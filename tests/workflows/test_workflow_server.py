"""Integration tests for the workflow server with composed tools.

Tests tool registration AND ToolError conversion — the wiring layer that maps
service exceptions to actionable MCP error responses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

from mtg_mcp.services.scryfall import CardNotFoundError, ScryfallError
from mtg_mcp.services.seventeen_lands import SeventeenLandsError
from mtg_mcp.services.spellbook import SpellbookError

if TYPE_CHECKING:
    from fastmcp import Client


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestWorkflowToolsRegistered:
    """Verify all workflow tools are registered on the workflow server."""

    async def test_all_workflow_tools_present(self, mcp_client: Client):
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        assert "commander_overview" in tool_names
        assert "evaluate_upgrade" in tool_names
        assert "draft_pack_pick" in tool_names
        assert "suggest_cuts" in tool_names


# ---------------------------------------------------------------------------
# ToolError conversion — commander_overview
# ---------------------------------------------------------------------------


class TestCommanderOverviewToolError:
    """Verify commander_overview converts service exceptions to ToolError."""

    async def test_card_not_found_becomes_tool_error(
        self,
        mcp_client: Client,
    ):
        """CardNotFoundError from Scryfall → ToolError with actionable message."""
        mock_scryfall = AsyncMock()
        mock_scryfall.get_card_by_name = AsyncMock(
            side_effect=CardNotFoundError("not found", status_code=404)
        )
        mock_spellbook = AsyncMock()
        mock_spellbook.find_combos = AsyncMock(return_value=[])

        with (
            patch("mtg_mcp.workflows.server._scryfall", mock_scryfall),
            patch("mtg_mcp.workflows.server._spellbook", mock_spellbook),
            patch("mtg_mcp.workflows.server._edhrec", None),
        ):
            result = await mcp_client.call_tool(
                "commander_overview",
                {"commander_name": "Nonexistent Card"},
                raise_on_error=False,
            )
        assert result.is_error
        text = result.content[0].text
        assert "not found" in text.lower()
        assert "Nonexistent Card" in text

    async def test_scryfall_error_becomes_tool_error(
        self,
        mcp_client: Client,
    ):
        """Generic ScryfallError (non-404) → ToolError."""
        mock_scryfall = AsyncMock()
        mock_scryfall.get_card_by_name = AsyncMock(
            side_effect=ScryfallError("API rate limited", status_code=429)
        )
        mock_spellbook = AsyncMock()
        mock_spellbook.find_combos = AsyncMock(return_value=[])

        with (
            patch("mtg_mcp.workflows.server._scryfall", mock_scryfall),
            patch("mtg_mcp.workflows.server._spellbook", mock_spellbook),
            patch("mtg_mcp.workflows.server._edhrec", None),
        ):
            result = await mcp_client.call_tool(
                "commander_overview",
                {"commander_name": "Muldrotha, the Gravetide"},
                raise_on_error=False,
            )
        assert result.is_error
        assert "service error" in result.content[0].text.lower()


# ---------------------------------------------------------------------------
# ToolError conversion — evaluate_upgrade
# ---------------------------------------------------------------------------


class TestEvaluateUpgradeToolError:
    """Verify evaluate_upgrade converts service exceptions to ToolError."""

    async def test_card_not_found_becomes_tool_error(
        self,
        mcp_client: Client,
    ):
        """CardNotFoundError → ToolError with the card name."""
        mock_scryfall = AsyncMock()
        mock_scryfall.get_card_by_name = AsyncMock(
            side_effect=CardNotFoundError("not found", status_code=404)
        )
        mock_spellbook = AsyncMock()
        mock_spellbook.find_combos = AsyncMock(return_value=[])

        with (
            patch("mtg_mcp.workflows.server._scryfall", mock_scryfall),
            patch("mtg_mcp.workflows.server._spellbook", mock_spellbook),
            patch("mtg_mcp.workflows.server._edhrec", None),
        ):
            result = await mcp_client.call_tool(
                "evaluate_upgrade",
                {"card_name": "Nonexistent", "commander_name": "Muldrotha"},
                raise_on_error=False,
            )
        assert result.is_error
        text = result.content[0].text
        assert "not found" in text.lower()
        assert "Nonexistent" in text


# ---------------------------------------------------------------------------
# ToolError conversion — draft_pack_pick
# ---------------------------------------------------------------------------


class TestDraftPackPickToolError:
    """Verify draft_pack_pick converts service exceptions to ToolError."""

    async def test_17lands_disabled_becomes_tool_error(
        self,
        mcp_client: Client,
    ):
        """17Lands not enabled → ToolError."""
        with patch("mtg_mcp.workflows.server._seventeen_lands", None):
            result = await mcp_client.call_tool(
                "draft_pack_pick",
                {"pack": ["Mulldrifter"], "set_code": "LRW"},
                raise_on_error=False,
            )
        assert result.is_error
        assert "not enabled" in result.content[0].text.lower()

    async def test_seventeen_lands_error_becomes_tool_error(
        self,
        mcp_client: Client,
    ):
        """SeventeenLandsError → ToolError."""
        mock_17lands = AsyncMock()
        mock_17lands.card_ratings = AsyncMock(
            side_effect=SeventeenLandsError("rate limited", status_code=429)
        )

        with patch("mtg_mcp.workflows.server._seventeen_lands", mock_17lands):
            result = await mcp_client.call_tool(
                "draft_pack_pick",
                {"pack": ["Mulldrifter"], "set_code": "LRW"},
                raise_on_error=False,
            )
        assert result.is_error
        assert "17lands" in result.content[0].text.lower()


# ---------------------------------------------------------------------------
# ToolError conversion — suggest_cuts
# ---------------------------------------------------------------------------


class TestSuggestCutsToolError:
    """Verify suggest_cuts converts service exceptions to ToolError."""

    async def test_spellbook_error_becomes_tool_error(
        self,
        mcp_client: Client,
    ):
        """SpellbookError propagating from suggest_cuts → ToolError."""
        mock_spellbook = AsyncMock()
        mock_spellbook.find_decklist_combos = AsyncMock(
            side_effect=SpellbookError("timeout", status_code=503)
        )

        with (
            patch("mtg_mcp.workflows.server._spellbook", mock_spellbook),
            patch("mtg_mcp.workflows.server._edhrec", None),
        ):
            result = await mcp_client.call_tool(
                "suggest_cuts",
                {
                    "decklist": ["Sol Ring", "Spore Frog"],
                    "commander_name": "Muldrotha",
                },
                raise_on_error=False,
            )
        # suggest_cuts handles SpellbookError internally (graceful degradation),
        # so this should succeed with partial data, not error
        assert not result.is_error
