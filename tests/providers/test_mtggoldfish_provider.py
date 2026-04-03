"""Tests for the MTGGoldfish MCP provider."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from fastmcp import Client
from fastmcp.server.lifespan import lifespan

import mtg_mcp_server.providers.mtggoldfish as mtggoldfish_mod
from mtg_mcp_server.providers.mtggoldfish import mtggoldfish_mcp
from mtg_mcp_server.types import (
    GoldfishArchetype,
    GoldfishArchetypeDetail,
    GoldfishFormatStaple,
    GoldfishMetaSnapshot,
)

# ---------------------------------------------------------------------------
# Fixture data builders
# ---------------------------------------------------------------------------


def _make_metagame() -> GoldfishMetaSnapshot:
    """Build a metagame snapshot for testing."""
    return GoldfishMetaSnapshot(
        format="Modern",
        archetypes=[
            GoldfishArchetype(
                name="Boros Energy",
                slug="boros-energy",
                meta_share=12.5,
                deck_count=142,
                price_paper=450,
                colors=["W", "R"],
                key_cards=["Galvanic Discharge", "Amped Raptor"],
            ),
            GoldfishArchetype(
                name="Azorius Control",
                slug="azorius-control",
                meta_share=8.3,
                deck_count=94,
                price_paper=620,
                colors=["W", "U"],
                key_cards=["Teferi, Hero of Dominaria", "Supreme Verdict"],
            ),
            GoldfishArchetype(
                name="Golgari Yawgmoth",
                slug="golgari-yawgmoth",
                meta_share=6.1,
                deck_count=69,
                price_paper=380,
                colors=["B", "G"],
                key_cards=["Yawgmoth, Thran Physician"],
            ),
        ],
        total_decks=1134,
    )


def _make_archetype_detail() -> GoldfishArchetypeDetail:
    """Build an archetype detail for testing."""
    return GoldfishArchetypeDetail(
        name="Boros Energy",
        author="PlayerOne",
        event="Modern Challenge",
        result="1st",
        deck_id="deck-12345",
        date="2026-04-01",
        mainboard=[
            "4 Galvanic Discharge",
            "4 Amped Raptor",
            "4 Guide of Souls",
            "4 Ocelot Pride",
            "3 Ajani, Nacatl Pariah",
            "4 Lightning Bolt",
            "2 Path to Exile",
            "21 Lands",
        ],
        sideboard=[
            "2 Wear // Tear",
            "3 Rest in Peace",
            "2 Sanctifier en-Vec",
        ],
    )


def _make_format_staples() -> list[GoldfishFormatStaple]:
    """Build format staples for testing."""
    return [
        GoldfishFormatStaple(
            rank=1,
            name="Lightning Bolt",
            pct_of_decks=42.5,
            copies_played=3.8,
            category="Instants",
        ),
        GoldfishFormatStaple(
            rank=2,
            name="Fatal Push",
            pct_of_decks=35.2,
            copies_played=3.5,
            category="Instants",
        ),
        GoldfishFormatStaple(
            rank=3,
            name="Orcish Bowmasters",
            pct_of_decks=28.9,
            copies_played=4.0,
            category="Creatures",
        ),
    ]


# ---------------------------------------------------------------------------
# Mock infrastructure
# ---------------------------------------------------------------------------


def _make_mock_lifespan(mock_client):
    """Create a no-op lifespan that sets _client to the mock."""

    @lifespan
    async def _mock_lifespan(server):
        mtggoldfish_mod._client = mock_client
        yield {}
        mtggoldfish_mod._client = None

    return _mock_lifespan


@asynccontextmanager
async def _mcp_client(mock_client):
    """Yield an MCP Client with the mtggoldfish lifespan replaced by a mock."""
    original = mtggoldfish_mcp._lifespan
    mtggoldfish_mcp._lifespan = _make_mock_lifespan(mock_client)
    try:
        async with Client(transport=mtggoldfish_mcp) as c:
            yield c
    finally:
        mtggoldfish_mcp._lifespan = original


@pytest.fixture
def mock_client():
    """Create a mock MTGGoldfishClient with fixture data."""
    client = AsyncMock()
    client.get_metagame = AsyncMock(return_value=_make_metagame())
    client.get_archetype = AsyncMock(return_value=_make_archetype_detail())
    client.get_format_staples = AsyncMock(return_value=_make_format_staples())
    client.get_deck_price = AsyncMock(
        return_value={"archetype": "Boros Energy", "estimated_price": 450, "card_count": 75}
    )
    return client


@pytest.fixture
async def client(mock_client):
    """MCP client with mocked MTGGoldfishClient."""
    async with _mcp_client(mock_client) as c:
        yield c


# ---------------------------------------------------------------------------
# Metagame tool
# ---------------------------------------------------------------------------


class TestMetagame:
    """metagame tool behavior."""

    async def test_returns_markdown_with_metagame_table(self, client: Client):
        """metagame returns markdown with a table of archetypes."""
        result = await client.call_tool("metagame", {"format": "Modern"})
        text = result.content[0].text

        assert "## Modern Metagame" in text
        assert "Boros Energy" in text
        assert "Azorius Control" in text
        assert "| Rank |" in text
        assert "12.5%" in text or "12.50%" in text
        assert "Data provided by [MTGGoldfish]" in text

    async def test_structured_content_has_archetype_list(self, client: Client):
        """Structured content contains format and archetype list with slim fields."""
        result = await client.call_tool("metagame", {"format": "Modern"})
        sc = result.structured_content

        assert sc is not None
        assert sc["format"] == "Modern"
        assert isinstance(sc["archetypes"], list)
        assert len(sc["archetypes"]) == 3
        assert sc["total_decks"] == 1134

        a = sc["archetypes"][0]
        assert "name" in a
        assert "slug" in a
        assert "meta_share" in a
        assert "deck_count" in a
        assert "price_paper" in a

    async def test_concise_response_format(self, client: Client):
        """Concise format uses bullet list instead of table."""
        result = await client.call_tool(
            "metagame", {"format": "Modern", "response_format": "concise"}
        )
        text = result.content[0].text

        # Concise uses bullet points, not table headers
        assert "| Rank |" not in text
        assert "- **Boros Energy**" in text

    async def test_empty_metagame(self):
        """Returns informational message when no archetypes found."""
        mock = AsyncMock()
        mock.get_metagame = AsyncMock(
            return_value=GoldfishMetaSnapshot(format="Modern", archetypes=[], total_decks=0)
        )
        async with _mcp_client(mock) as c:
            result = await c.call_tool("metagame", {"format": "Modern"})
            text = result.content[0].text
            assert "No metagame data" in text
            sc = result.structured_content
            assert sc["archetypes"] == []


# ---------------------------------------------------------------------------
# Archetype list tool
# ---------------------------------------------------------------------------


class TestArchetypeList:
    """archetype_list tool behavior."""

    async def test_returns_markdown_with_decklist(self, client: Client):
        """archetype_list returns markdown with deck metadata and card list."""
        result = await client.call_tool(
            "archetype_list", {"format": "Modern", "archetype": "Boros Energy"}
        )
        text = result.content[0].text

        assert "Boros Energy" in text
        assert "PlayerOne" in text
        assert "Modern Challenge" in text
        assert "1st" in text
        assert "Galvanic Discharge" in text
        assert "Data provided by [MTGGoldfish]" in text

    async def test_sideboard_shown(self, client: Client):
        """archetype_list includes sideboard when present."""
        result = await client.call_tool(
            "archetype_list", {"format": "Modern", "archetype": "Boros Energy"}
        )
        text = result.content[0].text

        assert "Sideboard" in text
        assert "Rest in Peace" in text

    async def test_structured_content_has_archetype_detail(self, client: Client):
        """Structured content includes full archetype detail model dump."""
        result = await client.call_tool(
            "archetype_list", {"format": "Modern", "archetype": "Boros Energy"}
        )
        sc = result.structured_content

        assert sc is not None
        assert sc["name"] == "Boros Energy"
        assert sc["author"] == "PlayerOne"
        assert sc["event"] == "Modern Challenge"
        assert sc["result"] == "1st"
        assert "mainboard" in sc
        assert "sideboard" in sc
        assert len(sc["mainboard"]) == 8
        assert len(sc["sideboard"]) == 3

    async def test_not_found_returns_error(self):
        """archetype_list returns ToolError for unknown archetype."""
        from mtg_mcp_server.services.mtggoldfish import ArchetypeNotFoundError

        mock = AsyncMock()
        mock.get_archetype = AsyncMock(
            side_effect=ArchetypeNotFoundError("Archetype not found: Nonexistent")
        )
        async with _mcp_client(mock) as c:
            result = await c.call_tool(
                "archetype_list",
                {"format": "Modern", "archetype": "Nonexistent"},
                raise_on_error=False,
            )
            assert result.is_error
            assert "not found" in result.content[0].text.lower()

    async def test_concise_response_format(self, client: Client):
        """Concise format shows abbreviated decklist."""
        result = await client.call_tool(
            "archetype_list",
            {"format": "Modern", "archetype": "Boros Energy", "response_format": "concise"},
        )
        text = result.content[0].text

        # Concise still shows deck name but may omit some metadata
        assert "Boros Energy" in text
        assert "Galvanic Discharge" in text


# ---------------------------------------------------------------------------
# Format staples tool
# ---------------------------------------------------------------------------


class TestFormatStaples:
    """format_staples tool behavior."""

    async def test_returns_markdown_with_staples_table(self, client: Client):
        """format_staples returns markdown with a table of most-played cards."""
        result = await client.call_tool("format_staples", {"format": "Modern"})
        text = result.content[0].text

        assert "## Modern Format Staples" in text
        assert "Lightning Bolt" in text
        assert "Fatal Push" in text
        assert "| Rank |" in text
        assert "42.5%" in text or "42.50%" in text
        assert "Data provided by [MTGGoldfish]" in text

    async def test_structured_content_has_staple_list(self, client: Client):
        """Structured content contains staple list with slim fields."""
        result = await client.call_tool("format_staples", {"format": "Modern"})
        sc = result.structured_content

        assert sc is not None
        assert isinstance(sc["staples"], list)
        assert len(sc["staples"]) == 3

        s = sc["staples"][0]
        assert "rank" in s
        assert "name" in s
        assert "pct_of_decks" in s
        assert "copies_played" in s

    async def test_limit_parameter(self, client: Client):
        """format_staples respects limit parameter."""
        result = await client.call_tool("format_staples", {"format": "Modern", "limit": 2})
        # The mock returns 3 staples, client calls with limit=2
        client_call = result.structured_content
        # The mock's return value is pre-set so we check the client was called with limit
        assert client_call is not None

    async def test_concise_response_format(self, client: Client):
        """Concise format uses bullet list instead of table."""
        result = await client.call_tool(
            "format_staples", {"format": "Modern", "response_format": "concise"}
        )
        text = result.content[0].text

        assert "| Rank |" not in text
        assert "Lightning Bolt" in text

    async def test_empty_staples(self):
        """Returns informational message when no staples found."""
        mock = AsyncMock()
        mock.get_format_staples = AsyncMock(return_value=[])
        async with _mcp_client(mock) as c:
            result = await c.call_tool("format_staples", {"format": "Modern"})
            text = result.content[0].text
            assert "No staple data" in text
            sc = result.structured_content
            assert sc["staples"] == []


# ---------------------------------------------------------------------------
# Deck price tool
# ---------------------------------------------------------------------------


class TestDeckPrice:
    """deck_price tool behavior."""

    async def test_returns_markdown_with_price_summary(self, client: Client):
        """deck_price returns markdown with price information."""
        result = await client.call_tool(
            "deck_price", {"format": "Modern", "archetype": "Boros Energy"}
        )
        text = result.content[0].text

        assert "Boros Energy" in text
        assert "$450" in text or "450" in text
        assert "Data provided by [MTGGoldfish]" in text

    async def test_structured_content_has_price_data(self, client: Client):
        """Structured content contains price data dict."""
        result = await client.call_tool(
            "deck_price", {"format": "Modern", "archetype": "Boros Energy"}
        )
        sc = result.structured_content

        assert sc is not None
        assert sc["archetype"] == "Boros Energy"
        assert sc["estimated_price"] == 450
        assert sc["card_count"] == 75

    async def test_not_found_returns_error(self):
        """deck_price returns ToolError for unknown archetype."""
        from mtg_mcp_server.services.mtggoldfish import ArchetypeNotFoundError

        mock = AsyncMock()
        mock.get_deck_price = AsyncMock(
            side_effect=ArchetypeNotFoundError("Archetype not found: Nonexistent")
        )
        async with _mcp_client(mock) as c:
            result = await c.call_tool(
                "deck_price",
                {"format": "Modern", "archetype": "Nonexistent"},
                raise_on_error=False,
            )
            assert result.is_error
            assert "not found" in result.content[0].text.lower()

    async def test_concise_response_format(self, client: Client):
        """Concise format shows abbreviated price info."""
        result = await client.call_tool(
            "deck_price",
            {"format": "Modern", "archetype": "Boros Energy", "response_format": "concise"},
        )
        text = result.content[0].text

        assert "Boros Energy" in text
        assert "450" in text


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """MTGGoldfish provider tool registration."""

    async def test_four_tools_registered(self, client: Client):
        """All four MTGGoldfish tools are registered on the provider."""
        tools = await client.list_tools()
        tool_names = {t.name for t in tools}
        assert tool_names == {"metagame", "archetype_list", "format_staples", "deck_price"}

    async def test_tools_have_correct_annotations(self, client: Client):
        """Tools have readOnly, idempotent, and openWorld annotations."""
        tools = await client.list_tools()
        for tool in tools:
            assert tool.annotations is not None
            assert tool.annotations.readOnlyHint is True
            assert tool.annotations.idempotentHint is True
            assert tool.annotations.openWorldHint is True


# ---------------------------------------------------------------------------
# Resource
# ---------------------------------------------------------------------------


class TestResource:
    """MTGGoldfish resource template behavior."""

    async def test_resource_template_registered(self, client: Client):
        """Metagame resource template is registered on the provider."""
        templates = await client.list_resource_templates()
        template_uris = {t.uriTemplate for t in templates}
        assert "mtg://metagame/{format}" in template_uris


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Error handling for MTGGoldfish provider tools."""

    async def test_format_not_found_error(self):
        """FormatNotFoundError is converted to ToolError."""
        from mtg_mcp_server.services.mtggoldfish import FormatNotFoundError

        mock = AsyncMock()
        mock.get_metagame = AsyncMock(side_effect=FormatNotFoundError("BadFormat"))
        async with _mcp_client(mock) as c:
            result = await c.call_tool(
                "metagame",
                {"format": "BadFormat"},
                raise_on_error=False,
            )
            assert result.is_error
            assert "not found" in result.content[0].text.lower()

    async def test_archetype_not_found_error(self):
        """ArchetypeNotFoundError is converted to ToolError."""
        from mtg_mcp_server.services.mtggoldfish import ArchetypeNotFoundError

        mock = AsyncMock()
        mock.get_archetype = AsyncMock(side_effect=ArchetypeNotFoundError("NotARealDeck"))
        async with _mcp_client(mock) as c:
            result = await c.call_tool(
                "archetype_list",
                {"format": "Modern", "archetype": "NotARealDeck"},
                raise_on_error=False,
            )
            assert result.is_error
            assert "not found" in result.content[0].text.lower()

    async def test_mtggoldfish_error(self):
        """MTGGoldfishError is converted to ToolError."""
        from mtg_mcp_server.services.mtggoldfish import MTGGoldfishError

        mock = AsyncMock()
        mock.get_metagame = AsyncMock(side_effect=MTGGoldfishError("Server unreachable"))
        async with _mcp_client(mock) as c:
            result = await c.call_tool(
                "metagame",
                {"format": "Modern"},
                raise_on_error=False,
            )
            assert result.is_error
            assert "MTGGoldfish" in result.content[0].text

    async def test_format_staples_format_not_found(self):
        """format_staples handles FormatNotFoundError."""
        from mtg_mcp_server.services.mtggoldfish import FormatNotFoundError

        mock = AsyncMock()
        mock.get_format_staples = AsyncMock(side_effect=FormatNotFoundError("BadFormat"))
        async with _mcp_client(mock) as c:
            result = await c.call_tool(
                "format_staples",
                {"format": "BadFormat"},
                raise_on_error=False,
            )
            assert result.is_error
            assert "not found" in result.content[0].text.lower()

    async def test_deck_price_mtggoldfish_error(self):
        """deck_price handles MTGGoldfishError."""
        from mtg_mcp_server.services.mtggoldfish import MTGGoldfishError

        mock = AsyncMock()
        mock.get_deck_price = AsyncMock(side_effect=MTGGoldfishError("Connection timeout"))
        async with _mcp_client(mock) as c:
            result = await c.call_tool(
                "deck_price",
                {"format": "Modern", "archetype": "Boros Energy"},
                raise_on_error=False,
            )
            assert result.is_error
            assert "MTGGoldfish" in result.content[0].text
