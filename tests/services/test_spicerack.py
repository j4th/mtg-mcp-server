"""Tests for the Spicerack service client."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from cachetools import TTLCache

from mtg_mcp_server.services.spicerack import (
    InvalidFormatError,
    SpicerackClient,
    SpicerackError,
)
from mtg_mcp_server.types import SpicerackStanding, SpicerackTournament

FIXTURES = Path(__file__).parent.parent / "fixtures" / "spicerack"
BASE_URL = "https://api.spicerack.gg"


@pytest.fixture(autouse=True)
def _clear_spicerack_cache():
    """Clear SpicerackClient cache before every test to prevent leakage."""
    SpicerackClient._tournaments_cache.clear()


def _load_fixture(name: str) -> list | dict:
    """Load a Spicerack JSON fixture by filename."""
    return json.loads((FIXTURES / name).read_text())


class TestGetTournaments:
    """Happy-path tests for tournament retrieval and parsing."""

    @respx.mock
    async def test_parses_two_tournaments(self):
        """Fixture with 2 tournaments returns 2 SpicerackTournament objects."""
        fixture = _load_fixture("tournaments_legacy.json")
        respx.get(f"{BASE_URL}/api/export-decklists/").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with SpicerackClient(base_url=BASE_URL) as client:
            result = await client.get_tournaments()

        assert len(result) == 2
        assert all(isinstance(t, SpicerackTournament) for t in result)

    @respx.mock
    async def test_tournament_fields_mapped(self):
        """Tournament API fields map to model fields correctly."""
        fixture = _load_fixture("tournaments_legacy.json")
        respx.get(f"{BASE_URL}/api/export-decklists/").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with SpicerackClient(base_url=BASE_URL) as client:
            result = await client.get_tournaments()

        t = result[0]
        assert t.tournament_id == "3135276"
        assert (
            t.name
            == "ETB x LOTN 3k-5k Jim Monolith 40th B-Day Bash - Enter the Battlefield - Newmarket"
        )
        assert t.format == "Legacy"
        assert t.bracket_url == "https://www.spicerack.gg/events/3135276/tournament"
        assert t.player_count == 79
        assert t.rounds_swiss == 5
        assert t.top_cut == 8

    @respx.mock
    async def test_start_date_converted_to_iso(self):
        """Unix timestamp startDate converts to ISO date string."""
        fixture = _load_fixture("tournaments_legacy.json")
        respx.get(f"{BASE_URL}/api/export-decklists/").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with SpicerackClient(base_url=BASE_URL) as client:
            result = await client.get_tournaments()

        # 1774710000 = 2026-03-28 in UTC
        assert result[0].date == "2026-03-28"

    @respx.mock
    async def test_standings_parsed_with_rank(self):
        """Standings are parsed with 1-based rank from array position."""
        fixture = _load_fixture("tournaments_legacy.json")
        respx.get(f"{BASE_URL}/api/export-decklists/").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with SpicerackClient(base_url=BASE_URL) as client:
            result = await client.get_tournaments()

        standings = result[0].standings
        assert len(standings) == 8
        assert all(isinstance(s, SpicerackStanding) for s in standings)
        # Ranks are 1-based from array index
        assert standings[0].rank == 1
        assert standings[1].rank == 2
        assert standings[7].rank == 8

    @respx.mock
    async def test_standing_fields_mapped(self):
        """Standing API fields map to model fields correctly."""
        fixture = _load_fixture("tournaments_legacy.json")
        respx.get(f"{BASE_URL}/api/export-decklists/").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with SpicerackClient(base_url=BASE_URL) as client:
            result = await client.get_tournaments()

        first = result[0].standings[0]
        assert first.player_name == "Chris Switalski"
        assert first.wins == 5
        assert first.losses == 1
        assert first.draws == 1
        assert first.bracket_wins == 3
        assert first.bracket_losses == 0

    @respx.mock
    async def test_decklist_url_preserved(self):
        """Moxfield decklist URL is preserved in standings."""
        fixture = _load_fixture("tournaments_legacy.json")
        respx.get(f"{BASE_URL}/api/export-decklists/").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with SpicerackClient(base_url=BASE_URL) as client:
            result = await client.get_tournaments()

        first = result[0].standings[0]
        assert first.decklist_url == "https://www.moxfield.com/decks/Etg7q115Q0itX7k4vktGMQ"

    @respx.mock
    async def test_empty_standings_handled(self):
        """Tournament with empty standings array returns empty standings list."""
        fixture = [
            {
                "TID": "999",
                "tournamentName": "No Results Yet",
                "format": "Modern",
                "bracketUrl": "",
                "players": 0,
                "startDate": 1774710000,
                "swissRounds": 0,
                "topCut": 0,
                "standings": [],
            }
        ]
        respx.get(f"{BASE_URL}/api/export-decklists/").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with SpicerackClient(base_url=BASE_URL) as client:
            result = await client.get_tournaments()

        assert len(result) == 1
        assert result[0].standings == []


class TestEmptyResults:
    """Tests for empty API responses."""

    @respx.mock
    async def test_empty_array_returns_empty_list(self):
        """Empty JSON array returns empty list."""
        fixture = _load_fixture("tournaments_empty.json")
        respx.get(f"{BASE_URL}/api/export-decklists/").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with SpicerackClient(base_url=BASE_URL) as client:
            result = await client.get_tournaments()

        assert result == []


class TestEventFormatFilter:
    """Tests for event_format parameter passing."""

    @respx.mock
    async def test_format_param_passed(self):
        """event_format parameter is passed to the API."""
        respx.get(f"{BASE_URL}/api/export-decklists/").mock(
            return_value=httpx.Response(200, json=[])
        )
        async with SpicerackClient(base_url=BASE_URL) as client:
            await client.get_tournaments(event_format="Legacy")

        request = respx.calls.last.request
        assert "event_format=Legacy" in str(request.url)

    @respx.mock
    async def test_num_days_param_passed(self):
        """num_days parameter is passed to the API."""
        respx.get(f"{BASE_URL}/api/export-decklists/").mock(
            return_value=httpx.Response(200, json=[])
        )
        async with SpicerackClient(base_url=BASE_URL) as client:
            await client.get_tournaments(num_days=7)

        request = respx.calls.last.request
        assert "num_days=7" in str(request.url)

    @respx.mock
    async def test_no_format_omits_param(self):
        """When event_format is None, no event_format param is sent."""
        respx.get(f"{BASE_URL}/api/export-decklists/").mock(
            return_value=httpx.Response(200, json=[])
        )
        async with SpicerackClient(base_url=BASE_URL) as client:
            await client.get_tournaments()

        request = respx.calls.last.request
        assert "event_format" not in str(request.url)


class TestErrorHandling:
    """Tests for HTTP error responses."""

    @respx.mock
    async def test_400_invalid_format_raises(self):
        """HTTP 400 (invalid format) raises InvalidFormatError."""
        fixture = _load_fixture("error_invalid_format.json")
        respx.get(f"{BASE_URL}/api/export-decklists/").mock(
            return_value=httpx.Response(400, json=fixture)
        )
        async with SpicerackClient(base_url=BASE_URL) as client:
            with pytest.raises(InvalidFormatError, match="Invalid format"):
                await client.get_tournaments(event_format="INVALID")

    @respx.mock
    async def test_500_raises_spicerack_error(self):
        """HTTP 500 raises SpicerackError."""
        respx.get(f"{BASE_URL}/api/export-decklists/").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        async with SpicerackClient(base_url=BASE_URL) as client:
            with pytest.raises(SpicerackError):
                await client.get_tournaments()

    @respx.mock
    async def test_non_json_response_raises(self):
        """Non-JSON response body raises SpicerackError."""
        respx.get(f"{BASE_URL}/api/export-decklists/").mock(
            return_value=httpx.Response(200, text="<html>Not JSON</html>")
        )
        async with SpicerackClient(base_url=BASE_URL) as client:
            with pytest.raises(SpicerackError, match="invalid JSON"):
                await client.get_tournaments()

    @respx.mock
    async def test_non_list_response_raises(self):
        """Non-list JSON response raises SpicerackError."""
        respx.get(f"{BASE_URL}/api/export-decklists/").mock(
            return_value=httpx.Response(200, json={"error": "unexpected"})
        )
        async with SpicerackClient(base_url=BASE_URL) as client:
            with pytest.raises(SpicerackError, match="Expected JSON array"):
                await client.get_tournaments()


class TestDefensiveParsing:
    """Tests for defensive parsing of malformed data."""

    @respx.mock
    async def test_missing_tournament_fields_get_defaults(self):
        """Missing fields in tournament object use defaults."""
        data = [{"TID": "1"}]
        respx.get(f"{BASE_URL}/api/export-decklists/").mock(
            return_value=httpx.Response(200, json=data)
        )
        async with SpicerackClient(base_url=BASE_URL) as client:
            result = await client.get_tournaments()

        assert len(result) == 1
        t = result[0]
        assert t.tournament_id == "1"
        assert t.name == ""
        assert t.format == ""
        assert t.player_count == 0
        assert t.date == ""
        assert t.standings == []

    @respx.mock
    async def test_missing_standing_fields_get_defaults(self):
        """Missing fields in standing object use defaults."""
        data = [
            {
                "TID": "1",
                "standings": [{"name": "Alice"}],
            }
        ]
        respx.get(f"{BASE_URL}/api/export-decklists/").mock(
            return_value=httpx.Response(200, json=data)
        )
        async with SpicerackClient(base_url=BASE_URL) as client:
            result = await client.get_tournaments()

        s = result[0].standings[0]
        assert s.player_name == "Alice"
        assert s.decklist_url == ""
        assert s.wins == 0
        assert s.losses == 0
        assert s.draws == 0
        assert s.bracket_wins == 0
        assert s.bracket_losses == 0
        assert s.rank == 1

    @respx.mock
    async def test_non_dict_in_standings_skipped(self):
        """Non-dict entries in standings array are skipped with warning."""
        data = [
            {
                "TID": "1",
                "standings": [
                    "not a dict",
                    {"name": "Bob"},
                ],
            }
        ]
        respx.get(f"{BASE_URL}/api/export-decklists/").mock(
            return_value=httpx.Response(200, json=data)
        )
        async with SpicerackClient(base_url=BASE_URL) as client:
            result = await client.get_tournaments()

        # Only the valid dict entry is parsed; non-dict is skipped
        assert len(result[0].standings) == 1
        assert result[0].standings[0].player_name == "Bob"
        # Rank should be 2 (index 1 + 1), since index 0 was skipped
        # Actually, the rank loop uses enumerate on raw_standings so
        # the non-dict at index 0 is skipped but Bob is at index 1
        assert result[0].standings[0].rank == 2

    @respx.mock
    async def test_non_list_standings_returns_empty(self):
        """Non-list standings value returns empty standings list."""
        data = [
            {
                "TID": "1",
                "standings": "not a list",
            }
        ]
        respx.get(f"{BASE_URL}/api/export-decklists/").mock(
            return_value=httpx.Response(200, json=data)
        )
        async with SpicerackClient(base_url=BASE_URL) as client:
            result = await client.get_tournaments()

        assert result[0].standings == []

    @respx.mock
    async def test_non_dict_tournament_entry_skipped(self):
        """Non-dict entries in the tournament array are skipped."""
        data = ["not a dict", {"TID": "2", "tournamentName": "Valid"}]
        respx.get(f"{BASE_URL}/api/export-decklists/").mock(
            return_value=httpx.Response(200, json=data)
        )
        async with SpicerackClient(base_url=BASE_URL) as client:
            result = await client.get_tournaments()

        assert len(result) == 1
        assert result[0].tournament_id == "2"


class TestCaching:
    """Tests for TTL cache behavior."""

    @respx.mock
    async def test_second_call_uses_cache(self):
        """Second identical call returns cached result without HTTP request."""
        fixture = _load_fixture("tournaments_legacy.json")
        respx.get(f"{BASE_URL}/api/export-decklists/").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with SpicerackClient(base_url=BASE_URL) as client:
            result1 = await client.get_tournaments()
            result2 = await client.get_tournaments()

        assert result1 == result2
        assert len(respx.calls) == 1  # Only one HTTP call

    @respx.mock
    async def test_different_params_cached_separately(self):
        """Different parameters create separate cache entries."""
        fixture = _load_fixture("tournaments_legacy.json")
        empty = _load_fixture("tournaments_empty.json")
        respx.get(f"{BASE_URL}/api/export-decklists/").mock(
            side_effect=[
                httpx.Response(200, json=fixture),
                httpx.Response(200, json=empty),
            ]
        )
        async with SpicerackClient(base_url=BASE_URL) as client:
            result1 = await client.get_tournaments(num_days=14)
            result2 = await client.get_tournaments(num_days=7)

        assert len(result1) == 2
        assert len(result2) == 0
        assert len(respx.calls) == 2

    def test_cache_attribute_exists(self):
        """Cache attribute is accessible for clearing in conftest."""
        assert hasattr(SpicerackClient.get_tournaments, "cache")
        assert isinstance(SpicerackClient.get_tournaments.cache, TTLCache)


class TestApiKeyHeader:
    """Tests for optional X-API-Key header behavior."""

    @respx.mock
    async def test_no_api_key_no_header(self):
        """When api_key is empty, no X-API-Key header is sent."""
        respx.get(f"{BASE_URL}/api/export-decklists/").mock(
            return_value=httpx.Response(200, json=[])
        )
        async with SpicerackClient(base_url=BASE_URL, api_key="") as client:
            await client.get_tournaments()

        request = respx.calls.last.request
        assert "x-api-key" not in {k.lower() for k in request.headers}

    @respx.mock
    async def test_api_key_included_in_header(self):
        """When api_key is set, X-API-Key header is included."""
        respx.get(f"{BASE_URL}/api/export-decklists/").mock(
            return_value=httpx.Response(200, json=[])
        )
        async with SpicerackClient(base_url=BASE_URL, api_key="test-key") as client:
            await client.get_tournaments()

        request = respx.calls.last.request
        assert request.headers.get("x-api-key") == "test-key"
