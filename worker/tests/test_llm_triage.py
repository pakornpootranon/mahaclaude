"""Tests for newswatch_worker.llm.triage against real local Postgres, with
a fake Anthropic client (no live ANTHROPIC_API_KEY in this sandbox)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from anthropic.types import Message, TextBlock, Usage
from sqlalchemy import select

from newswatch_worker.llm import client, triage

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


@pytest.fixture
def env(monkeypatch):
    from newswatch_worker.db import get_engine, table

    monkeypatch.setattr(client, "resolve_api_key", lambda conn: "sk-ant-fake")

    engine = get_engine()
    marker = uuid.uuid4().hex[:8]
    sources_t = table("sources")
    topics_t = table("topics")

    with engine.begin() as conn:
        source_id = conn.execute(
            sources_t.insert()
            .values(name=f"test-triage-src-{marker}", source_type="rss", config={"url": "http://example.com/feed"}, enabled=False)
            .returning(sources_t.c.id)
        ).scalar_one()
        topic_id = conn.execute(
            topics_t.insert()
            .values(name=f"test-triage-topic-{marker}", description="oil supply", keywords=["OPEC"], sensitivity=0.5, enabled=True)
            .returning(topics_t.c.id)
        ).scalar_one()

    yield {"source_id": str(source_id), "topic_id": str(topic_id)}

    with engine.begin() as conn:
        conn.execute(table("news_items").delete().where(table("news_items").c.source_id == source_id))
        conn.execute(table("topics").delete().where(table("topics").c.id == topic_id))
        conn.execute(table("sources").delete().where(table("sources").c.id == source_id))


def _insert_pending_item(conn, *, source_id: str, title: str, published_at=None) -> str:
    from newswatch_worker.db import table

    news_items_t = table("news_items")
    return str(
        conn.execute(
            news_items_t.insert()
            .values(
                source_id=source_id,
                dedupe_key=uuid.uuid4().hex,
                url=f"https://example.com/{uuid.uuid4().hex}",
                title=title,
                summary="a test summary",
                triage_status="pending",
                published_at=published_at,
            )
            .returning(news_items_t.c.id)
        ).scalar_one()
    )


def test_select_items_for_cycle_caps_newest_first_and_marks_overflow_skipped(env):
    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        older_id = _insert_pending_item(conn, source_id=env["source_id"], title="older", published_at=now - timedelta(hours=2))
        newer_id = _insert_pending_item(conn, source_id=env["source_id"], title="newer", published_at=now - timedelta(hours=1))

        selected, skipped = triage.select_items_for_cycle(conn, max_items_per_cycle=1)

        overflow_status = conn.execute(
            select(table("news_items").c.triage_status).where(table("news_items").c.id == older_id)
        ).scalar_one()

    assert skipped == 1
    assert len(selected) == 1
    assert selected[0].id == newer_id
    assert overflow_status == "skipped_budget"


def test_run_triage_writes_relevant_and_irrelevant_status_and_matched_topic_ids(env, monkeypatch):
    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        # published_at descending drives batch order (select_items_for_cycle) -
        # explicit timestamps make idx 0/1 below deterministic.
        relevant_id = _insert_pending_item(conn, source_id=env["source_id"], title="OPEC cuts oil production", published_at=now)
        irrelevant_id = _insert_pending_item(
            conn, source_id=env["source_id"], title="Local bakery wins award", published_at=now - timedelta(hours=1)
        )

        short_id = env["topic_id"].replace("-", "")[:8]
        response_json = (
            '{"items": ['
            f'{{"idx": 0, "relevant": true, "matched_topic_ids": ["{short_id}"], "story_key": "opec-test"}},'
            '{"idx": 1, "relevant": false, "matched_topic_ids": [], "story_key": "irrelevant-test"}'
            "]}"
        )
        fake = _FakeAnthropicClient([_message(response_json)])
        monkeypatch.setattr(client.anthropic, "Anthropic", lambda api_key: fake)

        cycles_t = table("cycles")
        cycle_id = str(
            conn.execute(
                cycles_t.insert()
                .values(scheduled_for=datetime.now(timezone.utc), kind="manual", state="TRIAGING", stats={})
                .returning(cycles_t.c.id)
            ).scalar_one()
        )

        stats = triage.run_triage(conn, cycle_id=cycle_id)

        relevant_row = conn.execute(
            select(table("news_items").c.triage_status, table("news_items").c.story_key, table("news_items").c.matched_topic_ids).where(
                table("news_items").c.id == relevant_id
            )
        ).first()
        irrelevant_row = conn.execute(
            select(table("news_items").c.triage_status, table("news_items").c.story_key).where(
                table("news_items").c.id == irrelevant_id
            )
        ).first()

        conn.execute(table("llm_calls").delete().where(table("llm_calls").c.cycle_id == cycle_id))
        conn.execute(cycles_t.delete().where(cycles_t.c.id == cycle_id))

    assert stats["triage_relevant"] == 1
    assert stats["triage_irrelevant"] == 1
    assert relevant_row.triage_status == "relevant"
    assert relevant_row.story_key == "opec-test"
    assert relevant_row.matched_topic_ids == [env["topic_id"]]
    assert irrelevant_row.triage_status == "irrelevant"
    assert irrelevant_row.story_key is None


def test_run_triage_marks_remaining_batches_skipped_budget_on_budget_exceeded(env, monkeypatch):
    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    with engine.begin() as conn:
        item_id = _insert_pending_item(conn, source_id=env["source_id"], title="OPEC cuts oil production")

        def _raise_budget(*args, **kwargs):
            raise client.BudgetExceededError("out of budget")

        monkeypatch.setattr(client, "call_structured", _raise_budget)

        cycles_t = table("cycles")
        cycle_id = str(
            conn.execute(
                cycles_t.insert()
                .values(scheduled_for=datetime.now(timezone.utc), kind="manual", state="TRIAGING", stats={})
                .returning(cycles_t.c.id)
            ).scalar_one()
        )

        stats = triage.run_triage(conn, cycle_id=cycle_id)

        status = conn.execute(select(table("news_items").c.triage_status).where(table("news_items").c.id == item_id)).scalar_one()

        conn.execute(table("llm_calls").delete().where(table("llm_calls").c.cycle_id == cycle_id))
        conn.execute(cycles_t.delete().where(cycles_t.c.id == cycle_id))

    assert stats["budget_hit"] is True
    assert status == "skipped_budget"
