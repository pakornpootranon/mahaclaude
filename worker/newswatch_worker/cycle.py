"""Digest cycle state machine (docs/02-architecture.md §3):

    PENDING -> INGESTING -> TRIAGING -> ANALYZING -> TRIGGERING
             -> PM_SCANNING -> SUMMARIZING -> DONE
                                          (any state) -> FAILED

Each state's step handler must be idempotent so a crashed cycle can be
re-run safely (PRD acceptance #4). Handlers not yet backed by a real
implementation are no-ops until their owning phase (triage/analysis/rules:
Phase 3; Polymarket scanning: Phase 5b) replaces them, without touching the
driver loop below. `--dry` (main.py) skips calling *any* handler, real or
not, so it stays a pure state-machine walk regardless of which phases have
landed.

Crash-resume design: the state transition (UPDATE cycles SET state = ...)
only commits *after* the step handler for the current state returns. If the
process is killed mid-step, the row is left at the state it was working on
when it died (never advanced, and never marked FAILED) — so the next
`run_cycle()` call finds it via `_find_resumable_cycle` and simply re-runs
that state's (idempotent) handler. FAILED is reserved for exceptions we
catch explicitly and choose to treat as non-retryable; the generic handler
below records the error but leaves `state` untouched, which keeps the cycle
resumable rather than dead-ending it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.engine import Connection

from newswatch_worker.db import get_engine, table

logger = logging.getLogger(__name__)

STATES = [
    "PENDING",
    "INGESTING",
    "TRIAGING",
    "ANALYZING",
    "TRIGGERING",
    "PM_SCANNING",
    "SUMMARIZING",
    "DONE",
]
FAILED = "FAILED"


@dataclass
class CycleContext:
    cycle_id: str
    conn: Connection
    dry: bool


def _noop_step(ctx: CycleContext) -> None:
    """Placeholder for a not-yet-implemented phase's cycle step."""


def _ingesting_step(ctx: CycleContext) -> None:
    from newswatch_worker.ingest import run_ingestion

    tables = {
        "sources": table("sources"),
        "news_items": table("news_items"),
        "topics": table("topics"),
    }
    stats = run_ingestion(ctx.conn, tables=tables, cycle_id=ctx.cycle_id)

    cycles_t = table("cycles")
    current_stats = ctx.conn.execute(
        select(cycles_t.c.stats).where(cycles_t.c.id == ctx.cycle_id)
    ).scalar_one()
    current_stats.update(stats)
    ctx.conn.execute(cycles_t.update().where(cycles_t.c.id == ctx.cycle_id).values(stats=current_stats))
    logger.info("cycle=%s ingestion stats: %s", ctx.cycle_id, stats)


def _pm_scanning_step(ctx: CycleContext) -> None:
    settings_t = table("settings")
    row = ctx.conn.execute(
        select(settings_t.c.value).where(settings_t.c.key == "polymarket")
    ).first()
    enabled = bool(row and row[0].get("enabled", True))
    if not enabled:
        logger.info("cycle=%s polymarket disabled, skipping PM_SCANNING", ctx.cycle_id)
    # Scan/match/estimate logic lands in Phase 5b.


STEP_HANDLERS: dict[str, Callable[[CycleContext], None]] = {
    "INGESTING": _ingesting_step,
    "TRIAGING": _noop_step,
    "ANALYZING": _noop_step,
    "TRIGGERING": _noop_step,
    "PM_SCANNING": _pm_scanning_step,
    "SUMMARIZING": _noop_step,
}


def _find_resumable_cycle(conn: Connection) -> str | None:
    """A cycle re-run reuses the same cycle_id if the previous attempt
    didn't reach DONE (arch §3)."""
    cycles_t = table("cycles")
    row = conn.execute(
        select(cycles_t.c.id)
        .where(cycles_t.c.state.notin_(["DONE", FAILED]))
        .order_by(cycles_t.c.scheduled_for.desc())
        .limit(1)
    ).first()
    return str(row[0]) if row else None


def run_cycle(*, dry: bool = False, kind: str = "manual") -> str:
    """Walk one cycle from its current state through to DONE.

    Resumes an incomplete cycle instead of creating a new one. Returns the
    final state reached (DONE, or whatever state the cycle was left at if a
    step raised).
    """
    engine = get_engine()
    cycles_t = table("cycles")

    with engine.begin() as conn:
        cycle_id = _find_resumable_cycle(conn)
        if cycle_id is None:
            result = conn.execute(
                cycles_t.insert()
                .values(
                    scheduled_for=datetime.now(timezone.utc),
                    kind=kind,
                    state="PENDING",
                    stats={},
                    started_at=datetime.now(timezone.utc),
                )
                .returning(cycles_t.c.id)
            )
            cycle_id = str(result.scalar_one())
            logger.info("cycle=%s created (kind=%s, dry=%s)", cycle_id, kind, dry)
        else:
            logger.info("cycle=%s resumed", cycle_id)

    while True:
        with engine.begin() as conn:
            current = conn.execute(
                select(cycles_t.c.state).where(cycles_t.c.id == cycle_id)
            ).scalar_one()

            if current == "DONE":
                return "DONE"
            if current == FAILED:
                return FAILED

            ctx = CycleContext(cycle_id=cycle_id, conn=conn, dry=dry)
            try:
                handler = STEP_HANDLERS.get(current)
                if handler is not None and not dry:
                    handler(ctx)
            except Exception as exc:  # noqa: BLE001 - cycle-level failure boundary
                logger.exception("cycle=%s failed in state=%s", cycle_id, current)
                # Record the error without advancing `state`, so the cycle
                # stays resumable at the state it failed in. Runs in its own
                # transaction since the enclosing one is about to roll back.
                with engine.begin() as error_conn:
                    error_conn.execute(
                        cycles_t.update()
                        .where(cycles_t.c.id == cycle_id)
                        .values(error=f"{current}: {exc}")
                    )
                raise

            next_state = STATES[STATES.index(current) + 1]
            update_values: dict[str, object] = {"state": next_state}
            if next_state == "DONE":
                update_values["finished_at"] = datetime.now(timezone.utc)
            conn.execute(
                cycles_t.update().where(cycles_t.c.id == cycle_id).values(**update_values)
            )
            logger.info("cycle=%s %s -> %s", cycle_id, current, next_state)

            if next_state == "DONE":
                return "DONE"
