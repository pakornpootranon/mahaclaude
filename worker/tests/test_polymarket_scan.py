"""Tests for newswatch_worker.polymarket.scan against real local Postgres,
with a fake Anthropic client and a monkeypatched Gamma client (no live
network access to either in this sandbox)."""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from anthropic.types import Message, TextBlock, Usage
from sqlalchemy import select

from newswatch_worker import cycle
from newswatch_worker.llm import client, pm_estimate
from newswatch_worker.polymarket import scan
from newswatch_worker.polymarket.client import PmMarketDTO

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")


def _message(text: str) -> Message:
    return Message(
        id="msg_test",
        type="message",
        role="assistant",
        model="claude-sonnet-5",
        content=[TextBlock(type="text", text=text)],
        stop_reason="end_turn",
        stop_sequence=None,
        usage=Usage(input_tokens=10, output_tokens=5),
    )


class _FakeMessages:
    def __init__(self, responses: list[Message]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class _FakeAnthropicClient:
    def __init__(self, responses: list[Message]):
        self.messages = _FakeMessages(responses)


@pytest.fixture(autouse=True)
def _clear_capability_cache():
    client._model_thinking_capability.cache_clear()
    yield
    client._model_thinking_capability.cache_clear()


@contextmanager
def _override_pm_settings(conn, **overrides):
    from newswatch_worker.db import table

    settings_t = table("settings")
    original = conn.execute(select(settings_t.c.value).where(settings_t.c.key == "polymarket")).scalar_one()
    patched = dict(original)
    patched.update(overrides)
    conn.execute(settings_t.update().where(settings_t.c.key == "polymarket").values(value=patched))
    try:
        yield patched
    finally:
        conn.execute(settings_t.update().where(settings_t.c.key == "polymarket").values(value=original))


@pytest.fixture
def env():
    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    marker = uuid.uuid4().hex[:8]
    cycles_t = table("cycles")
    with engine.begin() as conn:
        cycle_id = conn.execute(
            cycles_t.insert()
            .values(scheduled_for=datetime.now(timezone.utc), kind="manual", state="PM_SCANNING", stats={})
            .returning(cycles_t.c.id)
        ).scalar_one()

    yield {"cycle_id": str(cycle_id), "marker": marker}

    with engine.begin() as conn:
        conn.execute(table("pm_opportunities").delete().where(table("pm_opportunities").c.cycle_id == cycle_id))
        conn.execute(table("pm_markets").delete().where(table("pm_markets").c.id.like(f"test-{marker}-%")))
        conn.execute(table("llm_calls").delete().where(table("llm_calls").c.cycle_id == cycle_id))
        conn.execute(table("cycles").delete().where(table("cycles").c.id == cycle_id))


def _insert_market(conn, *, marker, suffix, **overrides):
    from newswatch_worker.db import table

    pm_markets_t = table("pm_markets")
    market_id = f"test-{marker}-{suffix}"
    values = {
        "id": market_id,
        "question": f"Will {suffix} happen?",
        "slug": market_id,
        "category": "Economy",
        "yes_price": 0.5,
        "volume_24h_usd": 10000,
        "liquidity_usd": 50000,
        "active": True,
        "resolved": False,
        "end_date": datetime.now(timezone.utc) + timedelta(days=30),
    }
    values.update(overrides)
    conn.execute(pm_markets_t.insert().values(**values))
    return market_id


# ---- pure function tests ----------------------------------------------


def test_prefilter_reasons_flags_low_liquidity_and_out_of_range_price():
    row = SimpleNamespace(
        liquidity_usd=100, end_date=datetime.now(timezone.utc) + timedelta(days=30), yes_price=0.99
    )
    pm_settings = {"min_liquidity_usd": 10000, "min_days_to_end": 2, "price_floor": 0.05, "price_ceiling": 0.95}
    reasons = scan._prefilter_reasons(row, pm_settings)
    assert "liquidity_below_floor" in reasons
    assert "price_outside_range" in reasons


def test_prefilter_reasons_flags_resolving_too_soon():
    row = SimpleNamespace(
        liquidity_usd=50000, end_date=datetime.now(timezone.utc) + timedelta(hours=1), yes_price=0.5
    )
    pm_settings = {"min_liquidity_usd": 10000, "min_days_to_end": 2, "price_floor": 0.05, "price_ceiling": 0.95}
    assert "resolving_too_soon" in scan._prefilter_reasons(row, pm_settings)


def test_prefilter_reasons_passes_clean_market():
    row = SimpleNamespace(
        liquidity_usd=50000, end_date=datetime.now(timezone.utc) + timedelta(days=30), yes_price=0.5
    )
    pm_settings = {"min_liquidity_usd": 10000, "min_days_to_end": 2, "price_floor": 0.05, "price_ceiling": 0.95}
    assert scan._prefilter_reasons(row, pm_settings) == []


def test_edge_candidate_passes_when_all_conditions_met():
    pm_settings = {"min_edge_points": 10, "min_confidence": 0.55, "min_liquidity_usd": 10000}
    estimate = pm_estimate.PmEstimate(
        market_id="m1", skip=False, est_probability=0.7, confidence=0.6, reasoning="r", key_uncertainties=""
    )
    candidate = scan._edge_candidate(
        market_id="m1", discovery="scan", analysis_ids=[], market_price=0.5, liquidity_usd=50000,
        estimate=estimate, model="claude-sonnet-5", pm_settings=pm_settings,
    )
    assert candidate.passed_individual_checks is True
    assert candidate.side == "YES"
    assert candidate.edge_points == pytest.approx(20.0)


def test_edge_candidate_fails_below_edge_floor():
    pm_settings = {"min_edge_points": 10, "min_confidence": 0.55, "min_liquidity_usd": 10000}
    estimate = pm_estimate.PmEstimate(
        market_id="m1", skip=False, est_probability=0.52, confidence=0.9, reasoning="r", key_uncertainties=""
    )
    candidate = scan._edge_candidate(
        market_id="m1", discovery="scan", analysis_ids=[], market_price=0.5, liquidity_usd=50000,
        estimate=estimate, model="claude-sonnet-5", pm_settings=pm_settings,
    )
    assert candidate.passed_individual_checks is False
    assert candidate.rule_trace["edge_points"]["pass"] is False


def test_edge_candidate_fails_when_llm_sets_skip():
    pm_settings = {"min_edge_points": 10, "min_confidence": 0.55, "min_liquidity_usd": 10000}
    estimate = pm_estimate.PmEstimate(
        market_id="m1", skip=True, skip_reason="ambiguous", est_probability=0.7, confidence=0.6,
        reasoning="r", key_uncertainties="",
    )
    candidate = scan._edge_candidate(
        market_id="m1", discovery="scan", analysis_ids=[], market_price=0.5, liquidity_usd=50000,
        estimate=estimate, model="claude-sonnet-5", pm_settings=pm_settings,
    )
    assert candidate.passed_individual_checks is False
    assert candidate.rule_trace["skip"]["pass"] is False


# ---- select_scan_candidates --------------------------------------------


def test_select_scan_candidates_excludes_recently_estimated(env):
    from newswatch_worker.db import get_engine

    engine = get_engine()
    with engine.begin() as conn:
        fresh = _insert_market(conn, marker=env["marker"], suffix="fresh", last_estimated_at=datetime.now(timezone.utc))
        stale = _insert_market(
            conn, marker=env["marker"], suffix="stale", last_estimated_at=datetime.now(timezone.utc) - timedelta(hours=48)
        )
        never = _insert_market(conn, marker=env["marker"], suffix="never")

        with _override_pm_settings(conn, reestimate_hours=24, scan_top_n=20, categories=[]) as pm_settings:
            candidates = scan.select_scan_candidates(conn, pm_settings)

    ids = {str(r.id) for r in candidates}
    assert fresh not in ids
    assert stale in ids
    assert never in ids


def test_select_scan_candidates_respects_category_filter(env):
    from newswatch_worker.db import get_engine

    engine = get_engine()
    with engine.begin() as conn:
        econ = _insert_market(conn, marker=env["marker"], suffix="econ", category="Economy")
        politics = _insert_market(conn, marker=env["marker"], suffix="politics", category="Politics")

        with _override_pm_settings(conn, categories=["Economy"], scan_top_n=20) as pm_settings:
            candidates = scan.select_scan_candidates(conn, pm_settings)

    ids = {str(r.id) for r in candidates}
    assert econ in ids
    assert politics not in ids


# ---- _insert_opportunities ---------------------------------------------


def test_insert_opportunities_applies_cap_highest_edge_first(env):
    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    with engine.begin() as conn:
        low = _insert_market(conn, marker=env["marker"], suffix="low-edge")
        high = _insert_market(conn, marker=env["marker"], suffix="high-edge")

        candidates = [
            scan.PmCandidate(
                market_id=low, discovery="scan", analysis_ids=[], side="YES", market_price=0.5,
                est_probability=0.62, edge_points=12.0, confidence=0.6, reasoning="r", model="m",
                rule_trace={}, passed_individual_checks=True,
            ),
            scan.PmCandidate(
                market_id=high, discovery="scan", analysis_ids=[], side="YES", market_price=0.5,
                est_probability=0.8, edge_points=30.0, confidence=0.6, reasoning="r", model="m",
                rule_trace={}, passed_individual_checks=True,
            ),
        ]
        with _override_pm_settings(conn, max_opportunities_per_cycle=1, dedup_window_hours=48) as pm_settings:
            flagged = scan._insert_opportunities(conn, cycle_id=env["cycle_id"], candidates=candidates, pm_settings=pm_settings)

        rows = conn.execute(
            select(table("pm_opportunities").c.market_id).where(table("pm_opportunities").c.cycle_id == env["cycle_id"])
        ).all()

    assert flagged == 1
    assert {str(r.market_id) for r in rows} == {high}


def test_insert_opportunities_deduplicates_same_window(env):
    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    with engine.begin() as conn:
        market_id = _insert_market(conn, marker=env["marker"], suffix="dup")
        candidate = scan.PmCandidate(
            market_id=market_id, discovery="scan", analysis_ids=[], side="YES", market_price=0.5,
            est_probability=0.7, edge_points=20.0, confidence=0.6, reasoning="r", model="m",
            rule_trace={}, passed_individual_checks=True,
        )
        with _override_pm_settings(conn, max_opportunities_per_cycle=5, dedup_window_hours=48) as pm_settings:
            first = scan._insert_opportunities(conn, cycle_id=env["cycle_id"], candidates=[candidate], pm_settings=pm_settings)
            second = scan._insert_opportunities(conn, cycle_id=env["cycle_id"], candidates=[candidate], pm_settings=pm_settings)

        rows = conn.execute(
            select(table("pm_opportunities").c.id).where(table("pm_opportunities").c.cycle_id == env["cycle_id"])
        ).all()

    assert first == 1
    assert second == 0
    assert len(rows) == 1


# ---- run_pm_scanning integration ----------------------------------------


def test_run_pm_scanning_flags_high_edge_market_and_marks_estimated(env, monkeypatch):
    from newswatch_worker.db import get_engine, table
    from newswatch_worker.polymarket.client import GammaClient

    monkeypatch.setattr(client, "resolve_api_key", lambda conn: "sk-ant-fake")
    market_id = f"test-{env['marker']}-scan1"
    fake_market = PmMarketDTO(
        id=market_id, question="Will X happen?", slug=market_id, category="Economy",
        end_date=datetime.now(timezone.utc) + timedelta(days=30), yes_price=0.5,
        volume_24h_usd=50000, liquidity_usd=50000, active=True, closed=False,
    )
    monkeypatch.setattr(GammaClient, "get_all_active_markets", lambda self, cap=500: [fake_market])

    response_json = (
        f'{{"market_id": "{market_id}", "skip": false, "skip_reason": null, "est_probability": 0.8, '
        '"confidence": 0.7, "reasoning": "Strong signal.", "key_uncertainties": ""}'
    )
    fake = _FakeAnthropicClient([_message(response_json)])
    monkeypatch.setattr(client.anthropic, "Anthropic", lambda api_key: fake)

    engine = get_engine()
    with engine.begin() as conn:
        with _override_pm_settings(
            conn, scan_top_n=20, reestimate_hours=24, min_edge_points=10, min_confidence=0.55,
            min_liquidity_usd=10000, min_days_to_end=2, price_floor=0.05, price_ceiling=0.95,
            dedup_window_hours=48, max_opportunities_per_cycle=5, categories=[],
        ):
            stats = scan.run_pm_scanning(conn, cycle_id=env["cycle_id"])

        opp_row = conn.execute(
            select(table("pm_opportunities").c.side, table("pm_opportunities").c.edge_points).where(
                table("pm_opportunities").c.cycle_id == env["cycle_id"]
            )
        ).first()
        last_estimated = conn.execute(
            select(table("pm_markets").c.last_estimated_at).where(table("pm_markets").c.id == market_id)
        ).scalar_one()

    assert stats["pm_markets_refreshed"] == 1
    assert stats["pm_estimated"] == 1
    assert stats["pm_opportunities_flagged"] == 1
    assert opp_row is not None
    assert opp_row.side == "YES"
    assert float(opp_row.edge_points) == pytest.approx(30.0)
    assert last_estimated is not None


def test_run_pm_scanning_skips_prefiltered_low_liquidity_market_without_llm_call(env, monkeypatch):
    from newswatch_worker.db import get_engine
    from newswatch_worker.polymarket.client import GammaClient

    monkeypatch.setattr(client, "resolve_api_key", lambda conn: "sk-ant-fake")
    market_id = f"test-{env['marker']}-thin"
    fake_market = PmMarketDTO(
        id=market_id, question="Thin market?", slug=market_id, category="Economy",
        end_date=datetime.now(timezone.utc) + timedelta(days=30), yes_price=0.5,
        volume_24h_usd=100, liquidity_usd=100, active=True, closed=False,
    )
    monkeypatch.setattr(GammaClient, "get_all_active_markets", lambda self, cap=500: [fake_market])

    fake = _FakeAnthropicClient([])  # any .create() call here raises IndexError -> test fails loudly
    monkeypatch.setattr(client.anthropic, "Anthropic", lambda api_key: fake)

    engine = get_engine()
    with engine.begin() as conn:
        with _override_pm_settings(conn, min_liquidity_usd=10000, scan_top_n=20, categories=[]):
            stats = scan.run_pm_scanning(conn, cycle_id=env["cycle_id"])

    assert stats["pm_prefiltered_out"] == 1
    assert stats["pm_estimated"] == 0
    assert fake.messages.calls == []


def test_pm_scanning_step_skips_entirely_when_disabled(monkeypatch):
    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    with engine.begin() as conn:
        with _override_pm_settings(conn, enabled=False):

            def _fail_if_called(*args, **kwargs):
                raise AssertionError("run_pm_scanning must not be called when polymarket.enabled=false")

            monkeypatch.setattr(scan, "run_pm_scanning", _fail_if_called)
            ctx = cycle.CycleContext(cycle_id="unused", conn=conn, dry=False)
            cycle._pm_scanning_step(ctx)
