"""Unit/integration tests for newswatch_worker.rules against real local
Postgres. No LLM calls involved — analyses/analysis_topics rows are
inserted directly, exercising rules.py exactly as docs/04-llm-pipeline.md §6
specifies it: pure deterministic code operating on already-stored analysis
results.
"""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from newswatch_worker import rules

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")


@contextmanager
def _override_rules_settings(conn, **overrides):
    from newswatch_worker.db import table

    settings_t = table("settings")
    original = conn.execute(select(settings_t.c.value).where(settings_t.c.key == "rules")).scalar_one()
    patched = dict(original)
    patched.update(overrides)
    conn.execute(settings_t.update().where(settings_t.c.key == "rules").values(value=patched))
    try:
        yield
    finally:
        conn.execute(settings_t.update().where(settings_t.c.key == "rules").values(value=original))


@pytest.fixture
def env():
    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    marker = uuid.uuid4().hex[:8]
    sources_t = table("sources")
    topics_t = table("topics")
    mappings_t = table("mappings")
    cycles_t = table("cycles")

    with engine.begin() as conn:
        source_id = conn.execute(
            sources_t.insert()
            .values(name=f"test-rules-src-{marker}", source_type="rss", config={"url": "http://example.com/feed"}, enabled=False)
            .returning(sources_t.c.id)
        ).scalar_one()
        topic_id = conn.execute(
            topics_t.insert()
            .values(name=f"test-rules-topic-{marker}", description="test topic", keywords=[], sensitivity=0.5, enabled=True)
            .returning(topics_t.c.id)
        ).scalar_one()
        conn.execute(
            mappings_t.insert().values(topic_id=topic_id, market="US", sector="Energy", tickers=["XLE", "CVX"], polarity=1, enabled=True)
        )
        conn.execute(
            mappings_t.insert().values(topic_id=topic_id, market="US", sector="Airlines", tickers=["JETS"], polarity=-1, enabled=True)
        )
        cycle_id = conn.execute(
            cycles_t.insert()
            .values(scheduled_for=datetime.now(timezone.utc), kind="manual", state="TRIGGERING", stats={})
            .returning(cycles_t.c.id)
        ).scalar_one()

    yield {"source_id": str(source_id), "topic_id": str(topic_id), "cycle_id": str(cycle_id), "marker": marker}

    with engine.begin() as conn:
        conn.execute(table("recommendations").delete().where(table("recommendations").c.cycle_id == cycle_id))
        conn.execute(table("analyses").delete().where(table("analyses").c.cycle_id == cycle_id))
        conn.execute(table("news_items").delete().where(table("news_items").c.source_id == source_id))
        conn.execute(table("cycles").delete().where(table("cycles").c.id == cycle_id))
        conn.execute(table("topics").delete().where(table("topics").c.id == topic_id))
        conn.execute(table("sources").delete().where(table("sources").c.id == source_id))


def _insert_news_item(conn, *, source_id: str, story_key: str, title: str = "test item") -> str:
    from newswatch_worker.db import table

    news_items_t = table("news_items")
    url = f"https://example.com/{uuid.uuid4().hex}"
    return str(
        conn.execute(
            news_items_t.insert()
            .values(
                source_id=source_id,
                dedupe_key=uuid.uuid4().hex,
                story_key=story_key,
                url=url,
                title=title,
                triage_status="relevant",
            )
            .returning(news_items_t.c.id)
        ).scalar_one()
    )


def _insert_analysis(
    conn,
    *,
    cycle_id: str,
    source_id: str,
    topic_id: str | None,
    magnitude: float,
    confidence: float,
    impacts: list[dict] | None = None,
    unmapped_sectors: list[dict] | None = None,
    horizon: str = "weeks",
    story_key: str | None = None,
    match_strength: float | None = None,
) -> tuple[str, str]:
    from newswatch_worker.db import table

    analyses_t = table("analyses")
    analysis_topics_t = table("analysis_topics")

    story_key = story_key or f"test-story-{uuid.uuid4().hex[:8]}"
    primary_item_id = _insert_news_item(conn, source_id=source_id, story_key=story_key)

    result = {
        "story_key": story_key,
        "event_polarity": 1,
        "magnitude": magnitude,
        "confidence": confidence,
        "horizon": horizon,
        "impacts": impacts or [],
        "unmapped_sectors": unmapped_sectors or [],
        "reasoning": "test reasoning",
        "caveats": "",
    }
    analysis_id = str(
        conn.execute(
            analyses_t.insert()
            .values(
                cycle_id=cycle_id,
                story_key=story_key,
                primary_item_id=primary_item_id,
                prompt_version="analyze-v1",
                model="test-model",
                result=result,
                event_polarity=1,
                magnitude=magnitude,
                confidence=confidence,
            )
            .returning(analyses_t.c.id)
        ).scalar_one()
    )
    conn.execute(
        analysis_topics_t.insert().values(
            analysis_id=analysis_id,
            topic_id=topic_id,
            match_strength=match_strength if match_strength is not None else confidence,
        )
    )
    return analysis_id, primary_item_id


def _recommendations_for_cycle(conn, cycle_id: str) -> list:
    from newswatch_worker.db import table

    recommendations_t = table("recommendations")
    return conn.execute(select(recommendations_t).where(recommendations_t.c.cycle_id == cycle_id)).all()


def test_bullish_impact_triggers_buy(env):
    from newswatch_worker.db import get_engine

    engine = get_engine()
    with engine.begin() as conn:
        _insert_analysis(
            conn,
            cycle_id=env["cycle_id"],
            source_id=env["source_id"],
            topic_id=env["topic_id"],
            magnitude=0.6,
            confidence=0.9,
            impacts=[{"market": "US", "sector": "Energy", "direction": "bullish", "tickers": ["XLE", "CVX"], "strength": 0.8}],
        )
        stats = rules.apply_rules(conn, cycle_id=env["cycle_id"])
        recs = _recommendations_for_cycle(conn, env["cycle_id"])

    assert stats["rules_triggered"] == 1
    assert len(recs) == 1
    assert recs[0].action == "BUY"
    assert sorted(recs[0].tickers) == ["CVX", "XLE"]
    assert recs[0].sector == "Energy"
    trace = recs[0].rule_trace
    assert trace["topic_enabled"]["pass"] is True
    assert trace["mapping_enabled"]["pass"] is True
    assert trace["dedup_window"]["pass"] is True
    assert trace["max_recommendations_per_cycle"]["pass"] is True


def test_downgraded_to_watch_by_low_magnitude(env):
    from newswatch_worker.db import get_engine

    engine = get_engine()
    with engine.begin() as conn:
        _insert_analysis(
            conn,
            cycle_id=env["cycle_id"],
            source_id=env["source_id"],
            topic_id=env["topic_id"],
            magnitude=0.4,  # >= global_magnitude_floor 0.35, < watch_floor 0.45
            confidence=0.9,
            impacts=[{"market": "US", "sector": "Airlines", "direction": "bearish", "tickers": ["JETS"], "strength": 0.9}],
        )
        rules.apply_rules(conn, cycle_id=env["cycle_id"])
        recs = _recommendations_for_cycle(conn, env["cycle_id"])

    assert len(recs) == 1
    assert recs[0].action == "WATCH"
    assert recs[0].rule_trace["action_downgrade"]["reason"] == "magnitude_below_watch_floor"


def test_downgraded_to_watch_by_months_horizon(env):
    from newswatch_worker.db import get_engine

    engine = get_engine()
    with engine.begin() as conn:
        _insert_analysis(
            conn,
            cycle_id=env["cycle_id"],
            source_id=env["source_id"],
            topic_id=env["topic_id"],
            magnitude=0.8,
            confidence=0.9,
            horizon="months",
            impacts=[{"market": "US", "sector": "Energy", "direction": "bullish", "tickers": ["XLE"], "strength": 0.9}],
        )
        rules.apply_rules(conn, cycle_id=env["cycle_id"])
        recs = _recommendations_for_cycle(conn, env["cycle_id"])

    assert len(recs) == 1
    assert recs[0].action == "WATCH"
    assert recs[0].rule_trace["action_downgrade"]["reason"] == "horizon_months"


def test_disabled_topic_never_triggers(env):
    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(table("topics").update().where(table("topics").c.id == env["topic_id"]).values(enabled=False))
        _insert_analysis(
            conn,
            cycle_id=env["cycle_id"],
            source_id=env["source_id"],
            topic_id=env["topic_id"],
            magnitude=0.8,
            confidence=0.9,
            impacts=[{"market": "US", "sector": "Energy", "direction": "bullish", "tickers": ["XLE"], "strength": 0.9}],
        )
        stats = rules.apply_rules(conn, cycle_id=env["cycle_id"])
        recs = _recommendations_for_cycle(conn, env["cycle_id"])

    assert stats["rules_triggered"] == 0
    assert recs == []


def test_disabled_mapping_never_triggers(env):
    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    with engine.begin() as conn:
        mappings_t = table("mappings")
        conn.execute(
            mappings_t.update()
            .where(mappings_t.c.topic_id == env["topic_id"])
            .where(mappings_t.c.sector == "Energy")
            .values(enabled=False)
        )
        _insert_analysis(
            conn,
            cycle_id=env["cycle_id"],
            source_id=env["source_id"],
            topic_id=env["topic_id"],
            magnitude=0.8,
            confidence=0.9,
            impacts=[{"market": "US", "sector": "Energy", "direction": "bullish", "tickers": ["XLE"], "strength": 0.9}],
        )
        stats = rules.apply_rules(conn, cycle_id=env["cycle_id"])

    assert stats["rules_triggered"] == 0


def test_sector_scope_blocklist_wins_over_allowlist(env):
    from newswatch_worker.db import get_engine

    engine = get_engine()
    with engine.begin() as conn:
        with _override_rules_settings(conn, sector_scope={"allowlist": ["Energy"], "blocklist": ["Energy"]}):
            _insert_analysis(
                conn,
                cycle_id=env["cycle_id"],
                source_id=env["source_id"],
                topic_id=env["topic_id"],
                magnitude=0.8,
                confidence=0.9,
                impacts=[{"market": "US", "sector": "Energy", "direction": "bullish", "tickers": ["XLE"], "strength": 0.9}],
            )
            stats = rules.apply_rules(conn, cycle_id=env["cycle_id"])

    assert stats["rules_triggered"] == 0


def test_sector_scope_allowlist_restricts_to_listed_sectors(env):
    from newswatch_worker.db import get_engine

    engine = get_engine()
    with engine.begin() as conn:
        with _override_rules_settings(conn, sector_scope={"allowlist": ["Airlines"], "blocklist": []}):
            _insert_analysis(
                conn,
                cycle_id=env["cycle_id"],
                source_id=env["source_id"],
                topic_id=env["topic_id"],
                magnitude=0.8,
                confidence=0.9,
                impacts=[
                    {"market": "US", "sector": "Energy", "direction": "bullish", "tickers": ["XLE"], "strength": 0.9},
                    {"market": "US", "sector": "Airlines", "direction": "bearish", "tickers": ["JETS"], "strength": 0.9},
                ],
            )
            stats = rules.apply_rules(conn, cycle_id=env["cycle_id"])
            recs = _recommendations_for_cycle(conn, env["cycle_id"])

    assert stats["rules_triggered"] == 1
    assert recs[0].sector == "Airlines"


def test_confidence_floor_uses_max_of_topic_sensitivity_and_global(env):
    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(table("topics").update().where(table("topics").c.id == env["topic_id"]).values(sensitivity=0.9))
        # effective_confidence = 0.8 * 0.9 = 0.72; passes global floor (0.6) but not topic sensitivity (0.9)
        _insert_analysis(
            conn,
            cycle_id=env["cycle_id"],
            source_id=env["source_id"],
            topic_id=env["topic_id"],
            magnitude=0.8,
            confidence=0.8,
            impacts=[{"market": "US", "sector": "Energy", "direction": "bullish", "tickers": ["XLE"], "strength": 0.9}],
        )
        stats = rules.apply_rules(conn, cycle_id=env["cycle_id"])

    assert stats["rules_triggered"] == 0


def test_magnitude_below_global_floor_never_triggers_even_as_watch(env):
    from newswatch_worker.db import get_engine

    engine = get_engine()
    with engine.begin() as conn:
        _insert_analysis(
            conn,
            cycle_id=env["cycle_id"],
            source_id=env["source_id"],
            topic_id=env["topic_id"],
            magnitude=0.2,  # below global_magnitude_floor 0.35
            confidence=0.95,
            impacts=[{"market": "US", "sector": "Energy", "direction": "bullish", "tickers": ["XLE"], "strength": 0.95}],
        )
        stats = rules.apply_rules(conn, cycle_id=env["cycle_id"])

    assert stats["rules_triggered"] == 0


def test_quiet_tickers_filtered_row_becomes_sector_only(env):
    from newswatch_worker.db import get_engine

    engine = get_engine()
    with engine.begin() as conn:
        with _override_rules_settings(conn, quiet_tickers=["XLE", "CVX"]):
            _insert_analysis(
                conn,
                cycle_id=env["cycle_id"],
                source_id=env["source_id"],
                topic_id=env["topic_id"],
                magnitude=0.8,
                confidence=0.9,
                impacts=[{"market": "US", "sector": "Energy", "direction": "bullish", "tickers": ["XLE", "CVX"], "strength": 0.9}],
            )
            stats = rules.apply_rules(conn, cycle_id=env["cycle_id"])
            recs = _recommendations_for_cycle(conn, env["cycle_id"])

    assert stats["rules_triggered"] == 1
    assert recs[0].tickers == []
    assert sorted(recs[0].rule_trace["quiet_tickers_filtered"]) == ["CVX", "XLE"]


def test_dedup_window_blocks_repeat_within_window(env):
    from newswatch_worker.db import get_engine

    engine = get_engine()
    with engine.begin() as conn:
        _insert_analysis(
            conn,
            cycle_id=env["cycle_id"],
            source_id=env["source_id"],
            topic_id=env["topic_id"],
            magnitude=0.8,
            confidence=0.9,
            impacts=[{"market": "US", "sector": "Energy", "direction": "bullish", "tickers": ["XLE"], "strength": 0.9}],
        )
        first = rules.apply_rules(conn, cycle_id=env["cycle_id"])
        second = rules.apply_rules(conn, cycle_id=env["cycle_id"])
        recs = _recommendations_for_cycle(conn, env["cycle_id"])

    assert first["rules_triggered"] == 1
    assert second["rules_triggered"] == 0
    assert len(recs) == 1


def test_max_recommendations_per_cycle_caps_and_ranks_by_effective_confidence(env):
    from newswatch_worker.db import get_engine

    engine = get_engine()
    with engine.begin() as conn:
        with _override_rules_settings(conn, max_recommendations_per_cycle=1):
            _insert_analysis(
                conn,
                cycle_id=env["cycle_id"],
                source_id=env["source_id"],
                topic_id=env["topic_id"],
                magnitude=0.6,
                confidence=0.7,
                impacts=[{"market": "US", "sector": "Energy", "direction": "bullish", "tickers": ["XLE"], "strength": 0.9}],
            )
            _insert_analysis(
                conn,
                cycle_id=env["cycle_id"],
                source_id=env["source_id"],
                topic_id=env["topic_id"],
                magnitude=0.8,
                confidence=0.95,
                impacts=[{"market": "US", "sector": "Airlines", "direction": "bearish", "tickers": ["JETS"], "strength": 0.95}],
            )
            stats = rules.apply_rules(conn, cycle_id=env["cycle_id"])
            recs = _recommendations_for_cycle(conn, env["cycle_id"])

    assert stats["rules_candidates"] == 2
    assert stats["rules_triggered"] == 1
    assert len(recs) == 1
    # higher effective_confidence (0.95*0.95) beat (0.7*0.9)
    assert recs[0].sector == "Airlines"


def test_unconfigured_significant_triggers_watch_above_floor(env):
    from newswatch_worker.db import get_engine

    engine = get_engine()
    with engine.begin() as conn:
        _insert_analysis(
            conn,
            cycle_id=env["cycle_id"],
            source_id=env["source_id"],
            topic_id=None,
            magnitude=0.75,
            confidence=0.6,
            unmapped_sectors=[{"sector": "Shipping", "note": "bunker fuel costs rise"}],
        )
        stats = rules.apply_rules(conn, cycle_id=env["cycle_id"])
        recs = _recommendations_for_cycle(conn, env["cycle_id"])

    assert stats["rules_triggered"] == 1
    assert recs[0].action == "WATCH"
    assert recs[0].topic_id is None
    assert recs[0].market == "GLOBAL"
    assert recs[0].sector == "Shipping"
    assert recs[0].tickers == []


def test_unconfigured_significant_below_floor_does_not_trigger(env):
    from newswatch_worker.db import get_engine

    engine = get_engine()
    with engine.begin() as conn:
        _insert_analysis(
            conn,
            cycle_id=env["cycle_id"],
            source_id=env["source_id"],
            topic_id=None,
            magnitude=0.5,  # below unconfigured_magnitude_floor 0.7
            confidence=0.9,
            unmapped_sectors=[{"sector": "Shipping", "note": "minor note"}],
        )
        stats = rules.apply_rules(conn, cycle_id=env["cycle_id"])

    assert stats["rules_triggered"] == 0


def test_provenance_links_every_news_item_with_the_story_key(env):
    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    with engine.begin() as conn:
        story_key = f"test-story-{uuid.uuid4().hex[:8]}"
        analysis_id, primary_id = _insert_analysis(
            conn,
            cycle_id=env["cycle_id"],
            source_id=env["source_id"],
            topic_id=env["topic_id"],
            magnitude=0.8,
            confidence=0.9,
            story_key=story_key,
            impacts=[{"market": "US", "sector": "Energy", "direction": "bullish", "tickers": ["XLE"], "strength": 0.9}],
        )
        corroborating_id = _insert_news_item(conn, source_id=env["source_id"], story_key=story_key, title="corroborating")

        rules.apply_rules(conn, cycle_id=env["cycle_id"])

        recommendation_id = conn.execute(
            select(table("recommendations").c.id).where(table("recommendations").c.cycle_id == env["cycle_id"])
        ).scalar_one()
        linked_item_ids = {
            str(row.news_item_id)
            for row in conn.execute(
                select(table("recommendation_sources").c.news_item_id).where(
                    table("recommendation_sources").c.recommendation_id == recommendation_id
                )
            ).all()
        }

    assert linked_item_ids == {primary_id, corroborating_id}
