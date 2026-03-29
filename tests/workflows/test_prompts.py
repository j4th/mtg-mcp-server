"""Tests for MCP prompts registered on the workflow server.

Prompts are user-invoked templates that guide AI assistants through
multi-step workflows. Each prompt returns a formatted instruction
string referencing specific tools by name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import Client


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestPromptRegistration:
    """Verify all prompts are registered on the server."""

    async def test_all_prompts_listed(self, mcp_client: Client):
        """All four prompt names present in the prompt list."""
        prompts = await mcp_client.list_prompts()
        prompt_names = {p.name for p in prompts}
        assert "evaluate_commander_swap" in prompt_names
        assert "deck_health_check" in prompt_names
        assert "draft_strategy" in prompt_names
        assert "find_upgrades" in prompt_names

    async def test_prompt_count(self, mcp_client: Client):
        """Exactly 9 prompts registered on the workflow server."""
        prompts = await mcp_client.list_prompts()
        # 4 existing + 4 cross-format + 1 rules prompt
        assert len(prompts) == 9


# ---------------------------------------------------------------------------
# evaluate_commander_swap
# ---------------------------------------------------------------------------


class TestEvaluateCommanderSwap:
    """Test the evaluate_commander_swap prompt."""

    async def test_returns_instructions(self, mcp_client: Client):
        """Returns instructions referencing both cards, commander, and tool names."""
        result = await mcp_client.get_prompt(
            "evaluate_commander_swap",
            arguments={
                "commander": "Muldrotha",
                "adding": "Spore Frog",
                "cutting": "Sol Ring",
            },
        )
        text = result.messages[0].content.text
        assert "Muldrotha" in text
        assert "Spore Frog" in text
        assert "Sol Ring" in text
        assert "scryfall_card_details" in text
        assert "SWAP" in text

    async def test_contains_evaluation_criteria(self, mcp_client: Client):
        """Prompt includes synergy threshold criteria."""
        result = await mcp_client.get_prompt(
            "evaluate_commander_swap",
            arguments={"commander": "X", "adding": "Y", "cutting": "Z"},
        )
        text = result.messages[0].content.text
        assert "Synergy" in text
        assert "30%" in text

    async def test_references_card_comparison_tool(self, mcp_client: Client):
        """Prompt references the card_comparison tool by name."""
        result = await mcp_client.get_prompt(
            "evaluate_commander_swap",
            arguments={"commander": "X", "adding": "Y", "cutting": "Z"},
        )
        text = result.messages[0].content.text
        assert "card_comparison" in text

    async def test_references_spellbook_find_combos(self, mcp_client: Client):
        """Prompt references the spellbook_find_combos tool by name."""
        result = await mcp_client.get_prompt(
            "evaluate_commander_swap",
            arguments={"commander": "X", "adding": "Y", "cutting": "Z"},
        )
        text = result.messages[0].content.text
        assert "spellbook_find_combos" in text


# ---------------------------------------------------------------------------
# deck_health_check
# ---------------------------------------------------------------------------


class TestDeckHealthCheck:
    """Test the deck_health_check prompt."""

    async def test_returns_instructions(self, mcp_client: Client):
        """Returns instructions referencing commander, deck_analysis, and suggest_cuts."""
        result = await mcp_client.get_prompt(
            "deck_health_check",
            arguments={"commander": "Muldrotha, the Gravetide"},
        )
        text = result.messages[0].content.text
        assert "Muldrotha" in text
        assert "deck_analysis" in text
        assert "suggest_cuts" in text

    async def test_contains_analysis_guidance(self, mcp_client: Client):
        """Prompt includes guidance about mana curve and bracket analysis."""
        result = await mcp_client.get_prompt(
            "deck_health_check",
            arguments={"commander": "Atraxa"},
        )
        text = result.messages[0].content.text
        assert "mana curve" in text.lower()
        assert "bracket" in text.lower()


# ---------------------------------------------------------------------------
# draft_strategy
# ---------------------------------------------------------------------------


class TestDraftStrategy:
    """Test the draft_strategy prompt."""

    async def test_returns_instructions(self, mcp_client: Client):
        """Returns instructions referencing set code, set_overview tool, and GIH WR."""
        result = await mcp_client.get_prompt(
            "draft_strategy",
            arguments={"set_code": "LCI"},
        )
        text = result.messages[0].content.text
        assert "LCI" in text
        assert "set_overview" in text
        assert "GIH WR" in text

    async def test_contains_draft_heuristics(self, mcp_client: Client):
        """Prompt includes GIH WR threshold, ALSA, and IWD heuristics."""
        result = await mcp_client.get_prompt(
            "draft_strategy",
            arguments={"set_code": "MKM"},
        )
        text = result.messages[0].content.text
        assert "58%" in text
        assert "ALSA" in text
        assert "IWD" in text


# ---------------------------------------------------------------------------
# find_upgrades
# ---------------------------------------------------------------------------


class TestFindUpgrades:
    """Test the find_upgrades prompt."""

    async def test_returns_instructions(self, mcp_client: Client):
        """Returns instructions referencing commander, budget, and upgrade tools."""
        result = await mcp_client.get_prompt(
            "find_upgrades",
            arguments={"commander": "Muldrotha", "budget": 5.0},
        )
        text = result.messages[0].content.text
        assert "Muldrotha" in text
        assert "$5.00" in text
        assert "budget_upgrade" in text
        assert "evaluate_upgrade" in text

    async def test_contains_evaluation_criteria(self, mcp_client: Client):
        """Prompt includes synergy and inclusion evaluation thresholds."""
        result = await mcp_client.get_prompt(
            "find_upgrades",
            arguments={"commander": "Korvold", "budget": 10.0},
        )
        text = result.messages[0].content.text
        assert "Synergy" in text
        assert "50%" in text

    async def test_budget_formatting(self, mcp_client: Client):
        """Budget value is formatted with 2 decimal places."""
        result = await mcp_client.get_prompt(
            "find_upgrades",
            arguments={"commander": "X", "budget": 3.5},
        )
        text = result.messages[0].content.text
        assert "$3.50" in text
