"""Tests for the async caching decorator and per-service cache behavior.

Tests cover:
- Core ``async_cached`` decorator mechanics
- Cache key functions (``_method_key``, ``_decklist_key``)
- Per-service cache behavior (cache hit skips HTTP, clear works)
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import respx
from cachetools import TTLCache

import mtg_mcp.services.cache as cache_mod
from mtg_mcp.services.cache import _decklist_key, _method_key, async_cached
from mtg_mcp.services.edhrec import EDHRECClient
from mtg_mcp.services.scryfall import ScryfallClient
from mtg_mcp.services.seventeen_lands import SeventeenLandsClient
from mtg_mcp.services.spellbook import SpellbookClient

SCRYFALL_FIXTURES = Path(__file__).parent.parent / "fixtures" / "scryfall"
SPELLBOOK_FIXTURES = Path(__file__).parent.parent / "fixtures" / "spellbook"
SEVENTEEN_LANDS_FIXTURES = Path(__file__).parent.parent / "fixtures" / "seventeen_lands"
EDHREC_FIXTURES = Path(__file__).parent.parent / "fixtures" / "edhrec"

SCRYFALL_URL = "https://api.scryfall.com"
SPELLBOOK_URL = "https://backend.commanderspellbook.com"
SEVENTEEN_LANDS_URL = "https://www.17lands.com"
EDHREC_URL = "https://json.edhrec.com"


def _load_json(path: Path) -> dict | list:
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Decorator unit tests
# ---------------------------------------------------------------------------


class TestAsyncCachedDecorator:
    """Tests for the ``async_cached`` decorator itself."""

    async def test_returns_cached_result_on_second_call(self):
        cache: TTLCache = TTLCache(maxsize=10, ttl=300)
        call_count = 0

        @async_cached(cache)
        async def fetch(self, key: str) -> str:
            nonlocal call_count
            call_count += 1
            return f"result-{key}"

        sentinel = object()
        result1 = await fetch(sentinel, "abc")
        result2 = await fetch(sentinel, "abc")

        assert result1 == "result-abc"
        assert result2 == "result-abc"
        assert call_count == 1  # only called once

    async def test_cache_miss_calls_wrapped_function(self):
        cache: TTLCache = TTLCache(maxsize=10, ttl=300)
        call_count = 0

        @async_cached(cache)
        async def fetch(self, key: str) -> str:
            nonlocal call_count
            call_count += 1
            return f"result-{key}"

        sentinel = object()
        await fetch(sentinel, "x")
        await fetch(sentinel, "y")

        assert call_count == 2  # different keys = different calls

    async def test_cache_attribute_is_accessible(self):
        cache: TTLCache = TTLCache(maxsize=10, ttl=300)

        @async_cached(cache)
        async def fetch(self, key: str) -> str:
            return key

        assert fetch.cache is cache

    async def test_cache_clear_forces_re_fetch(self):
        cache: TTLCache = TTLCache(maxsize=10, ttl=300)
        call_count = 0

        @async_cached(cache)
        async def fetch(self, key: str) -> str:
            nonlocal call_count
            call_count += 1
            return f"result-{key}"

        sentinel = object()
        await fetch(sentinel, "abc")
        assert call_count == 1

        cache.clear()
        await fetch(sentinel, "abc")
        assert call_count == 2  # had to re-fetch after clear

    async def test_disabled_flag_bypasses_cache(self):
        cache: TTLCache = TTLCache(maxsize=10, ttl=300)
        call_count = 0

        @async_cached(cache)
        async def fetch(self, key: str) -> str:
            nonlocal call_count
            call_count += 1
            return f"result-{key}"

        sentinel = object()
        old = cache_mod._disabled
        try:
            cache_mod._disabled = True
            await fetch(sentinel, "abc")
            await fetch(sentinel, "abc")
            assert call_count == 2  # both calls hit the function
            assert len(cache) == 0  # nothing stored in cache
        finally:
            cache_mod._disabled = old


class TestMethodKey:
    """Tests for ``_method_key`` — skips self, hashes the rest."""

    def test_skips_self_argument(self):
        sentinel = object()
        key1 = _method_key(sentinel, "card_name", fuzzy=True)
        key2 = _method_key(object(), "card_name", fuzzy=True)

        # Different self objects should produce the same key
        assert key1 == key2

    def test_different_args_produce_different_keys(self):
        s = object()
        key1 = _method_key(s, "card_a")
        key2 = _method_key(s, "card_b")
        assert key1 != key2

    def test_keyword_args_affect_key(self):
        s = object()
        key1 = _method_key(s, "name", fuzzy=True)
        key2 = _method_key(s, "name", fuzzy=False)
        assert key1 != key2

    def test_cache_key_isolation_fuzzy_vs_exact(self):
        """(name, fuzzy=True) and (name, fuzzy=False) must be separate entries."""
        cache: TTLCache = TTLCache(maxsize=10, ttl=300)

        # Simulate two cache entries
        k1 = _method_key(None, "Sol Ring", fuzzy=True)
        k2 = _method_key(None, "Sol Ring", fuzzy=False)
        cache[k1] = "fuzzy_result"
        cache[k2] = "exact_result"

        assert cache[k1] == "fuzzy_result"
        assert cache[k2] == "exact_result"
        assert len(cache) == 2


class TestDecklistKey:
    """Tests for ``_decklist_key`` — converts list args to tuples."""

    def test_converts_lists_to_tuples(self):
        s = object()
        # Should not raise TypeError (lists are unhashable)
        key = _decklist_key(s, ["Commander A"], ["Card 1", "Card 2"])
        assert key is not None

    def test_same_lists_produce_same_key(self):
        s = object()
        key1 = _decklist_key(s, ["A"], ["B", "C"])
        key2 = _decklist_key(s, ["A"], ["B", "C"])
        assert key1 == key2

    def test_different_lists_produce_different_keys(self):
        s = object()
        key1 = _decklist_key(s, ["A"], ["B", "C"])
        key2 = _decklist_key(s, ["A"], ["B", "D"])
        assert key1 != key2

    def test_skips_self(self):
        key1 = _decklist_key(object(), ["A"], ["B"])
        key2 = _decklist_key(object(), ["A"], ["B"])
        assert key1 == key2

    def test_handles_kwargs_with_lists(self):
        """Keyword args containing lists should also be converted to tuples."""
        s = object()
        key = _decklist_key(s, commanders=["A", "B"], decklist=["C", "D"])
        assert key is not None

    def test_kwargs_same_lists_produce_same_key(self):
        s = object()
        key1 = _decklist_key(s, commanders=["A"], decklist=["B"])
        key2 = _decklist_key(s, commanders=["A"], decklist=["B"])
        assert key1 == key2


# ---------------------------------------------------------------------------
# Per-service cache behavior tests
# ---------------------------------------------------------------------------


class TestScryfallCaching:
    """Verify ScryfallClient methods use the cache (second call skips HTTP)."""

    @respx.mock
    async def test_get_card_by_name_cached(self):
        fixture = _load_json(SCRYFALL_FIXTURES / "card_muldrotha.json")
        route = respx.get(
            f"{SCRYFALL_URL}/cards/named",
            params={"exact": "Muldrotha, the Gravetide"},
        ).mock(return_value=httpx.Response(200, json=fixture))

        async with ScryfallClient(base_url=SCRYFALL_URL) as client:
            card1 = await client.get_card_by_name("Muldrotha, the Gravetide")
            card2 = await client.get_card_by_name("Muldrotha, the Gravetide")

        assert card1.name == card2.name
        assert route.call_count == 1  # second call served from cache

    @respx.mock
    async def test_get_card_by_name_fuzzy_separate_from_exact(self):
        fixture = _load_json(SCRYFALL_FIXTURES / "card_muldrotha.json")
        exact_route = respx.get(
            f"{SCRYFALL_URL}/cards/named",
            params={"exact": "Muldrotha, the Gravetide"},
        ).mock(return_value=httpx.Response(200, json=fixture))
        fuzzy_route = respx.get(
            f"{SCRYFALL_URL}/cards/named",
            params={"fuzzy": "Muldrotha, the Gravetide"},
        ).mock(return_value=httpx.Response(200, json=fixture))

        async with ScryfallClient(base_url=SCRYFALL_URL) as client:
            await client.get_card_by_name("Muldrotha, the Gravetide")
            await client.get_card_by_name("Muldrotha, the Gravetide", fuzzy=True)

        assert exact_route.call_count == 1
        assert fuzzy_route.call_count == 1  # different key = separate call

    @respx.mock
    async def test_search_cards_cached(self):
        fixture = _load_json(SCRYFALL_FIXTURES / "search_sultai_commander.json")
        route = respx.get(
            f"{SCRYFALL_URL}/cards/search",
            params={"q": "f:commander", "page": "1"},
        ).mock(return_value=httpx.Response(200, json=fixture))

        async with ScryfallClient(base_url=SCRYFALL_URL) as client:
            await client.search_cards("f:commander")
            await client.search_cards("f:commander")

        assert route.call_count == 1

    @respx.mock
    async def test_get_card_by_id_cached(self):
        fixture = _load_json(SCRYFALL_FIXTURES / "card_sol_ring.json")
        card_id = fixture["id"]
        route = respx.get(f"{SCRYFALL_URL}/cards/{card_id}").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        async with ScryfallClient(base_url=SCRYFALL_URL) as client:
            await client.get_card_by_id(card_id)
            await client.get_card_by_id(card_id)

        assert route.call_count == 1

    @respx.mock
    async def test_get_rulings_cached(self):
        fixture = _load_json(SCRYFALL_FIXTURES / "rulings_muldrotha.json")
        card_id = "705b4d97-2f50-47f7-9053-d748f4337553"
        route = respx.get(f"{SCRYFALL_URL}/cards/{card_id}/rulings").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        async with ScryfallClient(base_url=SCRYFALL_URL) as client:
            await client.get_rulings(card_id)
            await client.get_rulings(card_id)

        assert route.call_count == 1

    @respx.mock
    async def test_cache_clear_forces_refetch(self):
        fixture = _load_json(SCRYFALL_FIXTURES / "card_muldrotha.json")
        route = respx.get(
            f"{SCRYFALL_URL}/cards/named",
            params={"exact": "Muldrotha, the Gravetide"},
        ).mock(return_value=httpx.Response(200, json=fixture))

        async with ScryfallClient(base_url=SCRYFALL_URL) as client:
            await client.get_card_by_name("Muldrotha, the Gravetide")
            ScryfallClient._card_name_cache.clear()
            await client.get_card_by_name("Muldrotha, the Gravetide")

        assert route.call_count == 2

    def test_cache_attributes_accessible(self):
        assert ScryfallClient.get_card_by_name.cache is ScryfallClient._card_name_cache
        assert ScryfallClient.get_card_by_id.cache is ScryfallClient._card_id_cache
        assert ScryfallClient.search_cards.cache is ScryfallClient._search_cache
        assert ScryfallClient.get_rulings.cache is ScryfallClient._rulings_cache


class TestSpellbookCaching:
    """Verify SpellbookClient methods use the cache."""

    @respx.mock
    async def test_find_combos_cached(self):
        fixture = _load_json(SPELLBOOK_FIXTURES / "combos_muldrotha.json")
        route = respx.get(
            f"{SPELLBOOK_URL}/variants/",
            params={"q": 'card:"Muldrotha, the Gravetide"', "limit": "10"},
        ).mock(return_value=httpx.Response(200, json=fixture))

        async with SpellbookClient(base_url=SPELLBOOK_URL) as client:
            await client.find_combos("Muldrotha, the Gravetide")
            await client.find_combos("Muldrotha, the Gravetide")

        assert route.call_count == 1

    @respx.mock
    async def test_get_combo_cached(self):
        fixture = _load_json(SPELLBOOK_FIXTURES / "combo_detail.json")
        combo_id = "1414-2730-5131-5256"
        route = respx.get(f"{SPELLBOOK_URL}/variants/{combo_id}/").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        async with SpellbookClient(base_url=SPELLBOOK_URL) as client:
            await client.get_combo(combo_id)
            await client.get_combo(combo_id)

        assert route.call_count == 1

    @respx.mock
    async def test_find_decklist_combos_cached(self):
        fixture = _load_json(SPELLBOOK_FIXTURES / "find_my_combos_response.json")
        route = respx.post(f"{SPELLBOOK_URL}/find-my-combos").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        async with SpellbookClient(base_url=SPELLBOOK_URL) as client:
            await client.find_decklist_combos(
                commanders=["Muldrotha, the Gravetide"],
                decklist=["Sol Ring", "Spore Frog"],
            )
            await client.find_decklist_combos(
                commanders=["Muldrotha, the Gravetide"],
                decklist=["Sol Ring", "Spore Frog"],
            )

        assert route.call_count == 1

    @respx.mock
    async def test_estimate_bracket_cached(self):
        fixture = _load_json(SPELLBOOK_FIXTURES / "estimate_bracket_response.json")
        route = respx.post(f"{SPELLBOOK_URL}/estimate-bracket").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        async with SpellbookClient(base_url=SPELLBOOK_URL) as client:
            await client.estimate_bracket(
                commanders=["Muldrotha, the Gravetide"],
                decklist=["Sol Ring"],
            )
            await client.estimate_bracket(
                commanders=["Muldrotha, the Gravetide"],
                decklist=["Sol Ring"],
            )

        assert route.call_count == 1

    @respx.mock
    async def test_different_decklists_are_separate_cache_entries(self):
        fixture = _load_json(SPELLBOOK_FIXTURES / "find_my_combos_response.json")
        route = respx.post(f"{SPELLBOOK_URL}/find-my-combos").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        async with SpellbookClient(base_url=SPELLBOOK_URL) as client:
            await client.find_decklist_combos(
                commanders=["Muldrotha, the Gravetide"],
                decklist=["Sol Ring"],
            )
            await client.find_decklist_combos(
                commanders=["Muldrotha, the Gravetide"],
                decklist=["Sol Ring", "Spore Frog"],
            )

        assert route.call_count == 2  # different decklist = different cache key

    def test_cache_attributes_accessible(self):
        assert SpellbookClient.find_combos.cache is SpellbookClient._combos_cache
        assert SpellbookClient.get_combo.cache is SpellbookClient._combo_cache
        assert SpellbookClient.find_decklist_combos.cache is SpellbookClient._decklist_combos_cache
        assert SpellbookClient.estimate_bracket.cache is SpellbookClient._bracket_cache


class TestSeventeenLandsCaching:
    """Verify SeventeenLandsClient methods use the cache."""

    @respx.mock
    async def test_card_ratings_cached(self):
        fixture = _load_json(SEVENTEEN_LANDS_FIXTURES / "card_ratings_lci.json")
        route = respx.get(
            f"{SEVENTEEN_LANDS_URL}/card_ratings/data",
            params={"expansion": "LCI", "event_type": "PremierDraft"},
        ).mock(return_value=httpx.Response(200, json=fixture))

        async with SeventeenLandsClient(base_url=SEVENTEEN_LANDS_URL) as client:
            await client.card_ratings("LCI")
            await client.card_ratings("LCI")

        assert route.call_count == 1

    @respx.mock
    async def test_card_ratings_different_sets_are_separate(self):
        fixture = _load_json(SEVENTEEN_LANDS_FIXTURES / "card_ratings_lci.json")
        route_lci = respx.get(
            f"{SEVENTEEN_LANDS_URL}/card_ratings/data",
            params={"expansion": "LCI", "event_type": "PremierDraft"},
        ).mock(return_value=httpx.Response(200, json=fixture))
        route_mkm = respx.get(
            f"{SEVENTEEN_LANDS_URL}/card_ratings/data",
            params={"expansion": "MKM", "event_type": "PremierDraft"},
        ).mock(return_value=httpx.Response(200, json=fixture))

        async with SeventeenLandsClient(base_url=SEVENTEEN_LANDS_URL) as client:
            await client.card_ratings("LCI")
            await client.card_ratings("MKM")

        assert route_lci.call_count == 1
        assert route_mkm.call_count == 1

    @respx.mock
    async def test_color_ratings_cached(self):
        fixture = _load_json(SEVENTEEN_LANDS_FIXTURES / "color_ratings_lci.json")
        route = respx.get(
            f"{SEVENTEEN_LANDS_URL}/color_ratings/data",
            params={
                "expansion": "LCI",
                "event_type": "PremierDraft",
                "start_date": "2023-11-07",
                "end_date": "2024-02-07",
            },
        ).mock(return_value=httpx.Response(200, json=fixture))

        async with SeventeenLandsClient(base_url=SEVENTEEN_LANDS_URL) as client:
            await client.color_ratings("LCI", "2023-11-07", "2024-02-07")
            await client.color_ratings("LCI", "2023-11-07", "2024-02-07")

        assert route.call_count == 1

    def test_cache_attributes_accessible(self):
        assert SeventeenLandsClient.card_ratings.cache is SeventeenLandsClient._card_ratings_cache
        assert SeventeenLandsClient.color_ratings.cache is SeventeenLandsClient._color_ratings_cache


class TestEDHRECCaching:
    """Verify EDHRECClient methods use the cache."""

    @respx.mock
    async def test_commander_top_cards_cached(self):
        fixture = _load_json(EDHREC_FIXTURES / "commander_muldrotha.json")
        route = respx.get(f"{EDHREC_URL}/pages/commanders/muldrotha-the-gravetide.json").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        async with EDHRECClient(base_url=EDHREC_URL) as client:
            await client.commander_top_cards("Muldrotha, the Gravetide")
            await client.commander_top_cards("Muldrotha, the Gravetide")

        assert route.call_count == 1

    @respx.mock
    async def test_card_synergy_cached(self):
        fixture = _load_json(EDHREC_FIXTURES / "commander_muldrotha.json")
        route = respx.get(f"{EDHREC_URL}/pages/commanders/muldrotha-the-gravetide.json").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        async with EDHRECClient(base_url=EDHREC_URL) as client:
            result1 = await client.card_synergy("Spore Frog", "Muldrotha, the Gravetide")
            result2 = await client.card_synergy("Spore Frog", "Muldrotha, the Gravetide")

        assert result1 is not None
        assert result1.name == result2.name
        # card_synergy delegates to commander_top_cards, but both are cached independently.
        # First call: card_synergy misses -> commander_top_cards misses -> 1 HTTP call.
        # Second call: card_synergy hits -> 0 HTTP calls.
        assert route.call_count == 1

    @respx.mock
    async def test_commander_and_synergy_caches_independent(self):
        """Both caches are independent — clearing one doesn't affect the other."""
        fixture = _load_json(EDHREC_FIXTURES / "commander_muldrotha.json")
        route = respx.get(f"{EDHREC_URL}/pages/commanders/muldrotha-the-gravetide.json").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        async with EDHRECClient(base_url=EDHREC_URL) as client:
            # Populate both caches
            await client.commander_top_cards("Muldrotha, the Gravetide")
            await client.card_synergy("Spore Frog", "Muldrotha, the Gravetide")

        # commander_top_cards called once (cached from first call for synergy too)
        assert route.call_count == 1

        # Clear only synergy cache
        EDHRECClient._synergy_cache.clear()

        async with EDHRECClient(base_url=EDHREC_URL) as client:
            # Synergy must re-fetch (its cache was cleared), but commander_top_cards
            # is still cached so the underlying HTTP call comes from that
            await client.card_synergy("Spore Frog", "Muldrotha, the Gravetide")

        # commander_top_cards cache still populated = no additional HTTP call
        assert route.call_count == 1

    def test_cache_attributes_accessible(self):
        assert EDHRECClient.commander_top_cards.cache is EDHRECClient._commander_cache
        assert EDHRECClient.card_synergy.cache is EDHRECClient._synergy_cache
