"""Tests for the EDHREC MCP provider."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from fastmcp import Client

from mtg_mcp.providers.edhrec import edhrec_mcp

FIXTURES = Path(__file__).parent.parent / "fixtures" / "edhrec"
BASE_URL = "https://json.edhrec.com"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
async def client():
    async with Client(transport=edhrec_mcp) as c:
        yield c


class TestCommanderStaples:
    @respx.mock
    async def test_returns_formatted_results(self, client: Client):
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

    @respx.mock
    async def test_category_filter(self, client: Client):
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

    @respx.mock
    async def test_not_found_returns_error(self, client: Client):
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
    @respx.mock
    async def test_returns_synergy_data(self, client: Client):
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

    @respx.mock
    async def test_card_not_found_returns_message(self, client: Client):
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


class TestToolRegistration:
    async def test_all_tools_registered(self, client: Client):
        tools = await client.list_tools()
        tool_names = {t.name for t in tools}
        assert tool_names == {"commander_staples", "card_synergy"}
