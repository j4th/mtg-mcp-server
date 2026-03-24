"""Tests for the Commander Spellbook MCP provider."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from fastmcp import Client

from mtg_mcp_server.providers.spellbook import spellbook_mcp

FIXTURES = Path(__file__).parent.parent / "fixtures" / "spellbook"
BASE_URL = "https://backend.commanderspellbook.com"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
async def client():
    async with Client(transport=spellbook_mcp) as c:
        yield c


class TestFindCombos:
    @respx.mock
    async def test_returns_formatted_results(self, client: Client):
        fixture = _load_fixture("combos_muldrotha.json")
        respx.get(
            f"{BASE_URL}/variants/",
            params={"q": 'card:"Muldrotha, the Gravetide"', "limit": "10"},
        ).mock(return_value=httpx.Response(200, json=fixture))

        result = await client.call_tool("find_combos", {"card_name": "Muldrotha, the Gravetide"})
        text = result.content[0].text
        assert "5 combo(s)" in text
        assert "Muldrotha, the Gravetide" in text
        assert "1414-2730-5131-5256" in text
        assert "Data provided by [Commander Spellbook]" in text

    @respx.mock
    async def test_no_combos_returns_message(self, client: Client):
        fixture = _load_fixture("combos_not_found.json")
        respx.get(
            f"{BASE_URL}/variants/",
            params={"q": 'card:"Xyzzy Nonexistent"', "limit": "10"},
        ).mock(return_value=httpx.Response(200, json=fixture))

        result = await client.call_tool("find_combos", {"card_name": "Xyzzy Nonexistent"})
        text = result.content[0].text
        assert "No combos found" in text


class TestComboDetails:
    @respx.mock
    async def test_returns_combo_data(self, client: Client):
        fixture = _load_fixture("combo_detail.json")
        respx.get(f"{BASE_URL}/variants/1414-2730-5131-5256/").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result = await client.call_tool("combo_details", {"combo_id": "1414-2730-5131-5256"})
        text = result.content[0].text
        assert "1414-2730-5131-5256" in text
        assert "Muldrotha, the Gravetide" in text
        assert "BGU" in text
        assert "Infinite death triggers" in text

    @respx.mock
    async def test_not_found_returns_error(self, client: Client):
        respx.get(f"{BASE_URL}/variants/9999-9999/").mock(
            return_value=httpx.Response(404, json={"detail": "Not found."})
        )

        result = await client.call_tool(
            "combo_details", {"combo_id": "9999-9999"}, raise_on_error=False
        )
        assert result.is_error


class TestFindDecklistCombos:
    @respx.mock
    async def test_returns_analysis(self, client: Client):
        fixture = _load_fixture("find_my_combos_response.json")
        respx.post(f"{BASE_URL}/find-my-combos").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result = await client.call_tool(
            "find_decklist_combos",
            {
                "commanders": ["Muldrotha, the Gravetide"],
                "decklist": ["Sol Ring", "Spore Frog"],
            },
        )
        text = result.content[0].text
        assert "BGU" in text
        assert "combo" in text.lower()


class TestEstimateBracket:
    @respx.mock
    async def test_returns_bracket(self, client: Client):
        fixture = _load_fixture("estimate_bracket_response.json")
        respx.post(f"{BASE_URL}/estimate-bracket").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result = await client.call_tool(
            "estimate_bracket",
            {
                "commanders": ["Muldrotha, the Gravetide"],
                "decklist": ["Sol Ring", "Spore Frog"],
            },
        )
        text = result.content[0].text
        assert "E" in text


class TestToolRegistration:
    async def test_all_tools_registered(self, client: Client):
        tools = await client.list_tools()
        tool_names = {t.name for t in tools}
        assert tool_names == {
            "find_combos",
            "combo_details",
            "find_decklist_combos",
            "estimate_bracket",
        }
