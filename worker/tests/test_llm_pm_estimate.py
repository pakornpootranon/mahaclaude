from __future__ import annotations

import os

import pytest
from anthropic.types import Message, TextBlock, Usage

from newswatch_worker.llm import client, pm_estimate

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


def test_render_market_input_includes_price_and_category():
    market = pm_estimate.MarketInput(
        market_id="0xabc", question="Will X happen?", market_price=0.42, end_date="2026-09-01T00:00:00Z", category="Economy"
    )
    rendered = pm_estimate.render_market_input(market)
    assert "market_price: 0.42" in rendered
    assert "category: Economy" in rendered
    assert "Will X happen?" in rendered


def test_render_storylines_empty_and_populated():
    assert pm_estimate.render_storylines([]) == "(none)"
    rendered = pm_estimate.render_storylines(["a: b"])
    assert rendered == "- a: b"


def test_estimate_probability_calls_client_and_parses(monkeypatch):
    from newswatch_worker.db import get_engine, table

    monkeypatch.setattr(client, "resolve_api_key", lambda conn: "sk-ant-fake")

    response_json = (
        '{"market_id": "0xabc", "skip": false, "skip_reason": null, "est_probability": 0.65, '
        '"confidence": 0.6, "reasoning": "Base rates favor this.", "key_uncertainties": "polling noise"}'
    )
    fake = _FakeAnthropicClient([_message(response_json)])
    monkeypatch.setattr(client.anthropic, "Anthropic", lambda api_key: fake)

    market = pm_estimate.MarketInput(
        market_id="0xabc", question="Will X happen?", market_price=0.5, end_date=None, category=None
    )

    engine = get_engine()
    with engine.begin() as conn:
        result = pm_estimate.estimate_probability(
            conn,
            cycle_id=None,
            market=market,
            storylines=["some-story: relevant context (magnitude=0.5, confidence=0.6)"],
            model="claude-sonnet-5",
            reasoning="off",
            today="2026-08-01 (Saturday)",
        )
        conn.execute(table("llm_calls").delete().where(table("llm_calls").c.purpose == "pm_estimate"))

    assert result is not None
    assert result.parsed.est_probability == pytest.approx(0.65)
    assert result.parsed.skip is False

    sent_system = fake.messages.calls[0]["system"]
    assert "2026-08-01 (Saturday)" in sent_system
    assert "some-story: relevant context" in sent_system
