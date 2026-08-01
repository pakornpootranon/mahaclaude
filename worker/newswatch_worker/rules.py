"""Deterministic rules engine (docs/04-llm-pipeline.md §6): analysis ->
recommendation. NOT the LLM — this is the one place a trigger decision gets
made, and every decision (pass or fail) is captured in a `rule_trace`.

Two spec gaps resolved here (documented inline where they bite):

1. Impact rows in `AnalysisResult.impacts` (docs/04 §5.2) carry no topic_id,
   so "trigger iff ... topic.enabled ... mapping row for (topic, market,
   sector)" (docs/04 §6) is evaluated per (matched_topic x impact) pair,
   looking up the mapping row keyed on (topic_id, market, sector) — the
   same key mappings are unique on (docs/03 §2.5).
2. `unmapped_sectors` (docs/04 §5.2) carries no `market` field, but
   `recommendations.market` is NOT NULL (docs/03 §2.7). The "unconfigured
   but significant" WATCH branch (docs/04 §6) defaults market to 'GLOBAL'
   for these — the least wrong default given docs/02 §2's "GLOBAL (map to
   US/TH tradable proxies)".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from newswatch_worker.db import table
from newswatch_worker.dedupe import recommendation_dedupe_key

logger = logging.getLogger(__name__)


@dataclass
class Candidate:
    analysis_id: str
    topic_id: str | None
    market: str
    sector: str
    tickers: list[str]
    action: str
    confidence: float
    effective_confidence: float
    reasoning: str
    rule_trace: dict = field(default_factory=dict)
    passed_individual_checks: bool = False


@dataclass(frozen=True)
class _Topic:
    id: str
    enabled: bool
    sensitivity: float


@dataclass(frozen=True)
class _Mapping:
    enabled: bool
    tickers: list[str]


def _load_rules_settings(conn: Connection) -> dict:
    settings_t = table("settings")
    row = conn.execute(select(settings_t.c.value).where(settings_t.c.key == "rules")).first()
    if row is None:
        raise RuntimeError("settings['rules'] is not seeded")
    return row[0]


def _load_all_topics(conn: Connection) -> dict[str, _Topic]:
    topics_t = table("topics")
    rows = conn.execute(select(topics_t.c.id, topics_t.c.enabled, topics_t.c.sensitivity)).all()
    return {str(r.id): _Topic(id=str(r.id), enabled=r.enabled, sensitivity=float(r.sensitivity)) for r in rows}


def _load_all_mappings(conn: Connection) -> dict[tuple[str, str, str], _Mapping]:
    mappings_t = table("mappings")
    rows = conn.execute(
        select(mappings_t.c.topic_id, mappings_t.c.market, mappings_t.c.sector, mappings_t.c.enabled, mappings_t.c.tickers)
    ).all()
    return {
        (str(r.topic_id), r.market, r.sector): _Mapping(enabled=r.enabled, tickers=list(r.tickers or []))
        for r in rows
    }


def _load_cycle_analyses(conn: Connection, cycle_id: str) -> list[tuple]:
    analyses_t = table("analyses")
    analysis_topics_t = table("analysis_topics")

    rows = conn.execute(
        select(analyses_t.c.id, analyses_t.c.magnitude, analyses_t.c.confidence, analyses_t.c.result).where(
            analyses_t.c.cycle_id == cycle_id
        )
    ).all()
    if not rows:
        return []

    analysis_ids = [r.id for r in rows]
    topic_rows = conn.execute(
        select(analysis_topics_t.c.analysis_id, analysis_topics_t.c.topic_id, analysis_topics_t.c.match_strength).where(
            analysis_topics_t.c.analysis_id.in_(analysis_ids)
        )
    ).all()
    topics_by_analysis: dict = {}
    for r in topic_rows:
        topics_by_analysis.setdefault(r.analysis_id, []).append(r)

    return [(r, topics_by_analysis.get(r.id, [])) for r in rows]


def _sector_scope_pass(sector: str, scope: dict) -> bool:
    sector_lower = sector.lower()
    blocklist = {s.lower() for s in scope.get("blocklist", [])}
    if sector_lower in blocklist:
        return False
    allowlist = {s.lower() for s in scope.get("allowlist", [])}
    if allowlist and sector_lower not in allowlist:
        return False
    return True


def _evaluate_matched_impact(
    *,
    analysis_id: str,
    topic_id: str,
    impact: dict,
    magnitude: float,
    confidence: float,
    horizon: str | None,
    reasoning: str,
    topics_by_id: dict[str, _Topic],
    mappings_by_key: dict[tuple[str, str, str], _Mapping],
    rules_settings: dict,
) -> Candidate:
    market = impact["market"]
    sector = impact["sector"]
    direction = impact["direction"]
    strength = float(impact["strength"])
    tickers_in = list(impact.get("tickers", []))

    action = "BUY" if direction == "bullish" else "SELL"
    downgrade_reason = None
    if magnitude < rules_settings["watch_floor"]:
        downgrade_reason = "magnitude_below_watch_floor"
    elif horizon == "months":
        downgrade_reason = "horizon_months"
    if downgrade_reason:
        action = "WATCH"

    effective_confidence = confidence * strength

    topic = topics_by_id.get(topic_id)
    mapping = mappings_by_key.get((topic_id, market, sector))

    # Re-intersect with the mapping's CURRENT tickers (not just what
    # analyze.py stripped against at analysis time — the mapping could have
    # been edited since) before subtracting quiet_tickers. A ticker landing
    # here at all already survived analyze.py's hallucination strip, so this
    # is defense in depth, not the primary filter (FR-A4 provenance safety).
    valid_tickers = set(mapping.tickers) if mapping else set()
    tickers_after_mapping = [t for t in tickers_in if t in valid_tickers]
    quiet_set = set(rules_settings["quiet_tickers"])
    tickers_final = [t for t in tickers_after_mapping if t not in quiet_set]
    quiet_filtered = [t for t in tickers_after_mapping if t in quiet_set]

    topic_enabled = bool(topic and topic.enabled)
    mapping_enabled = bool(mapping and mapping.enabled)
    sector_scope_ok = _sector_scope_pass(sector, rules_settings["sector_scope"])
    confidence_floor = max(topic.sensitivity if topic else 0.0, rules_settings["global_confidence_floor"])
    confidence_ok = effective_confidence >= confidence_floor
    magnitude_ok = magnitude >= rules_settings["global_magnitude_floor"]

    passed = topic_enabled and mapping_enabled and sector_scope_ok and confidence_ok and magnitude_ok

    rule_trace = {
        "branch": "matched_topic",
        "topic_id": topic_id,
        "topic_enabled": {"pass": topic_enabled, "value": topic.enabled if topic else None},
        "mapping_enabled": {"pass": mapping_enabled, "value": mapping.enabled if mapping else None},
        "sector_scope": {"pass": sector_scope_ok, "sector": sector},
        "effective_confidence": {"pass": confidence_ok, "value": effective_confidence, "floor": confidence_floor},
        "magnitude_floor": {"pass": magnitude_ok, "value": magnitude, "floor": rules_settings["global_magnitude_floor"]},
        "quiet_tickers_filtered": quiet_filtered,
        "action_downgrade": {"downgraded_to_watch": bool(downgrade_reason), "reason": downgrade_reason},
    }

    return Candidate(
        analysis_id=analysis_id,
        topic_id=topic_id,
        market=market,
        sector=sector,
        tickers=tickers_final,
        action=action,
        confidence=effective_confidence,
        effective_confidence=effective_confidence,
        reasoning=reasoning,
        rule_trace=rule_trace,
        passed_individual_checks=passed,
    )


def _evaluate_unconfigured(
    *, analysis_id: str, unmapped: dict, magnitude: float, confidence: float, reasoning: str, rules_settings: dict
) -> Candidate:
    sector = unmapped["sector"]
    market = "GLOBAL"

    magnitude_ok = magnitude >= rules_settings["unconfigured_magnitude_floor"]
    sector_scope_ok = _sector_scope_pass(sector, rules_settings["sector_scope"])
    passed = magnitude_ok and sector_scope_ok

    rule_trace = {
        "branch": "unconfigured",
        "magnitude_floor": {"pass": magnitude_ok, "value": magnitude, "floor": rules_settings["unconfigured_magnitude_floor"]},
        "sector_scope": {"pass": sector_scope_ok, "sector": sector},
        "market_default_note": "unmapped_sectors has no market field (docs/04 §5.2 gap); defaulted to GLOBAL",
    }

    return Candidate(
        analysis_id=analysis_id,
        topic_id=None,
        market=market,
        sector=sector,
        tickers=[],
        action="WATCH",
        confidence=confidence,
        effective_confidence=confidence,
        reasoning=unmapped.get("note") or reasoning,
        rule_trace=rule_trace,
        passed_individual_checks=passed,
    )


def build_candidates(conn: Connection, *, cycle_id: str, rules_settings: dict) -> list[Candidate]:
    topics_by_id = _load_all_topics(conn)
    mappings_by_key = _load_all_mappings(conn)
    analyses = _load_cycle_analyses(conn, cycle_id)

    candidates: list[Candidate] = []
    for analysis_row, topic_matches in analyses:
        magnitude = float(analysis_row.magnitude)
        confidence = float(analysis_row.confidence)
        result = analysis_row.result or {}
        horizon = result.get("horizon")
        reasoning = result.get("reasoning", "")

        matched_topic_ids = [str(tm.topic_id) for tm in topic_matches if tm.topic_id is not None]

        if matched_topic_ids:
            for topic_id in matched_topic_ids:
                for impact in result.get("impacts", []):
                    candidates.append(
                        _evaluate_matched_impact(
                            analysis_id=str(analysis_row.id),
                            topic_id=topic_id,
                            impact=impact,
                            magnitude=magnitude,
                            confidence=confidence,
                            horizon=horizon,
                            reasoning=reasoning,
                            topics_by_id=topics_by_id,
                            mappings_by_key=mappings_by_key,
                            rules_settings=rules_settings,
                        )
                    )
        else:
            for unmapped in result.get("unmapped_sectors", []):
                candidates.append(
                    _evaluate_unconfigured(
                        analysis_id=str(analysis_row.id),
                        unmapped=unmapped,
                        magnitude=magnitude,
                        confidence=confidence,
                        reasoning=reasoning,
                        rules_settings=rules_settings,
                    )
                )

    return candidates


def _link_recommendation_sources(conn: Connection, *, recommendation_id: str, analysis_id: str) -> None:
    """Full provenance (FR-A5): every news item clustered into this
    analysis's storyline, not just the up-to-5 the LLM actually read
    (analyze.py's primary + corroborating cap) — a complete audit trail is
    more useful here than mirroring the token-budget cap.
    """
    analyses_t = table("analyses")
    news_items_t = table("news_items")
    recommendation_sources_t = table("recommendation_sources")

    story_key = conn.execute(select(analyses_t.c.story_key).where(analyses_t.c.id == analysis_id)).scalar_one()
    item_ids = conn.execute(select(news_items_t.c.id).where(news_items_t.c.story_key == story_key)).all()
    for (item_id,) in item_ids:
        conn.execute(
            pg_insert(recommendation_sources_t)
            .values(recommendation_id=recommendation_id, news_item_id=item_id)
            .on_conflict_do_nothing(index_elements=["recommendation_id", "news_item_id"])
        )


def apply_rules(conn: Connection, *, cycle_id: str) -> dict:
    """Evaluates every analysis produced by this cycle, ranks passing
    candidates by effective_confidence, and inserts recommendations up to
    rules.max_recommendations_per_cycle — highest confidence first
    (docs/04 §6). Idempotent: dedupe_key is globally UNIQUE, and re-running
    against the same cycle re-derives the same candidate set deterministically.
    """
    rules_settings = _load_rules_settings(conn)
    candidates = build_candidates(conn, cycle_id=cycle_id, rules_settings=rules_settings)

    stats = {"rules_candidates": len(candidates), "rules_triggered": 0}

    passing = [c for c in candidates if c.passed_individual_checks]
    passing.sort(key=lambda c: c.effective_confidence, reverse=True)

    now = datetime.now(timezone.utc)
    window_bucket = int(now.timestamp() // 3600 // rules_settings["dedup_window_hours"])

    candidate_keys = [
        recommendation_dedupe_key(
            topic_id=c.topic_id, sector=c.sector, tickers=c.tickers, action=c.action, window_bucket=window_bucket
        )
        for c in passing
    ]

    recommendations_t = table("recommendations")
    existing_keys: set[str] = set()
    if candidate_keys:
        existing_keys = {
            row.dedupe_key
            for row in conn.execute(
                select(recommendations_t.c.dedupe_key).where(recommendations_t.c.dedupe_key.in_(candidate_keys))
            ).all()
        }

    seen_this_cycle: set[str] = set()
    cap = rules_settings["max_recommendations_per_cycle"]

    for candidate, dedupe_key_val in zip(passing, candidate_keys):
        trace = dict(candidate.rule_trace)
        is_dup = dedupe_key_val in existing_keys or dedupe_key_val in seen_this_cycle
        trace["dedup_window"] = {"pass": not is_dup, "dedupe_key": dedupe_key_val}
        under_cap = stats["rules_triggered"] < cap
        trace["max_recommendations_per_cycle"] = {
            "pass": under_cap,
            "rank": stats["rules_triggered"] + 1 if under_cap else None,
            "cap": cap,
        }

        if is_dup or not under_cap:
            continue

        seen_this_cycle.add(dedupe_key_val)
        insert_result = conn.execute(
            pg_insert(recommendations_t)
            .values(
                cycle_id=cycle_id,
                analysis_id=candidate.analysis_id,
                topic_id=candidate.topic_id,
                dedupe_key=dedupe_key_val,
                action=candidate.action,
                market=candidate.market,
                sector=candidate.sector,
                tickers=candidate.tickers,
                confidence=candidate.confidence,
                reasoning=candidate.reasoning,
                rule_trace=trace,
            )
            .on_conflict_do_nothing(index_elements=["dedupe_key"])
            .returning(recommendations_t.c.id)
        )
        row = insert_result.first()
        if row is None:
            continue

        stats["rules_triggered"] += 1
        _link_recommendation_sources(conn, recommendation_id=str(row.id), analysis_id=candidate.analysis_id)

    return stats
