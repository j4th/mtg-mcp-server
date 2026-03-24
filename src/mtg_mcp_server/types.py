"""Shared Pydantic models for MTG data types.

Define the canonical data models that services return and providers/workflows
consume. Each backend maps its API-specific JSON shapes into these models,
giving the rest of the codebase a stable, typed interface regardless of which
external API the data came from.

Backends:
    Scryfall — Card, CardSearchResult, Ruling
    Commander Spellbook — Combo, DecklistCombos, BracketEstimate
    17Lands — DraftCardRating, ArchetypeRating
    EDHREC — EDHRECCard, EDHRECCardList, EDHRECCommanderData
    MTGJSON — MTGJSONCard
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = [
    "ArchetypeRating",
    "BracketEstimate",
    "Card",
    "CardImageUris",
    "CardPrices",
    "CardSearchResult",
    "Combo",
    "ComboCard",
    "ComboResult",
    "DecklistCombos",
    "DraftCardRating",
    "EDHRECCard",
    "EDHRECCardList",
    "EDHRECCommanderData",
    "MTGJSONCard",
    "Ruling",
]

# ---------------------------------------------------------------------------
# Scryfall
# ---------------------------------------------------------------------------


class CardPrices(BaseModel):
    """Market prices for a card in string format (e.g. ``"5.50"``)."""

    usd: str | None = None
    usd_foil: str | None = None
    eur: str | None = None


class CardImageUris(BaseModel):
    """Scryfall-hosted image URIs for a card."""

    normal: str | None = None
    art_crop: str | None = None


class Card(BaseModel):
    """A Magic card from Scryfall.

    Field mapping notes:
        ``set_code`` uses ``alias="set"`` because ``set`` is a Python builtin.
        ``populate_by_name`` allows constructing with either ``set`` (from JSON)
        or ``set_code`` (from Python code).
    """

    id: str
    name: str
    mana_cost: str | None = None
    cmc: float = 0.0
    type_line: str = ""
    oracle_text: str | None = None
    colors: list[str] = Field(default_factory=list)  # Card colors (e.g. ["B", "G", "U"])
    color_identity: list[str] = Field(default_factory=list)  # Commander identity colors
    keywords: list[str] = Field(default_factory=list)
    power: str | None = None  # String because some values are "*" or "X"
    toughness: str | None = None
    set_code: str = Field(alias="set", default="")  # Aliased: Scryfall JSON uses "set"
    collector_number: str = ""
    rarity: str = ""
    prices: CardPrices = Field(default_factory=CardPrices)
    legalities: dict[str, str] = Field(default_factory=dict)  # format -> "legal"/"not_legal"/etc.
    image_uris: CardImageUris | None = None
    scryfall_uri: str = ""
    edhrec_rank: int | None = None
    rulings_uri: str = ""

    # Allow construction via Python name (set_code=) or JSON key (set=)
    model_config = {"populate_by_name": True}


class CardSearchResult(BaseModel):
    """Paginated card search results from Scryfall."""

    total_cards: int
    has_more: bool  # True when additional pages are available
    data: list[Card]


class Ruling(BaseModel):
    """An official ruling or clarification for a card."""

    source: str  # e.g. "wotc" (Wizards of the Coast)
    published_at: str  # ISO date string
    comment: str


# ---------------------------------------------------------------------------
# Commander Spellbook
# ---------------------------------------------------------------------------


class ComboCard(BaseModel):
    """A card used in a combo, extracted from the Spellbook ``uses`` array.

    Aliases map from Spellbook's camelCase JSON to snake_case Python fields.
    """

    name: str
    oracle_id: str | None = Field(None, alias="oracleId")
    type_line: str = Field("", alias="typeLine")
    # Zone codes: B=Battlefield, H=Hand, G=Graveyard, E=Exile, L=Library, C=Command Zone
    zone_locations: list[str] = Field(default_factory=list, alias="zoneLocations")
    must_be_commander: bool = Field(False, alias="mustBeCommander")

    model_config = {"populate_by_name": True}


class ComboResult(BaseModel):
    """A result produced by a combo, extracted from the Spellbook ``produces`` array.

    The API wraps each result as ``{"feature": {"name": ...}, "quantity": N}``;
    the service layer flattens this into ``feature_name`` + ``quantity``.
    """

    feature_name: str
    quantity: int = 1


class Combo(BaseModel):
    """A single combo variant from Commander Spellbook.

    ``bracket_tag`` is a single-letter code from the API (e.g. ``"E"``),
    not a human-readable label like ``"Ruthless"``.
    """

    id: str  # Hyphenated variant ID, e.g. "1414-2730-5131-5256"
    status: str = ""
    cards: list[ComboCard] = Field(default_factory=list)
    produces: list[ComboResult] = Field(default_factory=list)
    identity: str = ""  # Color identity string, e.g. "BGU"
    mana_needed: str = ""
    description: str = ""  # Step-by-step combo instructions
    easy_prerequisites: str = ""
    notable_prerequisites: str = ""
    popularity: int = 0  # Number of decks using this combo
    bracket_tag: str | None = None  # Single-letter bracket code from API
    legalities: dict[str, bool] = Field(default_factory=dict)  # format -> legal?
    prices: dict[str, str] = Field(default_factory=dict)  # marketplace -> price string


class DecklistCombos(BaseModel):
    """Result of ``/find-my-combos`` — combos found in a decklist.

    ``included`` combos have all pieces in the decklist.
    ``almost_included`` combos are missing one or two cards.
    """

    identity: str = ""  # Combined color identity of the decklist
    included: list[Combo] = Field(default_factory=list)
    almost_included: list[Combo] = Field(default_factory=list)


class BracketEstimate(BaseModel):
    """Result of ``/estimate-bracket`` — bracket estimation for a decklist.

    Aliases map from Spellbook's camelCase JSON to snake_case Python fields.
    """

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
    """Card performance data from 17Lands draft tracking.

    All ``float | None`` fields may be ``None`` when the sample size is
    too small (< 500 games) or when date range params are omitted from the
    API request. Use ``is not None`` checks — ``0.0`` is a valid win rate.

    Key metrics (see SERVICE_CONTRACTS.md for full details):
        ``ever_drawn_win_rate`` — GIH WR: best single metric for card quality.
        ``avg_seen`` — ALSA: how late the card wheels (openness signal).
        ``drawn_improvement_win_rate`` — IWD: win rate boost when drawn vs not.
        ``opening_hand_win_rate`` — OH WR: how good the card is early.
    """

    name: str
    color: str  # Single-letter color code (e.g. "B", "W", "G")
    rarity: str  # "common", "uncommon", "rare", "mythic"
    seen_count: int = 0
    avg_seen: float | None = None  # ALSA — Average Last Seen At
    pick_count: int = 0
    avg_pick: float | None = None  # ATA — may be null without date range
    game_count: int = 0
    play_rate: float | None = None  # May be null
    win_rate: float | None = None
    opening_hand_win_rate: float | None = None  # OH WR
    drawn_win_rate: float | None = None  # GD WR (drawn this game, not opening hand)
    ever_drawn_win_rate: float | None = None  # GIH WR — primary quality metric
    never_drawn_win_rate: float | None = None  # GND WR
    drawn_improvement_win_rate: float | None = None  # IWD — delta: drawn vs not drawn


class ArchetypeRating(BaseModel):
    """Color pair/archetype win rate data from 17Lands.

    The API returns raw ``wins`` and ``games`` counts; win rate is derived
    via the ``win_rate`` property. Rows where ``is_summary`` is True are
    aggregate rows (e.g. all mono-color decks) rather than specific archetypes.
    """

    is_summary: bool = False
    color_name: str  # e.g. "Azorius (WU)"
    wins: int = 0
    games: int = 0

    @property
    def win_rate(self) -> float | None:
        """Derive win rate from wins/games. Return None if no games played."""
        return self.wins / self.games if self.games > 0 else None


# ---------------------------------------------------------------------------
# EDHREC
# ---------------------------------------------------------------------------


class EDHRECCard(BaseModel):
    """A card entry from EDHREC with synergy and inclusion data.

    ``synergy`` ranges from -1.0 to 1.0 — high values mean the card is
    specifically good with this commander, not just generically popular.
    ``inclusion`` is the percentage of decks running the card (0-100).
    """

    name: str
    sanitized: str = ""  # URL slug, e.g. "spore-frog"
    synergy: float = 0.0  # -1.0 to 1.0: commander-specific popularity signal
    inclusion: int = 0  # Percentage of decks running this card (0-100)
    num_decks: int = 0  # Number of decks actually running the card
    potential_decks: int = 0  # Total decks analyzed for this commander
    label: str = ""  # e.g. "61% of 19,741 decks"


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
    """Card data from MTGJSON AtomicCards bulk download.

    Unlike :class:`Card` (Scryfall), this model has no pricing, legality,
    or image data — it provides offline, rate-limit-free card lookups for
    basic oracle info like name, type, and text.
    """

    name: str  # Front-face name for DFCs (e.g. "Delver of Secrets")
    mana_cost: str = ""
    type_line: str = ""  # Mapped from MTGJSON's "type" field
    oracle_text: str = ""  # Mapped from MTGJSON's "text" field
    colors: list[str] = Field(default_factory=list)
    color_identity: list[str] = Field(default_factory=list)
    types: list[str] = Field(default_factory=list)  # e.g. ["Creature"]
    subtypes: list[str] = Field(default_factory=list)  # e.g. ["Human", "Wizard"]
    supertypes: list[str] = Field(default_factory=list)  # e.g. ["Legendary"]
    keywords: list[str] = Field(default_factory=list)
    power: str | None = None
    toughness: str | None = None
    mana_value: float = 0.0
