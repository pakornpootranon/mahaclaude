from __future__ import annotations

from datetime import datetime, timezone

from newswatch_worker.sources.base import SourceConfig
from newswatch_worker.sources.mcp_connector import McpConnectorAdapter

RESULT_MAPPING = {
    "items_path": "$.results[*]",
    "title": "$.headline",
    "url": "$.url",
    "summary": "$.chunks[0].text",
    "published_at": "$.timestamp",
    "hints": "$.source",
}


def _source(server_url: str) -> SourceConfig:
    return SourceConfig(
        id="s1",
        name="Mock Bigdata",
        source_type="mcp",
        config={
            "server_url": server_url,
            "transport": "streamable_http",
            "tool_name": "bigdata_search",
            "args_template": {
                "request": {
                    "search_mode": "smart",
                    "query": {"text": "{topic_keywords} latest news", "context": "search in news"},
                }
            },
            "result_mapping": RESULT_MAPPING,
            "max_calls_per_cycle": 5,
        },
    )


def test_fetch_calls_tool_once_per_topic_and_maps_results(mock_mcp_server):
    server_url, call_log = mock_mcp_server
    source = _source(server_url)
    topics = [
        {"id": "t1", "name": "Oil supply shocks", "keywords": ["OPEC", "crude"], "sensitivity": 0.7},
        {"id": "t2", "name": "Fed rate decisions", "keywords": ["FOMC"], "sensitivity": 0.65},
    ]

    items = McpConnectorAdapter().fetch(source, since=datetime(2020, 1, 1, tzinfo=timezone.utc), topics=topics)

    assert len(call_log) == 2  # one call per enabled topic
    # highest-sensitivity topic queried first. call_log entries are the
    # `request` tool argument's *value* (the MCP server unwraps the single
    # top-level arg to the tool function's parameter), not a {"request": ...}
    # wrapper.
    assert "OPEC" in call_log[0]["query"]["text"]
    # each call returns 2 mapped items -> 4 total (dedupe happens later, at ingest time)
    assert len(items) == 4
    assert items[0].title == "OPEC+ agrees to extend production cuts through Q3"
    assert items[0].url == "https://example.com/documents/AAA111"
    assert items[0].summary == "OPEC+ ministers agreed on Sunday to extend cuts."
    assert items[0].published_at == datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)
    assert items[0].analysis_hints == {"name": "Reuters"}


def test_fetch_caps_calls_at_max_calls_per_cycle(mock_mcp_server):
    server_url, call_log = mock_mcp_server
    source = _source(server_url)
    source.config["max_calls_per_cycle"] = 1
    topics = [
        {"id": "t1", "name": "Low sensitivity", "keywords": [], "sensitivity": 0.5},
        {"id": "t2", "name": "High sensitivity", "keywords": [], "sensitivity": 0.9},
    ]

    McpConnectorAdapter().fetch(source, since=datetime(2020, 1, 1, tzinfo=timezone.utc), topics=topics)

    assert len(call_log) == 1
    assert "High sensitivity" in call_log[0]["query"]["text"]


def test_fetch_raises_when_configured_tool_missing(mock_mcp_server):
    server_url, _ = mock_mcp_server
    source = _source(server_url)
    source.config["tool_name"] = "does_not_exist"

    try:
        McpConnectorAdapter().fetch(source, since=datetime(2020, 1, 1, tzinfo=timezone.utc), topics=[])
        assert False, "expected McpToolNotFoundError"
    except Exception as exc:  # noqa: BLE001
        assert "does_not_exist" in str(exc)


def test_test_method_reports_sample_titles(mock_mcp_server):
    server_url, call_log = mock_mcp_server
    source = _source(server_url)

    result = McpConnectorAdapter().test(source)

    assert result.ok is True
    assert result.item_count == 2
    assert len(call_log) == 1
