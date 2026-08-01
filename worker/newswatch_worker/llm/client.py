"""Anthropic API wrapper: key resolution, budget guard, spend ledger,
extended-thinking config, structured-output calls with one repair retry.

docs/04-llm-pipeline.md §1, §8; docs/02-architecture.md §8-9.

Deviation from docs/04 §1's literal spec (documented per CLAUDE.md's "if the
spec is wrong/impossible, say so and propose the fix"): the spec describes a
single fixed thinking-token-budget knob (off/2048/8192/16384) passed as
`thinking={"type": "enabled", "budget_tokens": N}`. That request shape is
rejected (400) by the current Claude Sonnet 5 / Opus 5 API — those models
only accept `{"type": "adaptive"}` or `{"type": "disabled"}` for `thinking`,
with depth controlled instead by `output_config.effort`
(low/medium/high/...). Claude Haiku 4.5 predates adaptive thinking and still
accepts the old fixed-budget shape. Rather than silently picking one shape
and breaking the other model family, this module resolves each model's
actual thinking capability via `client.models.retrieve()` and picks the
request shape that model supports, while preserving the spec's four
user-facing reasoning levels (off/low/medium/high) in settings and in the
Settings UI. Level -> concrete config mapping:
  - fixed-budget models (Haiku-class): off=disabled, low/medium/high -> the
    spec's literal budget_tokens (2048/8192/16384).
  - adaptive-thinking models (Sonnet/Opus-class): off=disabled,
    low/medium/high -> thinking={"type": "adaptive"} plus
    output_config.effort set to the matching level.
  - models reporting no thinking support at all: silently degrade to off,
    which the caller surfaces as a health-strip flag (docs/04 §1).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import anthropic
from pydantic import BaseModel, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.engine import Connection

from newswatch_worker.db import get_engine, table

logger = logging.getLogger(__name__)

MAX_OUTPUT_TOKENS = 4096

REASONING_LEVELS = ("off", "low", "medium", "high")
_FIXED_BUDGET_TOKENS = {"low": 2048, "medium": 8192, "high": 16384}


class BudgetExceededError(RuntimeError):
    """Month-to-date spend has reached settings['llm'].monthly_budget_usd."""


class UnknownModelPriceError(RuntimeError):
    """Model has no entry in settings['llm'].prices_per_mtok — refuse the call (fail closed)."""


class LlmCallFailedError(RuntimeError):
    """API call (and its one repair retry, if applicable) both failed."""


@dataclass(frozen=True)
class LlmSettings:
    available_models: list[str]
    tiers: dict[str, dict[str, str]]
    max_items_per_cycle: int
    monthly_budget_usd: float
    prices_per_mtok: dict[str, dict[str, float]]

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "LlmSettings":
        return cls(
            available_models=list(value["available_models"]),
            tiers=dict(value["tiers"]),
            max_items_per_cycle=int(value["max_items_per_cycle"]),
            monthly_budget_usd=float(value["monthly_budget_usd"]),
            prices_per_mtok=dict(value["prices_per_mtok"]),
        )

    def tier(self, name: str) -> tuple[str, str]:
        """Returns (model, reasoning_level) for a pipeline tier."""
        cfg = self.tiers[name]
        return cfg["model"], cfg["reasoning"]


def get_llm_settings(conn: Connection) -> LlmSettings:
    settings_t = table("settings")
    row = conn.execute(
        select(settings_t.c.value).where(settings_t.c.key == "llm")
    ).first()
    if row is None:
        raise RuntimeError("settings['llm'] is not seeded")
    return LlmSettings.from_json(row[0])


def resolve_api_key(conn: Connection) -> str | None:
    """DB row wins; falls back to ANTHROPIC_API_KEY env. Re-read on every
    call so Settings-UI key rotation needs no worker restart (docs/02 §9)."""
    secrets_t = table("secrets")
    row = conn.execute(
        select(secrets_t.c.value).where(secrets_t.c.key == "anthropic_api_key")
    ).first()
    if row is not None and row[0]:
        return row[0]
    return os.environ.get("ANTHROPIC_API_KEY")


def mark_key_status(status: str) -> None:
    """docs/04 §1: 'On 401, mark key invalid in health strip.' Scoped to the
    DB-stored key row only (WHERE key=...) — a no-op (0 rows) when the
    ANTHROPIC_API_KEY env fallback is in use, since there's no row to mark
    and the rotation flow this exists for is specifically the Settings UI's
    DB-stored key (docs/02 §9, PRD acceptance #7).

    Opens its OWN connection/transaction rather than taking the caller's
    `conn` — a 401 always propagates back up as an exception (see _create
    below), which rolls back whatever transaction it's raised inside
    (cycle.py's per-state `with engine.begin()` block). Writing through the
    caller's conn would make this status update vanish along with that
    rollback, exactly the "on 401, mark key invalid" behavior it exists to
    provide. Same reasoning as cycle.py's own error-recording, which is
    already commented "runs in its own transaction since the enclosing one
    is about to roll back."
    """
    engine = get_engine()
    secrets_t = table("secrets")
    with engine.begin() as status_conn:
        status_conn.execute(
            secrets_t.update()
            .where(secrets_t.c.key == "anthropic_api_key")
            .values(status=status, last_checked_at=datetime.now(timezone.utc))
        )


def month_to_date_spend(conn: Connection) -> float:
    spend_t = table("spend_mtd_v")
    row = conn.execute(select(spend_t.c.spend_usd)).first()
    return float(row[0]) if row is not None else 0.0


def check_budget(conn: Connection, llm_settings: LlmSettings) -> None:
    spend = month_to_date_spend(conn)
    if spend >= llm_settings.monthly_budget_usd:
        raise BudgetExceededError(
            f"month-to-date spend ${spend:.2f} >= cap ${llm_settings.monthly_budget_usd:.2f}"
        )


def price_for_model(llm_settings: LlmSettings, model: str) -> dict[str, float]:
    try:
        return llm_settings.prices_per_mtok[model]
    except KeyError:
        raise UnknownModelPriceError(
            f"model {model!r} has no prices_per_mtok entry; refusing call (fail closed)"
        ) from None


def compute_cost(prices: dict[str, float], input_tokens: int, output_tokens: int) -> float:
    return (input_tokens / 1_000_000) * prices["input"] + (output_tokens / 1_000_000) * prices["output"]


def record_spend(
    conn: Connection,
    *,
    cycle_id: str | None,
    purpose: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
) -> None:
    llm_calls_t = table("llm_calls")
    conn.execute(
        llm_calls_t.insert().values(
            cycle_id=cycle_id,
            purpose=purpose,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
        )
    )


@lru_cache(maxsize=32)
def _model_thinking_capability(api_key: str, model: str) -> str:
    """Returns 'adaptive' | 'fixed_budget' | 'none'. Cached per (key, model)
    for the process lifetime — capability doesn't change mid-run, and this
    call would otherwise add API round-trip latency to every single tier
    call. Degrades to 'none' on any error (unknown model, network hiccup,
    older SDK without .capabilities) rather than failing the cycle."""
    try:
        client = anthropic.Anthropic(api_key=api_key)
        info = client.models.retrieve(model)
        capabilities = getattr(info, "capabilities", None)
        thinking = getattr(capabilities, "thinking", None) if capabilities else None
        types = getattr(thinking, "types", None) if thinking else None
        if types is None:
            return "none"
        adaptive = getattr(types, "adaptive", None)
        if adaptive is not None and getattr(adaptive, "supported", False):
            return "adaptive"
        enabled = getattr(types, "enabled", None)
        if enabled is not None and getattr(enabled, "supported", False):
            return "fixed_budget"
        return "none"
    except Exception:
        logger.warning("thinking capability lookup failed for model=%s; degrading to none", model, exc_info=True)
        return "none"


def thinking_request_shape(api_key: str, model: str, reasoning: str) -> tuple[dict | None, str | None]:
    """Returns (thinking_param, effort_param) for a `.messages.create()` call.

    thinking_param is the dict for the `thinking` request field (or None to
    omit it entirely). effort_param is the string for
    `output_config.effort` (or None). Silently degrades reasoning to "off"
    (both None) when the model reports no thinking support, per docs/04 §1
    ("if the selected model doesn't support extended thinking, client.py
    silently degrades to off and flags it in the health strip" — the health
    strip flag is the caller's responsibility, this function just reports
    the degraded level via its return value being fully off).
    """
    if reasoning not in REASONING_LEVELS:
        raise ValueError(f"unknown reasoning level: {reasoning!r}")
    if reasoning == "off":
        return None, None

    capability = _model_thinking_capability(api_key, model)
    if capability == "none":
        return None, None
    if capability == "fixed_budget":
        return {"type": "enabled", "budget_tokens": _FIXED_BUDGET_TOKENS[reasoning]}, None
    # adaptive
    return {"type": "adaptive"}, reasoning


def reasoning_degraded(api_key: str, model: str, reasoning: str) -> bool:
    """True when the requested reasoning level could not be honored because
    the model has no thinking support — the caller should flag this in the
    health strip (docs/04 §1)."""
    if reasoning == "off":
        return False
    return _model_thinking_capability(api_key, model) == "none"


def _ensure_additional_properties_false(schema: dict) -> dict:
    """Pydantic v2's model_json_schema() doesn't set additionalProperties:
    false by default, but the API's structured-output json_schema format
    requires it on every object node. Walk the schema (incl. $defs) and set
    it wherever an object's properties are declared."""
    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node.setdefault("additionalProperties", False)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schema)
    return schema


def schema_for(model_cls: type[BaseModel]) -> dict:
    return _ensure_additional_properties_false(model_cls.model_json_schema())


def _response_text(message: anthropic.types.Message) -> str:
    return "".join(block.text for block in message.content if getattr(block, "type", None) == "text")


@dataclass
class StructuredCallResult:
    parsed: Any
    model: str
    input_tokens: int
    output_tokens: int
    repaired: bool


def call_structured(
    conn: Connection,
    *,
    cycle_id: str | None,
    purpose: str,
    model: str,
    reasoning: str,
    output_model: type[BaseModel],
    system: str,
    user_content: str,
    max_tokens: int = MAX_OUTPUT_TOKENS,
    temperature: float | None = None,
) -> StructuredCallResult | None:
    """Budget-checked structured call with one repair retry (docs/04 §8).

    Returns None (never raises) when both the primary call and the repair
    retry fail to produce valid JSON — callers mark the storyline/item as
    failed and continue the cycle, per spec. Raises BudgetExceededError /
    UnknownModelPriceError before making any network call, and re-raises
    genuine API errors (auth, connectivity) after the SDK's own built-in
    429/5xx retry has been exhausted, since those are cycle-level failures
    the caller must decide how to handle (docs/04 §8 "API 429/5xx" row).
    """
    llm_settings = get_llm_settings(conn)
    check_budget(conn, llm_settings)
    prices = price_for_model(llm_settings, model)

    api_key = resolve_api_key(conn)
    if not api_key:
        raise RuntimeError("no Anthropic API key configured (secrets table or ANTHROPIC_API_KEY)")

    client = anthropic.Anthropic(api_key=api_key)
    thinking, effort = thinking_request_shape(api_key, model, reasoning)
    schema = schema_for(output_model)
    output_config: dict[str, Any] = {
        "format": {"type": "json_schema", "schema": schema}
    }
    if effort is not None:
        output_config["effort"] = effort

    # The API requires budget_tokens < max_tokens for the fixed-budget
    # thinking shape. The spec's own "medium"/"high" budgets (8192/16384,
    # docs/04 §1) already exceed its own "max 4096 output tokens per call"
    # invariant, so the two are mutually contradictory for fixed-budget
    # (Haiku-class) models at those levels. Resolve by keeping max_tokens's
    # spec value as the answer-text allowance and adding the thinking
    # budget on top, rather than capping total output at 4096 regardless
    # of reasoning level.
    effective_max_tokens = max_tokens
    if thinking is not None and thinking.get("type") == "enabled":
        effective_max_tokens = thinking["budget_tokens"] + max_tokens

    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": effective_max_tokens,
        "system": system,
        "output_config": output_config,
    }
    if thinking is not None:
        kwargs["thinking"] = thinking
    elif temperature is not None:
        # docs/04 §1: temperature constraints apply only when thinking is
        # off — the API requires default temperature with extended thinking.
        kwargs["temperature"] = temperature

    messages = [{"role": "user", "content": user_content}]

    def _record(msg: anthropic.types.Message) -> None:
        cost = compute_cost(prices, msg.usage.input_tokens, msg.usage.output_tokens)
        record_spend(
            conn,
            cycle_id=cycle_id,
            purpose=purpose,
            model=model,
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
            cost_usd=cost,
        )

    def _create(**call_kwargs) -> anthropic.types.Message:
        # docs/04 §1: "on 401, mark key invalid in health strip." A 401 means
        # every subsequent call will fail too, so this re-raises rather than
        # retrying — cycle.py's generic exception handler leaves the cycle
        # resumable, same as any other unexpected failure.
        try:
            msg = client.messages.create(**call_kwargs)
        except anthropic.AuthenticationError:
            mark_key_status("invalid")
            raise
        mark_key_status("valid")
        return msg

    message = _create(messages=messages, **kwargs)
    _record(message)
    text_out = _response_text(message)

    try:
        parsed = TypeAdapter(output_model).validate_json(text_out)
        return StructuredCallResult(
            parsed=parsed,
            model=model,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            repaired=False,
        )
    except (ValidationError, ValueError) as exc:
        logger.warning("purpose=%s model=%s invalid JSON, issuing repair retry: %s", purpose, model, exc)
        messages.append({"role": "assistant", "content": text_out})
        messages.append(
            {
                "role": "user",
                "content": f"Your last output was invalid JSON: {exc}. Re-emit valid JSON only.",
            }
        )
        try:
            check_budget(conn, llm_settings)
            repair_message = _create(messages=messages, **kwargs)
        except BudgetExceededError:
            logger.warning("purpose=%s model=%s budget exhausted before repair retry", purpose, model)
            return None
        _record(repair_message)
        repair_text = _response_text(repair_message)
        try:
            parsed = TypeAdapter(output_model).validate_json(repair_text)
            return StructuredCallResult(
                parsed=parsed,
                model=model,
                input_tokens=repair_message.usage.input_tokens,
                output_tokens=repair_message.usage.output_tokens,
                repaired=True,
            )
        except (ValidationError, ValueError) as repair_exc:
            logger.error(
                "purpose=%s model=%s repair retry also failed, giving up: %s", purpose, model, repair_exc
            )
            return None
