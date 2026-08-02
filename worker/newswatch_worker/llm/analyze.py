"""Tier 2 — Analysis (docs/04-llm-pipeline.md §4-5): storyline selection +
deep per-storyline impact analysis. One call per storyline, not per item.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from newswatch_worker.db import table
from newswatch_worker.llm import client
from newswatch_worker.llm.watch_context import build_watch_context, short_id_map

logger = logging.getLogger(__name__)

PROMPT_VERSION = "analyze-v1"
MAX_CORROBORATING_ITEMS = 4

SYSTEM_PROMPT_TEMPLATE = """You are a market impact analyst for a personal advisory dashboard (NOT financial advice;
the user reviews everything manually). Analyze ONE news storyline and output structured JSON.

Rules:
- Ground every judgment in the provided text. Do not invent facts, numbers, or tickers.
- event_polarity: +1 if the event pushes the matched topic's framing "positive" direction,
  -1 if negative, 0 if unclear. (Each topic's mapping table defines what +1 means per sector;
  you only judge the EVENT direction relative to the topic, e.g. for "Oil supply shocks",
  a supply disruption = +1.)
- magnitude 0-1: how market-moving for the affected sectors. 0.2 = routine, 0.5 = notable,
  0.8 = major, 1.0 = historic. Most news is <=0.4.
- confidence 0-1: your confidence in the direction call, NOT in the news being true.
  Calibrate honestly: single-source rumors cap at 0.5; official announcements can reach 0.9+.
- impacts: use ONLY sectors/tickers present in the provided mapping rows. If a genuinely
  impacted sector has no mapping row, put it in unmapped_sectors instead with a note.
- horizon: 'days' | 'weeks' | 'months' - over what horizon the impact likely plays out.
- reasoning: 2-4 sentences, plain language, mention the mechanism (why this news moves
  these sectors). This text is shown to the user verbatim.

{watch_context}

## Mapping rows for matched topics
{mapping_rows}"""


class MatchedTopic(BaseModel):
    topic_id: str
    match_strength: float


class Impact(BaseModel):
    market: str
    sector: str
    direction: Literal["bullish", "bearish"]
    tickers: list[str] = Field(default_factory=list)
    strength: float


class UnmappedSector(BaseModel):
    sector: str
    note: str


class AnalysisResult(BaseModel):
    story_key: str
    matched_topics: list[MatchedTopic] = Field(default_factory=list)
    event_polarity: Literal[-1, 0, 1]
    magnitude: float
    confidence: float
    horizon: Literal["days", "weeks", "months"]
    impacts: list[Impact] = Field(default_factory=list)
    unmapped_sectors: list[UnmappedSector] = Field(default_factory=list)
    reasoning: str
    caveats: str = ""


@dataclass(frozen=True)
class Storyline:
    story_key: str
    primary_item_id: str
    news_item_ids: list[str]
    matched_topic_ids: frozenset[str]


def select_storylines(conn: Connection, *, prompt_version: str = PROMPT_VERSION) -> list[Storyline]:
    """Per story_key with >=1 relevant item: primary = longest body_excerpt,
    else earliest; up to 4 corroborating items (docs/04 §4). Excludes
    story_keys that already have a committed analysis at this prompt
    version, so a resumed ANALYZING step and a re-run cycle only ever
    process what's left (idempotent, crash-resumable).
    """
    news_items_t = table("news_items")
    analyses_t = table("analyses")

    already_analyzed = select(analyses_t.c.story_key).where(analyses_t.c.prompt_version == prompt_version)
    rows = conn.execute(
        select(
            news_items_t.c.id,
            news_items_t.c.story_key,
            news_items_t.c.body_excerpt,
            news_items_t.c.published_at,
            news_items_t.c.fetched_at,
            news_items_t.c.matched_topic_ids,
        )
        .where(news_items_t.c.triage_status == "relevant")
        .where(news_items_t.c.story_key.isnot(None))
        .where(news_items_t.c.story_key.notin_(already_analyzed))
    ).all()

    groups: dict[str, list] = {}
    for row in rows:
        groups.setdefault(row.story_key, []).append(row)

    storylines = []
    for story_key, items in groups.items():
        ordered = sorted(
            items,
            key=lambda r: (-len(r.body_excerpt or ""), r.published_at or r.fetched_at),
        )
        primary = ordered[0]
        corroborating = ordered[1 : 1 + MAX_CORROBORATING_ITEMS]
        matched_topic_ids: set[str] = set()
        for r in items:
            matched_topic_ids.update(r.matched_topic_ids or [])
        storylines.append(
            Storyline(
                story_key=story_key,
                primary_item_id=str(primary.id),
                news_item_ids=[str(primary.id)] + [str(r.id) for r in corroborating],
                matched_topic_ids=frozenset(matched_topic_ids),
            )
        )
    return storylines


def load_mapping_rows_for_topics(conn: Connection, topic_ids: frozenset[str]) -> dict[str, list]:
    """Only enabled mapping rows: a disabled mapping means the user has
    temporarily turned off tracking for that (topic, market, sector) row,
    which we treat as "don't even surface it as an impact candidate" rather
    than "surface it but never let it trigger" — docs/04 §5.1 is silent on
    this, so this is a judgment call documented here.
    """
    if not topic_ids:
        return {}
    topics_t = table("topics")
    mappings_t = table("mappings")
    rows = conn.execute(
        select(
            topics_t.c.name.label("topic_name"),
            mappings_t.c.market,
            mappings_t.c.sector,
            mappings_t.c.tickers,
            mappings_t.c.polarity,
        )
        .select_from(mappings_t.join(topics_t, topics_t.c.id == mappings_t.c.topic_id))
        .where(mappings_t.c.topic_id.in_(topic_ids))
        .where(mappings_t.c.enabled.is_(True))
        .order_by(topics_t.c.name, mappings_t.c.market, mappings_t.c.sector)
    ).all()
    by_topic: dict[str, list] = {}
    for row in rows:
        by_topic.setdefault(row.topic_name, []).append(row)
    return by_topic


def render_mapping_rows(by_topic: dict[str, list]) -> str:
    if not by_topic:
        return "(no mapping rows for matched topics)"
    lines = []
    for topic_name, rows in by_topic.items():
        parts = []
        for r in rows:
            sign = "+1" if r.polarity > 0 else "-1"
            tickers = ",".join(r.tickers) if r.tickers else "(no tickers)"
            parts.append(f"[{r.market}/{r.sector} {sign}: {tickers}]")
        lines.append(f'topic="{topic_name}": {" ".join(parts)}')
    return "\n".join(lines)


def _valid_tickers_by_market_sector(by_topic: dict[str, list]) -> dict[tuple[str, str], set[str]]:
    result: dict[tuple[str, str], set[str]] = {}
    for rows in by_topic.values():
        for r in rows:
            result.setdefault((r.market, r.sector), set()).update(r.tickers or [])
    return result


def strip_hallucinated_tickers(analysis: AnalysisResult, by_topic: dict[str, list]) -> int:
    """docs/04 §8: 'Hallucinated ticker (not in mapping rows) | Code strips
    it; if impact row has no valid tickers left, becomes sector-only
    (FR-A4)'. Mutates analysis.impacts in place; returns count stripped.
    """
    valid = _valid_tickers_by_market_sector(by_topic)
    stripped = 0
    for impact in analysis.impacts:
        allowed = valid.get((impact.market, impact.sector), set())
        kept = [t for t in impact.tickers if t in allowed]
        stripped += len(impact.tickers) - len(kept)
        impact.tickers = kept
    return stripped


def render_storyline_input(storyline: Storyline, primary, corroborating: list) -> str:
    lines = [
        f"story_key: {storyline.story_key}",
        "",
        "## Primary item",
        f"title: {primary.title}",
        f"source: {primary.source_name}",
        f"published_at: {primary.published_at.isoformat() if primary.published_at else 'unknown'}",
        f"body: {primary.body_excerpt or primary.summary or ''}",
    ]
    if corroborating:
        lines.append("")
        lines.append("## Corroborating sources")
        for item in corroborating:
            lines.append(f"- {item.title} ({item.source_name})")
    return "\n".join(lines)


def _round_robin_by_topic(storylines: list[Storyline]) -> list[Storyline]:
    """Reorders storylines so the ANALYZING loop below visits every matched
    topic once before it revisits any topic a second time. `select_storylines`
    otherwise returns them in arbitrary DB scan order, so a topic that
    happens to produce many storylines this cycle (or that sorts first)
    could otherwise burn the whole per-cycle budget/item cap before every
    other watched topic gets even one analysis - the opposite of "each
    cycle works on all of them." Storylines matching zero topics
    ("unconfigured but significant" news, docs/03 §2.6) get their own
    shared bucket so that class of story stays fairly represented too.
    A storyline matching >1 topic is bucketed under its lowest topic_id
    (arbitrary but deterministic) - it's still analyzed exactly once
    either way; this only affects turn order, not coverage.
    """
    buckets: dict[str | None, list[Storyline]] = {}
    bucket_order: list[str | None] = []
    for storyline in storylines:
        key = min(storyline.matched_topic_ids) if storyline.matched_topic_ids else None
        if key not in buckets:
            buckets[key] = []
            bucket_order.append(key)
        buckets[key].append(storyline)

    ordered: list[Storyline] = []
    while any(buckets[key] for key in bucket_order):
        for key in bucket_order:
            if buckets[key]:
                ordered.append(buckets[key].pop(0))
    return ordered


def run_analysis(conn: Connection, *, cycle_id: str) -> dict:
    llm_settings = client.get_llm_settings(conn)
    # Reasoning here should sit above triage's: each call judges direction,
    # magnitude, and confidence for a single storyline from real prose, not
    # a mechanical classification - that's genuine per-story judgment worth
    # spending thinking budget on. Still bounded cost-wise because this
    # runs once per storyline (a handful per cycle), not once per raw item.
    model, reasoning = llm_settings.tier("analysis")

    watch_context, topics = build_watch_context(conn)
    id_map = short_id_map(topics)
    valid_topic_ids = {t.id for t in topics}

    storylines = _round_robin_by_topic(select_storylines(conn))
    stats = {
        "analysis_storylines": len(storylines),
        "analysis_succeeded": 0,
        "analysis_failed": 0,
        "analysis_tickers_stripped": 0,
        "budget_hit": False,
    }
    if not storylines:
        return stats

    news_items_t = table("news_items")
    sources_t = table("sources")
    analyses_t = table("analyses")
    analysis_topics_t = table("analysis_topics")

    for storyline in storylines:
        item_rows = conn.execute(
            select(
                news_items_t.c.id,
                news_items_t.c.title,
                news_items_t.c.summary,
                news_items_t.c.body_excerpt,
                news_items_t.c.published_at,
                sources_t.c.name.label("source_name"),
            )
            .select_from(news_items_t.join(sources_t, sources_t.c.id == news_items_t.c.source_id))
            .where(news_items_t.c.id.in_(storyline.news_item_ids))
        ).all()
        by_id = {str(r.id): r for r in item_rows}
        primary = by_id[storyline.primary_item_id]
        corroborating = [by_id[i] for i in storyline.news_item_ids[1:] if i in by_id]

        by_topic = load_mapping_rows_for_topics(conn, storyline.matched_topic_ids)
        system = SYSTEM_PROMPT_TEMPLATE.format(
            watch_context=watch_context, mapping_rows=render_mapping_rows(by_topic)
        )
        user_content = render_storyline_input(storyline, primary, corroborating)

        try:
            result = client.call_structured(
                conn,
                cycle_id=cycle_id,
                purpose="analysis",
                model=model,
                reasoning=reasoning,
                output_model=AnalysisResult,
                system=system,
                user_content=user_content,
                temperature=0.0,
            )
        except client.BudgetExceededError:
            # docs/04 §8 / docs/02 §8: stop LLM calls. Remaining storylines
            # have no `analyses` row yet, so select_storylines() naturally
            # re-offers them next cycle once budget resets — no explicit
            # "skipped" marking needed, unlike triage's news_items status.
            stats["budget_hit"] = True
            logger.warning(
                "cycle=%s budget exhausted mid-analysis; %d storylines left unanalyzed",
                cycle_id,
                stats["analysis_storylines"] - stats["analysis_succeeded"] - stats["analysis_failed"],
            )
            break

        if result is None:
            stats["analysis_failed"] += 1
            logger.error(
                "cycle=%s analysis failed after repair retry for story_key=%s", cycle_id, storyline.story_key
            )
            continue

        analysis = result.parsed
        stats["analysis_tickers_stripped"] += strip_hallucinated_tickers(analysis, by_topic)

        insert_result = conn.execute(
            pg_insert(analyses_t)
            .values(
                cycle_id=cycle_id,
                story_key=storyline.story_key,
                primary_item_id=storyline.primary_item_id,
                prompt_version=PROMPT_VERSION,
                model=result.model,
                result=analysis.model_dump(mode="json"),
                event_polarity=analysis.event_polarity,
                magnitude=analysis.magnitude,
                confidence=analysis.confidence,
            )
            .on_conflict_do_nothing(index_elements=["story_key", "prompt_version"])
            .returning(analyses_t.c.id)
        )
        row = insert_result.first()
        if row is None:
            continue
        analysis_id = str(row.id)

        matched = [mt for mt in analysis.matched_topics if id_map.get(mt.topic_id) in valid_topic_ids]
        if matched:
            for mt in matched:
                conn.execute(
                    pg_insert(analysis_topics_t)
                    .values(analysis_id=analysis_id, topic_id=id_map[mt.topic_id], match_strength=mt.match_strength)
                    .on_conflict_do_nothing(index_elements=["analysis_id", "topic_id"])
                )
        else:
            # "unconfigured but significant" flag (docs/03 §2.6): no topic
            # matched, NULL topic_id. match_strength has no natural analog
            # here (there's no topic to measure strength against), so we
            # store the analysis's own confidence as the closest signal.
            conn.execute(
                pg_insert(analysis_topics_t)
                .values(analysis_id=analysis_id, topic_id=None, match_strength=analysis.confidence)
                .on_conflict_do_nothing(index_elements=["analysis_id", "topic_id"])
            )

        stats["analysis_succeeded"] += 1

    return stats
