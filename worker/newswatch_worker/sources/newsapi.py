"""NewsAPI.org adapter (docs/02-architecture.md §4, source_type='newsapi').

config: {"query": "...", "domains": ["reuters.com"], "language": "en"}
(docs/05-config-schema.md §4). Secret env var: NEWSAPI_KEY.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from newswatch_worker.sources.base import RawItem, SourceConfig, TestResult
from newswatch_worker.sources.http_client import polite_get

BASE_URL = "https://newsapi.org/v2/everything"


class NewsApiAuthError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get("NEWSAPI_KEY")
    if not key:
        raise NewsApiAuthError("NEWSAPI_KEY is not set")
    return key


def _build_url(source: SourceConfig, since: datetime) -> str:
    params: dict[str, str] = {
        "q": source.config["query"],
        "language": source.config.get("language", "en"),
        "sortBy": "publishedAt",
        "from": since.date().isoformat(),
        "apiKey": _api_key(),
    }
    domains = source.config.get("domains")
    if domains:
        params["domains"] = ",".join(domains)
    return f"{BASE_URL}?{urlencode(params)}"


def _article_to_raw_item(article: dict[str, Any]) -> RawItem:
    published_at = None
    if article.get("publishedAt"):
        text = article["publishedAt"]
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            published_at = datetime.fromisoformat(text)
        except ValueError:
            published_at = None
    summary = article.get("description")
    return RawItem(
        title=(article.get("title") or "").strip(),
        url=(article.get("url") or "").strip(),
        summary=summary,
        body_excerpt=(article.get("content") or summary or "")[:2000] or None,
        published_at=published_at,
        author=article.get("author"),
    )


class NewsApiAdapter:
    source_type = "newsapi"

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
        if payload.get("status") != "ok":
            raise ValueError(f"NewsAPI error: {payload.get('message', payload)}")
        items = [_article_to_raw_item(a) for a in payload.get("articles", [])]
        return [i for i in items if i.url and (i.published_at is None or i.published_at >= since)]

    def test(self, source: SourceConfig) -> TestResult:
        try:
            since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            items = self.fetch(source, since=since)
            return TestResult(
                ok=True, item_count=len(items), sample_titles=[i.title for i in items[:3]]
            )
        except Exception as exc:  # noqa: BLE001
            return TestResult(ok=False, error=str(exc))
