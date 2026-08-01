"""Tests for newswatch_worker.scheduler against real local Postgres. Jobs
are added to an unstarted BackgroundScheduler (safe with APScheduler v3 -
add_job/get_jobs/remove_job all work without starting the scheduler thread)
so nothing actually fires; run_forever()'s infinite loop itself isn't
covered here, only the pieces it wires together.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from newswatch_worker import scheduler

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")


def test_reschedule_adds_one_job_per_enabled_cycle():
    sched = BackgroundScheduler()
    schedule_value = {
        "timezone": "Asia/Bangkok",
        "cycles": [
            {"id": "morning", "time": "07:00", "enabled": True, "label": "a"},
            {"id": "midday", "time": "12:30", "enabled": False, "label": "b"},
            {"id": "evening", "time": "20:30", "enabled": True, "label": "c"},
        ],
    }
    scheduler._reschedule(sched, schedule_value)

    job_ids = {job.id for job in sched.get_jobs()}
    assert job_ids == {"cycle-morning", "cycle-evening"}


def test_reschedule_removes_stale_jobs_before_adding_new():
    sched = BackgroundScheduler()
    scheduler._reschedule(sched, {"timezone": "Asia/Bangkok", "cycles": [{"id": "a", "time": "07:00", "enabled": True}]})
    assert {job.id for job in sched.get_jobs()} == {"cycle-a"}

    scheduler._reschedule(sched, {"timezone": "Asia/Bangkok", "cycles": [{"id": "b", "time": "20:00", "enabled": True}]})
    assert {job.id for job in sched.get_jobs()} == {"cycle-b"}


def test_reschedule_leaves_non_cycle_jobs_alone():
    sched = BackgroundScheduler()
    sched.add_job(lambda: None, "interval", seconds=60, id="poll-manual-and-source-tests")
    scheduler._reschedule(sched, {"timezone": "Asia/Bangkok", "cycles": [{"id": "a", "time": "07:00", "enabled": True}]})

    job_ids = {job.id for job in sched.get_jobs()}
    assert "poll-manual-and-source-tests" in job_ids
    assert "cycle-a" in job_ids


def test_run_cycle_safely_skips_when_already_locked(monkeypatch):
    calls = []
    monkeypatch.setattr(scheduler, "run_cycle", lambda **kwargs: calls.append(kwargs) or "DONE")

    assert scheduler._cycle_lock.acquire(blocking=False)
    try:
        scheduler._run_cycle_safely(kind="scheduled")
    finally:
        scheduler._cycle_lock.release()

    assert calls == []


def test_run_cycle_safely_calls_run_cycle_when_unlocked(monkeypatch):
    calls = []
    monkeypatch.setattr(scheduler, "run_cycle", lambda **kwargs: calls.append(kwargs) or "DONE")

    scheduler._run_cycle_safely(kind="scheduled")

    assert calls == [{"dry": False, "kind": "scheduled"}]


def test_poll_manual_and_source_tests_picks_up_pending_manual_cycle(monkeypatch):
    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    cycles_t = table("cycles")
    with engine.begin() as conn:
        cycle_id = conn.execute(
            cycles_t.insert()
            .values(
                scheduled_for=datetime.now(timezone.utc),
                kind="manual",
                requested_manual=True,
                state="PENDING",
                stats={},
            )
            .returning(cycles_t.c.id)
        ).scalar_one()

    calls = []
    monkeypatch.setattr(scheduler, "run_cycle", lambda **kwargs: calls.append(kwargs) or "DONE")

    try:
        scheduler._poll_manual_and_source_tests()
    finally:
        with engine.begin() as conn:
            conn.execute(cycles_t.delete().where(cycles_t.c.id == cycle_id))

    assert calls == [{"dry": False, "kind": "manual"}]


def test_poll_manual_and_source_tests_ignores_when_nothing_pending(monkeypatch):
    calls = []
    monkeypatch.setattr(scheduler, "run_cycle", lambda **kwargs: calls.append(kwargs) or "DONE")

    scheduler._poll_manual_and_source_tests()

    assert calls == []


def test_watch_schedule_settings_only_reschedules_on_change(monkeypatch):
    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    settings_t = table("settings")
    with engine.begin() as conn:
        original_value, original_updated_at = scheduler._load_schedule_settings(conn)

    sched = BackgroundScheduler()
    state = {"updated_at": original_updated_at}

    reschedule_calls = []
    monkeypatch.setattr(scheduler, "_reschedule", lambda s, v: reschedule_calls.append(v))

    scheduler._watch_schedule_settings(sched, state)
    assert reschedule_calls == []

    marker = f"test-marker-{uuid.uuid4().hex[:6]}"
    patched_value = dict(original_value)
    patched_value["_test_marker"] = marker
    try:
        with engine.begin() as conn:
            # settings.updated_at is Prisma's @updatedAt (client-side only,
            # no DB default/trigger - see schema.prisma) - real writes go
            # through the web app's Prisma-based API routes, which set this
            # automatically. Set it explicitly here to simulate that, since
            # this test updates via raw SQLAlchemy.
            conn.execute(
                settings_t.update()
                .where(settings_t.c.key == "schedule")
                .values(value=patched_value, updated_at=datetime.now(timezone.utc))
            )

        scheduler._watch_schedule_settings(sched, state)
        assert len(reschedule_calls) == 1
        assert reschedule_calls[0]["_test_marker"] == marker
    finally:
        with engine.begin() as conn:
            conn.execute(settings_t.update().where(settings_t.c.key == "schedule").values(value=original_value))
