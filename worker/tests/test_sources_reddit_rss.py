from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from newswatch_worker.sources.base import SourceConfig
from newswatch_worker.sources import reddit_rss

FIXTURE = (Path(__file__).parent / "fixtures" / "sample_feed.xml").read_bytes()


def test_fetch_builds_subreddit_url_and_parses(local_http_server, base_url, monkeypatch):
    monkeypatch.setattr(reddit_rss, "BASE_URL", base_url)
    local_http_server.routes["/r/stocks/hot/.rss"] = (200, FIXTURE, "application/atom+xml")

    source = SourceConfig(
        id="s1", name="r/stocks", source_type="reddit_rss",
        config={"subreddit": "stocks", "listing": "hot", "limit": 25},
    )
    items = reddit_rss.RedditRssAdapter().fetch(source, since=datetime(2020, 1, 1, tzinfo=timezone.utc))

    assert len(items) == 3
