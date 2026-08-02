"""Reddit subreddit RSS adapter (docs/02-architecture.md §4,
source_type='reddit_rss'). Reddit's subreddit .rss endpoint is a standard
Atom feed, so this just builds the URL and delegates parsing to rss.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from newswatch_worker.sources.base import RawItem, SourceConfig, TestResult
from newswatch_worker.sources.rss import fetch_feed

BASE_URL = "https://www.reddit.com"


def _feed_url(source: SourceConfig) -> str:
    subreddit = source.config["subreddit"]
    listing = source.config.get("listing", "hot")
    limit = source.config.get("limit", 25)
    return f"{BASE_URL}/r/{subreddit}/{listing}/.rss?limit={limit}"


class RedditRssAdapter:
    source_type = "reddit_rss"

    def fetch(
        self,
        source: SourceConfig,
        since: datetime,
        *,
        topics: list[dict[str, Any]] | None = None,
        secret: str | None = None,
    ) -> list[RawItem]:
        return fetch_feed(_feed_url(source), since)

    def test(self, source: SourceConfig, *, secret: str | None = None) -> TestResult:
        try:
            items = self.fetch(source, since=datetime.min.replace(tzinfo=timezone.utc))
            return TestResult(
                ok=True, item_count=len(items), sample_titles=[i.title for i in items[:3]]
            )
        except Exception as exc:  # noqa: BLE001
            return TestResult(ok=False, error=str(exc))
