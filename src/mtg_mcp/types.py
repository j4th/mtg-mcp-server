"""Shared Pydantic models for MTG data types.

Models are added here as services are implemented:
- Phase 1: Card, CardSearchResult, Ruling (Scryfall)
- Phase 2: Combo, DecklistCombos, BracketEstimate (Spellbook)
- Phase 2: DraftCardRating, ArchetypeRating (17Lands)
- Phase 2: EDHRECCard, SynergyData (EDHREC)
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Scryfall
# ---------------------------------------------------------------------------


class CardPrices(BaseModel):
    usd: str | None = None
    usd_foil: str | None = None
    eur: str | None = None


class CardImageUris(BaseModel):
    normal: str | None = None
    art_crop: str | None = None


class Card(BaseModel):
    id: str
    name: str
    mana_cost: str | None = None
    cmc: float = 0.0
    type_line: str = ""
    oracle_text: str | None = None
    colors: list[str] = Field(default_factory=list)
    color_identity: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    power: str | None = None
    toughness: str | None = None
    set_code: str = Field(alias="set", default="")
    collector_number: str = ""
    rarity: str = ""
    prices: CardPrices = Field(default_factory=CardPrices)
    legalities: dict[str, str] = Field(default_factory=dict)
    image_uris: CardImageUris | None = None
    scryfall_uri: str = ""
    edhrec_rank: int | None = None
    rulings_uri: str = ""

    model_config = {"populate_by_name": True}


class CardSearchResult(BaseModel):
    total_cards: int
    has_more: bool
    data: list[Card]


class Ruling(BaseModel):
    source: str
    published_at: str
    comment: str


# ---------------------------------------------------------------------------
# 17Lands
# ---------------------------------------------------------------------------


class DraftCardRating(BaseModel):
    """Card performance data from 17Lands draft tracking."""

    name: str
    color: str
    rarity: str
    seen_count: int = 0
    avg_seen: float | None = None
    pick_count: int = 0
    avg_pick: float | None = None
    game_count: int = 0
    play_rate: float | None = None
    win_rate: float | None = None
    opening_hand_win_rate: float | None = None
    drawn_win_rate: float | None = None
    ever_drawn_win_rate: float | None = None
    never_drawn_win_rate: float | None = None
    drawn_improvement_win_rate: float | None = None


class ArchetypeRating(BaseModel):
    """Color pair/archetype win rate data from 17Lands."""

    is_summary: bool = False
    color_name: str
    wins: int = 0
    games: int = 0

    @property
    def win_rate(self) -> float | None:
        """Derive win rate from wins/games."""
        return self.wins / self.games if self.games > 0 else None
