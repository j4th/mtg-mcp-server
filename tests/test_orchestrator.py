"""Integration tests for the MTG orchestrator with mounted backends."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import respx

if TYPE_CHECKING:
    from fastmcp import Client

SCRYFALL_FIXTURES = Path(__file__).parent / "fixtures" / "scryfall"
SPELLBOOK_FIXTURES = Path(__file__).parent / "fixtures" / "spellbook"
SCRYFALL_BASE = "https://api.scryfall.com"
SPELLBOOK_BASE = "https://backend.commanderspellbook.com"


def _load_scryfall_fixture(name: str) -> dict:
    return json.loads((SCRYFALL_FIXTURES / name).read_text())


def _load_spellbook_fixture(name: str) -> dict:
    return json.loads((SPELLBOOK_FIXTURES / name).read_text())


class TestScryfallMounted:
    """Verify Scryfall tools appear with scryfall_ namespace on the orchestrator."""

    async def test_namespaced_tools_appear(self, mcp_client: Client):
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        assert "scryfall_search_cards" in tool_names
        assert "scryfall_card_details" in tool_names
        assert "scryfall_card_price" in tool_names
        assert "scryfall_card_rulings" in tool_names

    @respx.mock
    async def test_end_to_end_card_details(self, mcp_client: Client):
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
        result = await mcp_client.call_tool("ping", {})
        assert result.data == "pong"


class TestSpellbookMounted:
    """Verify Spellbook tools appear with spellbook_ namespace on the orchestrator."""

    async def test_namespaced_tools_appear(self, mcp_client: Client):
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        assert "spellbook_find_combos" in tool_names
        assert "spellbook_combo_details" in tool_names
        assert "spellbook_find_decklist_combos" in tool_names
        assert "spellbook_estimate_bracket" in tool_names

    @respx.mock
    async def test_end_to_end_find_combos(self, mcp_client: Client):
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
