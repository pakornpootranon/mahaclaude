"""Generic RSS/Atom adapter (docs/02-architecture.md §4, source_type='rss')."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import feedparser

from newswatch_worker.sources.base import RawItem, SourceConfig, TestResult
from newswatch_worker.sources.http_client import polite_get


def _parse_entry_published(entry: Any) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            return datetime(*value[:6], tzinfo=timezone.utc)
    return None


def entry_to_raw_item(entry: Any) -> RawItem:
    summary = entry.get("summary")
    return RawItem(
        title=(entry.get("title") or "").strip(),
        url=(entry.get("link") or "").strip(),
        summary=summary,
        body_excerpt=(summary or "")[:2000] or None,
        published_at=_parse_entry_published(entry),
        author=entry.get("author"),
    )


def fetch_feed(url: str, since: datetime) -> list[RawItem]:
    response = polite_get(url)
    parsed = feedparser.parse(response.content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"failed to parse feed at {url}: {parsed.bozo_exception}")
    items = [entry_to_raw_item(e) for e in parsed.entries]
    return [i for i in items if i.url and (i.published_at is None or i.published_at >= since)]


class RssAdapter:
    source_type = "rss"

    def fetch(
        self,
        source: SourceConfig,
        since: datetime,
        *,
        topics: list[dict[str, Any]] | None = None,
        secret: str | None = None,
    ) -> list[RawItem]:
        return fetch_feed(source.config["url"], since)

    def test(self, source: SourceConfig, *, secret: str | None = None) -> TestResult:
        try:
            items = self.fetch(source, since=datetime.min.replace(tzinfo=timezone.utc))
            return TestResult(
                ok=True, item_count=len(items), sample_titles=[i.title for i in items[:3]]
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the Test button, not re-raised
            return TestResult(ok=False, error=str(exc))
