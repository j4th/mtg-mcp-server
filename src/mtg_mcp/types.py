"""Shared Pydantic models for MTG data types.

Models are added here as services are implemented:
- Phase 1: Card, CardSearchResult, Ruling (Scryfall)
- Phase 2: Combo, DecklistCombos, BracketEstimate (Spellbook)
- Phase 2: DraftCardRating, ArchetypeRating (17Lands)
- Phase 2: EDHRECCard, EDHRECCardList, EDHRECCommanderData (EDHREC)
"""

from __future__ import annotations

from pydantic import BaseModel, Field

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
