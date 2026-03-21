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


class ComboSearchResult(BaseModel):
    """Paginated list of combos from a search."""

    count: int | None = None
    results: list[Combo] = Field(default_factory=list)


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
