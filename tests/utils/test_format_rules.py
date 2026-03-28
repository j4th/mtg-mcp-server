"""Tests for format rules utility."""

import pytest

from mtg_mcp_server.utils.format_rules import (
    FormatRules,
    get_format_rules,
    is_basic_land,
    normalize_format,
)


class TestNormalizeFormat:
    """Tests for normalize_format()."""

    def test_edh_alias(self) -> None:
        assert normalize_format("edh") == "commander"

    def test_cedh_alias(self) -> None:
        assert normalize_format("cedh") == "commander"

    def test_draft_alias(self) -> None:
        assert normalize_format("draft") == "limited"

    def test_sealed_alias(self) -> None:
        assert normalize_format("sealed") == "limited"

    def test_case_insensitive(self) -> None:
        assert normalize_format("Modern") == "modern"
        assert normalize_format("STANDARD") == "standard"
        assert normalize_format("Commander") == "commander"

    def test_passthrough(self) -> None:
        assert normalize_format("standard") == "standard"
        assert normalize_format("modern") == "modern"
        assert normalize_format("legacy") == "legacy"
        assert normalize_format("vintage") == "vintage"
        assert normalize_format("pauper") == "pauper"
        assert normalize_format("commander") == "commander"
        assert normalize_format("limited") == "limited"
        assert normalize_format("brawl") == "brawl"
        assert normalize_format("oathbreaker") == "oathbreaker"
        assert normalize_format("pioneer") == "pioneer"

    def test_unknown_format_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown format"):
            normalize_format("twoheadedgiant")

    def test_empty_string_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown format"):
            normalize_format("")

    def test_alias_case_insensitive(self) -> None:
        assert normalize_format("EDH") == "commander"
        assert normalize_format("Draft") == "limited"


class TestGetFormatRules:
    """Tests for get_format_rules()."""

    def test_standard(self) -> None:
        rules = get_format_rules("standard")
        assert rules.min_main == 60
        assert rules.max_sideboard == 15
        assert rules.max_copies == 4
        assert rules.singleton is False
        assert rules.check_color_identity is False
        assert rules.check_rarity is None
        assert rules.restricted_as_one is False

    def test_commander_singleton_with_color_identity(self) -> None:
        rules = get_format_rules("commander")
        assert rules.min_main == 100
        assert rules.max_sideboard == 0
        assert rules.max_copies == 1
        assert rules.singleton is True
        assert rules.check_color_identity is True

    def test_pauper_checks_rarity(self) -> None:
        rules = get_format_rules("pauper")
        assert rules.check_rarity == "common"
        assert rules.min_main == 60
        assert rules.max_copies == 4

    def test_vintage_restricted(self) -> None:
        rules = get_format_rules("vintage")
        assert rules.restricted_as_one is True
        assert rules.min_main == 60
        assert rules.max_copies == 4

    def test_limited_no_copy_limit(self) -> None:
        rules = get_format_rules("limited")
        assert rules.max_copies is None
        assert rules.max_sideboard is None
        assert rules.min_main == 40

    def test_brawl(self) -> None:
        rules = get_format_rules("brawl")
        assert rules.min_main == 60
        assert rules.max_sideboard == 0
        assert rules.max_copies == 1
        assert rules.singleton is True
        assert rules.check_color_identity is True

    def test_oathbreaker(self) -> None:
        rules = get_format_rules("oathbreaker")
        assert rules.min_main == 60
        assert rules.max_sideboard == 0
        assert rules.max_copies == 1
        assert rules.singleton is True
        assert rules.check_color_identity is True

    def test_pioneer(self) -> None:
        rules = get_format_rules("pioneer")
        assert rules.min_main == 60
        assert rules.max_sideboard == 15
        assert rules.max_copies == 4

    def test_modern(self) -> None:
        rules = get_format_rules("modern")
        assert rules.min_main == 60
        assert rules.max_sideboard == 15
        assert rules.max_copies == 4

    def test_legacy(self) -> None:
        rules = get_format_rules("legacy")
        assert rules.min_main == 60
        assert rules.max_sideboard == 15
        assert rules.max_copies == 4

    def test_unknown_format_raises_key_error(self) -> None:
        with pytest.raises(KeyError):
            get_format_rules("notaformat")

    def test_format_rules_is_frozen(self) -> None:
        rules = get_format_rules("standard")
        with pytest.raises(AttributeError):
            rules.min_main = 40  # type: ignore[misc]


class TestIsBasicLand:
    """Tests for is_basic_land()."""

    def test_plains(self) -> None:
        assert is_basic_land("Plains") is True

    def test_island(self) -> None:
        assert is_basic_land("Island") is True

    def test_swamp(self) -> None:
        assert is_basic_land("Swamp") is True

    def test_mountain(self) -> None:
        assert is_basic_land("Mountain") is True

    def test_forest(self) -> None:
        assert is_basic_land("Forest") is True

    def test_wastes(self) -> None:
        assert is_basic_land("Wastes") is True

    def test_snow_covered_plains(self) -> None:
        assert is_basic_land("Snow-Covered Plains") is True

    def test_snow_covered_island(self) -> None:
        assert is_basic_land("Snow-Covered Island") is True

    def test_snow_covered_swamp(self) -> None:
        assert is_basic_land("Snow-Covered Swamp") is True

    def test_snow_covered_mountain(self) -> None:
        assert is_basic_land("Snow-Covered Mountain") is True

    def test_snow_covered_forest(self) -> None:
        assert is_basic_land("Snow-Covered Forest") is True

    def test_non_basic_land(self) -> None:
        assert is_basic_land("Lightning Bolt") is False

    def test_case_sensitive(self) -> None:
        assert is_basic_land("plains") is False
        assert is_basic_land("ISLAND") is False
        assert is_basic_land("snow-covered plains") is False

    def test_similar_names_not_basic(self) -> None:
        assert is_basic_land("Snow-Covered") is False
        assert is_basic_land("Plains ") is False
        assert is_basic_land("") is False
