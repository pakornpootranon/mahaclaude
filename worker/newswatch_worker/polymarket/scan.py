"""Top-active-markets sweep + deterministic edge rules (docs/04-llm-pipeline.md
§9) and the `PM_SCANNING` cycle-stage orchestrator (docs/02-architecture.md
§3). NOT the LLM for the edge decision — `pm_estimate.py` only produces a
probability estimate; every flag/no-flag decision here is deterministic and
captured in `rule_trace`, mirroring rules.py's own split of duties.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from newswatch_worker.db import table
from newswatch_worker.dedupe import pm_opportunity_dedupe_key
from newswatch_worker.llm import client, pm_estimate
from newswatch_worker.polymarket import match
from newswatch_worker.polymarket.client import GammaClient

logger = logging.getLogger(__name__)


@dataclass
class PmCandidate:
    market_id: str
    discovery: str
    analysis_ids: list[str]
    side: str
    market_price: float
    est_probability: float
    edge_points: float
    confidence: float
    reasoning: str
    model: str
    rule_trace: dict = field(default_factory=dict)
    passed_individual_checks: bool = False


def _load_pm_settings(conn: Connection) -> dict:
    settings_t = table("settings")
    row = conn.execute(select(settings_t.c.value).where(settings_t.c.key == "polymarket")).first()
    if row is None:
        raise RuntimeError("settings['polymarket'] is not seeded")
    return row[0]


def refresh_pm_markets(conn: Connection, gamma: GammaClient) -> int:
    """Upserts the active-market snapshot match.py and select_scan_candidates
    both read from. Deliberately excludes `last_estimated_at` from the
    UPDATE SET clause — that column is scan.py's own bookkeeping (see
    schema.prisma's PmMarket doc comment), not part of the live API
    response, and must survive a refresh untouched.

    `closed` (Gamma) maps to `resolved` (our schema) as the best available
    proxy: the Gamma API's exact field for a market's paid-out resolution
    outcome could not be confirmed against a live call from this sandbox
    (see client.py's module docstring), but "no longer accepting orders" is
    sufficient for our purposes — match.py/select_scan_candidates both
    exclude resolved=true markets from consideration either way.
    """
    markets = gamma.get_all_active_markets(cap=500)
    pm_markets_t = table("pm_markets")
    now = datetime.now(timezone.utc)
    for m in markets:
        values = {
            "question": m.question,
            "slug": m.slug,
            "category": m.category,
            "end_date": m.end_date,
            "yes_price": m.yes_price,
            "volume_24h_usd": m.volume_24h_usd,
            "liquidity_usd": m.liquidity_usd,
            "active": m.active,
            "resolved": m.closed,
            "resolution": m.resolution,
            "snapshot_at": now,
        }
        conn.execute(
            pg_insert(pm_markets_t)
            .values(id=m.id, **values)
            .on_conflict_do_update(index_elements=["id"], set_=values)
        )
    return len(markets)


def select_scan_candidates(conn: Connection, pm_settings: dict) -> list:
    pm_markets_t = table("pm_markets")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=pm_settings["reestimate_hours"])
    query = (
        select(
            pm_markets_t.c.id,
            pm_markets_t.c.question,
            pm_markets_t.c.category,
            pm_markets_t.c.yes_price,
            pm_markets_t.c.liquidity_usd,
            pm_markets_t.c.volume_24h_usd,
            pm_markets_t.c.end_date,
        )
        .where(pm_markets_t.c.active.is_(True))
        .where(pm_markets_t.c.resolved.is_(False))
        .where(or_(pm_markets_t.c.last_estimated_at.is_(None), pm_markets_t.c.last_estimated_at < cutoff))
    )
    categories = pm_settings.get("categories") or []
    if categories:
        query = query.where(pm_markets_t.c.category.in_(categories))
    query = query.order_by(pm_markets_t.c.volume_24h_usd.desc().nullslast()).limit(pm_settings["scan_top_n"])
    return conn.execute(query).all()


def _load_markets_by_id(conn: Connection, ids: list[str]) -> list:
    pm_markets_t = table("pm_markets")
    return conn.execute(
        select(
            pm_markets_t.c.id,
            pm_markets_t.c.question,
            pm_markets_t.c.category,
            pm_markets_t.c.yes_price,
            pm_markets_t.c.liquidity_usd,
            pm_markets_t.c.volume_24h_usd,
            pm_markets_t.c.end_date,
        ).where(pm_markets_t.c.id.in_(ids))
    ).all()


def _prefilter_reasons(row, pm_settings: dict) -> list[str]:
    """docs/04 §9: 'Pre-filter before any LLM call (code)' — a market
    failing any of these never gets an LLM call, so it never becomes a
    rule_trace-bearing candidate at all (mirrors triage's non-relevant-item
    silent skip)."""
    reasons = []
    if row.liquidity_usd is None or float(row.liquidity_usd) < pm_settings["min_liquidity_usd"]:
        reasons.append("liquidity_below_floor")
    if row.end_date is not None:
        days_to_end = (row.end_date - datetime.now(timezone.utc)).days
        if days_to_end < pm_settings["min_days_to_end"]:
            reasons.append("resolving_too_soon")
    if row.yes_price is None:
        reasons.append("no_yes_price")
    elif not (pm_settings["price_floor"] <= float(row.yes_price) <= pm_settings["price_ceiling"]):
        reasons.append("price_outside_range")
    return reasons


def _storyline_summaries(conn: Connection, analysis_ids: list[str]) -> list[str]:
    if not analysis_ids:
        return []
    analyses_t = table("analyses")
    rows = conn.execute(
        select(analyses_t.c.story_key, analyses_t.c.magnitude, analyses_t.c.confidence, analyses_t.c.result).where(
            analyses_t.c.id.in_(analysis_ids)
        )
    ).all()
    summaries = []
    for r in rows:
        reasoning = (r.result or {}).get("reasoning", "")
        summaries.append(
            f"{r.story_key}: {reasoning} (magnitude={float(r.magnitude):.2f}, confidence={float(r.confidence):.2f})"
        )
    return summaries


def _mark_market_estimated(conn: Connection, market_id: str) -> None:
    pm_markets_t = table("pm_markets")
    conn.execute(
        pm_markets_t.update()
        .where(pm_markets_t.c.id == market_id)
        .values(last_estimated_at=datetime.now(timezone.utc))
    )


def _edge_candidate(
    *,
    market_id: str,
    discovery: str,
    analysis_ids: list[str],
    market_price: float,
    liquidity_usd: float,
    estimate: pm_estimate.PmEstimate,
    model: str,
    pm_settings: dict,
) -> PmCandidate:
    """docs/04 §9 deterministic edge rules — NOT the LLM."""
    edge_points = abs(estimate.est_probability - market_price) * 100
    side = "YES" if estimate.est_probability > market_price else "NO"

    skip_ok = not estimate.skip
    edge_ok = edge_points >= pm_settings["min_edge_points"]
    confidence_ok = estimate.confidence >= pm_settings["min_confidence"]
    liquidity_ok = liquidity_usd >= pm_settings["min_liquidity_usd"]

    rule_trace = {
        "discovery": discovery,
        "skip": {"pass": skip_ok, "value": estimate.skip, "reason": estimate.skip_reason},
        "edge_points": {"pass": edge_ok, "value": edge_points, "floor": pm_settings["min_edge_points"]},
        "confidence": {"pass": confidence_ok, "value": estimate.confidence, "floor": pm_settings["min_confidence"]},
        "liquidity_usd": {"pass": liquidity_ok, "value": liquidity_usd, "floor": pm_settings["min_liquidity_usd"]},
    }
    passed = skip_ok and edge_ok and confidence_ok and liquidity_ok

    return PmCandidate(
        market_id=market_id,
        discovery=discovery,
        analysis_ids=analysis_ids,
        side=side,
        market_price=market_price,
        est_probability=estimate.est_probability,
        edge_points=edge_points,
        confidence=estimate.confidence,
        reasoning=estimate.reasoning,
        model=model,
        rule_trace=rule_trace,
        passed_individual_checks=passed,
    )


def _insert_opportunities(conn: Connection, *, cycle_id: str, candidates: list[PmCandidate], pm_settings: dict) -> int:
    """Ranks passing candidates by edge_points desc and applies dedup + cap
    in ranked order — mirrors rules.py's apply_rules exactly (docs/04 §9:
    'cycle PM flag count < max_opportunities_per_cycle, highest edge
    first')."""
    pm_opportunities_t = table("pm_opportunities")
    pm_opportunity_analyses_t = table("pm_opportunity_analyses")

    passing = [c for c in candidates if c.passed_individual_checks]
    passing.sort(key=lambda c: c.edge_points, reverse=True)

    now = datetime.now(timezone.utc)
    window_bucket = int(now.timestamp() // 3600 // pm_settings["dedup_window_hours"])

    dedupe_keys = [
        pm_opportunity_dedupe_key(market_id=c.market_id, side=c.side, window_bucket=window_bucket) for c in passing
    ]
    existing: set[str] = set()
    if dedupe_keys:
        existing = {
            row.dedupe_key
            for row in conn.execute(
                select(pm_opportunities_t.c.dedupe_key).where(pm_opportunities_t.c.dedupe_key.in_(dedupe_keys))
            ).all()
        }

    flagged = 0
    seen_this_cycle: set[str] = set()
    cap = pm_settings["max_opportunities_per_cycle"]

    for candidate, dedupe_key_val in zip(passing, dedupe_keys):
        trace = dict(candidate.rule_trace)
        is_dup = dedupe_key_val in existing or dedupe_key_val in seen_this_cycle
        trace["dedup_window"] = {"pass": not is_dup, "dedupe_key": dedupe_key_val}
        under_cap = flagged < cap
        trace["max_opportunities_per_cycle"] = {"pass": under_cap, "rank": flagged + 1 if under_cap else None, "cap": cap}

        if is_dup or not under_cap:
            continue
        seen_this_cycle.add(dedupe_key_val)

        insert_result = conn.execute(
            pg_insert(pm_opportunities_t)
            .values(
                cycle_id=cycle_id,
                market_id=candidate.market_id,
                dedupe_key=dedupe_key_val,
                discovery=candidate.discovery,
                side=candidate.side,
                market_price=candidate.market_price,
                est_probability=candidate.est_probability,
                edge_points=candidate.edge_points,
                confidence=candidate.confidence,
                reasoning=candidate.reasoning,
                rule_trace=trace,
                prompt_version=pm_estimate.PROMPT_VERSION,
                model=candidate.model,
            )
            .on_conflict_do_nothing(index_elements=["dedupe_key"])
            .returning(pm_opportunities_t.c.id)
        )
        row = insert_result.first()
        if row is None:
            continue
        flagged += 1

        for analysis_id in candidate.analysis_ids:
            conn.execute(
                pg_insert(pm_opportunity_analyses_t)
                .values(pm_opportunity_id=row.id, analysis_id=analysis_id)
                .on_conflict_do_nothing(index_elements=["pm_opportunity_id", "analysis_id"])
            )

    return flagged


def run_pm_scanning(conn: Connection, *, cycle_id: str) -> dict:
    """Entry point called from cycle.py's PM_SCANNING step. Idempotent in the
    same sense as rules.py: pm_opportunities.dedupe_key is globally UNIQUE,
    so a resumed/re-run cycle can't double-insert a row — though (documented
    limitation) a crash between an LLM call and the transaction commit could
    cause a re-run to re-bill that one market's estimate, the same
    at-least-once characteristic every other LLM-calling stage already has.
    """
    pm_settings = _load_pm_settings(conn)
    stats: dict = {
        "pm_markets_refreshed": 0,
        "pm_scan_candidates": 0,
        "pm_news_candidates": 0,
        "pm_prefiltered_out": 0,
        "pm_estimated": 0,
        "pm_estimate_failed": 0,
        "pm_opportunities_flagged": 0,
        "budget_hit": False,
    }

    gamma = GammaClient()
    try:
        stats["pm_markets_refreshed"] = refresh_pm_markets(conn, gamma)
    except Exception:
        logger.exception("cycle=%s polymarket market refresh failed; continuing with existing snapshot", cycle_id)

    scan_rows = select_scan_candidates(conn, pm_settings)
    news_matches = match.match_storylines_to_markets(conn, cycle_id=cycle_id)
    stats["pm_scan_candidates"] = len(scan_rows)
    stats["pm_news_candidates"] = len(news_matches)

    discovery_by_market: dict[str, str] = {str(r.id): "scan" for r in scan_rows}
    analysis_ids_by_market: dict[str, list[str]] = {str(r.id): [] for r in scan_rows}
    for m in news_matches:
        # News discovery takes priority when a market lands in both sets —
        # one LLM call per market per cycle either way (judgment call,
        # documented in match.py/scan.py module docstrings).
        discovery_by_market[m.market_id] = "news"
        analysis_ids_by_market[m.market_id] = m.analysis_ids

    all_ids = list(discovery_by_market.keys())
    if not all_ids:
        return stats

    market_rows = {str(r.id): r for r in _load_markets_by_id(conn, all_ids)}

    llm_settings = client.get_llm_settings(conn)
    model, reasoning = llm_settings.tier("pm_estimate")
    today = datetime.now(ZoneInfo("Asia/Bangkok")).strftime("%Y-%m-%d (%A)")

    candidates: list[PmCandidate] = []
    for market_id in all_ids:
        row = market_rows.get(market_id)
        if row is None:
            continue
        if _prefilter_reasons(row, pm_settings):
            stats["pm_prefiltered_out"] += 1
            continue

        analysis_ids = analysis_ids_by_market[market_id]
        storylines = _storyline_summaries(conn, analysis_ids)
        market_input = pm_estimate.MarketInput(
            market_id=market_id,
            question=row.question,
            market_price=float(row.yes_price),
            end_date=row.end_date.isoformat() if row.end_date else None,
            category=row.category,
        )

        try:
            call_result = pm_estimate.estimate_probability(
                conn,
                cycle_id=cycle_id,
                market=market_input,
                storylines=storylines,
                model=model,
                reasoning=reasoning,
                today=today,
            )
        except client.BudgetExceededError:
            stats["budget_hit"] = True
            logger.warning(
                "cycle=%s polymarket budget exhausted mid-scan; %d market(s) left unestimated",
                cycle_id,
                len(all_ids) - stats["pm_estimated"] - stats["pm_estimate_failed"] - stats["pm_prefiltered_out"],
            )
            break

        _mark_market_estimated(conn, market_id)

        if call_result is None:
            stats["pm_estimate_failed"] += 1
            logger.error("cycle=%s pm-estimate failed after repair retry for market_id=%s", cycle_id, market_id)
            continue
        stats["pm_estimated"] += 1

        candidates.append(
            _edge_candidate(
                market_id=market_id,
                discovery=discovery_by_market[market_id],
                analysis_ids=analysis_ids,
                market_price=float(row.yes_price),
                liquidity_usd=float(row.liquidity_usd or 0),
                estimate=call_result.parsed,
                model=call_result.model,
                pm_settings=pm_settings,
            )
        )

    stats["pm_opportunities_flagged"] = _insert_opportunities(
        conn, cycle_id=cycle_id, candidates=candidates, pm_settings=pm_settings
    )
    return stats
