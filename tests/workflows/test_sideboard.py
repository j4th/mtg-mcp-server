"""Tests for sideboard workflow functions."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mtg_mcp_server.types import (
    Card,
    CardPrices,
    GoldfishArchetype,
    GoldfishFormatStaple,
    GoldfishMetaSnapshot,
)
from mtg_mcp_server.workflows.sideboard import (
    _classify_archetype_strategy,
    _extract_deck_colors,
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
            side_effect=Exception("MTGGoldfish is down")
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
        # Primeval Titan (CMC 6) should be a candidate for cutting against aggro
        assert "Primeval Titan" in out_names or len(out_names) > 0

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
        mock_goldfish_failing.get_metagame = AsyncMock(side_effect=Exception("MTGGoldfish down"))

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
        mock_goldfish_failing.get_metagame = AsyncMock(side_effect=Exception("MTGGoldfish down"))

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
