"""Tests for sideboard workflow functions."""

from __future__ import annotations

from typing import ClassVar
from unittest.mock import AsyncMock

import pytest

from mtg_mcp_server.services.mtggoldfish import MTGGoldfishError
from mtg_mcp_server.types import (
    Card,
    CardPrices,
    GoldfishArchetype,
    GoldfishFormatStaple,
    GoldfishMetaSnapshot,
)
from mtg_mcp_server.workflows.sideboard import (
    _classify_archetype_strategy,
    _classify_sideboard_card,
    _extract_deck_colors,
    _infer_matchup_colors,
    _match_archetype_name,
    _opposing_colors,
    sideboard_guide,
    sideboard_matrix,
    suggest_sideboard,
)

# ---------------------------------------------------------------------------
# Mock card helper
# ---------------------------------------------------------------------------


def _mock_card(
    name: str,
    *,
    oracle_text: str = "",
    type_line: str = "Creature",
    colors: list[str] | None = None,
    color_identity: list[str] | None = None,
    mana_cost: str = "{1}",
    cmc: float = 1.0,
    keywords: list[str] | None = None,
    usd: str | None = "1.00",
    rarity: str = "common",
) -> Card:
    """Create a Card object for testing."""
    return Card(
        id=f"test-{name.lower().replace(' ', '-')}",
        name=name,
        oracle_text=oracle_text,
        type_line=type_line,
        colors=colors or [],
        color_identity=color_identity or [],
        mana_cost=mana_cost,
        cmc=cmc,
        keywords=keywords or [],
        prices=CardPrices(usd=usd),
        rarity=rarity,
        set_code="tst",
        legalities={"modern": "legal", "legacy": "legal"},
    )


# ---------------------------------------------------------------------------
# Shared test cards
# ---------------------------------------------------------------------------

BOLT = _mock_card(
    "Lightning Bolt",
    oracle_text="Lightning Bolt deals 3 damage to any target.",
    type_line="Instant",
    colors=["R"],
    color_identity=["R"],
    mana_cost="{R}",
    cmc=1.0,
)
COUNTERSPELL = _mock_card(
    "Counterspell",
    oracle_text="Counter target spell.",
    type_line="Instant",
    colors=["U"],
    color_identity=["U"],
    mana_cost="{U}{U}",
    cmc=2.0,
)
WRATH = _mock_card(
    "Wrath of God",
    oracle_text="Destroy all creatures. They can't be regenerated.",
    type_line="Sorcery",
    colors=["W"],
    color_identity=["W"],
    mana_cost="{2}{W}{W}",
    cmc=4.0,
)
NATURALIZE = _mock_card(
    "Naturalize",
    oracle_text="Destroy target artifact or destroy target enchantment.",
    type_line="Instant",
    colors=["G"],
    color_identity=["G"],
    mana_cost="{1}{G}",
    cmc=2.0,
)
RIP = _mock_card(
    "Rest in Peace",
    oracle_text="When Rest in Peace enters the battlefield, exile all cards from all graveyards. "
    "If a card or token would be put into a graveyard from anywhere, exile it instead.",
    type_line="Enchantment",
    colors=["W"],
    color_identity=["W"],
    mana_cost="{1}{W}",
    cmc=2.0,
)
CREATURE_A = _mock_card(
    "Goblin Guide",
    oracle_text="Haste. Whenever Goblin Guide attacks, defending player reveals the top card of their library.",
    type_line="Creature -- Goblin Scout",
    colors=["R"],
    color_identity=["R"],
    mana_cost="{R}",
    cmc=1.0,
)
BIG_CREATURE = _mock_card(
    "Primeval Titan",
    oracle_text="Trample. When Primeval Titan enters the battlefield or attacks, you may search your library for up to two land cards.",
    type_line="Creature -- Giant",
    colors=["G"],
    color_identity=["G"],
    mana_cost="{4}{G}{G}",
    cmc=6.0,
)
REMOVAL = _mock_card(
    "Fatal Push",
    oracle_text="Destroy target creature with mana value 2 or less.",
    type_line="Instant",
    colors=["B"],
    color_identity=["B"],
    mana_cost="{B}",
    cmc=1.0,
)
DISENCHANT = _mock_card(
    "Disenchant",
    oracle_text="Destroy target artifact or destroy target enchantment.",
    type_line="Instant",
    colors=["W"],
    color_identity=["W"],
    mana_cost="{1}{W}",
    cmc=2.0,
)
SKULLCRACK = _mock_card(
    "Skullcrack",
    oracle_text="Players can't gain life this turn. Damage can't be prevented this turn. "
    "Skullcrack deals 3 damage to target opponent.",
    type_line="Instant",
    colors=["R"],
    color_identity=["R"],
    mana_cost="{1}{R}",
    cmc=2.0,
)
PYROBLAST = _mock_card(
    "Pyroblast",
    oracle_text="Counter target spell if it's blue.",
    type_line="Instant",
    colors=["R"],
    color_identity=["R"],
    mana_cost="{R}",
    cmc=1.0,
)
HYDROBLAST = _mock_card(
    "Hydroblast",
    oracle_text="Counter target spell if it's red.",
    type_line="Instant",
    colors=["U"],
    color_identity=["U"],
    mana_cost="{U}",
    cmc=1.0,
)
SURGICAL = _mock_card(
    "Surgical Extraction",
    oracle_text="Exile target card from a graveyard. "
    "You may exile target card from your graveyard rather than pay this spell's mana cost.",
    type_line="Instant",
    colors=["B"],
    color_identity=["B"],
    mana_cost="{1}{B/P}",
    cmc=1.0,
)
PYROCLASM = _mock_card(
    "Pyroclasm",
    oracle_text="Pyroclasm deals 2 damage to each creature.",
    type_line="Sorcery",
    colors=["R"],
    color_identity=["R"],
    mana_cost="{1}{R}",
    cmc=2.0,
)
AURIOK = _mock_card(
    "Auriok Champion",
    oracle_text="Protection from black and from green.",
    type_line="Creature -- Human Cleric",
    colors=["W"],
    color_identity=["W"],
    mana_cost="{W}{W}",
    cmc=2.0,
)
PRO_WHITE_BURN = _mock_card(
    "Pro-White Bolt",
    oracle_text="Protection from white. Pro-White Bolt deals 2 damage to any target.",
    type_line="Instant",
    colors=["R"],
    color_identity=["R"],
    mana_cost="{1}{R}",
    cmc=2.0,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_bulk() -> AsyncMock:
    """Provide a mock ScryfallBulkClient."""
    client = AsyncMock()
    # Default: get_cards returns a dict of name -> Card
    client.get_cards = AsyncMock(
        return_value={
            "Lightning Bolt": BOLT,
            "Counterspell": COUNTERSPELL,
            "Goblin Guide": CREATURE_A,
            "Primeval Titan": BIG_CREATURE,
            "Fatal Push": REMOVAL,
            "Wrath of God": WRATH,
            "Rest in Peace": RIP,
            "Naturalize": NATURALIZE,
            "Skullcrack": SKULLCRACK,
            "Disenchant": DISENCHANT,
        }
    )
    # filter_cards returns a small set of candidates
    client.filter_cards = AsyncMock(return_value=[RIP, COUNTERSPELL, WRATH])
    return client


@pytest.fixture
def mock_goldfish() -> AsyncMock:
    """Provide a mock MTGGoldfishClient."""
    client = AsyncMock()
    client.get_format_staples = AsyncMock(
        return_value=[
            GoldfishFormatStaple(
                rank=1, name="Lightning Bolt", pct_of_decks=45.0, copies_played=4.0
            ),
            GoldfishFormatStaple(rank=2, name="Counterspell", pct_of_decks=30.0, copies_played=3.0),
            GoldfishFormatStaple(
                rank=3, name="Rest in Peace", pct_of_decks=20.0, copies_played=2.0
            ),
        ]
    )
    client.get_metagame = AsyncMock(
        return_value=GoldfishMetaSnapshot(
            format="modern",
            archetypes=[
                GoldfishArchetype(name="Boros Energy", slug="boros-energy", meta_share=15.0),
                GoldfishArchetype(name="Azorius Control", slug="azorius-control", meta_share=10.0),
                GoldfishArchetype(name="Mono-Red Aggro", slug="mono-red-aggro", meta_share=8.0),
                GoldfishArchetype(name="Storm Combo", slug="storm-combo", meta_share=6.0),
                GoldfishArchetype(name="Murktide Tempo", slug="murktide-tempo", meta_share=5.0),
                GoldfishArchetype(name="Jund Midrange", slug="jund-midrange", meta_share=4.0),
            ],
            total_decks=200,
        )
    )
    return client


# ===========================================================================
# Unit tests for helper functions
# ===========================================================================


class TestExtractDeckColors:
    """Test _extract_deck_colors helper."""

    def test_extracts_colors_from_resolved(self) -> None:
        resolved = {"Bolt": BOLT, "Counter": COUNTERSPELL}
        colors = _extract_deck_colors(resolved)
        assert colors == {"R", "U"}

    def test_skips_none(self) -> None:
        resolved: dict[str, Card | None] = {"Bolt": BOLT, "Unknown": None}
        colors = _extract_deck_colors(resolved)
        assert colors == {"R"}

    def test_empty_dict(self) -> None:
        assert _extract_deck_colors({}) == set()


class TestOpposingColors:
    """Test _opposing_colors helper."""

    def test_returns_complement(self) -> None:
        assert _opposing_colors({"R", "U"}) == {"W", "B", "G"}

    def test_all_colors(self) -> None:
        assert _opposing_colors({"W", "U", "B", "R", "G"}) == set()

    def test_empty(self) -> None:
        assert _opposing_colors(set()) == {"W", "U", "B", "R", "G"}


class TestMatchArchetypeName:
    """Test _match_archetype_name helper."""

    def test_exact_match(self) -> None:
        result = _match_archetype_name("Aggro", ["Aggro", "Control", "Combo"])
        assert result == "Aggro"

    def test_substring_match(self) -> None:
        result = _match_archetype_name("aggro", ["Mono-Red Aggro", "Control"])
        assert result == "Mono-Red Aggro"

    def test_unknown_returns_query(self) -> None:
        result = _match_archetype_name("Weird Brew", ["Aggro", "Control"])
        assert result == "Weird Brew"

    def test_empty_query_returns_none(self) -> None:
        assert _match_archetype_name("", ["Aggro"]) is None


class TestClassifyArchetypeStrategy:
    """Test _classify_archetype_strategy helper."""

    def test_aggro(self) -> None:
        assert _classify_archetype_strategy("Mono-Red Aggro") == "aggro"

    def test_control(self) -> None:
        assert _classify_archetype_strategy("Azorius Control") == "control"

    def test_combo(self) -> None:
        assert _classify_archetype_strategy("Storm Combo") == "combo"

    def test_tempo(self) -> None:
        assert _classify_archetype_strategy("Murktide Tempo") == "tempo"

    def test_midrange(self) -> None:
        assert _classify_archetype_strategy("Jund Midrange") == "midrange"

    def test_unknown_defaults_midrange(self) -> None:
        assert _classify_archetype_strategy("Unknown Brew") == "midrange"

    def test_burn_classified_as_aggro(self) -> None:
        assert _classify_archetype_strategy("Burn") == "aggro"


# ===========================================================================
# suggest_sideboard tests
# ===========================================================================


class TestSuggestSideboardSuccess:
    """suggest_sideboard with bulk data only (no MTGGoldfish)."""

    async def test_returns_categories_and_cards(self, mock_bulk: AsyncMock) -> None:
        result = await suggest_sideboard(
            ["4x Lightning Bolt", "4x Goblin Guide"],
            "modern",
            bulk=mock_bulk,
        )

        assert "Sideboard Suggestions" in result.markdown
        assert isinstance(result.data, dict)
        assert result.data["format"] == "modern"
        assert isinstance(result.data["suggested_cards"], list)
        assert result.data["total_cards"] <= 15

    async def test_deduplicates_against_main_deck(self, mock_bulk: AsyncMock) -> None:
        """Cards in the main deck are not suggested for the sideboard."""
        # filter_cards returns cards that include Lightning Bolt (which is in main deck)
        mock_bulk.filter_cards = AsyncMock(return_value=[BOLT, RIP, COUNTERSPELL])

        result = await suggest_sideboard(
            ["4x Lightning Bolt"],
            "modern",
            bulk=mock_bulk,
        )

        suggested_names = [c["name"] for c in result.data["suggested_cards"]]
        assert "Lightning Bolt" not in suggested_names

    async def test_categories_in_structured_data(self, mock_bulk: AsyncMock) -> None:
        result = await suggest_sideboard(
            ["4x Lightning Bolt"],
            "modern",
            bulk=mock_bulk,
        )

        assert "categories" in result.data
        categories = result.data["categories"]
        assert isinstance(categories, dict)

    async def test_empty_decklist(self, mock_bulk: AsyncMock) -> None:
        result = await suggest_sideboard([], "modern", bulk=mock_bulk)
        assert "No main deck cards provided" in result.markdown
        assert result.data["total_cards"] == 0


class TestSuggestSideboardWithGoldfish:
    """suggest_sideboard with MTGGoldfish format staples."""

    async def test_marks_format_staples(
        self, mock_bulk: AsyncMock, mock_goldfish: AsyncMock
    ) -> None:
        # filter_cards returns cards that include ones matching staple names
        mock_bulk.filter_cards = AsyncMock(return_value=[RIP, COUNTERSPELL])

        result = await suggest_sideboard(
            ["4x Lightning Bolt"],
            "modern",
            bulk=mock_bulk,
            mtggoldfish=mock_goldfish,
        )

        # At least one card should be marked as format staple in reasoning
        suggested = result.data["suggested_cards"]
        staple_found = any("format staple" in c.get("reasoning", "") for c in suggested)
        assert staple_found

    async def test_goldfish_failure_degrades_gracefully(self, mock_bulk: AsyncMock) -> None:
        """MTGGoldfish failure doesn't crash — falls back to heuristic-only."""
        mock_goldfish_failing = AsyncMock()
        mock_goldfish_failing.get_format_staples = AsyncMock(
            side_effect=MTGGoldfishError("MTGGoldfish is down")
        )

        result = await suggest_sideboard(
            ["4x Lightning Bolt"],
            "modern",
            bulk=mock_bulk,
            mtggoldfish=mock_goldfish_failing,
        )

        assert "Sideboard Suggestions" in result.markdown
        assert result.data["total_cards"] > 0


class TestSuggestSideboardMetaContext:
    """suggest_sideboard with meta_context prioritization."""

    async def test_aggro_context_boosts_board_wipes(self, mock_bulk: AsyncMock) -> None:
        result = await suggest_sideboard(
            ["4x Lightning Bolt"],
            "modern",
            bulk=mock_bulk,
            meta_context="heavy on Mono-Red aggro strategies",
        )

        # Should have suggestions — categories should include Board Wipes
        assert result.data["total_cards"] > 0

    async def test_graveyard_context_boosts_gy_hate(self, mock_bulk: AsyncMock) -> None:
        result = await suggest_sideboard(
            ["4x Lightning Bolt"],
            "modern",
            bulk=mock_bulk,
            meta_context="lots of graveyard decks and reanimator",
        )

        assert result.data["total_cards"] > 0


class TestSuggestSideboardResponseFormat:
    """Concise vs detailed output."""

    async def test_concise_shorter_than_detailed(self, mock_bulk: AsyncMock) -> None:
        detailed = await suggest_sideboard(
            ["4x Lightning Bolt"],
            "modern",
            bulk=mock_bulk,
            response_format="detailed",
        )
        concise = await suggest_sideboard(
            ["4x Lightning Bolt"],
            "modern",
            bulk=mock_bulk,
            response_format="concise",
        )

        assert len(concise.markdown) < len(detailed.markdown)


# ===========================================================================
# sideboard_guide tests
# ===========================================================================


class TestSideboardGuideSuccess:
    """sideboard_guide with basic success paths."""

    async def test_produces_in_out_plan(self, mock_bulk: AsyncMock) -> None:
        result = await sideboard_guide(
            decklist=["4x Lightning Bolt", "4x Goblin Guide", "4x Primeval Titan"],
            sideboard=["2x Counterspell", "2x Wrath of God", "2x Rest in Peace"],
            format="modern",
            matchup="Mono-Red Aggro",
            bulk=mock_bulk,
        )

        assert "vs" in result.markdown
        assert isinstance(result.data, dict)
        assert "matchup" in result.data
        assert "ins" in result.data
        assert "outs" in result.data
        assert "reasoning" in result.data

    async def test_aggro_matchup_cuts_expensive(self, mock_bulk: AsyncMock) -> None:
        """Against aggro, expensive cards (cmc >= 5) should be suggested as outs."""
        result = await sideboard_guide(
            decklist=["4x Primeval Titan", "4x Lightning Bolt"],
            sideboard=["2x Wrath of God"],
            format="modern",
            matchup="Mono-Red Aggro",
            bulk=mock_bulk,
        )

        out_names = [o["name"] for o in result.data["outs"]]
        # Aggro matchup should produce outs (slow/expensive cards are cut candidates)
        assert len(out_names) > 0

    async def test_control_matchup_cuts_removal(self, mock_bulk: AsyncMock) -> None:
        """Against control, creature removal should be suggested as outs."""
        result = await sideboard_guide(
            decklist=["4x Fatal Push", "4x Goblin Guide"],
            sideboard=["2x Counterspell"],
            format="modern",
            matchup="Azorius Control",
            bulk=mock_bulk,
        )

        out_names = [o["name"] for o in result.data["outs"]]
        # Fatal Push has "Destroy target creature" text -- should be cut vs control
        assert "Fatal Push" in out_names

    async def test_empty_decklist(self, mock_bulk: AsyncMock) -> None:
        result = await sideboard_guide(
            decklist=[],
            sideboard=["2x Counterspell"],
            format="modern",
            matchup="Aggro",
            bulk=mock_bulk,
        )

        assert "required" in result.markdown.lower()
        assert result.data["ins"] == []
        assert result.data["outs"] == []

    async def test_empty_sideboard(self, mock_bulk: AsyncMock) -> None:
        result = await sideboard_guide(
            decklist=["4x Lightning Bolt"],
            sideboard=[],
            format="modern",
            matchup="Aggro",
            bulk=mock_bulk,
        )

        assert "required" in result.markdown.lower()


class TestSideboardGuideWithGoldfish:
    """sideboard_guide with MTGGoldfish archetype matching."""

    async def test_uses_goldfish_archetypes(
        self, mock_bulk: AsyncMock, mock_goldfish: AsyncMock
    ) -> None:
        result = await sideboard_guide(
            decklist=["4x Lightning Bolt", "4x Goblin Guide"],
            sideboard=["2x Counterspell", "2x Rest in Peace"],
            format="modern",
            matchup="Azorius Control",
            bulk=mock_bulk,
            mtggoldfish=mock_goldfish,
        )

        # Should match against the goldfish archetype list
        assert result.data["matchup"] == "Azorius Control"

    async def test_goldfish_failure_falls_back(self, mock_bulk: AsyncMock) -> None:
        mock_goldfish_failing = AsyncMock()
        mock_goldfish_failing.get_metagame = AsyncMock(
            side_effect=MTGGoldfishError("MTGGoldfish down")
        )

        result = await sideboard_guide(
            decklist=["4x Lightning Bolt"],
            sideboard=["2x Counterspell"],
            format="modern",
            matchup="Aggro",
            bulk=mock_bulk,
            mtggoldfish=mock_goldfish_failing,
        )

        # Should still produce a result using default archetypes
        assert "vs" in result.markdown


class TestSideboardGuideComboMatchup:
    """sideboard_guide for combo matchups."""

    async def test_combo_strategy_brings_counterspells(self, mock_bulk: AsyncMock) -> None:
        """Counterspells should be IN against combo."""
        result = await sideboard_guide(
            decklist=["4x Goblin Guide", "4x Lightning Bolt"],
            sideboard=["2x Counterspell", "2x Wrath of God"],
            format="modern",
            matchup="Storm Combo",
            bulk=mock_bulk,
        )

        in_names = [i["name"] for i in result.data["ins"]]
        assert "Counterspell" in in_names


class TestSideboardGuideResponseFormat:
    """Response format tests."""

    async def test_concise_shorter(self, mock_bulk: AsyncMock) -> None:
        args = {
            "decklist": ["4x Lightning Bolt", "4x Primeval Titan"],
            "sideboard": ["2x Counterspell", "2x Wrath of God"],
            "format": "modern",
            "matchup": "Aggro",
            "bulk": mock_bulk,
        }

        detailed = await sideboard_guide(**args, response_format="detailed")
        concise = await sideboard_guide(**args, response_format="concise")

        assert len(concise.markdown) <= len(detailed.markdown)
        # Detailed includes reasoning section
        assert "**Reasoning:**" in detailed.markdown
        assert "**Reasoning:**" not in concise.markdown


# ===========================================================================
# sideboard_matrix tests
# ===========================================================================


class TestSideboardMatrixSuccess:
    """sideboard_matrix with explicit matchups."""

    async def test_produces_matrix(self, mock_bulk: AsyncMock) -> None:
        result = await sideboard_matrix(
            decklist=["4x Lightning Bolt"],
            sideboard=["2x Counterspell", "2x Rest in Peace", "2x Wrath of God"],
            format="modern",
            bulk=mock_bulk,
            matchups=["Aggro", "Control", "Combo"],
        )

        assert "Sideboard Matrix" in result.markdown
        assert isinstance(result.data, dict)
        assert result.data["format"] == "modern"
        assert result.data["matchups"] == ["Aggro", "Control", "Combo"]
        assert "matrix" in result.data

        matrix = result.data["matrix"]
        assert isinstance(matrix, dict)
        # Should have entries for each sideboard card
        assert "Counterspell" in matrix
        assert "Rest in Peace" in matrix
        assert "Wrath of God" in matrix

        # Each entry should have verdicts for each matchup
        for _card_name, row in matrix.items():
            assert isinstance(row, dict)
            for mu in ["Aggro", "Control", "Combo"]:
                assert row[mu] in ("IN", "OUT", "FLEX")

    async def test_counterspell_in_against_combo(self, mock_bulk: AsyncMock) -> None:
        """Counterspell should be IN against combo (counter target spell matches)."""
        result = await sideboard_matrix(
            decklist=["4x Lightning Bolt"],
            sideboard=["2x Counterspell"],
            format="modern",
            bulk=mock_bulk,
            matchups=["Storm Combo"],
        )

        matrix = result.data["matrix"]
        assert matrix["Counterspell"]["Storm Combo"] == "IN"

    async def test_markdown_table_format(self, mock_bulk: AsyncMock) -> None:
        result = await sideboard_matrix(
            decklist=["4x Lightning Bolt"],
            sideboard=["2x Counterspell"],
            format="modern",
            bulk=mock_bulk,
            matchups=["Aggro", "Control"],
        )

        # Should have table markers
        assert "| Card |" in result.markdown
        assert "|------|" in result.markdown
        assert "| Counterspell |" in result.markdown


class TestSideboardMatrixWithGoldfish:
    """sideboard_matrix with MTGGoldfish metagame data."""

    async def test_uses_goldfish_archetypes(
        self, mock_bulk: AsyncMock, mock_goldfish: AsyncMock
    ) -> None:
        result = await sideboard_matrix(
            decklist=["4x Lightning Bolt"],
            sideboard=["2x Counterspell", "2x Rest in Peace"],
            format="modern",
            bulk=mock_bulk,
            mtggoldfish=mock_goldfish,
        )

        # Should use top 6 archetypes from goldfish
        assert len(result.data["matchups"]) == 6
        assert "Boros Energy" in result.data["matchups"]

    async def test_goldfish_failure_no_matchups(self, mock_bulk: AsyncMock) -> None:
        """When goldfish fails and no matchups provided, returns error message."""
        mock_goldfish_failing = AsyncMock()
        mock_goldfish_failing.get_metagame = AsyncMock(
            side_effect=MTGGoldfishError("MTGGoldfish down")
        )

        result = await sideboard_matrix(
            decklist=["4x Lightning Bolt"],
            sideboard=["2x Counterspell"],
            format="modern",
            bulk=mock_bulk,
            mtggoldfish=mock_goldfish_failing,
        )

        assert "No matchups available" in result.markdown
        assert result.data.get("error") == "no_matchups"


class TestSideboardMatrixNoMatchups:
    """sideboard_matrix without matchups or goldfish."""

    async def test_returns_error_without_matchups_or_goldfish(self, mock_bulk: AsyncMock) -> None:
        result = await sideboard_matrix(
            decklist=["4x Lightning Bolt"],
            sideboard=["2x Counterspell"],
            format="modern",
            bulk=mock_bulk,
        )

        assert "No matchups available" in result.markdown
        assert result.data.get("error") == "no_matchups"

    async def test_empty_sideboard(self, mock_bulk: AsyncMock) -> None:
        result = await sideboard_matrix(
            decklist=["4x Lightning Bolt"],
            sideboard=[],
            format="modern",
            bulk=mock_bulk,
            matchups=["Aggro"],
        )

        assert "No sideboard cards provided" in result.markdown


class TestSideboardMatrixResponseFormat:
    """Response format tests for sideboard_matrix."""

    async def test_concise_omits_legend(self, mock_bulk: AsyncMock) -> None:
        args = {
            "decklist": ["4x Lightning Bolt"],
            "sideboard": ["2x Counterspell"],
            "format": "modern",
            "bulk": mock_bulk,
            "matchups": ["Aggro"],
        }

        detailed = await sideboard_matrix(**args, response_format="detailed")
        concise = await sideboard_matrix(**args, response_format="concise")

        assert "**Legend:**" in detailed.markdown
        assert "**Legend:**" not in concise.markdown


# ===========================================================================
# Part A — #64: color-identity filter in suggest_sideboard
# ===========================================================================


class TestSuggestSideboardColorFilter:
    """suggest_sideboard applies deck color_identity to candidate filtering."""

    async def test_color_filter_passes_deck_identity(self, mock_bulk: AsyncMock) -> None:
        """UR (Izzet) deck should pass its color identity to filter_cards."""
        decklist = ["4x Lightning Bolt", "4x Counterspell"]
        mock_bulk.get_cards = AsyncMock(
            return_value={"Lightning Bolt": BOLT, "Counterspell": COUNTERSPELL}
        )

        await suggest_sideboard(decklist, "modern", bulk=mock_bulk)

        call_kwargs = mock_bulk.filter_cards.call_args.kwargs
        assert call_kwargs.get("color_identity") == frozenset({"R", "U"})

    async def test_colorless_card_survives_filter(self, mock_bulk: AsyncMock) -> None:
        """Colorless hate cards are still suggested for a colored deck."""
        decklist = ["4x Lightning Bolt"]
        mock_bulk.get_cards = AsyncMock(return_value={"Lightning Bolt": BOLT})
        mock_bulk.filter_cards = AsyncMock(return_value=[RIP, SURGICAL])

        result = await suggest_sideboard(decklist, "modern", bulk=mock_bulk)

        suggested_names = [c["name"] for c in result.data["suggested_cards"]]
        assert "Surgical Extraction" in suggested_names

    async def test_gap_note_for_empty_category(self, mock_bulk: AsyncMock) -> None:
        """Categories with zero on-color candidates emit gap notes."""
        decklist = ["4x Lightning Bolt"]
        mock_bulk.get_cards = AsyncMock(return_value={"Lightning Bolt": BOLT})
        mock_bulk.filter_cards = AsyncMock(return_value=[])

        result = await suggest_sideboard(decklist, "modern", bulk=mock_bulk)

        assert "empty_categories" in result.data
        assert len(result.data["empty_categories"]) > 0
        assert "No strong on-color answers" in result.markdown

    async def test_skip_filter_when_no_cards_resolved(self, mock_bulk: AsyncMock) -> None:
        """If get_cards returns nothing, color filter is skipped but categories still searched."""
        mock_bulk.get_cards = AsyncMock(return_value={})
        mock_bulk.filter_cards = AsyncMock(return_value=[])

        result = await suggest_sideboard(["4x Lightning Bolt"], "modern", bulk=mock_bulk)

        assert "Sideboard Suggestions" in result.markdown
        assert "empty_categories" not in result.data
        assert mock_bulk.filter_cards.call_count > 0
        for call in mock_bulk.filter_cards.call_args_list:
            assert "color_identity" not in call.kwargs


# ===========================================================================
# Part B — #63: color-aware matrix cell classifier
# ===========================================================================


class TestInferMatchupColors:
    """_infer_matchup_colors heuristic."""

    def test_mono_color(self) -> None:
        assert _infer_matchup_colors("Mono-Blue Delver") == frozenset({"U"})

    def test_guild_name(self) -> None:
        assert _infer_matchup_colors("Izzet Phoenix") == frozenset({"U", "R"})

    def test_unknown_returns_empty(self) -> None:
        assert _infer_matchup_colors("Eldrazi Aggro") == frozenset()

    def test_unions_all_color_tokens(self) -> None:
        """Multiple color words union instead of returning the first parseable token."""
        assert _infer_matchup_colors("White Blue Fish") == frozenset({"W", "U"})
        assert _infer_matchup_colors("Black Green Rock") == frozenset({"B", "G"})

    def test_stray_word_tokens_add_no_colors(self) -> None:
        """Non-color words must not pollute inference (review note on token union).

        "burn"/"shadow" are not parseable color tokens, so they contribute
        nothing -- only explicit color words do.
        """
        assert _infer_matchup_colors("Burn") == frozenset()
        assert _infer_matchup_colors("Death Shadow") == frozenset()
        assert _infer_matchup_colors("Mono-Red Burn") == frozenset({"R"})

    def test_colorless_token_does_not_short_circuit(self) -> None:
        """A leading colorless token must not hide real colors later in the name."""
        assert _infer_matchup_colors("Colorless G Stompy") == frozenset({"G"})
        assert _infer_matchup_colors("c r eureka") == frozenset({"R"})

    def test_colorless_only_stays_empty(self) -> None:
        assert _infer_matchup_colors("Colorless Eldrazi") == frozenset()


class TestClassifySideboardCard:
    """Unified classifier with strategy and matchup colors."""

    def test_color_hate_in_when_color_in_matchup(self) -> None:
        verdict = _classify_sideboard_card(
            PYROBLAST, strategy="combo", matchup_colors=frozenset({"U", "R"})
        )
        assert verdict == "IN"

    def test_color_hate_out_when_color_not_in_matchup(self) -> None:
        verdict = _classify_sideboard_card(
            PYROBLAST, strategy="combo", matchup_colors=frozenset({"G"})
        )
        assert verdict == "OUT"

    def test_color_hate_flex_when_unknown_colors(self) -> None:
        """Unknown matchup colors fall through to role/strategy."""
        verdict = _classify_sideboard_card(PYROBLAST, strategy="combo", matchup_colors=frozenset())
        # Falls through to role/strategy: counterspell vs combo = IN
        assert verdict == "IN"

    def test_multi_color_hate_in_when_second_color_in_matchup(self) -> None:
        """Auriok Champion (pro black + pro green) is IN vs a green-only matchup.

        The first-match loop used to hit the black pattern first and mark it
        OUT because black is not in the matchup -- wrong, it also hates green.
        """
        verdict = _classify_sideboard_card(
            AURIOK, strategy="midrange", matchup_colors=frozenset({"G"})
        )
        assert verdict == "IN"

    def test_multi_color_hate_in_when_first_color_in_matchup(self) -> None:
        verdict = _classify_sideboard_card(
            AURIOK, strategy="midrange", matchup_colors=frozenset({"B"})
        )
        assert verdict == "IN"

    def test_multi_color_hate_out_when_no_hated_color_in_matchup(self) -> None:
        verdict = _classify_sideboard_card(
            AURIOK, strategy="midrange", matchup_colors=frozenset({"U", "R"})
        )
        assert verdict == "OUT"

    def test_multi_color_hate_falls_through_when_colors_unknown(self) -> None:
        """Unknown matchup colors skip color hate and fall through to role/strategy."""
        verdict = _classify_sideboard_card(AURIOK, strategy="midrange", matchup_colors=frozenset())
        assert verdict == "FLEX"

    def test_graveyard_hate_in_vs_combo(self) -> None:
        verdict = _classify_sideboard_card(
            SURGICAL, strategy="combo", matchup_colors=frozenset({"U"})
        )
        assert verdict == "IN"

    def test_board_wipe_in_vs_midrange(self) -> None:
        verdict = _classify_sideboard_card(
            PYROCLASM, strategy="midrange", matchup_colors=frozenset({"G"})
        )
        assert verdict == "IN"

    def test_counterspell_in_vs_combo_regression(self) -> None:
        verdict = _classify_sideboard_card(
            COUNTERSPELL, strategy="combo", matchup_colors=frozenset()
        )
        assert verdict == "IN"

    def test_none_card_returns_flex(self) -> None:
        verdict = _classify_sideboard_card(None, strategy="aggro", matchup_colors=frozenset())
        assert verdict == "FLEX"


class TestSideboardMatrixColorAware:
    """sideboard_matrix with color-aware classifier."""

    async def test_not_uniform_flex_with_colors(self, mock_bulk: AsyncMock) -> None:
        from mtg_mcp_server.types import GoldfishArchetype

        mock_goldfish_colored = AsyncMock()
        mock_goldfish_colored.get_metagame = AsyncMock(
            return_value=GoldfishMetaSnapshot(
                format="modern",
                archetypes=[
                    GoldfishArchetype(
                        name="Izzet Phoenix",
                        slug="izzet-phoenix",
                        meta_share=10.0,
                        colors=["U", "R"],
                    ),
                    GoldfishArchetype(
                        name="Mono-Green Tron", slug="mono-green-tron", meta_share=8.0, colors=["G"]
                    ),
                ],
                total_decks=200,
            )
        )

        mock_bulk.get_cards = AsyncMock(
            return_value={
                "Pyroblast": PYROBLAST,
                "Surgical Extraction": SURGICAL,
                "Pyroclasm": PYROCLASM,
            }
        )

        result = await sideboard_matrix(
            decklist=["4x Lightning Bolt"],
            sideboard=["2x Pyroblast", "2x Surgical Extraction", "2x Pyroclasm"],
            format="modern",
            bulk=mock_bulk,
            mtggoldfish=mock_goldfish_colored,
        )

        matrix = result.data["matrix"]
        all_verdicts = [v for row in matrix.values() for v in row.values()]
        assert "IN" in all_verdicts
        assert "OUT" in all_verdicts

    async def test_pyroblast_in_vs_blue_out_vs_colorless(self, mock_bulk: AsyncMock) -> None:
        """Pyroblast IN vs blue matchup, FLEX vs colorless (no color match, no role match)."""
        mock_bulk.get_cards = AsyncMock(return_value={"Pyroblast": PYROBLAST})

        result = await sideboard_matrix(
            decklist=["4x Lightning Bolt"],
            sideboard=["2x Pyroblast"],
            format="modern",
            bulk=mock_bulk,
            matchups=["Izzet Phoenix", "Eldrazi Aggro"],
        )

        matrix = result.data["matrix"]
        # Izzet Phoenix infers U,R; Pyroblast hates blue → IN
        assert matrix["Pyroblast"]["Izzet Phoenix"] == "IN"
        # Eldrazi Aggro infers no colors; no role match → FLEX
        assert matrix["Pyroblast"]["Eldrazi Aggro"] == "FLEX"

    async def test_surgical_extraction_in_vs_combo(self, mock_bulk: AsyncMock) -> None:
        mock_bulk.get_cards = AsyncMock(return_value={"Surgical Extraction": SURGICAL})

        result = await sideboard_matrix(
            decklist=["4x Lightning Bolt"],
            sideboard=["2x Surgical Extraction"],
            format="modern",
            bulk=mock_bulk,
            matchups=["Storm Combo"],
        )

        matrix = result.data["matrix"]
        assert matrix["Surgical Extraction"]["Storm Combo"] == "IN"

    async def test_explicit_matchups_color_inference(self, mock_bulk: AsyncMock) -> None:
        mock_bulk.get_cards = AsyncMock(return_value={"Pyroblast": PYROBLAST})

        result = await sideboard_matrix(
            decklist=["4x Lightning Bolt"],
            sideboard=["2x Pyroblast"],
            format="modern",
            bulk=mock_bulk,
            matchups=["Mono-Blue Delver", "Izzet Tempo"],
        )

        matrix = result.data["matrix"]
        assert matrix["Pyroblast"]["Mono-Blue Delver"] == "IN"
        assert matrix["Pyroblast"]["Izzet Tempo"] == "IN"

    async def test_goldfish_six_archetypes_preserved(
        self, mock_bulk: AsyncMock, mock_goldfish: AsyncMock
    ) -> None:
        """Auto-detect path still returns top 6 archetypes."""
        result = await sideboard_matrix(
            decklist=["4x Lightning Bolt"],
            sideboard=["2x Counterspell"],
            format="modern",
            bulk=mock_bulk,
            mtggoldfish=mock_goldfish,
        )

        assert len(result.data["matchups"]) == 6
        assert "Boros Energy" in result.data["matchups"]


# ===========================================================================
# Part C — unification: sideboard_guide and sideboard_matrix share one
# classifier (PR #67 review follow-ups)
# ===========================================================================


class TestSideboardGuideColorAware:
    """sideboard_guide uses the shared color-aware classifier."""

    async def test_color_hate_in_vs_matching_color(self, mock_bulk: AsyncMock) -> None:
        """Hydroblast is IN vs Mono-Red Aggro, with color-hate reasoning."""
        mock_bulk.get_cards = AsyncMock(return_value={"Hydroblast": HYDROBLAST})

        result = await sideboard_guide(
            decklist=["4x Lightning Bolt"],
            sideboard=["2x Hydroblast"],
            format="modern",
            matchup="Mono-Red Aggro",
            bulk=mock_bulk,
        )

        entry = next(i for i in result.data["ins"] if i["name"] == "Hydroblast")
        assert entry["verdict"] == "IN"
        assert "color" in entry["reasoning"].lower()

    async def test_color_hate_out_vs_non_matching_color(self, mock_bulk: AsyncMock) -> None:
        """Pyroblast vs Mono-Red Aggro is OUT -- absent from ins entirely."""
        mock_bulk.get_cards = AsyncMock(return_value={"Pyroblast": PYROBLAST})

        result = await sideboard_guide(
            decklist=["4x Lightning Bolt"],
            sideboard=["2x Pyroblast"],
            format="modern",
            matchup="Mono-Red Aggro",
            bulk=mock_bulk,
        )

        assert all(i["name"] != "Pyroblast" for i in result.data["ins"])

    async def test_color_hate_reasoning_not_claimed_when_colors_unknown(
        self, mock_bulk: AsyncMock
    ) -> None:
        """A color-hate card that is IN via category must not be called a color hoser.

        Vs a matchup with unknown colors the classifier falls through to the
        role/strategy logic; the reasoning string must reflect the category
        that actually drove the IN, not the card's color-hate text.
        """
        mock_bulk.get_cards = AsyncMock(return_value={"Pro-White Bolt": PRO_WHITE_BURN})

        result = await sideboard_guide(
            decklist=["4x Lightning Bolt"],
            sideboard=["2x Pro-White Bolt"],
            format="modern",
            matchup="Eldrazi Aggro",
            bulk=mock_bulk,
        )

        entry = next(i for i in result.data["ins"] if i["name"] == "Pro-White Bolt")
        assert entry["verdict"] == "IN"
        assert "direct damage" in entry["reasoning"].lower()
        assert "color hoser" not in entry["reasoning"].lower()


class TestGuideMatrixAgreement:
    """sideboard_guide and sideboard_matrix must render identical verdicts.

    Pins the unified classifier: for the same card vs the same matchup, the
    verdict in guide's structured ``ins`` entries (IN/FLEX) or its absence
    (OUT) must equal the corresponding matrix cell.
    """

    PIN_CARDS: ClassVar[list[Card]] = [
        PYROBLAST,
        HYDROBLAST,
        SURGICAL,
        PYROCLASM,
        COUNTERSPELL,
        RIP,
        AURIOK,
    ]
    PIN_MATCHUPS: ClassVar[list[str]] = [
        "Izzet Phoenix",
        "Mono-Red Aggro",
        "Eldrazi Aggro",
        "Storm Combo",
    ]

    async def test_both_tools_agree_on_fixture_set(self, mock_bulk: AsyncMock) -> None:
        resolved = {c.name: c for c in self.PIN_CARDS}
        mock_bulk.get_cards = AsyncMock(return_value=resolved)
        decklist = ["4x Lightning Bolt", "4x Goblin Guide", "4x Primeval Titan"]

        matrix_result = await sideboard_matrix(
            decklist=decklist,
            sideboard=[f"2x {c.name}" for c in self.PIN_CARDS],
            format="modern",
            bulk=mock_bulk,
            matchups=self.PIN_MATCHUPS,
        )
        matrix = matrix_result.data["matrix"]

        for mu in self.PIN_MATCHUPS:
            for card in self.PIN_CARDS:
                guide = await sideboard_guide(
                    decklist=decklist,
                    sideboard=[f"2x {card.name}"],
                    format="modern",
                    matchup=mu,
                    bulk=mock_bulk,
                )
                entry = next((i for i in guide.data["ins"] if i["name"] == card.name), None)
                guide_verdict = entry["verdict"] if entry is not None else "OUT"
                matrix_verdict = matrix[card.name][mu]
                assert guide_verdict == matrix_verdict, (
                    f"{card.name} vs {mu}: guide={guide_verdict} matrix={matrix_verdict}"
                )
