from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from newswatch_worker.sources.base import SourceConfig
from newswatch_worker.sources import finnhub

FIXTURE = (Path(__file__).parent / "fixtures" / "sample_finnhub.json").read_bytes()


def test_fetch_general_news(local_http_server, base_url, monkeypatch):
    monkeypatch.setattr(finnhub, "BASE_URL", base_url)
    monkeypatch.setenv("FINNHUB_KEY", "test-key")
    local_http_server.routes["/news"] = (200, FIXTURE, "application/json")

    source = SourceConfig(id="s1", name="Finnhub", source_type="finnhub", config={"category": "general"})
    items = finnhub.FinnhubAdapter().fetch(source, since=datetime(2020, 1, 1, tzinfo=timezone.utc))

    assert len(items) == 2
    assert {i.title for i in items} == {
        "OPEC+ agrees to extend production cuts through Q3",
        "Fed signals potential rate cut in September meeting",
    }


def test_fetch_company_news_uses_symbol_endpoint(local_http_server, base_url, monkeypatch):
    monkeypatch.setattr(finnhub, "BASE_URL", base_url)
    monkeypatch.setenv("FINNHUB_KEY", "test-key")
    local_http_server.routes["/company-news"] = (200, FIXTURE, "application/json")

    source = SourceConfig(id="s1", name="Finnhub AAPL", source_type="finnhub", config={"symbol": "AAPL"})
    items = finnhub.FinnhubAdapter().fetch(source, since=datetime(2020, 1, 1, tzinfo=timezone.utc))

    assert len(items) == 2


def test_fetch_raises_without_api_key(local_http_server, base_url, monkeypatch):
    monkeypatch.setattr(finnhub, "BASE_URL", base_url)
    monkeypatch.delenv("FINNHUB_KEY", raising=False)

    source = SourceConfig(id="s1", name="Finnhub", source_type="finnhub", config={"category": "general"})
    result = finnhub.FinnhubAdapter().test(source)

    assert result.ok is False
    assert "FINNHUB_KEY" in (result.error or "")
