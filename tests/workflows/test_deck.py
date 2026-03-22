"""Tests for suggest_cuts deck workflow."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mtg_mcp.types import (
    Combo,
    ComboCard,
    ComboResult,
    DecklistCombos,
    EDHRECCard,
    EDHRECCardList,
    EDHRECCommanderData,
)
from mtg_mcp.workflows.deck import suggest_cuts

# ---------------------------------------------------------------------------
# Fixtures — mock data
# ---------------------------------------------------------------------------


def _make_decklist_combos(
    included: list[Combo] | None = None,
    almost_included: list[Combo] | None = None,
) -> DecklistCombos:
    return DecklistCombos(
        identity="BGU",
        included=included or [],
        almost_included=almost_included or [],
    )


def _make_edhrec_data(
    cardviews: list[EDHRECCard] | None = None,
) -> EDHRECCommanderData:
    return EDHRECCommanderData(
        commander_name="Muldrotha, the Gravetide",
        total_decks=19000,
        cardlists=[
            EDHRECCardList(
                header="Creatures",
                tag="creatures",
                cardviews=cardviews
                or [
                    EDHRECCard(name="Spore Frog", synergy=0.61, inclusion=61, num_decks=12050),
                    EDHRECCard(name="Shriekmaw", synergy=0.45, inclusion=48, num_decks=9500),
                    EDHRECCard(name="Random Bad Card", synergy=0.05, inclusion=8, num_decks=1500),
                ],
            ),
        ],
    )


COMBO_WITH_SPORE_FROG = Combo(
    id="combo-1",
    cards=[
        ComboCard(name="Spore Frog", zone_locations=["G"]),
        ComboCard(name="Muldrotha, the Gravetide", zone_locations=["C"], must_be_commander=True),
    ],
    produces=[ComboResult(feature_name="Repeatable fog effect")],
)

SAMPLE_DECKLIST = [
    "Spore Frog",
    "Shriekmaw",
    "Random Bad Card",
    "Sol Ring",
    "Unknown Card",
]


def _extract_ranked_lines(text: str) -> list[str]:
    """Extract lines that start with a digit (ranking number) from output."""
    lines = text.split("\n")
    return [ln.strip() for ln in lines if ln.strip() and ln.strip()[0].isdigit()]


def _find_rank_of(card_name: str, ranked_lines: list[str]) -> int | None:
    """Find the rank number of a card in ranked output lines."""
    for ln in ranked_lines:
        if card_name in ln:
            return int(ln.split(".")[0])
    return None


@pytest.fixture
def mock_spellbook() -> AsyncMock:
    client = AsyncMock()
    client.find_decklist_combos = AsyncMock(
        return_value=_make_decklist_combos(included=[COMBO_WITH_SPORE_FROG])
    )
    return client


@pytest.fixture
def mock_edhrec() -> AsyncMock:
    client = AsyncMock()
    client.commander_top_cards = AsyncMock(return_value=_make_edhrec_data())
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAllSourcesSucceed:
    """Both Spellbook and EDHREC return valid data."""

    async def test_returns_ranked_output(
        self, mock_spellbook: AsyncMock, mock_edhrec: AsyncMock
    ) -> None:
        result = await suggest_cuts(
            SAMPLE_DECKLIST,
            "Muldrotha, the Gravetide",
            spellbook=mock_spellbook,
            edhrec=mock_edhrec,
            num_cuts=5,
        )

        assert "Suggested Cuts for Muldrotha, the Gravetide" in result
        # Random Bad Card should be the top cut (low synergy, low inclusion)
        ranked = _extract_ranked_lines(result)
        first_place = [ln for ln in ranked if ln.startswith("1.")]
        assert len(first_place) == 1
        assert "Random Bad Card" in first_place[0]

    async def test_combo_piece_is_protected(
        self, mock_spellbook: AsyncMock, mock_edhrec: AsyncMock
    ) -> None:
        result = await suggest_cuts(
            SAMPLE_DECKLIST,
            "Muldrotha, the Gravetide",
            spellbook=mock_spellbook,
            edhrec=mock_edhrec,
            num_cuts=5,
        )

        ranked = _extract_ranked_lines(result)
        spore_frog_rank = _find_rank_of("Spore Frog", ranked)
        random_bad_rank = _find_rank_of("Random Bad Card", ranked)

        assert spore_frog_rank is not None
        assert random_bad_rank is not None
        assert random_bad_rank < spore_frog_rank, (
            "Random Bad Card should be ranked before Spore Frog (combo piece)"
        )

    async def test_synergy_and_inclusion_shown(
        self, mock_spellbook: AsyncMock, mock_edhrec: AsyncMock
    ) -> None:
        result = await suggest_cuts(
            SAMPLE_DECKLIST,
            "Muldrotha, the Gravetide",
            spellbook=mock_spellbook,
            edhrec=mock_edhrec,
            num_cuts=5,
        )

        # Cards with EDHREC data should show synergy and inclusion
        assert "Synergy:" in result
        assert "Inclusion:" in result

    async def test_combo_piece_label_shown(
        self, mock_spellbook: AsyncMock, mock_edhrec: AsyncMock
    ) -> None:
        result = await suggest_cuts(
            SAMPLE_DECKLIST,
            "Muldrotha, the Gravetide",
            spellbook=mock_spellbook,
            edhrec=mock_edhrec,
            num_cuts=5,
        )

        # Spore Frog is a combo piece — should be marked
        assert "combo piece" in result.lower()

    async def test_data_sources_status_shown(
        self, mock_spellbook: AsyncMock, mock_edhrec: AsyncMock
    ) -> None:
        result = await suggest_cuts(
            SAMPLE_DECKLIST,
            "Muldrotha, the Gravetide",
            spellbook=mock_spellbook,
            edhrec=mock_edhrec,
            num_cuts=5,
        )

        assert "Spellbook" in result
        assert "EDHREC" in result

    async def test_unknown_card_flagged(
        self, mock_spellbook: AsyncMock, mock_edhrec: AsyncMock
    ) -> None:
        result = await suggest_cuts(
            SAMPLE_DECKLIST,
            "Muldrotha, the Gravetide",
            spellbook=mock_spellbook,
            edhrec=mock_edhrec,
            num_cuts=5,
        )

        # "Unknown Card" has no EDHREC data and is not a combo piece
        assert "low confidence" in result.lower()


class TestEdhrecIsNone:
    """EDHREC client is None (disabled via feature flag)."""

    async def test_ranks_by_combo_membership_only(self, mock_spellbook: AsyncMock) -> None:
        result = await suggest_cuts(
            SAMPLE_DECKLIST,
            "Muldrotha, the Gravetide",
            spellbook=mock_spellbook,
            edhrec=None,
            num_cuts=5,
        )

        assert "Suggested Cuts for Muldrotha, the Gravetide" in result
        # Spore Frog is a combo piece, should be ranked lower
        ranked = _extract_ranked_lines(result)
        spore_frog_rank = _find_rank_of("Spore Frog", ranked)
        assert spore_frog_rank is not None
        # Non-combo cards should be ranked first
        non_combo_ranks = []
        for ln in ranked:
            if "Spore Frog" not in ln:
                non_combo_ranks.append(int(ln.split(".")[0]))
        assert all(r < spore_frog_rank for r in non_combo_ranks)

    async def test_edhrec_unavailable_noted(self, mock_spellbook: AsyncMock) -> None:
        result = await suggest_cuts(
            SAMPLE_DECKLIST,
            "Muldrotha, the Gravetide",
            spellbook=mock_spellbook,
            edhrec=None,
            num_cuts=5,
        )

        assert "EDHREC" in result
        # Should indicate EDHREC is unavailable
        assert "unavailable" in result.lower() or "disabled" in result.lower()


class TestEdhrecRaisesException:
    """EDHREC client raises an exception during the call."""

    async def test_ranks_by_combo_data_with_failure_note(self, mock_spellbook: AsyncMock) -> None:
        mock_edhrec = AsyncMock()
        mock_edhrec.commander_top_cards = AsyncMock(side_effect=Exception("EDHREC is down"))

        result = await suggest_cuts(
            SAMPLE_DECKLIST,
            "Muldrotha, the Gravetide",
            spellbook=mock_spellbook,
            edhrec=mock_edhrec,
            num_cuts=5,
        )

        assert "Suggested Cuts for Muldrotha, the Gravetide" in result
        # Should note the failure
        assert "EDHREC" in result
        assert "failed" in result.lower()
        # Should still rank cards (combo data available)
        ranked = _extract_ranked_lines(result)
        assert len(ranked) == len(SAMPLE_DECKLIST)


class TestSpellbookRaisesException:
    """Spellbook client raises an exception during the call."""

    async def test_ranks_by_edhrec_data_with_failure_note(self, mock_edhrec: AsyncMock) -> None:
        mock_spellbook = AsyncMock()
        mock_spellbook.find_decklist_combos = AsyncMock(side_effect=Exception("Spellbook is down"))

        result = await suggest_cuts(
            SAMPLE_DECKLIST,
            "Muldrotha, the Gravetide",
            spellbook=mock_spellbook,
            edhrec=mock_edhrec,
            num_cuts=5,
        )

        assert "Suggested Cuts for Muldrotha, the Gravetide" in result
        # Should note the failure
        assert "Spellbook" in result
        assert "failed" in result.lower()
        # Random Bad Card should still be top cut (low synergy/inclusion via EDHREC)
        ranked = _extract_ranked_lines(result)
        first_place = [ln for ln in ranked if ln.startswith("1.")]
        assert len(first_place) == 1
        assert "Random Bad Card" in first_place[0]


class TestBothRaiseExceptions:
    """Both Spellbook and EDHREC fail."""

    async def test_all_cards_flagged_low_confidence(self) -> None:
        mock_spellbook = AsyncMock()
        mock_spellbook.find_decklist_combos = AsyncMock(side_effect=Exception("Spellbook is down"))
        mock_edhrec = AsyncMock()
        mock_edhrec.commander_top_cards = AsyncMock(side_effect=Exception("EDHREC is down"))

        result = await suggest_cuts(
            SAMPLE_DECKLIST,
            "Muldrotha, the Gravetide",
            spellbook=mock_spellbook,
            edhrec=mock_edhrec,
            num_cuts=5,
        )

        assert "Suggested Cuts for Muldrotha, the Gravetide" in result
        # All cards should be flagged as low confidence
        low_confidence_count = result.lower().count("low confidence")
        assert low_confidence_count == len(SAMPLE_DECKLIST)


class TestNoCombosFound:
    """Spellbook returns no combos."""

    async def test_synergy_data_only_drives_ranking(self, mock_edhrec: AsyncMock) -> None:
        mock_spellbook = AsyncMock()
        mock_spellbook.find_decklist_combos = AsyncMock(
            return_value=_make_decklist_combos(included=[])
        )

        result = await suggest_cuts(
            SAMPLE_DECKLIST,
            "Muldrotha, the Gravetide",
            spellbook=mock_spellbook,
            edhrec=mock_edhrec,
            num_cuts=5,
        )

        # Random Bad Card should be top cut since no combo protection applies
        ranked = _extract_ranked_lines(result)
        first_place = [ln for ln in ranked if ln.startswith("1.")]
        assert len(first_place) == 1
        assert "Random Bad Card" in first_place[0]

        # No "combo piece" labels since no combos found
        assert "combo piece" not in result.lower()


class TestNumCutsGreaterThanDeckSize:
    """num_cuts exceeds the decklist length."""

    async def test_caps_at_decklist_length(
        self, mock_spellbook: AsyncMock, mock_edhrec: AsyncMock
    ) -> None:
        small_decklist = ["Spore Frog", "Shriekmaw"]
        result = await suggest_cuts(
            small_decklist,
            "Muldrotha, the Gravetide",
            spellbook=mock_spellbook,
            edhrec=mock_edhrec,
            num_cuts=10,
        )

        ranked = _extract_ranked_lines(result)
        assert len(ranked) == 2


class TestEmptyDecklist:
    """Decklist is empty."""

    async def test_returns_appropriate_message(
        self, mock_spellbook: AsyncMock, mock_edhrec: AsyncMock
    ) -> None:
        result = await suggest_cuts(
            [],
            "Muldrotha, the Gravetide",
            spellbook=mock_spellbook,
            edhrec=mock_edhrec,
            num_cuts=5,
        )

        assert "no cards" in result.lower() or "empty" in result.lower()


class TestNumCutsZero:
    """num_cuts is 0."""

    async def test_returns_empty_result(
        self, mock_spellbook: AsyncMock, mock_edhrec: AsyncMock
    ) -> None:
        result = await suggest_cuts(
            SAMPLE_DECKLIST,
            "Muldrotha, the Gravetide",
            spellbook=mock_spellbook,
            edhrec=mock_edhrec,
            num_cuts=0,
        )

        # Should have the header but no ranked items
        assert "Suggested Cuts for Muldrotha, the Gravetide" in result
        ranked = _extract_ranked_lines(result)
        assert len(ranked) == 0
