"""Tests for price_comparison workflow."""

from __future__ import annotations

from unittest.mock import AsyncMock

from mtg_mcp_server.types import Card, CardPrices
from mtg_mcp_server.workflows.pricing import price_comparison

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
        legalities=legalities or {"commander": "legal"},
        prices=prices or CardPrices(),
        cmc=cmc,
        set_code="tst",
    )


def _make_bulk(cards: dict[str, Card | None]) -> AsyncMock:
    mock = AsyncMock()
    mock.get_cards.return_value = cards
    return mock


# ---------------------------------------------------------------------------
# Happy path tests
# ---------------------------------------------------------------------------


class TestBasicPriceComparison:
    """Core price comparison functionality."""

    async def test_two_cards_with_prices(self) -> None:
        """Two cards with USD prices produce a sorted table."""
        cards = {
            "Sol Ring": _make_card(
                name="Sol Ring",
                prices=CardPrices(usd="3.50", usd_foil="8.00", eur="3.00"),
            ),
            "Lightning Bolt": _make_card(
                name="Lightning Bolt",
                prices=CardPrices(usd="1.50", usd_foil="5.00", eur="1.20"),
            ),
        }
        mock_bulk = _make_bulk(cards)

        result = await price_comparison(
            ["Sol Ring", "Lightning Bolt"],
            bulk=mock_bulk,
        )

        assert "Price Comparison" in result
        assert "Sol Ring" in result
        assert "Lightning Bolt" in result
        assert "$3.50" in result
        assert "$1.50" in result
        # Total
        assert "$5.00" in result
        # Sol Ring (more expensive) should appear before Lightning Bolt
        sol_pos = result.index("Sol Ring")
        bolt_pos = result.index("Lightning Bolt")
        assert sol_pos < bolt_pos

    async def test_foil_and_eur_prices_shown(self) -> None:
        """Foil and EUR prices are included in the table."""
        cards = {
            "Sol Ring": _make_card(
                name="Sol Ring",
                prices=CardPrices(usd="3.50", usd_foil="8.00", eur="3.00"),
            ),
            "Path": _make_card(
                name="Path",
                prices=CardPrices(usd="2.00"),
            ),
        }
        mock_bulk = _make_bulk(cards)

        result = await price_comparison(
            ["Sol Ring", "Path"],
            bulk=mock_bulk,
        )

        assert "$8.00" in result  # Foil price
        assert "3.00 EUR" in result  # EUR price


class TestSortingOrder:
    """Price sorting behavior."""

    async def test_sorted_by_usd_descending(self) -> None:
        """Cards are sorted by USD price descending."""
        cards = {
            "Cheap": _make_card(name="Cheap", prices=CardPrices(usd="0.50")),
            "Medium": _make_card(name="Medium", prices=CardPrices(usd="5.00")),
            "Expensive": _make_card(name="Expensive", prices=CardPrices(usd="20.00")),
        }
        mock_bulk = _make_bulk(cards)

        result = await price_comparison(
            ["Cheap", "Medium", "Expensive"],
            bulk=mock_bulk,
        )

        exp_pos = result.index("Expensive")
        med_pos = result.index("Medium")
        cheap_pos = result.index("Cheap")
        assert exp_pos < med_pos < cheap_pos

    async def test_na_prices_sorted_last(self) -> None:
        """Cards without USD prices sort after priced cards."""
        cards = {
            "Priced": _make_card(name="Priced", prices=CardPrices(usd="5.00")),
            "No Price": _make_card(name="No Price", prices=CardPrices()),
        }
        mock_bulk = _make_bulk(cards)

        result = await price_comparison(
            ["Priced", "No Price"],
            bulk=mock_bulk,
        )

        priced_pos = result.index("Priced")
        no_price_pos = result.index("No Price")
        assert priced_pos < no_price_pos


class TestTotalRow:
    """Total price calculation."""

    async def test_total_sums_usd(self) -> None:
        """Total row sums all available USD prices."""
        cards = {
            "Card A": _make_card(name="Card A", prices=CardPrices(usd="10.00")),
            "Card B": _make_card(name="Card B", prices=CardPrices(usd="5.00")),
            "Card C": _make_card(name="Card C", prices=CardPrices(usd="2.50")),
        }
        mock_bulk = _make_bulk(cards)

        result = await price_comparison(
            ["Card A", "Card B", "Card C"],
            bulk=mock_bulk,
        )

        assert "$17.50" in result
        assert "Total" in result

    async def test_total_with_some_na(self) -> None:
        """Total only includes cards with USD prices."""
        cards = {
            "Card A": _make_card(name="Card A", prices=CardPrices(usd="10.00")),
            "Card B": _make_card(name="Card B", prices=CardPrices()),
        }
        mock_bulk = _make_bulk(cards)

        result = await price_comparison(
            ["Card A", "Card B"],
            bulk=mock_bulk,
        )

        assert "$10.00" in result
        assert "Total" in result

    async def test_total_na_when_no_prices(self) -> None:
        """Total is N/A when no cards have USD prices."""
        cards = {
            "Card A": _make_card(name="Card A", prices=CardPrices()),
            "Card B": _make_card(name="Card B", prices=CardPrices()),
        }
        mock_bulk = _make_bulk(cards)

        result = await price_comparison(
            ["Card A", "Card B"],
            bulk=mock_bulk,
        )

        assert "N/A" in result


class TestNotFoundCards:
    """Cards not found in bulk data."""

    async def test_not_found_shown_in_table(self) -> None:
        """Cards not in bulk data show 'Not Found' in the table."""
        cards: dict[str, Card | None] = {
            "Real Card": _make_card(name="Real Card", prices=CardPrices(usd="5.00")),
            "Fake Card": None,
        }
        mock_bulk = _make_bulk(cards)

        result = await price_comparison(
            ["Real Card", "Fake Card"],
            bulk=mock_bulk,
        )

        assert "Not Found" in result
        assert "Fake Card" in result
        assert "1 not found" in result.lower() or "not found" in result.lower()

    async def test_all_not_found(self) -> None:
        """All cards not found still produces valid output."""
        cards: dict[str, Card | None] = {
            "Unknown A": None,
            "Unknown B": None,
        }
        mock_bulk = _make_bulk(cards)

        result = await price_comparison(
            ["Unknown A", "Unknown B"],
            bulk=mock_bulk,
        )

        assert "Price Comparison" in result
        assert "Not Found" in result


class TestDeduplication:
    """Duplicate card names are deduplicated."""

    async def test_duplicates_removed(self) -> None:
        """Duplicate names result in one row per card."""
        cards = {
            "Sol Ring": _make_card(name="Sol Ring", prices=CardPrices(usd="3.50")),
        }
        mock_bulk = _make_bulk(cards)

        result = await price_comparison(
            ["Sol Ring", "Sol Ring", "Sol Ring"],
            bulk=mock_bulk,
        )

        # Should only appear once in the table (not counting header/total)
        # Count occurrences in table rows (lines starting with |)
        table_lines = [ln for ln in result.split("\n") if ln.startswith("| Sol Ring")]
        assert len(table_lines) == 1


class TestNaPriceHandling:
    """All prices None shows N/A."""

    async def test_all_prices_na(self) -> None:
        """Card with no prices shows N/A for all columns."""
        cards = {
            "Old Card": _make_card(name="Old Card", prices=CardPrices()),
        }
        mock_bulk = _make_bulk(cards)

        result = await price_comparison(
            ["Old Card", "Old Card"],
            bulk=mock_bulk,
        )

        assert "N/A" in result


class TestAttribution:
    """Attribution line is present."""

    async def test_scryfall_attribution(self) -> None:
        """Output includes Scryfall data attribution."""
        cards = {
            "Card": _make_card(name="Card", prices=CardPrices(usd="1.00")),
            "Card 2": _make_card(name="Card 2", prices=CardPrices(usd="2.00")),
        }
        mock_bulk = _make_bulk(cards)

        result = await price_comparison(
            ["Card", "Card 2"],
            bulk=mock_bulk,
        )

        assert "Scryfall" in result


class TestSummaryLine:
    """Summary line shows counts."""

    async def test_summary_counts(self) -> None:
        """Summary shows priced vs total count."""
        cards: dict[str, Card | None] = {
            "Found": _make_card(name="Found", prices=CardPrices(usd="1.00")),
            "Not Found": None,
        }
        mock_bulk = _make_bulk(cards)

        result = await price_comparison(
            ["Found", "Not Found"],
            bulk=mock_bulk,
        )

        assert "1 of 2" in result
