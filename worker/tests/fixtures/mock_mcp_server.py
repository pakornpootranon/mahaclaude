"""A real local MCP server (mirroring the shape the Bigdata.com bigdata_search
tool actually returns, verified live in-session — see seed.ts comments) used
to test McpConnectorAdapter end-to-end instead of mocking the transport.
"""

from __future__ import annotations

from mcp.server import MCPServer

SAMPLE_RESULTS = {
    "results": [
        {
            "id": "AAA111",
            "headline": "OPEC+ agrees to extend production cuts through Q3",
            "timestamp": "2026-07-01T09:00:00",
            "source": {"name": "Reuters"},
            "chunks": [{"cnum": 1, "text": "OPEC+ ministers agreed on Sunday to extend cuts."}],
            "url": "https://example.com/documents/AAA111",
        },
        {
            "id": "BBB222",
            "headline": "Fed signals potential rate cut in September meeting",
            "timestamp": "2026-07-01T08:30:00",
            "source": {"name": "CNBC"},
            "chunks": [{"cnum": 1, "text": "Federal Reserve officials hinted at a possible rate cut."}],
            "url": "https://example.com/documents/BBB222",
        },
    ]
}


def build_server() -> MCPServer:
    server = MCPServer(name="mock-bigdata")
    call_log: list[dict] = []
    server.call_log = call_log  # type: ignore[attr-defined]

    @server.tool(name="bigdata_search")
    def bigdata_search(request: dict) -> dict:
        call_log.append(request)
        return SAMPLE_RESULTS

    return server
