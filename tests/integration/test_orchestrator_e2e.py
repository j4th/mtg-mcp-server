"""Integration tests for the MTG orchestrator end-to-end.

Tests verify tool registration, tool invocation through the full MCP pipeline,
and basic health checks with all HTTP backends mocked via fixture data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from fastmcp import Client


pytestmark = pytest.mark.integration


class TestToolRegistration:
    """Verify the orchestrator exposes the expected tools."""

    async def test_all_23_tools_registered(self, mcp_client: Client):
        """The orchestrator exposes exactly 23 tools."""
        tools = await mcp_client.list_tools()
        tool_names = sorted(t.name for t in tools)
        # 1 ping + 4 scryfall + 4 spellbook + 2 draft + 2 edhrec + 2 bulk + 8 workflows = 23
        assert len(tools) == 23, f"Expected 23 tools, got {len(tools)}.\nTools: {tool_names}"

    async def test_no_mtgjson_tools(self, mcp_client: Client):
        """No tool names contain 'mtgjson' (replaced by Scryfall bulk data)."""
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        mtgjson_tools = [name for name in tool_names if "mtgjson" in name]
        assert not mtgjson_tools, f"Unexpected mtgjson tools: {mtgjson_tools}"

    async def test_bulk_tools_present(self, mcp_client: Client):
        """bulk_card_lookup and bulk_card_search are registered."""
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        assert "bulk_card_lookup" in tool_names
        assert "bulk_card_search" in tool_names


class TestScryfall:
    """Scryfall tools through the orchestrator."""

    async def test_card_details_returns_data(self, mcp_client: Client):
        """scryfall_card_details returns card info with type line."""
        result = await mcp_client.call_tool("scryfall_card_details", {"name": "Sol Ring"})
        text = result.content[0].text
        assert "Artifact" in text

    async def test_search_cards_returns_results(self, mcp_client: Client):
        """scryfall_search_cards returns search results."""
        result = await mcp_client.call_tool(
            "scryfall_search_cards", {"query": "f:commander id:sultai t:creature"}
        )
        text = result.content[0].text
        assert len(text) > 0


class TestPing:
    """Orchestrator health check."""

    async def test_ping_returns_pong(self, mcp_client: Client):
        """ping tool returns 'pong'."""
        result = await mcp_client.call_tool("ping", {})
        assert result.data == "pong"
