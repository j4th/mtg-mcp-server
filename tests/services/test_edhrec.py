"""Tests for the EDHREC service client."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from mtg_mcp_server.services.edhrec import CommanderNotFoundError, EDHRECClient, EDHRECError
from mtg_mcp_server.types import EDHRECCard, EDHRECCardList, EDHRECCommanderData

FIXTURES = Path(__file__).parent.parent / "fixtures" / "edhrec"
BASE_URL = "https://json.edhrec.com"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class TestSlugify:
    """Test the name-to-slug conversion for EDHREC URLs."""

    def test_basic_name(self):
        client = EDHRECClient.__new__(EDHRECClient)
        assert client._slugify("Sol Ring") == "sol-ring"

    def test_comma_removed(self):
        client = EDHRECClient.__new__(EDHRECClient)
        assert client._slugify("Muldrotha, the Gravetide") == "muldrotha-the-gravetide"

    def test_apostrophe_removed(self):
        client = EDHRECClient.__new__(EDHRECClient)
        assert client._slugify("Kaya's Ghostform") == "kayas-ghostform"

    def test_multiple_special_chars(self):
        client = EDHRECClient.__new__(EDHRECClient)
        assert client._slugify("Urza's Saga") == "urzas-saga"

    def test_multiple_spaces(self):
        client = EDHRECClient.__new__(EDHRECClient)
        assert client._slugify("The  Gitrog   Monster") == "the-gitrog-monster"

    def test_period_removed(self):
        client = EDHRECClient.__new__(EDHRECClient)
        assert client._slugify("Dr. Julius Jumblemorph") == "dr-julius-jumblemorph"


class TestCommanderTopCards:
    @respx.mock
    async def test_returns_commander_data(self):
        fixture = _load_fixture("commander_muldrotha.json")
        respx.get(f"{BASE_URL}/pages/commanders/muldrotha-the-gravetide.json").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with EDHRECClient(base_url=BASE_URL) as client:
            result = await client.commander_top_cards("Muldrotha, the Gravetide")

        assert isinstance(result, EDHRECCommanderData)
        assert result.commander_name == "Muldrotha, the Gravetide"
        assert result.total_decks == 22329
        assert len(result.cardlists) > 0
        # Check that cardlists are properly parsed
        assert all(isinstance(cl, EDHRECCardList) for cl in result.cardlists)
        # Check that cardviews contain EDHRECCard instances
        high_synergy = next((cl for cl in result.cardlists if cl.tag == "highsynergycards"), None)
        assert high_synergy is not None
        assert len(high_synergy.cardviews) == 3
        spore_frog = high_synergy.cardviews[0]
        assert isinstance(spore_frog, EDHRECCard)
        assert spore_frog.name == "Spore Frog"
        assert spore_frog.synergy == 0.53
        assert spore_frog.num_decks == 13416

    @respx.mock
    async def test_category_filter(self):
        fixture = _load_fixture("commander_muldrotha.json")
        respx.get(f"{BASE_URL}/pages/commanders/muldrotha-the-gravetide.json").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with EDHRECClient(base_url=BASE_URL) as client:
            result = await client.commander_top_cards(
                "Muldrotha, the Gravetide", category="creatures"
            )

        assert len(result.cardlists) == 1
        assert result.cardlists[0].tag == "creatures"
        assert result.cardlists[0].cardviews[0].name == "Spore Frog"

    @respx.mock
    async def test_category_filter_no_match(self):
        fixture = _load_fixture("commander_muldrotha.json")
        respx.get(f"{BASE_URL}/pages/commanders/muldrotha-the-gravetide.json").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with EDHRECClient(base_url=BASE_URL) as client:
            result = await client.commander_top_cards(
                "Muldrotha, the Gravetide", category="planeswalkers"
            )

        assert len(result.cardlists) == 0

    @respx.mock
    async def test_not_found_raises(self):
        respx.get(f"{BASE_URL}/pages/commanders/xyzzy-nonexistent.json").mock(
            return_value=httpx.Response(404, text="Not Found")
        )
        async with EDHRECClient(base_url=BASE_URL) as client:
            with pytest.raises(CommanderNotFoundError, match="xyzzy-nonexistent"):
                await client.commander_top_cards("Xyzzy Nonexistent")

    @respx.mock
    async def test_403_raises_not_found(self):
        """EDHREC returns 403 for missing commanders, not 404."""
        respx.get(f"{BASE_URL}/pages/commanders/xyzzy-nonexistent.json").mock(
            return_value=httpx.Response(403, text="Forbidden")
        )
        async with EDHRECClient(base_url=BASE_URL) as client:
            with pytest.raises(CommanderNotFoundError):
                await client.commander_top_cards("Xyzzy Nonexistent")

    @respx.mock
    async def test_defensive_missing_cardlists(self):
        """Handle missing or malformed container structure gracefully."""
        fixture = {"header": "Test Commander", "container": {}}
        respx.get(f"{BASE_URL}/pages/commanders/test-commander.json").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with EDHRECClient(base_url=BASE_URL) as client:
            result = await client.commander_top_cards("Test Commander")

        assert result.commander_name == "Test Commander"
        assert result.cardlists == []
        assert result.total_decks == 0


class TestCardSynergy:
    @respx.mock
    async def test_finds_card_in_commander(self):
        fixture = _load_fixture("commander_muldrotha.json")
        respx.get(f"{BASE_URL}/pages/commanders/muldrotha-the-gravetide.json").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with EDHRECClient(base_url=BASE_URL) as client:
            result = await client.card_synergy("Spore Frog", "Muldrotha, the Gravetide")

        assert result is not None
        assert result.name == "Spore Frog"
        assert result.synergy == 0.53
        assert result.num_decks == 13416

    @respx.mock
    async def test_card_not_in_commander(self):
        fixture = _load_fixture("commander_muldrotha.json")
        respx.get(f"{BASE_URL}/pages/commanders/muldrotha-the-gravetide.json").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with EDHRECClient(base_url=BASE_URL) as client:
            result = await client.card_synergy(
                "Totally Nonexistent Card", "Muldrotha, the Gravetide"
            )

        assert result is None


class TestServerErrors:
    @respx.mock
    async def test_500_raises_edhrec_error(self):
        respx.get(f"{BASE_URL}/pages/commanders/muldrotha-the-gravetide.json").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        async with EDHRECClient(base_url=BASE_URL) as client:
            with pytest.raises(EDHRECError):
                await client.commander_top_cards("Muldrotha, the Gravetide")
