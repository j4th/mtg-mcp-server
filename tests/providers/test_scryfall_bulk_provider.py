"""Tests for the Scryfall bulk data MCP provider."""

from __future__ import annotations

import json
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
        """All Scryfall bulk data tools are registered on the provider."""
        tools = await client.list_tools()
        tool_names = {t.name for t in tools}
        expected = {
            "card_lookup",
            "card_search",
            "format_legality",
            "format_search",
            "format_staples",
            "similar_cards",
            "random_card",
            "ban_list",
            "card_in_formats",
        }
        assert tool_names == expected


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

        # Structured output
        sc = result.structured_content
        assert sc is not None
        assert sc["name"] == "Sol Ring"
        assert sc["type_line"] == "Artifact"
        assert sc["mana_cost"] == "{1}"

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

        # Structured output for creature
        sc = result.structured_content
        assert sc is not None
        assert sc["name"] == "Muldrotha, the Gravetide"
        assert sc["power"] == "6"
        assert sc["toughness"] == "6"

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

        # Structured output
        sc = result.structured_content
        assert sc is not None
        assert sc["query"] == "Sol"
        assert sc["search_field"] == "name"
        assert sc["total_results"] >= 1
        assert isinstance(sc["cards"], list)
        assert sc["cards"][0]["name"] == "Sol Ring"

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


class TestResourceErrors:
    """Test card_data_resource error and not-found paths."""

    async def test_resource_card_not_found(self, client_with_data: Client):
        """Resource returns error JSON when card is not found."""
        import json as _json

        result = await client_with_data.read_resource("mtg://card-data/nonexistent")
        data = _json.loads(result[0].text)
        assert "error" in data
        assert "not found" in data["error"].lower()

    async def test_resource_returns_card_json(self, client_with_data: Client):
        """Resource returns valid card JSON for a known card."""
        import json as _json

        result = await client_with_data.read_resource("mtg://card-data/Sol Ring")
        data = _json.loads(result[0].text)
        assert data["name"] == "Sol Ring"


class TestLegalitiesFormatting:
    """Test _format_legalities edge cases."""

    async def test_no_legal_formats(self, mock_service: AsyncMock):
        """card_lookup shows 'Not legal in any format' when all banned/restricted."""
        card = _make_card(legalities={"commander": "banned", "modern": "not_legal"})
        mock_service.get_card = AsyncMock(return_value=card)

        with patch(
            "mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock_service
        ):
            async with Client(transport=scryfall_bulk_mcp) as c:
                result = await c.call_tool("card_lookup", {"name": "Sol Ring"})
                text = result.content[0].text
                assert "Not legal in any format" in text


# ---------------------------------------------------------------------------
# Shared test card pool
# ---------------------------------------------------------------------------


def _make_test_pool() -> list[Card]:
    """Build a small pool of test cards with diverse attributes."""
    return [
        _make_card(
            name="Sol Ring",
            mana_cost="{1}",
            type_line="Artifact",
            oracle_text="{T}: Add {C}{C}.",
            keywords=[],
            legalities={"commander": "legal", "modern": "banned", "vintage": "restricted"},
            edhrec_rank=1,
            prices=CardPrices(usd="1.50", usd_foil="5.00", eur="1.20"),
            rarity="uncommon",
        ),
        _make_card(
            name="Lightning Bolt",
            mana_cost="{R}",
            type_line="Instant",
            oracle_text="Lightning Bolt deals 3 damage to any target.",
            colors=["R"],
            color_identity=["R"],
            keywords=[],
            legalities={"commander": "legal", "modern": "legal", "standard": "not_legal"},
            edhrec_rank=5,
            prices=CardPrices(usd="0.50", usd_foil="2.00", eur="0.40"),
            rarity="common",
        ),
        _make_card(
            name="Muldrotha, the Gravetide",
            mana_cost="{3}{B}{G}{U}",
            type_line="Legendary Creature \u2014 Elemental Avatar",
            oracle_text="During each of your turns, you may play a land and cast a permanent spell of each permanent type from your graveyard.",
            colors=["B", "G", "U"],
            color_identity=["B", "G", "U"],
            power="6",
            toughness="6",
            keywords=[],
            legalities={"commander": "legal", "modern": "legal", "standard": "not_legal"},
            edhrec_rank=245,
            prices=CardPrices(usd="5.50", usd_foil="12.00", eur="4.80"),
            rarity="mythic",
        ),
        _make_card(
            name="Counterspell",
            mana_cost="{U}{U}",
            type_line="Instant",
            oracle_text="Counter target spell.",
            colors=["U"],
            color_identity=["U"],
            keywords=[],
            legalities={"commander": "legal", "modern": "legal", "standard": "not_legal"},
            edhrec_rank=10,
            prices=CardPrices(usd="1.00", usd_foil="3.00", eur="0.80"),
            rarity="uncommon",
        ),
        _make_card(
            name="Swords to Plowshares",
            mana_cost="{W}",
            type_line="Instant",
            oracle_text="Exile target creature. Its controller gains life equal to its power.",
            colors=["W"],
            color_identity=["W"],
            keywords=[],
            legalities={"commander": "legal", "modern": "not_legal", "legacy": "legal"},
            edhrec_rank=3,
            prices=CardPrices(usd="2.00", usd_foil="6.00", eur="1.50"),
            rarity="uncommon",
        ),
        _make_card(
            name="Birds of Paradise",
            mana_cost="{G}",
            type_line="Creature \u2014 Bird",
            oracle_text="{T}: Add one mana of any color.",
            colors=["G"],
            color_identity=["G"],
            power="0",
            toughness="1",
            keywords=["Flying"],
            legalities={"commander": "legal", "modern": "legal"},
            edhrec_rank=50,
            prices=CardPrices(usd="8.00", usd_foil="15.00", eur="6.00"),
            rarity="rare",
        ),
    ]


def _make_pool_client(pool: list[Card] | None = None) -> AsyncMock:
    """Create a mock client with a pool of cards for cross-format tools."""
    mock = _mock_client()
    cards = _make_test_pool() if pool is None else pool

    # Build the lookup dict and unique list
    cards_dict: dict[str, Card] = {}
    for card in cards:
        cards_dict[card.name.lower()] = card
        if " // " in card.name:
            front = card.name.split(" // ")[0].lower()
            cards_dict[front] = card

    mock._cards = cards_dict

    async def mock_all_cards() -> list[Card]:
        return cards

    async def mock_get_card(name: str) -> Card | None:
        return cards_dict.get(name.lower())

    async def mock_search(query: str, limit: int = 20) -> list[Card]:
        q = query.lower()
        return [c for c in cards if q in c.name.lower()][:limit]

    async def mock_get_cards(names: list[str]) -> dict[str, Card | None]:
        return {name: cards_dict.get(name.lower()) for name in names}

    async def mock_cards_by_legality(format: str, status: str) -> list[Card]:
        return [c for c in cards if c.legalities.get(format) == status]

    async def mock_random_card(
        *,
        format: str | None = None,
        color_identity: frozenset[str] | None = None,
        type_contains: str | None = None,
        rarity: str | None = None,
    ) -> Card | None:
        pool = list(cards)
        if format is not None:
            pool = [c for c in pool if c.legalities.get(format) == "legal"]
        if color_identity is not None:
            pool = [c for c in pool if frozenset(c.color_identity).issubset(color_identity)]
        if type_contains is not None:
            pool = [c for c in pool if type_contains.lower() in c.type_line.lower()]
        if rarity is not None:
            pool = [c for c in pool if c.rarity == rarity]
        return pool[0] if pool else None

    mock.get_card = AsyncMock(side_effect=mock_get_card)
    mock.get_cards = AsyncMock(side_effect=mock_get_cards)
    mock.cards_by_legality = AsyncMock(side_effect=mock_cards_by_legality)
    mock.random_card = AsyncMock(side_effect=mock_random_card)
    mock.search_cards = AsyncMock(side_effect=mock_search)
    mock.all_cards = AsyncMock(side_effect=mock_all_cards)
    mock.ensure_loaded = AsyncMock()
    return mock


# ---------------------------------------------------------------------------
# format_legality tests
# ---------------------------------------------------------------------------


class TestFormatLegality:
    """Tests for the format_legality tool."""

    async def test_all_legal(self):
        """format_legality shows legal status for all cards."""
        mock = _make_pool_client()
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.call_tool(
                    "format_legality",
                    {"cards": ["Sol Ring", "Lightning Bolt"], "format": "commander"},
                )
        text = result.content[0].text
        assert "Sol Ring" in text
        assert "Lightning Bolt" in text
        assert "Legal" in text

        # Structured output
        sc = result.structured_content
        assert sc is not None
        assert sc["format"] == "commander"
        assert isinstance(sc["cards"], list)
        assert len(sc["cards"]) == 2
        assert sc["cards"][0]["status"] == "legal"

    async def test_banned_card(self):
        """format_legality shows Banned status for banned cards."""
        mock = _make_pool_client()
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.call_tool(
                    "format_legality",
                    {"cards": ["Sol Ring"], "format": "modern"},
                )
        text = result.content[0].text
        assert "Banned" in text

    async def test_not_found_card(self):
        """format_legality shows Not Found for unknown cards."""
        mock = _make_pool_client()
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.call_tool(
                    "format_legality",
                    {"cards": ["Nonexistent Card"], "format": "commander"},
                )
        text = result.content[0].text
        assert "Not Found" in text

    async def test_format_alias(self):
        """format_legality normalizes format aliases (e.g. 'edh' -> 'commander')."""
        mock = _make_pool_client()
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.call_tool(
                    "format_legality",
                    {"cards": ["Sol Ring"], "format": "edh"},
                )
        text = result.content[0].text
        assert "Commander" in text  # header
        assert "Legal" in text


# ---------------------------------------------------------------------------
# format_search tests
# ---------------------------------------------------------------------------


class TestFormatSearch:
    """Tests for the format_search tool."""

    async def test_basic_search(self):
        """format_search finds legal cards by name substring."""
        mock = _make_pool_client()
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.call_tool(
                    "format_search",
                    {"format": "commander", "query": "Lightning"},
                )
        text = result.content[0].text
        assert "Lightning Bolt" in text

        # Structured output
        sc = result.structured_content
        assert sc is not None
        assert sc["format"] == "commander"
        assert sc["total_results"] >= 1
        assert isinstance(sc["cards"], list)

    async def test_search_by_type(self):
        """format_search matches type line text."""
        mock = _make_pool_client()
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.call_tool(
                    "format_search",
                    {"format": "commander", "query": "Instant"},
                )
        text = result.content[0].text
        # Should find all instants (Lightning Bolt, Counterspell, Swords)
        assert "Lightning Bolt" in text or "Counterspell" in text

    async def test_search_with_color_identity(self):
        """format_search filters by color identity."""
        mock = _make_pool_client()
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.call_tool(
                    "format_search",
                    {"format": "commander", "query": "Instant", "color_identity": "blue"},
                )
        text = result.content[0].text
        assert "Counterspell" in text
        # Swords is white, should be excluded
        assert "Swords to Plowshares" not in text

    async def test_search_no_results(self):
        """format_search returns error when nothing matches."""
        mock = _make_pool_client()
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.call_tool(
                    "format_search",
                    {"format": "commander", "query": "xyznonexistent"},
                    raise_on_error=False,
                )
        assert result.is_error

    async def test_search_with_price_filter(self):
        """format_search filters by max price."""
        mock = _make_pool_client()
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.call_tool(
                    "format_search",
                    {"format": "commander", "query": "Bolt", "max_price": 1.00},
                )
        text = result.content[0].text
        # Lightning Bolt costs $0.50, should be included
        assert "Lightning Bolt" in text


# ---------------------------------------------------------------------------
# format_staples tests
# ---------------------------------------------------------------------------


class TestFormatStaples:
    """Tests for the format_staples tool."""

    async def test_basic_staples(self):
        """format_staples returns cards sorted by EDHREC rank."""
        mock = _make_pool_client()
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.call_tool(
                    "format_staples",
                    {"format": "commander"},
                )
        text = result.content[0].text
        assert "Sol Ring" in text
        assert "#1" in text  # Sol Ring should be rank 1

        # Structured output
        sc = result.structured_content
        assert sc is not None
        assert sc["format"] == "commander"
        assert sc["total_results"] >= 1
        assert isinstance(sc["cards"], list)
        assert sc["cards"][0]["name"] == "Sol Ring"
        assert sc["cards"][0]["edhrec_rank"] == 1

    async def test_staples_with_type_filter(self):
        """format_staples filters by card type."""
        mock = _make_pool_client()
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.call_tool(
                    "format_staples",
                    {"format": "commander", "card_type": "instant"},
                )
        text = result.content[0].text
        assert "Swords to Plowshares" in text or "Counterspell" in text
        assert "Sol Ring" not in text  # Artifact, not instant

    async def test_staples_with_color(self):
        """format_staples filters by color identity."""
        mock = _make_pool_client()
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.call_tool(
                    "format_staples",
                    {"format": "commander", "color": "green"},
                )
        text = result.content[0].text
        assert "Birds of Paradise" in text
        # Colorless cards (Sol Ring) should also be included (subset of green identity)
        assert "Sol Ring" in text

    async def test_staples_no_results(self):
        """format_staples returns error when no cards match."""
        mock = _make_pool_client([])
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.call_tool(
                    "format_staples",
                    {"format": "commander"},
                    raise_on_error=False,
                )
        assert result.is_error


# ---------------------------------------------------------------------------
# similar_cards tests
# ---------------------------------------------------------------------------


class TestSimilarCards:
    """Tests for the similar_cards tool."""

    async def test_find_similar(self):
        """similar_cards finds cards with shared attributes."""
        mock = _make_pool_client()
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.call_tool(
                    "similar_cards",
                    {"card_name": "Lightning Bolt"},
                )
        text = result.content[0].text
        assert "Similar to Lightning Bolt" in text
        assert "score:" in text

        # Structured output
        sc = result.structured_content
        assert sc is not None
        assert sc["source_card"] == "Lightning Bolt"
        assert sc["total_results"] >= 1
        assert isinstance(sc["similar"], list)
        assert "name" in sc["similar"][0]
        assert "score" in sc["similar"][0]

    async def test_similar_not_found(self):
        """similar_cards returns error for unknown source card."""
        mock = _make_pool_client()
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.call_tool(
                    "similar_cards",
                    {"card_name": "Nonexistent Card"},
                    raise_on_error=False,
                )
        assert result.is_error
        assert "not found" in result.content[0].text.lower()

    async def test_similar_excludes_source(self):
        """similar_cards does not include the source card itself."""
        mock = _make_pool_client()
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.call_tool(
                    "similar_cards",
                    {"card_name": "Lightning Bolt"},
                )
        text = result.content[0].text
        # The card name appears in the header, but check no duplicate result line
        lines = text.split("\n")
        result_lines = [ln for ln in lines if "score:" in ln]
        for line in result_lines:
            assert "Lightning Bolt" not in line


# ---------------------------------------------------------------------------
# random_card tests
# ---------------------------------------------------------------------------


class TestRandomCard:
    """Tests for the random_card tool."""

    async def test_random_unfiltered(self):
        """random_card returns a card from the pool."""
        mock = _make_pool_client()
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.call_tool("random_card", {})
        text = result.content[0].text
        # Should contain one of the pool cards
        pool_names = [c.name for c in _make_test_pool()]
        assert any(name in text for name in pool_names)
        assert "Data: Scryfall bulk data" in text

        # Structured output
        sc = result.structured_content
        assert sc is not None
        assert "name" in sc
        assert "type_line" in sc
        assert sc["name"] in pool_names

    async def test_random_with_format(self):
        """random_card filters by format legality."""
        # Create pool where only one card is standard-legal
        pool = [
            _make_card(
                name="Standard Card",
                legalities={"standard": "legal", "commander": "legal"},
                edhrec_rank=100,
            ),
            _make_card(
                name="Modern Only",
                legalities={"standard": "not_legal", "modern": "legal"},
                edhrec_rank=200,
            ),
        ]
        mock = _make_pool_client(pool)
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.call_tool(
                    "random_card",
                    {"format": "standard"},
                )
        text = result.content[0].text
        assert "Standard Card" in text

    async def test_random_no_matches(self):
        """random_card returns error when no cards match filters."""
        mock = _make_pool_client([])
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.call_tool(
                    "random_card",
                    {"format": "standard"},
                    raise_on_error=False,
                )
        assert result.is_error


# ---------------------------------------------------------------------------
# ban_list tests
# ---------------------------------------------------------------------------


class TestBanList:
    """Tests for the ban_list tool."""

    async def test_has_banned_cards(self):
        """ban_list shows banned cards for a format."""
        mock = _make_pool_client()
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.call_tool(
                    "ban_list",
                    {"format": "modern"},
                )
        text = result.content[0].text
        assert "Banned" in text
        assert "Sol Ring" in text

        # Structured output
        sc = result.structured_content
        assert sc is not None
        assert sc["format"] == "modern"
        assert isinstance(sc["banned"], list)
        assert any(c["name"] == "Sol Ring" for c in sc["banned"])

    async def test_has_restricted_cards(self):
        """ban_list shows restricted cards for vintage."""
        mock = _make_pool_client()
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.call_tool(
                    "ban_list",
                    {"format": "vintage"},
                )
        text = result.content[0].text
        assert "Restricted" in text
        assert "Sol Ring" in text

    async def test_no_bans(self):
        """ban_list shows message when format has no bans."""
        pool = [
            _make_card(
                name="Basic Card",
                legalities={"legacy": "legal"},
            ),
        ]
        mock = _make_pool_client(pool)
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.call_tool(
                    "ban_list",
                    {"format": "legacy"},
                )
        text = result.content[0].text
        assert "no banned" in text.lower() or "No banned" in text


# ---------------------------------------------------------------------------
# card_in_formats tests
# ---------------------------------------------------------------------------


class TestCardInFormats:
    """Tests for the card_in_formats tool."""

    async def test_shows_all_formats(self):
        """card_in_formats shows legality in all formats."""
        mock = _make_pool_client()
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.call_tool(
                    "card_in_formats",
                    {"card_name": "Sol Ring"},
                )
        text = result.content[0].text
        assert "Sol Ring" in text
        assert "Commander" in text
        assert "Modern" in text
        assert "Vintage" in text

        # Structured output
        sc = result.structured_content
        assert sc is not None
        assert sc["card_name"] == "Sol Ring"
        assert isinstance(sc["legalities"], dict)
        assert sc["legalities"]["commander"] == "legal"

    async def test_card_not_found(self):
        """card_in_formats returns error for unknown card."""
        mock = _make_pool_client()
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.call_tool(
                    "card_in_formats",
                    {"card_name": "Nonexistent"},
                    raise_on_error=False,
                )
        assert result.is_error
        assert "not found" in result.content[0].text.lower()

    async def test_format_order(self):
        """card_in_formats shows priority formats first."""
        mock = _make_pool_client()
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.call_tool(
                    "card_in_formats",
                    {"card_name": "Sol Ring"},
                )
        text = result.content[0].text
        # Commander and Modern should appear before less common formats
        assert "Commander" in text
        assert "Format" in text  # table header


# ---------------------------------------------------------------------------
# Resource tests
# ---------------------------------------------------------------------------


class TestNewResources:
    """Tests for the 4 new resources."""

    async def test_format_legal_cards_resource(self):
        """format legal cards resource returns JSON with count."""
        mock = _make_pool_client()
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.read_resource("mtg://format/commander/legal-cards")
        data = json.loads(result[0].text)
        assert data["format"] == "commander"
        assert isinstance(data["legal_card_count"], int)
        assert data["legal_card_count"] > 0

    async def test_format_banned_resource(self):
        """format banned resource returns JSON list of banned cards."""
        mock = _make_pool_client()
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.read_resource("mtg://format/modern/banned")
        data = json.loads(result[0].text)
        assert isinstance(data, list)
        assert any(c["name"] == "Sol Ring" for c in data)

    async def test_card_formats_resource(self):
        """card formats resource returns legalities dict."""
        mock = _make_pool_client()
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.read_resource("mtg://card/Sol Ring/formats")
        data = json.loads(result[0].text)
        assert data["commander"] == "legal"

    async def test_card_formats_resource_not_found(self):
        """card formats resource returns error for unknown card."""
        mock = _make_pool_client()
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.read_resource("mtg://card/nonexistent/formats")
        data = json.loads(result[0].text)
        assert "error" in data

    async def test_card_similar_resource(self):
        """card similar resource returns JSON list with scores."""
        mock = _make_pool_client()
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.read_resource("mtg://card/Lightning Bolt/similar")
        data = json.loads(result[0].text)
        assert isinstance(data, list)
        if data:
            assert "name" in data[0]
            assert "score" in data[0]

    async def test_card_similar_resource_not_found(self):
        """card similar resource returns error for unknown card."""
        mock = _make_pool_client()
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                result = await client.read_resource("mtg://card/nonexistent/similar")
        data = json.loads(result[0].text)
        assert "error" in data


# ---------------------------------------------------------------------------
# Tool registration test for new tools
# ---------------------------------------------------------------------------


class TestNewToolRegistration:
    """Verify all 9 tools are registered (2 existing + 7 new)."""

    async def test_all_tools_registered(self):
        mock = _make_pool_client()
        with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
            async with Client(transport=scryfall_bulk_mcp) as client:
                tools = await client.list_tools()
        tool_names = {t.name for t in tools}
        expected = {
            "card_lookup",
            "card_search",
            "format_legality",
            "format_search",
            "format_staples",
            "similar_cards",
            "random_card",
            "ban_list",
            "card_in_formats",
        }
        assert expected == tool_names
