"""Integration tests against a real Postgres (per DATABASE_URL) proving the
PRD's ingestion acceptance criteria: idempotent re-runs, graceful failure
handling with health tracking, and that a disabled connector is never
dialed.

`run_ingestion` operates on every enabled source in the table by design (a
real cycle polls everything configured) — so these tests disable whatever
sources already exist (e.g. Phase 1's seed data) for their duration and
restore them afterward, rather than deleting/mutating that data.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")


def _feed_xml(items: list[tuple[str, str, str, datetime]]) -> bytes:
    """Builds a minimal RSS feed with timestamps relative to *now*, so the
    ingestion's default 24h lookback (newswatch_worker.ingest._since_for)
    never filters fixture items out no matter when the suite runs."""
    entries = "\n".join(
        f"""    <item>
      <title>{title}</title>
      <link>{link}</link>
      <description>{summary}</description>
      <pubDate>{pub_date.strftime('%a, %d %b %Y %H:%M:%S GMT')}</pubDate>
    </item>"""
        for title, link, summary, pub_date in items
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <link>https://example.com</link>
    <description>Test fixture feed</description>
{entries}
  </channel>
</rss>
""".encode()


def _sample_feed(now: datetime) -> bytes:
    return _feed_xml(
        [
            (
                "OPEC+ agrees to extend production cuts through Q3",
                "https://example.com/news/opec-cuts",
                "OPEC+ ministers agreed on Sunday to extend existing production cuts.",
                now - timedelta(hours=1),
            ),
            (
                "Fed signals potential rate cut in September meeting",
                "https://example.com/news/fed-rate-cut",
                "Federal Reserve officials hinted at a possible rate cut.",
                now - timedelta(hours=2),
            ),
            (
                "Local bakery wins county fair award",
                "https://example.com/news/bakery-award",
                "A small local bakery took home first prize.",
                now - timedelta(hours=3),
            ),
        ]
    )


@pytest.fixture(autouse=True)
def _isolate_sources():
    """Disable every pre-existing source (e.g. Phase 1 seed data) for the
    duration of the test, so run_ingestion only ever touches sources the
    test itself created — otherwise every ingest test would also poll the
    real seeded feeds. Restores the original enabled state afterward."""
    from newswatch_worker.db import get_engine, table

    engine = get_engine()
    sources_t = table("sources")

    with engine.begin() as conn:
        previously_enabled_ids = [
            row.id for row in conn.execute(select(sources_t.c.id).where(sources_t.c.enabled.is_(True))).all()
        ]
        if previously_enabled_ids:
            conn.execute(sources_t.update().where(sources_t.c.id.in_(previously_enabled_ids)).values(enabled=False))

    yield

    with engine.begin() as conn:
        conn.execute(table("news_items").delete())
        conn.execute(table("cycles").delete())
        conn.execute(sources_t.delete().where(sources_t.c.name.like("test-%")))
        if previously_enabled_ids:
            conn.execute(sources_t.update().where(sources_t.c.id.in_(previously_enabled_ids)).values(enabled=True))


def _insert_source(conn, sources_t, *, name: str, source_type: str, config: dict, enabled: bool = True):
    result = conn.execute(
        sources_t.insert()
        .values(name=name, source_type=source_type, config=config, enabled=enabled)
        .returning(sources_t.c.id)
    )
    return str(result.scalar_one())


def _insert_cycle(conn, cycles_t) -> str:
    result = conn.execute(
        cycles_t.insert()
        .values(scheduled_for=datetime.now(timezone.utc), kind="manual", state="INGESTING", stats={})
        .returning(cycles_t.c.id)
    )
    return str(result.scalar_one())


def test_ingest_upserts_news_items_from_rss_source(local_http_server, base_url):
    from newswatch_worker.db import get_engine, table
    from newswatch_worker.ingest import run_ingestion

    local_http_server.routes["/feed.xml"] = (200, _sample_feed(datetime.now(timezone.utc)), "application/rss+xml")
    engine = get_engine()
    tables = {"sources": table("sources"), "news_items": table("news_items"), "topics": table("topics")}

    with engine.begin() as conn:
        source_id = _insert_source(
            conn, tables["sources"], name="test-rss", source_type="rss", config={"url": f"{base_url}/feed.xml"}
        )
        cycle_id = _insert_cycle(conn, table("cycles"))
        stats = run_ingestion(conn, tables=tables, cycle_id=cycle_id)

    assert stats["ingested"] == 3
    assert stats["errors"] == 0

    with engine.begin() as conn:
        rows = conn.execute(
            select(tables["news_items"].c.title, tables["news_items"].c.source_id).where(
                tables["news_items"].c.source_id == source_id
            )
        ).all()
        source_row = conn.execute(
            select(tables["sources"]).where(tables["sources"].c.id == source_id)
        ).first()

    assert len(rows) == 3
    assert source_row.health == "ok"
    assert source_row.consecutive_failures == 0
    assert source_row.last_success_at is not None


def test_reingest_produces_zero_duplicates(local_http_server, base_url):
    """PRD acceptance #4 / Phase 2 verify: re-run produces zero duplicates —
    count(*) == count(DISTINCT dedupe_key)."""
    from newswatch_worker.db import get_engine, table
    from newswatch_worker.ingest import run_ingestion

    local_http_server.routes["/feed.xml"] = (200, _sample_feed(datetime.now(timezone.utc)), "application/rss+xml")
    engine = get_engine()
    tables = {"sources": table("sources"), "news_items": table("news_items"), "topics": table("topics")}

    with engine.begin() as conn:
        source_id = _insert_source(
            conn, tables["sources"], name="test-rss", source_type="rss", config={"url": f"{base_url}/feed.xml"}
        )
        cycle_id = _insert_cycle(conn, table("cycles"))
        run_ingestion(conn, tables=tables, cycle_id=cycle_id)

    # Re-run against the *same* since-window (this is what actually happens
    # on PRD acceptance #4's "kill mid-cycle, re-run" — the crashed attempt
    # never recorded last_success_at, so the retry recomputes an identical
    # `since`). Fetching the same feed again should hit ON CONFLICT DO
    # NOTHING for every item, not re-filter them out via the lookback window.
    with engine.begin() as conn:
        conn.execute(
            tables["sources"].update().where(tables["sources"].c.id == source_id).values(last_success_at=None)
        )
        cycle_id_2 = _insert_cycle(conn, table("cycles"))
        stats = run_ingestion(conn, tables=tables, cycle_id=cycle_id_2)

    assert stats["ingested"] == 0
    assert stats["deduped"] == 3

    with engine.begin() as conn:
        total, distinct = conn.execute(
            select(func.count(), func.count(func.distinct(tables["news_items"].c.dedupe_key)))
        ).one()

    assert total == distinct == 3


def test_source_failure_does_not_raise_and_tracks_health(local_http_server, base_url):
    from newswatch_worker.db import get_engine, table
    from newswatch_worker.ingest import FAILURE_THRESHOLD, run_ingestion

    # A fast, deterministic failure (404, no retry per http_client.py) rather
    # than an actually-unreachable host — avoids depending on how quickly
    # this sandbox's network stack reports connection-refused.
    engine = get_engine()
    tables = {"sources": table("sources"), "news_items": table("news_items"), "topics": table("topics")}

    with engine.begin() as conn:
        source_id = _insert_source(
            conn,
            tables["sources"],
            name="test-dead-rss",
            source_type="rss",
            config={"url": f"{base_url}/missing.xml"},
        )

    for _ in range(FAILURE_THRESHOLD):
        with engine.begin() as conn:
            cycle_id = _insert_cycle(conn, table("cycles"))
            stats = run_ingestion(conn, tables=tables, cycle_id=cycle_id)
            assert stats["errors"] == 1  # never raises — degrades gracefully (FR-I5)

    with engine.begin() as conn:
        source_row = conn.execute(
            select(tables["sources"]).where(tables["sources"].c.id == source_id)
        ).first()

    assert source_row.consecutive_failures == FAILURE_THRESHOLD
    assert source_row.health == "failing"


def test_disabled_mcp_connector_is_never_dialed(mock_mcp_server):
    """Phase 2 verify: a disabled MCP connector is provably never dialed —
    assert zero calls in the mock server's call log."""
    from newswatch_worker.db import get_engine, table
    from newswatch_worker.ingest import run_ingestion

    server_url, call_log = mock_mcp_server
    engine = get_engine()
    tables = {"sources": table("sources"), "news_items": table("news_items"), "topics": table("topics")}

    with engine.begin() as conn:
        _insert_source(
            conn,
            tables["sources"],
            name="test-mcp-disabled",
            source_type="mcp",
            enabled=False,
            config={
                "server_url": server_url,
                "tool_name": "bigdata_search",
                "args_template": {"request": {"search_mode": "smart", "query": {"text": "{topic_keywords}"}}},
                "result_mapping": {"items_path": "$.results[*]", "title": "$.headline", "url": "$.url"},
            },
        )
        cycle_id = _insert_cycle(conn, table("cycles"))
        stats = run_ingestion(conn, tables=tables, cycle_id=cycle_id)

    assert stats["sources_polled"] == 0
    assert call_log == []


def test_cadence_override_skips_source_polled_too_recently(local_http_server, base_url):
    from newswatch_worker.db import get_engine, table
    from newswatch_worker.ingest import run_ingestion

    local_http_server.routes["/feed.xml"] = (200, _sample_feed(datetime.now(timezone.utc)), "application/rss+xml")
    engine = get_engine()
    tables = {"sources": table("sources"), "news_items": table("news_items"), "topics": table("topics")}

    with engine.begin() as conn:
        source_id = _insert_source(
            conn, tables["sources"], name="test-cadence", source_type="rss", config={"url": f"{base_url}/feed.xml"}
        )
        conn.execute(
            tables["sources"]
            .update()
            .where(tables["sources"].c.id == source_id)
            .values(
                poll_override_minutes=60,
                last_success_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            )
        )
        cycle_id = _insert_cycle(conn, table("cycles"))
        stats = run_ingestion(conn, tables=tables, cycle_id=cycle_id)

    assert stats["sources_polled"] == 0
    assert stats["sources_skipped_cadence"] == 1
