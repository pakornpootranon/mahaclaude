"""Nightly outcomes job (docs/02-architecture.md §7): T+1/T+3/T+7 stock
price backfill via yfinance for triggered recommendations, plus Polymarket
opportunity price-drift + resolution tracking. NOT part of the digest cycle
state machine — runs on its own fixed nightly schedule (07:30 Asia/Bangkok,
scheduler.py), independent of `settings['schedule']` (which only governs
digest cycles).

Idempotent like everything else here: re-running only fills in fields that
are still missing, upserting on the tables' existing primary keys
(recommendation_id / pm_opportunity_id).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from newswatch_worker.db import table
from newswatch_worker.polymarket.client import GammaClient

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
_TERMINAL_STATUSES = ("complete", "unavailable")


def _pct_return(entry: float, close: float | None) -> float | None:
    if close is None or entry == 0:
        return None
    return (close - entry) / entry * 100


def _direction_hit(action: str, ret: float | None) -> bool | None:
    """docs/02 §7: 'direction-adjusted hit = sign(return) matches
    recommendation direction (SELL hits on negative return)'. WATCH isn't a
    directional call, so it has no hit verdict (judgment call, documented
    here) — hit_Nd stays NULL, which hit_rates_v already tolerates via its
    FILTER (WHERE ... IS NOT NULL) clauses."""
    if ret is None or action not in ("BUY", "SELL"):
        return None
    return ret > 0 if action == "BUY" else ret < 0


@dataclass(frozen=True)
class _PendingRecommendation:
    id: str
    ticker: str
    action: str
    created_at: datetime
    status: str
    attempts: int
    entry_price: float | None
    ret_1d: float | None
    ret_3d: float | None
    ret_7d: float | None


def _select_pending_recommendations(conn: Connection) -> list[_PendingRecommendation]:
    recommendations_t = table("recommendations")
    outcomes_t = table("outcomes")
    rows = conn.execute(
        select(
            recommendations_t.c.id,
            recommendations_t.c.tickers,
            recommendations_t.c.action,
            recommendations_t.c.created_at,
            outcomes_t.c.status,
            outcomes_t.c.attempts,
            outcomes_t.c.entry_price,
            outcomes_t.c.ret_1d,
            outcomes_t.c.ret_3d,
            outcomes_t.c.ret_7d,
        ).select_from(
            recommendations_t.outerjoin(outcomes_t, outcomes_t.c.recommendation_id == recommendations_t.c.id)
        )
    ).all()

    pending = []
    for r in rows:
        # v1 tracks one ticker per recommendation (docs/03 §2.8) — a
        # sector-only row (FR-A4) or the "unconfigured but significant"
        # WATCH branch (docs/04 §6) never carries tickers, so there's
        # nothing to price; no outcomes row is ever created for those.
        if not r.tickers:
            continue
        status = r.status or "pending"
        attempts = r.attempts or 0
        if status in _TERMINAL_STATUSES or attempts >= MAX_ATTEMPTS:
            continue
        pending.append(
            _PendingRecommendation(
                id=str(r.id),
                ticker=r.tickers[0],
                action=r.action,
                created_at=r.created_at,
                status=status,
                attempts=attempts,
                entry_price=float(r.entry_price) if r.entry_price is not None else None,
                ret_1d=float(r.ret_1d) if r.ret_1d is not None else None,
                ret_3d=float(r.ret_3d) if r.ret_3d is not None else None,
                ret_7d=float(r.ret_7d) if r.ret_7d is not None else None,
            )
        )
    return pending


def _fetch_price_history(ticker: str, since: datetime):
    end = datetime.now(timezone.utc).date() + timedelta(days=1)
    try:
        hist = yf.Ticker(ticker).history(start=since.date(), end=end)
    except Exception:  # noqa: BLE001 - any yfinance failure means "treat as unavailable this attempt"
        logger.warning("outcomes: yfinance fetch failed for ticker=%s", ticker, exc_info=True)
        return None
    return hist if hist is not None and not hist.empty else None


def _upsert_outcome(conn: Connection, *, recommendation_id: str, **values) -> None:
    outcomes_t = table("outcomes")
    conn.execute(
        pg_insert(outcomes_t)
        .values(recommendation_id=recommendation_id, **values)
        .on_conflict_do_update(index_elements=["recommendation_id"], set_=values)
    )


def _backfill_recommendation_outcome(conn: Connection, pending: _PendingRecommendation) -> str:
    """Returns one of 'complete'|'partial'|'pending'|'unavailable' for stats."""
    hist = _fetch_price_history(pending.ticker, pending.created_at)

    if hist is None:
        attempts = pending.attempts + 1
        status = "unavailable" if attempts >= MAX_ATTEMPTS else pending.status
        _upsert_outcome(
            conn,
            recommendation_id=pending.id,
            ticker=pending.ticker,
            entry_price=pending.entry_price,
            ret_1d=pending.ret_1d,
            ret_3d=pending.ret_3d,
            ret_7d=pending.ret_7d,
            hit_1d=_direction_hit(pending.action, pending.ret_1d),
            hit_3d=_direction_hit(pending.action, pending.ret_3d),
            hit_7d=_direction_hit(pending.action, pending.ret_7d),
            status=status,
            attempts=attempts,
        )
        return status

    entry_price = float(hist["Close"].iloc[0])

    def _close_at(offset: int) -> float | None:
        return float(hist["Close"].iloc[offset]) if len(hist) > offset else None

    ret_1d = _pct_return(entry_price, _close_at(1))
    ret_3d = _pct_return(entry_price, _close_at(3))
    ret_7d = _pct_return(entry_price, _close_at(7))

    status = "complete" if ret_7d is not None else ("partial" if (ret_1d is not None or ret_3d is not None) else "pending")

    _upsert_outcome(
        conn,
        recommendation_id=pending.id,
        ticker=pending.ticker,
        entry_price=entry_price,
        ret_1d=ret_1d,
        ret_3d=ret_3d,
        ret_7d=ret_7d,
        hit_1d=_direction_hit(pending.action, ret_1d),
        hit_3d=_direction_hit(pending.action, ret_3d),
        hit_7d=_direction_hit(pending.action, ret_7d),
        status=status,
        attempts=pending.attempts,
    )
    return status


@dataclass(frozen=True)
class _PendingPmOpportunity:
    id: str
    market_id: str
    side: str
    market_price: float
    est_probability: float
    created_at: datetime
    status: str
    attempts: int
    price_1d: float | None
    price_3d: float | None
    price_7d: float | None


def _select_pending_pm_opportunities(conn: Connection) -> list[_PendingPmOpportunity]:
    pm_opportunities_t = table("pm_opportunities")
    pm_outcomes_t = table("pm_outcomes")
    rows = conn.execute(
        select(
            pm_opportunities_t.c.id,
            pm_opportunities_t.c.market_id,
            pm_opportunities_t.c.side,
            pm_opportunities_t.c.market_price,
            pm_opportunities_t.c.est_probability,
            pm_opportunities_t.c.created_at,
            pm_outcomes_t.c.status,
            pm_outcomes_t.c.attempts,
            pm_outcomes_t.c.price_1d,
            pm_outcomes_t.c.price_3d,
            pm_outcomes_t.c.price_7d,
        ).select_from(
            pm_opportunities_t.outerjoin(pm_outcomes_t, pm_outcomes_t.c.pm_opportunity_id == pm_opportunities_t.c.id)
        )
    ).all()

    pending = []
    for r in rows:
        status = r.status or "pending"
        attempts = r.attempts or 0
        if status in _TERMINAL_STATUSES or attempts >= MAX_ATTEMPTS:
            continue
        pending.append(
            _PendingPmOpportunity(
                id=str(r.id),
                market_id=r.market_id,
                side=r.side,
                market_price=float(r.market_price),
                est_probability=float(r.est_probability),
                created_at=r.created_at,
                status=status,
                attempts=attempts,
                price_1d=float(r.price_1d) if r.price_1d is not None else None,
                price_3d=float(r.price_3d) if r.price_3d is not None else None,
                price_7d=float(r.price_7d) if r.price_7d is not None else None,
            )
        )
    return pending


def _upsert_pm_outcome(conn: Connection, *, pm_opportunity_id: str, **values) -> None:
    pm_outcomes_t = table("pm_outcomes")
    conn.execute(
        pg_insert(pm_outcomes_t)
        .values(pm_opportunity_id=pm_opportunity_id, **values)
        .on_conflict_do_update(index_elements=["pm_opportunity_id"], set_=values)
    )


def _backfill_pm_outcome(conn: Connection, gamma: GammaClient, pending: _PendingPmOpportunity) -> str:
    try:
        market = gamma.get_market_by_id(pending.market_id)
    except Exception:  # noqa: BLE001 - any Gamma failure means "treat as unavailable this attempt"
        logger.warning("outcomes: Gamma fetch failed for market_id=%s", pending.market_id, exc_info=True)
        market = None

    if market is None:
        attempts = pending.attempts + 1
        status = "unavailable" if attempts >= MAX_ATTEMPTS else pending.status
        _upsert_pm_outcome(
            conn,
            pm_opportunity_id=pending.id,
            price_1d=pending.price_1d,
            price_3d=pending.price_3d,
            price_7d=pending.price_7d,
            status=status,
            attempts=attempts,
        )
        return status

    elapsed_days = (datetime.now(timezone.utc) - pending.created_at).days
    price_1d = pending.price_1d if pending.price_1d is not None else (market.yes_price if elapsed_days >= 1 else None)
    price_3d = pending.price_3d if pending.price_3d is not None else (market.yes_price if elapsed_days >= 3 else None)
    price_7d = pending.price_7d if pending.price_7d is not None else (market.yes_price if elapsed_days >= 7 else None)

    moved_toward_estimate_7d = None
    if price_7d is not None:
        moved_toward_estimate_7d = abs(price_7d - pending.est_probability) < abs(
            pending.market_price - pending.est_probability
        )

    resolution = market.resolution if market.closed else None
    estimate_correct = (pending.side == resolution) if resolution in ("YES", "NO") else None

    status = "complete" if price_7d is not None else ("partial" if (price_1d is not None or price_3d is not None) else "pending")

    _upsert_pm_outcome(
        conn,
        pm_opportunity_id=pending.id,
        price_1d=price_1d,
        price_3d=price_3d,
        price_7d=price_7d,
        moved_toward_estimate_7d=moved_toward_estimate_7d,
        resolved=bool(market.closed),
        resolution=resolution,
        estimate_correct=estimate_correct,
        status=status,
        attempts=pending.attempts,
    )
    return status


def run_outcomes_job(conn: Connection) -> dict:
    stats = {
        "recommendations_checked": 0,
        "recommendations_complete": 0,
        "recommendations_unavailable": 0,
        "pm_opportunities_checked": 0,
        "pm_opportunities_complete": 0,
        "pm_opportunities_unavailable": 0,
    }

    for pending in _select_pending_recommendations(conn):
        stats["recommendations_checked"] += 1
        result_status = _backfill_recommendation_outcome(conn, pending)
        if result_status == "complete":
            stats["recommendations_complete"] += 1
        elif result_status == "unavailable":
            stats["recommendations_unavailable"] += 1

    gamma = GammaClient()
    for pending in _select_pending_pm_opportunities(conn):
        stats["pm_opportunities_checked"] += 1
        result_status = _backfill_pm_outcome(conn, gamma, pending)
        if result_status == "complete":
            stats["pm_opportunities_complete"] += 1
        elif result_status == "unavailable":
            stats["pm_opportunities_unavailable"] += 1

    logger.info("outcomes job finished: %s", stats)
    return stats
