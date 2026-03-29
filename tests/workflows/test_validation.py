"""Tests for deck_validate workflow."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mtg_mcp_server.types import Card, CardPrices
from mtg_mcp_server.workflows.validation import deck_validate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_card(
    *,
    name: str = "Sol Ring",
    mana_cost: str = "{1}",
    type_line: str = "Artifact",
    rarity: str = "uncommon",
    colors: list[str] | None = None,
    color_identity: list[str] | None = None,
    legalities: dict[str, str] | None = None,
    prices: CardPrices | None = None,
    cmc: float = 1.0,
) -> Card:
    return Card(
        id="test",
        name=name,
        mana_cost=mana_cost,
        type_line=type_line,
        rarity=rarity,
        colors=colors or [],
        color_identity=color_identity or [],
        legalities=legalities or {"commander": "legal", "modern": "legal", "standard": "legal"},
        prices=prices or CardPrices(),
        cmc=cmc,
        set_code="tst",
    )


def _make_bulk(cards: dict[str, Card | None]) -> AsyncMock:
    """Create a mock ScryfallBulkClient with given card lookup results."""
    mock = AsyncMock()
    mock.get_cards.return_value = cards
    mock.get_card.side_effect = lambda name: cards.get(name)
    return mock


# ---------------------------------------------------------------------------
# Happy path tests
# ---------------------------------------------------------------------------


class TestValidModernDeck:
    """A valid 60-card modern deck passes validation."""

    async def test_valid_60_card_modern(self) -> None:
        cards = {f"Card {i}": _make_card(name=f"Card {i}") for i in range(60)}
        mock_bulk = _make_bulk(cards)

        result = await deck_validate(
            [f"Card {i}" for i in range(60)],
            "modern",
            bulk=mock_bulk,
        )

        assert "VALID" in result.markdown
        assert "modern" in result.markdown.lower()
        assert isinstance(result.data, dict)

    async def test_valid_with_4x_prefix(self) -> None:
        cards = {
            "Lightning Bolt": _make_card(name="Lightning Bolt"),
            "Mountain": _make_card(name="Mountain", type_line="Basic Land - Mountain"),
        }
        mock_bulk = _make_bulk(cards)

        result = await deck_validate(
            ["4x Lightning Bolt"] + ["Mountain"] * 56,
            "modern",
            bulk=mock_bulk,
        )

        assert "VALID" in result.markdown


class TestValidCommanderDeck:
    """A valid 100-card commander deck with commander passes validation."""

    async def test_valid_commander_99_plus_commander(self) -> None:
        commander = _make_card(
            name="Muldrotha, the Gravetide",
            color_identity=["B", "G", "U"],
            type_line="Legendary Creature",
            legalities={"commander": "legal"},
        )
        cards: dict[str, Card | None] = {"Muldrotha, the Gravetide": commander}
        for i in range(99):
            cards[f"Card {i}"] = _make_card(
                name=f"Card {i}",
                color_identity=["B"],
                legalities={"commander": "legal"},
            )

        mock_bulk = _make_bulk(cards)

        result = await deck_validate(
            [f"Card {i}" for i in range(99)],
            "commander",
            commander="Muldrotha, the Gravetide",
            bulk=mock_bulk,
        )

        assert "VALID" in result.markdown
        assert isinstance(result.data, dict)


# ---------------------------------------------------------------------------
# Error detection tests
# ---------------------------------------------------------------------------


class TestBannedCard:
    """A banned card makes the deck invalid."""

    async def test_banned_card_detected(self) -> None:
        cards = {
            "Birthing Pod": _make_card(name="Birthing Pod", legalities={"modern": "banned"}),
        }
        # Add enough cards to meet minimum
        for i in range(59):
            cards[f"Card {i}"] = _make_card(name=f"Card {i}")

        mock_bulk = _make_bulk(cards)

        result = await deck_validate(
            ["Birthing Pod"] + [f"Card {i}" for i in range(59)],
            "modern",
            bulk=mock_bulk,
        )

        assert "INVALID" in result.markdown
        assert "Birthing Pod" in result.markdown
        assert "banned" in result.markdown.lower()
        assert isinstance(result.data, dict)


class TestDeckSizeTooSmall:
    """Deck with fewer cards than the minimum."""

    async def test_too_few_cards(self) -> None:
        cards = {
            "Sol Ring": _make_card(name="Sol Ring"),
        }
        mock_bulk = _make_bulk(cards)

        result = await deck_validate(
            ["Sol Ring"],
            "modern",
            bulk=mock_bulk,
        )

        assert "INVALID" in result.markdown
        assert "1 cards" in result.markdown
        assert "minimum 60" in result.markdown.lower() or "minimum" in result.markdown.lower()
        assert isinstance(result.data, dict)


class TestCommanderWrongSize:
    """Commander deck not exactly 100 cards."""

    async def test_commander_deck_too_small(self) -> None:
        commander = _make_card(
            name="Muldrotha, the Gravetide",
            color_identity=["B", "G", "U"],
            legalities={"commander": "legal"},
        )
        cards: dict[str, Card | None] = {"Muldrotha, the Gravetide": commander}
        for i in range(50):
            cards[f"Card {i}"] = _make_card(
                name=f"Card {i}",
                color_identity=["B"],
                legalities={"commander": "legal"},
            )

        mock_bulk = _make_bulk(cards)

        result = await deck_validate(
            [f"Card {i}" for i in range(50)],
            "commander",
            commander="Muldrotha, the Gravetide",
            bulk=mock_bulk,
        )

        assert "INVALID" in result.markdown
        assert "51 cards" in result.markdown
        assert "100" in result.markdown
        assert isinstance(result.data, dict)


class TestCopyLimits:
    """Too many copies of a non-basic card."""

    async def test_5_copies_in_modern(self) -> None:
        cards = {
            "Lightning Bolt": _make_card(name="Lightning Bolt"),
        }
        mock_bulk = _make_bulk(cards)

        result = await deck_validate(
            ["5x Lightning Bolt"] + ["Card"] * 55,
            "modern",
            bulk=mock_bulk,
        )

        assert "INVALID" in result.markdown
        assert "Lightning Bolt" in result.markdown
        assert "5" in result.markdown
        assert "max 4" in result.markdown.lower() or "max" in result.markdown
        assert isinstance(result.data, dict)

    async def test_basic_lands_exempt(self) -> None:
        """Basic lands are exempt from copy limits."""
        cards: dict[str, Card | None] = {
            "Plains": _make_card(name="Plains", type_line="Basic Land - Plains"),
        }
        for i in range(40):
            cards[f"Card {i}"] = _make_card(name=f"Card {i}")

        mock_bulk = _make_bulk(cards)

        result = await deck_validate(
            ["20x Plains"] + [f"Card {i}" for i in range(40)],
            "modern",
            bulk=mock_bulk,
        )

        assert "VALID" in result.markdown

    async def test_singleton_duplicate_in_commander(self) -> None:
        """Commander format forbids more than 1 copy of non-basic cards."""
        commander = _make_card(
            name="Muldrotha, the Gravetide",
            color_identity=["B", "G", "U"],
            legalities={"commander": "legal"},
        )
        cards: dict[str, Card | None] = {
            "Muldrotha, the Gravetide": commander,
            "Sol Ring": _make_card(
                name="Sol Ring",
                color_identity=[],
                legalities={"commander": "legal"},
            ),
        }
        for i in range(97):
            cards[f"Card {i}"] = _make_card(
                name=f"Card {i}",
                color_identity=["B"],
                legalities={"commander": "legal"},
            )

        mock_bulk = _make_bulk(cards)

        result = await deck_validate(
            ["2x Sol Ring"] + [f"Card {i}" for i in range(97)],
            "commander",
            commander="Muldrotha, the Gravetide",
            bulk=mock_bulk,
        )

        assert "INVALID" in result.markdown
        assert "Sol Ring" in result.markdown


class TestColorIdentity:
    """Cards outside the commander's color identity."""

    async def test_off_color_card(self) -> None:
        commander = _make_card(
            name="Muldrotha, the Gravetide",
            color_identity=["B", "G", "U"],
            legalities={"commander": "legal"},
        )
        red_card = _make_card(
            name="Lightning Bolt",
            color_identity=["R"],
            legalities={"commander": "legal"},
        )
        cards: dict[str, Card | None] = {
            "Muldrotha, the Gravetide": commander,
            "Lightning Bolt": red_card,
        }
        for i in range(98):
            cards[f"Card {i}"] = _make_card(
                name=f"Card {i}",
                color_identity=["B"],
                legalities={"commander": "legal"},
            )

        mock_bulk = _make_bulk(cards)

        result = await deck_validate(
            ["Lightning Bolt"] + [f"Card {i}" for i in range(98)],
            "commander",
            commander="Muldrotha, the Gravetide",
            bulk=mock_bulk,
        )

        assert "INVALID" in result.markdown
        assert "Lightning Bolt" in result.markdown
        assert "color identity" in result.markdown.lower()
        assert isinstance(result.data, dict)


class TestPauperLegality:
    """Pauper validation relies on Scryfall legality data, not rarity field."""

    async def test_uncommon_rarity_but_pauper_legal(self) -> None:
        """A card with uncommon rarity but pauper: legal passes validation.

        Scryfall's legality data already accounts for all printings — a card
        printed at common in any set is pauper-legal regardless of the rarity
        field in bulk data (which reflects one specific printing).
        """
        cards: dict[str, Card | None] = {
            "Uncommon Card": _make_card(
                name="Uncommon Card",
                rarity="uncommon",
                legalities={"pauper": "legal"},
            ),
        }
        for i in range(59):
            cards[f"Card {i}"] = _make_card(
                name=f"Card {i}",
                rarity="common",
                legalities={"pauper": "legal"},
            )

        mock_bulk = _make_bulk(cards)

        result = await deck_validate(
            ["Uncommon Card"] + [f"Card {i}" for i in range(59)],
            "pauper",
            bulk=mock_bulk,
        )

        assert "VALID" in result.markdown
        assert isinstance(result.data, dict)


class TestVintageRestricted:
    """Vintage restricted cards limited to 1 copy."""

    async def test_restricted_2_copies(self) -> None:
        cards: dict[str, Card | None] = {
            "Ancestral Recall": _make_card(
                name="Ancestral Recall",
                legalities={"vintage": "restricted"},
            ),
        }
        for i in range(58):
            cards[f"Card {i}"] = _make_card(name=f"Card {i}", legalities={"vintage": "legal"})

        mock_bulk = _make_bulk(cards)

        result = await deck_validate(
            ["2x Ancestral Recall"] + [f"Card {i}" for i in range(58)],
            "vintage",
            bulk=mock_bulk,
        )

        assert "INVALID" in result.markdown
        assert "Ancestral Recall" in result.markdown
        assert "restricted" in result.markdown.lower()
        assert isinstance(result.data, dict)


class TestSideboardSize:
    """Sideboard exceeds format maximum."""

    async def test_sideboard_too_large(self) -> None:
        cards: dict[str, Card | None] = {}
        for i in range(60):
            cards[f"Card {i}"] = _make_card(name=f"Card {i}")
        for i in range(20):
            cards[f"SB {i}"] = _make_card(name=f"SB {i}")

        mock_bulk = _make_bulk(cards)

        result = await deck_validate(
            [f"Card {i}" for i in range(60)],
            "modern",
            sideboard=[f"SB {i}" for i in range(20)],
            bulk=mock_bulk,
        )

        assert "INVALID" in result.markdown
        assert "Sideboard" in result.markdown or "sideboard" in result.markdown
        assert isinstance(result.data, dict)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestUnknownFormat:
    """Unknown format raises ValueError (caught by server.py → ToolError)."""

    async def test_invalid_format(self) -> None:
        mock_bulk = _make_bulk({})

        with pytest.raises(ValueError, match="Unknown format"):
            await deck_validate(
                ["Sol Ring"],
                "notaformat",
                bulk=mock_bulk,
            )


class TestUnresolvedCards:
    """Cards not found in bulk data produce warnings, not errors."""

    async def test_unresolved_cards_are_warnings(self) -> None:
        cards: dict[str, Card | None] = {"Sol Ring": _make_card(name="Sol Ring")}
        # Add enough resolved cards for deck size
        for i in range(59):
            cards[f"Card {i}"] = _make_card(name=f"Card {i}")
        # One card won't be found
        cards["Unknown Card"] = None

        mock_bulk = _make_bulk(cards)

        result = await deck_validate(
            ["Sol Ring", "Unknown Card"] + [f"Card {i}" for i in range(58)],
            "modern",
            bulk=mock_bulk,
        )

        assert "VALID" in result.markdown
        assert "warning" in result.markdown.lower()
        assert "Unknown Card" in result.markdown
        assert "unresolved" in result.markdown.lower()
        assert isinstance(result.data, dict)


class TestEmptyDecklist:
    """Empty decklist returns appropriate message."""

    async def test_empty_entries(self) -> None:
        mock_bulk = _make_bulk({})

        result = await deck_validate(
            [],
            "modern",
            bulk=mock_bulk,
        )

        assert "No cards" in result.markdown or "no cards" in result.markdown
        assert isinstance(result.data, dict)


class TestFormatAliases:
    """Format aliases (edh -> commander) work."""

    async def test_edh_alias(self) -> None:
        commander = _make_card(
            name="Muldrotha",
            color_identity=["B", "G", "U"],
            legalities={"commander": "legal"},
        )
        cards: dict[str, Card | None] = {"Muldrotha": commander}
        for i in range(99):
            cards[f"Card {i}"] = _make_card(
                name=f"Card {i}",
                color_identity=["B"],
                legalities={"commander": "legal"},
            )

        mock_bulk = _make_bulk(cards)

        result = await deck_validate(
            [f"Card {i}" for i in range(99)],
            "edh",
            commander="Muldrotha",
            bulk=mock_bulk,
        )

        # Should normalize to commander
        assert "Commander" in result.markdown
        assert isinstance(result.data, dict)


class TestQuantityParsing:
    """Various quantity prefix formats are handled."""

    async def test_various_qty_formats(self) -> None:
        cards = {
            "Bolt": _make_card(name="Bolt"),
            "Snap": _make_card(name="Snap"),
            "Path": _make_card(name="Path"),
        }
        mock_bulk = _make_bulk(cards)

        result = await deck_validate(
            ["4x Bolt", "3 Snap", "Path"],
            "modern",
            bulk=mock_bulk,
        )

        # Should parse all 8 cards (4+3+1)
        assert "8 cards checked" in result.markdown
        assert isinstance(result.data, dict)


class TestNotLegalCard:
    """Card that is not_legal (never printed at common, wrong format, etc)."""

    async def test_not_legal_status(self) -> None:
        cards: dict[str, Card | None] = {
            "Oko": _make_card(name="Oko", legalities={"standard": "not_legal"}),
        }
        for i in range(59):
            cards[f"Card {i}"] = _make_card(name=f"Card {i}")

        mock_bulk = _make_bulk(cards)

        result = await deck_validate(
            ["Oko"] + [f"Card {i}" for i in range(59)],
            "standard",
            bulk=mock_bulk,
        )

        assert "INVALID" in result.markdown
        assert "Oko" in result.markdown
        assert isinstance(result.data, dict)


# ---------------------------------------------------------------------------
# response_format tests
# ---------------------------------------------------------------------------


class TestDeckValidateResponseFormat:
    """Concise output is shorter than detailed."""

    async def test_concise_valid_shorter_than_detailed(self) -> None:
        """Valid deck: concise shows just 'VALID', detailed has full report."""
        cards = {f"Card {i}": _make_card(name=f"Card {i}") for i in range(60)}
        mock_bulk = _make_bulk(cards)

        detailed = await deck_validate(
            [f"Card {i}" for i in range(60)],
            "modern",
            bulk=mock_bulk,
            response_format="detailed",
        )
        concise = await deck_validate(
            [f"Card {i}" for i in range(60)],
            "modern",
            bulk=mock_bulk,
            response_format="concise",
        )

        assert len(concise.markdown) < len(detailed.markdown)
        assert "VALID" in concise.markdown
        # Concise omits the summary footer
        assert "cards checked" not in concise.markdown
        assert "cards checked" in detailed.markdown
        assert isinstance(detailed.data, dict)

    async def test_concise_invalid_shows_errors(self) -> None:
        """Invalid deck in concise: shows error count and error list."""
        cards = {
            "Banned Card": _make_card(name="Banned Card", legalities={"modern": "banned"}),
        }
        for i in range(59):
            cards[f"Card {i}"] = _make_card(name=f"Card {i}")

        mock_bulk = _make_bulk(cards)

        concise = await deck_validate(
            ["Banned Card"] + [f"Card {i}" for i in range(59)],
            "modern",
            bulk=mock_bulk,
            response_format="concise",
        )

        assert "INVALID" in concise.markdown
        assert "banned" in concise.markdown.lower()
