"""Tests for newswatch_worker.llm.analyze against real local Postgres, with
a fake Anthropic client (no live ANTHROPIC_API_KEY in this sandbox)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from anthropic.types import Message, TextBlock, Usage
from sqlalchemy import select

from newswatch_worker.llm import analyze, client

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
    mappings_t = table("mappings")
    cycles_t = table("cycles")

    with engine.begin() as conn:
        source_id = conn.execute(
            sources_t.insert()
            .values(name=f"test-analyze-src-{marker}", source_type="rss", config={"url": "http://example.com/feed"}, enabled=False)
            .returning(sources_t.c.id)
        ).scalar_one()
        topic_id = conn.execute(
            topics_t.insert()
            .values(name=f"test-analyze-topic-{marker}", description="oil supply", keywords=["OPEC"], sensitivity=0.5, enabled=True)
            .returning(topics_t.c.id)
        ).scalar_one()
        conn.execute(
            mappings_t.insert().values(topic_id=topic_id, market="US", sector="Energy", tickers=["XLE", "CVX"], polarity=1, enabled=True)
        )
        cycle_id = conn.execute(
            cycles_t.insert()
            .values(scheduled_for=datetime.now(timezone.utc), kind="manual", state="ANALYZING", stats={})
            .returning(cycles_t.c.id)
        ).scalar_one()

    yield {"source_id": str(source_id), "topic_id": str(topic_id), "cycle_id": str(cycle_id)}

    with engine.begin() as conn:
        conn.execute(table("analyses").delete().where(table("analyses").c.cycle_id == cycle_id))
        conn.execute(table("news_items").delete().where(table("news_items").c.source_id == source_id))
        conn.execute(table("llm_calls").delete().where(table("llm_calls").c.cycle_id == cycle_id))
        conn.execute(table("cycles").delete().where(table("cycles").c.id == cycle_id))
        conn.execute(table("topics").delete().where(table("topics").c.id == topic_id))
        conn.execute(table("sources").delete().where(table("sources").c.id == source_id))


def _insert_relevant_item(conn, *, source_id, story_key, title, body_excerpt="", matched_topic_ids=None, published_at=None):
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
                summary=title,
                body_excerpt=body_excerpt,
                triage_status="relevant",
                story_key=story_key,
                matched_topic_ids=matched_topic_ids or [],
                published_at=published_at,
            )
            .returning(news_items_t.c.id)
        ).scalar_one()
    )


def test_select_storylines_picks_longest_body_as_primary(env):
    from newswatch_worker.db import get_engine

    engine = get_engine()
    with engine.begin() as conn:
        short_id = _insert_relevant_item(
            conn, source_id=env["source_id"], story_key="s1", title="short version", body_excerpt="short"
        )
        long_id = _insert_relevant_item(
            conn, source_id=env["source_id"], story_key="s1", title="long version", body_excerpt="a much longer body excerpt here"
        )

        storylines = analyze.select_storylines(conn)

    matching = [s for s in storylines if s.story_key == "s1"]
    assert len(matching) == 1
    assert matching[0].primary_item_id == long_id
    assert set(matching[0].news_item_ids) == {long_id, short_id}


def test_select_storylines_excludes_already_analyzed_story_keys(env):
    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    with engine.begin() as conn:
        item_id = _insert_relevant_item(conn, source_id=env["source_id"], story_key="already-done", title="t")
        conn.execute(
            table("analyses")
            .insert()
            .values(
                cycle_id=env["cycle_id"],
                story_key="already-done",
                primary_item_id=item_id,
                prompt_version=analyze.PROMPT_VERSION,
                model="test",
                result={},
                event_polarity=0,
                magnitude=0.1,
                confidence=0.1,
            )
        )
        storylines = analyze.select_storylines(conn)

    assert all(s.story_key != "already-done" for s in storylines)


def test_run_analysis_strips_hallucinated_tickers_and_writes_analysis_topics(env, monkeypatch):
    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    with engine.begin() as conn:
        _insert_relevant_item(
            conn,
            source_id=env["source_id"],
            story_key="opec-cut",
            title="OPEC+ agrees to extend production cuts",
            body_excerpt="OPEC+ ministers agreed on Sunday to extend existing production cuts through Q3.",
            matched_topic_ids=[env["topic_id"]],
        )

        short_id = env["topic_id"].replace("-", "")[:8]
        response_json = (
            '{"story_key": "opec-cut", '
            f'"matched_topics": [{{"topic_id": "{short_id}", "match_strength": 0.9}}], '
            '"event_polarity": 1, "magnitude": 0.55, "confidence": 0.8, "horizon": "weeks", '
            '"impacts": [{"market": "US", "sector": "Energy", "direction": "bullish", '
            '"tickers": ["XLE", "CVX", "HALLUCINATED"], "strength": 0.6}], '
            '"unmapped_sectors": [], "reasoning": "OPEC+ cut supply.", "caveats": ""}'
        )
        fake = _FakeAnthropicClient([_message(response_json)])
        monkeypatch.setattr(client.anthropic, "Anthropic", lambda api_key: fake)

        stats = analyze.run_analysis(conn, cycle_id=env["cycle_id"])

        analyses_t = table("analyses")
        analysis_row = conn.execute(
            select(analyses_t.c.id, analyses_t.c.result, analyses_t.c.magnitude, analyses_t.c.confidence).where(
                analyses_t.c.story_key == "opec-cut"
            )
        ).first()

        analysis_topics_rows = conn.execute(
            select(table("analysis_topics").c.topic_id, table("analysis_topics").c.match_strength).where(
                table("analysis_topics").c.analysis_id == analysis_row.id
            )
        ).all()

    assert stats["analysis_succeeded"] == 1
    assert stats["analysis_tickers_stripped"] == 1
    assert analysis_row.result["impacts"][0]["tickers"] == ["XLE", "CVX"]
    assert float(analysis_row.magnitude) == pytest.approx(0.55)
    assert len(analysis_topics_rows) == 1
    assert str(analysis_topics_rows[0].topic_id) == env["topic_id"]
    assert float(analysis_topics_rows[0].match_strength) == pytest.approx(0.9)


def test_run_analysis_unconfigured_storyline_writes_null_topic_id(env, monkeypatch):
    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    with engine.begin() as conn:
        _insert_relevant_item(
            conn,
            source_id=env["source_id"],
            story_key="major-unconfigured",
            title="Central bank announces surprise emergency action",
            body_excerpt="A major central bank made a surprise policy announcement.",
            matched_topic_ids=[],
        )

        response_json = (
            '{"story_key": "major-unconfigured", "matched_topics": [], '
            '"event_polarity": 0, "magnitude": 0.8, "confidence": 0.7, "horizon": "days", '
            '"impacts": [], '
            '"unmapped_sectors": [{"sector": "Broad market", "note": "systemic event"}], '
            '"reasoning": "Surprise policy shift.", "caveats": ""}'
        )
        fake = _FakeAnthropicClient([_message(response_json)])
        monkeypatch.setattr(client.anthropic, "Anthropic", lambda api_key: fake)

        analyze.run_analysis(conn, cycle_id=env["cycle_id"])

        analyses_t = table("analyses")
        analysis_id = conn.execute(
            select(analyses_t.c.id).where(analyses_t.c.story_key == "major-unconfigured")
        ).scalar_one()
        analysis_topics_rows = conn.execute(
            select(table("analysis_topics").c.topic_id, table("analysis_topics").c.match_strength).where(
                table("analysis_topics").c.analysis_id == analysis_id
            )
        ).all()

    assert len(analysis_topics_rows) == 1
    assert analysis_topics_rows[0].topic_id is None
    assert float(analysis_topics_rows[0].match_strength) == pytest.approx(0.7)


def test_run_analysis_is_idempotent_on_rerun(env, monkeypatch):
    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    with engine.begin() as conn:
        _insert_relevant_item(
            conn,
            source_id=env["source_id"],
            story_key="rerun-test",
            title="Some analyzable event",
            body_excerpt="Enough text to analyze.",
            matched_topic_ids=[env["topic_id"]],
        )

        short_id = env["topic_id"].replace("-", "")[:8]
        response_json = (
            '{"story_key": "rerun-test", '
            f'"matched_topics": [{{"topic_id": "{short_id}", "match_strength": 0.8}}], '
            '"event_polarity": 1, "magnitude": 0.5, "confidence": 0.7, "horizon": "weeks", '
            '"impacts": [{"market": "US", "sector": "Energy", "direction": "bullish", "tickers": ["XLE"], "strength": 0.5}], '
            '"unmapped_sectors": [], "reasoning": "test.", "caveats": ""}'
        )
        fake = _FakeAnthropicClient([_message(response_json)])
        monkeypatch.setattr(client.anthropic, "Anthropic", lambda api_key: fake)

        first_stats = analyze.run_analysis(conn, cycle_id=env["cycle_id"])
        second_stats = analyze.run_analysis(conn, cycle_id=env["cycle_id"])

        count = conn.execute(
            select(table("analyses").c.id).where(table("analyses").c.story_key == "rerun-test")
        ).all()

    assert first_stats["analysis_succeeded"] == 1
    assert second_stats["analysis_storylines"] == 0
    assert len(count) == 1
    assert len(fake.messages.calls) == 1
