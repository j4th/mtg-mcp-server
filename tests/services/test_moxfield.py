"""Tests for the Moxfield service client."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from mtg_mcp_server.services.moxfield import DeckNotFoundError, MoxfieldClient, MoxfieldError
from mtg_mcp_server.types import MoxfieldDeck, MoxfieldDecklist

FIXTURES = Path(__file__).parent.parent / "fixtures" / "moxfield"
BASE_URL = "https://api2.moxfield.com"


@pytest.fixture(autouse=True)
def _clear_moxfield_cache():
    """Clear MoxfieldClient cache before every test to prevent leakage."""
    MoxfieldClient._deck_cache.clear()


def _load_fixture(name: str) -> dict:
    """Load a Moxfield JSON fixture by filename."""
    return json.loads((FIXTURES / name).read_text())


class TestExtractDeckId:
    """Test deck ID extraction from URLs and raw IDs."""

    def test_raw_deck_id(self):
        """Raw deck ID strings pass through unchanged."""
        assert MoxfieldClient.extract_deck_id("abc123") == "abc123"

    def test_full_url(self):
        """Full Moxfield URL extracts the deck ID segment."""
        url = "https://www.moxfield.com/decks/rGOl_LYVa0KJ_K0vLUS83A"
        assert MoxfieldClient.extract_deck_id(url) == "rGOl_LYVa0KJ_K0vLUS83A"

    def test_url_with_trailing_slash(self):
        """Trailing slash is stripped before extracting the deck ID."""
        url = "https://www.moxfield.com/decks/rGOl_LYVa0KJ_K0vLUS83A/"
        assert MoxfieldClient.extract_deck_id(url) == "rGOl_LYVa0KJ_K0vLUS83A"

    def test_url_with_query_params(self):
        """Query parameters are stripped before extracting the deck ID."""
        url = "https://www.moxfield.com/decks/rGOl_LYVa0KJ_K0vLUS83A?view=edit"
        assert MoxfieldClient.extract_deck_id(url) == "rGOl_LYVa0KJ_K0vLUS83A"

    def test_non_moxfield_url_passes_through(self):
        """Non-Moxfield URLs pass through as-is (treated as raw IDs)."""
        url = "https://archidekt.com/decks/12345"
        assert MoxfieldClient.extract_deck_id(url) == url


class TestGetDeck:
    """Deck retrieval and parsing."""

    @respx.mock
    async def test_returns_full_decklist(self):
        """Fixture parses into MoxfieldDecklist with correct commanders and mainboard."""
        fixture = _load_fixture("deck_commander.json")
        respx.get(f"{BASE_URL}/v3/decks/all/abc123").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with MoxfieldClient(base_url=BASE_URL) as client:
            result = await client.get_deck("abc123")

        assert isinstance(result, MoxfieldDecklist)
        # Commander board
        assert len(result.commanders) == 1
        assert result.commanders[0].name == "Muldrotha, the Gravetide"
        assert result.commanders[0].quantity == 1
        # Mainboard
        assert len(result.mainboard) == 3
        mainboard_names = [c.name for c in result.mainboard]
        assert "Sol Ring" in mainboard_names
        assert "Spore Frog" in mainboard_names
        # Sideboard
        assert len(result.sideboard) == 2

    @respx.mock
    async def test_deck_metadata_parsed(self):
        """Deck metadata (name, format, author, dates) is extracted correctly."""
        fixture = _load_fixture("deck_commander.json")
        respx.get(f"{BASE_URL}/v3/decks/all/abc123").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with MoxfieldClient(base_url=BASE_URL) as client:
            result = await client.get_deck("abc123")

        deck = result.deck
        assert isinstance(deck, MoxfieldDeck)
        assert deck.name == "Muldrotha Self-Mill"
        assert deck.format == "commander"
        assert deck.author == "mtgplayer42"
        assert deck.public_url == "https://www.moxfield.com/decks/abc123"
        assert deck.created_at == "2025-01-15T10:30:00Z"
        assert deck.updated_at == "2025-03-20T14:45:00Z"

    @respx.mock
    async def test_deck_not_found_raises(self):
        """404 response raises DeckNotFoundError."""
        respx.get(f"{BASE_URL}/v3/decks/all/nonexistent").mock(
            return_value=httpx.Response(404, text="Not Found")
        )
        async with MoxfieldClient(base_url=BASE_URL) as client:
            with pytest.raises(DeckNotFoundError, match="nonexistent"):
                await client.get_deck("nonexistent")

    @respx.mock
    async def test_server_error_raises(self):
        """500 response raises MoxfieldError."""
        respx.get(f"{BASE_URL}/v3/decks/all/some-deck").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        async with MoxfieldClient(base_url=BASE_URL) as client:
            with pytest.raises(MoxfieldError):
                await client.get_deck("some-deck")

    @respx.mock
    async def test_403_raises_deck_not_found(self):
        """403 response (private deck) raises DeckNotFoundError."""
        respx.get(f"{BASE_URL}/v3/decks/all/private-deck").mock(
            return_value=httpx.Response(403, text="Forbidden")
        )
        async with MoxfieldClient(base_url=BASE_URL) as client:
            with pytest.raises(DeckNotFoundError, match="private-deck"):
                await client.get_deck("private-deck")

    @respx.mock
    async def test_invalid_json_raises(self):
        """200 with non-JSON body raises MoxfieldError."""
        respx.get(f"{BASE_URL}/v3/decks/all/broken").mock(
            return_value=httpx.Response(200, content=b"<html>Not JSON</html>")
        )
        async with MoxfieldClient(base_url=BASE_URL) as client:
            with pytest.raises(MoxfieldError, match="invalid JSON"):
                await client.get_deck("broken")

    @respx.mock
    async def test_non_dict_response_raises(self):
        """200 with a JSON array instead of object raises MoxfieldError."""
        respx.get(f"{BASE_URL}/v3/decks/all/weird").mock(
            return_value=httpx.Response(200, json=["not", "a", "dict"])
        )
        async with MoxfieldClient(base_url=BASE_URL) as client:
            with pytest.raises(MoxfieldError, match="unexpected data format"):
                await client.get_deck("weird")

    @respx.mock
    async def test_defensive_missing_boards(self):
        """Missing `boards` key results in empty card lists."""
        fixture = {"id": "test", "name": "No boards", "format": "commander"}
        respx.get(f"{BASE_URL}/v3/decks/all/test-id").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with MoxfieldClient(base_url=BASE_URL) as client:
            result = await client.get_deck("test-id")

        assert result.commanders == []
        assert result.mainboard == []
        assert result.sideboard == []
        assert result.companions == []

    @respx.mock
    async def test_defensive_malformed_card_entry(self):
        """Card entries missing `card` or `quantity` keys are skipped gracefully."""
        fixture = {
            "id": "test",
            "name": "Malformed",
            "format": "commander",
            "boards": {
                "mainboard": {
                    "count": 3,
                    "cards": {
                        "good-card": {
                            "quantity": 1,
                            "card": {"name": "Sol Ring"},
                        },
                        "missing-card-key": {
                            "quantity": 1,
                            # no "card" key
                        },
                        "missing-quantity": {
                            # no "quantity" key
                            "card": {"name": "Spore Frog"},
                        },
                    },
                }
            },
        }
        respx.get(f"{BASE_URL}/v3/decks/all/test-id").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with MoxfieldClient(base_url=BASE_URL) as client:
            result = await client.get_deck("test-id")

        # Only the well-formed entry should be parsed
        assert len(result.mainboard) == 1
        assert result.mainboard[0].name == "Sol Ring"

    @respx.mock
    async def test_defensive_zero_and_bool_quantity_skipped(self):
        """Entries with quantity=0, quantity=False, or negative quantity are skipped."""
        fixture = {
            "id": "test",
            "name": "Bad quantities",
            "format": "commander",
            "boards": {
                "mainboard": {
                    "count": 4,
                    "cards": {
                        "good": {"quantity": 1, "card": {"name": "Sol Ring"}},
                        "zero-qty": {"quantity": 0, "card": {"name": "Bad Zero"}},
                        "bool-qty": {"quantity": False, "card": {"name": "Bad Bool"}},
                        "neg-qty": {"quantity": -1, "card": {"name": "Bad Neg"}},
                    },
                }
            },
        }
        respx.get(f"{BASE_URL}/v3/decks/all/test-id").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with MoxfieldClient(base_url=BASE_URL) as client:
            result = await client.get_deck("test-id")

        assert len(result.mainboard) == 1
        assert result.mainboard[0].name == "Sol Ring"

    @respx.mock
    async def test_mainboard_cards_sorted_alphabetically(self):
        """Cards within a board are sorted alphabetically by name."""
        fixture = _load_fixture("deck_commander.json")
        respx.get(f"{BASE_URL}/v3/decks/all/abc123").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with MoxfieldClient(base_url=BASE_URL) as client:
            result = await client.get_deck("abc123")

        mainboard_names = [c.name for c in result.mainboard]
        assert mainboard_names == sorted(mainboard_names)

    @respx.mock
    async def test_url_input_extracts_deck_id(self):
        """get_deck accepts full Moxfield URLs and extracts the ID."""
        fixture = _load_fixture("deck_commander.json")
        respx.get(f"{BASE_URL}/v3/decks/all/abc123").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with MoxfieldClient(base_url=BASE_URL) as client:
            result = await client.get_deck("https://www.moxfield.com/decks/abc123")

        assert result.deck.name == "Muldrotha Self-Mill"


class TestGetDeckInfo:
    """Deck info (metadata-only) retrieval."""

    @respx.mock
    async def test_returns_deck_metadata(self):
        """Returns MoxfieldDeck from the underlying get_deck call."""
        fixture = _load_fixture("deck_commander.json")
        respx.get(f"{BASE_URL}/v3/decks/all/abc123").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with MoxfieldClient(base_url=BASE_URL) as client:
            result = await client.get_deck_info("abc123")

        assert isinstance(result, MoxfieldDeck)
        assert result.name == "Muldrotha Self-Mill"
        assert result.format == "commander"

    @respx.mock
    async def test_deck_not_found_raises(self):
        """404 propagates through get_deck_info as DeckNotFoundError."""
        respx.get(f"{BASE_URL}/v3/decks/all/nonexistent").mock(
            return_value=httpx.Response(404, text="Not Found")
        )
        async with MoxfieldClient(base_url=BASE_URL) as client:
            with pytest.raises(DeckNotFoundError):
                await client.get_deck_info("nonexistent")


class TestCaching:
    """TTL cache behavior for get_deck."""

    @respx.mock
    async def test_second_call_returns_cached(self):
        """Second call for the same deck ID returns cached result without a second HTTP call."""
        fixture = _load_fixture("deck_commander.json")
        route = respx.get(f"{BASE_URL}/v3/decks/all/abc123").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with MoxfieldClient(base_url=BASE_URL) as client:
            result1 = await client.get_deck("abc123")
            result2 = await client.get_deck("abc123")

        assert route.call_count == 1
        assert result1.deck.name == result2.deck.name

    @respx.mock
    async def test_different_deck_ids_cached_separately(self):
        """Different deck IDs produce separate cache entries."""
        fixture = _load_fixture("deck_commander.json")
        route1 = respx.get(f"{BASE_URL}/v3/decks/all/deck-a").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        route2 = respx.get(f"{BASE_URL}/v3/decks/all/deck-b").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with MoxfieldClient(base_url=BASE_URL) as client:
            await client.get_deck("deck-a")
            await client.get_deck("deck-b")

        assert route1.call_count == 1
        assert route2.call_count == 1

    @respx.mock
    async def test_url_and_raw_id_share_cache_entry(self):
        """A URL and its extracted raw ID share the same cache entry."""
        fixture = _load_fixture("deck_commander.json")
        route = respx.get(f"{BASE_URL}/v3/decks/all/abc123").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with MoxfieldClient(base_url=BASE_URL) as client:
            await client.get_deck("https://www.moxfield.com/decks/abc123")
            await client.get_deck("abc123")

        assert route.call_count == 1


class TestDecklistFormatCompatibility:
    """Verify decklist output round-trips through the decklist parser."""

    @respx.mock
    async def test_output_produces_valid_decklist_lines(self):
        """Every MoxfieldCard produces a valid 'Nx Card Name' line for parse_decklist."""
        from mtg_mcp_server.utils.decklist import parse_decklist

        fixture = _load_fixture("deck_commander.json")
        respx.get(f"{BASE_URL}/v3/decks/all/abc123").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with MoxfieldClient(base_url=BASE_URL) as client:
            result = await client.get_deck("abc123")

        all_cards = result.commanders + result.mainboard + result.sideboard + result.companions
        lines = [f"{card.quantity}x {card.name}" for card in all_cards]
        parsed = parse_decklist(lines)
        assert len(parsed) == len(all_cards)
        for (qty, name), card in zip(parsed, all_cards, strict=True):
            assert qty == card.quantity
            assert name == card.name
