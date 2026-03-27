"""Tests for the Scryfall bulk card data service."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import respx

from mtg_mcp_server.services.scryfall_bulk import (
    ScryfallBulkClient,
    ScryfallBulkDownloadError,
    ScryfallBulkError,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "scryfall_bulk"

_BASE_URL = "https://api.scryfall.com"
_DOWNLOAD_URL = "https://data.scryfall.io/oracle-cards/oracle-cards-20260326090226.json"


def _load_metadata() -> dict:
    """Load the bulk-data metadata fixture."""
    return json.loads((FIXTURES / "bulk_metadata.json").read_text())


def _load_oracle_cards() -> str:
    """Load the oracle cards sample fixture as a JSON string."""
    return (FIXTURES / "oracle_cards_sample.json").read_text()


def _load_oracle_cards_bytes() -> bytes:
    """Load the oracle cards sample fixture as bytes (for HTTP response body)."""
    return (FIXTURES / "oracle_cards_sample.json").read_bytes()


# ---------------------------------------------------------------------------
# Helpers for respx-based mocking
# ---------------------------------------------------------------------------


def _mock_metadata_route(
    router: respx.MockRouter,
    metadata: dict | None = None,
    status_code: int = 200,
) -> respx.Route:
    """Register a metadata endpoint route."""
    meta = metadata or _load_metadata()
    return router.get(f"{_BASE_URL}/bulk-data/oracle_cards").mock(
        return_value=httpx.Response(status_code, json=meta)
    )


def _mock_download_route(
    router: respx.MockRouter,
    url: str = _DOWNLOAD_URL,
    content: bytes | None = None,
    status_code: int = 200,
    headers: dict | None = None,
) -> respx.Route:
    """Register a bulk data download route."""
    body = content if content is not None else _load_oracle_cards_bytes()
    resp_headers = headers or {}
    return router.get(url).mock(
        return_value=httpx.Response(status_code, content=body, headers=resp_headers)
    )


@pytest.fixture
async def loaded_client():
    """A client with pre-loaded fixture data (respx mocked HTTP)."""
    with respx.mock:
        _mock_metadata_route(respx)
        _mock_download_route(respx, headers={"ETag": '"abc123"'})

        client = ScryfallBulkClient(base_url=_BASE_URL, refresh_hours=24)
        async with client:
            await client.ensure_loaded()
            yield client


# ===========================================================================
# Test Classes
# ===========================================================================


class TestLazyLoading:
    """Test that data is not downloaded until first access."""

    async def test_no_download_on_aenter(self):
        """Creating and entering the client should NOT trigger a download."""
        client = ScryfallBulkClient(base_url=_BASE_URL, refresh_hours=24)
        async with client:
            assert client._loaded_at == 0.0
            assert len(client._cards) == 0

    async def test_first_get_card_triggers_download(self):
        """First card lookup triggers the bulk data download."""
        with respx.mock:
            meta_route = _mock_metadata_route(respx)
            dl_route = _mock_download_route(respx, headers={"ETag": '"abc123"'})

            client = ScryfallBulkClient(base_url=_BASE_URL, refresh_hours=24)
            async with client:
                result = await client.get_card("Sol Ring")
                assert result is not None
                assert result.name == "Sol Ring"
                assert meta_route.called
                assert dl_route.called


class TestStaleness:
    """Test that fresh data skips download and stale triggers re-fetch."""

    async def test_fresh_data_skips_download(self):
        """Data within refresh_hours is not re-downloaded."""
        with respx.mock:
            meta_route = _mock_metadata_route(respx)
            _mock_download_route(respx, headers={"ETag": '"abc123"'})

            client = ScryfallBulkClient(base_url=_BASE_URL, refresh_hours=24)
            async with client:
                await client.ensure_loaded()
                assert meta_route.call_count == 1

                # Second call should skip
                await client.ensure_loaded()
                assert meta_route.call_count == 1

    async def test_stale_data_triggers_refetch(self):
        """Data older than refresh_hours triggers a re-download."""
        with respx.mock:
            meta_route = _mock_metadata_route(respx)
            _mock_download_route(respx, headers={"ETag": '"abc123"'})

            client = ScryfallBulkClient(base_url=_BASE_URL, refresh_hours=1)
            async with client:
                await client.ensure_loaded()
                assert meta_route.call_count == 1

                # Simulate stale timestamp (2 hours ago)
                client._loaded_at = time.monotonic() - 7200

                await client.ensure_loaded()
                assert meta_route.call_count == 2


class TestRefreshFailure:
    """Test failure behavior: first-load propagates, refresh-failure serves stale."""

    async def test_first_load_download_error_propagates(self):
        """If the very first download fails, the error propagates."""
        with respx.mock:
            _mock_metadata_route(respx)
            _mock_download_route(respx, status_code=500, content=b"")

            client = ScryfallBulkClient(base_url=_BASE_URL, refresh_hours=24)
            async with client:
                with pytest.raises(ScryfallBulkDownloadError):
                    await client.ensure_loaded()

    async def test_first_load_metadata_error_propagates(self):
        """If the metadata fetch fails on first load, the error propagates."""
        with respx.mock:
            _mock_metadata_route(respx, status_code=500)

            client = ScryfallBulkClient(base_url=_BASE_URL, refresh_hours=24)
            async with client:
                with pytest.raises(ScryfallBulkDownloadError):
                    await client.ensure_loaded()

    async def test_refresh_failure_serves_stale_data(self):
        """If data was loaded but refresh fails, serve stale data."""
        with respx.mock:
            _mock_metadata_route(respx)
            _mock_download_route(respx, headers={"ETag": '"abc123"'})

            client = ScryfallBulkClient(base_url=_BASE_URL, refresh_hours=1)
            async with client:
                # First: successful load
                await client.ensure_loaded()
                assert len(client._cards) > 0

                # Simulate stale + failed refresh by clearing routes and
                # re-registering with 503
                respx.reset()
                _mock_metadata_route(respx, status_code=503)

                loaded_at = client._loaded_at
                stale_time = loaded_at + 7200

                with patch(
                    "mtg_mcp_server.services.scryfall_bulk.time.monotonic",
                    return_value=stale_time,
                ):
                    # Should NOT raise — serves stale data
                    await client.ensure_loaded()

                # Stale data should still be available
                card = await client.get_card("Sol Ring")
                assert card is not None
                assert card.name == "Sol Ring"


class TestETag:
    """Test ETag-based conditional download (304 = skip re-parse)."""

    async def test_etag_saved_from_response(self):
        """ETag from the download response is saved for subsequent requests."""
        with respx.mock:
            _mock_metadata_route(respx)
            _mock_download_route(respx, headers={"ETag": '"my-etag-value"'})

            client = ScryfallBulkClient(base_url=_BASE_URL, refresh_hours=24)
            async with client:
                await client.ensure_loaded()
                assert client._etag == '"my-etag-value"'

    async def test_304_response_skips_reparse(self):
        """304 Not Modified response skips re-parsing data."""
        with respx.mock:
            metadata = _load_metadata()
            _mock_metadata_route(respx, metadata=metadata)
            _mock_download_route(respx, headers={"ETag": '"etag-v1"'})

            client = ScryfallBulkClient(base_url=_BASE_URL, refresh_hours=1)
            async with client:
                await client.ensure_loaded()
                original_count = len(client._unique_cards)
                original_loaded_at = client._loaded_at

                # Simulate stale
                client._loaded_at = time.monotonic() - 7200

                # Swap routes: return 304 on re-fetch
                respx.reset()
                _mock_metadata_route(respx, metadata=metadata)
                _mock_download_route(
                    respx,
                    status_code=304,
                    content=b"",
                    headers={},
                )

                await client.ensure_loaded()
                # Data should NOT have been cleared
                assert len(client._unique_cards) == original_count
                # loaded_at should have been refreshed
                assert client._loaded_at > original_loaded_at

    async def test_etag_only_sent_when_url_matches(self):
        """ETag is only sent when the download URL matches the previous one."""
        metadata_v1 = _load_metadata()
        metadata_v2 = _load_metadata()
        metadata_v2["download_uri"] = "https://data.scryfall.io/oracle-cards/oracle-cards-v2.json"

        with respx.mock:
            # First load with URL v1
            _mock_metadata_route(respx, metadata=metadata_v1)
            _mock_download_route(
                respx, url=metadata_v1["download_uri"], headers={"ETag": '"etag-v1"'}
            )

            client = ScryfallBulkClient(base_url=_BASE_URL, refresh_hours=1)
            async with client:
                await client.ensure_loaded()
                assert client._etag == '"etag-v1"'

        # Simulate stale, metadata now points to a different URL
        client._loaded_at = time.monotonic() - 7200

        with respx.mock:
            _mock_metadata_route(respx, metadata=metadata_v2)
            dl_route = _mock_download_route(
                respx,
                url=metadata_v2["download_uri"],
                headers={"ETag": '"etag-v2"'},
            )

            async with client:
                await client.ensure_loaded()
                # Should have fetched the new URL without If-None-Match
                assert dl_route.called
                req = dl_route.calls[0].request
                assert "If-None-Match" not in req.headers
                # ETag should now be v2
                assert client._etag == '"etag-v2"'


class TestConcurrency:
    """Test that multiple concurrent ensure_loaded() calls only download once."""

    async def test_concurrent_ensure_loaded_only_downloads_once(self):
        """Multiple concurrent ensure_loaded() calls only download once (lock)."""
        with respx.mock:
            meta_route = _mock_metadata_route(respx)
            dl_route = _mock_download_route(respx, headers={"ETag": '"abc"'})

            client = ScryfallBulkClient(base_url=_BASE_URL, refresh_hours=24)
            async with client:
                # Launch 5 concurrent ensure_loaded calls
                await asyncio.gather(
                    client.ensure_loaded(),
                    client.ensure_loaded(),
                    client.ensure_loaded(),
                    client.ensure_loaded(),
                    client.ensure_loaded(),
                )
                # Only one download should have happened
                assert meta_route.call_count == 1
                assert dl_route.call_count == 1


class TestParsing:
    """Test that the bulk data is parsed correctly into Card models."""

    async def test_correct_card_count(self, loaded_client: ScryfallBulkClient):
        """8 playable cards (4 non-playable layouts filtered), 9 dict entries for DFC."""
        assert len(loaded_client._unique_cards) == 8
        # 8 normal keys + 1 extra for DFC front-face-only key
        assert len(loaded_client._cards) == 9

    async def test_card_has_prices(self, loaded_client: ScryfallBulkClient):
        """Parsed cards have price data."""
        card = await loaded_client.get_card("Sol Ring")
        assert card is not None
        assert card.prices.usd == "1.50"
        assert card.prices.usd_foil == "3.00"

    async def test_card_has_legalities(self, loaded_client: ScryfallBulkClient):
        """Parsed cards have legality data."""
        card = await loaded_client.get_card("Sol Ring")
        assert card is not None
        assert card.legalities["commander"] == "legal"
        assert card.legalities["legacy"] == "banned"

    async def test_card_has_edhrec_rank(self, loaded_client: ScryfallBulkClient):
        """Parsed cards have EDHREC rank."""
        card = await loaded_client.get_card("Sol Ring")
        assert card is not None
        assert card.edhrec_rank == 1

    async def test_card_without_edhrec_rank(self, loaded_client: ScryfallBulkClient):
        """Cards without edhrec_rank (like Forest) have None."""
        card = await loaded_client.get_card("Forest")
        assert card is not None
        assert card.edhrec_rank is None


class TestLayoutFiltering:
    """Test that non-playable card layouts are excluded from parsed data."""

    async def test_minigame_excluded(self, loaded_client: ScryfallBulkClient):
        """Minigame Sol Ring (acmm) is filtered; real Sol Ring returned."""
        card = await loaded_client.get_card("Sol Ring")
        assert card is not None
        assert card.set_code != "acmm"
        assert card.layout == "normal"
        assert card.type_line == "Artifact"

    async def test_art_series_excluded(self, loaded_client: ScryfallBulkClient):
        """Art series Lightning Bolt is filtered; real Lightning Bolt returned."""
        card = await loaded_client.get_card("Lightning Bolt")
        assert card is not None
        assert card.set_code != "sld"
        assert card.layout == "normal"
        assert card.type_line == "Instant"

    async def test_token_excluded(self, loaded_client: ScryfallBulkClient):
        """Token Forest is filtered; real Basic Land returned."""
        card = await loaded_client.get_card("Forest")
        assert card is not None
        assert "Basic Land" in card.type_line

    async def test_emblem_excluded(self, loaded_client: ScryfallBulkClient):
        """Emblem cards are filtered and not searchable."""
        results = await loaded_client.search_cards("Emblem")
        assert len(results) == 0

    async def test_real_card_preserved_despite_collision(self, loaded_client: ScryfallBulkClient):
        """Sol Ring retains correct data despite minigame entry later in fixture."""
        card = await loaded_client.get_card("Sol Ring")
        assert card is not None
        assert card.prices.usd == "1.50"
        assert card.legalities["commander"] == "legal"
        assert card.edhrec_rank == 1

    async def test_excluded_layouts_constant(self):
        """All 6 non-playable layouts are in the exclusion set."""
        from mtg_mcp_server.services.scryfall_bulk import _EXCLUDED_LAYOUTS

        expected = {
            "art_series",
            "double_faced_token",
            "emblem",
            "minigame",
            "placeholder",
            "token",
        }
        assert expected == _EXCLUDED_LAYOUTS

    async def test_layout_field_populated(self, loaded_client: ScryfallBulkClient):
        """Parsed cards have the layout field populated from Scryfall data."""
        card = await loaded_client.get_card("Sol Ring")
        assert card is not None
        assert card.layout == "normal"

        dfc = await loaded_client.get_card("Delver of Secrets")
        assert dfc is not None
        assert dfc.layout == "transform"


class TestDFC:
    """Test double-faced card handling."""

    async def test_dfc_accessible_by_full_name(self, loaded_client: ScryfallBulkClient):
        """DFC is accessible by full '// ' name."""
        card = await loaded_client.get_card("Delver of Secrets // Insectile Aberration")
        assert card is not None
        assert card.name == "Delver of Secrets // Insectile Aberration"

    async def test_dfc_accessible_by_front_face(self, loaded_client: ScryfallBulkClient):
        """DFC is accessible by front-face name only."""
        card = await loaded_client.get_card("Delver of Secrets")
        assert card is not None
        assert card.name == "Delver of Secrets // Insectile Aberration"

    async def test_dfc_not_duplicated_in_unique_cards(self, loaded_client: ScryfallBulkClient):
        """DFC should appear only once in _unique_cards."""
        delver_count = sum(1 for c in loaded_client._unique_cards if "Delver" in c.name)
        assert delver_count == 1

    async def test_dfc_has_front_face_data(self, loaded_client: ScryfallBulkClient):
        """DFC has oracle_text from front face (via _fill_from_card_faces)."""
        card = await loaded_client.get_card("Delver of Secrets")
        assert card is not None
        assert card.oracle_text is not None
        assert "transform" in card.oracle_text.lower()


class TestGetCard:
    """Test exact card lookup."""

    async def test_case_insensitive(self, loaded_client: ScryfallBulkClient):
        """Lookup is case-insensitive."""
        result = await loaded_client.get_card("sol ring")
        assert result is not None
        assert result.name == "Sol Ring"

    async def test_mixed_case(self, loaded_client: ScryfallBulkClient):
        """All-uppercase input resolves correctly."""
        result = await loaded_client.get_card("SOL RING")
        assert result is not None
        assert result.name == "Sol Ring"

    async def test_not_found_returns_none(self, loaded_client: ScryfallBulkClient):
        """Nonexistent card name returns None."""
        result = await loaded_client.get_card("Nonexistent Card")
        assert result is None

    async def test_legendary_creature(self, loaded_client: ScryfallBulkClient):
        """Legendary creature lookup includes power and toughness."""
        result = await loaded_client.get_card("Muldrotha, the Gravetide")
        assert result is not None
        assert result.power == "6"
        assert result.toughness == "6"
        assert result.cmc == 6.0

    async def test_special_characters(self, loaded_client: ScryfallBulkClient):
        """Card with non-ASCII characters is found correctly."""
        result = await loaded_client.get_card("Jötun Grunt")
        assert result is not None
        assert result.name == "Jötun Grunt"

    async def test_basic_land(self, loaded_client: ScryfallBulkClient):
        """Basic land has no colors and no power/toughness."""
        result = await loaded_client.get_card("Forest")
        assert result is not None
        assert result.type_line == "Basic Land — Forest"
        assert result.colors == []
        assert result.power is None
        assert result.toughness is None


class TestSearchCards:
    """Test name substring search."""

    async def test_search_by_name(self, loaded_client: ScryfallBulkClient):
        """Substring match on card name returns matching cards."""
        results = await loaded_client.search_cards("ring")
        assert len(results) == 1
        assert results[0].name == "Sol Ring"

    async def test_search_case_insensitive(self, loaded_client: ScryfallBulkClient):
        """Name search is case-insensitive."""
        results = await loaded_client.search_cards("BOLT")
        assert len(results) == 1
        assert results[0].name == "Lightning Bolt"

    async def test_search_no_results(self, loaded_client: ScryfallBulkClient):
        """Search with no matches returns an empty list."""
        results = await loaded_client.search_cards("xyzzynonexistent")
        assert results == []

    async def test_search_limit(self, loaded_client: ScryfallBulkClient):
        """Limit parameter caps the number of returned results."""
        results = await loaded_client.search_cards("", limit=3)
        assert len(results) == 3

    async def test_search_partial_match(self, loaded_client: ScryfallBulkClient):
        """Partial name substring matches cards containing that text."""
        results = await loaded_client.search_cards("counter")
        assert len(results) >= 1
        names = [r.name for r in results]
        assert "Counterspell" in names


class TestSearchByType:
    """Test type line substring search."""

    async def test_search_creature(self, loaded_client: ScryfallBulkClient):
        """Type search for 'Creature' includes creatures and excludes non-creatures."""
        results = await loaded_client.search_by_type("Creature")
        names = [r.name for r in results]
        assert "Spore Frog" in names
        assert "Sol Ring" not in names

    async def test_search_instant(self, loaded_client: ScryfallBulkClient):
        """Type search for 'Instant' returns instants."""
        results = await loaded_client.search_by_type("Instant")
        names = [r.name for r in results]
        assert "Lightning Bolt" in names
        assert "Counterspell" in names

    async def test_search_no_match(self, loaded_client: ScryfallBulkClient):
        """Type search with no matching cards returns empty list."""
        results = await loaded_client.search_by_type("Planeswalker")
        assert results == []


class TestSearchByText:
    """Test oracle text substring search."""

    async def test_search_damage(self, loaded_client: ScryfallBulkClient):
        """Oracle text search for 'damage' returns cards mentioning damage."""
        results = await loaded_client.search_by_text("damage")
        names = [r.name for r in results]
        assert "Lightning Bolt" in names
        assert "Spore Frog" in names

    async def test_search_counter(self, loaded_client: ScryfallBulkClient):
        """Oracle text search for 'Counter target spell' finds counterspells."""
        results = await loaded_client.search_by_text("Counter target spell")
        names = [r.name for r in results]
        assert "Counterspell" in names

    async def test_search_no_match(self, loaded_client: ScryfallBulkClient):
        """Text search with no matches returns an empty list."""
        results = await loaded_client.search_by_text("xyzzynonexistent")
        assert results == []


class TestBackgroundRefresh:
    """Test background refresh task lifecycle."""

    async def test_start_creates_task(self):
        """start_background_refresh() creates a background task."""
        client = ScryfallBulkClient(base_url=_BASE_URL, refresh_hours=24)
        async with client:
            client.start_background_refresh()
            assert client._refresh_task is not None
            assert not client._refresh_task.done()
            # Clean up
            client._refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await client._refresh_task

    async def test_aexit_cancels_task(self):
        """__aexit__ cancels the background refresh task."""
        client = ScryfallBulkClient(base_url=_BASE_URL, refresh_hours=24)
        async with client:
            client.start_background_refresh()
            task = client._refresh_task
            assert task is not None
        # After __aexit__, the task should be cancelled
        assert task.cancelled() or task.done()

    async def test_aexit_clears_data(self):
        """__aexit__ clears in-memory card data."""
        with respx.mock:
            _mock_metadata_route(respx)
            _mock_download_route(respx, headers={"ETag": '"abc"'})

            client = ScryfallBulkClient(base_url=_BASE_URL, refresh_hours=24)
            async with client:
                await client.ensure_loaded()
                assert len(client._cards) > 0

            # After __aexit__, data should be cleared
            assert len(client._cards) == 0
            assert len(client._unique_cards) == 0
            assert client._loaded_at == 0.0


class TestExceptionTypes:
    """Test that the correct exception types are raised."""

    async def test_bulk_error_is_service_error(self):
        """ScryfallBulkError inherits from ServiceError."""
        from mtg_mcp_server.services.base import ServiceError

        err = ScryfallBulkError("test")
        assert isinstance(err, ServiceError)
        assert err.status_code is None

    async def test_download_error_is_bulk_error(self):
        """ScryfallBulkDownloadError inherits from ScryfallBulkError."""
        err = ScryfallBulkDownloadError("test")
        assert isinstance(err, ScryfallBulkError)

    async def test_network_error_raises_download_error(self):
        """Network connection failure on metadata raises ScryfallBulkDownloadError."""
        with respx.mock:
            respx.get(f"{_BASE_URL}/bulk-data/oracle_cards").mock(
                side_effect=httpx.ConnectError("Connection refused")
            )

            client = ScryfallBulkClient(base_url=_BASE_URL, refresh_hours=24)
            async with client:
                with pytest.raises(ScryfallBulkDownloadError, match="Network error"):
                    await client.ensure_loaded()

    async def test_download_network_error_raises(self):
        """Network failure during bulk data download raises ScryfallBulkDownloadError."""
        with respx.mock:
            _mock_metadata_route(respx)
            respx.get(_DOWNLOAD_URL).mock(side_effect=httpx.ReadTimeout("Read timed out"))

            client = ScryfallBulkClient(base_url=_BASE_URL, refresh_hours=24)
            async with client:
                with pytest.raises(ScryfallBulkDownloadError, match="Network error"):
                    await client.ensure_loaded()


class TestMetadataValidation:
    """Test metadata response validation and edge cases."""

    async def test_missing_download_uri_raises(self):
        """Missing download_uri key in metadata raises ScryfallBulkError."""
        with respx.mock:
            _mock_metadata_route(respx, metadata={"object": "bulk_data", "type": "oracle_cards"})

            client = ScryfallBulkClient(base_url=_BASE_URL, refresh_hours=24)
            async with client:
                with pytest.raises(ScryfallBulkError, match="missing 'download_uri'"):
                    await client.ensure_loaded()

    async def test_non_json_metadata_raises(self):
        """Non-JSON metadata response raises ScryfallBulkDownloadError."""
        with respx.mock:
            respx.get(f"{_BASE_URL}/bulk-data/oracle_cards").mock(
                return_value=httpx.Response(
                    200, content=b"<html>error</html>", headers={"Content-Type": "text/html"}
                )
            )

            client = ScryfallBulkClient(base_url=_BASE_URL, refresh_hours=24)
            async with client:
                with pytest.raises(ScryfallBulkDownloadError, match="not valid JSON"):
                    await client.ensure_loaded()


class TestParseFailures:
    """Test _parse error handling for malformed data."""

    async def test_non_json_bulk_data_raises(self):
        """Non-JSON bulk data raises ScryfallBulkError on first load."""
        with respx.mock:
            _mock_metadata_route(respx)
            _mock_download_route(respx, content=b"<html>CDN error</html>")

            client = ScryfallBulkClient(base_url=_BASE_URL, refresh_hours=24)
            async with client:
                with pytest.raises(ScryfallBulkError, match="Failed to parse"):
                    await client.ensure_loaded()

    async def test_json_object_instead_of_array_raises(self):
        """JSON object (not array) raises ScryfallBulkError."""
        with respx.mock:
            _mock_metadata_route(respx)
            _mock_download_route(respx, content=b'{"error": "not found"}')

            client = ScryfallBulkClient(base_url=_BASE_URL, refresh_hours=24)
            async with client:
                with pytest.raises(ScryfallBulkError, match="not a JSON array"):
                    await client.ensure_loaded()

    async def test_all_invalid_cards_raises_zero_parsed(self):
        """Array of all-invalid entries raises ScryfallBulkError (zero cards)."""
        bad_data = json.dumps([{"not_a": "card"}, {"also": "bad"}]).encode()
        with respx.mock:
            _mock_metadata_route(respx)
            _mock_download_route(respx, content=bad_data)

            client = ScryfallBulkClient(base_url=_BASE_URL, refresh_hours=24)
            async with client:
                with pytest.raises(ScryfallBulkError, match="Parsed 0 cards"):
                    await client.ensure_loaded()

    async def test_bad_card_skipped_good_cards_loaded(self):
        """A malformed card in the middle is skipped; valid cards still load."""
        sample = json.loads(_load_oracle_cards())
        sample.insert(1, {"not_a": "valid_card"})  # inject bad entry
        with respx.mock:
            _mock_metadata_route(respx)
            _mock_download_route(respx, content=json.dumps(sample).encode())

            client = ScryfallBulkClient(base_url=_BASE_URL, refresh_hours=24)
            async with client:
                await client.ensure_loaded()
                # Original fixture has 8 valid cards
                assert len(client._unique_cards) == 8
                assert await client.get_card("Sol Ring") is not None

    async def test_corrupt_data_on_refresh_serves_stale(self):
        """Corrupt data during refresh serves stale data instead of failing."""
        with respx.mock:
            _mock_metadata_route(respx)
            _mock_download_route(respx, headers={"ETag": '"abc"'})

            client = ScryfallBulkClient(base_url=_BASE_URL, refresh_hours=1)
            async with client:
                await client.ensure_loaded()
                original_count = len(client._unique_cards)
                assert original_count > 0

                # Simulate stale + corrupt download
                respx.reset()
                _mock_metadata_route(respx)
                _mock_download_route(respx, content=b"not json at all")

                loaded_at = client._loaded_at
                stale_time = loaded_at + 7200

                with patch(
                    "mtg_mcp_server.services.scryfall_bulk.time.monotonic",
                    return_value=stale_time,
                ):
                    await client.ensure_loaded()  # Should NOT raise

                # Stale data still available
                assert len(client._unique_cards) == original_count
                assert await client.get_card("Sol Ring") is not None


class TestETagEdgeCases:
    """Test ETag edge cases."""

    async def test_missing_etag_header_leaves_etag_none(self):
        """Response without ETag header does not set _etag."""
        with respx.mock:
            _mock_metadata_route(respx)
            _mock_download_route(respx)  # No ETag header

            client = ScryfallBulkClient(base_url=_BASE_URL, refresh_hours=24)
            async with client:
                await client.ensure_loaded()
                assert client._etag is None


class TestBackgroundRefreshEdgeCases:
    """Test background refresh edge cases."""

    async def test_start_background_refresh_idempotent(self):
        """Calling start_background_refresh twice does not create duplicate tasks."""
        client = ScryfallBulkClient(base_url=_BASE_URL, refresh_hours=24)
        async with client:
            client.start_background_refresh()
            first_task = client._refresh_task
            assert first_task is not None

            client.start_background_refresh()
            assert client._refresh_task is first_task  # Same task, not a new one
