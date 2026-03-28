"""Tests for the 17Lands MCP provider."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from fastmcp import Client

from mtg_mcp_server.providers.seventeen_lands import draft_mcp

FIXTURES = Path(__file__).parent.parent / "fixtures" / "seventeen_lands"
BASE_URL = "https://www.17lands.com"


def _load_fixture(name: str) -> list[dict]:
    """Load a 17Lands JSON fixture file by name."""
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
async def client():
    """Provide an in-memory MCP client connected to the 17Lands provider."""
    async with Client(transport=draft_mcp) as c:
        yield c


class TestCardRatings:
    """17Lands card_ratings tool behavior."""

    @respx.mock
    async def test_returns_formatted_results(self, client: Client):
        """card_ratings returns formatted card list with GIH WR, ALSA, and attribution."""
        fixture = _load_fixture("card_ratings_lci.json")
        respx.get(
            f"{BASE_URL}/card_ratings/data",
            params={"expansion": "LCI", "event_type": "PremierDraft"},
        ).mock(return_value=httpx.Response(200, json=fixture))

        result = await client.call_tool("card_ratings", {"set_code": "LCI"})
        text = result.content[0].text
        assert "5 cards" in text
        assert "Abuelo's Awakening" in text
        assert "GIH WR:" in text
        assert "ALSA:" in text
        assert "Data provided by [17Lands]" in text

        # Structured output
        sc = result.structured_content
        assert isinstance(sc, dict)
        assert sc["set_code"] == "LCI"
        assert sc["event_type"] == "PremierDraft"
        assert sc["total_cards"] == 5
        assert isinstance(sc["cards"], list)
        assert len(sc["cards"]) == 5
        assert sc["cards"][0]["name"] == "Abuelo's Awakening"

    @respx.mock
    async def test_empty_results(self, client: Client):
        """card_ratings returns a 'no data' message for unknown set codes."""
        respx.get(
            f"{BASE_URL}/card_ratings/data",
            params={"expansion": "FAKE", "event_type": "PremierDraft"},
        ).mock(return_value=httpx.Response(200, json=[]))

        result = await client.call_tool("card_ratings", {"set_code": "FAKE"})
        text = result.content[0].text
        assert "No card rating data" in text

        # Structured output — empty result
        sc = result.structured_content
        assert isinstance(sc, dict)
        assert sc["total_cards"] == 0
        assert sc["cards"] == []

    @respx.mock
    async def test_server_error_returns_tool_error(self, client: Client):
        """card_ratings returns an error response on server failure."""
        respx.get(
            f"{BASE_URL}/card_ratings/data",
            params={"expansion": "LCI", "event_type": "PremierDraft"},
        ).mock(return_value=httpx.Response(500, text="Internal Server Error"))

        result = await client.call_tool("card_ratings", {"set_code": "LCI"}, raise_on_error=False)
        assert result.is_error


class TestArchetypeStats:
    """17Lands archetype_stats tool behavior."""

    @respx.mock
    async def test_returns_formatted_results(self, client: Client):
        """archetype_stats returns formatted color pair win rates."""
        fixture = _load_fixture("color_ratings_lci.json")
        respx.get(
            f"{BASE_URL}/color_ratings/data",
            params={
                "expansion": "LCI",
                "event_type": "PremierDraft",
                "start_date": "2023-11-07",
                "end_date": "2024-02-07",
            },
        ).mock(return_value=httpx.Response(200, json=fixture))

        result = await client.call_tool(
            "archetype_stats",
            {
                "set_code": "LCI",
                "start_date": "2023-11-07",
                "end_date": "2024-02-07",
            },
        )
        text = result.content[0].text
        assert "Archetype stats" in text
        assert "Azorius (WU)" in text
        assert "WR:" in text

        # Structured output
        sc = result.structured_content
        assert isinstance(sc, dict)
        assert sc["set_code"] == "LCI"
        assert sc["event_type"] == "PremierDraft"
        assert sc["start_date"] == "2023-11-07"
        assert sc["end_date"] == "2024-02-07"
        assert isinstance(sc["archetypes"], list)
        assert sc["total_archetypes"] == len(fixture)
        assert any(a["color_name"] == "Azorius (WU)" for a in sc["archetypes"])

    @respx.mock
    async def test_server_error_returns_tool_error(self, client: Client):
        """archetype_stats returns an error response on server failure."""
        respx.get(
            f"{BASE_URL}/color_ratings/data",
            params={
                "expansion": "LCI",
                "event_type": "PremierDraft",
                "start_date": "2023-11-07",
                "end_date": "2024-02-07",
            },
        ).mock(return_value=httpx.Response(500, text="Internal Server Error"))

        result = await client.call_tool(
            "archetype_stats",
            {
                "set_code": "LCI",
                "start_date": "2023-11-07",
                "end_date": "2024-02-07",
            },
            raise_on_error=False,
        )
        assert result.is_error


class TestToolRegistration:
    """17Lands provider tool registration."""

    async def test_all_tools_registered(self, client: Client):
        """Both 17Lands tools are registered on the provider."""
        tools = await client.list_tools()
        tool_names = {t.name for t in tools}
        assert tool_names == {"card_ratings", "archetype_stats"}
