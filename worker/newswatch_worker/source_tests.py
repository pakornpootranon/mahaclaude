"""Async test-fetch handshake (docs/02-architecture.md §6): web inserts a
`source_tests` row with status='requested', the worker picks it up, runs
that source's adapter.test(), and writes the result back. Covers MCP
connectors the same as any other source type (§4b) — same table, same
adapter.test() call.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Connection

from newswatch_worker.sources import ADAPTERS, SourceConfig

logger = logging.getLogger(__name__)


def _run_one(conn: Connection, *, source_tests_table, sources_table, test_row: Any) -> None:
    source_row = conn.execute(
        select(sources_table).where(sources_table.c.id == test_row.source_id)
    ).first()

    if source_row is None:
        conn.execute(
            source_tests_table.update()
            .where(source_tests_table.c.id == test_row.id)
            .values(
                status="error",
                result={"error": "source not found"},
                completed_at=datetime.now(timezone.utc),
            )
        )
        return

    adapter = ADAPTERS.get(source_row.source_type)
    if adapter is None:
        conn.execute(
            source_tests_table.update()
            .where(source_tests_table.c.id == test_row.id)
            .values(
                status="error",
                result={"error": f"no adapter for source_type={source_row.source_type}"},
                completed_at=datetime.now(timezone.utc),
            )
        )
        return

    source_config = SourceConfig(
        id=str(source_row.id),
        name=source_row.name,
        source_type=source_row.source_type,
        config=source_row.config,
        language=source_row.language,
    )
    test_result = adapter.test(source_config)

    conn.execute(
        source_tests_table.update()
        .where(source_tests_table.c.id == test_row.id)
        .values(
            status="ok" if test_result.ok else "error",
            result={
                "item_count": test_result.item_count,
                "sample_titles": test_result.sample_titles,
                "error": test_result.error,
            },
            completed_at=datetime.now(timezone.utc),
        )
    )


def process_pending_source_tests(conn: Connection, *, tables: dict[str, Any]) -> int:
    """Drains every source_tests row with status='requested'. Returns the
    number processed."""
    source_tests_t = tables["source_tests"]
    sources_t = tables["sources"]

    pending = conn.execute(
        select(source_tests_t).where(source_tests_t.c.status == "requested")
    ).all()

    for test_row in pending:
        try:
            _run_one(conn, source_tests_table=source_tests_t, sources_table=sources_t, test_row=test_row)
        except Exception as exc:  # noqa: BLE001 - one bad test-row must not block the others
            logger.exception("source_test=%s failed", test_row.id)
            conn.execute(
                source_tests_t.update()
                .where(source_tests_t.c.id == test_row.id)
                .values(status="error", result={"error": str(exc)}, completed_at=datetime.now(timezone.utc))
            )

    return len(pending)
