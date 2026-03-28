"""Tests for decklist parsing utility."""

from mtg_mcp_server.utils.decklist import parse_decklist


class TestParseDecklist:
    """parse_decklist handles various entry formats."""

    def test_quantity_x_format(self) -> None:
        result = parse_decklist(["4x Lightning Bolt"])
        assert result == [(4, "Lightning Bolt")]

    def test_quantity_space_format(self) -> None:
        result = parse_decklist(["4 Lightning Bolt"])
        assert result == [(4, "Lightning Bolt")]

    def test_no_quantity_defaults_to_1(self) -> None:
        result = parse_decklist(["Sol Ring"])
        assert result == [(1, "Sol Ring")]

    def test_multiple_entries(self) -> None:
        result = parse_decklist(["4x Lightning Bolt", "2x Counterspell", "Sol Ring"])
        assert result == [(4, "Lightning Bolt"), (2, "Counterspell"), (1, "Sol Ring")]

    def test_empty_entries_skipped(self) -> None:
        result = parse_decklist(["", "  ", "Sol Ring", ""])
        assert result == [(1, "Sol Ring")]

    def test_empty_list(self) -> None:
        result = parse_decklist([])
        assert result == []

    def test_whitespace_trimmed(self) -> None:
        result = parse_decklist(["  4x Lightning Bolt  "])
        assert result == [(4, "Lightning Bolt")]

    def test_single_digit_quantity(self) -> None:
        result = parse_decklist(["1x Sol Ring"])
        assert result == [(1, "Sol Ring")]

    def test_large_quantity(self) -> None:
        result = parse_decklist(["20x Plains"])
        assert result == [(20, "Plains")]

    def test_card_with_comma(self) -> None:
        result = parse_decklist(["1x Muldrotha, the Gravetide"])
        assert result == [(1, "Muldrotha, the Gravetide")]

    def test_card_with_apostrophe(self) -> None:
        result = parse_decklist(["1x Urza's Saga"])
        assert result == [(1, "Urza's Saga")]
