"""Polymarket Gamma API client (docs/02-architecture.md §2, docs/05 §3b):
read-only market data, no API key required.

Verification note (CLAUDE.md: "verify the Polymarket Gamma API endpoints ...
at implementation time"): this sandbox's outbound network policy blocks
direct HTTPS access to gamma-api.polymarket.com (only anthropic.com and
package registries are allowlisted), so the endpoint/field shapes below
could not be confirmed with a live call from here. They're cross-checked
against two independent sources instead: (1) Polymarket's own reference
client at github.com/Polymarket/agents (agents/polymarket/gamma.py +
agents/utils/objects.py's `Market`/`PolymarketEvent` pydantic models), which
is the most authoritative source reachable from this sandbox, and (2)
several third-party API write-ups that agree on the same field names. Parsing
below is deliberately defensive (JSON-string-or-native-list, missing fields
default sanely) so a minor shape mismatch degrades rather than crashes.
Flagged in the Phase 5b commit message as unverified-against-live-API, same
category of constraint as the RSS feed URLs in earlier phases.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from newswatch_worker.sources.http_client import polite_get

logger = logging.getLogger(__name__)

BASE_URL = "https://gamma-api.polymarket.com"
MAX_LIMIT = 500


@dataclass(frozen=True)
class PmMarketDTO:
    id: str
    question: str
    slug: str
    category: str | None
    end_date: datetime | None
    yes_price: float | None
    volume_24h_usd: float | None
    liquidity_usd: float | None
    active: bool
    closed: bool


def _parse_list_field(value: Any) -> list:
    """outcomes/outcomePrices/clobTokenIds ship as JSON-encoded strings on
    the real API per both cross-referenced sources, but this defends against
    an already-parsed list too rather than assuming one shape."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (ValueError, TypeError):
            return []
    return []


def _parse_end_date(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        logger.warning("polymarket: unparseable end date %r", raw)
        return None


def _yes_price(outcomes: list, prices: list) -> float | None:
    if not prices:
        return None
    idx = 0
    for i, outcome in enumerate(outcomes):
        if isinstance(outcome, str) and outcome.strip().lower() == "yes":
            idx = i
            break
    try:
        return float(prices[idx])
    except (IndexError, TypeError, ValueError):
        return None


def _category_from_tags(raw_market: dict) -> str | None:
    tags = raw_market.get("tags") or []
    for tag in tags:
        label = tag.get("label") if isinstance(tag, dict) else None
        if label:
            return str(label)
    return raw_market.get("category")


def parse_market(raw: dict) -> PmMarketDTO | None:
    market_id = raw.get("conditionId") or raw.get("id")
    question = raw.get("question")
    slug = raw.get("slug")
    if not market_id or not question or not slug:
        return None

    outcomes = _parse_list_field(raw.get("outcomes"))
    prices = _parse_list_field(raw.get("outcomePrices"))

    return PmMarketDTO(
        id=str(market_id),
        question=str(question),
        slug=str(slug),
        category=_category_from_tags(raw),
        end_date=_parse_end_date(raw.get("endDate")),
        yes_price=_yes_price(outcomes, prices),
        volume_24h_usd=_to_float(raw.get("volume24hr")),
        liquidity_usd=_to_float(raw.get("liquidity")),
        active=bool(raw.get("active", False)),
        closed=bool(raw.get("closed", False)),
    )


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class GammaClient:
    """Thin wrapper over GET /markets. Reuses the adapters' shared
    politeness/retry HTTP client (docs/02 §4) — a public read API deserves
    the same courtesy as the news sources."""

    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url

    def get_markets(
        self,
        *,
        active: bool = True,
        closed: bool = False,
        limit: int = 100,
        offset: int = 0,
        order: str = "volume24hr",
        ascending: bool = False,
    ) -> list[PmMarketDTO]:
        limit = min(limit, MAX_LIMIT)
        url = (
            f"{self.base_url}/markets?active={str(active).lower()}&closed={str(closed).lower()}"
            f"&limit={limit}&offset={offset}&order={order}&ascending={str(ascending).lower()}"
        )
        response = polite_get(url)
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError(f"unexpected Gamma /markets response shape: {type(payload)}")
        markets = []
        for raw in payload:
            parsed = parse_market(raw)
            if parsed is not None:
                markets.append(parsed)
        return markets

    def get_all_active_markets(self, *, cap: int = 1000) -> list[PmMarketDTO]:
        """Pages through /markets until `cap` is reached or a short page
        signals the end — used to refresh the full pm_markets snapshot that
        match.py's news-driven matching runs against (docs/04 §9)."""
        markets: list[PmMarketDTO] = []
        offset = 0
        while len(markets) < cap:
            page = self.get_markets(limit=MAX_LIMIT, offset=offset)
            markets.extend(page)
            if len(page) < MAX_LIMIT:
                break
            offset += MAX_LIMIT
        return markets[:cap]
