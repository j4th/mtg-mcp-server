"""Tests for card_resolver — bulk-data-first resolution with Scryfall fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mtg_mcp_server.services.scryfall import CardNotFoundError
from mtg_mcp_server.workflows.card_resolver import resolve_card


@pytest.fixture
def mock_scryfall():
    """Provide a mock ScryfallClient with get_card_by_name method."""
    client = AsyncMock()
    client.get_card_by_name = AsyncMock()
    return client


@pytest.fixture
def mock_bulk():
    """Provide a mock ScryfallBulkClient with get_card method."""
    client = AsyncMock()
    client.get_card = AsyncMock()
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
