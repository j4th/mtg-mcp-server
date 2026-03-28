"""Tests for Context progress reporting and tool input validation.

Tests the _progress helper function, verifies workflow tools are registered,
and checks input validation on the workflow tools (card_comparison,
budget_upgrade, deck_analysis, set_overview).
"""

from __future__ import annotations

import sys
import types
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from mtg_mcp_server.workflows import WorkflowResult

if TYPE_CHECKING:
    from fastmcp import Client


@pytest.fixture
def _mock_commander_stubs():
    """Patch commander module to stub card_comparison and budget_upgrade."""
    created = "mtg_mcp_server.workflows.commander" not in sys.modules
    mod = sys.modules.get("mtg_mcp_server.workflows.commander")
    if mod is None:
        mod = types.ModuleType("mtg_mcp_server.workflows.commander")
        sys.modules["mtg_mcp_server.workflows.commander"] = mod

    stub = AsyncMock(return_value=WorkflowResult(markdown="stub", data={}))
    originals: dict[str, object] = {}

    for name in ("card_comparison", "budget_upgrade"):
        originals[name] = getattr(mod, name, None)
        setattr(mod, name, stub)

    yield stub

    if created:
        sys.modules.pop("mtg_mcp_server.workflows.commander", None)
    else:
        for name, orig in originals.items():
            if orig is None:
                if hasattr(mod, name):
                    delattr(mod, name)
            else:
                setattr(mod, name, orig)


@pytest.fixture
def _mock_analysis_stubs():
    """Patch analysis module to expose deck_analysis stub."""
    created = "mtg_mcp_server.workflows.analysis" not in sys.modules
    mod = sys.modules.get("mtg_mcp_server.workflows.analysis")
    if mod is None:
        mod = types.ModuleType("mtg_mcp_server.workflows.analysis")
        sys.modules["mtg_mcp_server.workflows.analysis"] = mod

    stub = AsyncMock(return_value=WorkflowResult(markdown="stub", data={}))
    original = getattr(mod, "deck_analysis", None)
    mod.deck_analysis = stub

    yield stub

    if created:
        sys.modules.pop("mtg_mcp_server.workflows.analysis", None)
    else:
        if original is None:
            if hasattr(mod, "deck_analysis"):
                delattr(mod, "deck_analysis")
        else:
            mod.deck_analysis = original


@pytest.fixture
def _mock_draft_stubs():
    """Patch draft module to expose set_overview stub."""
    created = "mtg_mcp_server.workflows.draft" not in sys.modules
    mod = sys.modules.get("mtg_mcp_server.workflows.draft")
    if mod is None:
        mod = types.ModuleType("mtg_mcp_server.workflows.draft")
        sys.modules["mtg_mcp_server.workflows.draft"] = mod

    stub = AsyncMock(return_value=WorkflowResult(markdown="stub", data={}))
    original = getattr(mod, "set_overview", None)
    mod.set_overview = stub

    yield stub

    if created:
        sys.modules.pop("mtg_mcp_server.workflows.draft", None)
    else:
        if original is None:
            if hasattr(mod, "set_overview"):
                delattr(mod, "set_overview")
        else:
            mod.set_overview = original


# ---------------------------------------------------------------------------
# _progress helper
# ---------------------------------------------------------------------------


class TestProgressHelper:
    """Test the _progress helper function."""

    async def test_progress_calls_report(self):
        """_progress calls ctx.report_progress with step and total."""
        from mtg_mcp_server.workflows.server import _progress

        mock_ctx = AsyncMock()
        await _progress(mock_ctx, 1, 3)
        mock_ctx.report_progress.assert_called_once_with(progress=1, total=3)

    async def test_progress_passes_step_and_total(self):
        """Step and total values forwarded correctly to report_progress."""
        from mtg_mcp_server.workflows.server import _progress

        mock_ctx = AsyncMock()
        await _progress(mock_ctx, 5, 10)
        mock_ctx.report_progress.assert_called_once_with(progress=5, total=10)

    async def test_progress_zero_step(self):
        """Zero as step value accepted and forwarded correctly."""
        from mtg_mcp_server.workflows.server import _progress

        mock_ctx = AsyncMock()
        await _progress(mock_ctx, 0, 5)
        mock_ctx.report_progress.assert_called_once_with(progress=0, total=5)


# ---------------------------------------------------------------------------
# Input validation -- card_comparison
# ---------------------------------------------------------------------------


class TestCardComparisonValidation:
    """Test that card_comparison validates card count."""

    @pytest.fixture(autouse=True)
    def _stubs(self, _mock_commander_stubs):
        """Activate commander module stubs for this test class."""

    async def test_too_few_cards(self, mcp_client: Client):
        """Rejects card_comparison with fewer than 2 cards."""
        result = await mcp_client.call_tool(
            "card_comparison",
            {"cards": ["Sol Ring"], "commander_name": "Muldrotha"},
            raise_on_error=False,
        )
        assert result.is_error
        assert "at least 2" in result.content[0].text.lower()

    async def test_too_many_cards(self, mcp_client: Client):
        """Rejects card_comparison with more than 5 cards."""
        result = await mcp_client.call_tool(
            "card_comparison",
            {
                "cards": ["A", "B", "C", "D", "E", "F"],
                "commander_name": "X",
            },
            raise_on_error=False,
        )
        assert result.is_error
        assert "maximum 5" in result.content[0].text.lower()

    async def test_empty_cards_list(self, mcp_client: Client):
        """Rejects card_comparison with empty cards list."""
        result = await mcp_client.call_tool(
            "card_comparison",
            {"cards": [], "commander_name": "Muldrotha"},
            raise_on_error=False,
        )
        assert result.is_error
        assert "at least 2" in result.content[0].text.lower()


# ---------------------------------------------------------------------------
# Input validation -- budget_upgrade
# ---------------------------------------------------------------------------


class TestBudgetUpgradeValidation:
    """Test that budget_upgrade validates budget amount."""

    @pytest.fixture(autouse=True)
    def _stubs(self, _mock_commander_stubs):
        """Activate commander module stubs for this test class."""

    async def test_negative_budget(self, mcp_client: Client):
        """Rejects budget_upgrade with negative budget value."""
        result = await mcp_client.call_tool(
            "budget_upgrade",
            {"commander_name": "Muldrotha", "budget": -1.0},
            raise_on_error=False,
        )
        assert result.is_error
        assert "positive" in result.content[0].text.lower()

    async def test_zero_budget(self, mcp_client: Client):
        """Rejects budget_upgrade with zero budget value."""
        result = await mcp_client.call_tool(
            "budget_upgrade",
            {"commander_name": "Muldrotha", "budget": 0.0},
            raise_on_error=False,
        )
        assert result.is_error
        assert "positive" in result.content[0].text.lower()


# ---------------------------------------------------------------------------
# Input validation -- deck_analysis
# ---------------------------------------------------------------------------


class TestDeckAnalysisValidation:
    """Test that deck_analysis validates decklist."""

    @pytest.fixture(autouse=True)
    def _stubs(self, _mock_analysis_stubs):
        """Activate analysis module stubs for this test class."""

    async def test_empty_decklist(self, mcp_client: Client):
        """Rejects deck_analysis with empty decklist."""
        result = await mcp_client.call_tool(
            "deck_analysis",
            {"decklist": [], "commander_name": "Muldrotha"},
            raise_on_error=False,
        )
        assert result.is_error
        assert "at least one" in result.content[0].text.lower()


# ---------------------------------------------------------------------------
# Input validation -- set_overview
# ---------------------------------------------------------------------------


class TestSetOverviewValidation:
    """Test that set_overview validates 17Lands availability."""

    @pytest.fixture(autouse=True)
    def _stubs(self, _mock_draft_stubs):
        """Activate draft module stubs for this test class."""

    async def test_17lands_disabled(self, mcp_client: Client):
        """Rejects set_overview when 17Lands client is not enabled."""
        with patch("mtg_mcp_server.workflows.server._seventeen_lands", None):
            result = await mcp_client.call_tool(
                "set_overview",
                {"set_code": "LCI"},
                raise_on_error=False,
            )
        assert result.is_error
        assert "not enabled" in result.content[0].text.lower()


# ---------------------------------------------------------------------------
# New Phase 5 tools registered
# ---------------------------------------------------------------------------


class TestNewToolsRegistered:
    """Verify all Phase 5 tools are registered."""

    async def test_new_tools_present(self, mcp_client: Client):
        """All four Phase 5 tools present in the tool list."""
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        assert "card_comparison" in tool_names
        assert "budget_upgrade" in tool_names
        assert "deck_analysis" in tool_names
        assert "set_overview" in tool_names

    async def test_total_workflow_tool_count(self, mcp_client: Client):
        """All 8 workflow tools are registered (4 original + 4 new)."""
        tools = await mcp_client.list_tools()
        workflow_tools = {
            "commander_overview",
            "evaluate_upgrade",
            "draft_pack_pick",
            "suggest_cuts",
            "card_comparison",
            "budget_upgrade",
            "deck_analysis",
            "set_overview",
        }
        tool_names = {t.name for t in tools}
        for tool in workflow_tools:
            assert tool in tool_names, f"Missing workflow tool: {tool}"
