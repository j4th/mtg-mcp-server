"""Tests for new commander workflow functions (card_comparison, budget_upgrade).

These are unit tests of pure async functions. Service clients are mocked with
AsyncMock — no respx/httpx needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mtg_mcp_server.services.edhrec import EDHRECError
from mtg_mcp_server.services.scryfall import CardNotFoundError
from mtg_mcp_server.services.spellbook import SpellbookError
from mtg_mcp_server.types import (
    Card,
    CardPrices,
    Combo,
    ComboCard,
    ComboResult,
    EDHRECCard,
    EDHRECCardList,
    EDHRECCommanderData,
)
from mtg_mcp_server.workflows.commander import budget_upgrade, card_comparison

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

COMMANDER_NAME = "Muldrotha, the Gravetide"


@pytest.fixture
def sol_ring() -> Card:
    """Provide a Sol Ring Card with low price and high EDHREC rank."""
    return Card(
        id="test-id-sol-ring",
        name="Sol Ring",
        mana_cost="{1}",
        cmc=1.0,
        type_line="Artifact",
        oracle_text="{T}: Add {C}{C}.",
        colors=[],
        color_identity=[],
        set="cmd",
        rarity="uncommon",
        prices=CardPrices(usd="1.50"),
        edhrec_rank=1,
    )


@pytest.fixture
def spore_frog() -> Card:
    """Provide a Spore Frog Card with budget price and high synergy potential."""
    return Card(
        id="test-id-spore-frog",
        name="Spore Frog",
        mana_cost="{G}",
        cmc=1.0,
        type_line="Creature — Frog",
        oracle_text="Sacrifice Spore Frog: Prevent all combat damage that would be dealt this turn.",
        colors=["G"],
        color_identity=["G"],
        set="mma",
        rarity="common",
        prices=CardPrices(usd="0.25"),
        edhrec_rank=1200,
    )


@pytest.fixture
def animate_dead() -> Card:
    """Provide an Animate Dead Card for combo-related comparison tests."""
    return Card(
        id="test-id-animate-dead",
        name="Animate Dead",
        mana_cost="{1}{B}",
        cmc=2.0,
        type_line="Enchantment — Aura",
        oracle_text="Enchant creature card in a graveyard...",
        colors=["B"],
        color_identity=["B"],
        set="ema",
        rarity="uncommon",
        prices=CardPrices(usd="3.00"),
        edhrec_rank=500,
    )


@pytest.fixture
def mock_combos_sol_ring() -> list[Combo]:
    """Provide a single Sol Ring combo (Dramatic Reversal infinite mana)."""
    return [
        Combo(
            id="combo-sr-1",
            cards=[ComboCard(name="Sol Ring"), ComboCard(name="Dramatic Reversal")],
            produces=[ComboResult(feature_name="Infinite mana")],
            identity="C",
        ),
    ]


@pytest.fixture
def mock_combos_spore_frog() -> list[Combo]:
    """Provide two Spore Frog combos for combo count comparison."""
    return [
        Combo(
            id="combo-sf-1",
            cards=[ComboCard(name="Spore Frog"), ComboCard(name="Animate Dead")],
            produces=[ComboResult(feature_name="Infinite death triggers")],
            identity="BGU",
        ),
        Combo(
            id="combo-sf-2",
            cards=[ComboCard(name="Spore Frog"), ComboCard(name="Meren of Clan Nel Toth")],
            produces=[ComboResult(feature_name="Recurring fog")],
            identity="BG",
        ),
    ]


@pytest.fixture
def synergy_sol_ring() -> EDHRECCard:
    """Provide Sol Ring EDHREC data with negative synergy and high inclusion."""
    return EDHRECCard(
        name="Sol Ring",
        sanitized="sol-ring",
        synergy=-0.05,
        inclusion=95,
        num_decks=18750,
        label="95% of 19,741 decks",
    )


@pytest.fixture
def synergy_spore_frog() -> EDHRECCard:
    """Provide Spore Frog EDHREC data with high synergy for Muldrotha."""
    return EDHRECCard(
        name="Spore Frog",
        sanitized="spore-frog",
        synergy=0.61,
        inclusion=61,
        num_decks=12050,
        label="61% of 19,741 decks",
    )


@pytest.fixture
def mock_edhrec_data() -> EDHRECCommanderData:
    """Provide EDHREC commander data with creature and artifact cardlists."""
    return EDHRECCommanderData(
        commander_name=COMMANDER_NAME,
        total_decks=19741,
        cardlists=[
            EDHRECCardList(
                header="Creatures",
                tag="creatures",
                cardviews=[
                    EDHRECCard(
                        name="Spore Frog",
                        sanitized="spore-frog",
                        synergy=0.61,
                        inclusion=61,
                        num_decks=12050,
                    ),
                    EDHRECCard(
                        name="Sakura-Tribe Elder",
                        sanitized="sakura-tribe-elder",
                        synergy=0.15,
                        inclusion=72,
                        num_decks=14213,
                    ),
                ],
            ),
            EDHRECCardList(
                header="Artifacts",
                tag="artifacts",
                cardviews=[
                    EDHRECCard(
                        name="Sol Ring",
                        sanitized="sol-ring",
                        synergy=-0.05,
                        inclusion=95,
                        num_decks=18750,
                    ),
                    EDHRECCard(
                        name="Wayfarer's Bauble",
                        sanitized="wayfarers-bauble",
                        synergy=0.10,
                        inclusion=40,
                        num_decks=7896,
                    ),
                ],
            ),
        ],
    )


@pytest.fixture
def scryfall() -> AsyncMock:
    """Provide a mock ScryfallClient."""
    return AsyncMock()


@pytest.fixture
def spellbook() -> AsyncMock:
    """Provide a mock SpellbookClient."""
    return AsyncMock()


@pytest.fixture
def edhrec() -> AsyncMock:
    """Provide a mock EDHRECClient."""
    return AsyncMock()


# ===========================================================================
# card_comparison tests
# ===========================================================================


class TestCardComparison:
    """Tests for the card_comparison workflow function."""

    async def test_happy_path(
        self,
        scryfall: AsyncMock,
        spellbook: AsyncMock,
        edhrec: AsyncMock,
        sol_ring: Card,
        spore_frog: Card,
        mock_combos_sol_ring: list[Combo],
        mock_combos_spore_frog: list[Combo],
        synergy_sol_ring: EDHRECCard,
        synergy_spore_frog: EDHRECCard,
    ) -> None:
        """All sources succeed — full comparison table."""
        scryfall.get_card_by_name = AsyncMock(side_effect=[sol_ring, spore_frog])
        spellbook.find_combos = AsyncMock(
            side_effect=[mock_combos_sol_ring, mock_combos_spore_frog]
        )
        edhrec.card_synergy = AsyncMock(side_effect=[synergy_sol_ring, synergy_spore_frog])

        result = await card_comparison(
            ["Sol Ring", "Spore Frog"],
            COMMANDER_NAME,
            scryfall=scryfall,
            spellbook=spellbook,
            edhrec=edhrec,
        )

        # Table header
        assert "Card Comparison" in result
        assert COMMANDER_NAME in result

        # Both cards present in table
        assert "Sol Ring" in result
        assert "Spore Frog" in result

        # Mana costs
        assert "{1}" in result
        assert "{G}" in result

        # Synergy values
        assert "-5%" in result or "-0.05" in result  # Sol Ring negative synergy
        assert "+61%" in result or "0.61" in result  # Spore Frog high synergy

        # Inclusion percentages
        assert "95%" in result
        assert "61%" in result

        # Combo counts
        assert "1" in result  # Sol Ring has 1 combo
        assert "2" in result  # Spore Frog has 2 combos

        # Prices
        assert "$1.50" in result
        assert "$0.25" in result

        # Data Sources footer
        assert "**Data Sources:**" in result
        assert "Scryfall](https://scryfall.com)" in result
        assert "Commander Spellbook](https://commanderspellbook.com)" in result
        assert "EDHREC](https://edhrec.com)" in result

    async def test_edhrec_disabled(
        self,
        scryfall: AsyncMock,
        spellbook: AsyncMock,
        sol_ring: Card,
        spore_frog: Card,
        mock_combos_sol_ring: list[Combo],
        mock_combos_spore_frog: list[Combo],
    ) -> None:
        """EDHREC is None — synergy/inclusion show N/A."""
        scryfall.get_card_by_name = AsyncMock(side_effect=[sol_ring, spore_frog])
        spellbook.find_combos = AsyncMock(
            side_effect=[mock_combos_sol_ring, mock_combos_spore_frog]
        )

        result = await card_comparison(
            ["Sol Ring", "Spore Frog"],
            COMMANDER_NAME,
            scryfall=scryfall,
            spellbook=spellbook,
            edhrec=None,
        )

        assert "Sol Ring" in result
        assert "Spore Frog" in result
        assert "N/A" in result  # Synergy/inclusion unavailable

    async def test_edhrec_fails_partial(
        self,
        scryfall: AsyncMock,
        spellbook: AsyncMock,
        edhrec: AsyncMock,
        sol_ring: Card,
        spore_frog: Card,
        mock_combos_sol_ring: list[Combo],
        mock_combos_spore_frog: list[Combo],
    ) -> None:
        """EDHREC raises exception — synergy columns show N/A, rest works."""
        scryfall.get_card_by_name = AsyncMock(side_effect=[sol_ring, spore_frog])
        spellbook.find_combos = AsyncMock(
            side_effect=[mock_combos_sol_ring, mock_combos_spore_frog]
        )
        edhrec.card_synergy = AsyncMock(side_effect=EDHRECError("EDHREC is down", status_code=500))

        result = await card_comparison(
            ["Sol Ring", "Spore Frog"],
            COMMANDER_NAME,
            scryfall=scryfall,
            spellbook=spellbook,
            edhrec=edhrec,
        )

        assert "Sol Ring" in result
        assert "Spore Frog" in result
        # Synergy columns are N/A but combo counts still present
        assert "N/A" in result
        assert "$1.50" in result

    async def test_spellbook_fails_partial(
        self,
        scryfall: AsyncMock,
        spellbook: AsyncMock,
        edhrec: AsyncMock,
        sol_ring: Card,
        spore_frog: Card,
        synergy_sol_ring: EDHRECCard,
        synergy_spore_frog: EDHRECCard,
    ) -> None:
        """Spellbook raises exception — combo column shows N/A, rest works."""
        scryfall.get_card_by_name = AsyncMock(side_effect=[sol_ring, spore_frog])
        spellbook.find_combos = AsyncMock(
            side_effect=SpellbookError("Spellbook timeout", status_code=503)
        )
        edhrec.card_synergy = AsyncMock(side_effect=[synergy_sol_ring, synergy_spore_frog])

        result = await card_comparison(
            ["Sol Ring", "Spore Frog"],
            COMMANDER_NAME,
            scryfall=scryfall,
            spellbook=spellbook,
            edhrec=edhrec,
        )

        assert "Sol Ring" in result
        assert "Spore Frog" in result
        # Synergy present, combos N/A
        assert "+61%" in result or "0.61" in result
        # Both combo columns show N/A
        lines = result.split("\n")
        data_lines = [ln for ln in lines if ln.startswith("| ") and "Sol Ring" in ln]
        assert len(data_lines) == 1
        assert "N/A" in data_lines[0]  # combo column

    async def test_partial_results_when_card_not_found(
        self,
        scryfall: AsyncMock,
        spellbook: AsyncMock,
        edhrec: AsyncMock,
        sol_ring: Card,
        synergy_sol_ring: EDHRECCard,
        mock_combos_sol_ring: list[Combo],
    ) -> None:
        """One card not found — returns partial results with note about missing card."""

        async def resolve_side_effect(name: str) -> Card:
            if name == "Sol Ring":
                return sol_ring
            raise CardNotFoundError(f"Card not found: '{name}'", status_code=404)

        scryfall.get_card_by_name = AsyncMock(side_effect=resolve_side_effect)
        spellbook.find_combos = AsyncMock(return_value=mock_combos_sol_ring)
        edhrec.card_synergy = AsyncMock(return_value=synergy_sol_ring)

        result = await card_comparison(
            ["Sol Ring", "Nonexistent Card"],
            COMMANDER_NAME,
            scryfall=scryfall,
            spellbook=spellbook,
            edhrec=edhrec,
        )

        # Valid card is present in result
        assert "Sol Ring" in result
        # Missing card noted
        assert "Nonexistent Card" in result
        assert "not found" in result.lower()

    async def test_all_cards_not_found_raises(
        self,
        scryfall: AsyncMock,
        spellbook: AsyncMock,
        edhrec: AsyncMock,
    ) -> None:
        """All cards not found — raises CardNotFoundError."""
        scryfall.get_card_by_name = AsyncMock(
            side_effect=CardNotFoundError("Card not found: 'Nonexistent'", status_code=404)
        )

        with pytest.raises(CardNotFoundError):
            await card_comparison(
                ["Nonexistent", "Also Fake"],
                COMMANDER_NAME,
                scryfall=scryfall,
                spellbook=spellbook,
                edhrec=edhrec,
            )

    async def test_progress_callback(
        self,
        scryfall: AsyncMock,
        spellbook: AsyncMock,
        edhrec: AsyncMock,
        sol_ring: Card,
        spore_frog: Card,
    ) -> None:
        """Progress callback is called for each step."""
        scryfall.get_card_by_name = AsyncMock(side_effect=[sol_ring, spore_frog])
        spellbook.find_combos = AsyncMock(return_value=[])
        edhrec.card_synergy = AsyncMock(return_value=None)

        progress = AsyncMock()

        await card_comparison(
            ["Sol Ring", "Spore Frog"],
            COMMANDER_NAME,
            scryfall=scryfall,
            spellbook=spellbook,
            edhrec=edhrec,
            on_progress=progress,
        )

        assert progress.await_count == 3
        progress.assert_any_await(1, 3)
        progress.assert_any_await(2, 3)
        progress.assert_any_await(3, 3)

    async def test_no_progress_callback(
        self,
        scryfall: AsyncMock,
        spellbook: AsyncMock,
        sol_ring: Card,
        spore_frog: Card,
    ) -> None:
        """Works fine with no progress callback (None)."""
        scryfall.get_card_by_name = AsyncMock(side_effect=[sol_ring, spore_frog])
        spellbook.find_combos = AsyncMock(return_value=[])

        result = await card_comparison(
            ["Sol Ring", "Spore Frog"],
            COMMANDER_NAME,
            scryfall=scryfall,
            spellbook=spellbook,
            edhrec=None,
        )

        assert "Sol Ring" in result


# ===========================================================================
# budget_upgrade tests
# ===========================================================================


class TestBudgetUpgrade:
    """Tests for the budget_upgrade workflow function."""

    async def test_happy_path(
        self,
        scryfall: AsyncMock,
        edhrec: AsyncMock,
        mock_edhrec_data: EDHRECCommanderData,
        sol_ring: Card,
        spore_frog: Card,
    ) -> None:
        """All sources succeed — ranked suggestions returned."""
        edhrec.commander_top_cards = AsyncMock(return_value=mock_edhrec_data)
        # Return cards with prices for each EDHREC card
        ste_card = Card(
            id="test-ste",
            name="Sakura-Tribe Elder",
            mana_cost="{1}{G}",
            type_line="Creature — Snake Shaman",
            colors=["G"],
            color_identity=["G"],
            set="uma",
            rarity="common",
            prices=CardPrices(usd="0.50"),
            edhrec_rank=100,
        )
        bauble_card = Card(
            id="test-bauble",
            name="Wayfarer's Bauble",
            mana_cost="{1}",
            type_line="Artifact",
            colors=[],
            color_identity=[],
            set="cm2",
            rarity="common",
            prices=CardPrices(usd="0.35"),
            edhrec_rank=200,
        )
        scryfall.get_card_by_name = AsyncMock(
            side_effect=[spore_frog, ste_card, sol_ring, bauble_card]
        )

        result = await budget_upgrade(
            COMMANDER_NAME,
            budget=5.00,
            num_suggestions=10,
            scryfall=scryfall,
            edhrec=edhrec,
        )

        # Header
        assert "Budget Upgrades" in result
        assert COMMANDER_NAME in result
        assert "$5.00" in result

        # Cards should appear ranked by synergy/$
        assert "Spore Frog" in result
        assert "Sakura-Tribe Elder" in result
        assert "Sol Ring" in result

        # Table structure
        assert "Synergy/$" in result

        # Data Sources footer
        assert "**Data Sources:**" in result
        assert "Scryfall](https://scryfall.com)" in result
        assert "EDHREC](https://edhrec.com)" in result

    async def test_edhrec_disabled(
        self,
        scryfall: AsyncMock,
    ) -> None:
        """EDHREC is None — returns error message."""
        result = await budget_upgrade(
            COMMANDER_NAME,
            budget=5.00,
            scryfall=scryfall,
            edhrec=None,
        )

        assert "EDHREC is not enabled" in result
        assert "MTG_MCP_ENABLE_EDHREC" in result

    async def test_no_cards_under_budget(
        self,
        scryfall: AsyncMock,
        edhrec: AsyncMock,
        mock_edhrec_data: EDHRECCommanderData,
    ) -> None:
        """All cards exceed budget — returns message suggesting increase."""
        edhrec.commander_top_cards = AsyncMock(return_value=mock_edhrec_data)
        # All cards priced above budget
        expensive = Card(
            id="test-exp",
            name="Expensive Card",
            mana_cost="{1}",
            type_line="Artifact",
            colors=[],
            color_identity=[],
            set="cmd",
            rarity="rare",
            prices=CardPrices(usd="50.00"),
            edhrec_rank=1,
        )
        scryfall.get_card_by_name = AsyncMock(return_value=expensive)

        result = await budget_upgrade(
            COMMANDER_NAME,
            budget=0.10,
            scryfall=scryfall,
            edhrec=edhrec,
        )

        assert "No cards found under $0.10" in result
        assert "budget" in result.lower()

    async def test_empty_edhrec_cardlists(
        self,
        scryfall: AsyncMock,
        edhrec: AsyncMock,
    ) -> None:
        """EDHREC returns empty cardlists — returns no staples message."""
        empty_data = EDHRECCommanderData(
            commander_name=COMMANDER_NAME,
            total_decks=0,
            cardlists=[],
        )
        edhrec.commander_top_cards = AsyncMock(return_value=empty_data)

        result = await budget_upgrade(
            COMMANDER_NAME,
            budget=5.00,
            scryfall=scryfall,
            edhrec=edhrec,
        )

        assert "No staples found" in result

    async def test_scryfall_price_failures_skipped(
        self,
        scryfall: AsyncMock,
        edhrec: AsyncMock,
    ) -> None:
        """Scryfall price lookup fails for some cards — those are silently skipped."""
        data = EDHRECCommanderData(
            commander_name=COMMANDER_NAME,
            total_decks=19741,
            cardlists=[
                EDHRECCardList(
                    header="Creatures",
                    tag="creatures",
                    cardviews=[
                        EDHRECCard(name="Good Card", synergy=0.5, inclusion=50, num_decks=9000),
                        EDHRECCard(name="Missing Card", synergy=0.3, inclusion=40, num_decks=7000),
                    ],
                ),
            ],
        )
        edhrec.commander_top_cards = AsyncMock(return_value=data)

        good_card = Card(
            id="test-good",
            name="Good Card",
            mana_cost="{G}",
            type_line="Creature",
            colors=["G"],
            color_identity=["G"],
            set="cmd",
            rarity="common",
            prices=CardPrices(usd="1.00"),
            edhrec_rank=100,
        )

        def side_effect(name: str) -> Card:
            if name == "Good Card":
                return good_card
            raise CardNotFoundError(f"Card not found: '{name}'", status_code=404)

        scryfall.get_card_by_name = AsyncMock(side_effect=side_effect)

        result = await budget_upgrade(
            COMMANDER_NAME,
            budget=5.00,
            scryfall=scryfall,
            edhrec=edhrec,
        )

        assert "Good Card" in result
        assert "Missing Card" not in result

    async def test_cards_without_usd_price_skipped(
        self,
        scryfall: AsyncMock,
        edhrec: AsyncMock,
    ) -> None:
        """Cards with no USD price are skipped."""
        data = EDHRECCommanderData(
            commander_name=COMMANDER_NAME,
            total_decks=19741,
            cardlists=[
                EDHRECCardList(
                    header="Creatures",
                    tag="creatures",
                    cardviews=[
                        EDHRECCard(name="No Price Card", synergy=0.5, inclusion=50, num_decks=9000),
                    ],
                ),
            ],
        )
        edhrec.commander_top_cards = AsyncMock(return_value=data)

        no_price_card = Card(
            id="test-np",
            name="No Price Card",
            mana_cost="{G}",
            type_line="Creature",
            colors=["G"],
            color_identity=["G"],
            set="cmd",
            rarity="common",
            prices=CardPrices(usd=None),
            edhrec_rank=100,
        )
        scryfall.get_card_by_name = AsyncMock(return_value=no_price_card)

        result = await budget_upgrade(
            COMMANDER_NAME,
            budget=5.00,
            scryfall=scryfall,
            edhrec=edhrec,
        )

        assert "No cards found" in result

    async def test_progress_callback(
        self,
        scryfall: AsyncMock,
        edhrec: AsyncMock,
        mock_edhrec_data: EDHRECCommanderData,
        spore_frog: Card,
    ) -> None:
        """Progress callback is called at each step."""
        edhrec.commander_top_cards = AsyncMock(return_value=mock_edhrec_data)
        scryfall.get_card_by_name = AsyncMock(return_value=spore_frog)

        progress = AsyncMock()

        await budget_upgrade(
            COMMANDER_NAME,
            budget=5.00,
            scryfall=scryfall,
            edhrec=edhrec,
            on_progress=progress,
        )

        assert progress.await_count == 2
        progress.assert_any_await(1, 2)
        progress.assert_any_await(2, 2)

    async def test_num_suggestions_limit(
        self,
        scryfall: AsyncMock,
        edhrec: AsyncMock,
    ) -> None:
        """Only returns up to num_suggestions cards."""
        # Create many EDHREC cards
        many_cards = [
            EDHRECCard(name=f"Card {i}", synergy=0.5 - i * 0.05, inclusion=50, num_decks=9000)
            for i in range(20)
        ]
        data = EDHRECCommanderData(
            commander_name=COMMANDER_NAME,
            total_decks=19741,
            cardlists=[
                EDHRECCardList(header="All", tag="all", cardviews=many_cards),
            ],
        )
        edhrec.commander_top_cards = AsyncMock(return_value=data)

        cheap_card = Card(
            id="test-cheap",
            name="Card 0",
            mana_cost="{1}",
            type_line="Creature",
            colors=[],
            color_identity=[],
            set="cmd",
            rarity="common",
            prices=CardPrices(usd="0.50"),
            edhrec_rank=100,
        )
        scryfall.get_card_by_name = AsyncMock(return_value=cheap_card)

        result = await budget_upgrade(
            COMMANDER_NAME,
            budget=5.00,
            num_suggestions=3,
            scryfall=scryfall,
            edhrec=edhrec,
        )

        # Count data rows in the table (rows starting with "| " and containing a number)
        data_lines = [
            line
            for line in result.split("\n")
            if line.startswith("| ") and not line.startswith("| #") and not line.startswith("|---")
        ]
        assert len(data_lines) == 3

    async def test_synergy_per_dollar_floor(
        self,
        scryfall: AsyncMock,
        edhrec: AsyncMock,
    ) -> None:
        """Cards with price below $0.25 use $0.25 floor for synergy/$ calc."""
        data = EDHRECCommanderData(
            commander_name=COMMANDER_NAME,
            total_decks=19741,
            cardlists=[
                EDHRECCardList(
                    header="Creatures",
                    tag="creatures",
                    cardviews=[
                        EDHRECCard(name="Penny Card", synergy=0.50, inclusion=60, num_decks=11000),
                    ],
                ),
            ],
        )
        edhrec.commander_top_cards = AsyncMock(return_value=data)

        penny_card = Card(
            id="test-penny",
            name="Penny Card",
            mana_cost="{G}",
            type_line="Creature",
            colors=["G"],
            color_identity=["G"],
            set="cmd",
            rarity="common",
            prices=CardPrices(usd="0.05"),
            edhrec_rank=100,
        )
        scryfall.get_card_by_name = AsyncMock(return_value=penny_card)

        result = await budget_upgrade(
            COMMANDER_NAME,
            budget=5.00,
            scryfall=scryfall,
            edhrec=edhrec,
        )

        assert "Penny Card" in result
        # synergy_per_dollar = 0.50 / 0.25 = 2.00 (using floor, not 0.50/0.05=10.0)
        assert "2.00" in result

    async def test_sorting_by_synergy_per_dollar(
        self,
        scryfall: AsyncMock,
        edhrec: AsyncMock,
    ) -> None:
        """Cards are sorted by synergy/$ descending."""
        data = EDHRECCommanderData(
            commander_name=COMMANDER_NAME,
            total_decks=19741,
            cardlists=[
                EDHRECCardList(
                    header="Creatures",
                    tag="creatures",
                    cardviews=[
                        # Low synergy/$ = synergy 0.10 / $2.00 = 0.05
                        EDHRECCard(
                            name="Expensive Low Synergy",
                            synergy=0.10,
                            inclusion=30,
                            num_decks=5000,
                        ),
                        # High synergy/$ = synergy 0.50 / $0.50 = 1.00
                        EDHRECCard(
                            name="Cheap High Synergy",
                            synergy=0.50,
                            inclusion=60,
                            num_decks=11000,
                        ),
                    ],
                ),
            ],
        )
        edhrec.commander_top_cards = AsyncMock(return_value=data)

        expensive_card = Card(
            id="test-exp",
            name="Expensive Low Synergy",
            mana_cost="{2}",
            type_line="Creature",
            colors=[],
            color_identity=[],
            set="cmd",
            rarity="common",
            prices=CardPrices(usd="2.00"),
            edhrec_rank=200,
        )
        cheap_card = Card(
            id="test-cheap",
            name="Cheap High Synergy",
            mana_cost="{G}",
            type_line="Creature",
            colors=["G"],
            color_identity=["G"],
            set="cmd",
            rarity="common",
            prices=CardPrices(usd="0.50"),
            edhrec_rank=100,
        )

        def price_side_effect(name: str) -> Card:
            if name == "Expensive Low Synergy":
                return expensive_card
            return cheap_card

        scryfall.get_card_by_name = AsyncMock(side_effect=price_side_effect)

        result = await budget_upgrade(
            COMMANDER_NAME,
            budget=5.00,
            scryfall=scryfall,
            edhrec=edhrec,
        )

        # Cheap High Synergy should be ranked #1, Expensive Low Synergy #2
        lines = result.split("\n")
        data_lines = [
            line
            for line in lines
            if line.startswith("| ") and not line.startswith("| #") and not line.startswith("|---")
        ]
        assert len(data_lines) == 2
        assert "Cheap High Synergy" in data_lines[0]
        assert "Expensive Low Synergy" in data_lines[1]
