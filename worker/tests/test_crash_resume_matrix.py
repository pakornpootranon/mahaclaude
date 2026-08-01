"""Crash-resume test matrix (CLAUDE.md Phase 7, PRD acceptance #4).

cycle.py's real crash window: each state's work and its transition to the
next state commit atomically in ONE `with engine.begin() as conn:` block
(cycle.py's own module docstring). A real SIGKILL either commits the whole
step or, if it lands mid-transaction, commits nothing (Postgres rolls the
open transaction back) - so the only crash window that ever leaves
persisted, resumable partial state is "killed right as the process entered
state X, before X's handler produced any of its own writes." This test
simulates exactly that window, once per real state, by swapping that
state's handler for one that raises before doing any work, confirming the
cycle is left stuck at that state (not advanced, not FAILED - matching
cycle.py's own documented behavior), then letting a second `run_cycle()`
call resume and drive it to DONE using the SAME cycle_id with no duplicate
rows anywhere.
"""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager

import pytest
from anthropic.types import Message, TextBlock, Usage
from sqlalchemy import select

from newswatch_worker import cycle
from newswatch_worker.llm import client

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")

REAL_STATES = [s for s in cycle.STATES if s != "PENDING" and s != "DONE"]


def _message(text: str) -> Message:
    return Message(
        id="msg_test", type="message", role="assistant", model="claude-sonnet-5",
        content=[TextBlock(type="text", text=text)], stop_reason="end_turn", stop_sequence=None,
        usage=Usage(input_tokens=10, output_tokens=5),
    )


class _FakeMessages:
    def __init__(self, responses: list[Message]):
        self._responses = list(responses)

    def create(self, **kwargs):
        return self._responses.pop(0)


class _FakeAnthropicClient:
    def __init__(self, responses: list[Message]):
        self.messages = _FakeMessages(responses)


@pytest.fixture(autouse=True)
def _clear_capability_cache():
    client._model_thinking_capability.cache_clear()
    yield
    client._model_thinking_capability.cache_clear()


@pytest.fixture(autouse=True)
def _isolate_sources_and_cycles():
    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    sources_t = table("sources")
    with engine.begin() as conn:
        previously_enabled_ids = [row.id for row in conn.execute(select(sources_t.c.id).where(sources_t.c.enabled.is_(True))).all()]
        if previously_enabled_ids:
            conn.execute(sources_t.update().where(sources_t.c.id.in_(previously_enabled_ids)).values(enabled=False))

    yield

    with engine.begin() as conn:
        conn.execute(table("recommendation_sources").delete())
        conn.execute(table("recommendations").delete())
        conn.execute(table("analysis_topics").delete())
        conn.execute(table("analyses").delete())
        conn.execute(table("digests").delete())
        conn.execute(table("news_items").delete().where(table("news_items").c.source_id.in_(_test_source_ids(conn))))
        conn.execute(table("llm_calls").delete())
        conn.execute(table("cycles").delete())
        conn.execute(sources_t.delete().where(sources_t.c.name.like("test-crash-%")))
        conn.execute(table("topics").delete().where(table("topics").c.name.like("test-crash-%")))
        if previously_enabled_ids:
            conn.execute(sources_t.update().where(sources_t.c.id.in_(previously_enabled_ids)).values(enabled=True))


def _test_source_ids(conn):
    from newswatch_worker.db import table

    return [row.id for row in conn.execute(select(table("sources").c.id).where(table("sources").c.name.like("test-crash-%"))).all()]


@pytest.fixture
def seeded(monkeypatch):
    from newswatch_worker.db import get_engine, table

    monkeypatch.setattr(client, "resolve_api_key", lambda conn: "sk-ant-fake")

    engine = get_engine()
    marker = uuid.uuid4().hex[:8]
    with engine.begin() as conn:
        source_id = conn.execute(
            table("sources").insert()
            .values(name=f"test-crash-src-{marker}", source_type="rss", config={"url": "http://example.com/feed"}, enabled=False)
            .returning(table("sources").c.id)
        ).scalar_one()
        topic_id = conn.execute(
            table("topics").insert()
            .values(name=f"test-crash-oil-{marker}", description="oil supply shocks", keywords=["OPEC"], sensitivity=0.5, enabled=True)
            .returning(table("topics").c.id)
        ).scalar_one()
        conn.execute(
            table("mappings").insert()
            .values(topic_id=topic_id, market="US", sector="Energy", tickers=["XLE"], polarity=1, enabled=True)
        )
        item_id = conn.execute(
            table("news_items").insert()
            .values(
                source_id=source_id, dedupe_key=uuid.uuid4().hex, url=f"https://example.com/{uuid.uuid4().hex}",
                title="OPEC+ agrees to extend production cuts through Q3",
                summary="OPEC+ ministers agreed to extend production cuts.",
                body_excerpt="OPEC+ ministers agreed on Sunday to extend existing production cuts through Q3.",
                triage_status="pending",
            )
            .returning(table("news_items").c.id)
        ).scalar_one()

    yield {"source_id": str(source_id), "topic_id": str(topic_id), "item_id": str(item_id)}


@pytest.mark.parametrize("target_state", REAL_STATES)
def test_crash_resume_from_each_state(seeded, monkeypatch, target_state):
    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    short_id = seeded["topic_id"].replace("-", "")[:8]

    triage_response = (
        '{"items": [{"idx": 0, "relevant": true, "matched_topic_ids": ["' + short_id + '"], "story_key": "opec-cut-crash"}]}'
    )
    analysis_response = (
        '{"story_key": "opec-cut-crash", '
        f'"matched_topics": [{{"topic_id": "{short_id}", "match_strength": 0.9}}], '
        '"event_polarity": 1, "magnitude": 0.65, "confidence": 0.85, "horizon": "weeks", '
        '"impacts": [{"market": "US", "sector": "Energy", "direction": "bullish", "tickers": ["XLE"], "strength": 0.8}], '
        '"unmapped_sectors": [], "reasoning": "OPEC+ extended supply cuts.", "caveats": ""}'
    )
    digest_response = (
        '{"market_mood": "bullish", "synthesis": "Energy looks constructive.", '
        '"top_themes": [{"theme": "OPEC+ cuts", "why": "extended", "item_count": 1}]}'
    )
    # Consumed strictly in pipeline-dependency order (triage -> analysis ->
    # digest) regardless of which state crashes first, so one fixed queue
    # works for every parametrized target_state (see module docstring).
    fake = _FakeAnthropicClient([_message(triage_response), _message(analysis_response), _message(digest_response)])
    monkeypatch.setattr(client.anthropic, "Anthropic", lambda api_key: fake)

    with _polymarket_disabled_for_test(engine):
        real_handlers = dict(cycle.STEP_HANDLERS)

        def _boom(ctx):
            raise RuntimeError(f"simulated kill entering {target_state}")

        monkeypatch.setattr(cycle, "STEP_HANDLERS", {**real_handlers, target_state: _boom})

        with pytest.raises(RuntimeError, match="simulated kill"):
            cycle.run_cycle(dry=False, kind="manual")

        cycles_t = table("cycles")
        with engine.begin() as conn:
            stuck = conn.execute(
                select(cycles_t.c.id, cycles_t.c.state).order_by(cycles_t.c.scheduled_for.desc()).limit(1)
            ).first()
        assert stuck.state == target_state, "cycle must be left at the state it was killed entering, not advanced or FAILED"

        monkeypatch.setattr(cycle, "STEP_HANDLERS", real_handlers)

        final_state = cycle.run_cycle(dry=False, kind="manual")
        assert final_state == "DONE"

        with engine.begin() as conn:
            all_cycle_rows = conn.execute(select(cycles_t.c.id)).all()
            rec_rows = conn.execute(select(table("recommendations").c.id)).all()
            analysis_rows = conn.execute(select(table("analyses").c.id)).all()
            digest_rows = conn.execute(select(table("digests").c.cycle_id)).all()

        assert len(all_cycle_rows) == 1, "resume must reuse the stuck cycle_id, never create a second cycle row"
        assert str(all_cycle_rows[0].id) == str(stuck.id)
        assert len(analysis_rows) == 1, "no duplicate analysis from resuming"
        assert len(rec_rows) == 1, "no duplicate recommendation from resuming"
        assert len(digest_rows) == 1, "no duplicate digest from resuming"


@contextmanager
def _polymarket_disabled_for_test(engine):
    from newswatch_worker.db import table

    settings_t = table("settings")
    with engine.begin() as conn:
        original = conn.execute(select(settings_t.c.value).where(settings_t.c.key == "polymarket")).scalar_one()
        conn.execute(settings_t.update().where(settings_t.c.key == "polymarket").values(value={**original, "enabled": False}))
    try:
        yield
    finally:
        with engine.begin() as conn:
            conn.execute(settings_t.update().where(settings_t.c.key == "polymarket").values(value=original))
