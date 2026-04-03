"""Tests for the Moxfield MCP provider."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from fastmcp import Client

from mtg_mcp_server.providers.moxfield import moxfield_mcp
from mtg_mcp_server.services.moxfield import MoxfieldClient

FIXTURES = Path(__file__).parent.parent / "fixtures" / "moxfield"
BASE_URL = "https://api2.moxfield.com"


def _load_fixture(name: str) -> dict:
    """Load a Moxfield JSON fixture file by name."""
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def _clear_moxfield_caches():
    """Clear MoxfieldClient caches before each test to prevent leakage."""
    MoxfieldClient._deck_cache.clear()


@pytest.fixture
async def client():
    """Provide an in-memory MCP client connected to the Moxfield provider."""
    async with Client(transport=moxfield_mcp) as c:
        yield c


class TestMoxfieldDecklist:
    """Moxfield decklist tool behavior."""

    @respx.mock
    async def test_returns_formatted_decklist(self, client: Client):
        """decklist returns formatted markdown with deck name, format, boards, and attribution."""
        fixture = _load_fixture("deck_commander.json")
        respx.get(f"{BASE_URL}/v3/decks/all/abc123").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result = await client.call_tool("decklist", {"deck_id": "abc123"})
        text = result.content[0].text

        # Deck name and format
        assert "Muldrotha Self-Mill" in text
        assert "commander" in text
        # Author
        assert "mtgplayer42" in text
        # Board sections with "Nx Card Name" format
        assert "### Commanders" in text
        assert "1x Muldrotha, the Gravetide" in text
        assert "### Mainboard" in text
        assert "1x Sol Ring" in text
        assert "### Sideboard" in text
        assert "1x Strip Mine" in text
        # Attribution
        assert "Data provided by [Moxfield]" in text

    @respx.mock
    async def test_structured_content_has_all_boards(self, client: Client):
        """Structured content contains deck, commanders, mainboard, sideboard, companions, total_cards."""
        fixture = _load_fixture("deck_commander.json")
        respx.get(f"{BASE_URL}/v3/decks/all/abc123").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result = await client.call_tool("decklist", {"deck_id": "abc123"})
        sc = result.structured_content

        assert sc is not None
        assert "deck" in sc
        assert "commanders" in sc
        assert "mainboard" in sc
        assert "sideboard" in sc
        assert "companions" in sc
        assert "total_cards" in sc
        assert isinstance(sc["total_cards"], int)
        assert sc["total_cards"] > 0

    @respx.mock
    async def test_card_entries_have_name_and_quantity(self, client: Client):
        """Each card in structured_content has name and quantity fields."""
        fixture = _load_fixture("deck_commander.json")
        respx.get(f"{BASE_URL}/v3/decks/all/abc123").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result = await client.call_tool("decklist", {"deck_id": "abc123"})
        sc = result.structured_content

        # Check commanders
        for card in sc["commanders"]:
            assert "name" in card
            assert "quantity" in card
            assert isinstance(card["name"], str)
            assert isinstance(card["quantity"], int)

        # Check mainboard
        for card in sc["mainboard"]:
            assert "name" in card
            assert "quantity" in card

        # Check sideboard
        for card in sc["sideboard"]:
            assert "name" in card
            assert "quantity" in card

    @respx.mock
    async def test_not_found_returns_error(self, client: Client):
        """decklist returns an error response for nonexistent decks."""
        respx.get(f"{BASE_URL}/v3/decks/all/nonexistent").mock(
            return_value=httpx.Response(404, text="Not Found")
        )

        result = await client.call_tool(
            "decklist",
            {"deck_id": "nonexistent"},
            raise_on_error=False,
        )
        assert result.is_error
        assert "not found" in result.content[0].text.lower()

    @respx.mock
    async def test_server_error_returns_error(self, client: Client):
        """decklist returns an error response for server errors (non-404)."""
        respx.get(f"{BASE_URL}/v3/decks/all/abc123").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        result = await client.call_tool(
            "decklist",
            {"deck_id": "abc123"},
            raise_on_error=False,
        )
        assert result.is_error
        assert "Moxfield API error" in result.content[0].text

    @respx.mock
    async def test_accepts_full_url(self, client: Client):
        """decklist accepts a full Moxfield URL as input."""
        fixture = _load_fixture("deck_commander.json")
        respx.get(f"{BASE_URL}/v3/decks/all/abc123").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result = await client.call_tool(
            "decklist",
            {"deck_id": "https://www.moxfield.com/decks/abc123"},
        )
        text = result.content[0].text
        assert "Muldrotha Self-Mill" in text


class TestMoxfieldDeckInfo:
    """Moxfield deck_info tool behavior."""

    @respx.mock
    async def test_returns_deck_metadata(self, client: Client):
        """deck_info returns markdown with name, format, author, and dates."""
        fixture = _load_fixture("deck_commander.json")
        respx.get(f"{BASE_URL}/v3/decks/all/abc123").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result = await client.call_tool("deck_info", {"deck_id": "abc123"})
        text = result.content[0].text

        assert "Muldrotha Self-Mill" in text
        assert "commander" in text
        assert "mtgplayer42" in text
        assert "2025-01-15" in text
        assert "2025-03-20" in text

    @respx.mock
    async def test_structured_content_has_metadata(self, client: Client):
        """Structured content has deck metadata fields and board_counts."""
        fixture = _load_fixture("deck_commander.json")
        respx.get(f"{BASE_URL}/v3/decks/all/abc123").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result = await client.call_tool("deck_info", {"deck_id": "abc123"})
        sc = result.structured_content

        assert sc is not None
        assert sc["id"] == "abc123"
        assert sc["name"] == "Muldrotha Self-Mill"
        assert sc["format"] == "commander"
        assert sc["author"] == "mtgplayer42"
        assert "board_counts" in sc
        assert isinstance(sc["board_counts"], dict)
        assert "commanders" in sc["board_counts"]
        assert "mainboard" in sc["board_counts"]

    @respx.mock
    async def test_not_found_returns_error(self, client: Client):
        """deck_info returns an error response for nonexistent decks."""
        respx.get(f"{BASE_URL}/v3/decks/all/nonexistent").mock(
            return_value=httpx.Response(404, text="Not Found")
        )

        result = await client.call_tool(
            "deck_info",
            {"deck_id": "nonexistent"},
            raise_on_error=False,
        )
        assert result.is_error
        assert "not found" in result.content[0].text.lower()

    @respx.mock
    async def test_server_error_returns_error(self, client: Client):
        """deck_info returns an error response for server errors (non-404)."""
        respx.get(f"{BASE_URL}/v3/decks/all/abc123").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        result = await client.call_tool(
            "deck_info",
            {"deck_id": "abc123"},
            raise_on_error=False,
        )
        assert result.is_error
        assert "Moxfield API error" in result.content[0].text


class TestToolRegistration:
    """Moxfield provider tool registration."""

    async def test_all_tools_registered(self, client: Client):
        """Both Moxfield tools are registered on the provider."""
        tools = await client.list_tools()
        tool_names = {t.name for t in tools}
        assert tool_names == {"decklist", "deck_info"}

    async def test_tools_have_annotations(self, client: Client):
        """Tools have the expected readOnly, idempotent, and openWorld annotations."""
        tools = await client.list_tools()
        for tool in tools:
            assert tool.annotations is not None
            assert tool.annotations.readOnlyHint is True
            assert tool.annotations.idempotentHint is True
            assert tool.annotations.openWorldHint is True


class TestMoxfieldResource:
    """Moxfield mtg://moxfield/{deck_id} resource behavior."""

    @respx.mock
    async def test_deck_resource_returns_json(self, client: Client):
        """Resource returns parseable JSON with deck data."""
        fixture = _load_fixture("deck_commander.json")
        respx.get(f"{BASE_URL}/v3/decks/all/abc123").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result = await client.read_resource("mtg://moxfield/abc123")
        data = json.loads(result[0].text)
        assert data["deck"]["name"] == "Muldrotha Self-Mill"
        assert "commanders" in data
        assert "mainboard" in data

    @respx.mock
    async def test_deck_resource_not_found_returns_error_json(self, client: Client):
        """Resource returns error JSON for nonexistent decks."""
        respx.get(f"{BASE_URL}/v3/decks/all/nonexistent").mock(
            return_value=httpx.Response(404, text="Not Found")
        )

        result = await client.read_resource("mtg://moxfield/nonexistent")
        data = json.loads(result[0].text)
        assert "error" in data
        assert "Deck not found" in data["error"]

    @respx.mock
    async def test_deck_resource_server_error_returns_error_json(self, client: Client):
        """Resource returns error JSON for server errors."""
        respx.get(f"{BASE_URL}/v3/decks/all/abc123").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        result = await client.read_resource("mtg://moxfield/abc123")
        data = json.loads(result[0].text)
        assert "error" in data
        assert "Moxfield error" in data["error"]

    async def test_resource_template_registered(self, client: Client):
        """Moxfield deck resource template is registered on the provider."""
        templates = await client.list_resource_templates()
        template_uris = {t.uriTemplate for t in templates}
        assert "mtg://moxfield/{deck_id}" in template_uris
