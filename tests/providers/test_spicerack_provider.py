"""Tests for the Spicerack MCP provider."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastmcp import Client
from fastmcp.server.lifespan import lifespan

import mtg_mcp_server.providers.spicerack as spicerack_mod
from mtg_mcp_server.providers.spicerack import spicerack_mcp
from mtg_mcp_server.types import SpicerackStanding, SpicerackTournament

FIXTURES = Path(__file__).parent.parent / "fixtures" / "spicerack"


def _load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


def _make_tournaments() -> list[SpicerackTournament]:
    """Build SpicerackTournament objects from fixture data for mocking."""
    raw = _load_fixture("tournaments_legacy.json")
    tournaments = []
    for t in raw:
        standings = []
        for i, s in enumerate(t.get("standings", []), 1):
            standings.append(
                SpicerackStanding(
                    rank=i,
                    player_name=s["name"],
                    wins=s["winsSwiss"],
                    losses=s["lossesSwiss"],
                    draws=s["draws"],
                    bracket_wins=s["winsBracket"],
                    bracket_losses=s["lossesBracket"],
                    decklist_url=s.get("decklist", ""),
                )
            )
        date_str = datetime.fromtimestamp(t["startDate"], tz=UTC).strftime("%Y-%m-%d")
        tournaments.append(
            SpicerackTournament(
                tournament_id=str(t["TID"]),
                name=t["tournamentName"],
                format=t["format"],
                date=date_str,
                player_count=t["players"],
                rounds_swiss=t["swissRounds"],
                top_cut=t["topCut"],
                bracket_url=t["bracketUrl"],
                standings=standings,
            )
        )
    return tournaments


def _make_mock_lifespan(mock_client):
    """Create a no-op lifespan that sets _client to the mock."""

    @lifespan
    async def _mock_lifespan(server):
        spicerack_mod._client = mock_client
        yield {}
        spicerack_mod._client = None

    return _mock_lifespan


@asynccontextmanager
async def _mcp_client(mock_client):
    """Yield an MCP Client with the spicerack lifespan replaced by a mock."""
    original = spicerack_mcp._lifespan
    spicerack_mcp._lifespan = _make_mock_lifespan(mock_client)
    try:
        async with Client(transport=spicerack_mcp) as c:
            yield c
    finally:
        spicerack_mcp._lifespan = original


@pytest.fixture
def mock_client():
    """Create a mock SpicerackClient with fixture data."""
    client = AsyncMock()
    client.get_tournaments = AsyncMock(return_value=_make_tournaments())
    return client


@pytest.fixture
async def client(mock_client):
    """MCP client with mocked SpicerackClient."""
    async with _mcp_client(mock_client) as c:
        yield c


# -- Fixture constants for assertion clarity --
T1_ID = "3135276"
T1_NAME = "ETB x LOTN 3k-5k Jim Monolith 40th B-Day Bash - Enter the Battlefield - Newmarket"
T1_PLAYER1 = "Chris Switalski"

T2_ID = "2919004"
T2_NAME = "$2.5k Legacy Trial - NRG Series"
T2_PLAYER1 = "Oliver Voegeli"


class TestRecentTournaments:
    """recent_tournaments tool behavior."""

    async def test_returns_markdown_with_tournament_table(self, client: Client):
        """recent_tournaments returns markdown with a table of tournaments."""
        result = await client.call_tool("recent_tournaments", {"format": "Legacy"})
        text = result.content[0].text

        assert "## Recent Legacy Tournaments" in text
        assert T1_NAME in text
        assert T2_NAME in text
        assert "| Name | Date | Players | Standings | ID |" in text
        assert T1_ID in text
        assert T2_ID in text
        assert "Data provided by [Spicerack]" in text

    async def test_structured_content_has_tournament_list(self, client: Client):
        """Structured content contains format and tournament list with slim fields."""
        result = await client.call_tool("recent_tournaments", {"format": "Legacy"})
        sc = result.structured_content

        assert sc is not None
        assert sc["format"] == "Legacy"
        assert isinstance(sc["tournaments"], list)
        assert len(sc["tournaments"]) == 2

        t = sc["tournaments"][0]
        assert "tournament_id" in t
        assert "name" in t
        assert "format" in t
        assert "date" in t
        assert "player_count" in t

    async def test_respects_limit_parameter(self, client: Client):
        """recent_tournaments truncates results to limit."""
        result = await client.call_tool("recent_tournaments", {"format": "Legacy", "limit": 1})
        sc = result.structured_content

        assert len(sc["tournaments"]) == 1
        assert sc["tournaments"][0]["tournament_id"] == T1_ID

    async def test_concise_response_format(self, client: Client):
        """Concise format uses bullet list instead of table."""
        result = await client.call_tool(
            "recent_tournaments", {"format": "Legacy", "response_format": "concise"}
        )
        text = result.content[0].text

        # Concise uses bullet points, not table headers
        assert "| Name | Date |" not in text
        assert f"- **{T1_NAME}**" in text

    async def test_empty_results(self):
        """Returns informational message when no tournaments found."""
        mock = AsyncMock()
        mock.get_tournaments = AsyncMock(return_value=[])
        async with _mcp_client(mock) as c:
            result = await c.call_tool("recent_tournaments", {"format": "Legacy"})
            text = result.content[0].text
            assert "No Legacy tournaments found" in text
            sc = result.structured_content
            assert sc["tournaments"] == []


class TestTournamentResults:
    """tournament_results tool behavior."""

    async def test_returns_markdown_with_standings_table(self, client: Client):
        """tournament_results returns markdown with metadata and standings table."""
        result = await client.call_tool(
            "tournament_results",
            {"tournament_id": T1_ID},
        )
        text = result.content[0].text

        assert f"## {T1_NAME}" in text
        assert "| Rank | Player | Record | Bracket | Decklist |" in text
        assert T1_PLAYER1 in text
        assert "Data provided by [Spicerack]" in text

    async def test_standings_have_correct_record_format(self, client: Client):
        """Standings show W-L-D format for Swiss record."""
        result = await client.call_tool(
            "tournament_results",
            {"tournament_id": T1_ID},
        )
        text = result.content[0].text

        # Chris Switalski: 5-1-1
        assert "5-1-1" in text
        # Benjamin Dunk Kostecki: 5-0-2
        assert "5-0-2" in text

    async def test_bracket_record_shown_when_nonzero(self, client: Client):
        """Bracket column shows W-L when player has bracket games."""
        result = await client.call_tool(
            "tournament_results",
            {"tournament_id": T1_ID},
        )
        text = result.content[0].text

        # Chris Switalski: bracket 3-0
        assert "3-0" in text
        # Benjamin Dunk Kostecki: bracket 2-1
        assert "2-1" in text

    async def test_decklist_urls_preserved(self, client: Client):
        """Decklist URLs appear as links in markdown."""
        result = await client.call_tool(
            "tournament_results",
            {"tournament_id": T1_ID},
        )
        text = result.content[0].text

        assert "moxfield.com/decks/" in text
        assert "[Link](" in text

    async def test_not_found_returns_error(self, client: Client):
        """tournament_results returns ToolError for unknown tournament ID."""
        result = await client.call_tool(
            "tournament_results",
            {"tournament_id": "NONEXISTENT"},
            raise_on_error=False,
        )
        assert result.is_error
        assert "Tournament not found" in result.content[0].text

    async def test_respects_top_n_parameter(self, client: Client):
        """tournament_results truncates standings to top_n."""
        result = await client.call_tool(
            "tournament_results",
            {"tournament_id": T1_ID, "top_n": 2},
        )
        sc = result.structured_content

        assert len(sc["standings"]) == 2
        assert sc["standings"][0]["player_name"] == T1_PLAYER1

    async def test_structured_content_has_tournament_metadata(self, client: Client):
        """Structured content includes full tournament metadata and standings."""
        result = await client.call_tool(
            "tournament_results",
            {"tournament_id": T1_ID},
        )
        sc = result.structured_content

        assert sc is not None
        assert sc["tournament_id"] == T1_ID
        assert sc["name"] == T1_NAME
        assert sc["format"] == "Legacy"
        assert sc["player_count"] == 79
        assert sc["rounds_swiss"] == 5
        assert sc["top_cut"] == 8
        assert isinstance(sc["standings"], list)
        assert len(sc["standings"]) == 8

    async def test_concise_response_format(self, client: Client):
        """Concise format shows shorter metadata header."""
        result = await client.call_tool(
            "tournament_results",
            {"tournament_id": T1_ID, "response_format": "concise"},
        )
        text = result.content[0].text

        # Concise omits detailed metadata lines
        assert "**Swiss Rounds:**" not in text
        assert "**Top Cut:**" not in text
        # But still has standings table
        assert "| Rank | Player |" in text


class TestFormatDecklists:
    """format_decklists tool behavior."""

    async def test_returns_top_decklists_across_tournaments(self, client: Client):
        """format_decklists collects top-4 decklists from all tournaments."""
        result = await client.call_tool("format_decklists", {"format": "Legacy"})
        text = result.content[0].text

        assert "## Top Legacy Decklists" in text
        # Should include players with decklists from both tournaments
        assert T1_PLAYER1 in text
        assert T2_PLAYER1 in text
        assert "Data provided by [Spicerack]" in text

    async def test_respects_limit_parameter(self, client: Client):
        """format_decklists truncates to limit."""
        result = await client.call_tool("format_decklists", {"format": "Legacy", "limit": 2})
        sc = result.structured_content

        assert len(sc["decklists"]) == 2

    async def test_no_decklists_returns_informational_message(self):
        """Returns informational message (not error) when no decklists found."""
        mock = AsyncMock()
        mock.get_tournaments = AsyncMock(
            return_value=[
                SpicerackTournament(
                    tournament_id="EMPTY",
                    name="Empty Tournament",
                    format="Legacy",
                    date="2026-04-01",
                    player_count=8,
                    standings=[
                        SpicerackStanding(
                            rank=1,
                            player_name="Player1",
                            wins=3,
                            losses=0,
                            decklist_url="",
                        ),
                    ],
                ),
            ]
        )
        async with _mcp_client(mock) as c:
            result = await c.call_tool("format_decklists", {"format": "Legacy"})
            text = result.content[0].text
            assert "No decklists available" in text
            sc = result.structured_content
            assert sc["decklists"] == []

    async def test_structured_content_has_decklist_entries(self, client: Client):
        """Structured content has decklist entries with player, record, tournament, URL."""
        result = await client.call_tool("format_decklists", {"format": "Legacy"})
        sc = result.structured_content

        assert sc is not None
        assert sc["format"] == "Legacy"
        assert isinstance(sc["decklists"], list)
        assert len(sc["decklists"]) > 0

        d = sc["decklists"][0]
        assert "player" in d
        assert "rank" in d
        assert "record" in d
        assert "tournament" in d
        assert "decklist_url" in d

    async def test_sorted_by_rank(self, client: Client):
        """Decklists are sorted by rank, best first."""
        result = await client.call_tool("format_decklists", {"format": "Legacy"})
        sc = result.structured_content

        ranks = [d["rank"] for d in sc["decklists"]]
        assert ranks == sorted(ranks)


class TestToolRegistration:
    """Spicerack provider tool registration."""

    async def test_three_tools_registered(self, client: Client):
        """All three Spicerack tools are registered on the provider."""
        tools = await client.list_tools()
        tool_names = {t.name for t in tools}
        assert tool_names == {"recent_tournaments", "tournament_results", "format_decklists"}

    async def test_tools_have_correct_annotations(self, client: Client):
        """Tools have readOnly, idempotent, and openWorld annotations."""
        tools = await client.list_tools()
        for tool in tools:
            assert tool.annotations is not None
            assert tool.annotations.readOnlyHint is True
            assert tool.annotations.idempotentHint is True
            assert tool.annotations.openWorldHint is True


class TestSpicerackResource:
    """Spicerack resource template behavior."""

    async def test_resource_template_registered(self, client: Client):
        """Tournament resource template is registered on the provider."""
        templates = await client.list_resource_templates()
        template_uris = {t.uriTemplate for t in templates}
        assert "mtg://tournament/{event_format}/recent" in template_uris


class TestErrorHandling:
    """Error handling for Spicerack provider tools."""

    async def test_invalid_format_error(self):
        """InvalidFormatError is converted to ToolError."""
        from mtg_mcp_server.services.spicerack import InvalidFormatError

        mock = AsyncMock()
        mock.get_tournaments = AsyncMock(side_effect=InvalidFormatError("BadFormat"))
        async with _mcp_client(mock) as c:
            result = await c.call_tool(
                "recent_tournaments",
                {"format": "BadFormat"},
                raise_on_error=False,
            )
            assert result.is_error
            assert "Invalid format" in result.content[0].text

    async def test_spicerack_error(self):
        """SpicerackError is converted to ToolError."""
        from mtg_mcp_server.services.spicerack import SpicerackError

        mock = AsyncMock()
        mock.get_tournaments = AsyncMock(side_effect=SpicerackError("Server unreachable"))
        async with _mcp_client(mock) as c:
            result = await c.call_tool(
                "recent_tournaments",
                {"format": "Legacy"},
                raise_on_error=False,
            )
            assert result.is_error
            assert "Spicerack API error" in result.content[0].text

    async def test_tournament_results_invalid_format(self):
        """tournament_results handles InvalidFormatError."""
        from mtg_mcp_server.services.spicerack import InvalidFormatError

        mock = AsyncMock()
        mock.get_tournaments = AsyncMock(side_effect=InvalidFormatError("BadFormat"))
        async with _mcp_client(mock) as c:
            result = await c.call_tool(
                "tournament_results",
                {"tournament_id": T1_ID, "format": "BadFormat"},
                raise_on_error=False,
            )
            assert result.is_error
            assert "Invalid format" in result.content[0].text

    async def test_format_decklists_spicerack_error(self):
        """format_decklists handles SpicerackError."""
        from mtg_mcp_server.services.spicerack import SpicerackError

        mock = AsyncMock()
        mock.get_tournaments = AsyncMock(side_effect=SpicerackError("Connection timeout"))
        async with _mcp_client(mock) as c:
            result = await c.call_tool(
                "format_decklists",
                {"format": "Legacy"},
                raise_on_error=False,
            )
            assert result.is_error
            assert "Spicerack API error" in result.content[0].text
