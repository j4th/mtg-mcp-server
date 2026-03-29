"""Tests for commander workflow functions (commander_overview, evaluate_upgrade).

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
from mtg_mcp_server.workflows.commander import commander_overview, evaluate_upgrade

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_card() -> Card:
    """Provide a Muldrotha Card with full metadata for commander overview tests."""
    return Card(
        id="test-id-muldrotha",
        name="Muldrotha, the Gravetide",
        mana_cost="{3}{B}{G}{U}",
        cmc=6.0,
        type_line="Legendary Creature \u2014 Elemental Avatar",
        oracle_text="During each of your turns, you may play a land and cast a permanent spell of each permanent type from your graveyard.",
        colors=["B", "G", "U"],
        color_identity=["B", "G", "U"],
        set="dom",
        rarity="mythic",
        prices=CardPrices(usd="5.50", usd_foil="12.00", eur="4.80"),
        edhrec_rank=245,
        power="6",
        toughness="6",
    )


@pytest.fixture
def mock_upgrade_card() -> Card:
    """Provide a Spore Frog Card for evaluate_upgrade tests."""
    return Card(
        id="test-id-spore-frog",
        name="Spore Frog",
        mana_cost="{G}",
        cmc=1.0,
        type_line="Creature \u2014 Frog",
        oracle_text="Sacrifice Spore Frog: Prevent all combat damage that would be dealt this turn.",
        colors=["G"],
        color_identity=["G"],
        set="mma",
        rarity="common",
        prices=CardPrices(usd="0.25"),
        edhrec_rank=1200,
    )


@pytest.fixture
def mock_combos() -> list[Combo]:
    """Provide two Muldrotha combos with different results."""
    return [
        Combo(
            id="combo-1",
            cards=[
                ComboCard(name="Muldrotha, the Gravetide"),
                ComboCard(name="Spore Frog"),
                ComboCard(name="Animate Dead"),
            ],
            produces=[ComboResult(feature_name="Infinite death triggers")],
            identity="BGU",
            popularity=3000,
            description="Loop Spore Frog with Animate Dead.",
        ),
        Combo(
            id="combo-2",
            cards=[
                ComboCard(name="Muldrotha, the Gravetide"),
                ComboCard(name="Lion's Eye Diamond"),
            ],
            produces=[ComboResult(feature_name="Infinite mana")],
            identity="BGU",
            popularity=2500,
        ),
    ]


@pytest.fixture
def mock_edhrec_data() -> EDHRECCommanderData:
    """Provide EDHREC commander data with creature and enchantment cardlists."""
    return EDHRECCommanderData(
        commander_name="Muldrotha, the Gravetide",
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
                        label="61% of 19,741 decks",
                    ),
                    EDHRECCard(
                        name="Sakura-Tribe Elder",
                        sanitized="sakura-tribe-elder",
                        synergy=0.15,
                        inclusion=72,
                        num_decks=14213,
                        label="72% of 19,741 decks",
                    ),
                ],
            ),
            EDHRECCardList(
                header="Enchantments",
                tag="enchantments",
                cardviews=[
                    EDHRECCard(
                        name="Animate Dead",
                        sanitized="animate-dead",
                        synergy=0.45,
                        inclusion=55,
                        num_decks=10857,
                        label="55% of 19,741 decks",
                    ),
                ],
            ),
        ],
    )


@pytest.fixture
def mock_synergy_card() -> EDHRECCard:
    """Provide a Spore Frog EDHREC card with high synergy score."""
    return EDHRECCard(
        name="Spore Frog",
        sanitized="spore-frog",
        synergy=0.61,
        inclusion=61,
        num_decks=12050,
        label="61% of 19,741 decks",
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
# commander_overview tests
# ===========================================================================


class TestCommanderOverview:
    """Tests for the commander_overview workflow function."""

    async def test_all_sources_succeed(
        self,
        scryfall: AsyncMock,
        spellbook: AsyncMock,
        edhrec: AsyncMock,
        mock_card: Card,
        mock_combos: list[Combo],
        mock_edhrec_data: EDHRECCommanderData,
    ) -> None:
        """All sources succeed -- full output with all sections."""
        scryfall.get_card_by_name = AsyncMock(return_value=mock_card)
        spellbook.find_combos = AsyncMock(return_value=mock_combos)
        edhrec.commander_top_cards = AsyncMock(return_value=mock_edhrec_data)

        result = await commander_overview(
            "Muldrotha, the Gravetide",
            scryfall=scryfall,
            spellbook=spellbook,
            edhrec=edhrec,
        )

        # Structured data check
        assert isinstance(result.data, dict)

        # Card header section
        assert "Muldrotha, the Gravetide" in result.markdown
        assert "{3}{B}{G}{U}" in result.markdown
        assert "Legendary Creature" in result.markdown
        assert "During each of your turns" in result.markdown
        assert "245" in result.markdown  # edhrec_rank

        # Combo section
        assert "Combos" in result.markdown
        assert "combo-1" in result.markdown or "Spore Frog" in result.markdown
        assert "Infinite death triggers" in result.markdown

        # EDHREC section
        assert "Staples" in result.markdown or "EDHREC" in result.markdown
        assert "Spore Frog" in result.markdown
        assert "61%" in result.markdown or "0.61" in result.markdown

        # Data sources footer
        assert "**Data Sources:**" in result.markdown
        assert "Scryfall](https://scryfall.com)" in result.markdown
        assert "Spellbook" in result.markdown
        assert "EDHREC" in result.markdown

    async def test_edhrec_is_none(
        self,
        scryfall: AsyncMock,
        spellbook: AsyncMock,
        mock_card: Card,
        mock_combos: list[Combo],
    ) -> None:
        """EDHREC is None (disabled) -- partial output with note."""
        scryfall.get_card_by_name = AsyncMock(return_value=mock_card)
        spellbook.find_combos = AsyncMock(return_value=mock_combos)

        result = await commander_overview(
            "Muldrotha, the Gravetide",
            scryfall=scryfall,
            spellbook=spellbook,
            edhrec=None,
        )

        # Card data still present
        assert "Muldrotha, the Gravetide" in result.markdown

        # Combos still present
        assert "Combos" in result.markdown

        # EDHREC noted as not enabled
        assert "not enabled" in result.markdown.lower() or "disabled" in result.markdown.lower()

    async def test_edhrec_raises_exception(
        self,
        scryfall: AsyncMock,
        spellbook: AsyncMock,
        edhrec: AsyncMock,
        mock_card: Card,
        mock_combos: list[Combo],
    ) -> None:
        """EDHREC raises exception -- partial output with error note."""
        scryfall.get_card_by_name = AsyncMock(return_value=mock_card)
        spellbook.find_combos = AsyncMock(return_value=mock_combos)
        edhrec.commander_top_cards = AsyncMock(
            side_effect=EDHRECError("EDHREC is down", status_code=500)
        )

        result = await commander_overview(
            "Muldrotha, the Gravetide",
            scryfall=scryfall,
            spellbook=spellbook,
            edhrec=edhrec,
        )

        # Card data still present
        assert "Muldrotha, the Gravetide" in result.markdown

        # Combos still present
        assert "Combos" in result.markdown

        # EDHREC failure noted
        assert (
            "error" in result.markdown.lower()
            or "failed" in result.markdown.lower()
            or "unavailable" in result.markdown.lower()
        )

    async def test_spellbook_raises_exception(
        self,
        scryfall: AsyncMock,
        spellbook: AsyncMock,
        edhrec: AsyncMock,
        mock_card: Card,
        mock_edhrec_data: EDHRECCommanderData,
    ) -> None:
        """Spellbook raises exception -- partial output with error note."""
        scryfall.get_card_by_name = AsyncMock(return_value=mock_card)
        spellbook.find_combos = AsyncMock(
            side_effect=SpellbookError("Spellbook timeout", status_code=503)
        )
        edhrec.commander_top_cards = AsyncMock(return_value=mock_edhrec_data)

        result = await commander_overview(
            "Muldrotha, the Gravetide",
            scryfall=scryfall,
            spellbook=spellbook,
            edhrec=edhrec,
        )

        # Card data still present
        assert "Muldrotha, the Gravetide" in result.markdown

        # Spellbook failure noted
        assert (
            "error" in result.markdown.lower()
            or "failed" in result.markdown.lower()
            or "unavailable" in result.markdown.lower()
        )

        # EDHREC data still present
        assert "Spore Frog" in result.markdown

    async def test_scryfall_card_not_found_propagates(
        self,
        scryfall: AsyncMock,
        spellbook: AsyncMock,
        edhrec: AsyncMock,
    ) -> None:
        """Scryfall CardNotFoundError -- propagates (re-raised)."""
        scryfall.get_card_by_name = AsyncMock(
            side_effect=CardNotFoundError("Card not found: 'Nonexistent'", status_code=404)
        )
        spellbook.find_combos = AsyncMock(return_value=[])
        edhrec.commander_top_cards = AsyncMock(
            return_value=EDHRECCommanderData(commander_name="Nonexistent")
        )

        with pytest.raises(CardNotFoundError):
            await commander_overview(
                "Nonexistent",
                scryfall=scryfall,
                spellbook=spellbook,
                edhrec=edhrec,
            )

    async def test_empty_combos(
        self,
        scryfall: AsyncMock,
        spellbook: AsyncMock,
        mock_card: Card,
    ) -> None:
        """No combos found -- section says none found."""
        scryfall.get_card_by_name = AsyncMock(return_value=mock_card)
        spellbook.find_combos = AsyncMock(return_value=[])

        result = await commander_overview(
            "Muldrotha, the Gravetide",
            scryfall=scryfall,
            spellbook=spellbook,
            edhrec=None,
        )

        assert "Muldrotha, the Gravetide" in result.markdown
        assert (
            "no combos" in result.markdown.lower()
            or "none" in result.markdown.lower()
            or "0 combo" in result.markdown.lower()
        )

    async def test_both_optional_fail(
        self,
        scryfall: AsyncMock,
        spellbook: AsyncMock,
        edhrec: AsyncMock,
        mock_card: Card,
    ) -> None:
        """Both Spellbook and EDHREC fail -- still returns card data."""
        scryfall.get_card_by_name = AsyncMock(return_value=mock_card)
        spellbook.find_combos = AsyncMock(side_effect=SpellbookError("timeout", status_code=503))
        edhrec.commander_top_cards = AsyncMock(side_effect=EDHRECError("down", status_code=500))

        result = await commander_overview(
            "Muldrotha, the Gravetide",
            scryfall=scryfall,
            spellbook=spellbook,
            edhrec=edhrec,
        )

        # Card data must still be present
        assert "Muldrotha, the Gravetide" in result.markdown
        assert "{3}{B}{G}{U}" in result.markdown

    async def test_non_legendary_card_warning(
        self,
        scryfall: AsyncMock,
        spellbook: AsyncMock,
    ) -> None:
        """Non-legendary card used as commander gets a warning note."""
        non_legendary = Card(
            id="test-id-sol-ring",
            name="Sol Ring",
            mana_cost="{1}",
            type_line="Artifact",
            colors=[],
            color_identity=[],
            set="cmd",
            rarity="uncommon",
            prices=CardPrices(usd="1.50"),
        )
        scryfall.get_card_by_name = AsyncMock(return_value=non_legendary)
        spellbook.find_combos = AsyncMock(return_value=[])

        result = await commander_overview(
            "Sol Ring",
            scryfall=scryfall,
            spellbook=spellbook,
            edhrec=None,
        )

        assert "Sol Ring" in result.markdown
        assert (
            "not a legendary" in result.markdown.lower()
            or "may not be a valid commander" in result.markdown.lower()
        )


# ===========================================================================
# evaluate_upgrade tests
# ===========================================================================


class TestEvaluateUpgrade:
    """Tests for the evaluate_upgrade workflow function."""

    async def test_all_sources_succeed(
        self,
        scryfall: AsyncMock,
        spellbook: AsyncMock,
        edhrec: AsyncMock,
        mock_upgrade_card: Card,
        mock_combos: list[Combo],
        mock_synergy_card: EDHRECCard,
    ) -> None:
        """All sources succeed -- full output with all sections."""
        scryfall.get_card_by_name = AsyncMock(return_value=mock_upgrade_card)
        spellbook.find_combos = AsyncMock(return_value=mock_combos)
        edhrec.card_synergy = AsyncMock(return_value=mock_synergy_card)

        result = await evaluate_upgrade(
            "Spore Frog",
            "Muldrotha, the Gravetide",
            scryfall=scryfall,
            spellbook=spellbook,
            edhrec=edhrec,
        )

        # Structured data check
        assert isinstance(result.data, dict)

        # Card details
        assert "Spore Frog" in result.markdown
        assert "{G}" in result.markdown
        assert "Creature" in result.markdown

        # Price
        assert "$0.25" in result.markdown or "0.25" in result.markdown

        # Synergy data
        assert "0.61" in result.markdown or "61%" in result.markdown

        # Combos
        assert "combo" in result.markdown.lower()

        # Commander context
        assert "Muldrotha" in result.markdown

    async def test_edhrec_is_none(
        self,
        scryfall: AsyncMock,
        spellbook: AsyncMock,
        mock_upgrade_card: Card,
        mock_combos: list[Combo],
    ) -> None:
        """EDHREC is None (disabled) -- output without synergy data."""
        scryfall.get_card_by_name = AsyncMock(return_value=mock_upgrade_card)
        spellbook.find_combos = AsyncMock(return_value=mock_combos)

        result = await evaluate_upgrade(
            "Spore Frog",
            "Muldrotha, the Gravetide",
            scryfall=scryfall,
            spellbook=spellbook,
            edhrec=None,
        )

        # Card data still present
        assert "Spore Frog" in result.markdown

        # EDHREC noted as not enabled
        assert (
            "not enabled" in result.markdown.lower()
            or "disabled" in result.markdown.lower()
            or "not available" in result.markdown.lower()
        )

    async def test_edhrec_raises_exception(
        self,
        scryfall: AsyncMock,
        spellbook: AsyncMock,
        edhrec: AsyncMock,
        mock_upgrade_card: Card,
        mock_combos: list[Combo],
    ) -> None:
        """EDHREC raises exception -- output without synergy, note about failure."""
        scryfall.get_card_by_name = AsyncMock(return_value=mock_upgrade_card)
        spellbook.find_combos = AsyncMock(return_value=mock_combos)
        edhrec.card_synergy = AsyncMock(side_effect=EDHRECError("EDHREC error", status_code=500))

        result = await evaluate_upgrade(
            "Spore Frog",
            "Muldrotha, the Gravetide",
            scryfall=scryfall,
            spellbook=spellbook,
            edhrec=edhrec,
        )

        # Card data still present
        assert "Spore Frog" in result.markdown

        # EDHREC failure noted
        assert (
            "error" in result.markdown.lower()
            or "failed" in result.markdown.lower()
            or "unavailable" in result.markdown.lower()
        )

    async def test_spellbook_raises_exception(
        self,
        scryfall: AsyncMock,
        spellbook: AsyncMock,
        edhrec: AsyncMock,
        mock_upgrade_card: Card,
        mock_synergy_card: EDHRECCard,
    ) -> None:
        """Spellbook raises exception -- output without combos, note about failure."""
        scryfall.get_card_by_name = AsyncMock(return_value=mock_upgrade_card)
        spellbook.find_combos = AsyncMock(side_effect=SpellbookError("timeout", status_code=503))
        edhrec.card_synergy = AsyncMock(return_value=mock_synergy_card)

        result = await evaluate_upgrade(
            "Spore Frog",
            "Muldrotha, the Gravetide",
            scryfall=scryfall,
            spellbook=spellbook,
            edhrec=edhrec,
        )

        # Card data still present
        assert "Spore Frog" in result.markdown

        # Synergy data still present
        assert "0.61" in result.markdown or "61%" in result.markdown

        # Spellbook failure noted
        assert (
            "error" in result.markdown.lower()
            or "failed" in result.markdown.lower()
            or "unavailable" in result.markdown.lower()
        )

    async def test_scryfall_card_not_found_propagates(
        self,
        scryfall: AsyncMock,
        spellbook: AsyncMock,
        edhrec: AsyncMock,
    ) -> None:
        """Scryfall CardNotFoundError -- propagates (re-raised)."""
        scryfall.get_card_by_name = AsyncMock(
            side_effect=CardNotFoundError("Card not found: 'Nonexistent'", status_code=404)
        )
        spellbook.find_combos = AsyncMock(return_value=[])
        edhrec.card_synergy = AsyncMock(return_value=None)

        with pytest.raises(CardNotFoundError):
            await evaluate_upgrade(
                "Nonexistent",
                "Muldrotha, the Gravetide",
                scryfall=scryfall,
                spellbook=spellbook,
                edhrec=edhrec,
            )

    async def test_no_synergy_data_found(
        self,
        scryfall: AsyncMock,
        spellbook: AsyncMock,
        edhrec: AsyncMock,
        mock_upgrade_card: Card,
        mock_combos: list[Combo],
    ) -> None:
        """EDHREC returns None for card_synergy -- still produces output."""
        scryfall.get_card_by_name = AsyncMock(return_value=mock_upgrade_card)
        spellbook.find_combos = AsyncMock(return_value=mock_combos)
        edhrec.card_synergy = AsyncMock(return_value=None)

        result = await evaluate_upgrade(
            "Spore Frog",
            "Muldrotha, the Gravetide",
            scryfall=scryfall,
            spellbook=spellbook,
            edhrec=edhrec,
        )

        assert "Spore Frog" in result.markdown
        # Should note that no synergy data was found
        assert "no synergy" in result.markdown.lower() or "not found" in result.markdown.lower()

    async def test_empty_combos(
        self,
        scryfall: AsyncMock,
        spellbook: AsyncMock,
        edhrec: AsyncMock,
        mock_upgrade_card: Card,
        mock_synergy_card: EDHRECCard,
    ) -> None:
        """No combos found -- section says none found."""
        scryfall.get_card_by_name = AsyncMock(return_value=mock_upgrade_card)
        spellbook.find_combos = AsyncMock(return_value=[])
        edhrec.card_synergy = AsyncMock(return_value=mock_synergy_card)

        result = await evaluate_upgrade(
            "Spore Frog",
            "Muldrotha, the Gravetide",
            scryfall=scryfall,
            spellbook=spellbook,
            edhrec=edhrec,
        )

        assert "Spore Frog" in result.markdown
        assert (
            "no combos" in result.markdown.lower()
            or "none" in result.markdown.lower()
            or "0 combo" in result.markdown.lower()
        )


# ---------------------------------------------------------------------------
# response_format tests
# ---------------------------------------------------------------------------


class TestCommanderOverviewResponseFormat:
    """Concise output is shorter than detailed and omits verbose sections."""

    async def test_concise_shorter_than_detailed(
        self,
        scryfall: AsyncMock,
        spellbook: AsyncMock,
        edhrec: AsyncMock,
        mock_card: Card,
        mock_combos: list[Combo],
        mock_edhrec_data: EDHRECCommanderData,
    ) -> None:
        scryfall.get_card_by_name = AsyncMock(return_value=mock_card)
        spellbook.find_combos = AsyncMock(return_value=mock_combos)
        edhrec.commander_top_cards = AsyncMock(return_value=mock_edhrec_data)

        detailed = await commander_overview(
            "Muldrotha, the Gravetide",
            scryfall=scryfall,
            spellbook=spellbook,
            edhrec=edhrec,
            response_format="detailed",
        )
        concise = await commander_overview(
            "Muldrotha, the Gravetide",
            scryfall=scryfall,
            spellbook=spellbook,
            edhrec=edhrec,
            response_format="concise",
        )

        assert len(concise.markdown) < len(detailed.markdown)
        assert "Muldrotha" in concise.markdown
        # Concise omits Data Sources footer
        assert "**Data Sources:**" not in concise.markdown
        assert "**Data Sources:**" in detailed.markdown


class TestEvaluateUpgradeResponseFormat:
    """Concise output is shorter than detailed and omits verbose sections."""

    async def test_concise_shorter_than_detailed(
        self,
        scryfall: AsyncMock,
        spellbook: AsyncMock,
        edhrec: AsyncMock,
        mock_upgrade_card: Card,
        mock_combos: list[Combo],
        mock_synergy_card: EDHRECCard,
    ) -> None:
        scryfall.get_card_by_name = AsyncMock(return_value=mock_upgrade_card)
        spellbook.find_combos = AsyncMock(return_value=mock_combos)
        edhrec.card_synergy = AsyncMock(return_value=mock_synergy_card)

        detailed = await evaluate_upgrade(
            "Spore Frog",
            "Muldrotha, the Gravetide",
            scryfall=scryfall,
            spellbook=spellbook,
            edhrec=edhrec,
            response_format="detailed",
        )
        concise = await evaluate_upgrade(
            "Spore Frog",
            "Muldrotha, the Gravetide",
            scryfall=scryfall,
            spellbook=spellbook,
            edhrec=edhrec,
            response_format="concise",
        )

        assert len(concise.markdown) < len(detailed.markdown)
        assert "Spore Frog" in concise.markdown
        assert "**Data Sources:**" not in concise.markdown
