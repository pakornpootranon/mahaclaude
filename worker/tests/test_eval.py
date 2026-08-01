"""Mechanical test of the eval harness plumbing (newswatch_worker.eval)
against real local Postgres with a fake Anthropic client. This does NOT
verify real model drift (no live ANTHROPIC_API_KEY in this sandbox) - see
the Phase 3 commit message - it only proves run_eval/_grade_*/print_drift_report
wire together correctly: a fixture whose fake response matches expectations
grades PASS, and one that doesn't grades FAIL with a useful note.

The real golden_fixtures.json (16 fixtures, docs/04 §10) is exercised
end-to-end by `make eval` against the live API once a key is configured.
"""

from __future__ import annotations

import os

import pytest
from anthropic.types import Message, TextBlock, Usage

from newswatch_worker import eval as eval_mod
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


_FIXTURES = [
    {
        "id": "mechanical-relevant",
        "input": {"source": "Reuters", "title": "OPEC+ agrees to extend production cuts", "summary": "s", "body_excerpt": "b"},
        "expected_triage": {"relevant": True, "matched_topic_names": []},
        "expected_analysis": {
            "event_polarity": 1,
            "magnitude": 0.5,
            "confidence": 0.7,
            "matched_topic_names": [],
            "impacts": [],
        },
    },
    {
        "id": "mechanical-irrelevant",
        "input": {"source": "r/stocks", "title": "5 stocks to watch", "summary": "s", "body_excerpt": "b"},
        "expected_triage": {"relevant": False, "matched_topic_names": []},
    },
]


def test_run_eval_grades_matching_fixture_pass_and_mismatched_fixture_fail(monkeypatch):
    from newswatch_worker.db import get_engine

    monkeypatch.setattr(eval_mod, "load_fixtures", lambda: _FIXTURES)
    monkeypatch.setattr(client, "resolve_api_key", lambda conn: "sk-ant-fake")

    # First fixture: relevant, and the analysis response exactly matches
    # expected_analysis -> should grade PASS on both triage and analysis.
    triage_response_1 = '{"items": [{"idx": 0, "relevant": true, "matched_topic_ids": [], "story_key": "s1"}]}'
    analysis_response_1 = (
        '{"story_key": "s1", "matched_topics": [], "event_polarity": 1, "magnitude": 0.5, '
        '"confidence": 0.7, "horizon": "weeks", "impacts": [], "unmapped_sectors": [], '
        '"reasoning": "test", "caveats": ""}'
    )
    # Second fixture: expected irrelevant, but the fake model says relevant -> FAIL.
    triage_response_2 = '{"items": [{"idx": 0, "relevant": true, "matched_topic_ids": [], "story_key": "s2"}]}'
    analysis_response_2 = (
        '{"story_key": "s2", "matched_topics": [], "event_polarity": 0, "magnitude": 0.1, '
        '"confidence": 0.1, "horizon": "days", "impacts": [], "unmapped_sectors": [], '
        '"reasoning": "test", "caveats": ""}'
    )

    fake = _FakeAnthropicClient(
        [_message(triage_response_1), _message(analysis_response_1), _message(triage_response_2), _message(analysis_response_2)]
    )
    monkeypatch.setattr(client.anthropic, "Anthropic", lambda api_key: fake)

    from newswatch_worker.db import table

    engine = get_engine()
    with engine.begin() as conn:
        reports = eval_mod.run_eval(conn)
        conn.execute(table("llm_calls").delete().where(table("llm_calls").c.purpose.in_(["eval_triage", "eval_analysis"])))

    by_id = {r.fixture_id: r for r in reports}
    assert by_id["mechanical-relevant"].passed is True
    assert by_id["mechanical-irrelevant"].passed is False
    assert any("relevant" in note for note in by_id["mechanical-irrelevant"].triage_notes)

    all_passed = eval_mod.print_drift_report(reports)
    assert all_passed is False


_PM_FIXTURES = [
    {
        "id": "mechanical-pm-match",
        "input": {"question": "Will X happen?", "market_price": 0.5, "end_date": None, "category": None},
        "expected": {"skip": False, "est_probability": 0.6, "confidence_min": 0.5},
    },
    {
        "id": "mechanical-pm-skip-mismatch",
        "input": {"question": "Ambiguous question?", "market_price": 0.5, "end_date": None, "category": None},
        "expected": {"skip": True},
    },
]


def test_run_pm_eval_grades_matching_fixture_pass_and_mismatched_fixture_fail(monkeypatch):
    from newswatch_worker.db import get_engine

    monkeypatch.setattr(eval_mod, "load_pm_fixtures", lambda: _PM_FIXTURES)
    monkeypatch.setattr(client, "resolve_api_key", lambda conn: "sk-ant-fake")

    response_1 = (
        '{"market_id": "eval-mechanical-pm-match", "skip": false, "skip_reason": null, '
        '"est_probability": 0.62, "confidence": 0.6, "reasoning": "test", "key_uncertainties": ""}'
    )
    # Second fixture expects skip=true, but the fake model says skip=false -> FAIL.
    response_2 = (
        '{"market_id": "eval-mechanical-pm-skip-mismatch", "skip": false, "skip_reason": null, '
        '"est_probability": 0.5, "confidence": 0.5, "reasoning": "test", "key_uncertainties": ""}'
    )
    fake = _FakeAnthropicClient([_message(response_1), _message(response_2)])
    monkeypatch.setattr(client.anthropic, "Anthropic", lambda api_key: fake)

    from newswatch_worker.db import table

    engine = get_engine()
    with engine.begin() as conn:
        reports = eval_mod.run_pm_eval(conn)
        conn.execute(table("llm_calls").delete().where(table("llm_calls").c.purpose == "pm_estimate"))

    by_id = {r.fixture_id: r for r in reports}
    assert by_id["mechanical-pm-match"].passed is True
    assert by_id["mechanical-pm-skip-mismatch"].passed is False
    assert any("skip" in note for note in by_id["mechanical-pm-skip-mismatch"].notes)

    all_passed = eval_mod.print_pm_drift_report(reports)
    assert all_passed is False
