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
    Spicerack — SpicerackStanding, SpicerackTournament
    MTGGoldfish — GoldfishArchetype, GoldfishMetaSnapshot, GoldfishFormatStaple,
                  GoldfishArchetypeDetail, GoldfishDeckPrice
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

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
    "GlossaryEntry",
    "GoldfishArchetype",
    "GoldfishArchetypeDetail",
    "GoldfishDeckPrice",
    "GoldfishFormatStaple",
    "GoldfishMetaSnapshot",
    "MoxfieldCard",
    "MoxfieldDeck",
    "MoxfieldDecklist",
    "Rule",
    "Ruling",
    "SetInfo",
    "SpicerackStanding",
    "SpicerackTournament",
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
    layout: str = ""  # Scryfall layout (e.g. "normal", "transform", "modal_dfc")
    prices: CardPrices = Field(default_factory=CardPrices)
    legalities: dict[str, str] = Field(default_factory=dict)  # format -> "legal"/"not_legal"/etc.
    image_uris: CardImageUris | None = None
    scryfall_uri: str = ""
    edhrec_rank: int | None = None
    rulings_uri: str = ""

    # Allow construction via Python name (set_code=) or JSON key (set=)
    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _fill_from_card_faces(cls, data: dict) -> dict:
        """Populate top-level fields from card_faces[0] for MDFCs.

        Scryfall MDFCs (Modal Double-Faced Cards) store mana_cost,
        oracle_text, and colors only in ``card_faces``, not at the
        top level.  This validator fills those fields from the front
        face so downstream code doesn't need special-case handling.
        """
        if not isinstance(data, dict):
            return data
        faces = data.get("card_faces")
        if not isinstance(faces, list) or not faces:
            return data
        front = faces[0]
        if not isinstance(front, dict):
            return data
        for field in ("mana_cost", "oracle_text"):
            if data.get(field) is None and front.get(field) is not None:
                data[field] = front[field]
        if not data.get("colors") and front.get("colors"):
            data["colors"] = front["colors"]
        return data


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


class SetInfo(BaseModel):
    """Metadata for a Magic set from Scryfall."""

    code: str
    name: str
    set_type: str = ""
    released_at: str | None = None
    card_count: int = 0
    digital: bool = False
    icon_svg_uri: str = ""
    scryfall_uri: str = ""


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
    The API returns card/combo dicts in some list fields — validators coerce
    them to readable strings.
    """

    bracket_tag: str | None = Field(None, alias="bracketTag")
    banned_cards: list[str] = Field(default_factory=list, alias="bannedCards")
    game_changer_cards: list[str] = Field(default_factory=list, alias="gameChangerCards")
    two_card_combos: list[str] = Field(default_factory=list, alias="twoCardCombos")
    lock_combos: list[str] = Field(default_factory=list, alias="lockCombos")

    model_config = {"populate_by_name": True}

    @field_validator("banned_cards", "game_changer_cards", "lock_combos", mode="before")
    @classmethod
    def _extract_card_names(cls, v: list) -> list[str]:
        """Extract card names from card dicts, keep strings as-is."""
        return [item.get("name", str(item)) if isinstance(item, dict) else str(item) for item in v]

    @field_validator("two_card_combos", mode="before")
    @classmethod
    def _extract_combo_descriptions(cls, v: list) -> list[str]:
        """Extract card names from combo variant dicts, keep strings as-is."""
        result: list[str] = []
        for item in v:
            if isinstance(item, dict):
                cards = item.get("cards", [])
                if isinstance(cards, list) and cards:
                    names = [c.get("name", "?") if isinstance(c, dict) else str(c) for c in cards]
                    result.append(" + ".join(names))
                else:
                    result.append(item.get("name", str(item)))
            else:
                result.append(str(item))
        return result


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
    inclusion: int = (
        0  # Percentage of decks running this card (0-100), computed from num_decks/potential_decks
    )
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
# Moxfield
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Spicerack
# ---------------------------------------------------------------------------


class SpicerackStanding(BaseModel):
    """A player's result in a Spicerack tournament.

    Standings are ordered by final placement — the API does not provide
    an explicit rank field, so ``rank`` is assigned during parsing.
    ``decklist_url`` is a Moxfield URL or empty string.
    """

    rank: int = 0
    player_name: str = ""
    wins: int = 0
    losses: int = 0
    draws: int = 0
    bracket_wins: int = 0
    bracket_losses: int = 0
    decklist_url: str = ""


class SpicerackTournament(BaseModel):
    """Tournament metadata and standings from Spicerack.

    ``tournament_id`` is a string (the API's ``TID`` field).
    ``date`` is an ISO-8601 date string converted from the API's Unix timestamp.
    """

    tournament_id: str = ""
    name: str = ""
    format: str = ""
    date: str = ""
    player_count: int = 0
    rounds_swiss: int = 0
    top_cut: int = 0
    bracket_url: str = ""
    standings: list[SpicerackStanding] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# MTGGoldfish
# ---------------------------------------------------------------------------


class GoldfishArchetype(BaseModel):
    """An archetype from MTGGoldfish metagame breakdown."""

    name: str
    slug: str = ""
    meta_share: float = 0.0
    deck_count: int = 0
    price_paper: int = 0
    colors: list[str] = Field(default_factory=list)
    key_cards: list[str] = Field(default_factory=list)


class GoldfishMetaSnapshot(BaseModel):
    """A metagame snapshot for a format from MTGGoldfish."""

    format: str
    archetypes: list[GoldfishArchetype] = Field(default_factory=list)
    total_decks: int = 0


class GoldfishFormatStaple(BaseModel):
    """A commonly played card in a format from MTGGoldfish."""

    rank: int = 0
    name: str
    pct_of_decks: float = 0.0
    copies_played: float = 0.0


class GoldfishArchetypeDetail(BaseModel):
    """Archetype detail page with deck metadata and decklist."""

    name: str
    author: str = ""
    event: str = ""
    result: str = ""
    deck_id: str = ""
    date: str = ""
    mainboard: list[str] = Field(default_factory=list)
    sideboard: list[str] = Field(default_factory=list)


class GoldfishDeckPrice(BaseModel):
    """Price metadata for an archetype deck from MTGGoldfish."""

    archetype: str
    price_paper: int = 0
    mainboard_count: int = 0
    sideboard_count: int = 0


# ---------------------------------------------------------------------------
# Moxfield
# ---------------------------------------------------------------------------


class MoxfieldCard(BaseModel):
    """A card entry from a Moxfield decklist board section."""

    name: str
    quantity: int = Field(1, ge=1)


class MoxfieldDeck(BaseModel):
    """Metadata for a Moxfield deck."""

    id: str = ""
    name: str = ""
    format: str = ""
    description: str = ""
    author: str = ""
    public_url: str = ""
    created_at: str = ""
    updated_at: str = ""


class MoxfieldDecklist(BaseModel):
    """A fully resolved Moxfield decklist with board sections."""

    deck: MoxfieldDeck = Field(default_factory=MoxfieldDeck)
    commanders: list[MoxfieldCard] = Field(default_factory=list)
    mainboard: list[MoxfieldCard] = Field(default_factory=list)
    sideboard: list[MoxfieldCard] = Field(default_factory=list)
    companions: list[MoxfieldCard] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Comprehensive Rules
# ---------------------------------------------------------------------------


class Rule(BaseModel):
    """A single rule from the MTG Comprehensive Rules.

    Rule numbers follow the pattern ``section.subsection[letter]``
    (e.g. ``"100.1"``, ``"704.5k"``).  Subrules are nested children.
    """

    number: str
    text: str
    subrules: list[Rule] = Field(default_factory=list)


class GlossaryEntry(BaseModel):
    """A glossary term from the MTG Comprehensive Rules."""

    term: str
    definition: str
