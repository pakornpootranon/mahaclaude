"""APScheduler-driven cycle loop (docs/02-architecture.md §3): cron jobs in
Asia/Bangkok built from settings['schedule'], re-read on a settings-changed
check every minute so schedule edits need no restart (FR-C5). Manual runs
(web sets cycles.requested_manual=true) are picked up by polling every 15s,
same as `source_tests` requests (arch §6).

Single entrypoint: `newswatch serve` (main.py). Replaces the Phase 1
placeholder entrypoint (`run-cycle` once and exit) now that there's a
real cycle worth scheduling.
"""

from __future__ import annotations

import logging
import threading
import time

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from newswatch_worker.cycle import run_cycle
from newswatch_worker.db import get_engine, table
from newswatch_worker.outcomes import run_outcomes_job
from newswatch_worker.source_tests import process_pending_source_tests

logger = logging.getLogger(__name__)

MANUAL_POLL_SECONDS = 15
SETTINGS_POLL_SECONDS = 60
CYCLE_JOB_PREFIX = "cycle-"
OUTCOMES_JOB_ID = "outcomes-nightly"
# docs/02 §7: "Nightly at 07:30 Asia/Bangkok (after US close)" — a fixed
# time, unlike settings['schedule'].cycles which governs digest cycles and
# is user-configurable. Not wired to any settings key, so it needs no
# re-scheduling watcher.
OUTCOMES_HOUR = 7
OUTCOMES_MINUTE = 30

# A cron-triggered cycle and the manual-request poller could otherwise fire
# concurrently and each independently decide "nothing resumable, create a
# new cycle row" before either commits - this serializes all cycle
# execution to one at a time process-wide.
_cycle_lock = threading.Lock()


def _run_cycle_safely(*, kind: str) -> None:
    if not _cycle_lock.acquire(blocking=False):
        logger.info("cycle already running, skipping this %s trigger", kind)
        return
    try:
        final_state = run_cycle(dry=False, kind=kind)
        logger.info("%s cycle finished in state=%s", kind, final_state)
    except Exception:
        logger.exception("%s cycle raised", kind)
    finally:
        _cycle_lock.release()


def _load_schedule_settings(conn) -> tuple[dict, object]:
    settings_t = table("settings")
    row = conn.execute(
        select(settings_t.c.value, settings_t.c.updated_at).where(settings_t.c.key == "schedule")
    ).first()
    if row is None:
        raise RuntimeError("settings['schedule'] is not seeded")
    return row.value, row.updated_at


def _reschedule(scheduler: BackgroundScheduler, schedule_value: dict) -> None:
    for job in scheduler.get_jobs():
        if job.id.startswith(CYCLE_JOB_PREFIX):
            scheduler.remove_job(job.id)

    tz = schedule_value.get("timezone", "Asia/Bangkok")
    added = 0
    for entry in schedule_value.get("cycles", []):
        if not entry.get("enabled", True):
            continue
        hour_str, minute_str = entry["time"].split(":")
        scheduler.add_job(
            lambda: _run_cycle_safely(kind="scheduled"),
            CronTrigger(hour=int(hour_str), minute=int(minute_str), timezone=tz),
            id=f"{CYCLE_JOB_PREFIX}{entry['id']}",
            replace_existing=True,
            misfire_grace_time=300,
        )
        added += 1
    logger.info("(re)scheduled %d cycle job(s) in timezone=%s", added, tz)


def _run_outcomes_job_safely() -> None:
    engine = get_engine()
    try:
        with engine.begin() as conn:
            run_outcomes_job(conn)
    except Exception:
        logger.exception("outcomes job raised")


def _poll_manual_and_source_tests() -> None:
    engine = get_engine()
    cycles_t = table("cycles")
    with engine.begin() as conn:
        pending = conn.execute(
            select(cycles_t.c.id)
            .where(cycles_t.c.requested_manual.is_(True))
            .where(cycles_t.c.state.notin_(["DONE", "FAILED"]))
            .limit(1)
        ).first()
    if pending is not None:
        _run_cycle_safely(kind="manual")

    tables = {"source_tests": table("source_tests"), "sources": table("sources")}
    with engine.begin() as conn:
        count = process_pending_source_tests(conn, tables=tables)
    if count:
        logger.info("processed %d source test(s)", count)


def _watch_schedule_settings(scheduler: BackgroundScheduler, state: dict) -> None:
    engine = get_engine()
    with engine.begin() as conn:
        value, updated_at = _load_schedule_settings(conn)
    if state.get("updated_at") != updated_at:
        state["updated_at"] = updated_at
        _reschedule(scheduler, value)


def run_forever() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        initial_value, initial_updated_at = _load_schedule_settings(conn)

    scheduler = BackgroundScheduler()
    _reschedule(scheduler, initial_value)
    watch_state = {"updated_at": initial_updated_at}

    scheduler.add_job(
        _poll_manual_and_source_tests,
        "interval",
        seconds=MANUAL_POLL_SECONDS,
        id="poll-manual-and-source-tests",
    )
    scheduler.add_job(
        lambda: _watch_schedule_settings(scheduler, watch_state),
        "interval",
        seconds=SETTINGS_POLL_SECONDS,
        id="poll-schedule-settings",
    )
    scheduler.add_job(
        _run_outcomes_job_safely,
        CronTrigger(hour=OUTCOMES_HOUR, minute=OUTCOMES_MINUTE, timezone="Asia/Bangkok"),
        id=OUTCOMES_JOB_ID,
        misfire_grace_time=3600,
    )

    scheduler.start()
    logger.info("scheduler started")
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        logger.info("scheduler shutting down")
        scheduler.shutdown()
