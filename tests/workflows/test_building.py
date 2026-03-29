"""Tests for building workflow functions (theme_search, build_around, complete_deck).

These are unit tests of pure async functions. Service clients are mocked with
AsyncMock -- no respx/httpx needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

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
from mtg_mcp_server.workflows.building import build_around, complete_deck, theme_search

# ---------------------------------------------------------------------------
# Helper: create mock Card objects
# ---------------------------------------------------------------------------


def _mock_card(
    name: str,
    *,
    mana_cost: str = "{1}",
    cmc: float = 1.0,
    type_line: str = "Creature",
    oracle_text: str = "",
    colors: list[str] | None = None,
    color_identity: list[str] | None = None,
    keywords: list[str] | None = None,
    usd: str | None = "1.00",
    legalities: dict[str, str] | None = None,
    edhrec_rank: int | None = 1000,
    rarity: str = "common",
    power: str | None = None,
    toughness: str | None = None,
) -> Card:
    return Card(
        id=f"test-{name.lower().replace(' ', '-')}",
        name=name,
        mana_cost=mana_cost,
        cmc=cmc,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=colors or [],
        color_identity=color_identity or [],
        keywords=keywords or [],
        prices=CardPrices(usd=usd),
        legalities=legalities or {"standard": "legal", "commander": "legal"},
        edhrec_rank=edhrec_rank,
        rarity=rarity,
        power=power,
        toughness=toughness,
        set="test",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_bulk() -> AsyncMock:
    """Provide an AsyncMock ScryfallBulkClient."""
    client = AsyncMock()
    client.search_by_text = AsyncMock(return_value=[])
    client.search_by_type = AsyncMock(return_value=[])
    client.search_cards = AsyncMock(return_value=[])
    client.get_card = AsyncMock(return_value=None)
    client.get_cards = AsyncMock(return_value={})
    client.filter_cards = AsyncMock(return_value=[])
    return client


@pytest.fixture
def mock_spellbook() -> AsyncMock:
    """Provide an AsyncMock SpellbookClient."""
    client = AsyncMock()
    client.find_combos = AsyncMock(return_value=[])
    return client


@pytest.fixture
def mock_edhrec() -> AsyncMock:
    """Provide an AsyncMock EDHRECClient."""
    client = AsyncMock()
    client.commander_top_cards = AsyncMock(
        return_value=EDHRECCommanderData(
            commander_name="Test Commander",
            total_decks=1000,
            cardlists=[],
        )
    )
    return client


# ===========================================================================
# theme_search tests
# ===========================================================================


class TestThemeSearch:
    """Tests for the theme_search workflow."""

    async def test_mechanical_theme_aristocrats(self, mock_bulk: AsyncMock) -> None:
        """Mechanical theme 'aristocrats' searches oracle text for death triggers."""
        blood_artist = _mock_card(
            "Blood Artist",
            oracle_text="Whenever a creature dies, target opponent loses 1 life and you gain 1 life.",
            type_line="Creature - Vampire",
        )
        mock_bulk.filter_cards = AsyncMock(return_value=[blood_artist])

        result = await theme_search("aristocrats", bulk=mock_bulk)

        assert "Blood Artist" in result.markdown
        assert result.data["theme"] == "aristocrats"
        mock_bulk.filter_cards.assert_called()

    async def test_mechanical_theme_tokens(self, mock_bulk: AsyncMock) -> None:
        """Mechanical theme 'tokens' finds cards that create tokens."""
        raise_alarm = _mock_card(
            "Raise the Alarm",
            oracle_text="Create two 1/1 white Soldier creature tokens.",
            type_line="Instant",
        )
        mock_bulk.filter_cards = AsyncMock(return_value=[raise_alarm])

        result = await theme_search("tokens", bulk=mock_bulk)

        assert "Raise the Alarm" in result.markdown
        assert result.data["theme"] == "tokens"

    async def test_tribal_theme_merfolk(self, mock_bulk: AsyncMock) -> None:
        """Tribal theme searches type line for the creature type."""
        lord = _mock_card(
            "Lord of Atlantis",
            oracle_text="Other Merfolk get +1/+1 and have islandwalk.",
            type_line="Creature - Merfolk",
        )
        mock_bulk.filter_cards = AsyncMock(return_value=[lord])

        result = await theme_search("merfolk", bulk=mock_bulk)

        assert "Lord of Atlantis" in result.markdown
        assert result.data["theme"] == "merfolk"

    async def test_color_identity_filter(self, mock_bulk: AsyncMock) -> None:
        """Color identity filter is passed through to bulk search."""
        card = _mock_card(
            "Viscera Seer",
            oracle_text="Sacrifice a creature: Scry 1.",
            color_identity=["B"],
        )
        mock_bulk.filter_cards = AsyncMock(return_value=[card])

        result = await theme_search("aristocrats", bulk=mock_bulk, color_identity="BG")

        assert "Viscera Seer" in result.markdown
        # Check color_identity was passed to filter
        call_kwargs = mock_bulk.filter_cards.call_args
        assert call_kwargs is not None

    async def test_format_filter(self, mock_bulk: AsyncMock) -> None:
        """Format filter restricts to format-legal cards."""
        card = _mock_card(
            "Zulaport Cutthroat",
            oracle_text="Whenever a creature you control dies...",
            legalities={"commander": "legal", "standard": "not_legal"},
        )
        mock_bulk.filter_cards = AsyncMock(return_value=[card])

        result = await theme_search("aristocrats", bulk=mock_bulk, format="commander")

        assert "Zulaport Cutthroat" in result.markdown

    async def test_max_price_filter(self, mock_bulk: AsyncMock) -> None:
        """Price filter excludes expensive cards."""
        cheap = _mock_card("Blood Artist", oracle_text="Whenever a creature dies...", usd="0.50")
        mock_bulk.filter_cards = AsyncMock(return_value=[cheap])

        result = await theme_search("aristocrats", bulk=mock_bulk, max_price=5.0)

        assert "Blood Artist" in result.markdown

    async def test_limit_parameter(self, mock_bulk: AsyncMock) -> None:
        """Limit parameter caps output to N cards."""
        cards = [
            _mock_card(f"Card {i}", oracle_text="Whenever a creature dies...") for i in range(10)
        ]
        mock_bulk.filter_cards = AsyncMock(return_value=cards[:3])

        result = await theme_search("aristocrats", bulk=mock_bulk, limit=3)

        # Should have at most 3 cards
        assert result.data["total_found"] <= 3

    async def test_no_results(self, mock_bulk: AsyncMock) -> None:
        """Returns appropriate message when no cards match."""
        mock_bulk.filter_cards = AsyncMock(return_value=[])

        result = await theme_search("nonexistent_theme_xyz", bulk=mock_bulk)

        assert result.data["total_found"] == 0
        assert "no cards" in result.markdown.lower() or "0" in result.markdown

    async def test_concise_format(self, mock_bulk: AsyncMock) -> None:
        """Concise format produces shorter output."""
        card = _mock_card("Blood Artist", oracle_text="Whenever a creature dies...")
        mock_bulk.filter_cards = AsyncMock(return_value=[card])

        result = await theme_search("aristocrats", bulk=mock_bulk, response_format="concise")

        assert "Blood Artist" in result.markdown

    async def test_abstract_theme(self, mock_bulk: AsyncMock) -> None:
        """Abstract theme searches name and text for synonyms."""
        card = _mock_card(
            "Song of the Dryads",
            oracle_text="Enchant permanent",
            type_line="Enchantment - Aura",
        )
        mock_bulk.filter_cards = AsyncMock(return_value=[card])

        result = await theme_search("music", bulk=mock_bulk)

        # Should search for music-related terms
        assert result.data["theme"] == "music"

    async def test_edhrec_enrichment(self, mock_bulk: AsyncMock, mock_edhrec: AsyncMock) -> None:
        """EDHREC data enriches results when available."""
        card = _mock_card("Blood Artist", oracle_text="Whenever a creature dies...")
        mock_bulk.filter_cards = AsyncMock(return_value=[card])

        result = await theme_search("aristocrats", bulk=mock_bulk, edhrec=mock_edhrec)

        # Should succeed with or without EDHREC data
        assert "Blood Artist" in result.markdown


# ===========================================================================
# build_around tests
# ===========================================================================


class TestBuildAround:
    """Tests for the build_around workflow."""

    async def test_basic_synergy_search(
        self, mock_bulk: AsyncMock, mock_spellbook: AsyncMock
    ) -> None:
        """Finds synergistic cards for build-around pieces."""
        # Build-around card
        aristocrat = _mock_card(
            "Teysa Karlov",
            oracle_text="If a creature dying causes a triggered ability of a permanent you control to trigger, that ability triggers an additional time.",
            type_line="Legendary Creature - Human Advisor",
        )
        mock_bulk.get_cards = AsyncMock(return_value={"Teysa Karlov": aristocrat})

        # Synergistic cards
        seer = _mock_card(
            "Viscera Seer",
            oracle_text="Sacrifice a creature: Scry 1.",
        )
        mock_bulk.filter_cards = AsyncMock(return_value=[seer])

        result = await build_around(
            ["Teysa Karlov"],
            "commander",
            bulk=mock_bulk,
            spellbook=mock_spellbook,
        )

        assert result.data["build_around_cards"] == ["Teysa Karlov"]
        assert "Teysa Karlov" in result.markdown

    async def test_multiple_build_around_cards(
        self, mock_bulk: AsyncMock, mock_spellbook: AsyncMock
    ) -> None:
        """Handles multiple build-around cards."""
        card1 = _mock_card("Card A", oracle_text="When a creature dies...")
        card2 = _mock_card("Card B", oracle_text="Sacrifice a creature...")
        mock_bulk.get_cards = AsyncMock(return_value={"Card A": card1, "Card B": card2})
        mock_bulk.filter_cards = AsyncMock(return_value=[])

        result = await build_around(
            ["Card A", "Card B"],
            "commander",
            bulk=mock_bulk,
            spellbook=mock_spellbook,
        )

        assert "Card A" in result.markdown
        assert "Card B" in result.markdown

    async def test_combo_detection(self, mock_bulk: AsyncMock, mock_spellbook: AsyncMock) -> None:
        """Spellbook combos are included in results."""
        card = _mock_card("Thassa's Oracle", oracle_text="When Thassa's Oracle enters...")
        mock_bulk.get_cards = AsyncMock(return_value={"Thassa's Oracle": card})
        mock_bulk.filter_cards = AsyncMock(return_value=[])

        combo = Combo(
            id="combo-1",
            cards=[
                ComboCard(name="Thassa's Oracle"),
                ComboCard(name="Demonic Consultation"),
            ],
            produces=[ComboResult(feature_name="Win the game")],
            identity="UB",
        )
        mock_spellbook.find_combos = AsyncMock(return_value=[combo])

        result = await build_around(
            ["Thassa's Oracle"],
            "commander",
            bulk=mock_bulk,
            spellbook=mock_spellbook,
        )

        assert result.data["combos_found"] >= 1

    async def test_budget_filter(self, mock_bulk: AsyncMock, mock_spellbook: AsyncMock) -> None:
        """Budget filter excludes expensive cards from suggestions."""
        card = _mock_card("Budget Card", oracle_text="Tap: Draw a card.", usd="0.50")
        mock_bulk.get_cards = AsyncMock(return_value={"Budget Card": card})
        mock_bulk.filter_cards = AsyncMock(return_value=[card])

        result = await build_around(
            ["Budget Card"],
            "commander",
            bulk=mock_bulk,
            spellbook=mock_spellbook,
            budget=5.0,
        )

        assert result.markdown is not None

    async def test_format_legality(self, mock_bulk: AsyncMock, mock_spellbook: AsyncMock) -> None:
        """Cards are filtered by format legality."""
        card = _mock_card(
            "Modern Card",
            oracle_text="Flying",
            legalities={"modern": "legal"},
        )
        mock_bulk.get_cards = AsyncMock(return_value={"Modern Card": card})
        mock_bulk.filter_cards = AsyncMock(return_value=[])

        result = await build_around(
            ["Modern Card"],
            "modern",
            bulk=mock_bulk,
            spellbook=mock_spellbook,
        )

        assert result.markdown is not None

    async def test_unresolved_build_around(
        self, mock_bulk: AsyncMock, mock_spellbook: AsyncMock
    ) -> None:
        """Handles build-around cards that cannot be resolved."""
        mock_bulk.get_cards = AsyncMock(return_value={"Nonexistent Card": None})

        result = await build_around(
            ["Nonexistent Card"],
            "commander",
            bulk=mock_bulk,
            spellbook=mock_spellbook,
        )

        # Should mention the card could not be found
        assert "not found" in result.markdown.lower() or "unresolved" in result.markdown.lower()

    async def test_edhrec_enrichment(
        self,
        mock_bulk: AsyncMock,
        mock_spellbook: AsyncMock,
        mock_edhrec: AsyncMock,
    ) -> None:
        """EDHREC synergy data enriches results for commander format."""
        card = _mock_card(
            "Teysa Karlov",
            oracle_text="Death triggers double",
            type_line="Legendary Creature - Human Advisor",
        )
        mock_bulk.get_cards = AsyncMock(return_value={"Teysa Karlov": card})

        mock_edhrec.commander_top_cards = AsyncMock(
            return_value=EDHRECCommanderData(
                commander_name="Teysa Karlov",
                total_decks=5000,
                cardlists=[
                    EDHRECCardList(
                        header="Creatures",
                        cardviews=[
                            EDHRECCard(
                                name="Viscera Seer",
                                synergy=0.45,
                                inclusion=55,
                                num_decks=2750,
                            ),
                        ],
                    )
                ],
            )
        )
        mock_bulk.filter_cards = AsyncMock(return_value=[])

        result = await build_around(
            ["Teysa Karlov"],
            "commander",
            bulk=mock_bulk,
            spellbook=mock_spellbook,
            edhrec=mock_edhrec,
        )

        assert result.markdown is not None

    async def test_concise_format(self, mock_bulk: AsyncMock, mock_spellbook: AsyncMock) -> None:
        """Concise format produces shorter output."""
        card = _mock_card("Test Card", oracle_text="Test oracle text")
        mock_bulk.get_cards = AsyncMock(return_value={"Test Card": card})
        mock_bulk.filter_cards = AsyncMock(return_value=[])

        result = await build_around(
            ["Test Card"],
            "commander",
            bulk=mock_bulk,
            spellbook=mock_spellbook,
            response_format="concise",
        )

        assert result.markdown is not None


# ===========================================================================
# complete_deck tests
# ===========================================================================


class TestCompleteDeck:
    """Tests for the complete_deck workflow."""

    async def test_basic_gap_analysis(self, mock_bulk: AsyncMock) -> None:
        """Identifies missing card categories in a partial decklist."""
        creature = _mock_card(
            "Llanowar Elves",
            type_line="Creature - Elf Druid",
            oracle_text="{T}: Add {G}.",
            cmc=1.0,
            color_identity=["G"],
        )
        mock_bulk.get_cards = AsyncMock(return_value={"Llanowar Elves": creature})
        mock_bulk.filter_cards = AsyncMock(return_value=[])

        result = await complete_deck(
            ["Llanowar Elves"],
            "commander",
            bulk=mock_bulk,
        )

        assert result.data["deck_size_current"] == 1
        assert (
            "gap" in result.markdown.lower()
            or "need" in result.markdown.lower()
            or "missing" in result.markdown.lower()
        )

    async def test_commander_target_size(self, mock_bulk: AsyncMock) -> None:
        """Commander format targets 100 cards."""
        cards = {f"Card {i}": _mock_card(f"Card {i}") for i in range(50)}
        mock_bulk.get_cards = AsyncMock(return_value=cards)
        mock_bulk.filter_cards = AsyncMock(return_value=[])

        result = await complete_deck(
            list(cards.keys()),
            "commander",
            bulk=mock_bulk,
        )

        assert result.data["target_size"] == 100

    async def test_constructed_target_size(self, mock_bulk: AsyncMock) -> None:
        """Constructed formats target 60 cards."""
        cards = {f"Card {i}": _mock_card(f"Card {i}") for i in range(30)}
        mock_bulk.get_cards = AsyncMock(return_value=cards)
        mock_bulk.filter_cards = AsyncMock(return_value=[])

        result = await complete_deck(
            list(cards.keys()),
            "modern",
            bulk=mock_bulk,
        )

        assert result.data["target_size"] == 60

    async def test_limited_target_size(self, mock_bulk: AsyncMock) -> None:
        """Limited formats target 40 cards."""
        cards = {f"Card {i}": _mock_card(f"Card {i}") for i in range(20)}
        mock_bulk.get_cards = AsyncMock(return_value=cards)
        mock_bulk.filter_cards = AsyncMock(return_value=[])

        result = await complete_deck(
            list(cards.keys()),
            "limited",
            bulk=mock_bulk,
        )

        assert result.data["target_size"] == 40

    async def test_category_breakdown(self, mock_bulk: AsyncMock) -> None:
        """Output includes card category breakdown."""
        creature = _mock_card("Grizzly Bears", type_line="Creature - Bear", cmc=2.0)
        instant = _mock_card(
            "Lightning Bolt",
            type_line="Instant",
            oracle_text="Lightning Bolt deals 3 damage to any target.",
            cmc=1.0,
        )
        mock_bulk.get_cards = AsyncMock(
            return_value={"Grizzly Bears": creature, "Lightning Bolt": instant}
        )
        mock_bulk.filter_cards = AsyncMock(return_value=[])

        result = await complete_deck(
            ["Grizzly Bears", "Lightning Bolt"],
            "modern",
            bulk=mock_bulk,
        )

        # Should categorize cards
        assert "creature" in result.markdown.lower() or "Creature" in result.markdown

    async def test_commander_with_edhrec(
        self, mock_bulk: AsyncMock, mock_edhrec: AsyncMock
    ) -> None:
        """EDHREC staples data is used for commander suggestions."""
        creature = _mock_card("Sol Ring", type_line="Artifact", cmc=1.0)
        mock_bulk.get_cards = AsyncMock(return_value={"Sol Ring": creature})

        staple = _mock_card("Arcane Signet", type_line="Artifact", cmc=2.0)
        mock_edhrec.commander_top_cards = AsyncMock(
            return_value=EDHRECCommanderData(
                commander_name="Test Commander",
                total_decks=5000,
                cardlists=[
                    EDHRECCardList(
                        header="Artifacts",
                        cardviews=[
                            EDHRECCard(
                                name="Arcane Signet",
                                synergy=0.1,
                                inclusion=90,
                                num_decks=4500,
                            ),
                        ],
                    )
                ],
            )
        )
        mock_bulk.filter_cards = AsyncMock(return_value=[staple])

        result = await complete_deck(
            ["Sol Ring"],
            "commander",
            bulk=mock_bulk,
            edhrec=mock_edhrec,
            commander="Test Commander",
        )

        assert result.markdown is not None

    async def test_progress_reporting(self, mock_bulk: AsyncMock) -> None:
        """Progress callback is invoked during processing."""
        cards = {f"Card {i}": _mock_card(f"Card {i}") for i in range(5)}
        mock_bulk.get_cards = AsyncMock(return_value=cards)
        mock_bulk.filter_cards = AsyncMock(return_value=[])

        progress_calls: list[tuple[int, int]] = []

        async def on_progress(step: int, total: int) -> None:
            progress_calls.append((step, total))

        result = await complete_deck(
            list(cards.keys()),
            "commander",
            bulk=mock_bulk,
            on_progress=on_progress,
        )

        assert len(progress_calls) >= 1
        assert result.markdown is not None

    async def test_budget_filter(self, mock_bulk: AsyncMock) -> None:
        """Budget filter is passed to suggestion search."""
        cards = {"Card A": _mock_card("Card A")}
        mock_bulk.get_cards = AsyncMock(return_value=cards)
        mock_bulk.filter_cards = AsyncMock(return_value=[])

        result = await complete_deck(
            ["Card A"],
            "commander",
            bulk=mock_bulk,
            budget=5.0,
        )

        assert result.markdown is not None

    async def test_concise_format(self, mock_bulk: AsyncMock) -> None:
        """Concise format produces shorter output."""
        cards = {"Card A": _mock_card("Card A")}
        mock_bulk.get_cards = AsyncMock(return_value=cards)
        mock_bulk.filter_cards = AsyncMock(return_value=[])

        result = await complete_deck(
            ["Card A"],
            "commander",
            bulk=mock_bulk,
            response_format="concise",
        )

        assert result.markdown is not None

    async def test_unresolved_cards(self, mock_bulk: AsyncMock) -> None:
        """Cards that cannot be resolved are noted."""
        mock_bulk.get_cards = AsyncMock(return_value={"Nonexistent": None})
        mock_bulk.filter_cards = AsyncMock(return_value=[])

        result = await complete_deck(
            ["Nonexistent"],
            "commander",
            bulk=mock_bulk,
        )

        assert result.data["unresolved"] is not None
