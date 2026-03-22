"""Shared Pydantic models for MTG data types.

Models are added here as services are implemented:
- Phase 1: Card, CardSearchResult, Ruling (Scryfall)
- Phase 2: Combo, DecklistCombos, BracketEstimate (Spellbook)
- Phase 2: DraftCardRating, ArchetypeRating (17Lands)
- Phase 2: EDHRECCard, EDHRECCardList, EDHRECCommanderData (EDHREC)
- Phase 4: MTGJSONCard (MTGJSON bulk data)
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
# Commander Spellbook
# ---------------------------------------------------------------------------


class ComboCard(BaseModel):
    """A card used in a combo, extracted from the Spellbook 'uses' array."""

    name: str
    oracle_id: str | None = Field(None, alias="oracleId")
    type_line: str = Field("", alias="typeLine")
    zone_locations: list[str] = Field(default_factory=list, alias="zoneLocations")
    must_be_commander: bool = Field(False, alias="mustBeCommander")

    model_config = {"populate_by_name": True}


class ComboResult(BaseModel):
    """A result produced by a combo, extracted from the Spellbook 'produces' array."""

    feature_name: str
    quantity: int = 1


class Combo(BaseModel):
    """A single combo variant from Commander Spellbook."""

    id: str
    status: str = ""
    cards: list[ComboCard] = Field(default_factory=list)
    produces: list[ComboResult] = Field(default_factory=list)
    identity: str = ""
    mana_needed: str = ""
    description: str = ""
    easy_prerequisites: str = ""
    notable_prerequisites: str = ""
    popularity: int = 0
    bracket_tag: str | None = None
    legalities: dict[str, bool] = Field(default_factory=dict)
    prices: dict[str, str] = Field(default_factory=dict)


class DecklistCombos(BaseModel):
    """Result of /find-my-combos — combos found in a decklist."""

    identity: str = ""
    included: list[Combo] = Field(default_factory=list)
    almost_included: list[Combo] = Field(default_factory=list)


class BracketEstimate(BaseModel):
    """Result of /estimate-bracket — bracket estimation for a decklist."""

    bracket_tag: str | None = Field(None, alias="bracketTag")
    banned_cards: list[str] = Field(default_factory=list, alias="bannedCards")
    game_changer_cards: list[str] = Field(default_factory=list, alias="gameChangerCards")
    two_card_combos: list[str] = Field(default_factory=list, alias="twoCardCombos")
    lock_combos: list[str] = Field(default_factory=list, alias="lockCombos")

    model_config = {"populate_by_name": True}


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


# ---------------------------------------------------------------------------
# EDHREC
# ---------------------------------------------------------------------------


class EDHRECCard(BaseModel):
    """A card entry from EDHREC with synergy and inclusion data."""

    name: str
    sanitized: str = ""
    synergy: float = 0.0
    inclusion: int = 0
    num_decks: int = 0
    potential_decks: int = 0
    label: str = ""


class EDHRECCardList(BaseModel):
    """A categorized list of cards from an EDHREC commander page."""

    header: str
    tag: str = ""
    cardviews: list[EDHRECCard] = Field(default_factory=list)


class EDHRECCommanderData(BaseModel):
    """Parsed commander page data from EDHREC."""

    commander_name: str
    cardlists: list[EDHRECCardList] = Field(default_factory=list)
    total_decks: int = 0


# ---------------------------------------------------------------------------
# MTGJSON
# ---------------------------------------------------------------------------


class MTGJSONCard(BaseModel):
    """Card data from MTGJSON AtomicCards."""

    name: str
    mana_cost: str = ""
    type_line: str = ""
    oracle_text: str = ""
    colors: list[str] = Field(default_factory=list)
    color_identity: list[str] = Field(default_factory=list)
    types: list[str] = Field(default_factory=list)
    subtypes: list[str] = Field(default_factory=list)
    supertypes: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    power: str | None = None
    toughness: str | None = None
    mana_value: float = 0.0
