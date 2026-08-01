"""Tier 3 — Digest synthesis (docs/04-llm-pipeline.md §7).

The spec gives the exact output schema and "prompt instruction highlights"
for this tier but, unlike triage/analysis/pm-estimate, no verbatim system
prompt text. DIGEST_SYSTEM_PROMPT below is written to satisfy those
highlights (mention triggered actions explicitly; note big non-triggers and
why) — documented here since it's authored, not transcribed.

`market_mood`'s value set isn't enumerated in the spec either (only the
example "mixed"). Constrained to a small fixed set (bullish/bearish/mixed/
cautious/quiet) so Phase 4's dashboard has a stable badge vocabulary to
render against, rather than an open-ended string.
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from newswatch_worker.db import table
from newswatch_worker.llm import client
from newswatch_worker.llm.analyze import select_storylines

logger = logging.getLogger(__name__)

PROMPT_VERSION = "digest-v1"

DIGEST_SYSTEM_PROMPT = """You are writing the end-of-cycle digest for a personal financial news
monitoring dashboard (NOT financial advice; nothing is executed automatically).

Summarize this cycle's news-monitoring run for the user:
- market_mood: one word for the overall tone of this cycle's flagged news - one of
  'bullish', 'bearish', 'mixed', 'cautious', 'quiet' (little happened).
- synthesis: one paragraph, <=120 words, plain language. Mention any triggered BUY/SELL/WATCH
  actions explicitly by ticker or sector. Also note anything notable that did NOT trigger a
  recommendation and why (e.g. below the confidence floor), so the user stays aware of
  borderline calls.
- top_themes: the biggest storylines this cycle (3-6), each with a one-line "why" and an
  item_count (how many news items covered it, from the context given).

Output JSON only."""


class Theme(BaseModel):
    theme: str
    why: str
    item_count: int


class DigestResult(BaseModel):
    market_mood: Literal["bullish", "bearish", "mixed", "cautious", "quiet"]
    synthesis: str
    top_themes: list[Theme] = Field(default_factory=list)


def _load_recommendations(conn: Connection, cycle_id: str) -> list:
    recommendations_t = table("recommendations")
    return conn.execute(
        select(
            recommendations_t.c.action,
            recommendations_t.c.market,
            recommendations_t.c.sector,
            recommendations_t.c.tickers,
            recommendations_t.c.confidence,
            recommendations_t.c.reasoning,
        )
        .where(recommendations_t.c.cycle_id == cycle_id)
        .order_by(recommendations_t.c.confidence.desc())
    ).all()


def _load_storyline_summaries(conn: Connection, cycle_id: str) -> list:
    analyses_t = table("analyses")
    analysis_topics_t = table("analysis_topics")
    topics_t = table("topics")
    recommendations_t = table("recommendations")

    analysis_rows = conn.execute(
        select(
            analyses_t.c.id,
            analyses_t.c.story_key,
            analyses_t.c.magnitude,
            analyses_t.c.confidence,
            analyses_t.c.event_polarity,
            analyses_t.c.result,
        ).where(analyses_t.c.cycle_id == cycle_id)
    ).all()
    if not analysis_rows:
        return []

    analysis_ids = [row.id for row in analysis_rows]

    topic_rows = conn.execute(
        select(analysis_topics_t.c.analysis_id, topics_t.c.name)
        .select_from(analysis_topics_t.outerjoin(topics_t, topics_t.c.id == analysis_topics_t.c.topic_id))
        .where(analysis_topics_t.c.analysis_id.in_(analysis_ids))
    ).all()
    topics_by_analysis: dict = {}
    for row in topic_rows:
        topics_by_analysis.setdefault(row.analysis_id, []).append(row.name or "unconfigured but significant")

    triggered_ids = {
        row.analysis_id
        for row in conn.execute(
            select(recommendations_t.c.analysis_id).where(recommendations_t.c.analysis_id.in_(analysis_ids))
        ).all()
    }

    summaries = []
    for row in analysis_rows:
        summaries.append(
            {
                "story_key": row.story_key,
                "topics": topics_by_analysis.get(row.id, []),
                "magnitude": float(row.magnitude),
                "confidence": float(row.confidence),
                "event_polarity": row.event_polarity,
                "horizon": (row.result or {}).get("horizon", "unknown"),
                "triggered": row.id in triggered_ids,
            }
        )
    return summaries


def render_digest_input(cycle_stats: dict, recommendations: list, storylines: list) -> str:
    lines = [f"## Cycle stats\n{cycle_stats}", "", "## Triggered recommendations this cycle"]
    if recommendations:
        for r in recommendations:
            tickers = ",".join(r.tickers) if r.tickers else "(sector-only)"
            lines.append(f"- {r.action} {r.market}/{r.sector} [{tickers}] confidence={r.confidence} - {r.reasoning}")
    else:
        lines.append("(none triggered this cycle)")

    lines.append("")
    lines.append("## Storylines analyzed this cycle (triggered and not)")
    if storylines:
        for s in storylines:
            status = "TRIGGERED" if s["triggered"] else "not triggered"
            topics = ", ".join(s["topics"]) if s["topics"] else "unconfigured but significant"
            lines.append(
                f"- [{status}] {topics}: magnitude={s['magnitude']:.2f} confidence={s['confidence']:.2f} "
                f"polarity={s['event_polarity']} horizon={s['horizon']}"
            )
    else:
        lines.append("(no storylines analyzed this cycle)")

    return "\n".join(lines)


def _degraded_digest(conn: Connection, *, cycle_id: str) -> DigestResult:
    """docs/04 §7 budget-hit path: no LLM call. top_themes from topic-match
    counts; synthesis is a templated banner naming how many storylines
    never got analyzed."""
    analyses_t = table("analyses")
    analysis_topics_t = table("analysis_topics")
    topics_t = table("topics")

    rows = conn.execute(
        select(func.coalesce(topics_t.c.name, "Unconfigured but significant").label("theme"), func.count().label("cnt"))
        .select_from(
            analyses_t.join(analysis_topics_t, analysis_topics_t.c.analysis_id == analyses_t.c.id).outerjoin(
                topics_t, topics_t.c.id == analysis_topics_t.c.topic_id
            )
        )
        .where(analyses_t.c.cycle_id == cycle_id)
        .group_by(topics_t.c.name)
    ).all()

    unanalyzed_count = len(select_storylines(conn))
    top_themes = [Theme(theme=row.theme, why="topic-match count (LLM budget reached this cycle)", item_count=row.cnt) for row in rows]

    return DigestResult(
        market_mood="mixed",
        synthesis=f"LLM budget reached; {unanalyzed_count} storylines unanalyzed.",
        top_themes=top_themes,
    )


def run_digest(conn: Connection, *, cycle_id: str, budget_hit: bool) -> dict:
    """Writes the cycle's digests row (docs/04 §7). Idempotent: digests.cycle_id
    is the primary key, ON CONFLICT DO NOTHING skips a re-run against an
    already-committed digest.
    """
    digests_t = table("digests")
    cycles_t = table("cycles")
    stats: dict = {"digest_degraded": budget_hit}

    if budget_hit:
        result = _degraded_digest(conn, cycle_id=cycle_id)
    else:
        llm_settings = client.get_llm_settings(conn)
        model, reasoning = llm_settings.tier("digest")

        cycle_stats = conn.execute(select(cycles_t.c.stats).where(cycles_t.c.id == cycle_id)).scalar_one()
        recommendations = _load_recommendations(conn, cycle_id)
        storylines = _load_storyline_summaries(conn, cycle_id)
        user_content = render_digest_input(cycle_stats, recommendations, storylines)

        call_result = client.call_structured(
            conn,
            cycle_id=cycle_id,
            purpose="digest",
            model=model,
            reasoning=reasoning,
            output_model=DigestResult,
            system=DIGEST_SYSTEM_PROMPT,
            user_content=user_content,
            temperature=0.3,
        )
        if call_result is None:
            logger.error("cycle=%s digest call failed after repair retry; falling back to degraded digest", cycle_id)
            result = _degraded_digest(conn, cycle_id=cycle_id)
            stats["digest_degraded"] = True
            stats["digest_llm_failed"] = True
        else:
            result = call_result.parsed

    conn.execute(
        pg_insert(digests_t)
        .values(
            cycle_id=cycle_id,
            market_mood=result.market_mood,
            synthesis=result.synthesis,
            top_themes=[t.model_dump() for t in result.top_themes],
        )
        .on_conflict_do_nothing(index_elements=["cycle_id"])
    )
    return stats
