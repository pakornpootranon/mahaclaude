from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from newswatch_worker.sources.base import SourceConfig
from newswatch_worker.sources.rss import RssAdapter

FIXTURE = (Path(__file__).parent / "fixtures" / "sample_feed.xml").read_bytes()


def test_fetch_parses_all_entries(local_http_server, base_url):
    local_http_server.routes["/feed.xml"] = (200, FIXTURE, "application/rss+xml")
    source = SourceConfig(id="s1", name="Sample Feed", source_type="rss", config={"url": f"{base_url}/feed.xml"})

    items = RssAdapter().fetch(source, since=datetime(2020, 1, 1, tzinfo=timezone.utc))

    assert len(items) == 3
    titles = {i.title for i in items}
    assert "OPEC+ agrees to extend production cuts through Q3" in titles


def test_fetch_strips_tracking_params_are_preserved_in_raw_url(local_http_server, base_url):
    # Canonicalization happens in dedupe.py, not the adapter — the adapter
    # should hand back the URL exactly as published.
    local_http_server.routes["/feed.xml"] = (200, FIXTURE, "application/rss+xml")
    source = SourceConfig(id="s1", name="Sample Feed", source_type="rss", config={"url": f"{base_url}/feed.xml"})

    items = RssAdapter().fetch(source, since=datetime(2020, 1, 1, tzinfo=timezone.utc))

    opec_item = next(i for i in items if "OPEC" in i.title)
    assert "utm_source=newsletter" in opec_item.url


def test_fetch_filters_by_since(local_http_server, base_url):
    local_http_server.routes["/feed.xml"] = (200, FIXTURE, "application/rss+xml")
    source = SourceConfig(id="s1", name="Sample Feed", source_type="rss", config={"url": f"{base_url}/feed.xml"})

    since = datetime(2026, 7, 1, 8, 45, tzinfo=timezone.utc)
    items = RssAdapter().fetch(source, since=since)

    assert len(items) == 1
    assert "OPEC" in items[0].title


def test_test_method_reports_sample_titles(local_http_server, base_url):
    local_http_server.routes["/feed.xml"] = (200, FIXTURE, "application/rss+xml")
    source = SourceConfig(id="s1", name="Sample Feed", source_type="rss", config={"url": f"{base_url}/feed.xml"})

    result = RssAdapter().test(source)

    assert result.ok is True
    assert result.item_count == 3
    assert len(result.sample_titles) == 3


def test_test_method_reports_error_on_404(local_http_server, base_url):
    source = SourceConfig(id="s1", name="Missing", source_type="rss", config={"url": f"{base_url}/missing.xml"})

    result = RssAdapter().test(source)

    assert result.ok is False
    assert result.error is not None
