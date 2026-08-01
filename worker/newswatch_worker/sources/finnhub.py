"""Finnhub News API adapter (docs/02-architecture.md §4, source_type='finnhub').

config: {"category": "general"} -> GET /news (general market news), or
        {"symbol": "AAPL"} -> GET /company-news (per docs/05-config-schema.md §4).
Secret env var: FINNHUB_KEY.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from newswatch_worker.sources.base import RawItem, SourceConfig, TestResult
from newswatch_worker.sources.http_client import polite_get

BASE_URL = "https://finnhub.io/api/v1"


class FinnhubAuthError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get("FINNHUB_KEY")
    if not key:
        raise FinnhubAuthError("FINNHUB_KEY is not set")
    return key


def _build_url(source: SourceConfig, since: datetime) -> str:
    key = _api_key()
    if "symbol" in source.config:
        date_from = since.date().isoformat()
        date_to = datetime.now(timezone.utc).date().isoformat()
        return (
            f"{BASE_URL}/company-news?symbol={source.config['symbol']}"
            f"&from={date_from}&to={date_to}&token={key}"
        )
    category = source.config.get("category", "general")
    return f"{BASE_URL}/news?category={category}&token={key}"


def _item_to_raw_item(item: dict[str, Any]) -> RawItem:
    published_at = None
    if item.get("datetime"):
        published_at = datetime.fromtimestamp(item["datetime"], tz=timezone.utc)
    summary = item.get("summary")
    return RawItem(
        title=(item.get("headline") or "").strip(),
        url=(item.get("url") or "").strip(),
        summary=summary,
        body_excerpt=(summary or "")[:2000] or None,
        published_at=published_at,
    )


class FinnhubAdapter:
    source_type = "finnhub"

    def fetch(
        self,
        source: SourceConfig,
        since: datetime,
        *,
        topics: list[dict[str, Any]] | None = None,
    ) -> list[RawItem]:
        url = _build_url(source, since)
        response = polite_get(url)
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError(f"unexpected Finnhub response shape: {type(payload)}")
        items = [_item_to_raw_item(i) for i in payload]
        return [i for i in items if i.url and (i.published_at is None or i.published_at >= since)]

    def test(self, source: SourceConfig) -> TestResult:
        try:
            since = datetime.now(timezone.utc) - timedelta(days=7)
            items = self.fetch(source, since=since)
            return TestResult(
                ok=True, item_count=len(items), sample_titles=[i.title for i in items[:3]]
            )
        except Exception as exc:  # noqa: BLE001
            return TestResult(ok=False, error=str(exc))
