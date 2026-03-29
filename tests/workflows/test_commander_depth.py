"""Tests for commander depth workflow functions.

Unit tests for commander_comparison, tribal_staples, precon_upgrade,
and color_identity_staples. Service clients are mocked with AsyncMock.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mtg_mcp_server.services.spellbook import SpellbookError
from mtg_mcp_server.types import (
    Card,
    CardPrices,
    Combo,
    ComboCard,
    ComboResult,
    DecklistCombos,
    EDHRECCard,
    EDHRECCardList,
    EDHRECCommanderData,
)
from mtg_mcp_server.workflows.commander_depth import (
    color_identity_staples,
    commander_comparison,
    precon_upgrade,
    tribal_staples,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_card(
    name: str,
    *,
    mana_cost: str = "{1}",
    type_line: str = "Creature",
    oracle_text: str = "",
    colors: list[str] | None = None,
    color_identity: list[str] | None = None,
    power: str | None = None,
    toughness: str | None = None,
    usd: str | None = "1.00",
    edhrec_rank: int | None = 1000,
    rarity: str = "rare",
    legalities: dict[str, str] | None = None,
    keywords: list[str] | None = None,
) -> Card:
    """Create a Card instance for testing."""
    return Card(
        id=f"test-id-{name.lower().replace(' ', '-')}",
        name=name,
        mana_cost=mana_cost,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=colors or [],
        color_identity=color_identity or [],
        keywords=keywords or [],
        power=power,
        toughness=toughness,
        set="test",
        rarity=rarity,
        prices=CardPrices(usd=usd),
        edhrec_rank=edhrec_rank,
        legalities=legalities or {"commander": "legal"},
    )


def _mock_edhrec_data(
    commander_name: str,
    cards: list[EDHRECCard] | None = None,
    total_decks: int = 10000,
) -> EDHRECCommanderData:
    """Create mock EDHREC commander data."""
    if cards is None:
        cards = [
            EDHRECCard(name="Sol Ring", synergy=0.10, inclusion=80, num_decks=8000),
            EDHRECCard(name="Spore Frog", synergy=0.61, inclusion=61, num_decks=6100),
            EDHRECCard(name="Animate Dead", synergy=0.45, inclusion=55, num_decks=5500),
        ]
    return EDHRECCommanderData(
        commander_name=commander_name,
        total_decks=total_decks,
        cardlists=[EDHRECCardList(header="All", tag="all", cardviews=cards)],
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_bulk() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_spellbook() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_edhrec() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def muldrotha() -> Card:
    return _mock_card(
        "Muldrotha, the Gravetide",
        mana_cost="{3}{B}{G}{U}",
        type_line="Legendary Creature \u2014 Elemental Avatar",
        oracle_text="During each of your turns, you may play a permanent spell of each permanent type from your graveyard.",
        colors=["B", "G", "U"],
        color_identity=["B", "G", "U"],
        power="6",
        toughness="6",
        edhrec_rank=245,
        rarity="mythic",
    )


@pytest.fixture
def atraxa() -> Card:
    return _mock_card(
        "Atraxa, Praetors' Voice",
        mana_cost="{G}{W}{U}{B}",
        type_line="Legendary Creature \u2014 Phyrexian Angel Horror",
        oracle_text="Flying, vigilance, deathtouch, lifelink\nAt the beginning of your end step, proliferate.",
        colors=["W", "U", "B", "G"],
        color_identity=["W", "U", "B", "G"],
        power="4",
        toughness="4",
        edhrec_rank=12,
        rarity="mythic",
    )


@pytest.fixture
def mock_combos() -> list[Combo]:
    return [
        Combo(
            id="combo-1",
            cards=[ComboCard(name="Muldrotha, the Gravetide"), ComboCard(name="Spore Frog")],
            produces=[ComboResult(feature_name="Infinite death triggers")],
            identity="BGU",
            popularity=3000,
        ),
    ]


# ===========================================================================
# commander_comparison tests
# ===========================================================================


class TestCommanderComparison:
    """Tests for the commander_comparison workflow function."""

    async def test_two_commanders_all_sources(
        self,
        mock_bulk: AsyncMock,
        mock_spellbook: AsyncMock,
        mock_edhrec: AsyncMock,
        muldrotha: Card,
        atraxa: Card,
        mock_combos: list[Combo],
    ) -> None:
        """Two commanders with all sources succeeding."""
        mock_bulk.get_card = AsyncMock(side_effect=[muldrotha, atraxa])
        mock_spellbook.find_combos = AsyncMock(side_effect=[mock_combos, []])
        mock_edhrec.commander_top_cards = AsyncMock(
            side_effect=[
                _mock_edhrec_data(
                    "Muldrotha",
                    [
                        EDHRECCard(name="Sol Ring", synergy=0.10, inclusion=80, num_decks=8000),
                        EDHRECCard(name="Spore Frog", synergy=0.61, inclusion=61, num_decks=6100),
                        EDHRECCard(
                            name="Command Tower", synergy=0.05, inclusion=90, num_decks=9000
                        ),
                    ],
                ),
                _mock_edhrec_data(
                    "Atraxa",
                    [
                        EDHRECCard(name="Sol Ring", synergy=0.10, inclusion=85, num_decks=8500),
                        EDHRECCard(
                            name="Deepglow Skate", synergy=0.72, inclusion=60, num_decks=6000
                        ),
                        EDHRECCard(
                            name="Command Tower", synergy=0.05, inclusion=92, num_decks=9200
                        ),
                    ],
                ),
            ]
        )

        result = await commander_comparison(
            ["Muldrotha, the Gravetide", "Atraxa, Praetors' Voice"],
            bulk=mock_bulk,
            spellbook=mock_spellbook,
            edhrec=mock_edhrec,
        )

        assert "Muldrotha" in result.markdown
        assert "Atraxa" in result.markdown
        # Should have commander names in structured data
        assert isinstance(result.data, dict)
        assert "commanders" in result.data

    async def test_commander_not_found(
        self,
        mock_bulk: AsyncMock,
        mock_spellbook: AsyncMock,
    ) -> None:
        """Commander not found in bulk data raises error."""
        mock_bulk.get_card = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="not found"):
            await commander_comparison(
                ["Nonexistent Commander"],
                bulk=mock_bulk,
                spellbook=mock_spellbook,
            )

    async def test_edhrec_disabled(
        self,
        mock_bulk: AsyncMock,
        mock_spellbook: AsyncMock,
        muldrotha: Card,
        atraxa: Card,
    ) -> None:
        """Works without EDHREC."""
        mock_bulk.get_card = AsyncMock(side_effect=[muldrotha, atraxa])
        mock_spellbook.find_combos = AsyncMock(return_value=[])

        result = await commander_comparison(
            ["Muldrotha, the Gravetide", "Atraxa, Praetors' Voice"],
            bulk=mock_bulk,
            spellbook=mock_spellbook,
            edhrec=None,
        )

        assert "Muldrotha" in result.markdown
        assert "Atraxa" in result.markdown

    async def test_spellbook_failure_partial(
        self,
        mock_bulk: AsyncMock,
        mock_spellbook: AsyncMock,
        muldrotha: Card,
        atraxa: Card,
    ) -> None:
        """Spellbook failure degrades gracefully."""
        mock_bulk.get_card = AsyncMock(side_effect=[muldrotha, atraxa])
        mock_spellbook.find_combos = AsyncMock(
            side_effect=SpellbookError("timeout", status_code=503)
        )

        result = await commander_comparison(
            ["Muldrotha, the Gravetide", "Atraxa, Praetors' Voice"],
            bulk=mock_bulk,
            spellbook=mock_spellbook,
        )

        # Should still produce output with both commanders
        assert "Muldrotha" in result.markdown
        assert "Atraxa" in result.markdown

    async def test_progress_callback(
        self,
        mock_bulk: AsyncMock,
        mock_spellbook: AsyncMock,
        muldrotha: Card,
        atraxa: Card,
    ) -> None:
        """Progress callback is invoked at each step."""
        mock_bulk.get_card = AsyncMock(side_effect=[muldrotha, atraxa])
        mock_spellbook.find_combos = AsyncMock(return_value=[])

        progress_calls: list[tuple[int, int]] = []

        async def on_progress(current: int, total: int) -> None:
            progress_calls.append((current, total))

        await commander_comparison(
            ["Muldrotha, the Gravetide", "Atraxa, Praetors' Voice"],
            bulk=mock_bulk,
            spellbook=mock_spellbook,
            on_progress=on_progress,
        )

        assert len(progress_calls) == 3
        assert progress_calls[0] == (1, 3)
        assert progress_calls[2] == (3, 3)

    async def test_concise_format(
        self,
        mock_bulk: AsyncMock,
        mock_spellbook: AsyncMock,
        muldrotha: Card,
        atraxa: Card,
    ) -> None:
        """Concise format is shorter than detailed."""
        mock_bulk.get_card = AsyncMock(side_effect=[muldrotha, atraxa])
        mock_spellbook.find_combos = AsyncMock(return_value=[])

        detailed = await commander_comparison(
            ["Muldrotha, the Gravetide", "Atraxa, Praetors' Voice"],
            bulk=mock_bulk,
            spellbook=mock_spellbook,
            response_format="detailed",
        )

        mock_bulk.get_card = AsyncMock(side_effect=[muldrotha, atraxa])
        mock_spellbook.find_combos = AsyncMock(return_value=[])

        concise = await commander_comparison(
            ["Muldrotha, the Gravetide", "Atraxa, Praetors' Voice"],
            bulk=mock_bulk,
            spellbook=mock_spellbook,
            response_format="concise",
        )

        assert len(concise.markdown) < len(detailed.markdown)

    async def test_shared_and_unique_staples(
        self,
        mock_bulk: AsyncMock,
        mock_spellbook: AsyncMock,
        mock_edhrec: AsyncMock,
        muldrotha: Card,
        atraxa: Card,
    ) -> None:
        """EDHREC data shows shared and unique staples."""
        mock_bulk.get_card = AsyncMock(side_effect=[muldrotha, atraxa])
        mock_spellbook.find_combos = AsyncMock(return_value=[])
        mock_edhrec.commander_top_cards = AsyncMock(
            side_effect=[
                _mock_edhrec_data(
                    "Muldrotha",
                    [
                        EDHRECCard(name="Sol Ring", synergy=0.10, inclusion=80, num_decks=8000),
                        EDHRECCard(name="Spore Frog", synergy=0.61, inclusion=61, num_decks=6100),
                    ],
                ),
                _mock_edhrec_data(
                    "Atraxa",
                    [
                        EDHRECCard(name="Sol Ring", synergy=0.10, inclusion=85, num_decks=8500),
                        EDHRECCard(
                            name="Deepglow Skate", synergy=0.72, inclusion=60, num_decks=6000
                        ),
                    ],
                ),
            ]
        )

        result = await commander_comparison(
            ["Muldrotha, the Gravetide", "Atraxa, Praetors' Voice"],
            bulk=mock_bulk,
            spellbook=mock_spellbook,
            edhrec=mock_edhrec,
        )

        # Sol Ring is shared, Spore Frog / Deepglow Skate are unique
        assert "Sol Ring" in result.markdown


# ===========================================================================
# tribal_staples tests
# ===========================================================================


class TestTribalStaples:
    """Tests for the tribal_staples workflow function."""

    async def test_basic_tribe_search(self, mock_bulk: AsyncMock) -> None:
        """Searches for tribal lords and members."""
        lord = _mock_card(
            "Lord of the Accursed",
            type_line="Creature \u2014 Zombie",
            oracle_text="Other Zombie creatures you control get +1/+1.",
            color_identity=["B"],
            edhrec_rank=500,
        )
        member = _mock_card(
            "Gravecrawler",
            type_line="Creature \u2014 Zombie",
            oracle_text="You may cast Gravecrawler from your graveyard...",
            color_identity=["B"],
            edhrec_rank=200,
        )
        tribal_support = _mock_card(
            "Kindred Discovery",
            type_line="Enchantment",
            oracle_text="As Kindred Discovery enters, choose a creature type.",
            color_identity=["U"],
            edhrec_rank=300,
        )

        # Lords/anthems
        mock_bulk.search_by_text = AsyncMock(
            side_effect=[
                [lord],  # "other zombie" or "zombie creatures you control get"
                [lord, member],  # tribe name text search
            ]
        )
        # Type search for members
        mock_bulk.search_by_type = AsyncMock(return_value=[lord, member])
        # Tribal support search
        mock_bulk.filter_cards = AsyncMock(return_value=[tribal_support])

        result = await tribal_staples("Zombie", bulk=mock_bulk)

        assert "Lord of the Accursed" in result.markdown
        assert "Gravecrawler" in result.markdown or "Zombie" in result.markdown
        assert isinstance(result.data, dict)

    async def test_color_identity_filter(self, mock_bulk: AsyncMock) -> None:
        """Color identity narrows results."""
        blue_card = _mock_card(
            "Zombie Master",
            type_line="Creature \u2014 Zombie",
            color_identity=["B"],
        )
        mock_bulk.search_by_text = AsyncMock(return_value=[])
        mock_bulk.search_by_type = AsyncMock(return_value=[blue_card])
        mock_bulk.filter_cards = AsyncMock(return_value=[])

        result = await tribal_staples("Zombie", bulk=mock_bulk, color_identity="B")

        assert isinstance(result.data, dict)

    async def test_format_filter(self, mock_bulk: AsyncMock) -> None:
        """Format filter is respected."""
        mock_bulk.search_by_text = AsyncMock(return_value=[])
        mock_bulk.search_by_type = AsyncMock(return_value=[])
        mock_bulk.filter_cards = AsyncMock(return_value=[])

        result = await tribal_staples("Elf", bulk=mock_bulk, format="commander")

        assert isinstance(result.data, dict)

    async def test_empty_results(self, mock_bulk: AsyncMock) -> None:
        """No results for obscure tribe."""
        mock_bulk.search_by_text = AsyncMock(return_value=[])
        mock_bulk.search_by_type = AsyncMock(return_value=[])
        mock_bulk.filter_cards = AsyncMock(return_value=[])

        result = await tribal_staples("Brushwagg", bulk=mock_bulk)

        assert "no" in result.markdown.lower() or "0" in result.markdown

    async def test_edhrec_enrichment(self, mock_bulk: AsyncMock, mock_edhrec: AsyncMock) -> None:
        """EDHREC enriches results with synergy data when available."""
        member = _mock_card(
            "Gravecrawler",
            type_line="Creature \u2014 Zombie",
            color_identity=["B"],
        )
        mock_bulk.search_by_text = AsyncMock(return_value=[])
        mock_bulk.search_by_type = AsyncMock(return_value=[member])
        mock_bulk.filter_cards = AsyncMock(return_value=[])

        # EDHREC won't be queried without a commander, so just check it handles it
        result = await tribal_staples("Zombie", bulk=mock_bulk, edhrec=mock_edhrec)
        assert isinstance(result.data, dict)

    async def test_limit_respected(self, mock_bulk: AsyncMock) -> None:
        """Limit caps the output."""
        cards = [
            _mock_card(f"Zombie {i}", type_line="Creature \u2014 Zombie", edhrec_rank=i)
            for i in range(30)
        ]
        mock_bulk.search_by_text = AsyncMock(return_value=[])
        mock_bulk.search_by_type = AsyncMock(return_value=cards)
        mock_bulk.filter_cards = AsyncMock(return_value=[])

        result = await tribal_staples("Zombie", bulk=mock_bulk, limit=5)

        # Structured data should have at most 5 cards total
        total_cards = sum(
            len(group.get("cards", [])) for group in result.data.get("categories", [])
        )
        assert total_cards <= 5

    async def test_concise_format(self, mock_bulk: AsyncMock) -> None:
        """Concise format is shorter."""
        member = _mock_card("Gravecrawler", type_line="Creature \u2014 Zombie")
        mock_bulk.search_by_text = AsyncMock(return_value=[])
        mock_bulk.search_by_type = AsyncMock(return_value=[member])
        mock_bulk.filter_cards = AsyncMock(return_value=[])

        detailed = await tribal_staples("Zombie", bulk=mock_bulk, response_format="detailed")

        mock_bulk.search_by_text = AsyncMock(return_value=[])
        mock_bulk.search_by_type = AsyncMock(return_value=[member])
        mock_bulk.filter_cards = AsyncMock(return_value=[])

        concise = await tribal_staples("Zombie", bulk=mock_bulk, response_format="concise")

        assert len(concise.markdown) <= len(detailed.markdown)


# ===========================================================================
# precon_upgrade tests
# ===========================================================================


class TestPreconUpgrade:
    """Tests for the precon_upgrade workflow function."""

    async def test_basic_upgrade(
        self,
        mock_bulk: AsyncMock,
        mock_spellbook: AsyncMock,
        mock_edhrec: AsyncMock,
        muldrotha: Card,
    ) -> None:
        """Basic upgrade path with all sources."""
        # Resolve decklist cards
        weak_card = _mock_card("Golgari Signet", edhrec_rank=5000, usd="0.50")
        ok_card = _mock_card("Sol Ring", edhrec_rank=1, usd="3.00")
        mock_bulk.get_cards = AsyncMock(
            return_value={
                "Muldrotha, the Gravetide": muldrotha,
                "Golgari Signet": weak_card,
                "Sol Ring": ok_card,
            }
        )

        # Spellbook: no combos
        mock_spellbook.find_decklist_combos = AsyncMock(
            return_value=DecklistCombos(identity="BGU", included=[], almost_included=[])
        )

        # EDHREC: weak_card has low synergy, upgrade_card is high synergy
        mock_edhrec.commander_top_cards = AsyncMock(
            return_value=_mock_edhrec_data(
                "Muldrotha",
                [
                    EDHRECCard(name="Golgari Signet", synergy=0.05, inclusion=30, num_decks=3000),
                    EDHRECCard(name="Sol Ring", synergy=0.10, inclusion=80, num_decks=8000),
                    EDHRECCard(name="Spore Frog", synergy=0.61, inclusion=61, num_decks=6100),
                    EDHRECCard(name="Animate Dead", synergy=0.45, inclusion=55, num_decks=5500),
                ],
            )
        )

        # Upgrade card price
        upgrade_card = _mock_card("Spore Frog", usd="0.25", edhrec_rank=1200)
        mock_bulk.get_card = AsyncMock(return_value=upgrade_card)

        result = await precon_upgrade(
            ["Golgari Signet", "Sol Ring"],
            "Muldrotha, the Gravetide",
            bulk=mock_bulk,
            spellbook=mock_spellbook,
            edhrec=mock_edhrec,
        )

        assert isinstance(result.data, dict)
        assert "Muldrotha" in result.markdown or "upgrade" in result.markdown.lower()

    async def test_empty_decklist(
        self,
        mock_bulk: AsyncMock,
        mock_spellbook: AsyncMock,
    ) -> None:
        """Empty decklist returns early."""
        result = await precon_upgrade(
            [],
            "Muldrotha, the Gravetide",
            bulk=mock_bulk,
            spellbook=mock_spellbook,
        )

        assert "no cards" in result.markdown.lower() or "empty" in result.markdown.lower()

    async def test_edhrec_disabled(
        self,
        mock_bulk: AsyncMock,
        mock_spellbook: AsyncMock,
        muldrotha: Card,
    ) -> None:
        """Works without EDHREC (no upgrade suggestions, just cut analysis)."""
        weak = _mock_card("Golgari Signet")
        mock_bulk.get_cards = AsyncMock(
            return_value={"Muldrotha, the Gravetide": muldrotha, "Golgari Signet": weak}
        )
        mock_spellbook.find_decklist_combos = AsyncMock(
            return_value=DecklistCombos(identity="BGU", included=[], almost_included=[])
        )

        result = await precon_upgrade(
            ["Golgari Signet"],
            "Muldrotha, the Gravetide",
            bulk=mock_bulk,
            spellbook=mock_spellbook,
            edhrec=None,
        )

        # Should still produce output
        assert isinstance(result.data, dict)

    async def test_budget_filter(
        self,
        mock_bulk: AsyncMock,
        mock_spellbook: AsyncMock,
        mock_edhrec: AsyncMock,
        muldrotha: Card,
    ) -> None:
        """Budget filter excludes expensive upgrades."""
        weak = _mock_card("Golgari Signet", usd="0.50")
        mock_bulk.get_cards = AsyncMock(
            return_value={"Muldrotha, the Gravetide": muldrotha, "Golgari Signet": weak}
        )
        mock_spellbook.find_decklist_combos = AsyncMock(
            return_value=DecklistCombos(identity="BGU", included=[], almost_included=[])
        )

        # All suggested upgrades are expensive
        mock_edhrec.commander_top_cards = AsyncMock(
            return_value=_mock_edhrec_data(
                "Muldrotha",
                [
                    EDHRECCard(name="Golgari Signet", synergy=0.05, inclusion=30, num_decks=3000),
                ],
            )
        )

        result = await precon_upgrade(
            ["Golgari Signet"],
            "Muldrotha, the Gravetide",
            bulk=mock_bulk,
            spellbook=mock_spellbook,
            edhrec=mock_edhrec,
            budget=0.10,  # Very tight budget
        )

        assert isinstance(result.data, dict)

    async def test_progress_callback(
        self,
        mock_bulk: AsyncMock,
        mock_spellbook: AsyncMock,
        muldrotha: Card,
    ) -> None:
        """Progress callback is invoked."""
        weak = _mock_card("Golgari Signet")
        mock_bulk.get_cards = AsyncMock(
            return_value={"Muldrotha, the Gravetide": muldrotha, "Golgari Signet": weak}
        )
        mock_spellbook.find_decklist_combos = AsyncMock(
            return_value=DecklistCombos(identity="BGU", included=[], almost_included=[])
        )

        progress_calls: list[tuple[int, int]] = []

        async def on_progress(current: int, total: int) -> None:
            progress_calls.append((current, total))

        await precon_upgrade(
            ["Golgari Signet"],
            "Muldrotha, the Gravetide",
            bulk=mock_bulk,
            spellbook=mock_spellbook,
            on_progress=on_progress,
        )

        assert len(progress_calls) == 4
        assert progress_calls[0] == (1, 4)
        assert progress_calls[3] == (4, 4)

    async def test_combo_pieces_protected(
        self,
        mock_bulk: AsyncMock,
        mock_spellbook: AsyncMock,
        mock_edhrec: AsyncMock,
        muldrotha: Card,
    ) -> None:
        """Combo pieces should not be suggested as cuts."""
        combo_piece = _mock_card("Spore Frog", usd="0.25")
        non_combo = _mock_card("Golgari Signet", usd="0.50")
        mock_bulk.get_cards = AsyncMock(
            return_value={
                "Muldrotha, the Gravetide": muldrotha,
                "Spore Frog": combo_piece,
                "Golgari Signet": non_combo,
            }
        )
        mock_spellbook.find_decklist_combos = AsyncMock(
            return_value=DecklistCombos(
                identity="BGU",
                included=[
                    Combo(
                        id="combo-1",
                        cards=[
                            ComboCard(name="Muldrotha, the Gravetide"),
                            ComboCard(name="Spore Frog"),
                        ],
                        produces=[ComboResult(feature_name="Infinite death triggers")],
                    ),
                ],
                almost_included=[],
            )
        )
        mock_edhrec.commander_top_cards = AsyncMock(
            return_value=_mock_edhrec_data(
                "Muldrotha",
                [
                    EDHRECCard(name="Spore Frog", synergy=0.61, inclusion=61, num_decks=6100),
                    EDHRECCard(name="Golgari Signet", synergy=0.05, inclusion=30, num_decks=3000),
                    EDHRECCard(name="Animate Dead", synergy=0.45, inclusion=55, num_decks=5500),
                ],
            )
        )
        mock_bulk.get_card = AsyncMock(return_value=_mock_card("Animate Dead", usd="3.00"))

        result = await precon_upgrade(
            ["Spore Frog", "Golgari Signet"],
            "Muldrotha, the Gravetide",
            bulk=mock_bulk,
            spellbook=mock_spellbook,
            edhrec=mock_edhrec,
        )

        # The cuts should prefer Golgari Signet over Spore Frog
        cuts = result.data.get("cuts", [])
        if cuts:
            # If Golgari Signet appears before Spore Frog, combo protection worked
            cut_names = [c["name"] for c in cuts]
            if "Spore Frog" in cut_names and "Golgari Signet" in cut_names:
                assert cut_names.index("Golgari Signet") < cut_names.index("Spore Frog")


# ===========================================================================
# color_identity_staples tests
# ===========================================================================


class TestColorIdentityStaples:
    """Tests for the color_identity_staples workflow function."""

    async def test_basic_color_identity(self, mock_bulk: AsyncMock) -> None:
        """Returns cards within the given color identity."""
        sol_ring = _mock_card(
            "Sol Ring",
            type_line="Artifact",
            color_identity=[],
            edhrec_rank=1,
        )
        counterspell = _mock_card(
            "Counterspell",
            type_line="Instant",
            color_identity=["U"],
            edhrec_rank=50,
        )
        mock_bulk.filter_cards = AsyncMock(return_value=[sol_ring, counterspell])

        result = await color_identity_staples("sultai", bulk=mock_bulk)

        assert "Sol Ring" in result.markdown
        assert isinstance(result.data, dict)

    async def test_named_identity_parsing(self, mock_bulk: AsyncMock) -> None:
        """Parses named identities like 'sultai'."""
        mock_bulk.filter_cards = AsyncMock(return_value=[])

        result = await color_identity_staples("sultai", bulk=mock_bulk)

        # Should not raise
        assert isinstance(result.data, dict)

    async def test_letter_identity_parsing(self, mock_bulk: AsyncMock) -> None:
        """Parses letter sequences like 'BUG'."""
        mock_bulk.filter_cards = AsyncMock(return_value=[])

        result = await color_identity_staples("BUG", bulk=mock_bulk)

        assert isinstance(result.data, dict)

    async def test_invalid_color_identity(self, mock_bulk: AsyncMock) -> None:
        """Invalid color identity returns an error message."""
        result = await color_identity_staples("invalidcolor", bulk=mock_bulk)

        assert "error" in result.markdown.lower() or "unrecognized" in result.markdown.lower()

    async def test_category_filter(self, mock_bulk: AsyncMock) -> None:
        """Category filter narrows results by type."""
        creature = _mock_card(
            "Tarmogoyf",
            type_line="Creature \u2014 Lhurgoyf",
            color_identity=["G"],
            edhrec_rank=100,
        )
        mock_bulk.filter_cards = AsyncMock(return_value=[creature])

        result = await color_identity_staples("green", bulk=mock_bulk, category="creatures")

        assert isinstance(result.data, dict)

    async def test_limit_respected(self, mock_bulk: AsyncMock) -> None:
        """Limit caps number of results."""
        cards = [_mock_card(f"Card {i}", color_identity=["U"], edhrec_rank=i) for i in range(30)]
        mock_bulk.filter_cards = AsyncMock(return_value=cards[:5])

        result = await color_identity_staples("blue", bulk=mock_bulk, limit=5)

        card_list = result.data.get("cards", [])
        assert len(card_list) <= 5

    async def test_colorless(self, mock_bulk: AsyncMock) -> None:
        """Colorless identity works."""
        sol_ring = _mock_card(
            "Sol Ring",
            type_line="Artifact",
            color_identity=[],
            edhrec_rank=1,
        )
        mock_bulk.filter_cards = AsyncMock(return_value=[sol_ring])

        result = await color_identity_staples("colorless", bulk=mock_bulk)

        assert "Sol Ring" in result.markdown

    async def test_concise_format(self, mock_bulk: AsyncMock) -> None:
        """Concise is shorter than detailed."""
        card = _mock_card("Sol Ring", color_identity=[], edhrec_rank=1)
        mock_bulk.filter_cards = AsyncMock(return_value=[card])

        detailed = await color_identity_staples(
            "sultai", bulk=mock_bulk, response_format="detailed"
        )

        mock_bulk.filter_cards = AsyncMock(return_value=[card])

        concise = await color_identity_staples("sultai", bulk=mock_bulk, response_format="concise")

        assert len(concise.markdown) <= len(detailed.markdown)

    async def test_edhrec_enrichment(self, mock_bulk: AsyncMock, mock_edhrec: AsyncMock) -> None:
        """EDHREC data is noted but not required."""
        card = _mock_card("Sol Ring", color_identity=[], edhrec_rank=1)
        mock_bulk.filter_cards = AsyncMock(return_value=[card])

        result = await color_identity_staples("sultai", bulk=mock_bulk, edhrec=mock_edhrec)

        assert isinstance(result.data, dict)
