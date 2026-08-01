"""Tests for newswatch_worker.outcomes against real local Postgres, with a
fake yfinance Ticker and a monkeypatched Gamma client (no live network
access to either in this sandbox)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from sqlalchemy import select

from newswatch_worker import outcomes
from newswatch_worker.polymarket.client import PmMarketDTO
from newswatch_worker.polymarket.client import GammaClient

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")


# ---- pure function tests (no DB) ----------------------------------------


def test_pct_return_computes_percentage():
    assert outcomes._pct_return(100.0, 105.0) == pytest.approx(5.0)
    assert outcomes._pct_return(100.0, 95.0) == pytest.approx(-5.0)
    assert outcomes._pct_return(100.0, None) is None


def test_direction_hit_buy_and_sell():
    assert outcomes._direction_hit("BUY", 2.0) is True
    assert outcomes._direction_hit("BUY", -2.0) is False
    assert outcomes._direction_hit("SELL", -2.0) is True
    assert outcomes._direction_hit("SELL", 2.0) is False


def test_direction_hit_watch_is_none():
    assert outcomes._direction_hit("WATCH", 5.0) is None
    assert outcomes._direction_hit("BUY", None) is None


# ---- DB fixtures ----------------------------------------------------------


@pytest.fixture
def env():
    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    marker = uuid.uuid4().hex[:8]
    sources_t = table("sources")
    topics_t = table("topics")
    cycles_t = table("cycles")
    news_items_t = table("news_items")
    analyses_t = table("analyses")

    with engine.begin() as conn:
        source_id = conn.execute(
            sources_t.insert()
            .values(name=f"test-outcomes-src-{marker}", source_type="rss", config={"url": "http://example.com/feed"}, enabled=False)
            .returning(sources_t.c.id)
        ).scalar_one()
        topic_id = conn.execute(
            topics_t.insert()
            .values(name=f"test-outcomes-topic-{marker}", description="d", keywords=[], sensitivity=0.5, enabled=True)
            .returning(topics_t.c.id)
        ).scalar_one()
        cycle_id = conn.execute(
            cycles_t.insert()
            .values(scheduled_for=datetime.now(timezone.utc), kind="manual", state="TRIGGERING", stats={})
            .returning(cycles_t.c.id)
        ).scalar_one()
        item_id = conn.execute(
            news_items_t.insert()
            .values(
                source_id=source_id, dedupe_key=uuid.uuid4().hex, url=f"https://example.com/{uuid.uuid4().hex}",
                title="t", summary="t", triage_status="relevant", story_key=f"story-{marker}", matched_topic_ids=[],
            )
            .returning(news_items_t.c.id)
        ).scalar_one()
        analysis_id = conn.execute(
            analyses_t.insert()
            .values(
                cycle_id=cycle_id, story_key=f"story-{marker}", primary_item_id=item_id, prompt_version="analyze-v1",
                model="test", result={}, event_polarity=1, magnitude=0.5, confidence=0.7,
            )
            .returning(analyses_t.c.id)
        ).scalar_one()

    yield {"source_id": str(source_id), "topic_id": str(topic_id), "cycle_id": str(cycle_id), "analysis_id": str(analysis_id), "marker": marker}

    with engine.begin() as conn:
        conn.execute(table("outcomes").delete().where(table("outcomes").c.recommendation_id.in_(
            select(table("recommendations").c.id).where(table("recommendations").c.cycle_id == cycle_id)
        )))
        conn.execute(table("recommendations").delete().where(table("recommendations").c.cycle_id == cycle_id))
        conn.execute(table("pm_opportunities").delete().where(table("pm_opportunities").c.cycle_id == cycle_id))
        conn.execute(table("pm_markets").delete().where(table("pm_markets").c.id.like(f"test-{marker}-%")))
        conn.execute(table("analyses").delete().where(table("analyses").c.cycle_id == cycle_id))
        conn.execute(table("news_items").delete().where(table("news_items").c.source_id == source_id))
        conn.execute(table("cycles").delete().where(table("cycles").c.id == cycle_id))
        conn.execute(table("topics").delete().where(table("topics").c.id == topic_id))
        conn.execute(table("sources").delete().where(table("sources").c.id == source_id))


def _insert_recommendation(conn, *, env, ticker, action, created_at, dedupe_key):
    from newswatch_worker.db import table

    recommendations_t = table("recommendations")
    return str(
        conn.execute(
            recommendations_t.insert()
            .values(
                cycle_id=env["cycle_id"], analysis_id=env["analysis_id"], topic_id=env["topic_id"],
                dedupe_key=dedupe_key, action=action, market="US", sector="Energy",
                tickers=[ticker] if ticker else [], confidence=0.7, reasoning="r", rule_trace={},
                created_at=created_at,
            )
            .returning(recommendations_t.c.id)
        ).scalar_one()
    )


def _price_history(start: datetime, closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range(start=start.date(), periods=len(closes), freq="B", tz="UTC")
    return pd.DataFrame({"Close": closes}, index=idx)


# ---- stock outcomes -------------------------------------------------------


def test_run_outcomes_job_populates_returns_and_hit_flags_for_backdated_buy(env, monkeypatch):
    from newswatch_worker.db import get_engine, table

    created_at = datetime.now(timezone.utc) - timedelta(days=10)
    closes = [100.0, 102.0, 101.0, 103.0, 104.0, 105.0, 106.0, 110.0]  # entry=100, T+1=102, T+3=103, T+7=110
    hist = _price_history(created_at, closes)

    class _FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, start=None, end=None):
            return hist

    monkeypatch.setattr(outcomes.yf, "Ticker", _FakeTicker)
    monkeypatch.setattr(outcomes.GammaClient, "get_market_by_id", lambda self, market_id: None)

    engine = get_engine()
    with engine.begin() as conn:
        rec_id = _insert_recommendation(
            conn, env=env, ticker="AAPL", action="BUY", created_at=created_at, dedupe_key=f"dedupe-buy-{env['marker']}"
        )
        stats = outcomes.run_outcomes_job(conn)

        row = conn.execute(
            select(table("outcomes").c.entry_price, table("outcomes").c.ret_1d, table("outcomes").c.ret_7d,
                   table("outcomes").c.hit_1d, table("outcomes").c.hit_7d, table("outcomes").c.status)
            .where(table("outcomes").c.recommendation_id == rec_id)
        ).first()

    assert stats["recommendations_checked"] == 1
    assert stats["recommendations_complete"] == 1
    assert float(row.entry_price) == pytest.approx(100.0)
    assert float(row.ret_1d) == pytest.approx(2.0)
    assert float(row.ret_7d) == pytest.approx(10.0)
    assert row.hit_1d is True
    assert row.hit_7d is True
    assert row.status == "complete"


def test_run_outcomes_job_direction_adjusts_hit_for_sell(env, monkeypatch):
    from newswatch_worker.db import get_engine, table

    created_at = datetime.now(timezone.utc) - timedelta(days=10)
    closes = [100.0, 90.0, 89.0, 88.0, 87.0, 86.0, 85.0, 80.0]  # falling price -> SELL should hit
    hist = _price_history(created_at, closes)

    class _FakeTicker:
        def __init__(self, symbol):
            pass

        def history(self, start=None, end=None):
            return hist

    monkeypatch.setattr(outcomes.yf, "Ticker", _FakeTicker)
    monkeypatch.setattr(outcomes.GammaClient, "get_market_by_id", lambda self, market_id: None)

    engine = get_engine()
    with engine.begin() as conn:
        rec_id = _insert_recommendation(
            conn, env=env, ticker="JETS", action="SELL", created_at=created_at, dedupe_key=f"dedupe-sell-{env['marker']}"
        )
        outcomes.run_outcomes_job(conn)
        row = conn.execute(
            select(table("outcomes").c.hit_1d, table("outcomes").c.hit_7d).where(table("outcomes").c.recommendation_id == rec_id)
        ).first()

    assert row.hit_1d is True
    assert row.hit_7d is True


def test_run_outcomes_job_watch_recommendation_has_no_hit_verdict(env, monkeypatch):
    from newswatch_worker.db import get_engine, table

    created_at = datetime.now(timezone.utc) - timedelta(days=10)
    closes = [100.0, 102.0, 101.0, 103.0, 104.0, 105.0, 106.0, 110.0]
    hist = _price_history(created_at, closes)

    class _FakeTicker:
        def __init__(self, symbol):
            pass

        def history(self, start=None, end=None):
            return hist

    monkeypatch.setattr(outcomes.yf, "Ticker", _FakeTicker)
    monkeypatch.setattr(outcomes.GammaClient, "get_market_by_id", lambda self, market_id: None)

    engine = get_engine()
    with engine.begin() as conn:
        rec_id = _insert_recommendation(
            conn, env=env, ticker="XLE", action="WATCH", created_at=created_at, dedupe_key=f"dedupe-watch-{env['marker']}"
        )
        outcomes.run_outcomes_job(conn)
        row = conn.execute(
            select(table("outcomes").c.hit_1d, table("outcomes").c.hit_7d, table("outcomes").c.ret_7d).where(
                table("outcomes").c.recommendation_id == rec_id
            )
        ).first()

    assert row.ret_7d is not None
    assert row.hit_1d is None
    assert row.hit_7d is None


def test_run_outcomes_job_marks_unavailable_after_three_attempts(env, monkeypatch):
    from newswatch_worker.db import get_engine, table

    created_at = datetime.now(timezone.utc) - timedelta(days=10)

    class _FakeTicker:
        def __init__(self, symbol):
            pass

        def history(self, start=None, end=None):
            return pd.DataFrame()  # bogus symbol -> always empty

    monkeypatch.setattr(outcomes.yf, "Ticker", _FakeTicker)
    monkeypatch.setattr(outcomes.GammaClient, "get_market_by_id", lambda self, market_id: None)

    engine = get_engine()
    with engine.begin() as conn:
        rec_id = _insert_recommendation(
            conn, env=env, ticker="BOGUSXYZ", action="BUY", created_at=created_at, dedupe_key=f"dedupe-bogus-{env['marker']}"
        )
        for _ in range(3):
            outcomes.run_outcomes_job(conn)
        row = conn.execute(
            select(table("outcomes").c.status, table("outcomes").c.attempts).where(table("outcomes").c.recommendation_id == rec_id)
        ).first()
        # a 4th run must not touch it further - it's excluded from selection now
        stats = outcomes.run_outcomes_job(conn)

    assert row.status == "unavailable"
    assert row.attempts == 3
    assert stats["recommendations_checked"] == 0


def test_run_outcomes_job_skips_ticker_less_recommendation(env, monkeypatch):
    from newswatch_worker.db import get_engine, table

    monkeypatch.setattr(outcomes.GammaClient, "get_market_by_id", lambda self, market_id: None)

    engine = get_engine()
    with engine.begin() as conn:
        _insert_recommendation(
            conn, env=env, ticker=None, action="WATCH",
            created_at=datetime.now(timezone.utc) - timedelta(days=10), dedupe_key=f"dedupe-sectoronly-{env['marker']}",
        )
        stats = outcomes.run_outcomes_job(conn)

    assert stats["recommendations_checked"] == 0


# ---- Polymarket outcomes ---------------------------------------------------


def _insert_pm_market_and_opportunity(conn, *, env, suffix, side, market_price, est_probability, created_at):
    from newswatch_worker.db import table

    pm_markets_t = table("pm_markets")
    pm_opportunities_t = table("pm_opportunities")
    market_id = f"test-{env['marker']}-{suffix}"
    conn.execute(pm_markets_t.insert().values(id=market_id, question="Q?", slug=market_id, active=True, resolved=False))
    opp_id = conn.execute(
        pm_opportunities_t.insert()
        .values(
            cycle_id=env["cycle_id"], market_id=market_id, dedupe_key=f"dedupe-pm-{suffix}-{env['marker']}",
            discovery="scan", side=side, market_price=market_price, est_probability=est_probability,
            edge_points=abs(est_probability - market_price) * 100, confidence=0.6, reasoning="r", rule_trace={},
            prompt_version="pm-estimate-v1", model="test", created_at=created_at,
        )
        .returning(pm_opportunities_t.c.id)
    ).scalar_one()
    return market_id, str(opp_id)


def test_run_outcomes_job_populates_pm_price_1d_for_backdated_opportunity(env, monkeypatch):
    from newswatch_worker.db import get_engine, table

    monkeypatch.setattr(outcomes.yf, "Ticker", lambda symbol: pytest.fail("yfinance must not be called for PM path"))

    created_at = datetime.now(timezone.utc) - timedelta(days=8)
    market_id, opp_id = None, None

    engine = get_engine()
    with engine.begin() as conn:
        market_id, opp_id = _insert_pm_market_and_opportunity(
            conn, env=env, suffix="drift", side="YES", market_price=0.30, est_probability=0.55, created_at=created_at
        )

    fake_market = PmMarketDTO(
        id=market_id, question="Q?", slug=market_id, category=None, end_date=None, yes_price=0.45,
        volume_24h_usd=1000, liquidity_usd=20000, active=True, closed=False, resolution=None,
    )
    monkeypatch.setattr(GammaClient, "get_market_by_id", lambda self, mid: fake_market)

    with engine.begin() as conn:
        stats = outcomes.run_outcomes_job(conn)
        row = conn.execute(
            select(table("pm_outcomes").c.price_1d, table("pm_outcomes").c.price_7d, table("pm_outcomes").c.status,
                   table("pm_outcomes").c.moved_toward_estimate_7d)
            .where(table("pm_outcomes").c.pm_opportunity_id == opp_id)
        ).first()

    assert stats["pm_opportunities_checked"] == 1
    assert float(row.price_1d) == pytest.approx(0.45)
    assert float(row.price_7d) == pytest.approx(0.45)
    assert row.status == "complete"
    # price moved from 0.30 toward the 0.55 estimate (now 0.45) -> True
    assert row.moved_toward_estimate_7d is True


def test_run_outcomes_job_records_pm_resolution_and_estimate_correct(env, monkeypatch):
    from newswatch_worker.db import get_engine, table

    created_at = datetime.now(timezone.utc) - timedelta(days=8)
    with_engine = get_engine()
    with with_engine.begin() as conn:
        market_id, opp_id = _insert_pm_market_and_opportunity(
            conn, env=env, suffix="resolved", side="YES", market_price=0.30, est_probability=0.7, created_at=created_at
        )

    fake_market = PmMarketDTO(
        id=market_id, question="Q?", slug=market_id, category=None, end_date=None, yes_price=0.99,
        volume_24h_usd=1000, liquidity_usd=20000, active=False, closed=True, resolution="YES",
    )
    monkeypatch.setattr(GammaClient, "get_market_by_id", lambda self, mid: fake_market)

    with with_engine.begin() as conn:
        outcomes.run_outcomes_job(conn)
        row = conn.execute(
            select(table("pm_outcomes").c.resolved, table("pm_outcomes").c.resolution, table("pm_outcomes").c.estimate_correct)
            .where(table("pm_outcomes").c.pm_opportunity_id == opp_id)
        ).first()

    assert row.resolved is True
    assert row.resolution == "YES"
    assert row.estimate_correct is True
