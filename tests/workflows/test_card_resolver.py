"""Tests for card_resolver — MTGJSON-first resolution with Scryfall fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mtg_mcp_server.services.scryfall import CardNotFoundError
from mtg_mcp_server.workflows.card_resolver import resolve_card


@pytest.fixture
def mock_scryfall():
    client = AsyncMock()
    client.get_card_by_name = AsyncMock()
    return client


@pytest.fixture
def mock_mtgjson():
    client = AsyncMock()
    client.get_card = AsyncMock()
    return client


class TestResolveCard:
    async def test_mtgjson_hit_returns_mtgjson_card(self, mock_mtgjson, mock_scryfall):
        mtgjson_card = AsyncMock(name="Sol Ring")
        mock_mtgjson.get_card.return_value = mtgjson_card

        result = await resolve_card("Sol Ring", mtgjson=mock_mtgjson, scryfall=mock_scryfall)

        assert result is mtgjson_card
        mock_mtgjson.get_card.assert_awaited_once_with("Sol Ring")
        mock_scryfall.get_card_by_name.assert_not_awaited()

    async def test_mtgjson_miss_falls_back_to_scryfall(self, mock_mtgjson, mock_scryfall):
        mock_mtgjson.get_card.return_value = None
        scryfall_card = AsyncMock(name="Sol Ring")
        mock_scryfall.get_card_by_name.return_value = scryfall_card

        result = await resolve_card("Sol Ring", mtgjson=mock_mtgjson, scryfall=mock_scryfall)

        assert result is scryfall_card
        mock_mtgjson.get_card.assert_awaited_once()
        mock_scryfall.get_card_by_name.assert_awaited_once_with("Sol Ring")

    async def test_need_prices_skips_mtgjson(self, mock_mtgjson, mock_scryfall):
        scryfall_card = AsyncMock(name="Sol Ring")
        mock_scryfall.get_card_by_name.return_value = scryfall_card

        result = await resolve_card(
            "Sol Ring", mtgjson=mock_mtgjson, scryfall=mock_scryfall, need_prices=True
        )

        assert result is scryfall_card
        mock_mtgjson.get_card.assert_not_awaited()

    async def test_mtgjson_none_uses_scryfall(self, mock_scryfall):
        scryfall_card = AsyncMock(name="Sol Ring")
        mock_scryfall.get_card_by_name.return_value = scryfall_card

        result = await resolve_card("Sol Ring", mtgjson=None, scryfall=mock_scryfall)

        assert result is scryfall_card
        mock_scryfall.get_card_by_name.assert_awaited_once_with("Sol Ring")

    async def test_scryfall_not_found_propagates(self, mock_scryfall):
        mock_scryfall.get_card_by_name.side_effect = CardNotFoundError("Not found")

        with pytest.raises(CardNotFoundError):
            await resolve_card("Nonexistent", mtgjson=None, scryfall=mock_scryfall)
