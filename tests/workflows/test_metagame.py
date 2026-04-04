"""Tests for constructed metagame workflow functions.

These are unit tests of pure async functions. Service clients are mocked with
AsyncMock — no respx/httpx needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mtg_mcp_server.types import (
    Card,
    CardPrices,
    GoldfishArchetype,
    GoldfishArchetypeDetail,
    GoldfishMetaSnapshot,
    SpicerackStanding,
    SpicerackTournament,
)
from mtg_mcp_server.workflows.metagame import (
    _classify_tiers,
    _match_archetype,
    archetype_comparison,
    archetype_decklist,
    format_entry_guide,
    metagame_snapshot,
)

# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------


def _mock_card(
    name: str = "Lightning Bolt",
    *,
    price_usd: str | None = "1.50",
    type_line: str = "Instant",
) -> Card:
    """Create a test Card object."""
    return Card(
        id=f"test-id-{name.lower().replace(' ', '-')}",
        name=name,
        mana_cost="{R}",
        cmc=1.0,
        type_line=type_line,
        colors=["R"],
        color_identity=["R"],
        set="m25",
        rarity="uncommon",
        prices=CardPrices(usd=price_usd),
    )


def _mock_archetypes() -> list[GoldfishArchetype]:
    """Create a set of test archetypes with diverse meta shares."""
    return [
        GoldfishArchetype(
            name="Boros Energy",
            slug="boros-energy",
            meta_share=20.3,
            deck_count=150,
            price_paper=350,
            colors=["W", "R"],
        ),
        GoldfishArchetype(
            name="Azorius Control",
            slug="azorius-control",
            meta_share=8.5,
            deck_count=60,
            price_paper=500,
            colors=["W", "U"],
        ),
        GoldfishArchetype(
            name="Mono-Red Aggro",
            slug="mono-red-aggro",
            meta_share=5.1,
            deck_count=40,
            price_paper=150,
            colors=["R"],
        ),
        GoldfishArchetype(
            name="Jeskai Control",
            slug="jeskai-control",
            meta_share=2.0,
            deck_count=15,
            price_paper=600,
            colors=["W", "U", "R"],
        ),
        GoldfishArchetype(
            name="Golgari Midrange",
            slug="golgari-midrange",
            meta_share=1.5,
            deck_count=10,
            price_paper=200,
            colors=["B", "G"],
        ),
    ]


def _mock_snapshot(format: str = "modern") -> GoldfishMetaSnapshot:
    """Create a test metagame snapshot."""
    archetypes = _mock_archetypes()
    return GoldfishMetaSnapshot(
        format=format,
        archetypes=archetypes,
        total_decks=sum(a.deck_count for a in archetypes),
    )


def _mock_archetype_detail(
    name: str = "Boros Energy",
) -> GoldfishArchetypeDetail:
    """Create a test archetype detail with decklist."""
    return GoldfishArchetypeDetail(
        name=name,
        author="TestPlayer",
        event="Modern Challenge",
        result="1st",
        deck_id="12345",
        date="2026-03-15",
        mainboard=[
            "4 Lightning Bolt",
            "4 Ragavan, Nimble Pilferer",
            "4 Goblin Guide",
            "3 Galvanic Blast",
        ],
        sideboard=[
            "2 Blood Moon",
            "3 Leyline of the Void",
        ],
    )


def _mock_tournaments() -> list[SpicerackTournament]:
    """Create test tournament data for Spicerack fallback."""
    return [
        SpicerackTournament(
            tournament_id="3001",
            name="Modern Challenge #1",
            format="Modern",
            date="2026-03-20",
            player_count=64,
            rounds_swiss=6,
            top_cut=8,
            standings=[
                SpicerackStanding(
                    rank=1,
                    player_name="Alice",
                    wins=6,
                    losses=0,
                    decklist_url="https://moxfield.com/decks/a1",
                ),
                SpicerackStanding(
                    rank=2,
                    player_name="Bob",
                    wins=5,
                    losses=1,
                    decklist_url="https://moxfield.com/decks/b2",
                ),
            ],
        ),
        SpicerackTournament(
            tournament_id="3002",
            name="Modern Challenge #2",
            format="Modern",
            date="2026-03-22",
            player_count=48,
            rounds_swiss=5,
            top_cut=8,
            standings=[],
        ),
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_mtggoldfish() -> AsyncMock:
    """Mock MTGGoldfishClient."""
    client = AsyncMock()
    client.get_metagame = AsyncMock(return_value=_mock_snapshot())
    client.get_archetype = AsyncMock(return_value=_mock_archetype_detail())
    return client


@pytest.fixture
def mock_spicerack() -> AsyncMock:
    """Mock SpicerackClient."""
    client = AsyncMock()
    client.get_tournaments = AsyncMock(return_value=_mock_tournaments())
    return client


@pytest.fixture
def mock_bulk() -> AsyncMock:
    """Mock ScryfallBulkClient."""
    client = AsyncMock()
    client.get_cards = AsyncMock(
        return_value={
            "Lightning Bolt": _mock_card("Lightning Bolt", price_usd="1.50"),
            "Ragavan, Nimble Pilferer": _mock_card("Ragavan, Nimble Pilferer", price_usd="55.00"),
            "Goblin Guide": _mock_card("Goblin Guide", price_usd="3.00"),
            "Galvanic Blast": _mock_card("Galvanic Blast", price_usd="0.50"),
        }
    )
    client.filter_cards = AsyncMock(
        return_value=[
            _mock_card("Lightning Bolt"),
            _mock_card("Fatal Push", price_usd="2.00"),
        ]
    )
    return client


# ---------------------------------------------------------------------------
# _match_archetype tests
# ---------------------------------------------------------------------------


class TestMatchArchetype:
    """Tests for fuzzy archetype matching."""

    def test_exact_match(self) -> None:
        archetypes = _mock_archetypes()
        result = _match_archetype("Boros Energy", archetypes)
        assert result is not None
        assert result.name == "Boros Energy"

    def test_case_insensitive_match(self) -> None:
        archetypes = _mock_archetypes()
        result = _match_archetype("boros energy", archetypes)
        assert result is not None
        assert result.name == "Boros Energy"

    def test_substring_match(self) -> None:
        archetypes = _mock_archetypes()
        result = _match_archetype("Boros", archetypes)
        assert result is not None
        assert result.name == "Boros Energy"

    def test_word_overlap_match(self) -> None:
        archetypes = _mock_archetypes()
        result = _match_archetype("Control Azorius", archetypes)
        assert result is not None
        # Should match Azorius Control via word overlap
        assert "Control" in result.name

    def test_no_match(self) -> None:
        archetypes = _mock_archetypes()
        result = _match_archetype("Totally Nonexistent Deck", archetypes)
        assert result is None

    def test_empty_archetypes(self) -> None:
        result = _match_archetype("Boros Energy", [])
        assert result is None


# ---------------------------------------------------------------------------
# _classify_tiers tests
# ---------------------------------------------------------------------------


class TestClassifyTiers:
    """Tests for tier classification logic."""

    def test_tier_assignment(self) -> None:
        archetypes = _mock_archetypes()
        tiers = _classify_tiers(archetypes)

        # Boros Energy (20.3%) should be T1
        t1_names = [a.name for a in tiers["T1"]]
        assert "Boros Energy" in t1_names

        # Azorius Control (8.5%) and Mono-Red Aggro (5.1%) should be T2
        t2_names = [a.name for a in tiers["T2"]]
        assert "Azorius Control" in t2_names
        assert "Mono-Red Aggro" in t2_names

        # Jeskai Control (2.0%) and Golgari Midrange (1.5%) should be T3
        t3_names = [a.name for a in tiers["T3"]]
        assert "Jeskai Control" in t3_names
        assert "Golgari Midrange" in t3_names

    def test_boundary_values(self) -> None:
        archetypes = [
            GoldfishArchetype(name="Exactly10", slug="x", meta_share=10.0),
            GoldfishArchetype(name="Over10", slug="y", meta_share=10.1),
            GoldfishArchetype(name="Exactly3", slug="z", meta_share=3.0),
            GoldfishArchetype(name="Under3", slug="w", meta_share=2.9),
        ]
        tiers = _classify_tiers(archetypes)

        # 10.0 is not > 10.0, so T2
        assert len(tiers["T1"]) == 1
        assert tiers["T1"][0].name == "Over10"

        # 10.0 and 3.0 are T2 (>= 3.0 and <= 10.0)
        t2_names = [a.name for a in tiers["T2"]]
        assert "Exactly10" in t2_names
        assert "Exactly3" in t2_names

        # 2.9 is T3
        assert len(tiers["T3"]) == 1
        assert tiers["T3"][0].name == "Under3"


# ---------------------------------------------------------------------------
# metagame_snapshot tests
# ---------------------------------------------------------------------------


class TestMetagameSnapshot:
    """Tests for the metagame_snapshot workflow."""

    @pytest.mark.anyio
    async def test_mtggoldfish_primary_path(self, mock_mtggoldfish: AsyncMock) -> None:
        result = await metagame_snapshot(
            "modern",
            mtggoldfish=mock_mtggoldfish,
            spicerack=None,
            bulk=None,
        )

        assert "Modern Metagame" in result.markdown
        assert "Boros Energy" in result.markdown
        assert "MTGGoldfish" in result.markdown
        assert result.data["source"] == "mtggoldfish"
        assert result.data["format"] == "modern"
        assert len(result.data["tiers"]["T1"]) >= 1

    @pytest.mark.anyio
    async def test_mtggoldfish_concise_format(self, mock_mtggoldfish: AsyncMock) -> None:
        result = await metagame_snapshot(
            "modern",
            mtggoldfish=mock_mtggoldfish,
            spicerack=None,
            bulk=None,
            response_format="concise",
        )

        assert "Boros Energy" in result.markdown
        # Concise should not have Data Sources footer
        assert "Data Sources" not in result.markdown

    @pytest.mark.anyio
    async def test_spicerack_fallback(
        self,
        mock_spicerack: AsyncMock,
    ) -> None:
        result = await metagame_snapshot(
            "modern",
            mtggoldfish=None,
            spicerack=mock_spicerack,
            bulk=None,
        )

        assert "Tournament Data" in result.markdown
        assert result.data["source"] == "spicerack"

    @pytest.mark.anyio
    async def test_mtggoldfish_failure_falls_back_to_spicerack(
        self,
        mock_mtggoldfish: AsyncMock,
        mock_spicerack: AsyncMock,
    ) -> None:
        mock_mtggoldfish.get_metagame.side_effect = RuntimeError("scrape failed")

        result = await metagame_snapshot(
            "modern",
            mtggoldfish=mock_mtggoldfish,
            spicerack=mock_spicerack,
            bulk=None,
        )

        assert result.data["source"] == "spicerack"

    @pytest.mark.anyio
    async def test_no_sources_available(self) -> None:
        result = await metagame_snapshot(
            "modern",
            mtggoldfish=None,
            spicerack=None,
            bulk=None,
        )

        assert "No metagame data available" in result.markdown
        assert result.data["source"] is None

    @pytest.mark.anyio
    async def test_both_sources_fail(
        self,
        mock_mtggoldfish: AsyncMock,
        mock_spicerack: AsyncMock,
    ) -> None:
        mock_mtggoldfish.get_metagame.side_effect = RuntimeError("scrape failed")
        mock_spicerack.get_tournaments.side_effect = RuntimeError("api down")

        result = await metagame_snapshot(
            "modern",
            mtggoldfish=mock_mtggoldfish,
            spicerack=mock_spicerack,
            bulk=None,
        )

        assert "No metagame data available" in result.markdown
        assert result.data["source"] is None

    @pytest.mark.anyio
    async def test_structured_data_includes_tiers(self, mock_mtggoldfish: AsyncMock) -> None:
        result = await metagame_snapshot(
            "modern",
            mtggoldfish=mock_mtggoldfish,
            spicerack=None,
            bulk=None,
        )

        tiers = result.data["tiers"]
        assert "T1" in tiers
        assert "T2" in tiers
        assert "T3" in tiers
        # T1 should have Boros Energy (20.3%)
        t1_names = [a["name"] for a in tiers["T1"]]
        assert "Boros Energy" in t1_names

    @pytest.mark.anyio
    async def test_spicerack_empty_tournaments(
        self,
        mock_spicerack: AsyncMock,
    ) -> None:
        mock_spicerack.get_tournaments.return_value = []

        result = await metagame_snapshot(
            "modern",
            mtggoldfish=None,
            spicerack=mock_spicerack,
            bulk=None,
        )

        # Empty tournaments should fall through to no-sources
        assert "No metagame data available" in result.markdown


# ---------------------------------------------------------------------------
# archetype_decklist tests
# ---------------------------------------------------------------------------


class TestArchetypeDecklist:
    """Tests for the archetype_decklist workflow."""

    @pytest.mark.anyio
    async def test_success_path(
        self,
        mock_mtggoldfish: AsyncMock,
        mock_bulk: AsyncMock,
    ) -> None:
        result = await archetype_decklist(
            "modern",
            "Boros Energy",
            mtggoldfish=mock_mtggoldfish,
            bulk=mock_bulk,
        )

        assert "Boros Energy" in result.markdown
        assert "Lightning Bolt" in result.markdown
        assert "Mainboard" in result.markdown
        assert "Sideboard" in result.markdown
        assert result.data["archetype"] == "Boros Energy"
        assert result.data["slug"] == "boros-energy"
        assert len(result.data["mainboard"]) > 0

    @pytest.mark.anyio
    async def test_fuzzy_match_archetype(
        self,
        mock_mtggoldfish: AsyncMock,
    ) -> None:
        result = await archetype_decklist(
            "modern",
            "boros",
            mtggoldfish=mock_mtggoldfish,
            bulk=None,
        )

        assert "Boros Energy" in result.markdown
        assert result.data["archetype"] == "Boros Energy"

    @pytest.mark.anyio
    async def test_archetype_not_found(
        self,
        mock_mtggoldfish: AsyncMock,
    ) -> None:
        result = await archetype_decklist(
            "modern",
            "Totally Fake Deck",
            mtggoldfish=mock_mtggoldfish,
            bulk=None,
        )

        assert "not found" in result.markdown
        assert "Available archetypes" in result.markdown
        assert result.data["error"] == "not_found"

    @pytest.mark.anyio
    async def test_with_bulk_pricing(
        self,
        mock_mtggoldfish: AsyncMock,
        mock_bulk: AsyncMock,
    ) -> None:
        result = await archetype_decklist(
            "modern",
            "Boros Energy",
            mtggoldfish=mock_mtggoldfish,
            bulk=mock_bulk,
        )

        assert result.data["total_price"] is not None
        assert result.data["total_price"] > 0

    @pytest.mark.anyio
    async def test_without_bulk_pricing(
        self,
        mock_mtggoldfish: AsyncMock,
    ) -> None:
        result = await archetype_decklist(
            "modern",
            "Boros Energy",
            mtggoldfish=mock_mtggoldfish,
            bulk=None,
        )

        assert result.data["total_price"] is None

    @pytest.mark.anyio
    async def test_bulk_pricing_failure_degrades_gracefully(
        self,
        mock_mtggoldfish: AsyncMock,
        mock_bulk: AsyncMock,
    ) -> None:
        mock_bulk.get_cards.side_effect = RuntimeError("bulk data unavailable")

        result = await archetype_decklist(
            "modern",
            "Boros Energy",
            mtggoldfish=mock_mtggoldfish,
            bulk=mock_bulk,
        )

        # Should still succeed with no price
        assert "Boros Energy" in result.markdown
        assert result.data["total_price"] is None

    @pytest.mark.anyio
    async def test_concise_format(
        self,
        mock_mtggoldfish: AsyncMock,
    ) -> None:
        result = await archetype_decklist(
            "modern",
            "Boros Energy",
            mtggoldfish=mock_mtggoldfish,
            bulk=None,
            response_format="concise",
        )

        # Concise should skip metadata and Data Sources
        assert "Data Sources" not in result.markdown
        # But still show the decklist
        assert "Lightning Bolt" in result.markdown

    @pytest.mark.anyio
    async def test_uses_slug_not_name_for_get_archetype(
        self,
        mock_mtggoldfish: AsyncMock,
    ) -> None:
        """Verify we pass the slug to get_archetype, not the raw name."""
        await archetype_decklist(
            "modern",
            "Boros Energy",
            mtggoldfish=mock_mtggoldfish,
            bulk=None,
        )

        # get_archetype should be called with the slug from metagame data
        mock_mtggoldfish.get_archetype.assert_called_once_with("modern", "boros-energy")

    @pytest.mark.anyio
    async def test_structured_data_fields(
        self,
        mock_mtggoldfish: AsyncMock,
    ) -> None:
        result = await archetype_decklist(
            "modern",
            "Boros Energy",
            mtggoldfish=mock_mtggoldfish,
            bulk=None,
        )

        assert result.data["format"] == "modern"
        assert result.data["archetype"] == "Boros Energy"
        assert result.data["author"] == "TestPlayer"
        assert result.data["event"] == "Modern Challenge"
        assert result.data["result"] == "1st"
        assert isinstance(result.data["mainboard"], list)
        assert isinstance(result.data["sideboard"], list)


# ---------------------------------------------------------------------------
# archetype_comparison tests
# ---------------------------------------------------------------------------


class TestArchetypeComparison:
    """Tests for the archetype_comparison workflow."""

    @pytest.mark.anyio
    async def test_success_path(
        self,
        mock_mtggoldfish: AsyncMock,
    ) -> None:
        result = await archetype_comparison(
            "modern",
            ["Boros Energy", "Azorius Control"],
            mtggoldfish=mock_mtggoldfish,
            bulk=None,
        )

        assert "Archetype Comparison" in result.markdown
        assert "Boros Energy" in result.markdown
        assert "Azorius Control" in result.markdown
        assert "Meta Share" in result.markdown
        assert len(result.data["archetypes"]) == 2

    @pytest.mark.anyio
    async def test_insufficient_matches(
        self,
        mock_mtggoldfish: AsyncMock,
    ) -> None:
        result = await archetype_comparison(
            "modern",
            ["Nonexistent Deck A", "Nonexistent Deck B"],
            mtggoldfish=mock_mtggoldfish,
            bulk=None,
        )

        assert "Could not match enough" in result.markdown
        assert result.data["error"] == "insufficient_matches"

    @pytest.mark.anyio
    async def test_one_match_one_miss(
        self,
        mock_mtggoldfish: AsyncMock,
    ) -> None:
        result = await archetype_comparison(
            "modern",
            ["Boros Energy", "Nonexistent Deck"],
            mtggoldfish=mock_mtggoldfish,
            bulk=None,
        )

        # Only 1 match found — insufficient for comparison
        assert "Could not match enough" in result.markdown

    @pytest.mark.anyio
    async def test_shared_staples_detected(
        self,
        mock_mtggoldfish: AsyncMock,
    ) -> None:
        """Verify shared staples are found when decks share cards."""
        # Make both archetypes return decklists with shared cards
        detail_a = GoldfishArchetypeDetail(
            name="Boros Energy",
            mainboard=["4 Lightning Bolt", "4 Ragavan, Nimble Pilferer"],
            sideboard=[],
        )
        detail_b = GoldfishArchetypeDetail(
            name="Azorius Control",
            mainboard=["4 Lightning Bolt", "4 Counterspell"],
            sideboard=[],
        )
        mock_mtggoldfish.get_archetype.side_effect = [detail_a, detail_b]

        result = await archetype_comparison(
            "modern",
            ["Boros Energy", "Azorius Control"],
            mtggoldfish=mock_mtggoldfish,
            bulk=None,
        )

        assert "Shared Staples" in result.markdown
        assert "Lightning Bolt" in result.markdown

    @pytest.mark.anyio
    async def test_fetch_failure_partial(
        self,
        mock_mtggoldfish: AsyncMock,
    ) -> None:
        """One archetype fetch fails — should show N/A for that archetype."""
        detail_a = _mock_archetype_detail("Boros Energy")
        mock_mtggoldfish.get_archetype.side_effect = [
            detail_a,
            RuntimeError("fetch failed"),
        ]

        result = await archetype_comparison(
            "modern",
            ["Boros Energy", "Azorius Control"],
            mtggoldfish=mock_mtggoldfish,
            bulk=None,
        )

        assert "Boros Energy" in result.markdown
        assert "N/A" in result.markdown

    @pytest.mark.anyio
    async def test_concise_skips_shared_staples(
        self,
        mock_mtggoldfish: AsyncMock,
    ) -> None:
        detail_a = GoldfishArchetypeDetail(
            name="Boros Energy",
            mainboard=["4 Lightning Bolt"],
            sideboard=[],
        )
        detail_b = GoldfishArchetypeDetail(
            name="Azorius Control",
            mainboard=["4 Lightning Bolt"],
            sideboard=[],
        )
        mock_mtggoldfish.get_archetype.side_effect = [detail_a, detail_b]

        result = await archetype_comparison(
            "modern",
            ["Boros Energy", "Azorius Control"],
            mtggoldfish=mock_mtggoldfish,
            bulk=None,
            response_format="concise",
        )

        assert "Shared Staples" not in result.markdown

    @pytest.mark.anyio
    async def test_not_found_listed(
        self,
        mock_mtggoldfish: AsyncMock,
    ) -> None:
        """Partial match: 2 found + 1 not found."""
        result = await archetype_comparison(
            "modern",
            ["Boros Energy", "Azorius Control", "Nonexistent"],
            mtggoldfish=mock_mtggoldfish,
            bulk=None,
        )

        assert "Not found" in result.markdown
        assert "Nonexistent" in result.markdown
        assert "not_found" in result.data
        assert "Nonexistent" in result.data["not_found"]


# ---------------------------------------------------------------------------
# format_entry_guide tests
# ---------------------------------------------------------------------------


class TestFormatEntryGuide:
    """Tests for the format_entry_guide workflow."""

    @pytest.mark.anyio
    async def test_success_with_mtggoldfish(
        self,
        mock_mtggoldfish: AsyncMock,
        mock_bulk: AsyncMock,
    ) -> None:
        result = await format_entry_guide(
            "modern",
            mtggoldfish=mock_mtggoldfish,
            spicerack=None,
            bulk=mock_bulk,
        )

        assert "Modern Format Entry Guide" in result.markdown
        assert "Format Rules" in result.markdown
        assert "Archetypes by Budget" in result.markdown
        assert result.data["format"] == "modern"

    @pytest.mark.anyio
    async def test_format_rules_included(
        self,
        mock_mtggoldfish: AsyncMock,
    ) -> None:
        result = await format_entry_guide(
            "modern",
            mtggoldfish=mock_mtggoldfish,
            spicerack=None,
            bulk=None,
        )

        assert "60 cards" in result.markdown
        assert "15 cards" in result.markdown  # sideboard
        assert result.data["rules"] is not None
        assert result.data["rules"]["min_main"] == 60

    @pytest.mark.anyio
    async def test_budget_filter(
        self,
        mock_mtggoldfish: AsyncMock,
    ) -> None:
        result = await format_entry_guide(
            "modern",
            mtggoldfish=mock_mtggoldfish,
            spicerack=None,
            bulk=None,
            budget=200.0,
        )

        assert "under $200" in result.markdown
        assert result.data["budget"] == 200.0
        # Only Mono-Red Aggro ($150) should be under $200
        # Boros Energy ($350), Azorius Control ($500) should be excluded
        assert "Mono-Red Aggro" in result.markdown

    @pytest.mark.anyio
    async def test_budget_too_low(
        self,
        mock_mtggoldfish: AsyncMock,
    ) -> None:
        result = await format_entry_guide(
            "modern",
            mtggoldfish=mock_mtggoldfish,
            spicerack=None,
            bulk=None,
            budget=50.0,
        )

        assert (
            "No archetypes found" in result.markdown or "increasing your budget" in result.markdown
        )

    @pytest.mark.anyio
    async def test_recommended_first_deck(
        self,
        mock_mtggoldfish: AsyncMock,
    ) -> None:
        result = await format_entry_guide(
            "modern",
            mtggoldfish=mock_mtggoldfish,
            spicerack=None,
            bulk=None,
        )

        # Should recommend the cheapest deck
        assert "Recommended First Deck" in result.markdown
        assert "Mono-Red Aggro" in result.markdown

    @pytest.mark.anyio
    async def test_no_sources_available(self) -> None:
        result = await format_entry_guide(
            "modern",
            mtggoldfish=None,
            spicerack=None,
            bulk=None,
        )

        assert "Modern Format Entry Guide" in result.markdown
        assert "No metagame data available" in result.markdown

    @pytest.mark.anyio
    async def test_bulk_staples_section(
        self,
        mock_mtggoldfish: AsyncMock,
        mock_bulk: AsyncMock,
    ) -> None:
        result = await format_entry_guide(
            "modern",
            mtggoldfish=mock_mtggoldfish,
            spicerack=None,
            bulk=mock_bulk,
        )

        assert "Format Staples" in result.markdown
        assert "Lightning Bolt" in result.markdown

    @pytest.mark.anyio
    async def test_bulk_failure_degrades_gracefully(
        self,
        mock_mtggoldfish: AsyncMock,
        mock_bulk: AsyncMock,
    ) -> None:
        mock_bulk.filter_cards.side_effect = RuntimeError("bulk down")

        result = await format_entry_guide(
            "modern",
            mtggoldfish=mock_mtggoldfish,
            spicerack=None,
            bulk=mock_bulk,
        )

        # Should still succeed without staples section
        assert "Modern Format Entry Guide" in result.markdown
        assert "Format Staples" not in result.markdown

    @pytest.mark.anyio
    async def test_concise_format(
        self,
        mock_mtggoldfish: AsyncMock,
    ) -> None:
        result = await format_entry_guide(
            "modern",
            mtggoldfish=mock_mtggoldfish,
            spicerack=None,
            bulk=None,
            response_format="concise",
        )

        # Concise skips Format Rules and Data Sources
        assert "Format Rules" not in result.markdown
        assert "Data Sources" not in result.markdown

    @pytest.mark.anyio
    async def test_spicerack_fallback_in_guide(
        self,
        mock_spicerack: AsyncMock,
    ) -> None:
        result = await format_entry_guide(
            "modern",
            mtggoldfish=None,
            spicerack=mock_spicerack,
            bulk=None,
        )

        assert "Modern Format Entry Guide" in result.markdown
        assert "Tournament Activity" in result.markdown

    @pytest.mark.anyio
    async def test_structured_data_fields(
        self,
        mock_mtggoldfish: AsyncMock,
    ) -> None:
        result = await format_entry_guide(
            "modern",
            mtggoldfish=mock_mtggoldfish,
            spicerack=None,
            bulk=None,
            budget=1000.0,
        )

        assert result.data["format"] == "modern"
        assert result.data["source"] == "mtggoldfish"
        assert result.data["budget"] == 1000.0
        assert result.data["rules"] is not None
        assert isinstance(result.data["archetypes"], list)
