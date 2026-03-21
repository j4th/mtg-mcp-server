"""Shared test fixtures for MTG MCP server tests."""

from __future__ import annotations

import pytest
from fastmcp import Client

from mtg_mcp.server import mcp


@pytest.fixture
async def mcp_client():
    """In-memory MCP client connected to the orchestrator."""
    async with Client(transport=mcp) as client:
        yield client
