"""End-to-end test of the full digest cycle state machine with the LLM
pipeline wired in (Phase 3): PENDING -> INGESTING -> TRIAGING -> ANALYZING
-> TRIGGERING -> PM_SCANNING -> SUMMARIZING -> DONE, driven through the real
`cycle.run_cycle()` entrypoint exactly as `newswatch run-cycle` would.

Sources are disabled (as in test_ingest.py) so INGESTING is a real no-op
rather than hitting the network; news_items are seeded directly instead.
The Anthropic client is faked (no live ANTHROPIC_API_KEY in this sandbox)
but every other layer - cycle state machine, triage, analysis, rules,
digest, and their DB writes - runs for real. This is the closest thing to a
live end-to-end run available here, and it verifies the full provenance
chain PRD acceptance requires: recommendation -> analysis JSON -> news items.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from anthropic.types import Message, TextBlock, Usage
from sqlalchemy import select

from newswatch_worker import cycle
from newswatch_worker.llm import client

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")


def _message(text: str) -> Message:
    return Message(
        id="msg_test",
        type="message",
        role="assistant",
        model="claude-haiku-4-5",
        content=[TextBlock(type="text", text=text)],
        stop_reason="end_turn",
        stop_sequence=None,
        usage=Usage(input_tokens=10, output_tokens=5),
    )


class _FakeMessages:
    def __init__(self, responses: list[Message]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
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
        conn.execute(sources_t.delete().where(sources_t.c.name.like("test-e2e-%")))
        conn.execute(table("topics").delete().where(table("topics").c.name.like("test-e2e-%")))
        if previously_enabled_ids:
            conn.execute(sources_t.update().where(sources_t.c.id.in_(previously_enabled_ids)).values(enabled=True))


def _test_source_ids(conn):
    from newswatch_worker.db import table

    return [row.id for row in conn.execute(select(table("sources").c.id).where(table("sources").c.name.like("test-e2e-%"))).all()]


@pytest.fixture
def seeded(monkeypatch):
    from newswatch_worker.db import get_engine, table

    monkeypatch.setattr(client, "resolve_api_key", lambda conn: "sk-ant-fake")

    engine = get_engine()
    marker = uuid.uuid4().hex[:8]
    with engine.begin() as conn:
        source_id = conn.execute(
            table("sources")
            .insert()
            .values(name=f"test-e2e-src-{marker}", source_type="rss", config={"url": "http://example.com/feed"}, enabled=False)
            .returning(table("sources").c.id)
        ).scalar_one()
        topic_id = conn.execute(
            table("topics")
            .insert()
            .values(name=f"test-e2e-oil-{marker}", description="oil supply shocks", keywords=["OPEC"], sensitivity=0.5, enabled=True)
            .returning(table("topics").c.id)
        ).scalar_one()
        conn.execute(
            table("mappings")
            .insert()
            .values(topic_id=topic_id, market="US", sector="Energy", tickers=["XLE", "CVX"], polarity=1, enabled=True)
        )
        news_items_t = table("news_items")
        item_id = conn.execute(
            news_items_t.insert()
            .values(
                source_id=source_id,
                dedupe_key=uuid.uuid4().hex,
                url=f"https://example.com/{uuid.uuid4().hex}",
                title="OPEC+ agrees to extend production cuts through Q3",
                summary="OPEC+ ministers agreed on Sunday to extend existing production cuts.",
                body_excerpt="OPEC+ ministers agreed on Sunday to extend existing production cuts through Q3, "
                "citing continued demand uncertainty.",
                triage_status="pending",
            )
            .returning(news_items_t.c.id)
        ).scalar_one()

    yield {"source_id": str(source_id), "topic_id": str(topic_id), "item_id": str(item_id)}


def test_full_cycle_pipeline_reaches_done_with_full_provenance_chain(seeded, monkeypatch):
    short_id = seeded["topic_id"].replace("-", "")[:8]

    triage_response = (
        '{"items": [{"idx": 0, "relevant": true, "matched_topic_ids": ["'
        + short_id
        + '"], "story_key": "opec-cut-e2e"}]}'
    )
    analysis_response = (
        '{"story_key": "opec-cut-e2e", '
        f'"matched_topics": [{{"topic_id": "{short_id}", "match_strength": 0.9}}], '
        '"event_polarity": 1, "magnitude": 0.65, "confidence": 0.85, "horizon": "weeks", '
        '"impacts": [{"market": "US", "sector": "Energy", "direction": "bullish", "tickers": ["XLE", "CVX"], "strength": 0.8}], '
        '"unmapped_sectors": [], "reasoning": "OPEC+ extended supply cuts, tightening the market.", "caveats": ""}'
    )
    digest_response = (
        '{"market_mood": "bullish", "synthesis": "Energy names look constructive after OPEC+ extended cuts.", '
        '"top_themes": [{"theme": "OPEC+ supply cuts", "why": "extended through Q3", "item_count": 1}]}'
    )

    fake = _FakeAnthropicClient([_message(triage_response), _message(analysis_response), _message(digest_response)])
    monkeypatch.setattr(client.anthropic, "Anthropic", lambda api_key: fake)

    final_state = cycle.run_cycle(dry=False, kind="manual")

    assert final_state == "DONE"

    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    with engine.begin() as conn:
        cycle_row = conn.execute(
            select(table("cycles").c.state, table("cycles").c.budget_hit).order_by(table("cycles").c.scheduled_for.desc()).limit(1)
        ).first()

        rec_row = conn.execute(
            select(
                table("recommendations").c.id,
                table("recommendations").c.action,
                table("recommendations").c.sector,
                table("recommendations").c.tickers,
                table("recommendations").c.analysis_id,
                table("recommendations").c.rule_trace,
            )
        ).first()

        analysis_row = conn.execute(
            select(table("analyses").c.id, table("analyses").c.story_key, table("analyses").c.result).where(
                table("analyses").c.id == rec_row.analysis_id
            )
        ).first()

        source_item_ids = {
            row.news_item_id
            for row in conn.execute(
                select(table("recommendation_sources").c.news_item_id).where(
                    table("recommendation_sources").c.recommendation_id == rec_row.id
                )
            ).all()
        }

        digest_row = conn.execute(select(table("digests").c.market_mood, table("digests").c.synthesis)).first()

    assert cycle_row.state == "DONE"
    assert cycle_row.budget_hit is False

    # provenance chain: recommendation -> analysis JSON -> news item(s)
    assert rec_row.action == "BUY"
    assert rec_row.sector == "Energy"
    assert sorted(rec_row.tickers) == ["CVX", "XLE"]
    assert rec_row.rule_trace["dedup_window"]["pass"] is True
    assert analysis_row.story_key == "opec-cut-e2e"
    assert analysis_row.result["reasoning"]
    assert str(source_item_ids.pop()) == seeded["item_id"]

    assert digest_row.market_mood == "bullish"
    assert "OPEC" in digest_row.synthesis or "opec" in digest_row.synthesis.lower()

    assert len(fake.messages.calls) == 3
