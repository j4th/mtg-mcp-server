"""Tests for the MTGJSON bulk card data service."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from mtg_mcp.services.mtgjson import MTGJSONClient, MTGJSONDownloadError, MTGJSONError

FIXTURES = Path(__file__).parent.parent / "fixtures" / "mtgjson"

_DATA_URL = "https://example.com/AtomicCards.json.gz"


def _load_fixture_bytes() -> bytes:
    """Load the gzipped fixture file as raw bytes."""
    return (FIXTURES / "atomic_cards_sample.json.gz").read_bytes()


def _mock_httpx_response(content: bytes, status_code: int = 200) -> httpx.Response:
    """Create a mock httpx response with binary content."""
    return httpx.Response(status_code=status_code, content=content)


@pytest.fixture
async def loaded_client():
    """A client with pre-loaded fixture data (mocked HTTP)."""
    fixture_bytes = _load_fixture_bytes()
    client = MTGJSONClient(data_url=_DATA_URL, refresh_hours=24)
    async with client:
        mock_response = _mock_httpx_response(fixture_bytes)
        with patch("mtg_mcp.services.mtgjson.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_response)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_http

            await client.ensure_loaded()
            yield client


class TestLazyLoading:
    """Test that data is not downloaded until first access."""

    async def test_no_download_on_init(self):
        """Creating and entering the client should NOT trigger a download."""
        client = MTGJSONClient(data_url=_DATA_URL, refresh_hours=24)
        async with client:
            # No cards should be loaded yet
            assert client._loaded_at == 0.0

    async def test_first_access_triggers_download(self):
        fixture_bytes = _load_fixture_bytes()
        client = MTGJSONClient(data_url=_DATA_URL, refresh_hours=24)
        async with client:
            mock_response = _mock_httpx_response(fixture_bytes)
            with patch("mtg_mcp.services.mtgjson.httpx.AsyncClient") as mock_cls:
                mock_http = AsyncMock()
                mock_http.get = AsyncMock(return_value=mock_response)
                mock_http.__aenter__ = AsyncMock(return_value=mock_http)
                mock_http.__aexit__ = AsyncMock(return_value=False)
                mock_cls.return_value = mock_http

                result = await client.get_card("Sol Ring")
                assert result is not None
                assert result.name == "Sol Ring"
                mock_http.get.assert_called_once()


class TestDownloadAndParse:
    """Test the download, decompress, and parse pipeline."""

    async def test_downloads_and_parses(self):
        fixture_bytes = _load_fixture_bytes()
        client = MTGJSONClient(data_url=_DATA_URL, refresh_hours=24)
        async with client:
            mock_response = _mock_httpx_response(fixture_bytes)
            with patch("mtg_mcp.services.mtgjson.httpx.AsyncClient") as mock_cls:
                mock_http = AsyncMock()
                mock_http.get = AsyncMock(return_value=mock_response)
                mock_http.__aenter__ = AsyncMock(return_value=mock_http)
                mock_http.__aexit__ = AsyncMock(return_value=False)
                mock_cls.return_value = mock_http

                await client.ensure_loaded()
                assert client._loaded_at > 0
                # 8 cards + 1 extra key for double-faced "Delver of Secrets // ..."
                assert len(client._cards) == 9

    async def test_download_error_raises(self):
        client = MTGJSONClient(data_url=_DATA_URL, refresh_hours=24)
        async with client:
            mock_response = _mock_httpx_response(b"", status_code=500)
            with patch("mtg_mcp.services.mtgjson.httpx.AsyncClient") as mock_cls:
                mock_http = AsyncMock()
                mock_http.get = AsyncMock(return_value=mock_response)
                mock_http.__aenter__ = AsyncMock(return_value=mock_http)
                mock_http.__aexit__ = AsyncMock(return_value=False)
                mock_cls.return_value = mock_http

                with pytest.raises(MTGJSONDownloadError, match="HTTP 500"):
                    await client.ensure_loaded()

    async def test_network_error_raises(self):
        client = MTGJSONClient(data_url=_DATA_URL, refresh_hours=24)
        async with client:
            with patch("mtg_mcp.services.mtgjson.httpx.AsyncClient") as mock_cls:
                mock_http = AsyncMock()
                mock_http.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
                mock_http.__aenter__ = AsyncMock(return_value=mock_http)
                mock_http.__aexit__ = AsyncMock(return_value=False)
                mock_cls.return_value = mock_http

                with pytest.raises(MTGJSONDownloadError, match="Network error"):
                    await client.ensure_loaded()

    async def test_corrupt_gzip_raises(self):
        client = MTGJSONClient(data_url=_DATA_URL, refresh_hours=24)
        async with client:
            mock_response = _mock_httpx_response(b"not-gzip-data")
            with patch("mtg_mcp.services.mtgjson.httpx.AsyncClient") as mock_cls:
                mock_http = AsyncMock()
                mock_http.get = AsyncMock(return_value=mock_response)
                mock_http.__aenter__ = AsyncMock(return_value=mock_http)
                mock_http.__aexit__ = AsyncMock(return_value=False)
                mock_cls.return_value = mock_http

                with pytest.raises(MTGJSONError, match=r"decompress|parse"):
                    await client.ensure_loaded()


class TestRefreshLogic:
    """Test that stale data triggers a re-download."""

    async def test_stale_data_triggers_refresh(self):
        fixture_bytes = _load_fixture_bytes()
        client = MTGJSONClient(data_url=_DATA_URL, refresh_hours=1)
        async with client:
            mock_response = _mock_httpx_response(fixture_bytes)
            with patch("mtg_mcp.services.mtgjson.httpx.AsyncClient") as mock_cls:
                mock_http = AsyncMock()
                mock_http.get = AsyncMock(return_value=mock_response)
                mock_http.__aenter__ = AsyncMock(return_value=mock_http)
                mock_http.__aexit__ = AsyncMock(return_value=False)
                mock_cls.return_value = mock_http

                # First load
                await client.ensure_loaded()
                assert mock_http.get.call_count == 1

                # Simulate stale timestamp (2 hours ago)
                client._loaded_at = time.monotonic() - 7200

                # Second access should re-download
                await client.ensure_loaded()
                assert mock_http.get.call_count == 2

    async def test_fresh_data_does_not_re_download(self):
        fixture_bytes = _load_fixture_bytes()
        client = MTGJSONClient(data_url=_DATA_URL, refresh_hours=24)
        async with client:
            mock_response = _mock_httpx_response(fixture_bytes)
            with patch("mtg_mcp.services.mtgjson.httpx.AsyncClient") as mock_cls:
                mock_http = AsyncMock()
                mock_http.get = AsyncMock(return_value=mock_response)
                mock_http.__aenter__ = AsyncMock(return_value=mock_http)
                mock_http.__aexit__ = AsyncMock(return_value=False)
                mock_cls.return_value = mock_http

                # First load
                await client.ensure_loaded()
                # Second load — should NOT re-download
                await client.ensure_loaded()
                assert mock_http.get.call_count == 1


class TestGetCard:
    """Test exact card lookup."""

    async def test_exact_lookup(self, loaded_client: MTGJSONClient):
        result = await loaded_client.get_card("Sol Ring")
        assert result is not None
        assert result.name == "Sol Ring"
        assert result.mana_cost == "{1}"
        assert result.type_line == "Artifact"
        assert result.oracle_text == "{T}: Add {C}{C}."
        assert result.mana_value == 1.0

    async def test_case_insensitive(self, loaded_client: MTGJSONClient):
        result = await loaded_client.get_card("sol ring")
        assert result is not None
        assert result.name == "Sol Ring"

    async def test_mixed_case(self, loaded_client: MTGJSONClient):
        result = await loaded_client.get_card("SOL RING")
        assert result is not None
        assert result.name == "Sol Ring"

    async def test_not_found_returns_none(self, loaded_client: MTGJSONClient):
        result = await loaded_client.get_card("Nonexistent Card")
        assert result is None

    async def test_legendary_creature(self, loaded_client: MTGJSONClient):
        result = await loaded_client.get_card("Muldrotha, the Gravetide")
        assert result is not None
        assert result.name == "Muldrotha, the Gravetide"
        assert result.power == "6"
        assert result.toughness == "6"
        assert "Legendary" in result.supertypes
        assert "Elemental" in result.subtypes
        assert result.mana_value == 6.0

    async def test_double_faced_card_uses_front_face(self, loaded_client: MTGJSONClient):
        result = await loaded_client.get_card("Delver of Secrets // Insectile Aberration")
        assert result is not None
        assert result.name == "Delver of Secrets"
        assert result.power == "1"
        assert result.toughness == "1"

    async def test_basic_land(self, loaded_client: MTGJSONClient):
        result = await loaded_client.get_card("Forest")
        assert result is not None
        assert result.name == "Forest"
        assert result.type_line == "Basic Land — Forest"
        assert result.colors == []
        assert result.power is None
        assert result.toughness is None

    async def test_special_characters(self, loaded_client: MTGJSONClient):
        result = await loaded_client.get_card("Jötun Grunt")
        assert result is not None
        assert result.name == "Jötun Grunt"
        assert result.power == "4"
        assert result.toughness == "4"


class TestSearchCards:
    """Test name substring search."""

    async def test_search_by_name(self, loaded_client: MTGJSONClient):
        results = await loaded_client.search_cards("ring")
        assert len(results) == 1
        assert results[0].name == "Sol Ring"

    async def test_search_case_insensitive(self, loaded_client: MTGJSONClient):
        results = await loaded_client.search_cards("BOLT")
        assert len(results) == 1
        assert results[0].name == "Lightning Bolt"

    async def test_search_multiple_results(self, loaded_client: MTGJSONClient):
        # "frog" appears in Spore Frog
        results = await loaded_client.search_cards("frog")
        assert len(results) >= 1
        names = [r.name for r in results]
        assert "Spore Frog" in names

    async def test_search_no_results(self, loaded_client: MTGJSONClient):
        results = await loaded_client.search_cards("xyzzynonexistent")
        assert results == []

    async def test_search_limit(self, loaded_client: MTGJSONClient):
        # Search for something that matches many cards
        results = await loaded_client.search_cards("", limit=3)
        assert len(results) == 3

    async def test_search_partial_match(self, loaded_client: MTGJSONClient):
        results = await loaded_client.search_cards("counter")
        assert len(results) >= 1
        names = [r.name for r in results]
        assert "Counterspell" in names


class TestSearchByType:
    """Test type line substring search."""

    async def test_search_creature(self, loaded_client: MTGJSONClient):
        results = await loaded_client.search_by_type("Creature")
        names = [r.name for r in results]
        assert "Spore Frog" in names
        assert "Muldrotha, the Gravetide" in names
        # Non-creatures should be excluded
        assert "Sol Ring" not in names
        assert "Lightning Bolt" not in names

    async def test_search_instant(self, loaded_client: MTGJSONClient):
        results = await loaded_client.search_by_type("Instant")
        names = [r.name for r in results]
        assert "Lightning Bolt" in names
        assert "Counterspell" in names

    async def test_search_legendary(self, loaded_client: MTGJSONClient):
        results = await loaded_client.search_by_type("Legendary")
        names = [r.name for r in results]
        assert "Muldrotha, the Gravetide" in names
        assert len(results) == 1

    async def test_search_no_match(self, loaded_client: MTGJSONClient):
        results = await loaded_client.search_by_type("Planeswalker")
        assert results == []


class TestSearchByText:
    """Test oracle text substring search."""

    async def test_search_by_text(self, loaded_client: MTGJSONClient):
        results = await loaded_client.search_by_text("damage")
        names = [r.name for r in results]
        assert "Lightning Bolt" in names
        assert "Spore Frog" in names  # "combat damage" in its text

    async def test_search_counter(self, loaded_client: MTGJSONClient):
        results = await loaded_client.search_by_text("Counter target spell")
        names = [r.name for r in results]
        assert "Counterspell" in names

    async def test_search_graveyard(self, loaded_client: MTGJSONClient):
        results = await loaded_client.search_by_text("graveyard")
        assert len(results) >= 1
        names = [r.name for r in results]
        assert "Muldrotha, the Gravetide" in names

    async def test_search_no_match(self, loaded_client: MTGJSONClient):
        results = await loaded_client.search_by_text("xyzzynonexistent")
        assert results == []
