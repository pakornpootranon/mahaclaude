from __future__ import annotations

import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import uvicorn


class _StaticServer(ThreadingHTTPServer):
    routes: dict[str, tuple[int, bytes, str]] = {}
    daemon_threads = True


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # noqa: D401 - silence test server logging
        pass

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        path_only = self.path.split("?", 1)[0]
        route = self.server.routes.get(path_only)
        if route is None:
            self.send_response(404)
            self.end_headers()
            return
        status, body, content_type = route
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def local_http_server():
    """A tiny threaded HTTP server serving fixed responses at fixed paths,
    for testing adapters against realistic payloads without live network
    access (unavailable in this build environment for the real feed hosts).
    Use `server.routes[path] = (status, body_bytes, content_type)`.
    """
    server = _StaticServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture
def base_url(local_http_server):
    host, port = local_http_server.server_address
    return f"http://{host}:{port}"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(host: str, port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex((host, port)) == 0:
                return
        time.sleep(0.05)
    raise TimeoutError(f"nothing listening on {host}:{port} after {timeout}s")


@pytest.fixture
def mock_mcp_server():
    """A real local MCP server (streamable HTTP over uvicorn), so
    McpConnectorAdapter tests exercise the real `mcp` client/server wire
    protocol rather than a mocked transport. Yields (base_url, call_log).
    """
    from tests.fixtures.mock_mcp_server import build_server

    server = build_server()
    app = server.streamable_http_app()
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    uv_server = uvicorn.Server(config)

    thread = threading.Thread(target=uv_server.run, daemon=True)
    thread.start()
    _wait_for_port("127.0.0.1", port)

    try:
        yield f"http://127.0.0.1:{port}/mcp", server.call_log
    finally:
        uv_server.should_exit = True
        thread.join(timeout=5)
