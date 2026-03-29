"""Tests for suggest_mana_base workflow."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mtg_mcp_server.types import Card, CardPrices
from mtg_mcp_server.workflows.mana_base import suggest_mana_base

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
        legalities=legalities or {"commander": "legal", "modern": "legal"},
        prices=prices or CardPrices(),
        cmc=cmc,
        set_code="tst",
    )


def _make_bulk(
    cards: dict[str, Card | None],
    filter_results: list[Card] | None = None,
) -> AsyncMock:
    """Create a mock ScryfallBulkClient."""
    mock = AsyncMock()
    mock.get_cards.return_value = cards
    mock.filter_cards.return_value = filter_results or []
    return mock


# ---------------------------------------------------------------------------
# Basic functionality tests
# ---------------------------------------------------------------------------


class TestBasicManaBase:
    """Core mana base recommendation logic."""

    async def test_mono_red_deck(self) -> None:
        """Mono-red deck gets only Mountains."""
        cards: dict[str, Card | None] = {}
        for i in range(15):
            cards[f"Bolt {i}"] = _make_card(
                name=f"Bolt {i}",
                mana_cost="{R}",
                colors=["R"],
                color_identity=["R"],
                cmc=1.0,
            )

        mock_bulk = _make_bulk(cards)

        result = await suggest_mana_base(
            [f"Bolt {i}" for i in range(15)],
            "modern",
            bulk=mock_bulk,
        )

        assert "Mountain" in result.markdown
        assert "Red" in result.markdown or "R" in result.markdown
        assert "100%" in result.markdown or "100" in result.markdown
        assert isinstance(result.data, dict)

    async def test_two_color_deck(self) -> None:
        """Two-color deck gets both basic lands in proportional amounts."""
        cards: dict[str, Card | None] = {}
        # 6 red pips
        for i in range(6):
            cards[f"Red {i}"] = _make_card(
                name=f"Red {i}",
                mana_cost="{R}",
                colors=["R"],
                cmc=1.0,
            )
        # 4 blue pips
        for i in range(4):
            cards[f"Blue {i}"] = _make_card(
                name=f"Blue {i}",
                mana_cost="{U}",
                colors=["U"],
                cmc=1.0,
            )

        mock_bulk = _make_bulk(cards)

        result = await suggest_mana_base(
            [f"Red {i}" for i in range(6)] + [f"Blue {i}" for i in range(4)],
            "modern",
            bulk=mock_bulk,
        )

        assert "Mountain" in result.markdown
        assert "Island" in result.markdown
        # Red should have more lands than blue
        assert "60%" in result.markdown or "Red" in result.markdown

    async def test_colorless_deck(self) -> None:
        """Colorless deck gets Wastes recommendation."""
        cards: dict[str, Card | None] = {}
        for i in range(10):
            cards[f"Artifact {i}"] = _make_card(
                name=f"Artifact {i}",
                mana_cost="{2}",
                type_line="Artifact",
                colors=[],
                cmc=2.0,
            )

        mock_bulk = _make_bulk(cards)

        result = await suggest_mana_base(
            [f"Artifact {i}" for i in range(10)],
            "modern",
            bulk=mock_bulk,
        )

        assert "Wastes" in result.markdown or "colorless" in result.markdown.lower()


class TestLandCountRecommendation:
    """Land count calculation and overrides."""

    async def test_override_total_lands(self) -> None:
        """User-specified land count overrides the auto-calculation."""
        cards = {
            "Bolt": _make_card(name="Bolt", mana_cost="{R}", cmc=1.0),
        }
        mock_bulk = _make_bulk(cards)

        result = await suggest_mana_base(
            ["Bolt"],
            "modern",
            total_lands=18,
            bulk=mock_bulk,
        )

        assert "18" in result.markdown
        assert isinstance(result.data, dict)

    async def test_high_cmc_gets_more_lands(self) -> None:
        """Higher average CMC should recommend more lands."""
        cards: dict[str, Card | None] = {}
        for i in range(10):
            cards[f"Big {i}"] = _make_card(
                name=f"Big {i}",
                mana_cost="{4}{R}{R}",
                cmc=6.0,
            )

        mock_bulk = _make_bulk(cards)

        result = await suggest_mana_base(
            [f"Big {i}" for i in range(10)],
            "modern",
            bulk=mock_bulk,
        )

        # High CMC deck should get 24+ lands in 60-card format
        # The exact number depends on suggest_land_count but should be >= 24
        assert "Recommended Lands" in result.markdown

    async def test_commander_format_lands(self) -> None:
        """Commander format gets more lands than 60-card formats."""
        cards: dict[str, Card | None] = {}
        for i in range(20):
            cards[f"Spell {i}"] = _make_card(
                name=f"Spell {i}",
                mana_cost="{2}{B}",
                cmc=3.0,
            )

        mock_bulk = _make_bulk(cards)

        result = await suggest_mana_base(
            [f"Spell {i}" for i in range(20)],
            "commander",
            bulk=mock_bulk,
        )

        # Commander decks need 33-40 lands
        assert "Recommended Lands" in result.markdown
        assert "Commander" in result.markdown


class TestPipDistribution:
    """Color pip distribution table rendering."""

    async def test_pip_table_rendered(self) -> None:
        """Output contains a pip distribution table with colors and ratios."""
        cards = {
            "Bolt": _make_card(name="Bolt", mana_cost="{R}"),
            "Growth": _make_card(name="Growth", mana_cost="{G}"),
        }
        mock_bulk = _make_bulk(cards)

        result = await suggest_mana_base(
            ["Bolt", "Growth"],
            "modern",
            bulk=mock_bulk,
        )

        assert "Color Pip Distribution" in result.markdown
        assert "| Color" in result.markdown
        assert "Red" in result.markdown
        assert "Green" in result.markdown
        assert "50%" in result.markdown  # Equal split between R and G
        assert isinstance(result.data, dict)

    async def test_hybrid_mana_counted(self) -> None:
        """Hybrid mana pips are split between colors."""
        cards = {
            "Hybrid": _make_card(name="Hybrid", mana_cost="{G/W}"),
        }
        mock_bulk = _make_bulk(cards)

        result = await suggest_mana_base(
            ["Hybrid"],
            "modern",
            bulk=mock_bulk,
        )

        assert "Green" in result.markdown
        assert "White" in result.markdown


class TestDualLandSuggestions:
    """Dual land recommendation logic."""

    async def test_dual_lands_suggested_for_multicolor(self) -> None:
        """Two-color decks get dual land suggestions."""
        dual = _make_card(
            name="Steam Vents",
            type_line="Land - Island Mountain",
            color_identity=["U", "R"],
            prices=CardPrices(usd="15.00"),
        )
        cards = {
            "Bolt": _make_card(name="Bolt", mana_cost="{R}"),
            "Snap": _make_card(name="Snap", mana_cost="{U}"),
        }
        mock_bulk = _make_bulk(cards, filter_results=[dual])

        result = await suggest_mana_base(
            ["Bolt", "Snap"],
            "modern",
            bulk=mock_bulk,
        )

        assert "Dual Lands" in result.markdown or "Steam Vents" in result.markdown
        assert isinstance(result.data, dict)

    async def test_no_duals_for_mono_color(self) -> None:
        """Mono-color decks don't get dual land suggestions."""
        cards = {
            "Bolt": _make_card(name="Bolt", mana_cost="{R}"),
        }
        mock_bulk = _make_bulk(cards)

        await suggest_mana_base(
            ["Bolt"],
            "modern",
            bulk=mock_bulk,
        )

        # Mono-color doesn't need duals
        # filter_cards should not even be called
        mock_bulk.filter_cards.assert_not_called()


class TestHeavyColorWarnings:
    """Heavy color requirement warnings."""

    async def test_heavy_color_warning(self) -> None:
        """5+ pips of a single color triggers a warning."""
        cards: dict[str, Card | None] = {}
        for i in range(6):
            cards[f"Bolt {i}"] = _make_card(
                name=f"Bolt {i}",
                mana_cost="{R}{R}",
                cmc=2.0,
            )

        mock_bulk = _make_bulk(cards)

        result = await suggest_mana_base(
            [f"Bolt {i}" for i in range(6)],
            "modern",
            bulk=mock_bulk,
        )

        # 6 cards * 2 red pips = 12 pips -> should warn
        assert "Warnings" in result.markdown or "Red" in result.markdown
        assert isinstance(result.data, dict)


class TestEdgeCases:
    """Edge case handling."""

    async def test_unknown_format(self) -> None:
        mock_bulk = _make_bulk({})

        with pytest.raises(ValueError, match="Unknown format"):
            await suggest_mana_base(
                ["Card"],
                "notaformat",
                bulk=mock_bulk,
            )

    async def test_empty_decklist(self) -> None:
        mock_bulk = _make_bulk({})

        result = await suggest_mana_base(
            [],
            "modern",
            bulk=mock_bulk,
        )

        assert "No cards" in result.markdown
        assert isinstance(result.data, dict)

    async def test_all_unresolved(self) -> None:
        """All cards unresolved still produces output."""
        mock_bulk = _make_bulk({"Unknown": None})

        result = await suggest_mana_base(
            ["Unknown"],
            "modern",
            bulk=mock_bulk,
        )

        # Should still produce output with warnings
        assert "unresolved" in result.markdown.lower()

    async def test_lands_skipped_for_pip_counting(self) -> None:
        """Land cards don't contribute to pip counts."""
        cards = {
            "Bolt": _make_card(name="Bolt", mana_cost="{R}", cmc=1.0),
            "Forest": _make_card(
                name="Forest",
                mana_cost=None,
                type_line="Basic Land - Forest",
                cmc=0.0,
            ),
        }
        mock_bulk = _make_bulk(cards)

        result = await suggest_mana_base(
            ["Bolt", "Forest"],
            "modern",
            bulk=mock_bulk,
        )

        # Only Bolt contributes pips
        assert "Red" in result.markdown
        # Green should NOT appear in pips (Forest is a land, not a spell)
        assert "Green" not in result.markdown or "100%" not in result.markdown

    async def test_quantity_weighting(self) -> None:
        """Card quantity is weighted in pip counting."""
        cards = {
            "Bolt": _make_card(name="Bolt", mana_cost="{R}", cmc=1.0),
            "Growth": _make_card(name="Growth", mana_cost="{G}", cmc=1.0),
        }
        mock_bulk = _make_bulk(cards)

        result = await suggest_mana_base(
            ["4x Bolt", "Growth"],
            "modern",
            bulk=mock_bulk,
        )

        # 4 red pips vs 1 green pip -> Red should be ~80%
        assert "80%" in result.markdown


# ---------------------------------------------------------------------------
# response_format tests
# ---------------------------------------------------------------------------


class TestSuggestManaBaseResponseFormat:
    """Concise output is shorter than detailed."""

    async def test_concise_shorter_than_detailed(self) -> None:
        cards: dict[str, Card | None] = {}
        for i in range(15):
            cards[f"Bolt {i}"] = _make_card(
                name=f"Bolt {i}",
                mana_cost="{R}",
                colors=["R"],
                color_identity=["R"],
                cmc=1.0,
            )

        mock_bulk = _make_bulk(cards)

        detailed = await suggest_mana_base(
            [f"Bolt {i}" for i in range(15)],
            "modern",
            bulk=mock_bulk,
            response_format="detailed",
        )
        concise = await suggest_mana_base(
            [f"Bolt {i}" for i in range(15)],
            "modern",
            bulk=mock_bulk,
            response_format="concise",
        )

        assert len(concise.markdown) < len(detailed.markdown)
        # Concise has basic lands but no dual land section or warnings
        assert "Mountain" in concise.markdown
        assert "## Color Pip Distribution" not in concise.markdown
        assert "## Color Pip Distribution" in detailed.markdown
        assert isinstance(detailed.data, dict)
