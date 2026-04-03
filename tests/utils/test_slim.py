"""Tests for slim dict-builder functions.

Each slim function extracts essential fields from a Pydantic model,
dropping bloat fields (legalities, image URIs, etc.) to reduce
structured_content response sizes.
"""

import pytest

from mtg_mcp_server.types import (
    Card,
    CardImageUris,
    CardPrices,
    Combo,
    ComboCard,
    ComboResult,
    DraftCardRating,
    EDHRECCard,
    Rule,
)
from mtg_mcp_server.utils.slim import (
    slim_card,
    slim_combo,
    slim_edhrec_card,
    slim_rating,
    slim_rule,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_card() -> Card:
    return Card(
        id="abc-123",
        name="Muldrotha, the Gravetide",
        mana_cost="{3}{B}{G}{U}",
        cmc=6.0,
        type_line="Legendary Creature — Elemental Avatar",
        oracle_text="During each of your turns, you may play...",
        colors=["B", "G", "U"],
        color_identity=["B", "G", "U"],
        keywords=["Vigilance"],
        power="6",
        toughness="6",
        set_code="dom",
        collector_number="199",
        rarity="mythic",
        layout="normal",
        prices=CardPrices(usd="5.50", usd_foil="12.00", eur="4.80"),
        legalities={"commander": "legal", "standard": "not_legal", "modern": "legal"},
        image_uris=CardImageUris(normal="https://img.scryfall.com/normal.jpg"),
        scryfall_uri="https://scryfall.com/card/dom/199",
        edhrec_rank=245,
        rulings_uri="https://api.scryfall.com/cards/abc/rulings",
    )


@pytest.fixture
def sample_rating() -> DraftCardRating:
    return DraftCardRating(
        name="Nameless Inversion",
        color="B",
        rarity="common",
        seen_count=12500,
        avg_seen=4.2,
        pick_count=8300,
        avg_pick=2.1,
        game_count=15000,
        play_rate=0.85,
        win_rate=0.572,
        opening_hand_win_rate=0.591,
        drawn_win_rate=0.583,
        ever_drawn_win_rate=0.587,
        never_drawn_win_rate=0.554,
        drawn_improvement_win_rate=0.033,
    )


@pytest.fixture
def sample_edhrec_card() -> EDHRECCard:
    return EDHRECCard(
        name="Spore Frog",
        sanitized="spore-frog",
        synergy=0.61,
        inclusion=61,
        num_decks=12050,
    )


@pytest.fixture
def sample_combo() -> Combo:
    return Combo(
        id="1414-2730",
        status="OK",
        cards=[
            ComboCard(name="Muldrotha, the Gravetide", zone_locations=["C"]),
            ComboCard(name="Spore Frog", zone_locations=["B"]),
        ],
        produces=[
            ComboResult(feature_name="Infinite death triggers"),
            ComboResult(feature_name="Infinite ETB"),
        ],
        identity="BGU",
        mana_needed="{2}{B}{G}{U}",
        description="Step 1: ...",
        easy_prerequisites="All permanents on the battlefield.",
        popularity=3382,
        bracket_tag="E",
        legalities={"commander": True},
        prices={"tcgplayer": "63.22"},
    )


# ---------------------------------------------------------------------------
# slim_card
# ---------------------------------------------------------------------------


class TestSlimCard:
    def test_includes_essential_fields(self, sample_card: Card) -> None:
        result = slim_card(sample_card)
        assert result["name"] == "Muldrotha, the Gravetide"
        assert result["mana_cost"] == "{3}{B}{G}{U}"
        assert result["type_line"] == "Legendary Creature — Elemental Avatar"
        assert result["rarity"] == "mythic"
        assert result["price_usd"] == "5.50"
        assert result["edhrec_rank"] == 245

    def test_excludes_bloat_fields(self, sample_card: Card) -> None:
        result = slim_card(sample_card)
        assert "id" not in result
        assert "oracle_text" not in result
        assert "colors" not in result
        assert "color_identity" not in result
        assert "keywords" not in result
        assert "power" not in result
        assert "toughness" not in result
        assert "set_code" not in result
        assert "collector_number" not in result
        assert "layout" not in result
        assert "legalities" not in result
        assert "image_uris" not in result
        assert "scryfall_uri" not in result
        assert "rulings_uri" not in result
        assert "cmc" not in result

    def test_handles_none_prices(self) -> None:
        card = Card(id="x", name="Test Card", prices=CardPrices())
        result = slim_card(card)
        assert result["price_usd"] is None

    def test_handles_none_edhrec_rank(self) -> None:
        card = Card(id="x", name="Test Card")
        result = slim_card(card)
        assert result["edhrec_rank"] is None

    def test_field_count(self, sample_card: Card) -> None:
        result = slim_card(sample_card)
        assert len(result) == 6


# ---------------------------------------------------------------------------
# slim_rating
# ---------------------------------------------------------------------------


class TestSlimRating:
    def test_includes_essential_fields(self, sample_rating: DraftCardRating) -> None:
        result = slim_rating(sample_rating)
        assert result["name"] == "Nameless Inversion"
        assert result["color"] == "B"
        assert result["rarity"] == "common"
        assert result["gih_wr"] == 0.587
        assert result["alsa"] == 4.2
        assert result["iwd"] == 0.033
        assert result["game_count"] == 15000

    def test_excludes_bloat_fields(self, sample_rating: DraftCardRating) -> None:
        result = slim_rating(sample_rating)
        assert "seen_count" not in result
        assert "pick_count" not in result
        assert "avg_pick" not in result
        assert "play_rate" not in result
        assert "win_rate" not in result
        assert "opening_hand_win_rate" not in result
        assert "drawn_win_rate" not in result
        assert "never_drawn_win_rate" not in result

    def test_handles_none_values(self) -> None:
        rating = DraftCardRating(name="Test", color="W", rarity="common")
        result = slim_rating(rating)
        assert result["gih_wr"] is None
        assert result["alsa"] is None
        assert result["iwd"] is None

    def test_field_count(self, sample_rating: DraftCardRating) -> None:
        result = slim_rating(sample_rating)
        assert len(result) == 7


# ---------------------------------------------------------------------------
# slim_edhrec_card
# ---------------------------------------------------------------------------


class TestSlimEdhrecCard:
    def test_includes_essential_fields(self, sample_edhrec_card: EDHRECCard) -> None:
        result = slim_edhrec_card(sample_edhrec_card)
        assert result["name"] == "Spore Frog"
        assert result["synergy"] == 0.61
        assert result["inclusion"] == 61
        assert result["num_decks"] == 12050

    def test_excludes_bloat_fields(self, sample_edhrec_card: EDHRECCard) -> None:
        result = slim_edhrec_card(sample_edhrec_card)
        assert "sanitized" not in result
        assert "potential_decks" not in result
        assert "label" not in result

    def test_field_count(self, sample_edhrec_card: EDHRECCard) -> None:
        result = slim_edhrec_card(sample_edhrec_card)
        assert len(result) == 4


# ---------------------------------------------------------------------------
# slim_combo
# ---------------------------------------------------------------------------


class TestSlimCombo:
    def test_includes_essential_fields(self, sample_combo: Combo) -> None:
        result = slim_combo(sample_combo)
        assert result["id"] == "1414-2730"
        assert result["cards"] == ["Muldrotha, the Gravetide", "Spore Frog"]
        assert result["results"] == ["Infinite death triggers", "Infinite ETB"]
        assert result["color_identity"] == "BGU"

    def test_excludes_bloat_fields(self, sample_combo: Combo) -> None:
        result = slim_combo(sample_combo)
        assert "status" not in result
        assert "mana_needed" not in result
        assert "description" not in result
        assert "easy_prerequisites" not in result
        assert "notable_prerequisites" not in result
        assert "popularity" not in result
        assert "bracket_tag" not in result
        assert "legalities" not in result
        assert "prices" not in result

    def test_extracts_card_names_not_objects(self, sample_combo: Combo) -> None:
        result = slim_combo(sample_combo)
        for card_name in result["cards"]:
            assert isinstance(card_name, str)

    def test_extracts_result_feature_names(self, sample_combo: Combo) -> None:
        result = slim_combo(sample_combo)
        for result_name in result["results"]:
            assert isinstance(result_name, str)

    def test_empty_combo(self) -> None:
        combo = Combo(id="empty")
        result = slim_combo(combo)
        assert result["cards"] == []
        assert result["results"] == []
        assert result["color_identity"] == ""

    def test_field_count(self, sample_combo: Combo) -> None:
        result = slim_combo(sample_combo)
        assert len(result) == 4


# ---------------------------------------------------------------------------
# slim_rule
# ---------------------------------------------------------------------------


class TestSlimRule:
    @pytest.fixture
    def sample_rule(self) -> Rule:
        return Rule(
            number="702.2b",
            text="A creature with toughness greater than 0 that's been dealt damage by a source with deathtouch since the last time state-based actions were checked is destroyed as a state-based action.",
            subrules=[
                Rule(number="702.2c", text="Subrule text here."),
            ],
        )

    def test_includes_essential_fields(self, sample_rule: Rule) -> None:
        result = slim_rule(sample_rule)
        assert result["number"] == "702.2b"
        assert "deathtouch" in result["text"]

    def test_excludes_subrules(self, sample_rule: Rule) -> None:
        result = slim_rule(sample_rule)
        assert "subrules" not in result

    def test_field_count(self, sample_rule: Rule) -> None:
        result = slim_rule(sample_rule)
        assert len(result) == 2

    def test_no_recursive_bloat(self) -> None:
        """Deeply nested subrules should not appear in slim output."""
        deep = Rule(
            number="100.1",
            text="Top level",
            subrules=[
                Rule(
                    number="100.1a",
                    text="Level 1",
                    subrules=[Rule(number="100.1a-i", text="Level 2")],
                ),
            ],
        )
        result = slim_rule(deep)
        assert result == {"number": "100.1", "text": "Top level"}
