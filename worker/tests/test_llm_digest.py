"""Tests for newswatch_worker.llm.digest against real local Postgres, with
a fake Anthropic client (no live ANTHROPIC_API_KEY in this sandbox)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from anthropic.types import Message, TextBlock, Usage
from sqlalchemy import select

from newswatch_worker.llm import client, digest

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")


def _message(text: str) -> Message:
    return Message(
        id="msg_test",
        type="message",
        role="assistant",
        model="claude-sonnet-5",
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


@pytest.fixture
def env(monkeypatch):
    from newswatch_worker.db import get_engine, table

    monkeypatch.setattr(client, "resolve_api_key", lambda conn: "sk-ant-fake")

    engine = get_engine()
    marker = uuid.uuid4().hex[:8]
    sources_t = table("sources")
    topics_t = table("topics")
    cycles_t = table("cycles")

    with engine.begin() as conn:
        source_id = conn.execute(
            sources_t.insert()
            .values(name=f"test-digest-src-{marker}", source_type="rss", config={"url": "http://example.com/feed"}, enabled=False)
            .returning(sources_t.c.id)
        ).scalar_one()
        topic_id = conn.execute(
            topics_t.insert()
            .values(name=f"test-digest-topic-{marker}", description="d", keywords=[], sensitivity=0.5, enabled=True)
            .returning(topics_t.c.id)
        ).scalar_one()
        cycle_id = conn.execute(
            cycles_t.insert()
            .values(scheduled_for=datetime.now(timezone.utc), kind="manual", state="SUMMARIZING", stats={"ingested": 3})
            .returning(cycles_t.c.id)
        ).scalar_one()

    yield {"source_id": str(source_id), "topic_id": str(topic_id), "cycle_id": str(cycle_id)}

    with engine.begin() as conn:
        conn.execute(table("digests").delete().where(table("digests").c.cycle_id == cycle_id))
        conn.execute(table("recommendations").delete().where(table("recommendations").c.cycle_id == cycle_id))
        conn.execute(table("analyses").delete().where(table("analyses").c.cycle_id == cycle_id))
        conn.execute(table("news_items").delete().where(table("news_items").c.source_id == source_id))
        conn.execute(table("llm_calls").delete().where(table("llm_calls").c.cycle_id == cycle_id))
        conn.execute(table("cycles").delete().where(table("cycles").c.id == cycle_id))
        conn.execute(table("topics").delete().where(table("topics").c.id == topic_id))
        conn.execute(table("sources").delete().where(table("sources").c.id == source_id))


def _insert_analysis(conn, *, cycle_id, source_id, topic_id, story_key="s1"):
    from newswatch_worker.db import table

    news_items_t = table("news_items")
    analyses_t = table("analyses")
    analysis_topics_t = table("analysis_topics")

    item_id = conn.execute(
        news_items_t.insert()
        .values(
            source_id=source_id,
            dedupe_key=uuid.uuid4().hex,
            url=f"https://example.com/{uuid.uuid4().hex}",
            title="test item",
            triage_status="relevant",
            story_key=story_key,
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
            result={"horizon": "weeks"},
            event_polarity=1,
            magnitude=0.5,
            confidence=0.7,
        )
        .returning(analyses_t.c.id)
    ).scalar_one()
    conn.execute(analysis_topics_t.insert().values(analysis_id=analysis_id, topic_id=topic_id, match_strength=0.7))
    return str(analysis_id)


def test_run_digest_calls_llm_and_writes_digest_row(env, monkeypatch):
    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    with engine.begin() as conn:
        _insert_analysis(conn, cycle_id=env["cycle_id"], source_id=env["source_id"], topic_id=env["topic_id"])

        response_json = (
            '{"market_mood": "mixed", "synthesis": "A quiet cycle overall.", '
            '"top_themes": [{"theme": "Test theme", "why": "test", "item_count": 1}], '
            '"topic_summaries": [{"topic_id": "%s", "topic_name": "t", "summary": "สรุปภาษาไทย"}]}'
        ) % env["topic_id"]
        fake = _FakeAnthropicClient([_message(response_json)])
        monkeypatch.setattr(client.anthropic, "Anthropic", lambda api_key: fake)

        stats = digest.run_digest(conn, cycle_id=env["cycle_id"], budget_hit=False)

        row = conn.execute(
            select(
                table("digests").c.market_mood,
                table("digests").c.synthesis,
                table("digests").c.top_themes,
                table("digests").c.topic_summaries,
            ).where(table("digests").c.cycle_id == env["cycle_id"])
        ).first()

    assert stats["digest_degraded"] is False
    assert row.market_mood == "mixed"
    assert row.synthesis == "A quiet cycle overall."
    assert row.top_themes[0]["theme"] == "Test theme"
    assert row.topic_summaries[0]["topic_id"] == env["topic_id"]
    assert row.topic_summaries[0]["summary"] == "สรุปภาษาไทย"
    assert len(fake.messages.calls) == 1


def test_run_digest_budget_hit_skips_llm_and_uses_topic_match_counts(env, monkeypatch):
    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    with engine.begin() as conn:
        _insert_analysis(conn, cycle_id=env["cycle_id"], source_id=env["source_id"], topic_id=env["topic_id"])

        fake = _FakeAnthropicClient([])
        monkeypatch.setattr(client.anthropic, "Anthropic", lambda api_key: fake)

        stats = digest.run_digest(conn, cycle_id=env["cycle_id"], budget_hit=True)

        row = conn.execute(
            select(
                table("digests").c.market_mood,
                table("digests").c.synthesis,
                table("digests").c.top_themes,
                table("digests").c.topic_summaries,
            ).where(table("digests").c.cycle_id == env["cycle_id"])
        ).first()

    assert stats["digest_degraded"] is True
    assert row.market_mood == "mixed"
    assert "งบประมาณ" in row.synthesis  # Thai for "budget" - degraded synthesis is Thai now
    assert len(fake.messages.calls) == 0
    assert any(t["item_count"] == 1 for t in row.top_themes)
    # degraded path still covers every topic, Thai-language, even with no LLM call
    assert any(t["topic_id"] == env["topic_id"] and "งบประมาณ" in t["summary"] for t in row.topic_summaries)


def test_run_digest_is_idempotent_on_rerun(env, monkeypatch):
    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    with engine.begin() as conn:
        _insert_analysis(conn, cycle_id=env["cycle_id"], source_id=env["source_id"], topic_id=env["topic_id"])

        response_json = '{"market_mood": "quiet", "synthesis": "Nothing much.", "top_themes": []}'
        fake = _FakeAnthropicClient([_message(response_json), _message(response_json)])
        monkeypatch.setattr(client.anthropic, "Anthropic", lambda api_key: fake)

        digest.run_digest(conn, cycle_id=env["cycle_id"], budget_hit=False)
        digest.run_digest(conn, cycle_id=env["cycle_id"], budget_hit=False)

        rows = conn.execute(select(table("digests").c.cycle_id).where(table("digests").c.cycle_id == env["cycle_id"])).all()

    assert len(rows) == 1
    # second call still makes its own LLM call (digest has no "already done"
    # short-circuit like analyze.py's select_storylines) but ON CONFLICT DO
    # NOTHING keeps the digests row itself singular.
    assert len(fake.messages.calls) == 2
