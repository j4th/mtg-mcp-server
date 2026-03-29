"""Deck workflow — suggest cuts from a Commander decklist."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import structlog

if TYPE_CHECKING:
    from mtg_mcp_server.services.edhrec import EDHRECClient
    from mtg_mcp_server.services.spellbook import SpellbookClient
    from mtg_mcp_server.types import DecklistCombos, EDHRECCard, EDHRECCommanderData

log = structlog.get_logger(service="workflow.deck")


@dataclass
class _CardScore:
    """Scoring data for a single card in the decklist."""

    name: str
    synergy_score: float = 0.0
    inclusion_rate: int = 0
    is_combo_piece: bool = False
    has_edhrec_data: bool = False
    has_data: bool = False
    cuttability: float = 0.0


@dataclass
class _DataSources:
    """Track which data sources succeeded or failed."""

    spellbook_ok: bool = False
    edhrec_ok: bool = False
    edhrec_available: bool = False
    failures: list[str] = field(default_factory=list)


async def suggest_cuts(
    decklist: list[str],
    commander_name: str,
    *,
    spellbook: SpellbookClient,
    edhrec: EDHRECClient | None,
    num_cuts: int = 5,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> str:
    """Identify the weakest cards in a Commander decklist.

    Uses EDHREC synergy/inclusion data and Spellbook combo analysis to rank
    cards by cuttability. Combo pieces are protected.
    """
    if not decklist:
        return f"# Suggested Cuts for {commander_name}\n\nNo cards in decklist to evaluate."

    if num_cuts <= 0:
        return f"# Suggested Cuts for {commander_name}\n\nNo cuts requested."

    sources = _DataSources(edhrec_available=edhrec is not None)

    # -- 1. Gather data concurrently ------------------------------------------
    combo_data, edhrec_data = await _fetch_data(
        decklist, commander_name, spellbook=spellbook, edhrec=edhrec, sources=sources
    )

    # -- 2. Extract combo pieces -----------------------------------------------
    combo_pieces = _extract_combo_pieces(combo_data)

    # -- 3. Build synergy lookup -----------------------------------------------
    synergy_lookup = build_synergy_lookup(edhrec_data)

    # -- 4. Score each card ----------------------------------------------------
    scored = _score_cards(decklist, combo_pieces, synergy_lookup, sources)

    # -- 5. Sort by cuttability descending and cap -----------------------------
    scored.sort(key=lambda c: c.cuttability, reverse=True)
    cut_count = min(num_cuts, len(scored))
    top_cuts = scored[:cut_count]

    # -- 6. Format output ------------------------------------------------------
    return _format_output(commander_name, top_cuts, sources, response_format=response_format)


async def _fetch_spellbook(
    spellbook: SpellbookClient,
    commander_name: str,
    decklist: list[str],
) -> DecklistCombos | BaseException:
    """Fetch Spellbook data, returning the exception on failure."""
    try:
        return await spellbook.find_decklist_combos([commander_name], decklist)
    except Exception as exc:
        return exc


async def _fetch_edhrec(
    edhrec: EDHRECClient,
    commander_name: str,
) -> EDHRECCommanderData | BaseException:
    """Fetch EDHREC data, returning the exception on failure."""
    try:
        return await edhrec.commander_top_cards(commander_name)
    except Exception as exc:
        return exc


async def _fetch_data(
    decklist: list[str],
    commander_name: str,
    *,
    spellbook: SpellbookClient,
    edhrec: EDHRECClient | None,
    sources: _DataSources,
) -> tuple[DecklistCombos | None, EDHRECCommanderData | None]:
    """Fetch Spellbook and EDHREC data concurrently, tolerating failures."""
    spellbook_coro = _fetch_spellbook(spellbook, commander_name, decklist)

    if edhrec is not None:
        edhrec_coro = _fetch_edhrec(edhrec, commander_name)
        spellbook_result, edhrec_result = await asyncio.gather(spellbook_coro, edhrec_coro)
    else:
        spellbook_result = await spellbook_coro
        edhrec_result = None

    # Process spellbook result
    combo_data: DecklistCombos | None = None
    if isinstance(spellbook_result, BaseException):
        log.warning(
            "spellbook_fetch_failed",
            error=str(spellbook_result),
            error_type=type(spellbook_result).__name__,
        )
        sources.failures.append(f"Spellbook: {spellbook_result}")
    else:
        combo_data = spellbook_result
        sources.spellbook_ok = True

    # Process edhrec result
    edhrec_data: EDHRECCommanderData | None = None
    if edhrec_result is not None:
        if isinstance(edhrec_result, BaseException):
            log.warning(
                "edhrec_fetch_failed",
                error=str(edhrec_result),
                error_type=type(edhrec_result).__name__,
            )
            sources.failures.append(f"EDHREC: {edhrec_result}")
        else:
            edhrec_data = edhrec_result
            sources.edhrec_ok = True

    return combo_data, edhrec_data


def _extract_combo_pieces(combo_data: DecklistCombos | None) -> set[str]:
    """Extract lowercased card names from included combos."""
    pieces: set[str] = set()
    if combo_data is None:
        return pieces
    for combo in combo_data.included:
        for card in combo.cards:
            pieces.add(card.name.lower())
    return pieces


def build_synergy_lookup(
    edhrec_data: EDHRECCommanderData | None,
) -> dict[str, EDHRECCard]:
    """Build a lookup dict from EDHREC data keyed by lowercased card name."""
    lookup: dict[str, EDHRECCard] = {}
    if edhrec_data is None:
        return lookup
    for cardlist in edhrec_data.cardlists:
        for card in cardlist.cardviews:
            lookup[card.name.lower()] = card
    return lookup


def _score_cards(
    decklist: list[str],
    combo_pieces: set[str],
    synergy_lookup: dict[str, EDHRECCard],
    sources: _DataSources,
) -> list[_CardScore]:
    """Score each card in the decklist for cuttability."""
    scored: list[_CardScore] = []

    for card_name in decklist:
        cs = _CardScore(name=card_name)
        key = card_name.lower()

        # EDHREC data
        edhrec_card = synergy_lookup.get(key)
        if edhrec_card is not None:
            cs.synergy_score = edhrec_card.synergy
            cs.inclusion_rate = edhrec_card.inclusion
            cs.has_edhrec_data = True
            cs.has_data = True

        # Combo membership
        cs.is_combo_piece = key in combo_pieces
        if cs.is_combo_piece:
            cs.has_data = True

        # Cuttability scoring formula:
        #   base = (1 - synergy) + (1 - inclusion/100)  [0..2 range from EDHREC]
        #   combo piece:  -2.0  (strongly protects from being cut)
        #   no data:      +0.5  (slight bias toward cutting unknowns)
        # Higher cuttability = weaker card = more likely cut candidate.
        cuttability = 0.0

        if cs.has_edhrec_data:
            cuttability += 1.0 - cs.synergy_score
            cuttability += (100 - cs.inclusion_rate) / 100.0

        if cs.is_combo_piece:
            cuttability -= 2.0

        if not cs.has_data:
            cuttability += 0.5

        cs.cuttability = cuttability
        scored.append(cs)

    return scored


def _format_output(
    commander_name: str,
    top_cuts: list[_CardScore],
    sources: _DataSources,
    *,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> str:
    """Build the markdown output for suggested cuts."""
    lines: list[str] = []
    lines.append(f"# Suggested Cuts for {commander_name}")
    lines.append("")

    if response_format != "concise":
        # Data sources status
        lines.append("## Data Sources")
        lines.append(
            f"- [Commander Spellbook](https://commanderspellbook.com): "
            f"{'OK' if sources.spellbook_ok else 'Failed'}"
        )

        if not sources.edhrec_available:
            lines.append("- [EDHREC](https://edhrec.com): Disabled")
        elif sources.edhrec_ok:
            lines.append("- [EDHREC](https://edhrec.com): OK")
        else:
            lines.append("- [EDHREC](https://edhrec.com): Failed")
        lines.append("")

    # Ranked list
    if response_format != "concise":
        lines.append("## Suggested Cuts")
    for i, cs in enumerate(top_cuts, start=1):
        reasoning_parts: list[str] = []

        if cs.has_edhrec_data:
            reasoning_parts.append(
                f"Synergy: {cs.synergy_score:.0%}, Inclusion: {cs.inclusion_rate}%"
            )

        if cs.is_combo_piece:
            reasoning_parts.append("PROTECTED \u2014 combo piece")

        if not cs.has_data:
            reasoning_parts.append("Low confidence \u2014 no data found")

        reasoning = " | ".join(reasoning_parts) if reasoning_parts else "No additional data"
        lines.append(f"{i}. **{cs.name}** \u2014 {reasoning}")

    # Notes section if any sources failed (detailed only)
    if response_format != "concise" and sources.failures:
        lines.append("")
        lines.append("## Notes")
        for failure in sources.failures:
            lines.append(f"- {failure}")

    return "\n".join(lines)
