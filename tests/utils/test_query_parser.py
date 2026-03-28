"""Tests for the natural-language MTG query parser."""

import pytest

from mtg_mcp_server.utils.query_parser import QueryFilters, parse_query


class TestQueryFiltersDefaults:
    """QueryFilters has sensible defaults."""

    def test_empty_filters(self) -> None:
        f = QueryFilters()
        assert f.type_contains == []
        assert f.text_contains == []
        assert f.text_any == []
        assert f.cmc_eq is None
        assert f.cmc_lte is None
        assert f.keywords == []
        assert f.name_contains is None
        assert f.description == ""


class TestNDropPatterns:
    """N-drop patterns: '2-drop creatures', '3 drop instants', '3-drops'."""

    def test_2_drop_creatures(self) -> None:
        result = parse_query("2-drop creatures")
        assert result.cmc_eq == 2.0
        assert "Creature" in result.type_contains
        assert "CMC 2" in result.description
        assert "Creature" in result.description

    def test_3_drop_instants(self) -> None:
        result = parse_query("3 drop instants")
        assert result.cmc_eq == 3.0
        assert "Instant" in result.type_contains

    def test_3_drops_no_type(self) -> None:
        result = parse_query("3-drops")
        assert result.cmc_eq == 3.0
        assert result.type_contains == []
        assert "CMC 3" in result.description

    def test_1_drop(self) -> None:
        result = parse_query("1-drop")
        assert result.cmc_eq == 1.0

    def test_5_drop_sorceries(self) -> None:
        result = parse_query("5-drop sorceries")
        assert result.cmc_eq == 5.0
        assert "Sorcery" in result.type_contains


class TestRemoval:
    """Removal pattern matches."""

    def test_removal(self) -> None:
        result = parse_query("removal")
        assert "destroy target" in result.text_any
        assert "exile target" in result.text_any
        assert "deals damage to" in result.text_any
        assert "Removal" in result.description or "removal" in result.description.lower()

    def test_removal_case_insensitive(self) -> None:
        result = parse_query("Removal")
        assert "destroy target" in result.text_any
        assert "exile target" in result.text_any


class TestCardDraw:
    """Card draw pattern matches."""

    def test_card_draw(self) -> None:
        result = parse_query("card draw")
        assert "draw a card" in result.text_any
        assert "draw cards" in result.text_any
        assert "draw" in result.description.lower()

    def test_draw_alone(self) -> None:
        result = parse_query("draw")
        assert "draw a card" in result.text_any
        assert "draw cards" in result.text_any


class TestRamp:
    """Ramp pattern matches."""

    def test_ramp(self) -> None:
        result = parse_query("ramp")
        assert any("add {" in t.lower() for t in result.text_any)
        assert any("search your library for a" in t.lower() for t in result.text_any)
        assert "ramp" in result.description.lower()


class TestBoardWipe:
    """Board wipe / wrath / mass removal pattern matches."""

    def test_board_wipe(self) -> None:
        result = parse_query("board wipe")
        assert "destroy all" in result.text_any
        assert "exile all" in result.text_any
        assert (
            "board wipe" in result.description.lower()
            or "mass removal" in result.description.lower()
        )

    def test_wrath(self) -> None:
        result = parse_query("wrath")
        assert "destroy all" in result.text_any

    def test_mass_removal(self) -> None:
        result = parse_query("mass removal")
        assert "destroy all" in result.text_any
        assert "exile all" in result.text_any


class TestCounter:
    """Counterspell pattern matches."""

    def test_counter(self) -> None:
        result = parse_query("counter")
        assert "counter target spell" in result.text_any
        assert "counter target" in result.text_any
        assert "Instant" in result.type_contains
        assert (
            "counterspell" in result.description.lower() or "counter" in result.description.lower()
        )

    def test_counterspell(self) -> None:
        result = parse_query("counterspell")
        assert "counter target spell" in result.text_any
        assert "Instant" in result.type_contains


class TestTutor:
    """Tutor pattern matches."""

    def test_tutor(self) -> None:
        result = parse_query("tutor")
        assert "search your library" in result.text_any
        assert "tutor" in result.description.lower()


class TestFallback:
    """Unrecognized queries fall back to oracle text search."""

    def test_unrecognized_query(self) -> None:
        result = parse_query("flying lifelink")
        assert "flying lifelink" in result.text_contains
        assert "oracle text" in result.description.lower()

    def test_random_text(self) -> None:
        result = parse_query("enters the battlefield")
        assert "enters the battlefield" in result.text_contains


class TestCaseInsensitivity:
    """All patterns should work regardless of input case."""

    def test_uppercase_removal(self) -> None:
        result = parse_query("REMOVAL")
        assert "destroy target" in result.text_any

    def test_mixed_case_board_wipe(self) -> None:
        result = parse_query("Board Wipe")
        assert "destroy all" in result.text_any

    def test_uppercase_ramp(self) -> None:
        result = parse_query("RAMP")
        assert any("add {" in t.lower() for t in result.text_any)

    def test_uppercase_tutor(self) -> None:
        result = parse_query("TUTOR")
        assert "search your library" in result.text_any


class TestDescriptionPopulated:
    """Every parse result should have a non-empty description."""

    @pytest.mark.parametrize(
        "query",
        [
            "2-drop creatures",
            "3-drops",
            "removal",
            "card draw",
            "ramp",
            "board wipe",
            "counter",
            "tutor",
            "flying lifelink",
        ],
    )
    def test_description_non_empty(self, query: str) -> None:
        result = parse_query(query)
        assert result.description != ""


class TestTypeSingularization:
    """Plural type words should be singularized to match type_line."""

    def test_creatures_becomes_creature(self) -> None:
        result = parse_query("2-drop creatures")
        assert "Creature" in result.type_contains
        assert "Creatures" not in result.type_contains

    def test_instants_becomes_instant(self) -> None:
        result = parse_query("3 drop instants")
        assert "Instant" in result.type_contains

    def test_sorceries_becomes_sorcery(self) -> None:
        result = parse_query("5-drop sorceries")
        assert "Sorcery" in result.type_contains

    def test_enchantments_becomes_enchantment(self) -> None:
        result = parse_query("4-drop enchantments")
        assert "Enchantment" in result.type_contains

    def test_artifacts_becomes_artifact(self) -> None:
        result = parse_query("3-drop artifacts")
        assert "Artifact" in result.type_contains
