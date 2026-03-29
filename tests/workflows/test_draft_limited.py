"""Unit tests for draft limited workflow tools — sealed_pool_build, draft_signal_read, draft_log_review."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mtg_mcp_server.types import Card, CardPrices, DraftCardRating

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _make_card(
    name: str,
    mana_cost: str = "{1}{W}",
    type_line: str = "Creature — Human",
    oracle_text: str = "",
    colors: list[str] | None = None,
    color_identity: list[str] | None = None,
    cmc: float = 2.0,
    keywords: list[str] | None = None,
    power: str = "2",
    toughness: str = "2",
    rarity: str = "common",
    usd: str | None = "0.25",
) -> Card:
    """Build a Card model for testing."""
    return Card(
        id="test-id",
        name=name,
        mana_cost=mana_cost,
        cmc=cmc,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=colors or ["W"],
        color_identity=color_identity or ["W"],
        keywords=keywords or [],
        power=power,
        toughness=toughness,
        set_code="TST",
        rarity=rarity,
        prices=CardPrices(usd=usd),
    )


# A pool of cards across colors for sealed tests
POOL_CARDS: dict[str, Card] = {
    # White creatures
    "Serra Angel": _make_card(
        "Serra Angel",
        "{3}{W}{W}",
        "Creature — Angel",
        "Flying, vigilance",
        ["W"],
        ["W"],
        5.0,
        ["Flying", "Vigilance"],
        "4",
        "4",
        "uncommon",
    ),
    "Savannah Lions": _make_card(
        "Savannah Lions", "{W}", "Creature — Cat", "", ["W"], ["W"], 1.0, power="2", toughness="1"
    ),
    "Glory Seeker": _make_card(
        "Glory Seeker",
        "{1}{W}",
        "Creature — Human Soldier",
        "",
        ["W"],
        ["W"],
        2.0,
        power="2",
        toughness="2",
    ),
    "Inspiring Captain": _make_card(
        "Inspiring Captain",
        "{3}{W}",
        "Creature — Human Knight",
        "When Inspiring Captain enters, creatures you control get +1/+1 until end of turn.",
        ["W"],
        ["W"],
        4.0,
        power="3",
        toughness="3",
    ),
    # Blue creatures and spells
    "Mulldrifter": _make_card(
        "Mulldrifter",
        "{4}{U}",
        "Creature — Elemental",
        "Flying\nWhen Mulldrifter enters, draw two cards.\nEvoke {2}{U}",
        ["U"],
        ["U"],
        5.0,
        ["Flying"],
        "2",
        "2",
        "common",
    ),
    "Silvergill Adept": _make_card(
        "Silvergill Adept",
        "{1}{U}",
        "Creature — Merfolk Wizard",
        "When Silvergill Adept enters, draw a card.",
        ["U"],
        ["U"],
        2.0,
        power="2",
        toughness="1",
        rarity="uncommon",
    ),
    "Wind Drake": _make_card(
        "Wind Drake",
        "{2}{U}",
        "Creature — Drake",
        "Flying",
        ["U"],
        ["U"],
        3.0,
        ["Flying"],
        "2",
        "2",
    ),
    "Cancel": _make_card(
        "Cancel", "{1}{U}{U}", "Instant", "Counter target spell.", ["U"], ["U"], 3.0
    ),
    # Black creatures and spells
    "Nameless Inversion": _make_card(
        "Nameless Inversion",
        "{1}{B}",
        "Tribal Instant — Shapeshifter",
        "Target creature gets +3/-3 and loses all creature types until end of turn.",
        ["B"],
        ["B"],
        2.0,
    ),
    "Ravenous Rats": _make_card(
        "Ravenous Rats",
        "{1}{B}",
        "Creature — Rat",
        "When Ravenous Rats enters, target opponent discards a card.",
        ["B"],
        ["B"],
        2.0,
        power="1",
        toughness="1",
    ),
    "Dread Shade": _make_card(
        "Dread Shade",
        "{B}{B}{B}",
        "Creature — Shade",
        "{B}: Dread Shade gets +1/+1 until end of turn.",
        ["B"],
        ["B"],
        3.0,
        power="3",
        toughness="3",
        rarity="rare",
    ),
    # Red creatures and spells
    "Shock": _make_card(
        "Shock", "{R}", "Instant", "Shock deals 2 damage to any target.", ["R"], ["R"], 1.0
    ),
    "Goblin Piker": _make_card(
        "Goblin Piker",
        "{1}{R}",
        "Creature — Goblin Warrior",
        "",
        ["R"],
        ["R"],
        2.0,
        power="2",
        toughness="1",
    ),
    "Fire Elemental": _make_card(
        "Fire Elemental",
        "{3}{R}{R}",
        "Creature — Elemental",
        "",
        ["R"],
        ["R"],
        5.0,
        power="5",
        toughness="4",
    ),
    # Green creatures
    "Llanowar Elves": _make_card(
        "Llanowar Elves",
        "{G}",
        "Creature — Elf Druid",
        "{T}: Add {G}.",
        ["G"],
        ["G"],
        1.0,
        power="1",
        toughness="1",
    ),
    "Centaur Courser": _make_card(
        "Centaur Courser",
        "{2}{G}",
        "Creature — Centaur Warrior",
        "",
        ["G"],
        ["G"],
        3.0,
        power="3",
        toughness="3",
    ),
    "Colossal Dreadmaw": _make_card(
        "Colossal Dreadmaw",
        "{4}{G}{G}",
        "Creature — Dinosaur",
        "Trample",
        ["G"],
        ["G"],
        6.0,
        ["Trample"],
        "6",
        "6",
    ),
    # Filler
    "Walking Corpse": _make_card(
        "Walking Corpse",
        "{1}{B}",
        "Creature — Zombie",
        "",
        ["B"],
        ["B"],
        2.0,
        power="2",
        toughness="2",
    ),
    "Runeclaw Bear": _make_card(
        "Runeclaw Bear",
        "{1}{G}",
        "Creature — Bear",
        "",
        ["G"],
        ["G"],
        2.0,
        power="2",
        toughness="2",
    ),
    # Bomb rare
    "Baneslayer Angel": _make_card(
        "Baneslayer Angel",
        "{3}{W}{W}",
        "Creature — Angel",
        "Flying, first strike, lifelink",
        ["W"],
        ["W"],
        5.0,
        ["Flying", "First strike", "Lifelink"],
        "5",
        "5",
        "mythic",
    ),
    # Land (should not count as playable nonland)
    "Plains": _make_card(
        "Plains", "", "Basic Land — Plains", "", [], [], 0.0, power="", toughness=""
    ),
}


RATINGS_FOR_SET: list[DraftCardRating] = [
    _make_rating("Serra Angel", "W", "uncommon", 0.570, 3.5, 0.030, 0.560, 12000),
    _make_rating("Savannah Lions", "W", "common", 0.540, 6.0, 0.010, 0.530, 8000),
    _make_rating("Glory Seeker", "W", "common", 0.510, 7.5, 0.005, 0.505, 7000),
    _make_rating("Inspiring Captain", "W", "common", 0.530, 6.5, 0.015, 0.525, 9000),
    _make_rating("Mulldrifter", "U", "common", 0.612, 2.8, 0.045, 0.605, 18000),
    _make_rating("Silvergill Adept", "U", "uncommon", 0.572, 3.5, 0.025, 0.568, 12000),
    _make_rating("Wind Drake", "U", "common", 0.535, 6.3, 0.012, 0.530, 8000),
    _make_rating("Cancel", "U", "common", 0.505, 8.0, -0.005, 0.500, 6000),
    _make_rating("Nameless Inversion", "B", "common", 0.587, 4.2, 0.033, 0.591, 15000),
    _make_rating("Ravenous Rats", "B", "common", 0.520, 7.0, 0.008, 0.515, 7000),
    _make_rating("Dread Shade", "B", "rare", 0.560, 2.0, 0.025, 0.555, 5000),
    _make_rating("Shock", "R", "common", 0.565, 4.5, 0.028, 0.560, 14000),
    _make_rating("Goblin Piker", "R", "common", 0.490, 9.0, -0.010, 0.485, 6000),
    _make_rating("Fire Elemental", "R", "common", 0.515, 7.0, 0.008, 0.510, 7000),
    _make_rating("Llanowar Elves", "G", "common", 0.580, 3.0, 0.035, 0.575, 16000),
    _make_rating("Centaur Courser", "G", "common", 0.525, 6.8, 0.010, 0.520, 8000),
    _make_rating("Colossal Dreadmaw", "G", "common", 0.510, 7.5, 0.005, 0.505, 7000),
    _make_rating("Walking Corpse", "B", "common", 0.500, 8.5, 0.000, 0.495, 5000),
    _make_rating("Runeclaw Bear", "G", "common", 0.505, 8.0, 0.002, 0.500, 6000),
    _make_rating("Baneslayer Angel", "W", "mythic", 0.650, 1.5, 0.060, 0.640, 3000),
]


@pytest.fixture
def mock_bulk() -> AsyncMock:
    """Mock ScryfallBulkClient that returns cards from POOL_CARDS."""
    mock = AsyncMock()

    async def _get_card(name: str) -> Card | None:
        return POOL_CARDS.get(name)

    async def _get_cards(names: list[str]) -> dict[str, Card | None]:
        return {name: POOL_CARDS.get(name) for name in names}

    mock.get_card.side_effect = _get_card
    mock.get_cards.side_effect = _get_cards
    return mock


@pytest.fixture
def mock_17lands() -> AsyncMock:
    """Mock SeventeenLandsClient that returns RATINGS_FOR_SET."""
    mock = AsyncMock()
    mock.card_ratings.return_value = RATINGS_FOR_SET
    return mock


# ===========================================================================
# sealed_pool_build
# ===========================================================================


class TestSealedPoolBuild:
    """Tests for the sealed_pool_build workflow."""

    async def test_basic_build_returns_result(self, mock_bulk: AsyncMock, mock_17lands: AsyncMock):
        """Should return a WorkflowResult with markdown and data."""
        from mtg_mcp_server.workflows.draft_limited import sealed_pool_build

        pool = list(POOL_CARDS.keys())
        result = await sealed_pool_build(pool, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands)

        assert result.markdown
        assert isinstance(result.data, dict)
        assert "builds" in result.data

    async def test_header_contains_set_code(self, mock_bulk: AsyncMock, mock_17lands: AsyncMock):
        """Output should include a header with the set code."""
        from mtg_mcp_server.workflows.draft_limited import sealed_pool_build

        pool = list(POOL_CARDS.keys())
        result = await sealed_pool_build(pool, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands)

        assert "TST" in result.markdown
        assert "Sealed Pool" in result.markdown

    async def test_builds_ranked_by_quality(self, mock_bulk: AsyncMock, mock_17lands: AsyncMock):
        """Builds should be ordered by quality score, best first."""
        from mtg_mcp_server.workflows.draft_limited import sealed_pool_build

        pool = list(POOL_CARDS.keys())
        result = await sealed_pool_build(pool, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands)

        builds = result.data["builds"]
        assert len(builds) >= 1
        # Scores should be in descending order
        scores = [b["score"] for b in builds]
        assert scores == sorted(scores, reverse=True)

    async def test_includes_land_suggestion(self, mock_bulk: AsyncMock, mock_17lands: AsyncMock):
        """Each build should suggest a 17-land mana base."""
        from mtg_mcp_server.workflows.draft_limited import sealed_pool_build

        pool = list(POOL_CARDS.keys())
        result = await sealed_pool_build(pool, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands)

        # Should mention lands in the output
        assert "land" in result.markdown.lower() or "Land" in result.markdown

    async def test_without_17lands(self, mock_bulk: AsyncMock):
        """Should fall back to heuristic scoring when 17Lands is unavailable."""
        from mtg_mcp_server.workflows.draft_limited import sealed_pool_build

        pool = list(POOL_CARDS.keys())
        result = await sealed_pool_build(pool, "TST", bulk=mock_bulk, seventeen_lands=None)

        assert result.markdown
        builds = result.data["builds"]
        assert len(builds) >= 1
        # Should still produce ranked builds
        scores = [b["score"] for b in builds]
        assert scores == sorted(scores, reverse=True)

    async def test_empty_pool(self, mock_bulk: AsyncMock, mock_17lands: AsyncMock):
        """Empty pool should return a message about no cards."""
        from mtg_mcp_server.workflows.draft_limited import sealed_pool_build

        result = await sealed_pool_build([], "TST", bulk=mock_bulk, seventeen_lands=mock_17lands)

        assert "empty" in result.markdown.lower() or "no cards" in result.markdown.lower()

    async def test_progress_reporting(self, mock_bulk: AsyncMock, mock_17lands: AsyncMock):
        """Progress callback should be invoked with (step, 3)."""
        from mtg_mcp_server.workflows.draft_limited import sealed_pool_build

        progress_calls: list[tuple[int, int]] = []

        async def on_progress(step: int, total: int) -> None:
            progress_calls.append((step, total))

        pool = list(POOL_CARDS.keys())
        await sealed_pool_build(
            pool, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands, on_progress=on_progress
        )

        assert (1, 3) in progress_calls
        assert (2, 3) in progress_calls
        assert (3, 3) in progress_calls

    async def test_mana_curve_in_output(self, mock_bulk: AsyncMock, mock_17lands: AsyncMock):
        """Output should include a mana curve for each build."""
        from mtg_mcp_server.workflows.draft_limited import sealed_pool_build

        pool = list(POOL_CARDS.keys())
        result = await sealed_pool_build(pool, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands)

        # Should mention curve
        assert "curve" in result.markdown.lower() or "CMC" in result.markdown

    async def test_unresolved_cards_noted(self, mock_bulk: AsyncMock, mock_17lands: AsyncMock):
        """Cards not found in bulk data should be noted."""
        from mtg_mcp_server.workflows.draft_limited import sealed_pool_build

        pool = ["Totally Fake Card", "Mulldrifter", "Serra Angel"]
        result = await sealed_pool_build(pool, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands)

        assert "unresolved" in result.data or "Totally Fake Card" in result.markdown

    async def test_concise_format(self, mock_bulk: AsyncMock, mock_17lands: AsyncMock):
        """Concise format should produce shorter output."""
        from mtg_mcp_server.workflows.draft_limited import sealed_pool_build

        pool = list(POOL_CARDS.keys())
        detailed = await sealed_pool_build(
            pool, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands, response_format="detailed"
        )
        concise = await sealed_pool_build(
            pool, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands, response_format="concise"
        )

        assert len(concise.markdown) <= len(detailed.markdown)

    async def test_lands_not_counted_as_playables(
        self, mock_bulk: AsyncMock, mock_17lands: AsyncMock
    ):
        """Basic lands in the pool should not be counted as nonland playables."""
        from mtg_mcp_server.workflows.draft_limited import sealed_pool_build

        # Pool with mostly lands
        pool = ["Plains", "Plains", "Plains", "Mulldrifter"]
        result = await sealed_pool_build(pool, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands)

        # Should still produce output without crashing
        assert result.markdown


# ===========================================================================
# draft_signal_read
# ===========================================================================


class TestDraftSignalRead:
    """Tests for the draft_signal_read workflow."""

    async def test_basic_signal_analysis(self, mock_bulk: AsyncMock, mock_17lands: AsyncMock):
        """Should return a WorkflowResult with signal data."""
        from mtg_mcp_server.workflows.draft_limited import draft_signal_read

        picks = ["Mulldrifter", "Nameless Inversion", "Silvergill Adept"]
        result = await draft_signal_read(picks, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands)

        assert result.markdown
        assert isinstance(result.data, dict)
        assert "signals" in result.data

    async def test_color_commitment_shown(self, mock_bulk: AsyncMock, mock_17lands: AsyncMock):
        """Output should show which colors the drafter is committed to."""
        from mtg_mcp_server.workflows.draft_limited import draft_signal_read

        picks = ["Mulldrifter", "Silvergill Adept", "Wind Drake"]
        result = await draft_signal_read(picks, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands)

        # Should show blue commitment
        assert "U" in result.markdown or "Blue" in result.markdown

    async def test_signal_strength_calculated(self, mock_bulk: AsyncMock, mock_17lands: AsyncMock):
        """Signal strength should be calculated per color."""
        from mtg_mcp_server.workflows.draft_limited import draft_signal_read

        # Picks where cards were taken later than expected ALSA = open signal
        picks = ["Mulldrifter", "Nameless Inversion"]
        result = await draft_signal_read(picks, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands)

        signals = result.data["signals"]
        assert isinstance(signals, dict)
        # Should have signal values for at least the colors we picked
        assert len(signals) > 0

    async def test_current_pack_ranking(self, mock_bulk: AsyncMock, mock_17lands: AsyncMock):
        """When current_pack is provided, it should rank those cards."""
        from mtg_mcp_server.workflows.draft_limited import draft_signal_read

        picks = ["Mulldrifter", "Silvergill Adept"]
        current_pack = ["Serra Angel", "Shock", "Wind Drake"]
        result = await draft_signal_read(
            picks, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands, current_pack=current_pack
        )

        # Should mention current pack cards
        assert "Serra Angel" in result.markdown or "Wind Drake" in result.markdown

    async def test_empty_picks(self, mock_bulk: AsyncMock, mock_17lands: AsyncMock):
        """Empty picks should return a message about no data."""
        from mtg_mcp_server.workflows.draft_limited import draft_signal_read

        result = await draft_signal_read([], "TST", bulk=mock_bulk, seventeen_lands=mock_17lands)

        assert (
            "no picks" in result.markdown.lower()
            or "empty" in result.markdown.lower()
            or result.data.get("signals") == {}
        )

    async def test_header_with_set_code(self, mock_bulk: AsyncMock, mock_17lands: AsyncMock):
        """Output should include the set code in the header."""
        from mtg_mcp_server.workflows.draft_limited import draft_signal_read

        picks = ["Mulldrifter"]
        result = await draft_signal_read(picks, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands)

        assert "TST" in result.markdown

    async def test_concise_format(self, mock_bulk: AsyncMock, mock_17lands: AsyncMock):
        """Concise output should be shorter than detailed."""
        from mtg_mcp_server.workflows.draft_limited import draft_signal_read

        picks = ["Mulldrifter", "Nameless Inversion", "Silvergill Adept"]
        detailed = await draft_signal_read(
            picks, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands, response_format="detailed"
        )
        concise = await draft_signal_read(
            picks, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands, response_format="concise"
        )

        assert len(concise.markdown) <= len(detailed.markdown)


# ===========================================================================
# draft_log_review
# ===========================================================================


class TestDraftLogReview:
    """Tests for the draft_log_review workflow."""

    async def test_basic_review(self, mock_bulk: AsyncMock, mock_17lands: AsyncMock):
        """Should return a WorkflowResult with markdown and data."""
        from mtg_mcp_server.workflows.draft_limited import draft_log_review

        picks = ["Mulldrifter", "Nameless Inversion", "Serra Angel"]
        result = await draft_log_review(picks, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands)

        assert result.markdown
        assert isinstance(result.data, dict)

    async def test_pick_table_present(self, mock_bulk: AsyncMock, mock_17lands: AsyncMock):
        """Output should contain a pick-by-pick table."""
        from mtg_mcp_server.workflows.draft_limited import draft_log_review

        picks = ["Mulldrifter", "Nameless Inversion", "Serra Angel"]
        result = await draft_log_review(picks, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands)

        # Should have pick numbers
        assert "P1P1" in result.markdown or "1" in result.markdown
        assert "Mulldrifter" in result.markdown

    async def test_gih_wr_shown_per_pick(self, mock_bulk: AsyncMock, mock_17lands: AsyncMock):
        """Each pick should show its GIH WR."""
        from mtg_mcp_server.workflows.draft_limited import draft_log_review

        picks = ["Mulldrifter"]
        result = await draft_log_review(picks, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands)

        # Mulldrifter has 0.612 = 61.2%
        assert "61.2%" in result.markdown

    async def test_average_gih_wr_computed(self, mock_bulk: AsyncMock, mock_17lands: AsyncMock):
        """Data should include average GIH WR across all picks."""
        from mtg_mcp_server.workflows.draft_limited import draft_log_review

        picks = ["Mulldrifter", "Nameless Inversion"]
        result = await draft_log_review(picks, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands)

        assert "avg_gih_wr" in result.data
        # Average of 0.612 and 0.587 = 0.5995
        avg = result.data["avg_gih_wr"]
        assert avg is not None
        assert abs(avg - 0.5995) < 0.01

    async def test_color_consistency_tracked(self, mock_bulk: AsyncMock, mock_17lands: AsyncMock):
        """Data should include color breakdown of picks."""
        from mtg_mcp_server.workflows.draft_limited import draft_log_review

        picks = ["Mulldrifter", "Silvergill Adept", "Wind Drake"]
        result = await draft_log_review(picks, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands)

        assert "color_counts" in result.data

    async def test_final_deck_analysis(self, mock_bulk: AsyncMock, mock_17lands: AsyncMock):
        """When final_deck is provided, should analyze what made the cut."""
        from mtg_mcp_server.workflows.draft_limited import draft_log_review

        picks = ["Mulldrifter", "Nameless Inversion", "Serra Angel", "Goblin Piker"]
        final_deck = ["Mulldrifter", "Nameless Inversion", "Serra Angel"]
        result = await draft_log_review(
            picks, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands, final_deck=final_deck
        )

        # Should mention sideboard rate or deck inclusion
        assert (
            "sideboard" in result.markdown.lower()
            or "cut" in result.markdown.lower()
            or "final" in result.markdown.lower()
        )

    async def test_draft_grade_in_data(self, mock_bulk: AsyncMock, mock_17lands: AsyncMock):
        """Data should contain a draft grade."""
        from mtg_mcp_server.workflows.draft_limited import draft_log_review

        picks = ["Mulldrifter", "Nameless Inversion", "Serra Angel"]
        result = await draft_log_review(picks, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands)

        assert "grade" in result.data
        assert result.data["grade"] in ("A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D", "F")

    async def test_empty_picks_handled(self, mock_bulk: AsyncMock, mock_17lands: AsyncMock):
        """Empty picks should return an appropriate message."""
        from mtg_mcp_server.workflows.draft_limited import draft_log_review

        result = await draft_log_review([], "TST", bulk=mock_bulk, seventeen_lands=mock_17lands)

        assert "no picks" in result.markdown.lower() or "empty" in result.markdown.lower()

    async def test_header_with_set_code(self, mock_bulk: AsyncMock, mock_17lands: AsyncMock):
        """Output should include the set code in the header."""
        from mtg_mcp_server.workflows.draft_limited import draft_log_review

        picks = ["Mulldrifter"]
        result = await draft_log_review(picks, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands)

        assert "TST" in result.markdown

    async def test_pick_number_formatting(self, mock_bulk: AsyncMock, mock_17lands: AsyncMock):
        """Picks should be labeled with pack/pick numbers (P1P1 format)."""
        from mtg_mcp_server.workflows.draft_limited import draft_log_review

        # 15 picks = pack 1 complete + 1 from pack 2
        picks = [
            "Mulldrifter",
            "Nameless Inversion",
            "Serra Angel",
            "Shock",
            "Llanowar Elves",
            "Savannah Lions",
            "Wind Drake",
            "Ravenous Rats",
            "Centaur Courser",
            "Glory Seeker",
            "Goblin Piker",
            "Cancel",
            "Walking Corpse",
            "Runeclaw Bear",
            # Pack 2
            "Silvergill Adept",
        ]
        result = await draft_log_review(picks, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands)

        assert "P1P1" in result.markdown
        assert "P2P1" in result.markdown

    async def test_concise_format(self, mock_bulk: AsyncMock, mock_17lands: AsyncMock):
        """Concise output should be shorter."""
        from mtg_mcp_server.workflows.draft_limited import draft_log_review

        picks = ["Mulldrifter", "Nameless Inversion", "Serra Angel"]
        detailed = await draft_log_review(
            picks, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands, response_format="detailed"
        )
        concise = await draft_log_review(
            picks, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands, response_format="concise"
        )

        assert len(concise.markdown) <= len(detailed.markdown)

    async def test_unknown_cards_handled(self, mock_bulk: AsyncMock, mock_17lands: AsyncMock):
        """Cards not in 17Lands data should show N/A for GIH WR."""
        from mtg_mcp_server.workflows.draft_limited import draft_log_review

        picks = ["Totally Fake Card", "Mulldrifter"]
        result = await draft_log_review(picks, "TST", bulk=mock_bulk, seventeen_lands=mock_17lands)

        assert "N/A" in result.markdown or "no data" in result.markdown.lower()
