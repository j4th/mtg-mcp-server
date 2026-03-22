"""Tests for set_overview draft workflow."""

from __future__ import annotations

from unittest.mock import AsyncMock

from mtg_mcp.types import DraftCardRating
from mtg_mcp.workflows.draft import set_overview


def _make_rating(
    name: str,
    color: str = "W",
    rarity: str = "common",
    ever_drawn_win_rate: float | None = 0.550,
    avg_seen: float | None = 5.0,
    drawn_improvement_win_rate: float | None = 0.020,
    game_count: int = 10000,
) -> DraftCardRating:
    """Helper to build a DraftCardRating with sensible defaults."""
    return DraftCardRating(
        name=name,
        color=color,
        rarity=rarity,
        seen_count=8000,
        avg_seen=avg_seen,
        pick_count=6000,
        avg_pick=3.0,
        game_count=game_count,
        ever_drawn_win_rate=ever_drawn_win_rate,
        drawn_improvement_win_rate=drawn_improvement_win_rate,
    )


# Build a realistic set of ratings with diverse rarities and win rates
COMMONS = [
    _make_rating("Top Common A", color="U", rarity="common", ever_drawn_win_rate=0.620),
    _make_rating("Top Common B", color="B", rarity="common", ever_drawn_win_rate=0.595),
    _make_rating("Mid Common C", color="G", rarity="common", ever_drawn_win_rate=0.555),
    _make_rating("Mid Common D", color="R", rarity="common", ever_drawn_win_rate=0.540),
    _make_rating("Low Common E", color="W", rarity="common", ever_drawn_win_rate=0.510),
]

UNCOMMONS = [
    _make_rating("Top Uncommon X", color="U", rarity="uncommon", ever_drawn_win_rate=0.610),
    _make_rating("Top Uncommon Y", color="B", rarity="uncommon", ever_drawn_win_rate=0.580),
    _make_rating("Mid Uncommon Z", color="G", rarity="uncommon", ever_drawn_win_rate=0.545),
]

RARES = [
    _make_rating("Good Rare", color="U", rarity="rare", ever_drawn_win_rate=0.630),
    _make_rating("Trap Rare", color="R", rarity="rare", ever_drawn_win_rate=0.480),
    _make_rating("Bad Rare", color="W", rarity="rare", ever_drawn_win_rate=0.460),
]

MYTHICS = [
    _make_rating("Bomb Mythic", color="B", rarity="mythic", ever_drawn_win_rate=0.650),
    _make_rating("Trap Mythic", color="G", rarity="mythic", ever_drawn_win_rate=0.490),
]

SAMPLE_RATINGS = COMMONS + UNCOMMONS + RARES + MYTHICS


def _make_mock_client(ratings: list[DraftCardRating] | None = None) -> AsyncMock:
    """Create a mock SeventeenLandsClient."""
    mock = AsyncMock()
    mock.card_ratings = AsyncMock(return_value=ratings if ratings is not None else SAMPLE_RATINGS)
    return mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSetOverviewHappyPath:
    """Normal case with diverse ratings across rarities."""

    async def test_header_contains_set_code(self) -> None:
        client = _make_mock_client()
        result = await set_overview("LRW", seventeen_lands=client)
        assert "Set Overview" in result
        assert "LRW" in result

    async def test_top_commons_section_present(self) -> None:
        client = _make_mock_client()
        result = await set_overview("LRW", seventeen_lands=client)
        assert "## Top Commons" in result

    async def test_top_uncommons_section_present(self) -> None:
        client = _make_mock_client()
        result = await set_overview("LRW", seventeen_lands=client)
        assert "## Top Uncommons" in result

    async def test_trap_rares_section_present(self) -> None:
        client = _make_mock_client()
        result = await set_overview("LRW", seventeen_lands=client)
        assert "## Trap Rares/Mythics" in result

    async def test_commons_sorted_by_gih_wr(self) -> None:
        client = _make_mock_client()
        result = await set_overview("LRW", seventeen_lands=client)
        # Top Common A (62.0%) should appear before Top Common B (59.5%)
        pos_a = result.index("Top Common A")
        pos_b = result.index("Top Common B")
        assert pos_a < pos_b

    async def test_uncommons_sorted_by_gih_wr(self) -> None:
        client = _make_mock_client()
        result = await set_overview("LRW", seventeen_lands=client)
        # Top Uncommon X (61.0%) should appear before Top Uncommon Y (58.0%)
        pos_x = result.index("Top Uncommon X")
        pos_y = result.index("Top Uncommon Y")
        assert pos_x < pos_y

    async def test_trap_rares_below_median(self) -> None:
        client = _make_mock_client()
        result = await set_overview("LRW", seventeen_lands=client)
        # Trap Rare (48.0%) and Bad Rare (46.0%) and Trap Mythic (49.0%)
        # should all be in the trap section
        assert "Trap Rare" in result
        assert "Bad Rare" in result
        assert "Trap Mythic" in result

    async def test_good_rares_not_in_trap_section(self) -> None:
        client = _make_mock_client()
        result = await set_overview("LRW", seventeen_lands=client)
        # Good Rare (63.0%) and Bomb Mythic (65.0%) should NOT be traps
        trap_section = result.split("## Trap Rares/Mythics")[1]
        assert "Good Rare" not in trap_section
        assert "Bomb Mythic" not in trap_section

    async def test_gih_wr_displayed_as_percentage(self) -> None:
        client = _make_mock_client()
        result = await set_overview("LRW", seventeen_lands=client)
        assert "62.0%" in result  # Top Common A

    async def test_median_gih_displayed(self) -> None:
        client = _make_mock_client()
        result = await set_overview("LRW", seventeen_lands=client)
        assert "Median GIH WR" in result

    async def test_event_type_shown(self) -> None:
        client = _make_mock_client()
        result = await set_overview("LRW", event_type="TradDraft", seventeen_lands=client)
        assert "TradDraft" in result

    async def test_calls_card_ratings_with_params(self) -> None:
        client = _make_mock_client()
        await set_overview("MKM", event_type="TradDraft", seventeen_lands=client)
        client.card_ratings.assert_awaited_once_with("MKM", event_type="TradDraft")


class TestSetOverviewEmptyRatings:
    """17Lands returns no ratings for the set."""

    async def test_returns_no_data_message(self) -> None:
        client = _make_mock_client(ratings=[])
        result = await set_overview("XYZ", seventeen_lands=client)
        assert "No card data available" in result
        assert "XYZ" in result


class TestSetOverviewAllNoneGihWr:
    """All cards have None GIH WR (insufficient data)."""

    async def test_returns_no_data_message(self) -> None:
        ratings = [
            _make_rating("Card A", rarity="common", ever_drawn_win_rate=None),
            _make_rating("Card B", rarity="uncommon", ever_drawn_win_rate=None),
            _make_rating("Card C", rarity="rare", ever_drawn_win_rate=None),
        ]
        client = _make_mock_client(ratings)
        result = await set_overview("XYZ", seventeen_lands=client)
        assert "No card data available" in result


class TestSetOverviewNoTrapRares:
    """All rares/mythics are above the median GIH WR."""

    async def test_no_trap_rares_message(self) -> None:
        # All cards have the same high win rate
        ratings = [
            _make_rating("Common A", rarity="common", ever_drawn_win_rate=0.550),
            _make_rating("Uncommon A", rarity="uncommon", ever_drawn_win_rate=0.560),
            _make_rating("Great Rare", rarity="rare", ever_drawn_win_rate=0.620),
            _make_rating("Great Mythic", rarity="mythic", ever_drawn_win_rate=0.650),
        ]
        client = _make_mock_client(ratings)
        result = await set_overview("LRW", seventeen_lands=client)
        assert "No trap rares found" in result


class TestSetOverviewProgressCallback:
    """Progress callback is called at the right times."""

    async def test_progress_called_twice(self) -> None:
        client = _make_mock_client()
        progress = AsyncMock()
        await set_overview("LRW", seventeen_lands=client, on_progress=progress)
        assert progress.await_count == 2
        progress.assert_any_await(1, 2)
        progress.assert_any_await(2, 2)

    async def test_works_without_progress(self) -> None:
        """No crash when on_progress is None."""
        client = _make_mock_client()
        result = await set_overview("LRW", seventeen_lands=client, on_progress=None)
        assert "Set Overview" in result


class TestSetOverviewTopNLimit:
    """Top 10 limit is respected for commons and uncommons."""

    async def test_at_most_ten_commons_shown(self) -> None:
        # Create 15 commons
        ratings = [
            _make_rating(f"Common {i}", rarity="common", ever_drawn_win_rate=0.5 + i * 0.01)
            for i in range(15)
        ]
        client = _make_mock_client(ratings)
        result = await set_overview("LRW", seventeen_lands=client)
        # Count ranked rows in the commons section
        commons_section = result.split("## Top Commons")[1].split("## Top Uncommons")[0]
        ranked_rows = [
            line
            for line in commons_section.split("\n")
            if line.strip().startswith("|") and "." in line
        ]
        assert len(ranked_rows) <= 10

    async def test_at_most_ten_uncommons_shown(self) -> None:
        # Create 15 uncommons
        ratings = [
            _make_rating(f"Uncommon {i}", rarity="uncommon", ever_drawn_win_rate=0.5 + i * 0.01)
            for i in range(15)
        ]
        client = _make_mock_client(ratings)
        result = await set_overview("LRW", seventeen_lands=client)
        uncommons_section = result.split("## Top Uncommons")[1].split("## Trap Rares")[0]
        ranked_rows = [
            line
            for line in uncommons_section.split("\n")
            if line.strip().startswith("|") and "." in line
        ]
        assert len(ranked_rows) <= 10
