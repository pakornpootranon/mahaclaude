"""Tests for newswatch_worker.polymarket.match against real local Postgres.
Pure token-overlap logic — no LLM calls involved."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest

from newswatch_worker.polymarket import match

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")


@pytest.fixture
def env():
    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    marker = uuid.uuid4().hex[:8]
    sources_t = table("sources")
    cycles_t = table("cycles")

    with engine.begin() as conn:
        source_id = conn.execute(
            sources_t.insert()
            .values(name=f"test-match-src-{marker}", source_type="rss", config={"url": "http://example.com/feed"}, enabled=False)
            .returning(sources_t.c.id)
        ).scalar_one()
        cycle_id = conn.execute(
            cycles_t.insert()
            .values(scheduled_for=datetime.now(timezone.utc), kind="manual", state="PM_SCANNING", stats={})
            .returning(cycles_t.c.id)
        ).scalar_one()

    yield {"source_id": str(source_id), "cycle_id": str(cycle_id), "marker": marker}

    with engine.begin() as conn:
        conn.execute(table("pm_markets").delete().where(table("pm_markets").c.id.like(f"test-{marker}-%")))
        conn.execute(table("analyses").delete().where(table("analyses").c.cycle_id == cycle_id))
        conn.execute(table("news_items").delete().where(table("news_items").c.source_id == source_id))
        conn.execute(table("cycles").delete().where(table("cycles").c.id == cycle_id))
        conn.execute(table("sources").delete().where(table("sources").c.id == source_id))


def _insert_analysis(conn, *, cycle_id, source_id, story_key, title, sector="Energy producers"):
    from newswatch_worker.db import table

    news_items_t = table("news_items")
    analyses_t = table("analyses")

    item_id = conn.execute(
        news_items_t.insert()
        .values(
            source_id=source_id,
            dedupe_key=uuid.uuid4().hex,
            url=f"https://example.com/{uuid.uuid4().hex}",
            title=title,
            summary=title,
            triage_status="relevant",
            story_key=story_key,
            matched_topic_ids=[],
        )
        .returning(news_items_t.c.id)
    ).scalar_one()

    analysis_id = conn.execute(
        analyses_t.insert()
        .values(
            cycle_id=cycle_id,
            story_key=story_key,
            primary_item_id=item_id,
            prompt_version="analyze-v1",
            model="test",
            result={"reasoning": "test", "impacts": [{"market": "US", "sector": sector, "direction": "bullish"}]},
            event_polarity=1,
            magnitude=0.6,
            confidence=0.7,
        )
        .returning(analyses_t.c.id)
    ).scalar_one()
    return str(item_id), str(analysis_id)


def _insert_market(conn, *, marker, suffix, question, category="Economy", active=True, resolved=False):
    from newswatch_worker.db import table

    pm_markets_t = table("pm_markets")
    market_id = f"test-{marker}-{suffix}"
    conn.execute(
        pm_markets_t.insert().values(
            id=market_id, question=question, slug=market_id, category=category, active=active, resolved=resolved
        )
    )
    return market_id


def test_match_storylines_to_markets_matches_on_token_overlap(env):
    from newswatch_worker.db import get_engine

    engine = get_engine()
    marker = env["marker"]
    with engine.begin() as conn:
        _, analysis_id = _insert_analysis(
            conn,
            cycle_id=env["cycle_id"],
            source_id=env["source_id"],
            story_key="hormuz-tension",
            title="Tensions rise near Strait of Hormuz after tanker incident",
            sector="Energy producers",
        )
        matching_market = _insert_market(
            conn, marker=marker, suffix="oil", question="Will Brent crude close above $95/barrel amid Hormuz tensions?"
        )
        unrelated_market = _insert_market(
            conn, marker=marker, suffix="unrelated", question="Will the incumbent win the mayoral election?"
        )

        candidates = match.match_storylines_to_markets(conn, cycle_id=env["cycle_id"])

    by_market = {c.market_id: c for c in candidates}
    assert matching_market in by_market
    assert analysis_id in by_market[matching_market].analysis_ids
    assert unrelated_market not in by_market


def test_match_storylines_to_markets_excludes_resolved_markets(env):
    from newswatch_worker.db import get_engine

    engine = get_engine()
    marker = env["marker"]
    with engine.begin() as conn:
        _insert_analysis(
            conn,
            cycle_id=env["cycle_id"],
            source_id=env["source_id"],
            story_key="hormuz-tension-2",
            title="Tensions rise near Strait of Hormuz after tanker incident",
        )
        resolved_market = _insert_market(
            conn,
            marker=marker,
            suffix="resolved",
            question="Will Brent crude close above $95/barrel amid Hormuz tensions?",
            resolved=True,
        )

        candidates = match.match_storylines_to_markets(conn, cycle_id=env["cycle_id"])

    assert all(c.market_id != resolved_market for c in candidates)


def test_match_storylines_to_markets_returns_empty_without_analyses(env):
    from newswatch_worker.db import get_engine

    engine = get_engine()
    with engine.begin() as conn:
        candidates = match.match_storylines_to_markets(conn, cycle_id=env["cycle_id"])

    assert candidates == []
