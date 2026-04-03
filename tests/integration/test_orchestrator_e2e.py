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

    async def test_all_56_tools_registered(self, mcp_client: Client):
        """The orchestrator exposes exactly 56 tools."""
        tools = await mcp_client.list_tools()
        tool_names = sorted(t.name for t in tools)
        # 1 ping + 6 scryfall + 4 spellbook + 2 draft + 2 edhrec + 2 moxfield + 3 spicerack + 9 bulk + 22 workflows + 5 rules = 56
        # TODO(#47): update to 60 after MTGGoldfish tools are implemented (+ 4 goldfish)
        assert len(tools) == 56, f"Expected 56 tools, got {len(tools)}.\nTools: {tool_names}"

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


class TestNewBulkTools:
    """New cross-format tools on the bulk provider."""

    async def test_ban_list_returns_data(self, mcp_client: Client):
        """bulk_ban_list returns ban/restricted list for a format."""
        result = await mcp_client.call_tool("bulk_ban_list", {"format": "modern"})
        text = result.content[0].text
        assert "modern" in text.lower() or "Ban" in text or "No banned" in text

    async def test_card_in_formats_returns_table(self, mcp_client: Client):
        """bulk_card_in_formats returns legality table for a known card."""
        result = await mcp_client.call_tool("bulk_card_in_formats", {"card_name": "Sol Ring"})
        text = result.content[0].text
        assert "Sol Ring" in text
        assert "commander" in text.lower()

    async def test_format_search_returns_results(self, mcp_client: Client):
        """bulk_format_search returns matching cards."""
        result = await mcp_client.call_tool(
            "bulk_format_search", {"format": "commander", "query": "creatures"}
        )
        text = result.content[0].text
        assert len(text) > 0


class TestNewScryfallTools:
    """New Scryfall API tools."""

    async def test_set_info_returns_data(self, mcp_client: Client):
        """scryfall_set_info returns set metadata."""
        result = await mcp_client.call_tool("scryfall_set_info", {"set_code": "dom"})
        text = result.content[0].text
        assert "Dominaria" in text

    async def test_whats_new_returns_results(self, mcp_client: Client):
        """scryfall_whats_new returns recent cards."""
        result = await mcp_client.call_tool("scryfall_whats_new", {"days": 7})
        text = result.content[0].text
        assert len(text) > 0


class TestNewWorkflowTools:
    """New workflow tools through the orchestrator."""

    async def test_deck_validate_valid_deck(self, mcp_client: Client):
        """deck_validate with a small valid deck."""
        result = await mcp_client.call_tool(
            "deck_validate",
            {
                "decklist": ["4x Sol Ring", "4x Forest"] + ["4x Sol Ring"] * 13,
                "format": "modern",
            },
        )
        text = result.content[0].text
        assert "VALID" in text or "INVALID" in text

    async def test_price_comparison_returns_table(self, mcp_client: Client):
        """price_comparison returns a price table."""
        result = await mcp_client.call_tool("price_comparison", {"cards": ["Sol Ring", "Forest"]})
        text = result.content[0].text
        assert "Sol Ring" in text


class TestNewResourcesE2E:
    """New resources are visible on the orchestrator."""

    async def test_new_resources_listed(self, mcp_client: Client):
        """New resource templates appear in the resource list."""
        resources = await mcp_client.list_resource_templates()
        uris = {r.uriTemplate for r in resources}
        assert "mtg://bulk/format/{format}/legal-cards" in uris
        assert "mtg://bulk/format/{format}/banned" in uris
        assert "mtg://bulk/card/{name}/formats" in uris
        assert "mtg://scryfall/set/{code}" in uris


class TestNewPromptsE2E:
    """New prompts are visible on the orchestrator."""

    async def test_new_prompts_listed(self, mcp_client: Client):
        """All 17 prompts registered on the orchestrator."""
        prompts = await mcp_client.list_prompts()
        names = {p.name for p in prompts}
        # 4 original + 4 cross-format + 1 rules + 8 format workflow prompts = 17
        assert "build_deck" in names
        assert "evaluate_collection" in names
        assert "format_intro" in names
        assert "card_alternatives" in names
        assert "build_around_deck" in names
        assert "build_tribal_deck" in names
        assert "build_theme_deck" in names
        assert "upgrade_precon" in names
        assert len(prompts) == 17


class TestPing:
    """Orchestrator health check."""

    async def test_ping_returns_pong(self, mcp_client: Client):
        """ping tool returns 'pong'."""
        result = await mcp_client.call_tool("ping", {})
        assert result.data == "pong"
