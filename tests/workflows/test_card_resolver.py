"""Tests for card_resolver — bulk-data-first resolution with Scryfall fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mtg_mcp_server.services.base import ServiceError
from mtg_mcp_server.services.scryfall import CardNotFoundError
from mtg_mcp_server.services.scryfall_bulk import ScryfallBulkError
from mtg_mcp_server.workflows.card_resolver import resolve_card, resolve_cards


@pytest.fixture
def mock_scryfall():
    """Provide a mock ScryfallClient with get_card_by_name method."""
    client = AsyncMock()
    client.get_card_by_name = AsyncMock()
    return client


@pytest.fixture
def mock_bulk():
    """Provide a mock ScryfallBulkClient with get_card/get_cards methods."""
    client = AsyncMock()
    client.get_card = AsyncMock()
    client.get_cards = AsyncMock(return_value={})
    return client


class TestResolveCard:
    """Tests for the resolve_card utility function."""

    async def test_bulk_hit_returns_card(self, mock_bulk, mock_scryfall):
        """Bulk data card returned directly when found, Scryfall not called."""
        bulk_card = AsyncMock(name="Sol Ring")
        mock_bulk.get_card.return_value = bulk_card

        result = await resolve_card("Sol Ring", bulk=mock_bulk, scryfall=mock_scryfall)

        assert result is bulk_card
        mock_bulk.get_card.assert_awaited_once_with("Sol Ring")
        mock_scryfall.get_card_by_name.assert_not_awaited()

    async def test_bulk_miss_falls_back_to_scryfall(self, mock_bulk, mock_scryfall):
        """Falls back to Scryfall when bulk data returns None."""
        mock_bulk.get_card.return_value = None
        scryfall_card = AsyncMock(name="Sol Ring")
        mock_scryfall.get_card_by_name.return_value = scryfall_card

        result = await resolve_card("Sol Ring", bulk=mock_bulk, scryfall=mock_scryfall)

        assert result is scryfall_card
        mock_bulk.get_card.assert_awaited_once()
        mock_scryfall.get_card_by_name.assert_awaited_once_with("Sol Ring")

    async def test_bulk_none_uses_scryfall(self, mock_scryfall):
        """Uses Scryfall directly when bulk client is None (disabled)."""
        scryfall_card = AsyncMock(name="Sol Ring")
        mock_scryfall.get_card_by_name.return_value = scryfall_card

        result = await resolve_card("Sol Ring", bulk=None, scryfall=mock_scryfall)

        assert result is scryfall_card
        mock_scryfall.get_card_by_name.assert_awaited_once_with("Sol Ring")

    async def test_scryfall_not_found_propagates(self, mock_scryfall):
        """CardNotFoundError from Scryfall propagates to caller."""
        mock_scryfall.get_card_by_name.side_effect = CardNotFoundError("Not found")

        with pytest.raises(CardNotFoundError):
            await resolve_card("Nonexistent", bulk=None, scryfall=mock_scryfall)

    async def test_bulk_error_falls_back_to_scryfall(self, mock_bulk, mock_scryfall):
        """ScryfallBulkError from bulk client falls back to Scryfall."""
        mock_bulk.get_card.side_effect = ScryfallBulkError("Download failed")
        scryfall_card = AsyncMock(name="Sol Ring")
        mock_scryfall.get_card_by_name.return_value = scryfall_card

        result = await resolve_card("Sol Ring", bulk=mock_bulk, scryfall=mock_scryfall)

        assert result is scryfall_card
        mock_scryfall.get_card_by_name.assert_awaited_once_with("Sol Ring")


class TestResolveCards:
    """Tests for resolve_cards — the batch counterpart of resolve_card.

    Must mirror resolve_card's degradation semantics: bulk error or bulk
    miss for any card falls back to Scryfall for that card; a card not
    found anywhere maps to None (never raises).
    """

    async def test_bulk_batch_hit_skips_scryfall(self, mock_bulk, mock_scryfall):
        """Bulk batch hit returns cards directly; Scryfall never called."""
        bulk_card = AsyncMock(name="Sol Ring")
        mock_bulk.get_cards.return_value = {"Sol Ring": bulk_card}

        result = await resolve_cards(["Sol Ring"], bulk=mock_bulk, scryfall=mock_scryfall)

        assert result == {"Sol Ring": bulk_card}
        mock_bulk.get_cards.assert_awaited_once_with(["Sol Ring"])
        mock_scryfall.get_card_by_name.assert_not_awaited()

    async def test_bulk_error_falls_back_to_scryfall(self, mock_bulk, mock_scryfall):
        """ScryfallBulkError from the batch lookup falls back per name."""
        mock_bulk.get_cards.side_effect = ScryfallBulkError("Download failed")
        scryfall_card = AsyncMock(name="Sol Ring")
        mock_scryfall.get_card_by_name.return_value = scryfall_card

        result = await resolve_cards(["Sol Ring"], bulk=mock_bulk, scryfall=mock_scryfall)

        assert result == {"Sol Ring": scryfall_card}
        mock_scryfall.get_card_by_name.assert_awaited_once_with("Sol Ring")

    async def test_bulk_miss_falls_back_to_scryfall(self, mock_bulk, mock_scryfall):
        """A card missing from the bulk batch is fetched from Scryfall."""
        bulk_card = AsyncMock(name="Sol Ring")
        scryfall_card = AsyncMock(name="New Card")
        mock_bulk.get_cards.return_value = {"Sol Ring": bulk_card, "New Card": None}
        mock_scryfall.get_card_by_name.return_value = scryfall_card

        result = await resolve_cards(
            ["Sol Ring", "New Card"], bulk=mock_bulk, scryfall=mock_scryfall
        )

        assert result == {"Sol Ring": bulk_card, "New Card": scryfall_card}
        mock_scryfall.get_card_by_name.assert_awaited_once_with("New Card")

    async def test_duplicate_names_fetch_fallback_once(self, mock_bulk, mock_scryfall):
        """Duplicate input names collapse to one Scryfall fallback fetch.

        Decklists repeat card names; each distinct name must hit Scryfall
        at most once regardless of how many times it appears.
        """
        mock_bulk.get_cards.side_effect = ScryfallBulkError("Download failed")
        scryfall_card = AsyncMock(name="Sol Ring")
        bolt_card = AsyncMock(name="Lightning Bolt")

        def _by_name(name: str):
            return bolt_card if name == "Lightning Bolt" else scryfall_card

        mock_scryfall.get_card_by_name.side_effect = _by_name

        result = await resolve_cards(
            ["Sol Ring", "Lightning Bolt", "Sol Ring"],
            bulk=mock_bulk,
            scryfall=mock_scryfall,
        )

        assert result["Sol Ring"] is scryfall_card
        assert result["Lightning Bolt"] is bolt_card
        assert mock_scryfall.get_card_by_name.await_count == 2

    async def test_not_found_anywhere_maps_to_none(self, mock_bulk, mock_scryfall):
        """CardNotFoundError from Scryfall maps to None instead of raising."""
        mock_bulk.get_cards.return_value = {"Ghost": None}
        mock_scryfall.get_card_by_name.side_effect = CardNotFoundError("Not found")

        result = await resolve_cards(["Ghost"], bulk=mock_bulk, scryfall=mock_scryfall)

        assert result == {"Ghost": None}

    async def test_scryfall_api_error_maps_to_none(self, mock_bulk, mock_scryfall):
        """Other ServiceErrors from Scryfall map to None instead of raising."""
        mock_bulk.get_cards.return_value = {"Ghost": None}
        mock_scryfall.get_card_by_name.side_effect = ServiceError("HTTP 503")

        result = await resolve_cards(["Ghost"], bulk=mock_bulk, scryfall=mock_scryfall)

        assert result == {"Ghost": None}

    async def test_bulk_none_uses_scryfall(self, mock_scryfall):
        """Bulk disabled (None) resolves every name via Scryfall."""
        scryfall_card = AsyncMock(name="Sol Ring")
        mock_scryfall.get_card_by_name.return_value = scryfall_card

        result = await resolve_cards(["Sol Ring"], bulk=None, scryfall=mock_scryfall)

        assert result == {"Sol Ring": scryfall_card}
        mock_scryfall.get_card_by_name.assert_awaited_once_with("Sol Ring")

    async def test_keys_preserve_input_casing(self, mock_bulk, mock_scryfall):
        """Returned dict keys preserve the caller's casing, like bulk.get_cards."""
        bulk_card = AsyncMock(name="Sol Ring")
        mock_bulk.get_cards.return_value = {"sol ring": bulk_card}

        result = await resolve_cards(["sol ring"], bulk=mock_bulk, scryfall=mock_scryfall)

        assert result == {"sol ring": bulk_card}
