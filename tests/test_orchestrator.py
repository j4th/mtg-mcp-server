"""Integration tests for the MTG orchestrator with mounted backends."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import httpx
import respx

if TYPE_CHECKING:
    from fastmcp import Client

SCRYFALL_FIXTURES = Path(__file__).parent / "fixtures" / "scryfall"
SPELLBOOK_FIXTURES = Path(__file__).parent / "fixtures" / "spellbook"
SEVENTEEN_LANDS_FIXTURES = Path(__file__).parent / "fixtures" / "seventeen_lands"
EDHREC_FIXTURES = Path(__file__).parent / "fixtures" / "edhrec"
MTGJSON_FIXTURES = Path(__file__).parent / "fixtures" / "mtgjson"
SCRYFALL_BASE = "https://api.scryfall.com"
SPELLBOOK_BASE = "https://backend.commanderspellbook.com"
SEVENTEEN_LANDS_BASE = "https://www.17lands.com"
EDHREC_BASE = "https://json.edhrec.com"


def _load_scryfall_fixture(name: str) -> dict:
    """Load a Scryfall JSON fixture by filename."""
    return json.loads((SCRYFALL_FIXTURES / name).read_text())


def _load_spellbook_fixture(name: str) -> dict:
    """Load a Spellbook JSON fixture by filename."""
    return json.loads((SPELLBOOK_FIXTURES / name).read_text())


def _load_seventeen_lands_fixture(name: str) -> list[dict]:
    """Load a 17Lands JSON fixture by filename."""
    return json.loads((SEVENTEEN_LANDS_FIXTURES / name).read_text())


def _load_edhrec_fixture(name: str) -> dict:
    """Load an EDHREC JSON fixture by filename."""
    return json.loads((EDHREC_FIXTURES / name).read_text())


class TestScryfallMounted:
    """Verify Scryfall tools appear with scryfall_ namespace on the orchestrator."""

    async def test_namespaced_tools_appear(self, mcp_client: Client):
        """All four Scryfall tools are listed with the scryfall_ namespace prefix."""
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        assert "scryfall_search_cards" in tool_names
        assert "scryfall_card_details" in tool_names
        assert "scryfall_card_price" in tool_names
        assert "scryfall_card_rulings" in tool_names

    @respx.mock
    async def test_end_to_end_card_details(self, mcp_client: Client):
        """Calling scryfall_card_details through the orchestrator returns card data."""
        fixture = _load_scryfall_fixture("card_muldrotha.json")
        respx.get(
            f"{SCRYFALL_BASE}/cards/named",
            params={"exact": "Muldrotha, the Gravetide"},
        ).mock(return_value=httpx.Response(200, json=fixture))

        result = await mcp_client.call_tool(
            "scryfall_card_details", {"name": "Muldrotha, the Gravetide"}
        )
        text = result.content[0].text
        assert "Muldrotha, the Gravetide" in text
        assert "{3}{B}{G}{U}" in text

    async def test_ping_still_available(self, mcp_client: Client):
        """Ping health-check tool remains available alongside mounted backends."""
        result = await mcp_client.call_tool("ping", {})
        assert result.data == "pong"


class TestSpellbookMounted:
    """Verify Spellbook tools appear with spellbook_ namespace on the orchestrator."""

    async def test_namespaced_tools_appear(self, mcp_client: Client):
        """All four Spellbook tools are listed with the spellbook_ namespace prefix."""
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        assert "spellbook_find_combos" in tool_names
        assert "spellbook_combo_details" in tool_names
        assert "spellbook_find_decklist_combos" in tool_names
        assert "spellbook_estimate_bracket" in tool_names

    @respx.mock
    async def test_end_to_end_find_combos(self, mcp_client: Client):
        """Calling spellbook_find_combos through the orchestrator returns combo data."""
        fixture = _load_spellbook_fixture("combos_muldrotha.json")
        respx.get(
            f"{SPELLBOOK_BASE}/variants/",
            params={"q": 'card:"Muldrotha, the Gravetide"', "limit": "10"},
        ).mock(return_value=httpx.Response(200, json=fixture))

        result = await mcp_client.call_tool(
            "spellbook_find_combos", {"card_name": "Muldrotha, the Gravetide"}
        )
        text = result.content[0].text
        assert "combo" in text.lower()
        assert "Muldrotha" in text


class TestSeventeenLandsMounted:
    """Verify 17Lands tools appear with draft_ namespace on the orchestrator."""

    async def test_namespaced_tools_appear(self, mcp_client: Client):
        """Both 17Lands tools are listed with the draft_ namespace prefix."""
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        assert "draft_card_ratings" in tool_names
        assert "draft_archetype_stats" in tool_names

    @respx.mock
    async def test_end_to_end_card_ratings(self, mcp_client: Client):
        """Calling draft_card_ratings through the orchestrator returns rating data."""
        fixture = _load_seventeen_lands_fixture("card_ratings_lci.json")
        respx.get(
            f"{SEVENTEEN_LANDS_BASE}/card_ratings/data",
            params={"expansion": "LCI", "event_type": "PremierDraft"},
        ).mock(return_value=httpx.Response(200, json=fixture))

        result = await mcp_client.call_tool("draft_card_ratings", {"set_code": "LCI"})
        text = result.content[0].text
        assert len(text) > 0


class TestWorkflowsMounted:
    """Verify workflow tools appear without namespace on the orchestrator."""

    async def test_workflow_tools_appear(self, mcp_client: Client):
        """Workflow tools appear without any namespace prefix."""
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        assert "commander_overview" in tool_names
        assert "evaluate_upgrade" in tool_names
        assert "draft_pack_pick" in tool_names
        assert "suggest_cuts" in tool_names


class TestEdhrecMounted:
    """Verify EDHREC tools appear with edhrec_ namespace on the orchestrator."""

    async def test_namespaced_tools_appear(self, mcp_client: Client):
        """Both EDHREC tools are listed with the edhrec_ namespace prefix."""
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        assert "edhrec_commander_staples" in tool_names
        assert "edhrec_card_synergy" in tool_names

    @respx.mock
    async def test_end_to_end_commander_staples(self, mcp_client: Client):
        """Calling edhrec_commander_staples through the orchestrator returns staple data."""
        fixture = _load_edhrec_fixture("commander_muldrotha.json")
        respx.get(f"{EDHREC_BASE}/pages/commanders/muldrotha-the-gravetide.json").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result = await mcp_client.call_tool(
            "edhrec_commander_staples",
            {"commander_name": "Muldrotha, the Gravetide"},
        )
        text = result.content[0].text
        assert "Muldrotha, the Gravetide" in text


class TestMtgjsonMounted:
    """Verify MTGJSON tools appear with mtgjson_ namespace on the orchestrator."""

    async def test_namespaced_tools_appear(self, mcp_client: Client):
        """Both MTGJSON tools are listed with the mtgjson_ namespace prefix."""
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        assert "mtgjson_card_lookup" in tool_names
        assert "mtgjson_card_search" in tool_names

    async def test_end_to_end_card_lookup(self, mcp_client: Client):
        """Calling mtgjson_card_lookup through the orchestrator returns card data."""
        fixture_bytes = (MTGJSON_FIXTURES / "atomic_cards_sample.json.gz").read_bytes()
        mock_response = httpx.Response(200, content=fixture_bytes)

        with patch("mtg_mcp_server.services.mtgjson.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_response)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_http

            result = await mcp_client.call_tool("mtgjson_card_lookup", {"name": "Sol Ring"})
            text = result.content[0].text
            assert "Sol Ring" in text
            assert "Artifact" in text

    async def test_end_to_end_card_search(self, mcp_client: Client):
        """Calling mtgjson_card_search through the orchestrator returns search results."""
        fixture_bytes = (MTGJSON_FIXTURES / "atomic_cards_sample.json.gz").read_bytes()
        mock_response = httpx.Response(200, content=fixture_bytes)

        with patch("mtg_mcp_server.services.mtgjson.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_response)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_http

            result = await mcp_client.call_tool("mtgjson_card_search", {"query": "bolt"})
            text = result.content[0].text
            assert "Lightning Bolt" in text
