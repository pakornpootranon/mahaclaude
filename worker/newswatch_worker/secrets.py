"""Source/connector credential resolution (docs/02 §9 override, 2026-08-02):
originally Finnhub/NewsAPI/MCP connector tokens were env-only, with the
Claude API key as the sole DB-backed exception. That decision changed at
the user's request - these now follow the exact same pattern as the Claude
key (`llm/client.py`'s `resolve_api_key`): DB row in the shared `secrets`
table wins, `.env` is the fallback for anyone who prefers it. Generalized
here rather than duplicated, since it's now three call sites (finnhub,
newsapi, mcp) instead of one.
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Connection

from newswatch_worker.db import table

FINNHUB_SECRET_KEY = "finnhub_api_key"
NEWSAPI_SECRET_KEY = "newsapi_api_key"


def mcp_connector_secret_key(source_id: str) -> str:
    """Unlike Finnhub/NewsAPI (one account per install), each MCP connector
    is a user-added row that can point at a different server entirely - the
    secret has to be scoped per source id, not a single shared key name."""
    return f"mcp_connector_token:{source_id}"


def resolve_secret(conn: Connection, *, db_key: str, env_var: str | None) -> str | None:
    secrets_t = table("secrets")
    row = conn.execute(select(secrets_t.c.value).where(secrets_t.c.key == db_key)).first()
    if row is not None and row[0]:
        return row[0]
    return os.environ.get(env_var) if env_var else None


def resolve_source_secret(conn: Connection, source_row: Any) -> str | None:
    """Dispatches by source_type to the right (db_key, env_var) pair. Shared
    by ingest.py (real polling) and source_tests.py (the Settings 'Test'
    button) so both paths resolve credentials identically."""
    if source_row.source_type == "finnhub":
        return resolve_secret(conn, db_key=FINNHUB_SECRET_KEY, env_var="FINNHUB_KEY")
    if source_row.source_type == "newsapi":
        return resolve_secret(conn, db_key=NEWSAPI_SECRET_KEY, env_var="NEWSAPI_KEY")
    if source_row.source_type == "mcp":
        config = source_row.config or {}
        return resolve_secret(
            conn,
            db_key=mcp_connector_secret_key(str(source_row.id)),
            env_var=config.get("auth_env_var"),
        )
    return None
