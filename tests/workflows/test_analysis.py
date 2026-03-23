"""Tests for deck_analysis workflow."""

from __future__ import annotations

from unittest.mock import AsyncMock

from mtg_mcp.services.base import ServiceError
from mtg_mcp.types import (
    BracketEstimate,
    Card,
    CardPrices,
    Combo,
    ComboCard,
    ComboResult,
    DecklistCombos,
    EDHRECCard,
    EDHRECCardList,
    EDHRECCommanderData,
    MTGJSONCard,
)
from mtg_mcp.workflows.analysis import deck_analysis

# ---------------------------------------------------------------------------
# Mock data helpers
# ---------------------------------------------------------------------------

COMMANDER = "Muldrotha, the Gravetide"


def _make_card(
    name: str,
    mana_cost: str = "{2}{U}",
    cmc: float = 3.0,
    usd_price: str | None = "1.50",
) -> Card:
    """Create a minimal Scryfall Card for testing."""
    return Card(
        id="test-id-" + name.lower().replace(" ", "-"),
        name=name,
        mana_cost=mana_cost,
        cmc=cmc,
        type_line="Creature",
        prices=CardPrices(usd=usd_price),
        rarity="common",
    )


def _make_mtgjson_card(
    name: str,
    mana_cost: str = "{2}{U}",
    mana_value: float = 3.0,
) -> MTGJSONCard:
    """Create a minimal MTGJSONCard for testing."""
    return MTGJSONCard(
        name=name,
        mana_cost=mana_cost,
        mana_value=mana_value,
        type_line="Creature",
    )


def _make_bracket() -> BracketEstimate:
    return BracketEstimate(
        bracketTag="E",
        bannedCards=[],
        gameChangerCards=[],
        twoCardCombos=["combo1"],
        lockCombos=[],
    )


def _make_decklist_combos(
    included: list[Combo] | None = None,
    almost_included: list[Combo] | None = None,
) -> DecklistCombos:
    return DecklistCombos(
        identity="BGU",
        included=included or [],
        almost_included=almost_included or [],
    )


SAMPLE_COMBO = Combo(
    id="combo-1",
    cards=[
        ComboCard(name="Spore Frog", zone_locations=["G"]),
        ComboCard(name="Muldrotha, the Gravetide", zone_locations=["C"], must_be_commander=True),
    ],
    produces=[ComboResult(feature_name="Repeatable fog")],
)


def _make_edhrec_data(
    cardviews: list[EDHRECCard] | None = None,
) -> EDHRECCommanderData:
    return EDHRECCommanderData(
        commander_name=COMMANDER,
        total_decks=19000,
        cardlists=[
            EDHRECCardList(
                header="Creatures",
                tag="creatures",
                cardviews=cardviews
                or [
                    EDHRECCard(name="Sol Ring", synergy=0.05, inclusion=95, num_decks=18000),
                    EDHRECCard(name="Spore Frog", synergy=0.61, inclusion=61, num_decks=12050),
                    EDHRECCard(name="Bad Card", synergy=-0.10, inclusion=5, num_decks=900),
                ],
            ),
        ],
    )


SAMPLE_DECKLIST = ["Sol Ring", "Spore Frog", "Bad Card", "Unknown Card"]


# ---------------------------------------------------------------------------
# Mock client builders
# ---------------------------------------------------------------------------


def _make_scryfall(cards: dict[str, Card] | None = None) -> AsyncMock:
    """Mock ScryfallClient that returns Card objects by name."""
    default_cards = {
        "sol ring": _make_card("Sol Ring", mana_cost="{1}", cmc=1.0, usd_price="3.00"),
        "spore frog": _make_card("Spore Frog", mana_cost="{G}", cmc=1.0, usd_price="0.50"),
        "bad card": _make_card("Bad Card", mana_cost="{3}{B}{B}", cmc=5.0, usd_price="0.10"),
    }
    lookup = cards if cards is not None else default_cards

    async def get_card_by_name(name: str, *, fuzzy: bool = False) -> Card:
        key = name.lower()
        if key in lookup:
            return lookup[key]
        from mtg_mcp.services.scryfall import CardNotFoundError

        raise CardNotFoundError(f"Card not found: '{name}'", status_code=404)

    mock = AsyncMock()
    mock.get_card_by_name = AsyncMock(side_effect=get_card_by_name)
    return mock


def _make_mtgjson(cards: dict[str, MTGJSONCard] | None = None) -> AsyncMock:
    """Mock MTGJSONClient that returns MTGJSONCard objects by name."""
    default_cards = {
        "sol ring": _make_mtgjson_card("Sol Ring", mana_cost="{1}", mana_value=1.0),
        "spore frog": _make_mtgjson_card("Spore Frog", mana_cost="{G}", mana_value=1.0),
        "bad card": _make_mtgjson_card("Bad Card", mana_cost="{3}{B}{B}", mana_value=5.0),
    }
    lookup = cards if cards is not None else default_cards

    async def get_card(name: str) -> MTGJSONCard | None:
        return lookup.get(name.lower())

    mock = AsyncMock()
    mock.get_card = AsyncMock(side_effect=get_card)
    return mock


def _make_spellbook(
    bracket: BracketEstimate | None = None,
    combos: DecklistCombos | None = None,
) -> AsyncMock:
    mock = AsyncMock()
    mock.estimate_bracket = AsyncMock(return_value=bracket or _make_bracket())
    mock.find_decklist_combos = AsyncMock(
        return_value=combos or _make_decklist_combos(included=[SAMPLE_COMBO])
    )
    return mock


def _make_edhrec(data: EDHRECCommanderData | None = None) -> AsyncMock:
    mock = AsyncMock()
    mock.commander_top_cards = AsyncMock(return_value=data or _make_edhrec_data())
    return mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDeckAnalysisHappyPath:
    """All backends available and returning data."""

    async def test_header_contains_commander_name(self) -> None:
        result = await deck_analysis(
            SAMPLE_DECKLIST,
            COMMANDER,
            mtgjson=_make_mtgjson(),
            scryfall=_make_scryfall(),
            spellbook=_make_spellbook(),
            edhrec=_make_edhrec(),
        )
        assert "Deck Analysis" in result
        assert COMMANDER in result

    async def test_mana_curve_section_present(self) -> None:
        result = await deck_analysis(
            SAMPLE_DECKLIST,
            COMMANDER,
            mtgjson=_make_mtgjson(),
            scryfall=_make_scryfall(),
            spellbook=_make_spellbook(),
            edhrec=_make_edhrec(),
        )
        assert "## Mana Curve" in result

    async def test_color_requirements_section_present(self) -> None:
        result = await deck_analysis(
            SAMPLE_DECKLIST,
            COMMANDER,
            mtgjson=_make_mtgjson(),
            scryfall=_make_scryfall(),
            spellbook=_make_spellbook(),
            edhrec=_make_edhrec(),
        )
        assert "## Color Requirements" in result

    async def test_combos_bracket_section_present(self) -> None:
        result = await deck_analysis(
            SAMPLE_DECKLIST,
            COMMANDER,
            mtgjson=_make_mtgjson(),
            scryfall=_make_scryfall(),
            spellbook=_make_spellbook(),
            edhrec=_make_edhrec(),
        )
        assert "## Combos & Bracket" in result
        assert "Bracket:" in result

    async def test_budget_section_present(self) -> None:
        result = await deck_analysis(
            SAMPLE_DECKLIST,
            COMMANDER,
            mtgjson=_make_mtgjson(),
            scryfall=_make_scryfall(),
            spellbook=_make_spellbook(),
            edhrec=_make_edhrec(),
        )
        assert "## Budget" in result
        assert "Total:" in result

    async def test_lowest_synergy_section_present(self) -> None:
        result = await deck_analysis(
            SAMPLE_DECKLIST,
            COMMANDER,
            mtgjson=_make_mtgjson(),
            scryfall=_make_scryfall(),
            spellbook=_make_spellbook(),
            edhrec=_make_edhrec(),
        )
        assert "## Lowest Synergy Cards" in result

    async def test_data_sources_footer_present(self) -> None:
        result = await deck_analysis(
            SAMPLE_DECKLIST,
            COMMANDER,
            mtgjson=_make_mtgjson(),
            scryfall=_make_scryfall(),
            spellbook=_make_spellbook(),
            edhrec=_make_edhrec(),
        )
        assert "**Data Sources:**" in result
        assert "Scryfall](https://scryfall.com): OK" in result
        assert "Commander Spellbook](https://commanderspellbook.com): OK" in result
        assert "EDHREC](https://edhrec.com): OK" in result
        assert "MTGJSON](https://mtgjson.com): OK" in result

    async def test_bracket_tag_displayed(self) -> None:
        result = await deck_analysis(
            SAMPLE_DECKLIST,
            COMMANDER,
            mtgjson=_make_mtgjson(),
            scryfall=_make_scryfall(),
            spellbook=_make_spellbook(),
            edhrec=_make_edhrec(),
        )
        assert "Bracket:" in result

    async def test_included_combos_count(self) -> None:
        result = await deck_analysis(
            SAMPLE_DECKLIST,
            COMMANDER,
            mtgjson=_make_mtgjson(),
            scryfall=_make_scryfall(),
            spellbook=_make_spellbook(combos=_make_decklist_combos(included=[SAMPLE_COMBO])),
            edhrec=_make_edhrec(),
        )
        assert "Included combos:" in result

    async def test_lowest_synergy_cards_listed(self) -> None:
        result = await deck_analysis(
            SAMPLE_DECKLIST,
            COMMANDER,
            mtgjson=_make_mtgjson(),
            scryfall=_make_scryfall(),
            spellbook=_make_spellbook(),
            edhrec=_make_edhrec(),
        )
        # Bad Card has -10% synergy, should be listed first
        assert "Bad Card" in result

    async def test_color_pips_counted(self) -> None:
        # Sol Ring ({1}) = no colored pips
        # Spore Frog ({G}) = 1 G
        # Bad Card ({3}{B}{B}) = 2 B
        result = await deck_analysis(
            ["Sol Ring", "Spore Frog", "Bad Card"],
            COMMANDER,
            mtgjson=_make_mtgjson(),
            scryfall=_make_scryfall(),
            spellbook=_make_spellbook(),
            edhrec=_make_edhrec(),
        )
        assert "G: 1" in result
        assert "B: 2" in result


class TestDeckAnalysisMtgjsonDisabled:
    """MTGJSON is None — falls back to Scryfall for card resolution."""

    async def test_falls_back_to_scryfall(self) -> None:
        result = await deck_analysis(
            SAMPLE_DECKLIST,
            COMMANDER,
            mtgjson=None,
            scryfall=_make_scryfall(),
            spellbook=_make_spellbook(),
            edhrec=_make_edhrec(),
        )
        assert "Deck Analysis" in result
        assert "MTGJSON](https://mtgjson.com): Disabled" in result

    async def test_mana_curve_still_computed(self) -> None:
        result = await deck_analysis(
            ["Sol Ring", "Spore Frog"],
            COMMANDER,
            mtgjson=None,
            scryfall=_make_scryfall(),
            spellbook=_make_spellbook(),
            edhrec=_make_edhrec(),
        )
        assert "## Mana Curve" in result


class TestDeckAnalysisEdhrecDisabled:
    """EDHREC is None — synergy section shows disabled message."""

    async def test_synergy_section_shows_disabled(self) -> None:
        result = await deck_analysis(
            SAMPLE_DECKLIST,
            COMMANDER,
            mtgjson=_make_mtgjson(),
            scryfall=_make_scryfall(),
            spellbook=_make_spellbook(),
            edhrec=None,
        )
        assert "not enabled" in result.lower() or "disabled" in result.lower()
        assert "EDHREC](https://edhrec.com): Disabled" in result

    async def test_other_sections_still_present(self) -> None:
        result = await deck_analysis(
            SAMPLE_DECKLIST,
            COMMANDER,
            mtgjson=_make_mtgjson(),
            scryfall=_make_scryfall(),
            spellbook=_make_spellbook(),
            edhrec=None,
        )
        assert "## Mana Curve" in result
        assert "## Budget" in result
        assert "## Combos & Bracket" in result


class TestDeckAnalysisSpellbookFailure:
    """Spellbook raises an exception — combos/bracket section degrades."""

    async def test_bracket_shows_unavailable(self) -> None:
        spellbook = AsyncMock()
        spellbook.estimate_bracket = AsyncMock(
            side_effect=ServiceError("Spellbook is down", status_code=503)
        )
        spellbook.find_decklist_combos = AsyncMock(
            side_effect=ServiceError("Spellbook is down", status_code=503)
        )
        result = await deck_analysis(
            SAMPLE_DECKLIST,
            COMMANDER,
            mtgjson=_make_mtgjson(),
            scryfall=_make_scryfall(),
            spellbook=spellbook,
            edhrec=_make_edhrec(),
        )
        assert (
            "Spellbook unavailable" in result
            or "Spellbook](https://commanderspellbook.com): Failed" in result
        )

    async def test_other_sections_still_present(self) -> None:
        spellbook = AsyncMock()
        spellbook.estimate_bracket = AsyncMock(side_effect=ServiceError("down", status_code=503))
        spellbook.find_decklist_combos = AsyncMock(
            side_effect=ServiceError("down", status_code=503)
        )
        result = await deck_analysis(
            SAMPLE_DECKLIST,
            COMMANDER,
            mtgjson=_make_mtgjson(),
            scryfall=_make_scryfall(),
            spellbook=spellbook,
            edhrec=_make_edhrec(),
        )
        assert "## Mana Curve" in result
        assert "## Budget" in result
        assert "## Lowest Synergy Cards" in result


class TestDeckAnalysisPartialCardResolution:
    """Some cards fail to resolve."""

    async def test_failures_noted_in_output(self) -> None:
        # "Unknown Card" will fail in both MTGJSON (None) and Scryfall (not found)
        result = await deck_analysis(
            SAMPLE_DECKLIST,
            COMMANDER,
            mtgjson=_make_mtgjson(),
            scryfall=_make_scryfall(),
            spellbook=_make_spellbook(),
            edhrec=_make_edhrec(),
        )
        assert "Unknown Card" in result
        assert "Unresolved" in result

    async def test_resolved_cards_still_analyzed(self) -> None:
        result = await deck_analysis(
            SAMPLE_DECKLIST,
            COMMANDER,
            mtgjson=_make_mtgjson(),
            scryfall=_make_scryfall(),
            spellbook=_make_spellbook(),
            edhrec=_make_edhrec(),
        )
        # Should still have mana curve data from resolved cards
        assert "## Mana Curve" in result
        assert "Total mana value" in result


class TestDeckAnalysisEmptyDecklist:
    """Empty decklist."""

    async def test_returns_appropriate_message(self) -> None:
        result = await deck_analysis(
            [],
            COMMANDER,
            mtgjson=_make_mtgjson(),
            scryfall=_make_scryfall(),
            spellbook=_make_spellbook(),
            edhrec=_make_edhrec(),
        )
        assert "No cards in decklist" in result


class TestDeckAnalysisProgressCallback:
    """Progress callback is called at the right steps."""

    async def test_progress_called_four_times(self) -> None:
        progress = AsyncMock()
        await deck_analysis(
            SAMPLE_DECKLIST,
            COMMANDER,
            mtgjson=_make_mtgjson(),
            scryfall=_make_scryfall(),
            spellbook=_make_spellbook(),
            edhrec=_make_edhrec(),
            on_progress=progress,
        )
        assert progress.await_count == 4
        progress.assert_any_await(1, 4)
        progress.assert_any_await(2, 4)
        progress.assert_any_await(3, 4)
        progress.assert_any_await(4, 4)

    async def test_works_without_progress(self) -> None:
        """No crash when on_progress is None."""
        result = await deck_analysis(
            SAMPLE_DECKLIST,
            COMMANDER,
            mtgjson=_make_mtgjson(),
            scryfall=_make_scryfall(),
            spellbook=_make_spellbook(),
            edhrec=_make_edhrec(),
            on_progress=None,
        )
        assert "Deck Analysis" in result


class TestDeckAnalysisEdhrecFailure:
    """EDHREC is enabled but raises an exception."""

    async def test_synergy_shows_failure(self) -> None:
        edhrec = AsyncMock()
        edhrec.commander_top_cards = AsyncMock(
            side_effect=ServiceError("EDHREC is down", status_code=503)
        )
        result = await deck_analysis(
            SAMPLE_DECKLIST,
            COMMANDER,
            mtgjson=_make_mtgjson(),
            scryfall=_make_scryfall(),
            spellbook=_make_spellbook(),
            edhrec=edhrec,
        )
        assert "EDHREC" in result
        assert "Failed" in result

    async def test_other_sections_still_present(self) -> None:
        edhrec = AsyncMock()
        edhrec.commander_top_cards = AsyncMock(side_effect=ServiceError("down", status_code=503))
        result = await deck_analysis(
            SAMPLE_DECKLIST,
            COMMANDER,
            mtgjson=_make_mtgjson(),
            scryfall=_make_scryfall(),
            spellbook=_make_spellbook(),
            edhrec=edhrec,
        )
        assert "## Mana Curve" in result
        assert "## Budget" in result


class TestDeckAnalysisBudget:
    """Budget computation tests."""

    async def test_total_price_computed(self) -> None:
        # Sol Ring $3.00 + Spore Frog $0.50 + Bad Card $0.10 = $3.60
        # Unknown Card has no price
        result = await deck_analysis(
            SAMPLE_DECKLIST,
            COMMANDER,
            mtgjson=_make_mtgjson(),
            scryfall=_make_scryfall(),
            spellbook=_make_spellbook(),
            edhrec=_make_edhrec(),
        )
        assert "$3.60" in result

    async def test_average_price_shown(self) -> None:
        result = await deck_analysis(
            SAMPLE_DECKLIST,
            COMMANDER,
            mtgjson=_make_mtgjson(),
            scryfall=_make_scryfall(),
            spellbook=_make_spellbook(),
            edhrec=_make_edhrec(),
        )
        assert "Average card:" in result
