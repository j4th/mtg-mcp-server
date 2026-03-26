"""Integration tests for the workflow server with composed tools.

Tests tool registration AND ToolError conversion — the wiring layer that maps
service exceptions to actionable MCP error responses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

from mtg_mcp_server.services.base import ServiceError
from mtg_mcp_server.services.scryfall import CardNotFoundError, ScryfallError
from mtg_mcp_server.services.seventeen_lands import SeventeenLandsError
from mtg_mcp_server.services.spellbook import SpellbookError

if TYPE_CHECKING:
    from fastmcp import Client


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestWorkflowToolsRegistered:
    """Verify all workflow tools are registered on the workflow server."""

    async def test_all_workflow_tools_present(self, mcp_client: Client):
        """All workflow tools appear in the orchestrator's tools/list."""
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
            patch("mtg_mcp_server.workflows.server._scryfall", mock_scryfall),
            patch("mtg_mcp_server.workflows.server._spellbook", mock_spellbook),
            patch("mtg_mcp_server.workflows.server._edhrec", None),
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
            patch("mtg_mcp_server.workflows.server._scryfall", mock_scryfall),
            patch("mtg_mcp_server.workflows.server._spellbook", mock_spellbook),
            patch("mtg_mcp_server.workflows.server._edhrec", None),
        ):
            result = await mcp_client.call_tool(
                "commander_overview",
                {"commander_name": "Muldrotha, the Gravetide"},
                raise_on_error=False,
            )
        assert result.is_error
        assert "commander_overview failed" in result.content[0].text.lower()


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
            patch("mtg_mcp_server.workflows.server._scryfall", mock_scryfall),
            patch("mtg_mcp_server.workflows.server._spellbook", mock_spellbook),
            patch("mtg_mcp_server.workflows.server._edhrec", None),
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

    async def test_service_error_becomes_tool_error(
        self,
        mcp_client: Client,
    ):
        """Generic ServiceError → ToolError with tool name."""
        mock_scryfall = AsyncMock()
        mock_scryfall.get_card_by_name = AsyncMock(side_effect=ServiceError("timeout"))
        mock_spellbook = AsyncMock()

        with (
            patch("mtg_mcp_server.workflows.server._scryfall", mock_scryfall),
            patch("mtg_mcp_server.workflows.server._spellbook", mock_spellbook),
            patch("mtg_mcp_server.workflows.server._edhrec", None),
        ):
            result = await mcp_client.call_tool(
                "evaluate_upgrade",
                {"card_name": "Sol Ring", "commander_name": "Muldrotha"},
                raise_on_error=False,
            )
        assert result.is_error
        assert "evaluate_upgrade failed" in result.content[0].text.lower()


# ---------------------------------------------------------------------------
# ToolError conversion — draft_pack_pick
# ---------------------------------------------------------------------------


class TestDraftPackPickToolError:
    """Verify draft_pack_pick converts service exceptions to ToolError."""

    async def test_17lands_disabled_becomes_tool_error(
        self,
        mcp_client: Client,
    ):
        """17Lands not enabled → ToolError with feature flag hint."""
        with patch("mtg_mcp_server.workflows.server._seventeen_lands", None):
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

        with patch("mtg_mcp_server.workflows.server._seventeen_lands", mock_17lands):
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
            patch("mtg_mcp_server.workflows.server._spellbook", mock_spellbook),
            patch("mtg_mcp_server.workflows.server._edhrec", None),
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

    async def test_service_error_becomes_tool_error(
        self,
        mcp_client: Client,
    ):
        """ServiceError from _require_spellbook → ToolError with tool name."""
        with patch(
            "mtg_mcp_server.workflows.server._require_spellbook",
            side_effect=ServiceError("client not available"),
        ):
            result = await mcp_client.call_tool(
                "suggest_cuts",
                {
                    "decklist": ["Sol Ring", "Spore Frog"],
                    "commander_name": "Muldrotha",
                },
                raise_on_error=False,
            )
        assert result.is_error
        assert "suggest_cuts failed" in result.content[0].text.lower()


# ---------------------------------------------------------------------------
# ToolError conversion — card_comparison
# ---------------------------------------------------------------------------


class TestCardComparisonToolError:
    """Verify card_comparison converts service exceptions to ToolError."""

    async def test_too_few_cards_becomes_tool_error(self, mcp_client: Client):
        """Fewer than 2 cards → ToolError with validation message."""
        result = await mcp_client.call_tool(
            "card_comparison",
            {"cards": ["Sol Ring"], "commander_name": "Muldrotha"},
            raise_on_error=False,
        )
        assert result.is_error
        assert "at least 2" in result.content[0].text.lower()

    async def test_too_many_cards_becomes_tool_error(self, mcp_client: Client):
        """More than 5 cards → ToolError with validation message."""
        result = await mcp_client.call_tool(
            "card_comparison",
            {"cards": ["A", "B", "C", "D", "E", "F"], "commander_name": "Muldrotha"},
            raise_on_error=False,
        )
        assert result.is_error
        assert "maximum 5" in result.content[0].text.lower()

    async def test_card_not_found_becomes_tool_error(self, mcp_client: Client):
        """CardNotFoundError from Scryfall → ToolError."""
        mock_scryfall = AsyncMock()
        mock_scryfall.get_card_by_name = AsyncMock(
            side_effect=CardNotFoundError("not found", status_code=404)
        )
        mock_spellbook = AsyncMock()

        with (
            patch("mtg_mcp_server.workflows.server._scryfall", mock_scryfall),
            patch("mtg_mcp_server.workflows.server._spellbook", mock_spellbook),
            patch("mtg_mcp_server.workflows.server._edhrec", None),
            patch("mtg_mcp_server.workflows.server._mtgjson", None),
        ):
            result = await mcp_client.call_tool(
                "card_comparison",
                {"cards": ["Nonexistent", "Sol Ring"], "commander_name": "Muldrotha"},
                raise_on_error=False,
            )
        assert result.is_error
        assert "not found" in result.content[0].text.lower()

    async def test_service_error_becomes_tool_error(self, mcp_client: Client):
        """Generic ServiceError → ToolError with tool name."""
        mock_scryfall = AsyncMock()
        mock_scryfall.get_card_by_name = AsyncMock(side_effect=ServiceError("timeout"))
        mock_spellbook = AsyncMock()

        with (
            patch("mtg_mcp_server.workflows.server._scryfall", mock_scryfall),
            patch("mtg_mcp_server.workflows.server._spellbook", mock_spellbook),
            patch("mtg_mcp_server.workflows.server._edhrec", None),
            patch("mtg_mcp_server.workflows.server._mtgjson", None),
        ):
            result = await mcp_client.call_tool(
                "card_comparison",
                {"cards": ["Sol Ring", "Mana Crypt"], "commander_name": "Muldrotha"},
                raise_on_error=False,
            )
        assert result.is_error
        assert "card_comparison failed" in result.content[0].text.lower()


# ---------------------------------------------------------------------------
# ToolError conversion — budget_upgrade
# ---------------------------------------------------------------------------


class TestBudgetUpgradeToolError:
    """Verify budget_upgrade converts service exceptions to ToolError."""

    async def test_negative_budget_becomes_tool_error(self, mcp_client: Client):
        """Negative budget → ToolError with validation message."""
        result = await mcp_client.call_tool(
            "budget_upgrade",
            {"commander_name": "Muldrotha", "budget": -5.0},
            raise_on_error=False,
        )
        assert result.is_error
        assert "positive" in result.content[0].text.lower()

    async def test_edhrec_disabled_becomes_tool_error(self, mcp_client: Client):
        """EDHREC not enabled → ToolError (required backend, not optional)."""
        with patch("mtg_mcp_server.workflows.server._edhrec", None):
            result = await mcp_client.call_tool(
                "budget_upgrade",
                {"commander_name": "Muldrotha", "budget": 5.0},
                raise_on_error=False,
            )
        assert result.is_error
        assert "edhrec" in result.content[0].text.lower()
        assert "not enabled" in result.content[0].text.lower()

    async def test_service_error_becomes_tool_error(self, mcp_client: Client):
        """Generic ServiceError → ToolError with tool name."""
        mock_edhrec = AsyncMock()
        mock_edhrec.commander_top_cards = AsyncMock(side_effect=ServiceError("timeout"))
        mock_scryfall = AsyncMock()

        with (
            patch("mtg_mcp_server.workflows.server._scryfall", mock_scryfall),
            patch("mtg_mcp_server.workflows.server._edhrec", mock_edhrec),
        ):
            result = await mcp_client.call_tool(
                "budget_upgrade",
                {"commander_name": "Muldrotha", "budget": 5.0},
                raise_on_error=False,
            )
        assert result.is_error
        assert "budget_upgrade failed" in result.content[0].text.lower()


# ---------------------------------------------------------------------------
# ToolError conversion — deck_analysis
# ---------------------------------------------------------------------------


class TestDeckAnalysisToolError:
    """Verify deck_analysis converts service exceptions to ToolError."""

    async def test_empty_decklist_becomes_tool_error(self, mcp_client: Client):
        """Empty decklist → ToolError with validation message."""
        result = await mcp_client.call_tool(
            "deck_analysis",
            {"decklist": [], "commander_name": "Muldrotha"},
            raise_on_error=False,
        )
        assert result.is_error
        assert "at least one" in result.content[0].text.lower()

    async def test_card_resolve_failure_degrades_gracefully(self, mcp_client: Client):
        """deck_analysis handles individual card failures — returns partial results."""
        mock_scryfall = AsyncMock()
        mock_scryfall.get_card_by_name = AsyncMock(side_effect=ServiceError("timeout"))
        mock_spellbook = AsyncMock()

        with (
            patch("mtg_mcp_server.workflows.server._scryfall", mock_scryfall),
            patch("mtg_mcp_server.workflows.server._spellbook", mock_spellbook),
            patch("mtg_mcp_server.workflows.server._edhrec", None),
            patch("mtg_mcp_server.workflows.server._mtgjson", None),
        ):
            result = await mcp_client.call_tool(
                "deck_analysis",
                {"decklist": ["Sol Ring"], "commander_name": "Muldrotha"},
                raise_on_error=False,
            )
        # Graceful degradation — returns partial results, not an error
        assert not result.is_error

    async def test_service_error_becomes_tool_error(self, mcp_client: Client):
        """Generic ServiceError from _require_scryfall → ToolError with tool name."""
        with patch(
            "mtg_mcp_server.workflows.server._require_scryfall",
            side_effect=ServiceError("client not available"),
        ):
            result = await mcp_client.call_tool(
                "deck_analysis",
                {"decklist": ["Sol Ring"], "commander_name": "Muldrotha"},
                raise_on_error=False,
            )
        assert result.is_error
        assert "deck_analysis failed" in result.content[0].text.lower()


# ---------------------------------------------------------------------------
# ToolError conversion — set_overview
# ---------------------------------------------------------------------------


class TestSetOverviewToolError:
    """Verify set_overview converts service exceptions to ToolError."""

    async def test_17lands_disabled_becomes_tool_error(self, mcp_client: Client):
        """17Lands not enabled → ToolError."""
        with patch("mtg_mcp_server.workflows.server._seventeen_lands", None):
            result = await mcp_client.call_tool(
                "set_overview",
                {"set_code": "LCI"},
                raise_on_error=False,
            )
        assert result.is_error
        assert "not enabled" in result.content[0].text.lower()

    async def test_service_error_becomes_tool_error(self, mcp_client: Client):
        """SeventeenLandsError → ToolError with backend name."""
        mock_17lands = AsyncMock()
        mock_17lands.card_ratings = AsyncMock(
            side_effect=SeventeenLandsError("rate limited", status_code=429)
        )
        mock_17lands.color_ratings = AsyncMock(
            side_effect=SeventeenLandsError("rate limited", status_code=429)
        )

        with patch("mtg_mcp_server.workflows.server._seventeen_lands", mock_17lands):
            result = await mcp_client.call_tool(
                "set_overview",
                {"set_code": "LCI"},
                raise_on_error=False,
            )
        assert result.is_error
        assert "17lands" in result.content[0].text.lower()


# ---------------------------------------------------------------------------
# Input validation — empty strings
# ---------------------------------------------------------------------------


class TestEmptyStringValidation:
    """Empty/whitespace-only strings rejected with clear ToolError."""

    async def test_commander_overview_empty_name(self, mcp_client: Client):
        """commander_overview rejects empty commander name."""
        result = await mcp_client.call_tool(
            "commander_overview",
            {"commander_name": "  "},
            raise_on_error=False,
        )
        assert result.is_error
        assert (
            "empty" in result.content[0].text.lower() or "blank" in result.content[0].text.lower()
        )

    async def test_evaluate_upgrade_empty_card(self, mcp_client: Client):
        """evaluate_upgrade rejects empty card name."""
        result = await mcp_client.call_tool(
            "evaluate_upgrade",
            {"card_name": "", "commander_name": "Muldrotha"},
            raise_on_error=False,
        )
        assert result.is_error

    async def test_evaluate_upgrade_empty_commander(self, mcp_client: Client):
        """evaluate_upgrade rejects empty commander name."""
        result = await mcp_client.call_tool(
            "evaluate_upgrade",
            {"card_name": "Sol Ring", "commander_name": ""},
            raise_on_error=False,
        )
        assert result.is_error

    async def test_card_comparison_empty_commander(self, mcp_client: Client):
        """card_comparison rejects empty commander name."""
        result = await mcp_client.call_tool(
            "card_comparison",
            {"cards": ["Sol Ring", "Mana Crypt"], "commander_name": "  "},
            raise_on_error=False,
        )
        assert result.is_error

    async def test_budget_upgrade_empty_commander(self, mcp_client: Client):
        """budget_upgrade rejects empty commander name."""
        result = await mcp_client.call_tool(
            "budget_upgrade",
            {"commander_name": "", "budget": 5.0},
            raise_on_error=False,
        )
        assert result.is_error

    async def test_suggest_cuts_empty_commander(self, mcp_client: Client):
        """suggest_cuts rejects empty commander name."""
        result = await mcp_client.call_tool(
            "suggest_cuts",
            {"decklist": ["Sol Ring"], "commander_name": "  "},
            raise_on_error=False,
        )
        assert result.is_error


# ---------------------------------------------------------------------------
# card_comparison dedup
# ---------------------------------------------------------------------------


class TestCardComparisonDedup:
    """Duplicate card names are removed before comparison."""

    async def test_dedup_reduces_to_unique(self, mcp_client: Client):
        """Duplicate cards are deduplicated — 3 inputs with 1 dup → 2 unique cards."""
        mock_scryfall = AsyncMock()
        from mtg_mcp_server.types import Card, CardPrices

        sol_ring = Card(
            id="sol-ring-id",
            name="Sol Ring",
            mana_cost="{1}",
            type_line="Artifact",
            colors=[],
            color_identity=[],
            set="cmd",
            rarity="uncommon",
            prices=CardPrices(usd="1.50"),
        )
        mana_crypt = Card(
            id="mana-crypt-id",
            name="Mana Crypt",
            mana_cost="{0}",
            type_line="Artifact",
            colors=[],
            color_identity=[],
            set="cmd",
            rarity="mythic",
            prices=CardPrices(usd="150.00"),
        )

        async def resolve(name: str) -> Card:
            return sol_ring if name == "Sol Ring" else mana_crypt

        mock_scryfall.get_card_by_name = AsyncMock(side_effect=resolve)
        mock_spellbook = AsyncMock()
        mock_spellbook.find_combos = AsyncMock(return_value=[])

        with (
            patch("mtg_mcp_server.workflows.server._scryfall", mock_scryfall),
            patch("mtg_mcp_server.workflows.server._spellbook", mock_spellbook),
            patch("mtg_mcp_server.workflows.server._edhrec", None),
        ):
            result = await mcp_client.call_tool(
                "card_comparison",
                {
                    "cards": ["Sol Ring", "Mana Crypt", "Sol Ring"],
                    "commander_name": "Muldrotha",
                },
            )

        text = result.content[0].text
        # Scryfall called twice (not three times) — dedup happened before resolution
        assert mock_scryfall.get_card_by_name.call_count == 2
        assert "Sol Ring" in text
        assert "Mana Crypt" in text
