"""Tests for the Scryfall service client."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from mtg_mcp.services.scryfall import CardNotFoundError, ScryfallClient, ScryfallError
from mtg_mcp.types import Card, CardSearchResult, Ruling

FIXTURES = Path(__file__).parent.parent / "fixtures" / "scryfall"
BASE_URL = "https://api.scryfall.com"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class TestGetCardByName:
    @respx.mock
    async def test_exact_match(self):
        fixture = _load_fixture("card_muldrotha.json")
        respx.get(f"{BASE_URL}/cards/named", params={"exact": "Muldrotha, the Gravetide"}).mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with ScryfallClient(base_url=BASE_URL) as client:
            card = await client.get_card_by_name("Muldrotha, the Gravetide")

        assert isinstance(card, Card)
        assert card.name == "Muldrotha, the Gravetide"
        assert card.mana_cost == "{3}{B}{G}{U}"
        assert card.cmc == 6.0
        assert card.type_line == "Legendary Creature \u2014 Elemental Avatar"
        assert card.colors == ["B", "G", "U"]
        assert card.power == "6"
        assert card.toughness == "6"
        assert card.rarity == "mythic"
        assert card.prices.usd == "0.57"
        assert card.edhrec_rank == 1140

    @respx.mock
    async def test_fuzzy_match(self):
        fixture = _load_fixture("card_muldrotha.json")
        respx.get(f"{BASE_URL}/cards/named", params={"fuzzy": "muldrotha"}).mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with ScryfallClient(base_url=BASE_URL) as client:
            card = await client.get_card_by_name("muldrotha", fuzzy=True)

        assert card.name == "Muldrotha, the Gravetide"

    @respx.mock
    async def test_not_found_raises(self):
        fixture = _load_fixture("card_not_found.json")
        respx.get(f"{BASE_URL}/cards/named", params={"exact": "Xyzzy"}).mock(
            return_value=httpx.Response(404, json=fixture)
        )
        async with ScryfallClient(base_url=BASE_URL) as client:
            with pytest.raises(CardNotFoundError, match="Xyzzy"):
                await client.get_card_by_name("Xyzzy")


class TestSearchCards:
    @respx.mock
    async def test_returns_search_result(self):
        fixture = _load_fixture("search_sultai_commander.json")
        respx.get(
            f"{BASE_URL}/cards/search",
            params={"q": "f:commander id:sultai t:creature", "page": "1"},
        ).mock(return_value=httpx.Response(200, json=fixture))
        async with ScryfallClient(base_url=BASE_URL) as client:
            result = await client.search_cards("f:commander id:sultai t:creature")

        assert isinstance(result, CardSearchResult)
        assert result.total_cards == 9273
        assert result.has_more is True
        assert len(result.data) == 3
        assert all(isinstance(c, Card) for c in result.data)

    @respx.mock
    async def test_search_not_found_raises(self):
        respx.get(f"{BASE_URL}/cards/search", params={"q": "xyzzy_nonexistent", "page": "1"}).mock(
            return_value=httpx.Response(
                404,
                json={
                    "object": "error",
                    "code": "not_found",
                    "status": 404,
                    "details": "No cards found",
                },
            )
        )
        async with ScryfallClient(base_url=BASE_URL) as client:
            with pytest.raises(CardNotFoundError):
                await client.search_cards("xyzzy_nonexistent")


class TestGetCardById:
    @respx.mock
    async def test_returns_card(self):
        fixture = _load_fixture("card_sol_ring.json")
        card_id = fixture["id"]
        respx.get(f"{BASE_URL}/cards/{card_id}").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with ScryfallClient(base_url=BASE_URL) as client:
            card = await client.get_card_by_id(card_id)

        assert isinstance(card, Card)
        assert card.name == "Sol Ring"


class TestGetRulings:
    @respx.mock
    async def test_returns_rulings(self):
        fixture = _load_fixture("rulings_muldrotha.json")
        card_id = "705b4d97-2f50-47f7-9053-d748f4337553"
        respx.get(f"{BASE_URL}/cards/{card_id}/rulings").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with ScryfallClient(base_url=BASE_URL) as client:
            rulings = await client.get_rulings(card_id)

        assert len(rulings) == 8
        assert all(isinstance(r, Ruling) for r in rulings)
        assert rulings[0].source == "wotc"
        assert "2020-11-10" in rulings[0].published_at


class TestScryfallServerErrors:
    @respx.mock
    async def test_500_raises_scryfall_error(self):
        respx.get(f"{BASE_URL}/cards/named", params={"exact": "Sol Ring"}).mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        async with ScryfallClient(base_url=BASE_URL) as client:
            with pytest.raises(ScryfallError):
                await client.get_card_by_name("Sol Ring")
