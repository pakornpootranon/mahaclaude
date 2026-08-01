"""Integration tests against a real Postgres (per DATABASE_URL) — the cycle
state machine is thin SQLAlchemy Core over reflected Postgres-specific types
(uuid, jsonb, text[]), so there's little value mocking it out.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set"
)


@pytest.fixture(autouse=True)
def _clean_cycles():
    from newswatch_worker.db import get_engine, table

    yield

    cycles_t = table("cycles")
    with get_engine().begin() as conn:
        conn.execute(cycles_t.delete())


def test_dry_run_reaches_done():
    from newswatch_worker.cycle import run_cycle

    final_state = run_cycle(dry=True, kind="manual")
    assert final_state == "DONE"


def test_dry_run_creates_exactly_one_cycle_row():
    from newswatch_worker.cycle import run_cycle
    from newswatch_worker.db import get_engine, table

    run_cycle(dry=True, kind="manual")

    cycles_t = table("cycles")
    with get_engine().begin() as conn:
        rows = conn.execute(select(cycles_t.c.state)).fetchall()

    assert len(rows) == 1
    assert rows[0][0] == "DONE"


def test_resumes_incomplete_cycle_instead_of_creating_a_new_one():
    from newswatch_worker.cycle import run_cycle
    from newswatch_worker.db import get_engine, table

    cycles_t = table("cycles")
    with get_engine().begin() as conn:
        result = conn.execute(
            cycles_t.insert()
            .values(
                scheduled_for=datetime.now(timezone.utc),
                kind="manual",
                state="TRIAGING",
                stats={},
            )
            .returning(cycles_t.c.id)
        )
        stuck_cycle_id = str(result.scalar_one())

    final_state = run_cycle(dry=True, kind="manual")
    assert final_state == "DONE"

    with get_engine().begin() as conn:
        rows = conn.execute(select(cycles_t.c.id)).fetchall()
    assert len(rows) == 1
    assert str(rows[0][0]) == stuck_cycle_id
