"""News-driven storyline -> Polymarket market matching (docs/04-llm-pipeline.md
§9, match.py): "for each storyline analyzed this cycle, keyword/entity match
against active pm_markets questions (token overlap + category heuristics)".

Matches against the `pm_markets` DB table (the snapshot scan.py refreshes
each cycle via the Gamma client), per the spec's own wording — not a live
API call. Scoring thresholds are authored (the spec names the technique,
not exact numbers): documented here since they're a judgment call, not
transcribed from the spec.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.engine import Connection

from newswatch_worker.db import table

MIN_OVERLAP_TOKENS = 2
MIN_OVERLAP_RATIO = 0.12

_STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "will", "is", "are",
    "be", "by", "at", "with", "from", "this", "that", "as", "its", "after", "amid",
    "over", "under", "than", "into", "about", "would", "could", "has", "have", "had",
}


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


@dataclass(frozen=True)
class StorylineContext:
    analysis_id: str
    story_key: str
    tokens: frozenset[str]
    topic_keywords: frozenset[str]


@dataclass(frozen=True)
class MatchCandidate:
    market_id: str
    analysis_ids: list[str]
    score: float


def load_cycle_storylines(conn: Connection, *, cycle_id: str) -> list[StorylineContext]:
    analyses_t = table("analyses")
    analysis_topics_t = table("analysis_topics")
    topics_t = table("topics")
    news_items_t = table("news_items")

    rows = conn.execute(
        select(analyses_t.c.id, analyses_t.c.story_key, analyses_t.c.primary_item_id, analyses_t.c.result).where(
            analyses_t.c.cycle_id == cycle_id
        )
    ).all()
    if not rows:
        return []

    item_ids = [r.primary_item_id for r in rows]
    items_by_id = {
        str(r.id): r
        for r in conn.execute(
            select(news_items_t.c.id, news_items_t.c.title, news_items_t.c.summary).where(
                news_items_t.c.id.in_(item_ids)
            )
        ).all()
    }

    analysis_ids = [r.id for r in rows]
    topic_rows = conn.execute(
        select(analysis_topics_t.c.analysis_id, topics_t.c.name, topics_t.c.keywords)
        .select_from(analysis_topics_t.outerjoin(topics_t, topics_t.c.id == analysis_topics_t.c.topic_id))
        .where(analysis_topics_t.c.analysis_id.in_(analysis_ids))
    ).all()
    topics_by_analysis: dict = {}
    for r in topic_rows:
        topics_by_analysis.setdefault(r.analysis_id, []).append(r)

    contexts = []
    for row in rows:
        item = items_by_id.get(str(row.primary_item_id))
        title = item.title if item else ""
        summary = (item.summary if item else "") or ""
        topic_names: list[str] = []
        topic_keywords: set[str] = set()
        for tr in topics_by_analysis.get(row.id, []):
            if tr.name:
                topic_names.append(tr.name)
            topic_keywords.update(tr.keywords or [])
        sectors = [impact.get("sector", "") for impact in (row.result or {}).get("impacts", [])]
        text = " ".join([title, summary, *topic_names, *sectors])
        contexts.append(
            StorylineContext(
                analysis_id=str(row.id),
                story_key=row.story_key,
                tokens=frozenset(_tokenize(text)),
                topic_keywords=frozenset(k.lower() for k in topic_keywords),
            )
        )
    return contexts


def load_active_markets(conn: Connection) -> list:
    pm_markets_t = table("pm_markets")
    return conn.execute(
        select(
            pm_markets_t.c.id,
            pm_markets_t.c.question,
            pm_markets_t.c.category,
        )
        .where(pm_markets_t.c.active.is_(True))
        .where(pm_markets_t.c.resolved.is_(False))
    ).all()


def match_storylines_to_markets(conn: Connection, *, cycle_id: str) -> list[MatchCandidate]:
    storylines = load_cycle_storylines(conn, cycle_id=cycle_id)
    if not storylines:
        return []
    markets = load_active_markets(conn)
    if not markets:
        return []

    matches_by_market: dict[str, list[tuple[str, float]]] = {}
    for market in markets:
        market_tokens = frozenset(_tokenize(f"{market.question} {market.category or ''}"))
        if not market_tokens:
            continue
        for storyline in storylines:
            if not storyline.tokens:
                continue
            overlap = storyline.tokens & market_tokens
            if not overlap:
                continue
            ratio = len(overlap) / min(len(storyline.tokens), len(market_tokens))
            if len(overlap) < MIN_OVERLAP_TOKENS and ratio < MIN_OVERLAP_RATIO:
                continue
            category_boost = 0.5 if market.category and market.category.lower() in storyline.topic_keywords else 0.0
            score = len(overlap) + category_boost
            matches_by_market.setdefault(str(market.id), []).append((storyline.analysis_id, score))

    candidates = []
    for market_id, pairs in matches_by_market.items():
        analysis_ids = sorted({a for a, _ in pairs})
        score = max(s for _, s in pairs)
        candidates.append(MatchCandidate(market_id=market_id, analysis_ids=analysis_ids, score=score))
    return candidates
