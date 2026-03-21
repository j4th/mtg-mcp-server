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
SEVENTEEN_LANDS_FIXTURES = Path(__file__).parent / "fixtures" / "seventeen_lands"
SCRYFALL_URL = "https://api.scryfall.com"
SEVENTEEN_LANDS_URL = "https://www.17lands.com"


def _load_scryfall_fixture(name: str) -> dict:
    return json.loads((SCRYFALL_FIXTURES / name).read_text())


def _load_seventeen_lands_fixture(name: str) -> list[dict]:
    return json.loads((SEVENTEEN_LANDS_FIXTURES / name).read_text())


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
        respx.get(f"{SCRYFALL_URL}/cards/named", params={"exact": "Muldrotha, the Gravetide"}).mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result = await mcp_client.call_tool(
            "scryfall_card_details", {"name": "Muldrotha, the Gravetide"}
        )
        text = result.content[0].text
        assert "Muldrotha, the Gravetide" in text
        assert "{3}{B}{G}{U}" in text

    async def test_ping_still_available(self, mcp_client: Client):
        result = await mcp_client.call_tool("ping", {})
        assert result.data == "pong"


class TestSeventeenLandsMounted:
    """Verify 17Lands tools appear with draft_ namespace on the orchestrator."""

    async def test_namespaced_tools_appear(self, mcp_client: Client):
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        assert "draft_card_ratings" in tool_names
        assert "draft_archetype_stats" in tool_names

    @respx.mock
    async def test_end_to_end_card_ratings(self, mcp_client: Client):
        fixture = _load_seventeen_lands_fixture("card_ratings_lci.json")
        respx.get(
            f"{SEVENTEEN_LANDS_URL}/card_ratings/data",
            params={"expansion": "LCI", "event_type": "PremierDraft"},
        ).mock(return_value=httpx.Response(200, json=fixture))

        result = await mcp_client.call_tool("draft_card_ratings", {"set_code": "LCI"})
        text = result.content[0].text
        assert "Abuelo's Awakening" in text
        assert "GIH WR:" in text
