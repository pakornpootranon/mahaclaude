from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from newswatch_worker.sources.base import SourceConfig
from newswatch_worker.sources import newsapi

FIXTURE = (Path(__file__).parent / "fixtures" / "sample_newsapi.json").read_bytes()


def test_fetch_articles(local_http_server, base_url, monkeypatch):
    monkeypatch.setattr(newsapi, "BASE_URL", f"{base_url}/v2/everything")
    monkeypatch.setenv("NEWSAPI_KEY", "test-key")
    local_http_server.routes["/v2/everything"] = (200, FIXTURE, "application/json")

    source = SourceConfig(
        id="s1",
        name="NewsAPI",
        source_type="newsapi",
        config={"query": "OPEC OR oil supply", "domains": ["reuters.com"], "language": "en"},
    )
    items = newsapi.NewsApiAdapter().fetch(source, since=datetime(2020, 1, 1, tzinfo=timezone.utc))

    assert len(items) == 2
    assert items[0].author in ("Jane Doe", "John Smith")


def test_fetch_raises_on_status_error(local_http_server, base_url, monkeypatch):
    monkeypatch.setattr(newsapi, "BASE_URL", f"{base_url}/v2/everything")
    monkeypatch.setenv("NEWSAPI_KEY", "test-key")
    error_body = b'{"status": "error", "code": "rateLimited", "message": "You have exceeded your rate limit"}'
    local_http_server.routes["/v2/everything"] = (200, error_body, "application/json")

    source = SourceConfig(id="s1", name="NewsAPI", source_type="newsapi", config={"query": "test"})
    result = newsapi.NewsApiAdapter().test(source)

    assert result.ok is False
    assert "rate limit" in (result.error or "").lower()
