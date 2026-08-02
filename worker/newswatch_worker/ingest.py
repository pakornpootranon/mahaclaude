"""Ingestion orchestration for the cycle's INGESTING state
(docs/02-architecture.md §4, §4b, §5).

- Polls every enabled source, honoring `poll_override_minutes` cadence.
- Adapter fetch failures degrade gracefully (FR-I5): recorded on the source
  (consecutive_failures, health) and skipped, never raised to fail the cycle.
- Upserts news_items on dedupe_key — a disabled source's adapter is never
  invoked at all (the enabled-sources query excludes it), which is what
  makes "disabled MCP connector never dialed" provable from the caller side
  rather than needing an internal enable-check inside the adapter.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from newswatch_worker.dedupe import dedupe_key
from newswatch_worker.secrets import resolve_source_secret
from newswatch_worker.sources import ADAPTERS, SourceConfig

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_HOURS = 24
FAILURE_THRESHOLD = 3


def _since_for(last_success_at: datetime | None, now: datetime) -> datetime:
    return last_success_at or (now - timedelta(hours=DEFAULT_LOOKBACK_HOURS))


def _due_by_cadence(
    poll_override_minutes: int | None, last_success_at: datetime | None, now: datetime
) -> bool:
    if poll_override_minutes is None or last_success_at is None:
        return True
    elapsed_minutes = (now - last_success_at).total_seconds() / 60
    return elapsed_minutes >= poll_override_minutes


def _enabled_topics(conn: Connection, topics_table) -> list[dict[str, Any]]:
    rows = conn.execute(
        select(topics_table.c.id, topics_table.c.name, topics_table.c.keywords, topics_table.c.sensitivity)
        .where(topics_table.c.enabled.is_(True))
    ).all()
    return [
        {"id": str(r.id), "name": r.name, "keywords": list(r.keywords or []), "sensitivity": float(r.sensitivity)}
        for r in rows
    ]


def _record_failure(conn: Connection, sources_table, source_id: str, consecutive_failures: int) -> None:
    new_count = consecutive_failures + 1
    health = "failing" if new_count >= FAILURE_THRESHOLD else "ok"
    conn.execute(
        sources_table.update()
        .where(sources_table.c.id == source_id)
        .values(consecutive_failures=new_count, health=health)
    )


def _record_success(conn: Connection, sources_table, source_id: str, now: datetime) -> None:
    conn.execute(
        sources_table.update()
        .where(sources_table.c.id == source_id)
        .values(consecutive_failures=0, health="ok", last_success_at=now)
    )


def ingest_source(
    conn: Connection,
    *,
    sources_table,
    news_items_table,
    source_row: Any,
    topics: list[dict[str, Any]],
    cycle_id: str,
    now: datetime,
) -> dict[str, Any]:
    adapter = ADAPTERS.get(source_row.source_type)
    if adapter is None:
        logger.error("source=%s no adapter registered for source_type=%s", source_row.id, source_row.source_type)
        return {"fetched": 0, "upserted": 0, "error": f"no adapter for {source_row.source_type}"}

    since = _since_for(source_row.last_success_at, now)
    source_config = SourceConfig(
        id=str(source_row.id),
        name=source_row.name,
        source_type=source_row.source_type,
        config=source_row.config,
        language=source_row.language,
    )

    secret = resolve_source_secret(conn, source_row)

    try:
        raw_items = adapter.fetch(source_config, since, topics=topics, secret=secret)
    except Exception as exc:  # noqa: BLE001 - a source failure must not fail the cycle (FR-I5)
        logger.warning("source=%s fetch failed: %s", source_row.id, exc)
        _record_failure(conn, sources_table, source_row.id, source_row.consecutive_failures)
        return {"fetched": 0, "upserted": 0, "error": str(exc)}

    upserted = 0
    for item in raw_items:
        if not item.url or not item.title:
            continue
        stmt = (
            pg_insert(news_items_table)
            .values(
                source_id=source_row.id,
                cycle_id=cycle_id,
                dedupe_key=dedupe_key(item.url),
                url=item.url,
                title=item.title,
                summary=item.summary,
                body_excerpt=item.body_excerpt,
                language=item.language,
                published_at=item.published_at,
                analysis_hints=item.analysis_hints,
            )
            .on_conflict_do_nothing(index_elements=["dedupe_key"])
            # psycopg reports rowcount=-1 (undeterminable) for ON CONFLICT
            # DO NOTHING inserts rather than 0-on-skip/1-on-insert, so
            # `if result.rowcount` is always truthy and silently counts
            # every skipped duplicate as ingested. RETURNING id is the
            # reliable signal: empty means the conflict fired.
            .returning(news_items_table.c.id)
        )
        result = conn.execute(stmt)
        if result.first() is not None:
            upserted += 1

    _record_success(conn, sources_table, source_row.id, now)
    return {"fetched": len(raw_items), "upserted": upserted}


def run_ingestion(conn: Connection, *, tables: dict[str, Any], cycle_id: str) -> dict[str, Any]:
    """Runs INGESTING for one cycle. Returns aggregate stats for
    cycles.stats. Iterates only `enabled = true` sources — a disabled
    source's adapter is never constructed or called."""
    sources_t = tables["sources"]
    news_items_t = tables["news_items"]
    topics_t = tables["topics"]

    now = datetime.now(timezone.utc)
    topics = _enabled_topics(conn, topics_t)

    enabled_sources = conn.execute(select(sources_t).where(sources_t.c.enabled.is_(True))).all()

    stats = {"sources_polled": 0, "sources_skipped_cadence": 0, "ingested": 0, "deduped": 0, "errors": 0}
    for source_row in enabled_sources:
        if not _due_by_cadence(source_row.poll_override_minutes, source_row.last_success_at, now):
            stats["sources_skipped_cadence"] += 1
            continue

        stats["sources_polled"] += 1
        result = ingest_source(
            conn,
            sources_table=sources_t,
            news_items_table=news_items_t,
            source_row=source_row,
            topics=topics,
            cycle_id=cycle_id,
            now=now,
        )
        if "error" in result:
            stats["errors"] += 1
        else:
            stats["ingested"] += result["upserted"]
            stats["deduped"] += result["fetched"] - result["upserted"]

    return stats
