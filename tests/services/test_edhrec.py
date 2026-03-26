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
    """Load an EDHREC JSON fixture by filename."""
    return json.loads((FIXTURES / name).read_text())


class TestSlugify:
    """Test the name-to-slug conversion for EDHREC URLs."""

    def test_basic_name(self):
        """Simple two-word name converts to lowercase hyphenated slug."""
        client = EDHRECClient.__new__(EDHRECClient)
        assert client._slugify("Sol Ring") == "sol-ring"

    def test_comma_removed(self):
        """Commas are stripped from the slug."""
        client = EDHRECClient.__new__(EDHRECClient)
        assert client._slugify("Muldrotha, the Gravetide") == "muldrotha-the-gravetide"

    def test_apostrophe_removed(self):
        """Apostrophes are stripped from the slug."""
        client = EDHRECClient.__new__(EDHRECClient)
        assert client._slugify("Kaya's Ghostform") == "kayas-ghostform"

    def test_multiple_special_chars(self):
        """Multiple special characters are all stripped from the slug."""
        client = EDHRECClient.__new__(EDHRECClient)
        assert client._slugify("Urza's Saga") == "urzas-saga"

    def test_multiple_spaces(self):
        """Consecutive spaces are collapsed into a single hyphen."""
        client = EDHRECClient.__new__(EDHRECClient)
        assert client._slugify("The  Gitrog   Monster") == "the-gitrog-monster"

    def test_period_removed(self):
        """Periods are stripped from the slug."""
        client = EDHRECClient.__new__(EDHRECClient)
        assert client._slugify("Dr. Julius Jumblemorph") == "dr-julius-jumblemorph"


class TestCommanderTopCards:
    """Commander top cards and staples retrieval."""

    @respx.mock
    async def test_returns_commander_data(self):
        """Commander page returns EDHRECCommanderData with cardlists and synergy scores."""
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
    async def test_inclusion_is_percentage_not_raw_count(self):
        """Inclusion field is computed as percentage from num_decks/potential_decks.

        The EDHREC API returns inclusion as a raw deck count (identical to
        num_decks), not a percentage. The service must compute the percentage
        at parse time so consumers can use it directly.
        """
        fixture = _load_fixture("commander_muldrotha.json")
        respx.get(f"{BASE_URL}/pages/commanders/muldrotha-the-gravetide.json").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with EDHRECClient(base_url=BASE_URL) as client:
            result = await client.commander_top_cards("Muldrotha, the Gravetide")

        high_synergy = next(cl for cl in result.cardlists if cl.tag == "highsynergycards")
        spore_frog = high_synergy.cardviews[0]
        # Fixture: num_decks=13416, potential_decks=22329 → 60%
        assert spore_frog.inclusion == 60
        assert spore_frog.num_decks == 13416
        assert spore_frog.potential_decks == 22329

        # "New Cards" have different potential_decks than total_decks
        new_cards = next(cl for cl in result.cardlists if cl.tag == "newcards")
        twilight_diviner = new_cards.cardviews[0]
        # Fixture: num_decks=770, potential_decks=4119 → 19%
        assert twilight_diviner.inclusion == 19
        assert twilight_diviner.num_decks == 770

    @respx.mock
    async def test_category_filter(self):
        """Category filter narrows results to only the specified card type."""
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
        """Category filter with no matching cardlist returns empty results."""
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
        """404 response raises CommanderNotFoundError."""
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
    """Card synergy score lookup for a specific commander."""

    @respx.mock
    async def test_finds_card_in_commander(self):
        """Known card returns its EDHRECCard with synergy score and deck count."""
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
        """Unknown card returns None instead of raising."""
        fixture = _load_fixture("commander_muldrotha.json")
        respx.get(f"{BASE_URL}/pages/commanders/muldrotha-the-gravetide.json").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with EDHRECClient(base_url=BASE_URL) as client:
            result = await client.card_synergy(
                "Totally Nonexistent Card", "Muldrotha, the Gravetide"
            )

        assert result is None

    @respx.mock
    async def test_matches_unicode_name_without_diacritics(self):
        """Searching 'Gloin' matches 'Glóin' in EDHREC data (Bug 6)."""
        fixture = _load_fixture("commander_muldrotha.json")
        # Inject a card with a diacritical name into the fixture
        fixture["container"]["json_dict"]["cardlists"][0]["cardviews"].append(
            {
                "name": "Glóin, Dwarf Emissary",
                "sanitized": "gloin-dwarf-emissary",
                "synergy": 0.44,
                "inclusion": 7849,
                "num_decks": 7849,
                "potential_decks": 22329,
            }
        )
        respx.get(f"{BASE_URL}/pages/commanders/muldrotha-the-gravetide.json").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with EDHRECClient(base_url=BASE_URL) as client:
            result = await client.card_synergy("Gloin, Dwarf Emissary", "Muldrotha, the Gravetide")

        assert result is not None
        assert result.name == "Glóin, Dwarf Emissary"

    @respx.mock
    async def test_matches_front_face_without_dfc_suffix(self):
        """Searching 'Pinnacle Monk // Mystic Peak' matches 'Pinnacle Monk' (Bug 7)."""
        fixture = _load_fixture("commander_muldrotha.json")
        fixture["container"]["json_dict"]["cardlists"][0]["cardviews"].append(
            {
                "name": "Pinnacle Monk",
                "sanitized": "pinnacle-monk",
                "synergy": 0.13,
                "inclusion": 3710,
                "num_decks": 3710,
                "potential_decks": 22329,
            }
        )
        respx.get(f"{BASE_URL}/pages/commanders/muldrotha-the-gravetide.json").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with EDHRECClient(base_url=BASE_URL) as client:
            result = await client.card_synergy(
                "Pinnacle Monk // Mystic Peak", "Muldrotha, the Gravetide"
            )

        assert result is not None
        assert result.name == "Pinnacle Monk"


class TestServerErrors:
    """EDHREC API server error handling."""

    @respx.mock
    async def test_500_raises_edhrec_error(self):
        """500 response from EDHREC raises EDHRECError."""
        respx.get(f"{BASE_URL}/pages/commanders/muldrotha-the-gravetide.json").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        async with EDHRECClient(base_url=BASE_URL) as client:
            with pytest.raises(EDHRECError):
                await client.commander_top_cards("Muldrotha, the Gravetide")
