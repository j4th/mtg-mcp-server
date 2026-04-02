"""Tests for the EDHREC MCP provider."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from fastmcp import Client

from mtg_mcp_server.providers.edhrec import edhrec_mcp

FIXTURES = Path(__file__).parent.parent / "fixtures" / "edhrec"
BASE_URL = "https://json.edhrec.com"


def _load_fixture(name: str) -> dict:
    """Load an EDHREC JSON fixture file by name."""
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
async def client():
    """Provide an in-memory MCP client connected to the EDHREC provider."""
    async with Client(transport=edhrec_mcp) as c:
        yield c


class TestCommanderStaples:
    """EDHREC commander_staples tool behavior."""

    @respx.mock
    async def test_returns_formatted_results(self, client: Client):
        """commander_staples returns formatted staples with synergy scores and deck count."""
        fixture = _load_fixture("commander_muldrotha.json")
        respx.get(f"{BASE_URL}/pages/commanders/muldrotha-the-gravetide.json").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result = await client.call_tool(
            "commander_staples", {"commander_name": "Muldrotha, the Gravetide"}
        )
        text = result.content[0].text
        assert "Muldrotha, the Gravetide" in text
        assert "22329 decks" in text
        assert "Spore Frog" in text
        assert "+53%" in text
        assert "Data provided by [EDHREC]" in text

        # Structured output
        sc = result.structured_content
        assert sc is not None
        assert sc["commander_name"] == "Muldrotha, the Gravetide"
        assert sc["total_decks"] == 22329
        assert isinstance(sc["categories"], list)
        assert len(sc["categories"]) > 0
        # Slim fields only
        card = sc["categories"][0]["cards"][0]
        assert "name" in card
        assert "synergy" in card
        assert "inclusion" in card
        assert "num_decks" in card
        # Bloat fields excluded
        assert "sanitized" not in card
        assert "potential_decks" not in card
        assert "label" not in card

    @respx.mock
    async def test_category_filter(self, client: Client):
        """commander_staples filters results to a single card category when specified."""
        fixture = _load_fixture("commander_muldrotha.json")
        respx.get(f"{BASE_URL}/pages/commanders/muldrotha-the-gravetide.json").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result = await client.call_tool(
            "commander_staples",
            {"commander_name": "Muldrotha, the Gravetide", "category": "creatures"},
        )
        text = result.content[0].text
        assert "Creatures" in text
        assert "Spore Frog" in text
        # Should not contain other categories
        assert "Enchantments" not in text

        # Structured output respects filter
        sc = result.structured_content
        assert sc is not None
        assert len(sc["categories"]) == 1
        assert sc["categories"][0]["header"] == "Creatures"

    @respx.mock
    async def test_limit_caps_per_category(self, client: Client):
        """commander_staples respects limit parameter per category."""
        fixture = _load_fixture("commander_muldrotha.json")
        respx.get(f"{BASE_URL}/pages/commanders/muldrotha-the-gravetide.json").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result = await client.call_tool(
            "commander_staples",
            {"commander_name": "Muldrotha, the Gravetide", "limit": 2},
        )
        sc = result.structured_content
        for cat in sc["categories"]:
            assert len(cat["cards"]) <= 2

    @respx.mock
    async def test_not_found_returns_error(self, client: Client):
        """commander_staples returns an error response for nonexistent commanders."""
        respx.get(f"{BASE_URL}/pages/commanders/xyzzy-nonexistent.json").mock(
            return_value=httpx.Response(404, text="Not Found")
        )

        result = await client.call_tool(
            "commander_staples",
            {"commander_name": "Xyzzy Nonexistent"},
            raise_on_error=False,
        )
        assert result.is_error


class TestCardSynergy:
    """EDHREC card_synergy tool behavior."""

    @respx.mock
    async def test_returns_synergy_data(self, client: Client):
        """card_synergy returns synergy score and classification for a card-commander pair."""
        fixture = _load_fixture("commander_muldrotha.json")
        respx.get(f"{BASE_URL}/pages/commanders/muldrotha-the-gravetide.json").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result = await client.call_tool(
            "card_synergy",
            {"card_name": "Spore Frog", "commander_name": "Muldrotha, the Gravetide"},
        )
        text = result.content[0].text
        assert "Spore Frog" in text
        assert "+53%" in text
        assert "high-synergy" in text

        # Structured output
        sc = result.structured_content
        assert sc is not None
        assert sc["card_name"] == "Spore Frog"
        assert sc["commander_name"] == "Muldrotha, the Gravetide"
        assert sc["found"] is True
        assert isinstance(sc["synergy"], float)
        assert sc["synergy"] > 0.3
        assert isinstance(sc["num_decks"], int)

    @respx.mock
    async def test_card_not_found_returns_message(self, client: Client):
        """card_synergy returns a 'not found' message when the card is not in the commander's data."""
        fixture = _load_fixture("commander_muldrotha.json")
        respx.get(f"{BASE_URL}/pages/commanders/muldrotha-the-gravetide.json").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result = await client.call_tool(
            "card_synergy",
            {
                "card_name": "Totally Nonexistent Card",
                "commander_name": "Muldrotha, the Gravetide",
            },
        )
        text = result.content[0].text
        assert "not found" in text.lower()

        # Structured output for not-found case
        sc = result.structured_content
        assert sc is not None
        assert sc["found"] is False
        assert sc["card_name"] == "Totally Nonexistent Card"


class TestToolRegistration:
    """EDHREC provider tool registration."""

    async def test_all_tools_registered(self, client: Client):
        """Both EDHREC tools are registered on the provider."""
        tools = await client.list_tools()
        tool_names = {t.name for t in tools}
        assert tool_names == {"commander_staples", "card_synergy"}
