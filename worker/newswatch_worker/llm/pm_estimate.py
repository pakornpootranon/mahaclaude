"""Tier 4 — Polymarket probability estimation (docs/04-llm-pipeline.md §9).

System prompt is verbatim from the spec (CLAUDE.md: "prompts verbatim from
docs/04"), with `{today}` and `{storylines}` filled in the same way triage/
analyze/digest fill their own template placeholders.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel
from sqlalchemy.engine import Connection

from newswatch_worker.llm import client

PROMPT_VERSION = "pm-estimate-v1"

SYSTEM_PROMPT_TEMPLATE = """You are a forecaster estimating the true probability of a prediction-market question for a
personal advisory dashboard (NOT betting advice; nothing is executed automatically).

Rules:
- Estimate P(YES) as a decimal 0–1 based ONLY on: the question text and resolution criteria,
  today's date, the provided recent news storylines (if any), and well-established base rates.
- Do NOT anchor on the current market price; you will be shown it only as "market_price" and
  must form your estimate before comparing.
- confidence 0–1: how well-informed your estimate is. Cap at 0.5 when the question hinges on
  information you plausibly lack (private polls, insider process, very recent events not in
  the provided news). Questions with ambiguous resolution criteria: set skip=true.
- reasoning: 2–4 sentences citing the decisive factors. Shown to the user verbatim.

## Today
{today}

## Related news storylines from this cycle (may be empty)
{storylines}"""


class PmEstimate(BaseModel):
    market_id: str
    skip: bool
    skip_reason: str | None = None
    est_probability: float
    confidence: float
    reasoning: str
    key_uncertainties: str = ""


@dataclass(frozen=True)
class MarketInput:
    """Deliberately DB-row-agnostic (a plain dataclass, not a SQLAlchemy
    row) so eval.py can build one directly from a fixture without needing a
    live pm_markets row, and scan.py can build one from a refreshed
    PmMarketDTO."""

    market_id: str
    question: str
    market_price: float
    end_date: str | None
    category: str | None


def render_storylines(storylines: list[str]) -> str:
    if not storylines:
        return "(none)"
    return "\n".join(f"- {s}" for s in storylines)


def render_market_input(market: MarketInput) -> str:
    lines = [
        f"market_id: {market.market_id}",
        f"question: {market.question}",
        f"market_price: {market.market_price}",
    ]
    if market.category:
        lines.append(f"category: {market.category}")
    if market.end_date:
        lines.append(f"resolves: {market.end_date}")
    return "\n".join(lines)


def estimate_probability(
    conn: Connection,
    *,
    cycle_id: str | None,
    market: MarketInput,
    storylines: list[str],
    model: str,
    reasoning: str,
    today: str,
) -> client.StructuredCallResult | None:
    system = SYSTEM_PROMPT_TEMPLATE.format(today=today, storylines=render_storylines(storylines))
    return client.call_structured(
        conn,
        cycle_id=cycle_id,
        purpose="pm_estimate",
        model=model,
        reasoning=reasoning,
        output_model=PmEstimate,
        system=system,
        user_content=render_market_input(market),
        temperature=0.0,
    )
