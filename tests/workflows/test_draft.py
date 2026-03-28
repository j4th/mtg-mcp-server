"""Unit tests for draft_pack_pick workflow — TDD, tests written first."""

from __future__ import annotations

from unittest.mock import AsyncMock

from mtg_mcp_server.types import DraftCardRating
from mtg_mcp_server.workflows.draft import draft_pack_pick


def _make_rating(
    name: str,
    color: str = "W",
    rarity: str = "common",
    ever_drawn_win_rate: float | None = 0.550,
    avg_seen: float | None = 5.0,
    drawn_improvement_win_rate: float | None = 0.020,
    opening_hand_win_rate: float | None = 0.540,
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
        opening_hand_win_rate=opening_hand_win_rate,
        drawn_improvement_win_rate=drawn_improvement_win_rate,
    )


MOCK_RATINGS = [
    _make_rating(
        "Mulldrifter",
        color="U",
        rarity="common",
        ever_drawn_win_rate=0.612,
        avg_seen=2.8,
        drawn_improvement_win_rate=0.045,
        opening_hand_win_rate=0.605,
        game_count=18000,
    ),
    _make_rating(
        "Nameless Inversion",
        color="B",
        rarity="common",
        ever_drawn_win_rate=0.587,
        avg_seen=4.2,
        drawn_improvement_win_rate=0.033,
        opening_hand_win_rate=0.591,
        game_count=15000,
    ),
    _make_rating(
        "Silvergill Adept",
        color="U",
        rarity="uncommon",
        ever_drawn_win_rate=0.572,
        avg_seen=3.5,
        drawn_improvement_win_rate=0.025,
        opening_hand_win_rate=0.568,
        game_count=12000,
    ),
    _make_rating(
        "Leaf Gilder",
        color="G",
        rarity="common",
        ever_drawn_win_rate=0.541,
        avg_seen=6.1,
        drawn_improvement_win_rate=0.010,
        opening_hand_win_rate=0.535,
        game_count=9000,
    ),
    _make_rating(
        "Stinkdrinker Daredevil",
        color="R",
        rarity="common",
        ever_drawn_win_rate=0.520,
        avg_seen=7.3,
        drawn_improvement_win_rate=0.005,
        opening_hand_win_rate=0.515,
        game_count=8000,
    ),
    _make_rating(
        "Kithkin Greatheart",
        color="W",
        rarity="common",
        ever_drawn_win_rate=0.505,
        avg_seen=8.0,
        drawn_improvement_win_rate=-0.002,
        opening_hand_win_rate=0.500,
        game_count=7000,
    ),
]

# Additional ratings with None GIH WR (insufficient data)
RATING_NO_GIH = _make_rating(
    "Mystery Card",
    color="B",
    rarity="rare",
    ever_drawn_win_rate=None,
    avg_seen=2.0,
    drawn_improvement_win_rate=None,
    opening_hand_win_rate=None,
    game_count=200,
)


def _make_mock_client(ratings: list[DraftCardRating] | None = None) -> AsyncMock:
    """Create a mock SeventeenLandsClient."""
    mock = AsyncMock()
    mock.card_ratings.return_value = ratings if ratings is not None else MOCK_RATINGS
    return mock


class TestDraftPackPickBasic:
    """Normal cases: all cards found, sorted by GIH WR."""

    async def test_cards_sorted_by_gih_wr_descending(self):
        """Cards sorted by GIH WR descending in output."""
        pack = ["Nameless Inversion", "Mulldrifter", "Leaf Gilder"]
        client = _make_mock_client()

        result = await draft_pack_pick(pack, "LRW", seventeen_lands=client)

        # Mulldrifter (61.2%) should be ranked first, then Nameless Inversion (58.7%), then Leaf Gilder (54.1%)
        mul_pos = result.markdown.index("Mulldrifter")
        ni_pos = result.markdown.index("Nameless Inversion")
        lg_pos = result.markdown.index("Leaf Gilder")
        assert mul_pos < ni_pos < lg_pos

    async def test_output_contains_header(self):
        """Output includes Draft Pack Analysis header with set code and 17Lands attribution."""
        pack = ["Mulldrifter"]
        client = _make_mock_client()

        result = await draft_pack_pick(pack, "LRW", seventeen_lands=client)

        assert "Draft Pack Analysis" in result.markdown
        assert "LRW" in result.markdown
        assert "Data provided by [17Lands]" in result.markdown

    async def test_output_contains_gih_wr_as_percentage(self):
        """GIH WR displayed as a percentage (e.g., 61.2%)."""
        pack = ["Mulldrifter"]
        client = _make_mock_client()

        result = await draft_pack_pick(pack, "LRW", seventeen_lands=client)

        assert "61.2%" in result.markdown

    async def test_output_contains_alsa(self):
        """ALSA (Average Last Seen At) value displayed in output."""
        pack = ["Mulldrifter"]
        client = _make_mock_client()

        result = await draft_pack_pick(pack, "LRW", seventeen_lands=client)

        assert "2.8" in result.markdown

    async def test_output_contains_iwd_with_sign(self):
        """Positive IWD displayed with + sign (e.g., +4.5%)."""
        pack = ["Mulldrifter"]
        client = _make_mock_client()

        result = await draft_pack_pick(pack, "LRW", seventeen_lands=client)

        # IWD 0.045 => "+4.5%"
        assert "+4.5%" in result.markdown

    async def test_negative_iwd_displayed_correctly(self):
        """Negative IWD displayed with - sign (e.g., -0.2%)."""
        pack = ["Kithkin Greatheart"]
        client = _make_mock_client()

        result = await draft_pack_pick(pack, "LRW", seventeen_lands=client)

        # IWD -0.002 => "-0.2%"
        assert "-0.2%" in result.markdown

    async def test_output_contains_rarity_and_color(self):
        """Card color and rarity included in output."""
        pack = ["Mulldrifter"]
        client = _make_mock_client()

        result = await draft_pack_pick(pack, "LRW", seventeen_lands=client)

        assert "U" in result.markdown
        assert "common" in result.markdown.lower()

    async def test_output_contains_game_count(self):
        """Game count (sample size) displayed in output."""
        pack = ["Mulldrifter"]
        client = _make_mock_client()

        result = await draft_pack_pick(pack, "LRW", seventeen_lands=client)

        assert "18000" in result.markdown

    async def test_calls_card_ratings_with_set_code(self):
        """17Lands card_ratings called with the provided set code."""
        pack = ["Mulldrifter"]
        client = _make_mock_client()

        await draft_pack_pick(pack, "MKM", seventeen_lands=client)

        client.card_ratings.assert_awaited_once_with("MKM")

    async def test_rank_numbers_in_output(self):
        """Sequential rank numbers (1., 2., 3.) present in output."""
        pack = ["Nameless Inversion", "Mulldrifter", "Leaf Gilder"]
        client = _make_mock_client()

        result = await draft_pack_pick(pack, "LRW", seventeen_lands=client)

        assert "1." in result.markdown
        assert "2." in result.markdown
        assert "3." in result.markdown


class TestDraftPackPickMissingData:
    """Cards not found in 17Lands data appear in 'No data' section."""

    async def test_missing_cards_in_no_data_section(self):
        """Unrecognized cards listed in a separate No data section."""
        pack = ["Mulldrifter", "Totally Fake Card"]
        client = _make_mock_client()

        result = await draft_pack_pick(pack, "LRW", seventeen_lands=client)

        assert "Totally Fake Card" in result.markdown
        assert "No data" in result.markdown

    async def test_all_cards_missing(self):
        """All pack cards in No data section when none found in 17Lands."""
        pack = ["Fake Card A", "Fake Card B"]
        client = _make_mock_client()

        result = await draft_pack_pick(pack, "LRW", seventeen_lands=client)

        assert "No data" in result.markdown
        assert "Fake Card A" in result.markdown
        assert "Fake Card B" in result.markdown

    async def test_case_insensitive_matching(self):
        """Card names in the pack should match 17Lands data case-insensitively."""
        pack = ["mulldrifter", "NAMELESS INVERSION"]
        client = _make_mock_client()

        result = await draft_pack_pick(pack, "LRW", seventeen_lands=client)

        # Both should be found and ranked, not in the "No data" section
        assert "61.2%" in result.markdown  # Mulldrifter's GIH WR
        assert "58.7%" in result.markdown  # Nameless Inversion's GIH WR


class TestDraftPackPickNoneGihWr:
    """Cards with None GIH WR go to the end of the found list."""

    async def test_none_gih_wr_sorted_to_end(self):
        """Cards with None GIH WR appear after cards with valid GIH WR."""
        ratings = [*MOCK_RATINGS, RATING_NO_GIH]
        pack = ["Mystery Card", "Mulldrifter", "Leaf Gilder"]
        client = _make_mock_client(ratings)

        result = await draft_pack_pick(pack, "LRW", seventeen_lands=client)

        # Mulldrifter and Leaf Gilder should appear before Mystery Card
        mul_pos = result.markdown.index("Mulldrifter")
        lg_pos = result.markdown.index("Leaf Gilder")
        mc_pos = result.markdown.index("Mystery Card")
        assert mul_pos < mc_pos
        assert lg_pos < mc_pos

    async def test_none_gih_wr_shows_na(self):
        """Cards with None GIH WR display N/A instead of a percentage."""
        ratings = [*MOCK_RATINGS, RATING_NO_GIH]
        pack = ["Mystery Card"]
        client = _make_mock_client(ratings)

        result = await draft_pack_pick(pack, "LRW", seventeen_lands=client)

        assert "N/A" in result.markdown


class TestDraftPackPickColorAnalysis:
    """When current_picks are provided, color analysis should appear."""

    async def test_color_distribution_shown(self):
        """Color distribution section shown with current pick colors."""
        pack = ["Mulldrifter"]
        current_picks = ["Nameless Inversion", "Silvergill Adept", "Mulldrifter"]
        client = _make_mock_client()

        result = await draft_pack_pick(
            pack, "LRW", seventeen_lands=client, current_picks=current_picks
        )

        assert "Current colors" in result.markdown
        assert "U" in result.markdown
        assert "B" in result.markdown

    async def test_on_color_annotation(self):
        """Cards matching current pick colors annotated as on-color."""
        pack = ["Silvergill Adept"]
        # Current picks are mostly blue
        current_picks = ["Mulldrifter", "Silvergill Adept", "Mulldrifter"]
        client = _make_mock_client()

        result = await draft_pack_pick(
            pack, "LRW", seventeen_lands=client, current_picks=current_picks
        )

        assert "on-color" in result.markdown.lower()

    async def test_off_color_annotation(self):
        """Cards not matching current pick colors annotated as off-color."""
        pack = ["Leaf Gilder"]
        # Current picks are mostly blue
        current_picks = ["Mulldrifter", "Silvergill Adept", "Mulldrifter"]
        client = _make_mock_client()

        result = await draft_pack_pick(
            pack, "LRW", seventeen_lands=client, current_picks=current_picks
        )

        assert "off-color" in result.markdown.lower()

    async def test_no_color_analysis_without_picks(self):
        """No color analysis section when current_picks is not provided."""
        pack = ["Mulldrifter"]
        client = _make_mock_client()

        result = await draft_pack_pick(pack, "LRW", seventeen_lands=client)

        assert "Current colors" not in result.markdown

    async def test_no_color_analysis_with_empty_picks(self):
        """No color analysis section when current_picks is an empty list."""
        pack = ["Mulldrifter"]
        client = _make_mock_client()

        result = await draft_pack_pick(pack, "LRW", seventeen_lands=client, current_picks=[])

        assert "Current colors" not in result.markdown

    async def test_picks_not_in_data_ignored_for_color_analysis(self):
        """If a current pick isn't in 17Lands data, skip it for color counting."""
        pack = ["Mulldrifter"]
        current_picks = ["Totally Fake Card"]
        client = _make_mock_client()

        result = await draft_pack_pick(
            pack, "LRW", seventeen_lands=client, current_picks=current_picks
        )

        # No recognized picks → no color counts → color section omitted
        assert "Current colors" not in result.markdown


class TestDraftPackPickEdgeCases:
    """Edge cases: empty pack, single card."""

    async def test_empty_pack(self):
        """Empty pack returns a message about no cards."""
        pack: list[str] = []
        client = _make_mock_client()

        result = await draft_pack_pick(pack, "LRW", seventeen_lands=client)

        assert "empty" in result.markdown.lower() or "no cards" in result.markdown.lower()

    async def test_single_card_pack(self):
        """Single-card pack returns that card with its stats."""
        pack = ["Mulldrifter"]
        client = _make_mock_client()

        result = await draft_pack_pick(pack, "LRW", seventeen_lands=client)

        assert "Mulldrifter" in result.markdown
        assert "61.2%" in result.markdown

    async def test_none_alsa_shows_na(self):
        """Cards with None ALSA display N/A."""
        rating = _make_rating("No ALSA Card", avg_seen=None)
        client = _make_mock_client([rating])

        result = await draft_pack_pick(["No ALSA Card"], "LRW", seventeen_lands=client)

        assert "N/A" in result.markdown
