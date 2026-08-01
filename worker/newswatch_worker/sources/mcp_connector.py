"""Generic MCP-client adapter (docs/02-architecture.md §4b, source_type='mcp').

Connection lifecycle: connect -> list_tools sanity check (configured tool
must exist, else health='failing' with a clear error) -> call tool per
enabled topic batch, highest-sensitivity first, capped by
max_calls_per_cycle -> map results via config.result_mapping -> close.
20s per call, one connector at a time. Auth token comes from a per-connector
env var (config.auth_env_var), never the DB.

Verified against the installed `mcp` package (2.0.0) API directly — see
worker/tests/test_sources_mcp_connector.py, which runs this adapter against
a real local MCP server (mcp.server.MCPServer over streamable HTTP on
localhost) rather than mocking the transport.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, TypeVar

import httpx2
import mcp
from mcp.client.streamable_http import streamable_http_client

from newswatch_worker.sources.base import RawItem, SourceConfig, TestResult

CALL_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_CALLS_PER_CYCLE = 10

T = TypeVar("T")


class McpToolNotFoundError(RuntimeError):
    pass


def _resolve_path(obj: Any, path: str) -> Any:
    """Tiny JSONPath-like resolver for the subset used in
    sources.config.result_mapping ('$.a.b', '$.a[0].b') — not a general
    JSONPath implementation, just what the spec's mapping shape needs."""
    if not path.startswith("$."):
        raise ValueError(f"unsupported path: {path}")
    current = obj
    for segment in path[2:].split("."):
        key, *bracket = segment.replace("]", "").split("[")
        if key:
            current = current.get(key) if isinstance(current, dict) else None
        for idx in bracket:
            if current is None:
                break
            index = int(idx)
            current = current[index] if isinstance(current, list) and index < len(current) else None
    return current


def resolve_items(obj: Any, items_path: str) -> list[Any]:
    """items_path is always of the form '$.a.b[*]' — the trailing [*]
    selects "every element of this list"."""
    if not items_path.endswith("[*]"):
        raise ValueError(f"unsupported items_path: {items_path}")
    container = _resolve_path(obj, items_path[:-3])
    if container is None:
        return []
    if not isinstance(container, list):
        raise ValueError(f"items_path {items_path!r} did not resolve to a list")
    return container


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _render_args(template: Any, topic_keywords: str) -> Any:
    if isinstance(template, str):
        return template.replace("{topic_keywords}", topic_keywords)
    if isinstance(template, dict):
        return {k: _render_args(v, topic_keywords) for k, v in template.items()}
    if isinstance(template, list):
        return [_render_args(v, topic_keywords) for v in template]
    return template


def _auth_headers(source: SourceConfig) -> dict[str, str]:
    env_var = source.config.get("auth_env_var")
    token = os.environ.get(env_var) if env_var else None
    return {"Authorization": f"Bearer {token}"} if token else {}


async def _with_session(source: SourceConfig, fn: Callable[[mcp.ClientSession], Awaitable[T]]) -> T:
    server_url = source.config["server_url"]
    client = httpx2.AsyncClient(
        headers=_auth_headers(source), timeout=httpx2.Timeout(CALL_TIMEOUT_SECONDS)
    )
    async with streamable_http_client(server_url, http_client=client) as (read, write):
        async with mcp.ClientSession(read, write) as session:
            await session.initialize()
            return await fn(session)


def _tool_result_payload(result: mcp.types.CallToolResult) -> dict[str, Any]:
    """Prefer structured_content, but most tools (verified against both a
    local test server and the real bigdata_search tool) don't declare an
    output schema, so the actual payload arrives as a JSON-serialized
    TextContent block instead — parse that before falling back to a raw
    {"text": ...} wrapper the configured result_mapping can't reach into.
    """
    if result.structured_content is not None:
        return result.structured_content

    text_blocks = [b.text for b in result.content if getattr(b, "type", None) == "text"]
    joined = "\n".join(text_blocks)
    try:
        parsed = json.loads(joined)
    except (json.JSONDecodeError, ValueError):
        return {"text": joined}
    return parsed if isinstance(parsed, dict) else {"text": joined}


def _map_result_items(payload: dict[str, Any], result_mapping: dict[str, str]) -> list[RawItem]:
    items: list[RawItem] = []
    for raw in resolve_items(payload, result_mapping["items_path"]):
        items.append(
            RawItem(
                title=str(_resolve_path(raw, result_mapping["title"]) or "").strip(),
                url=str(_resolve_path(raw, result_mapping["url"]) or "").strip(),
                summary=_resolve_path(raw, result_mapping.get("summary", "")) or None,
                body_excerpt=(str(_resolve_path(raw, result_mapping.get("summary", "")) or ""))[:2000]
                or None,
                published_at=_parse_datetime(_resolve_path(raw, result_mapping.get("published_at", ""))),
                analysis_hints=_resolve_path(raw, result_mapping["hints"])
                if "hints" in result_mapping
                else None,
            )
        )
    return items


async def _fetch_async(source: SourceConfig, topics: list[dict[str, Any]]) -> list[RawItem]:
    tool_name = source.config["tool_name"]
    args_template = source.config["args_template"]
    result_mapping = source.config["result_mapping"]
    max_calls = source.config.get("max_calls_per_cycle", DEFAULT_MAX_CALLS_PER_CYCLE)

    async def run(session: mcp.ClientSession) -> list[RawItem]:
        tools = await session.list_tools()
        tool_names = {t.name for t in tools.tools}
        if tool_name not in tool_names:
            raise McpToolNotFoundError(
                f"configured tool {tool_name!r} not found on {source.config['server_url']} "
                f"(available: {sorted(tool_names)})"
            )

        ordered_topics = sorted(
            topics, key=lambda t: -float(t.get("sensitivity") or 0)
        )[:max_calls]

        items: list[RawItem] = []
        for topic in ordered_topics:
            keywords = ", ".join(topic.get("keywords") or []) or topic["name"]
            args = _render_args(args_template, keywords)
            result = await session.call_tool(
                tool_name, args, read_timeout_seconds=CALL_TIMEOUT_SECONDS
            )
            payload = _tool_result_payload(result)
            items.extend(_map_result_items(payload, result_mapping))
        return items

    return await _with_session(source, run)


async def _test_async(source: SourceConfig) -> TestResult:
    tool_name = source.config["tool_name"]

    async def run(session: mcp.ClientSession) -> TestResult:
        tools = await session.list_tools()
        tool_names = {t.name for t in tools.tools}
        if tool_name not in tool_names:
            return TestResult(
                ok=False,
                error=f"configured tool {tool_name!r} not found (available: {sorted(tool_names)})",
            )

        args = _render_args(source.config["args_template"], "market news")
        result = await session.call_tool(tool_name, args, read_timeout_seconds=CALL_TIMEOUT_SECONDS)
        payload = _tool_result_payload(result)
        items = _map_result_items(payload, source.config["result_mapping"])
        return TestResult(ok=True, item_count=len(items), sample_titles=[i.title for i in items[:3]])

    return await _with_session(source, run)


def _unwrap_exception_group(exc: BaseException) -> BaseException:
    """anyio's TaskGroup wraps child-task exceptions in (Base)ExceptionGroup,
    often several levels deep (streamable_http_client's group inside
    ClientSession's group). Surface the first real exception so callers see
    e.g. "tool 'x' not found" instead of "unhandled errors in a TaskGroup".
    """
    while isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:
        exc = exc.exceptions[0]
    return exc


class McpConnectorAdapter:
    source_type = "mcp"

    def fetch(
        self,
        source: SourceConfig,
        since: datetime,
        *,
        topics: list[dict[str, Any]] | None = None,
    ) -> list[RawItem]:
        try:
            items = asyncio.run(_fetch_async(source, topics or []))
        except BaseExceptionGroup as exc:
            raise _unwrap_exception_group(exc) from exc
        return [i for i in items if i.url and (i.published_at is None or i.published_at >= since)]

    def test(self, source: SourceConfig) -> TestResult:
        try:
            return asyncio.run(_test_async(source))
        except BaseExceptionGroup as exc:
            return TestResult(ok=False, error=str(_unwrap_exception_group(exc)))
        except Exception as exc:  # noqa: BLE001
            return TestResult(ok=False, error=str(exc))
