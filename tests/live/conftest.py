"""Fixtures for live smoke tests — starts a real server subprocess."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import time

import httpx
import pytest
from fastmcp import Client


def _find_free_port() -> int:
    """Bind to port 0 and let the OS assign a free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server():
    """Start the MTG MCP server as a subprocess on a free port.

    Waits up to 30 seconds for the server to become ready by polling
    the ``/mcp`` endpoint. Yields connection info, then terminates the
    subprocess on teardown.
    """
    port = _find_free_port()
    url = f"http://127.0.0.1:{port}/mcp"

    env = {
        **os.environ,
        "MTG_MCP_HTTP_PORT": str(port),
        "MTG_MCP_DISABLE_CACHE": "true",
    }

    process = subprocess.Popen(
        ["uv", "run", "python", "-m", "mtg_mcp_server.server", "http"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Poll until the server is accepting connections (up to 30s).
    deadline = time.monotonic() + 30
    ready = False
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(url, timeout=2)
            if resp.status_code < 500:
                ready = True
                break
        except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError):
            pass
        time.sleep(1)

    if not ready:
        process.terminate()
        process.wait(timeout=5)
        stderr_output = process.stderr.read().decode() if process.stderr else ""
        pytest.fail(f"Live server did not become ready within 30s. stderr:\n{stderr_output}")

    yield {"port": port, "url": url}

    # Teardown: graceful termination, then close pipes to avoid ResourceWarning.
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.send_signal(signal.SIGKILL)
        process.wait(timeout=5)
    if process.stdout:
        process.stdout.close()
    if process.stderr:
        process.stderr.close()


@pytest.fixture
async def live_client(live_server):
    """FastMCP Client connected to the live server over HTTP.

    Function-scoped so each test gets a client on its own event loop.
    The server subprocess (session-scoped) stays alive across all tests.
    """
    async with Client(live_server["url"]) as client:
        yield client
