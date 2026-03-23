"""Tests for the Commander Spellbook service client."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from mtg_mcp_server.services.spellbook import (
    ComboNotFoundError,
    SpellbookClient,
    SpellbookError,
)
from mtg_mcp_server.types import BracketEstimate, Combo, DecklistCombos

FIXTURES = Path(__file__).parent.parent / "fixtures" / "spellbook"
BASE_URL = "https://backend.commanderspellbook.com"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class TestFindCombos:
    @respx.mock
    async def test_returns_combos(self):
        fixture = _load_fixture("combos_muldrotha.json")
        respx.get(
            f"{BASE_URL}/variants/",
            params={"q": 'card:"Muldrotha, the Gravetide"', "limit": "10"},
        ).mock(return_value=httpx.Response(200, json=fixture))

        async with SpellbookClient(base_url=BASE_URL) as client:
            combos = await client.find_combos("Muldrotha, the Gravetide")

        assert len(combos) == 5
        assert all(isinstance(c, Combo) for c in combos)
        assert combos[0].id == "1414-2730-5131-5256"
        assert combos[0].identity == "BGU"
        assert combos[0].bracket_tag == "E"
        assert len(combos[0].cards) > 0
        assert combos[0].cards[0].name == "Muldrotha, the Gravetide"

    @respx.mock
    async def test_returns_combos_with_color_identity(self):
        fixture = _load_fixture("combos_muldrotha.json")
        respx.get(
            f"{BASE_URL}/variants/",
            params={
                "q": 'card:"Muldrotha, the Gravetide" coloridentity:sultai',
                "limit": "10",
            },
        ).mock(return_value=httpx.Response(200, json=fixture))

        async with SpellbookClient(base_url=BASE_URL) as client:
            combos = await client.find_combos("Muldrotha, the Gravetide", color_identity="sultai")

        assert len(combos) == 5

    @respx.mock
    async def test_empty_results_returns_empty_list(self):
        fixture = _load_fixture("combos_not_found.json")
        respx.get(
            f"{BASE_URL}/variants/",
            params={"q": 'card:"Xyzzy Nonexistent Card"', "limit": "10"},
        ).mock(return_value=httpx.Response(200, json=fixture))

        async with SpellbookClient(base_url=BASE_URL) as client:
            combos = await client.find_combos("Xyzzy Nonexistent Card")

        assert combos == []


class TestGetCombo:
    @respx.mock
    async def test_returns_combo(self):
        fixture = _load_fixture("combo_detail.json")
        combo_id = "1414-2730-5131-5256"
        respx.get(f"{BASE_URL}/variants/{combo_id}/").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        async with SpellbookClient(base_url=BASE_URL) as client:
            combo = await client.get_combo(combo_id)

        assert isinstance(combo, Combo)
        assert combo.id == combo_id
        assert combo.identity == "BGU"
        assert len(combo.cards) == 4
        assert len(combo.produces) > 0
        assert combo.produces[0].feature_name == "Infinite death triggers"

    @respx.mock
    async def test_not_found_raises(self):
        respx.get(f"{BASE_URL}/variants/9999-9999/").mock(
            return_value=httpx.Response(404, json={"detail": "Not found."})
        )

        async with SpellbookClient(base_url=BASE_URL) as client:
            with pytest.raises(ComboNotFoundError, match="9999-9999"):
                await client.get_combo("9999-9999")


class TestFindDecklistCombos:
    @respx.mock
    async def test_returns_decklist_combos(self):
        fixture = _load_fixture("find_my_combos_response.json")
        respx.post(f"{BASE_URL}/find-my-combos").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        async with SpellbookClient(base_url=BASE_URL) as client:
            result = await client.find_decklist_combos(
                commanders=["Muldrotha, the Gravetide"],
                decklist=["Sol Ring", "Spore Frog", "Altar of Dementia"],
            )

        assert isinstance(result, DecklistCombos)
        assert result.identity == "BGU"
        # The fixture has 0 included and 3 almost-included (trimmed)
        assert isinstance(result.included, list)
        assert isinstance(result.almost_included, list)


class TestEstimateBracket:
    @respx.mock
    async def test_returns_bracket_estimate(self):
        fixture = _load_fixture("estimate_bracket_response.json")
        respx.post(f"{BASE_URL}/estimate-bracket").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        async with SpellbookClient(base_url=BASE_URL) as client:
            result = await client.estimate_bracket(
                commanders=["Muldrotha, the Gravetide"],
                decklist=["Sol Ring", "Spore Frog"],
            )

        assert isinstance(result, BracketEstimate)
        assert result.bracket_tag == "E"


class TestSpellbookServerErrors:
    @respx.mock
    async def test_500_raises_spellbook_error(self):
        respx.get(f"{BASE_URL}/variants/", params__contains={"q": 'card:"Sol Ring"'}).mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        async with SpellbookClient(base_url=BASE_URL) as client:
            with pytest.raises(SpellbookError):
                await client.find_combos("Sol Ring")
