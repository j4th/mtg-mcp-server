"""Tests for the Scryfall MCP provider."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from fastmcp import Client

from mtg_mcp.providers.scryfall import scryfall_mcp

FIXTURES = Path(__file__).parent.parent / "fixtures" / "scryfall"
BASE_URL = "https://api.scryfall.com"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
async def client():
    async with Client(transport=scryfall_mcp) as c:
        yield c


class TestSearchCards:
    @respx.mock
    async def test_returns_formatted_results(self, client: Client):
        fixture = _load_fixture("search_sultai_commander.json")
        respx.get(
            f"{BASE_URL}/cards/search",
            params={"q": "f:commander id:sultai t:creature", "page": "1"},
        ).mock(return_value=httpx.Response(200, json=fixture))

        result = await client.call_tool(
            "search_cards", {"query": "f:commander id:sultai t:creature"}
        )
        text = result.content[0].text
        assert "9273" in text
        assert fixture["data"][0]["name"] in text


class TestCardDetails:
    @respx.mock
    async def test_returns_card_data(self, client: Client):
        fixture = _load_fixture("card_muldrotha.json")
        respx.get(f"{BASE_URL}/cards/named", params={"exact": "Muldrotha, the Gravetide"}).mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result = await client.call_tool("card_details", {"name": "Muldrotha, the Gravetide"})
        text = result.content[0].text
        assert "Muldrotha, the Gravetide" in text
        assert "{3}{B}{G}{U}" in text
        assert "6/6" in text

    @respx.mock
    async def test_not_found_returns_error(self, client: Client):
        fixture = _load_fixture("card_not_found.json")
        respx.get(f"{BASE_URL}/cards/named", params={"exact": "Xyzzy"}).mock(
            return_value=httpx.Response(404, json=fixture)
        )

        result = await client.call_tool("card_details", {"name": "Xyzzy"}, raise_on_error=False)
        assert result.is_error


class TestCardPrice:
    @respx.mock
    async def test_returns_prices(self, client: Client):
        fixture = _load_fixture("card_sol_ring.json")
        respx.get(f"{BASE_URL}/cards/named", params={"exact": "Sol Ring"}).mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result = await client.call_tool("card_price", {"name": "Sol Ring"})
        text = result.content[0].text
        assert "Sol Ring" in text
        assert "$" in text


class TestCardRulings:
    @respx.mock
    async def test_returns_rulings(self, client: Client):
        card_fixture = _load_fixture("card_muldrotha.json")
        rulings_fixture = _load_fixture("rulings_muldrotha.json")
        card_id = card_fixture["id"]

        respx.get(f"{BASE_URL}/cards/named", params={"exact": "Muldrotha, the Gravetide"}).mock(
            return_value=httpx.Response(200, json=card_fixture)
        )
        respx.get(f"{BASE_URL}/cards/{card_id}/rulings").mock(
            return_value=httpx.Response(200, json=rulings_fixture)
        )

        result = await client.call_tool("card_rulings", {"name": "Muldrotha, the Gravetide"})
        text = result.content[0].text
        assert "Muldrotha" in text
        assert "8 ruling" in text.lower()


class TestToolRegistration:
    async def test_all_tools_registered(self, client: Client):
        tools = await client.list_tools()
        tool_names = {t.name for t in tools}
        assert tool_names == {"search_cards", "card_details", "card_price", "card_rulings"}
