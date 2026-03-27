"""Tests for the Scryfall bulk data MCP provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import Client

from mtg_mcp_server.providers.scryfall_bulk import scryfall_bulk_mcp
from mtg_mcp_server.services.scryfall_bulk import ScryfallBulkError
from mtg_mcp_server.types import Card, CardPrices


def _make_card(
    *,
    name: str = "Sol Ring",
    mana_cost: str | None = "{1}",
    type_line: str = "Artifact",
    oracle_text: str | None = "{T}: Add {C}{C}.",
    colors: list[str] | None = None,
    color_identity: list[str] | None = None,
    power: str | None = None,
    toughness: str | None = None,
    set_code: str = "cmd",
    rarity: str = "uncommon",
    prices: CardPrices | None = None,
    legalities: dict[str, str] | None = None,
    edhrec_rank: int | None = 1,
    keywords: list[str] | None = None,
) -> Card:
    """Build a Card instance for testing."""
    return Card(
        id="test-id",
        name=name,
        mana_cost=mana_cost,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=colors or [],
        color_identity=color_identity or [],
        power=power,
        toughness=toughness,
        set_code=set_code,
        rarity=rarity,
        prices=prices or CardPrices(usd="0.50", usd_foil="1.00", eur="0.40"),
        legalities=legalities or {"commander": "legal", "modern": "legal"},
        edhrec_rank=edhrec_rank,
        keywords=keywords or [],
    )


def _mock_client() -> AsyncMock:
    """Create an AsyncMock matching the ScryfallBulkClient interface."""
    mock = AsyncMock()
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=False)
    mock.start_background_refresh = lambda: None
    mock.get_card = AsyncMock(return_value=None)
    mock.search_cards = AsyncMock(return_value=[])
    mock.search_by_type = AsyncMock(return_value=[])
    mock.search_by_text = AsyncMock(return_value=[])
    return mock


@pytest.fixture
async def client():
    """In-memory MCP client connected to the Scryfall bulk data provider.

    Patches the ScryfallBulkClient constructor so no real downloads happen.
    """
    mock = _mock_client()

    with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
        async with Client(transport=scryfall_bulk_mcp) as c:
            yield c


@pytest.fixture
def mock_service() -> AsyncMock:
    """Provide direct access to the mock service for test setup."""
    return _mock_client()


@pytest.fixture
async def client_with_data(mock_service: AsyncMock):
    """In-memory MCP client with pre-configured mock data."""
    sol_ring = _make_card()
    muldrotha = _make_card(
        name="Muldrotha, the Gravetide",
        mana_cost="{3}{B}{G}{U}",
        type_line="Legendary Creature \u2014 Elemental Avatar",
        oracle_text="During each of your turns, you may play a land and cast a permanent spell of each permanent type from your graveyard.",
        colors=["B", "G", "U"],
        color_identity=["B", "G", "U"],
        power="6",
        toughness="6",
        rarity="mythic",
        edhrec_rank=245,
        legalities={"commander": "legal", "modern": "legal", "standard": "not_legal"},
    )

    async def mock_get_card(name: str) -> Card | None:
        lookup = {
            "sol ring": sol_ring,
            "muldrotha, the gravetide": muldrotha,
        }
        return lookup.get(name.lower())

    async def mock_search_cards(query: str, limit: int = 20) -> list[Card]:
        cards = [sol_ring, muldrotha]
        results = [c for c in cards if query.lower() in c.name.lower()]
        return results[:limit]

    async def mock_search_by_type(type_query: str, limit: int = 20) -> list[Card]:
        cards = [sol_ring, muldrotha]
        results = [c for c in cards if type_query.lower() in c.type_line.lower()]
        return results[:limit]

    async def mock_search_by_text(text_query: str, limit: int = 20) -> list[Card]:
        cards = [sol_ring, muldrotha]
        results = [
            c for c in cards if c.oracle_text and text_query.lower() in c.oracle_text.lower()
        ]
        return results[:limit]

    mock_service.get_card = AsyncMock(side_effect=mock_get_card)
    mock_service.search_cards = AsyncMock(side_effect=mock_search_cards)
    mock_service.search_by_type = AsyncMock(side_effect=mock_search_by_type)
    mock_service.search_by_text = AsyncMock(side_effect=mock_search_by_text)

    with patch(
        "mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock_service
    ):
        async with Client(transport=scryfall_bulk_mcp) as c:
            yield c


class TestToolRegistration:
    """Scryfall bulk data provider tool registration."""

    async def test_all_tools_registered(self, client: Client):
        """Both Scryfall bulk data tools are registered on the provider."""
        tools = await client.list_tools()
        tool_names = {t.name for t in tools}
        assert tool_names == {"card_lookup", "card_search"}


class TestCardLookup:
    """Scryfall bulk card_lookup tool behavior."""

    async def test_exact_lookup(self, client_with_data: Client):
        """card_lookup returns full card data for an exact name match."""
        result = await client_with_data.call_tool("card_lookup", {"name": "Sol Ring"})
        text = result.content[0].text
        assert "Sol Ring" in text
        assert "{1}" in text
        assert "Artifact" in text
        assert "{T}: Add {C}{C}." in text
        assert "Data: Scryfall bulk data" in text

    async def test_card_with_prices_and_legalities(self, client_with_data: Client):
        """card_lookup shows prices, legalities, and EDHREC rank."""
        result = await client_with_data.call_tool("card_lookup", {"name": "Sol Ring"})
        text = result.content[0].text
        assert "$0.50" in text
        assert "EDHREC Rank" in text
        assert "commander" in text.lower()

    async def test_legendary_creature(self, client_with_data: Client):
        """card_lookup returns power/toughness for creatures."""
        result = await client_with_data.call_tool(
            "card_lookup", {"name": "Muldrotha, the Gravetide"}
        )
        text = result.content[0].text
        assert "Muldrotha, the Gravetide" in text
        assert "6/6" in text
        assert "Legendary Creature" in text

    async def test_case_insensitive(self, client_with_data: Client):
        """card_lookup matches card names case-insensitively."""
        result = await client_with_data.call_tool("card_lookup", {"name": "sol ring"})
        text = result.content[0].text
        assert "Sol Ring" in text

    async def test_not_found_returns_error(self, client_with_data: Client):
        """card_lookup returns an error response for nonexistent cards."""
        result = await client_with_data.call_tool(
            "card_lookup", {"name": "Nonexistent Card"}, raise_on_error=False
        )
        assert result.is_error
        text = result.content[0].text
        assert "not found" in text.lower()

    async def test_service_error(self):
        """card_lookup surfaces service errors as ToolError."""
        mock = _mock_client()
        mock.get_card = AsyncMock(side_effect=ScryfallBulkError("Download failed"))

        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as c:
                result = await c.call_tool(
                    "card_lookup", {"name": "Sol Ring"}, raise_on_error=False
                )
                assert result.is_error
                text = result.content[0].text
                assert "scryfall bulk data error" in text.lower()


class TestCardSearch:
    """Scryfall bulk card_search tool behavior."""

    async def test_search_by_name(self, client_with_data: Client):
        """card_search finds cards by substring match on name."""
        result = await client_with_data.call_tool("card_search", {"query": "Sol"})
        text = result.content[0].text
        assert "Sol Ring" in text
        assert "Found" in text

    async def test_search_by_type(self, client_with_data: Client):
        """card_search finds cards by type line when search_field is 'type'."""
        result = await client_with_data.call_tool(
            "card_search", {"query": "Creature", "search_field": "type"}
        )
        text = result.content[0].text
        assert "Muldrotha" in text

    async def test_search_by_text(self, client_with_data: Client):
        """card_search finds cards by oracle text when search_field is 'text'."""
        result = await client_with_data.call_tool(
            "card_search", {"query": "graveyard", "search_field": "text"}
        )
        text = result.content[0].text
        assert "Muldrotha" in text

    async def test_search_no_results(self, client_with_data: Client):
        """card_search returns an error response when no cards match the query."""
        result = await client_with_data.call_tool(
            "card_search", {"query": "xyzzynonexistent"}, raise_on_error=False
        )
        assert result.is_error
        text = result.content[0].text
        assert "no cards found" in text.lower()

    async def test_search_with_limit(self, client_with_data: Client):
        """card_search respects the limit parameter for result count."""
        result = await client_with_data.call_tool(
            "card_search", {"query": "", "search_field": "type", "limit": 1}
        )
        text = result.content[0].text
        assert "Found 1" in text

    async def test_invalid_search_field(self, client_with_data: Client):
        """card_search returns a validation error for unsupported search_field values."""
        result = await client_with_data.call_tool(
            "card_search",
            {"query": "test", "search_field": "invalid"},
            raise_on_error=False,
        )
        assert result.is_error
        text = result.content[0].text
        # Pydantic validates Literal type before our code runs
        assert "'name'" in text or "literal_error" in text

    async def test_search_attribution(self, client_with_data: Client):
        """card_search includes Scryfall bulk data attribution."""
        result = await client_with_data.call_tool("card_search", {"query": "Sol"})
        text = result.content[0].text
        assert "Data: Scryfall bulk data" in text
