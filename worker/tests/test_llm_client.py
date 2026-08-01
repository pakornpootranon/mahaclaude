"""Unit tests for newswatch_worker.llm.client.

No live ANTHROPIC_API_KEY is available in this sandbox, so `.messages.create`
is exercised via a hand-built fake client rather than the real network call
(this is called out explicitly in the Phase 3 commit message as something
that could not be live-verified here). Budget-guard/spend-ledger/settings
plumbing runs against the real local Postgres, same pattern as test_ingest.py.
"""

from __future__ import annotations

import os

import pytest
from anthropic.types import Message, TextBlock, Usage
from pydantic import BaseModel

from newswatch_worker.llm import client

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")


class _Impact(BaseModel):
    sector: str
    strength: float


class _Result(BaseModel):
    story_key: str
    magnitude: float
    impacts: list[_Impact]


def _message(text: str, *, input_tokens: int = 10, output_tokens: int = 5) -> Message:
    return Message(
        id="msg_test",
        type="message",
        role="assistant",
        model="claude-haiku-4-5",
        content=[TextBlock(type="text", text=text)],
        stop_reason="end_turn",
        stop_sequence=None,
        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _auth_error() -> Exception:
    import httpx

    response = httpx.Response(
        401,
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
        json={"error": {"message": "invalid x-api-key"}},
    )
    return client.anthropic.AuthenticationError("invalid x-api-key", response=response, body=None)


class _FakeMessages:
    """Queues canned Message responses (or exceptions to raise), one per
    call.messages.create()."""

    def __init__(self, responses: list[Message | Exception]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _FakeAnthropicClient:
    def __init__(self, responses: list[Message]):
        self.messages = _FakeMessages(responses)


@pytest.fixture(autouse=True)
def _clear_capability_cache():
    client._model_thinking_capability.cache_clear()
    yield
    client._model_thinking_capability.cache_clear()


@pytest.fixture
def db_conn():
    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    llm_calls_t = table("llm_calls")

    with engine.begin() as conn:
        yield conn

    with engine.begin() as conn:
        # Delete by this file's test-only purpose values, not a
        # before/after ID diff: a diff-based cleanup permanently "loses"
        # any row that ever escapes cleanup once (e.g. a failed run) since
        # every later test's pre-test snapshot would then treat it as
        # legitimate pre-existing data and never touch it again.
        conn.execute(llm_calls_t.delete().where(llm_calls_t.c.purpose == "test"))


def test_llm_settings_reads_seeded_config(db_conn):
    settings = client.get_llm_settings(db_conn)
    assert settings.tiers["triage"]["reasoning"] == "off"
    assert settings.tiers["analysis"]["model"] == "claude-sonnet-5"
    assert "claude-sonnet-5" in settings.prices_per_mtok


def test_price_for_model_fails_closed_on_unknown_model(db_conn):
    settings = client.get_llm_settings(db_conn)
    with pytest.raises(client.UnknownModelPriceError):
        client.price_for_model(settings, "not-a-real-model")


def test_compute_cost_matches_per_mtok_prices():
    prices = {"input": 3.0, "output": 15.0}
    cost = client.compute_cost(prices, input_tokens=1_000_000, output_tokens=500_000)
    assert cost == pytest.approx(3.0 + 7.5)


def test_record_spend_then_month_to_date_reflects_it(db_conn):
    before = client.month_to_date_spend(db_conn)
    client.record_spend(
        db_conn,
        cycle_id=None,
        purpose="test",
        model="claude-haiku-4-5",
        input_tokens=1000,
        output_tokens=500,
        cost_usd=0.0035,
    )
    after = client.month_to_date_spend(db_conn)
    assert after == pytest.approx(before + 0.0035)


def test_check_budget_raises_once_spend_reaches_cap(db_conn):
    settings = client.get_llm_settings(db_conn)
    spend_needed = settings.monthly_budget_usd - client.month_to_date_spend(db_conn)
    client.record_spend(
        db_conn,
        cycle_id=None,
        purpose="test",
        model="claude-haiku-4-5",
        input_tokens=0,
        output_tokens=0,
        cost_usd=spend_needed,
    )
    with pytest.raises(client.BudgetExceededError):
        client.check_budget(db_conn, settings)


def test_resolve_api_key_falls_back_to_env_when_no_db_secret(db_conn, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env-fallback")
    assert client.resolve_api_key(db_conn) == "sk-ant-env-fallback"


def test_schema_for_sets_additional_properties_false_recursively():
    schema = client.schema_for(_Result)
    assert schema["additionalProperties"] is False
    impact_def = schema["$defs"]["_Impact"]
    assert impact_def["additionalProperties"] is False


def test_thinking_request_shape_off_omits_thinking_entirely(monkeypatch):
    thinking, effort = client.thinking_request_shape("fake-key", "claude-sonnet-5", "off")
    assert thinking is None
    assert effort is None


def test_thinking_request_shape_adaptive_model_uses_effort(monkeypatch):
    monkeypatch.setattr(client, "_model_thinking_capability", lambda key, model: "adaptive")
    thinking, effort = client.thinking_request_shape("fake-key", "claude-sonnet-5", "medium")
    assert thinking == {"type": "adaptive"}
    assert effort == "medium"


def test_thinking_request_shape_fixed_budget_model_uses_budget_tokens(monkeypatch):
    monkeypatch.setattr(client, "_model_thinking_capability", lambda key, model: "fixed_budget")
    thinking, effort = client.thinking_request_shape("fake-key", "claude-haiku-4-5", "high")
    assert thinking == {"type": "enabled", "budget_tokens": 16384}
    assert effort is None


def test_thinking_request_shape_degrades_silently_when_unsupported(monkeypatch):
    monkeypatch.setattr(client, "_model_thinking_capability", lambda key, model: "none")
    thinking, effort = client.thinking_request_shape("fake-key", "some-old-model", "high")
    assert thinking is None
    assert effort is None


def test_reasoning_degraded_true_only_when_requested_and_unsupported(monkeypatch):
    monkeypatch.setattr(client, "_model_thinking_capability", lambda key, model: "none")
    assert client.reasoning_degraded("fake-key", "m", "high") is True
    assert client.reasoning_degraded("fake-key", "m", "off") is False


def test_call_structured_parses_valid_json_on_first_try(db_conn, monkeypatch):
    fake = _FakeAnthropicClient([_message('{"story_key": "s1", "magnitude": 0.5, "impacts": []}')])
    monkeypatch.setattr(client.anthropic, "Anthropic", lambda api_key: fake)
    monkeypatch.setattr(client, "resolve_api_key", lambda conn: "sk-ant-fake")

    result = client.call_structured(
        db_conn,
        cycle_id=None,
        purpose="test",
        model="claude-haiku-4-5",
        reasoning="off",
        output_model=_Result,
        system="sys",
        user_content="analyze this",
    )

    assert result is not None
    assert result.parsed.story_key == "s1"
    assert result.repaired is False
    assert len(fake.messages.calls) == 1


def test_call_structured_repairs_once_on_invalid_json_then_succeeds(db_conn, monkeypatch):
    fake = _FakeAnthropicClient(
        [
            _message("not valid json at all"),
            _message('{"story_key": "s2", "magnitude": 0.3, "impacts": []}'),
        ]
    )
    monkeypatch.setattr(client.anthropic, "Anthropic", lambda api_key: fake)
    monkeypatch.setattr(client, "resolve_api_key", lambda conn: "sk-ant-fake")

    result = client.call_structured(
        db_conn,
        cycle_id=None,
        purpose="test",
        model="claude-haiku-4-5",
        reasoning="off",
        output_model=_Result,
        system="sys",
        user_content="analyze this",
    )

    assert result is not None
    assert result.parsed.story_key == "s2"
    assert result.repaired is True
    assert len(fake.messages.calls) == 2
    # repair turn must show the model its own bad output plus the exact
    # instruction text from docs/04 §8.
    repair_messages = fake.messages.calls[1]["messages"]
    assert repair_messages[1]["role"] == "assistant"
    assert repair_messages[1]["content"] == "not valid json at all"
    assert "Re-emit valid JSON only" in repair_messages[2]["content"]


def test_call_structured_gives_up_after_repair_also_fails(db_conn, monkeypatch):
    fake = _FakeAnthropicClient([_message("still not json"), _message("still not json either")])
    monkeypatch.setattr(client.anthropic, "Anthropic", lambda api_key: fake)
    monkeypatch.setattr(client, "resolve_api_key", lambda conn: "sk-ant-fake")

    result = client.call_structured(
        db_conn,
        cycle_id=None,
        purpose="test",
        model="claude-haiku-4-5",
        reasoning="off",
        output_model=_Result,
        system="sys",
        user_content="analyze this",
    )

    assert result is None
    assert len(fake.messages.calls) == 2


def test_call_structured_records_spend_for_every_real_call_made(db_conn, monkeypatch):
    fake = _FakeAnthropicClient(
        [
            _message("bad json", input_tokens=20, output_tokens=10),
            _message('{"story_key": "s3", "magnitude": 0.2, "impacts": []}', input_tokens=25, output_tokens=8),
        ]
    )
    monkeypatch.setattr(client.anthropic, "Anthropic", lambda api_key: fake)
    monkeypatch.setattr(client, "resolve_api_key", lambda conn: "sk-ant-fake")

    before = client.month_to_date_spend(db_conn)
    client.call_structured(
        db_conn,
        cycle_id=None,
        purpose="test",
        model="claude-haiku-4-5",
        reasoning="off",
        output_model=_Result,
        system="sys",
        user_content="analyze this",
    )
    after = client.month_to_date_spend(db_conn)

    settings = client.get_llm_settings(db_conn)
    prices = settings.prices_per_mtok["claude-haiku-4-5"]
    expected = client.compute_cost(prices, 20, 10) + client.compute_cost(prices, 25, 8)
    assert after == pytest.approx(before + expected)


def test_call_structured_raises_before_any_network_call_when_budget_exhausted(db_conn, monkeypatch):
    settings = client.get_llm_settings(db_conn)
    spend_needed = settings.monthly_budget_usd - client.month_to_date_spend(db_conn)
    client.record_spend(
        db_conn,
        cycle_id=None,
        purpose="test",
        model="claude-haiku-4-5",
        input_tokens=0,
        output_tokens=0,
        cost_usd=spend_needed,
    )

    fake = _FakeAnthropicClient([])
    monkeypatch.setattr(client.anthropic, "Anthropic", lambda api_key: fake)
    monkeypatch.setattr(client, "resolve_api_key", lambda conn: "sk-ant-fake")

    with pytest.raises(client.BudgetExceededError):
        client.call_structured(
            db_conn,
            cycle_id=None,
            purpose="test",
            model="claude-haiku-4-5",
            reasoning="off",
            output_model=_Result,
            system="sys",
            user_content="analyze this",
        )
    assert fake.messages.calls == []


def test_call_structured_raises_for_unpriced_model_before_calling_api(db_conn, monkeypatch):
    fake = _FakeAnthropicClient([])
    monkeypatch.setattr(client.anthropic, "Anthropic", lambda api_key: fake)
    monkeypatch.setattr(client, "resolve_api_key", lambda conn: "sk-ant-fake")

    with pytest.raises(client.UnknownModelPriceError):
        client.call_structured(
            db_conn,
            cycle_id=None,
            purpose="test",
            model="not-a-real-model",
            reasoning="off",
            output_model=_Result,
            system="sys",
            user_content="analyze this",
        )
    assert fake.messages.calls == []


@pytest.fixture
def secret_row():
    # mark_key_status() opens its own committed transaction (see its
    # docstring - status writes must survive the caller's transaction
    # rolling back on a 401), so this row needs to be genuinely committed
    # too, not inserted via db_conn's still-open transaction, or
    # mark_key_status's separate connection would never see it exists.
    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    secrets_t = table("secrets")
    with engine.begin() as conn:
        conn.execute(secrets_t.insert().values(key="anthropic_api_key", value="sk-ant-real-looking", last4="king"))
    yield
    with engine.begin() as conn:
        conn.execute(secrets_t.delete().where(secrets_t.c.key == "anthropic_api_key"))


def _secret_status(conn) -> str:
    from sqlalchemy import select

    from newswatch_worker.db import table

    secrets_t = table("secrets")
    return conn.execute(
        select(secrets_t.c.status).where(secrets_t.c.key == "anthropic_api_key")
    ).scalar_one()


def test_call_structured_marks_db_key_invalid_on_401(db_conn, monkeypatch, secret_row):
    fake = _FakeAnthropicClient([_auth_error()])
    monkeypatch.setattr(client.anthropic, "Anthropic", lambda api_key: fake)

    with pytest.raises(client.anthropic.AuthenticationError):
        client.call_structured(
            db_conn,
            cycle_id=None,
            purpose="test",
            model="claude-haiku-4-5",
            reasoning="off",
            output_model=_Result,
            system="sys",
            user_content="analyze this",
        )

    assert _secret_status(db_conn) == "invalid"


def test_call_structured_marks_db_key_valid_on_success(db_conn, monkeypatch, secret_row):
    from newswatch_worker.db import get_engine, table

    # Committed via a separate connection, not db_conn's still-open
    # transaction: mark_key_status() (called inside call_structured below)
    # opens its OWN transaction to update this same row, which would
    # otherwise block forever waiting on the row lock db_conn's
    # uncommitted UPDATE would be holding - a self-deadlock, since
    # db_conn's transaction only commits after this test function returns.
    secrets_t = table("secrets")
    with get_engine().begin() as setup_conn:
        setup_conn.execute(secrets_t.update().where(secrets_t.c.key == "anthropic_api_key").values(status="invalid"))

    fake = _FakeAnthropicClient([_message('{"story_key": "s1", "magnitude": 0.5, "impacts": []}')])
    monkeypatch.setattr(client.anthropic, "Anthropic", lambda api_key: fake)

    result = client.call_structured(
        db_conn,
        cycle_id=None,
        purpose="test",
        model="claude-haiku-4-5",
        reasoning="off",
        output_model=_Result,
        system="sys",
        user_content="analyze this",
    )

    assert result is not None
    assert _secret_status(db_conn) == "valid"


def test_mark_key_status_is_noop_when_using_env_fallback():
    # No secrets row inserted here - resolve_api_key would fall back to
    # ANTHROPIC_API_KEY. mark_key_status should affect zero rows, not error.
    client.mark_key_status("invalid")
