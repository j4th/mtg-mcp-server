"""Tests for color identity parser utility."""

from __future__ import annotations

import pytest

from mtg_mcp_server.utils.color_identity import is_within_identity, parse_color_identity

# ---------------------------------------------------------------------------
# Guild names (two-color, all 10)
# ---------------------------------------------------------------------------


class TestGuildNames:
    def test_azorius(self):
        assert parse_color_identity("azorius") == frozenset({"W", "U"})

    def test_dimir(self):
        assert parse_color_identity("dimir") == frozenset({"U", "B"})

    def test_rakdos(self):
        assert parse_color_identity("rakdos") == frozenset({"B", "R"})

    def test_gruul(self):
        assert parse_color_identity("gruul") == frozenset({"R", "G"})

    def test_selesnya(self):
        assert parse_color_identity("selesnya") == frozenset({"G", "W"})

    def test_orzhov(self):
        assert parse_color_identity("orzhov") == frozenset({"W", "B"})

    def test_izzet(self):
        assert parse_color_identity("izzet") == frozenset({"U", "R"})

    def test_golgari(self):
        assert parse_color_identity("golgari") == frozenset({"B", "G"})

    def test_boros(self):
        assert parse_color_identity("boros") == frozenset({"R", "W"})

    def test_simic(self):
        assert parse_color_identity("simic") == frozenset({"G", "U"})


# ---------------------------------------------------------------------------
# Shard names (three-color, allied)
# ---------------------------------------------------------------------------


class TestShardNames:
    def test_bant(self):
        assert parse_color_identity("bant") == frozenset({"W", "U", "G"})

    def test_esper(self):
        assert parse_color_identity("esper") == frozenset({"W", "U", "B"})

    def test_grixis(self):
        assert parse_color_identity("grixis") == frozenset({"U", "B", "R"})

    def test_jund(self):
        assert parse_color_identity("jund") == frozenset({"B", "R", "G"})

    def test_naya(self):
        assert parse_color_identity("naya") == frozenset({"R", "G", "W"})


# ---------------------------------------------------------------------------
# Wedge names (three-color, enemy)
# ---------------------------------------------------------------------------


class TestWedgeNames:
    def test_abzan(self):
        assert parse_color_identity("abzan") == frozenset({"W", "B", "G"})

    def test_jeskai(self):
        assert parse_color_identity("jeskai") == frozenset({"W", "U", "R"})

    def test_sultai(self):
        assert parse_color_identity("sultai") == frozenset({"B", "G", "U"})

    def test_mardu(self):
        assert parse_color_identity("mardu") == frozenset({"W", "B", "R"})

    def test_temur(self):
        assert parse_color_identity("temur") == frozenset({"U", "R", "G"})


# ---------------------------------------------------------------------------
# Four-color names
# ---------------------------------------------------------------------------


class TestFourColorNames:
    def test_glint(self):
        assert parse_color_identity("glint") == frozenset({"U", "B", "R", "G"})

    def test_dune(self):
        assert parse_color_identity("dune") == frozenset({"W", "B", "R", "G"})

    def test_ink(self):
        assert parse_color_identity("ink") == frozenset({"W", "U", "R", "G"})

    def test_witch(self):
        assert parse_color_identity("witch") == frozenset({"W", "U", "B", "G"})

    def test_yore(self):
        assert parse_color_identity("yore") == frozenset({"W", "U", "B", "R"})


# ---------------------------------------------------------------------------
# Five-color and colorless
# ---------------------------------------------------------------------------


class TestFiveColorAndColorless:
    def test_wubrg(self):
        assert parse_color_identity("wubrg") == frozenset({"W", "U", "B", "R", "G"})

    def test_5c(self):
        assert parse_color_identity("5c") == frozenset({"W", "U", "B", "R", "G"})

    def test_colorless(self):
        assert parse_color_identity("colorless") == frozenset()

    def test_empty_string(self):
        assert parse_color_identity("") == frozenset()

    def test_c_for_colorless(self):
        assert parse_color_identity("C") == frozenset()


# ---------------------------------------------------------------------------
# Letter sequences
# ---------------------------------------------------------------------------


class TestLetterSequences:
    def test_single_letter(self):
        assert parse_color_identity("R") == frozenset({"R"})

    def test_two_letters(self):
        assert parse_color_identity("WU") == frozenset({"W", "U"})

    def test_three_letters(self):
        assert parse_color_identity("BUG") == frozenset({"B", "U", "G"})

    def test_four_letters(self):
        assert parse_color_identity("WUBR") == frozenset({"W", "U", "B", "R"})

    def test_all_five_letters(self):
        assert parse_color_identity("WUBRG") == frozenset({"W", "U", "B", "R", "G"})

    def test_lowercase_letters(self):
        assert parse_color_identity("bug") == frozenset({"B", "U", "G"})


# ---------------------------------------------------------------------------
# Color words
# ---------------------------------------------------------------------------


class TestColorWords:
    def test_white(self):
        assert parse_color_identity("white") == frozenset({"W"})

    def test_blue(self):
        assert parse_color_identity("blue") == frozenset({"U"})

    def test_black(self):
        assert parse_color_identity("black") == frozenset({"B"})

    def test_red(self):
        assert parse_color_identity("red") == frozenset({"R"})

    def test_green(self):
        assert parse_color_identity("green") == frozenset({"G"})


# ---------------------------------------------------------------------------
# Case insensitivity
# ---------------------------------------------------------------------------


class TestCaseInsensitivity:
    def test_upper_guild(self):
        assert parse_color_identity("SULTAI") == frozenset({"B", "G", "U"})

    def test_mixed_guild(self):
        assert parse_color_identity("Sultai") == frozenset({"B", "G", "U"})

    def test_upper_color_word(self):
        assert parse_color_identity("Blue") == frozenset({"U"})

    def test_upper_5c(self):
        assert parse_color_identity("5C") == frozenset({"W", "U", "B", "R", "G"})


# ---------------------------------------------------------------------------
# Invalid input
# ---------------------------------------------------------------------------


class TestInvalidInput:
    def test_nonsense_raises(self):
        with pytest.raises(ValueError, match="Unrecognized color identity"):
            parse_color_identity("purple")

    def test_partial_word_raises(self):
        with pytest.raises(ValueError, match="Unrecognized color identity"):
            parse_color_identity("blu")

    def test_invalid_letter_raises(self):
        with pytest.raises(ValueError, match="Unrecognized color identity"):
            parse_color_identity("X")

    def test_mixed_valid_invalid_raises(self):
        with pytest.raises(ValueError, match="Unrecognized color identity"):
            parse_color_identity("WX")


# ---------------------------------------------------------------------------
# is_within_identity
# ---------------------------------------------------------------------------


class TestIsWithinIdentity:
    def test_subset(self):
        assert is_within_identity(["U", "B"], frozenset({"B", "G", "U"})) is True

    def test_exact_match(self):
        assert is_within_identity(["B", "G", "U"], frozenset({"B", "G", "U"})) is True

    def test_not_subset(self):
        assert is_within_identity(["W", "U"], frozenset({"B", "G", "U"})) is False

    def test_colorless_always_within(self):
        assert is_within_identity([], frozenset({"B", "G", "U"})) is True

    def test_colorless_within_colorless(self):
        assert is_within_identity([], frozenset()) is True

    def test_colored_not_within_colorless(self):
        assert is_within_identity(["R"], frozenset()) is False

    def test_single_color_within_five_color(self):
        assert is_within_identity(["G"], frozenset({"W", "U", "B", "R", "G"})) is True
