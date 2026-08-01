from __future__ import annotations

from pathlib import Path

from newswatch_worker.polymarket import client as pm_client

FIXTURE = (Path(__file__).parent / "fixtures" / "sample_gamma_markets.json").read_bytes()


def test_parse_market_handles_string_encoded_outcome_fields():
    raw = {
        "conditionId": "0xaaa",
        "question": "Q?",
        "slug": "q",
        "tags": [{"label": "Economy"}],
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.62", "0.38"]',
        "volume24hr": 185000.5,
        "liquidity": 340000,
        "endDate": "2026-09-17T23:59:59Z",
        "active": True,
        "closed": False,
    }
    market = pm_client.parse_market(raw)
    assert market is not None
    assert market.id == "0xaaa"
    assert market.yes_price == 0.62
    assert market.category == "Economy"
    assert market.volume_24h_usd == 185000.5
    assert market.liquidity_usd == 340000
    assert market.active is True
    assert market.closed is False
    assert market.end_date is not None and market.end_date.year == 2026


def test_parse_market_handles_native_list_outcome_fields():
    raw = {
        "conditionId": "0xbbb",
        "question": "Q2?",
        "slug": "q2",
        "outcomes": ["Yes", "No"],
        "outcomePrices": [0.3, 0.7],
    }
    market = pm_client.parse_market(raw)
    assert market is not None
    assert market.yes_price == 0.3


def test_parse_market_returns_none_when_slug_missing():
    assert pm_client.parse_market({"conditionId": "x", "question": "q", "slug": ""}) is None


def test_get_markets_fetches_and_filters_unparseable_rows(local_http_server, base_url, monkeypatch):
    local_http_server.routes["/markets"] = (200, FIXTURE, "application/json")
    gamma = pm_client.GammaClient(base_url=base_url)

    markets = gamma.get_markets(limit=10)

    assert len(markets) == 2  # the third fixture row (empty slug) is dropped
    by_id = {m.id: m for m in markets}
    assert by_id["0xaaa111"].yes_price == 0.62
    assert by_id["0xbbb222"].yes_price == 0.3


def test_get_all_active_markets_stops_on_short_page(local_http_server, base_url):
    local_http_server.routes["/markets"] = (200, FIXTURE, "application/json")
    gamma = pm_client.GammaClient(base_url=base_url)

    markets = gamma.get_all_active_markets(cap=1000)

    assert len(markets) == 2
