"""Tests for the Scryfall MCP provider."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from fastmcp import Client

from mtg_mcp_server.providers.scryfall import scryfall_mcp

FIXTURES = Path(__file__).parent.parent / "fixtures" / "scryfall"
BASE_URL = "https://api.scryfall.com"


def _load_fixture(name: str) -> dict:
    """Load a Scryfall JSON fixture file by name."""
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
async def client():
    """Provide an in-memory MCP client connected to the Scryfall provider."""
    async with Client(transport=scryfall_mcp) as c:
        yield c


class TestSearchCards:
    """Scryfall search_cards tool behavior."""

    @respx.mock
    async def test_returns_formatted_results(self, client: Client):
        """search_cards returns formatted card list with count and attribution."""
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
        assert "Data provided by [Scryfall]" in text

        sc = result.structured_content
        assert isinstance(sc, dict)
        assert sc["query"] == "f:commander id:sultai t:creature"
        assert sc["total_cards"] == 9273
        assert isinstance(sc["cards"], list)


class TestSearchCardsConcise:
    """Scryfall search_cards tool concise mode."""

    @respx.mock
    async def test_concise_is_shorter(self, client: Client):
        """Concise output omits type and price, producing shorter text."""
        fixture = _load_fixture("search_sultai_commander.json")
        respx.get(
            f"{BASE_URL}/cards/search",
            params={"q": "f:commander id:sultai t:creature", "page": "1"},
        ).mock(return_value=httpx.Response(200, json=fixture))

        result_detailed = await client.call_tool(
            "search_cards",
            {"query": "f:commander id:sultai t:creature", "response_format": "detailed"},
        )
        # Re-mock for second call
        respx.get(
            f"{BASE_URL}/cards/search",
            params={"q": "f:commander id:sultai t:creature", "page": "1"},
        ).mock(return_value=httpx.Response(200, json=fixture))

        result_concise = await client.call_tool(
            "search_cards",
            {"query": "f:commander id:sultai t:creature", "response_format": "concise"},
        )
        detailed_text = result_detailed.content[0].text
        concise_text = result_concise.content[0].text
        assert len(concise_text) < len(detailed_text)
        # Card name still present
        assert fixture["data"][0]["name"] in concise_text
        assert "Data provided by [Scryfall]" in concise_text

        sc = result_concise.structured_content
        assert isinstance(sc, dict)
        assert sc["query"] == "f:commander id:sultai t:creature"
        assert isinstance(sc["cards"], list)


class TestCardDetails:
    """Scryfall card_details tool behavior."""

    @respx.mock
    async def test_returns_card_data(self, client: Client):
        """card_details returns full card data including name, mana cost, and power/toughness."""
        fixture = _load_fixture("card_muldrotha.json")
        respx.get(f"{BASE_URL}/cards/named", params={"exact": "Muldrotha, the Gravetide"}).mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result = await client.call_tool("card_details", {"name": "Muldrotha, the Gravetide"})
        text = result.content[0].text
        assert "Muldrotha, the Gravetide" in text
        assert "{3}{B}{G}{U}" in text
        assert "6/6" in text

        sc = result.structured_content
        assert isinstance(sc, dict)
        assert sc["name"] == "Muldrotha, the Gravetide"
        assert "type_line" in sc

    @respx.mock
    async def test_not_found_returns_error(self, client: Client):
        """card_details returns an error response for nonexistent cards."""
        fixture = _load_fixture("card_not_found.json")
        respx.get(f"{BASE_URL}/cards/named", params={"exact": "Xyzzy"}).mock(
            return_value=httpx.Response(404, json=fixture)
        )

        result = await client.call_tool("card_details", {"name": "Xyzzy"}, raise_on_error=False)
        assert result.is_error


class TestCardDetailsConcise:
    """Scryfall card_details tool concise mode."""

    @respx.mock
    async def test_concise_is_shorter(self, client: Client):
        """Concise output returns only name, type, and price -- no oracle text or legalities."""
        fixture = _load_fixture("card_muldrotha.json")
        respx.get(f"{BASE_URL}/cards/named", params={"exact": "Muldrotha, the Gravetide"}).mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result_detailed = await client.call_tool(
            "card_details",
            {"name": "Muldrotha, the Gravetide", "response_format": "detailed"},
        )
        respx.get(f"{BASE_URL}/cards/named", params={"exact": "Muldrotha, the Gravetide"}).mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result_concise = await client.call_tool(
            "card_details",
            {"name": "Muldrotha, the Gravetide", "response_format": "concise"},
        )
        detailed_text = result_detailed.content[0].text
        concise_text = result_concise.content[0].text
        assert len(concise_text) < len(detailed_text)
        assert "Muldrotha, the Gravetide" in concise_text
        # Concise should NOT include legalities or scryfall URI
        assert "Legalities:" not in concise_text
        assert "Scryfall:" not in concise_text

        sc = result_concise.structured_content
        assert isinstance(sc, dict)
        assert sc["name"] == "Muldrotha, the Gravetide"
        assert "type_line" in sc


class TestCardPrice:
    """Scryfall card_price tool behavior."""

    @respx.mock
    async def test_returns_prices(self, client: Client):
        """card_price returns pricing data with USD formatting."""
        fixture = _load_fixture("card_sol_ring.json")
        respx.get(f"{BASE_URL}/cards/named", params={"exact": "Sol Ring"}).mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result = await client.call_tool("card_price", {"name": "Sol Ring"})
        text = result.content[0].text
        assert "Sol Ring" in text
        assert "$" in text

        sc = result.structured_content
        assert isinstance(sc, dict)
        assert sc["name"] == "Sol Ring"
        assert "prices" in sc


class TestCardRulings:
    """Scryfall card_rulings tool behavior."""

    @respx.mock
    async def test_returns_rulings(self, client: Client):
        """card_rulings returns rulings list with count for a valid card."""
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

        sc = result.structured_content
        assert isinstance(sc, dict)
        assert sc["name"] == "Muldrotha, the Gravetide"
        assert sc["total_rulings"] == 8
        assert isinstance(sc["rulings"], list)


class TestSetInfo:
    """Scryfall set_info tool behavior."""

    @respx.mock
    async def test_returns_set_details(self, client: Client):
        """set_info returns set metadata with name, code, type, and release date."""
        fixture = _load_fixture("set_dominaria.json")
        respx.get(f"{BASE_URL}/sets/dom").mock(return_value=httpx.Response(200, json=fixture))

        result = await client.call_tool("set_info", {"set_code": "dom"})
        text = result.content[0].text
        assert "Dominaria" in text
        assert "DOM" in text
        assert "expansion" in text
        assert "2018-04-27" in text
        assert "280" in text
        assert "Data provided by [Scryfall]" in text

        sc = result.structured_content
        assert isinstance(sc, dict)
        assert sc["name"] == "Dominaria"
        assert sc["code"] == "dom"

    @respx.mock
    async def test_set_not_found(self, client: Client):
        """set_info returns an error for nonexistent set codes."""
        respx.get(f"{BASE_URL}/sets/zzz").mock(
            return_value=httpx.Response(
                404, json={"object": "error", "code": "not_found", "details": ""}
            )
        )

        result = await client.call_tool("set_info", {"set_code": "zzz"}, raise_on_error=False)
        assert result.is_error
        assert "not found" in result.content[0].text.lower()


class TestWhatsNew:
    """Scryfall whats_new tool behavior."""

    @respx.mock
    async def test_returns_recent_cards(self, client: Client):
        """whats_new returns a formatted list of recently released cards."""
        fixture = _load_fixture("search_sultai_commander.json")
        respx.get(f"{BASE_URL}/cards/search").mock(return_value=httpx.Response(200, json=fixture))

        result = await client.call_tool("whats_new", {"days": 30})
        text = result.content[0].text
        assert "Found" in text
        assert "card" in text.lower()
        assert "Data provided by [Scryfall]" in text

        sc = result.structured_content
        assert isinstance(sc, dict)
        assert sc["total_cards"] == 9273
        assert isinstance(sc["cards"], list)

    @respx.mock
    async def test_with_set_and_format_filters(self, client: Client):
        """whats_new accepts optional set_code and format filters."""
        fixture = _load_fixture("search_sultai_commander.json")
        respx.get(f"{BASE_URL}/cards/search").mock(return_value=httpx.Response(200, json=fixture))

        result = await client.call_tool(
            "whats_new", {"days": 7, "set_code": "dom", "format": "standard"}
        )
        text = result.content[0].text
        assert "Found" in text

        sc = result.structured_content
        assert isinstance(sc, dict)
        assert sc["days"] == 7
        assert sc["set_code"] == "dom"

    async def test_invalid_days_zero(self, client: Client):
        """whats_new rejects days < 1."""
        result = await client.call_tool("whats_new", {"days": 0}, raise_on_error=False)
        assert result.is_error
        assert "days must be at least 1" in result.content[0].text.lower()

    @respx.mock
    async def test_no_results(self, client: Client):
        """whats_new returns an error when no cards match the date range."""
        respx.get(f"{BASE_URL}/cards/search").mock(
            return_value=httpx.Response(
                404, json={"object": "error", "code": "not_found", "details": ""}
            )
        )

        result = await client.call_tool("whats_new", {"days": 1}, raise_on_error=False)
        assert result.is_error
        assert "no new cards found" in result.content[0].text.lower()


class TestWhatsNewConcise:
    """Scryfall whats_new tool concise mode."""

    @respx.mock
    async def test_concise_is_shorter(self, client: Client):
        """Concise output omits type line, producing shorter text."""
        fixture = _load_fixture("search_sultai_commander.json")
        respx.get(f"{BASE_URL}/cards/search").mock(return_value=httpx.Response(200, json=fixture))

        result_detailed = await client.call_tool(
            "whats_new", {"days": 30, "response_format": "detailed"}
        )
        respx.get(f"{BASE_URL}/cards/search").mock(return_value=httpx.Response(200, json=fixture))

        result_concise = await client.call_tool(
            "whats_new", {"days": 30, "response_format": "concise"}
        )
        detailed_text = result_detailed.content[0].text
        concise_text = result_concise.content[0].text
        assert len(concise_text) < len(detailed_text)
        assert "Found" in concise_text

        sc = result_concise.structured_content
        assert isinstance(sc, dict)
        assert sc["total_cards"] == 9273
        assert isinstance(sc["cards"], list)


class TestToolRegistration:
    """Scryfall provider tool registration."""

    async def test_all_tools_registered(self, client: Client):
        """All six Scryfall tools are registered on the provider."""
        tools = await client.list_tools()
        tool_names = {t.name for t in tools}
        assert tool_names == {
            "search_cards",
            "card_details",
            "card_price",
            "card_rulings",
            "set_info",
            "whats_new",
        }
