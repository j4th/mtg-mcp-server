"""Deck analysis workflow — full decklist health check using all backends."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

from mtg_mcp_server.services.base import ServiceError
from mtg_mcp_server.utils.mana import count_pips
from mtg_mcp_server.workflows import WorkflowResult
from mtg_mcp_server.workflows.deck import build_synergy_lookup

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mtg_mcp_server.services.edhrec import EDHRECClient
    from mtg_mcp_server.services.scryfall import ScryfallClient
    from mtg_mcp_server.services.scryfall_bulk import ScryfallBulkClient
    from mtg_mcp_server.services.spellbook import SpellbookClient
    from mtg_mcp_server.types import (
        BracketEstimate,
        Card,
        DecklistCombos,
        EDHRECCard,
        EDHRECCommanderData,
    )

log = structlog.get_logger(service="workflow.analysis")

# Column headers for the mana curve table. Bucket 7 collects all CMC >= 7.
_CMC_HEADER = ["0", "1", "2", "3", "4", "5", "6", "7+"]


# ---------------------------------------------------------------------------
# Internal data structures
# ---------------------------------------------------------------------------


@dataclass
class _DataSources:
    """Track which data sources succeeded or failed."""

    scryfall_ok: bool = True
    spellbook_ok: bool = False
    spellbook_error: str | None = None
    edhrec_ok: bool = False
    edhrec_available: bool = False
    edhrec_error: str | None = None
    bulk_data_available: bool = False


@dataclass
class _ResolvedCard:
    """A card resolved from bulk data or Scryfall."""

    name: str
    mana_cost: str | None = None
    cmc: float = 0.0
    price_usd: str | None = None


@dataclass
class _ManaCurve:
    """Mana curve distribution."""

    buckets: dict[int, int] = field(default_factory=lambda: {i: 0 for i in range(8)})
    total_mana_value: float = 0.0


@dataclass
class _ColorPips:
    """Color pip counts extracted from mana costs."""

    pips: dict[str, float] = field(
        default_factory=lambda: {"W": 0.0, "U": 0.0, "B": 0.0, "R": 0.0, "G": 0.0}
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_cmc(card: Card) -> float:
    """Extract CMC from a resolved card."""
    return card.cmc


def _get_mana_cost(card: Card) -> str | None:
    """Extract mana cost from a resolved card."""
    return card.mana_cost if card.mana_cost else None


def _get_price_usd(card: Card) -> str | None:
    """Extract USD price from a card."""
    return card.prices.usd


def _compute_mana_curve(cards: list[_ResolvedCard]) -> _ManaCurve:
    """Compute mana curve from resolved cards."""
    curve = _ManaCurve()
    for card in cards:
        cmc = card.cmc
        curve.total_mana_value += cmc
        bucket = int(cmc) if cmc < 7 else 7
        curve.buckets[bucket] = curve.buckets.get(bucket, 0) + 1
    return curve


def _compute_color_pips(cards: list[_ResolvedCard]) -> _ColorPips:
    """Compute color pip totals from resolved cards."""
    color_pips = _ColorPips()
    for card in cards:
        pips = count_pips(card.mana_cost)
        for color, count in pips.items():
            color_pips.pips[color] = color_pips.pips.get(color, 0.0) + count
    return color_pips


# ---------------------------------------------------------------------------
# Main workflow
# ---------------------------------------------------------------------------


async def deck_analysis(
    decklist: list[str],
    commander_name: str,
    *,
    bulk: ScryfallBulkClient | None,
    scryfall: ScryfallClient,
    spellbook: SpellbookClient,
    edhrec: EDHRECClient | None,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> WorkflowResult:
    """Full decklist health check using all available backends.

    Args:
        decklist: List of card names in the deck.
        commander_name: The commander's name.
        bulk: Initialized ScryfallBulkClient, or None if disabled.
        scryfall: Initialized ScryfallClient.
        spellbook: Initialized SpellbookClient.
        edhrec: Initialized EDHRECClient, or None if disabled.
        on_progress: Optional progress callback (step, total).

    Returns:
        Formatted markdown string with deck analysis.
    """
    log.info("deck_analysis.start", commander=commander_name, deck_size=len(decklist))

    sources = _DataSources(
        edhrec_available=edhrec is not None,
        bulk_data_available=bulk is not None,
    )

    if not decklist:
        return WorkflowResult(
            markdown=f"# Deck Analysis \u2014 {commander_name}\n\nNo cards in decklist to analyze.",
            data={"commander_name": commander_name, "deck_size": 0},
        )

    # Step 1/3: Resolve cards
    if on_progress is not None:
        await on_progress(1, 3)

    resolved_cards, failures = await _resolve_cards(decklist, bulk=bulk, scryfall=scryfall)

    # Step 2/3: Combo/bracket analysis
    if on_progress is not None:
        await on_progress(2, 3)

    bracket, deck_combos = await _fetch_spellbook_data(
        commander_name, decklist, spellbook=spellbook, sources=sources
    )

    # Step 3/3: Synergy analysis
    if on_progress is not None:
        await on_progress(3, 3)

    edhrec_data = await _fetch_edhrec_data(commander_name, edhrec=edhrec, sources=sources)
    synergy_lookup = build_synergy_lookup(edhrec_data)

    # Compute analytics
    mana_curve = _compute_mana_curve(resolved_cards)
    color_pips = _compute_color_pips(resolved_cards)

    # Find lowest-synergy cards
    low_synergy = _find_low_synergy(decklist, synergy_lookup)

    # Compute budget from resolved cards (prices already populated)
    total_price, avg_price, priced_count = _compute_budget(resolved_cards)

    # Format output
    markdown = _format_output(
        commander_name=commander_name,
        deck_size=len(decklist),
        mana_curve=mana_curve,
        color_pips=color_pips,
        bracket=bracket,
        deck_combos=deck_combos,
        total_price=total_price,
        avg_price=avg_price,
        priced_count=priced_count,
        low_synergy=low_synergy,
        failures=failures,
        sources=sources,
    )
    data: dict = {
        "commander_name": commander_name,
        "deck_size": len(decklist),
        "mana_curve": mana_curve.buckets,
        "total_mana_value": mana_curve.total_mana_value,
        "color_pips": {c: v for c, v in color_pips.pips.items() if v > 0},
        "bracket": bracket.model_dump(mode="json") if bracket is not None else None,
        "combos_included": len(deck_combos.included) if deck_combos is not None else None,
        "combos_almost": len(deck_combos.almost_included) if deck_combos is not None else None,
        "total_price": total_price,
        "avg_price": avg_price,
        "priced_count": priced_count,
        "low_synergy": [{"name": n, "synergy": s} for n, s in low_synergy],
        "unresolved": failures,
        "sources": {
            "scryfall": sources.scryfall_ok,
            "spellbook": sources.spellbook_ok,
            "edhrec": sources.edhrec_ok,
            "bulk_data": sources.bulk_data_available,
        },
    }
    return WorkflowResult(markdown=markdown, data=data)


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------


async def _resolve_cards(
    decklist: list[str],
    *,
    bulk: ScryfallBulkClient | None,
    scryfall: ScryfallClient,
) -> tuple[list[_ResolvedCard], list[str]]:
    """Resolve all cards in the decklist using bulk-data-first fallback."""
    from mtg_mcp_server.workflows.card_resolver import resolve_card

    # Cap concurrent Scryfall lookups to avoid overwhelming the connection pool.
    sem = asyncio.Semaphore(10)

    async def _bounded_resolve(name: str) -> Card:
        """Resolve a single card with concurrency limiting."""
        async with sem:
            return await resolve_card(name, bulk=bulk, scryfall=scryfall)

    tasks = [_bounded_resolve(name) for name in decklist]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    resolved: list[_ResolvedCard] = []
    failures: list[str] = []

    for name, result in zip(decklist, results, strict=True):
        if isinstance(result, BaseException):
            log.warning(
                "deck_analysis.resolve_failed",
                card=name,
                error=str(result),
                error_type=type(result).__name__,
            )
            failures.append(name)
            # Add with defaults so curve still counts it
            resolved.append(_ResolvedCard(name=name))
        else:
            resolved.append(
                _ResolvedCard(
                    name=result.name,
                    mana_cost=_get_mana_cost(result),
                    cmc=_get_cmc(result),
                    price_usd=_get_price_usd(result),
                )
            )

    return resolved, failures


async def _fetch_spellbook_data(
    commander_name: str,
    decklist: list[str],
    *,
    spellbook: SpellbookClient,
    sources: _DataSources,
) -> tuple[BracketEstimate | None, DecklistCombos | None]:
    """Fetch bracket estimate and decklist combos concurrently."""
    bracket_coro = spellbook.estimate_bracket([commander_name], decklist)
    combo_coro = spellbook.find_decklist_combos([commander_name], decklist)

    results = await asyncio.gather(bracket_coro, combo_coro, return_exceptions=True)

    bracket: BracketEstimate | None = None
    deck_combos: DecklistCombos | None = None

    bracket_result = results[0]
    if isinstance(bracket_result, BaseException):
        log.warning(
            "deck_analysis.bracket_failed",
            error=str(bracket_result),
            error_type=type(bracket_result).__name__,
        )
        sources.spellbook_error = str(bracket_result)
    else:
        bracket = bracket_result

    combo_result = results[1]
    if isinstance(combo_result, BaseException):
        log.warning(
            "deck_analysis.combos_failed",
            error=str(combo_result),
            error_type=type(combo_result).__name__,
        )
        if sources.spellbook_error is None:
            sources.spellbook_error = str(combo_result)
    else:
        deck_combos = combo_result

    # Mark Spellbook as OK if at least one call succeeded
    sources.spellbook_ok = bracket is not None or deck_combos is not None

    return bracket, deck_combos


async def _fetch_edhrec_data(
    commander_name: str,
    *,
    edhrec: EDHRECClient | None,
    sources: _DataSources,
) -> EDHRECCommanderData | None:
    """Fetch EDHREC commander data if available."""
    if edhrec is None:
        return None

    try:
        data = await edhrec.commander_top_cards(commander_name)
    except ServiceError as exc:
        log.warning("deck_analysis.edhrec_failed", error=str(exc), error_type=type(exc).__name__)
        sources.edhrec_error = str(exc)
        return None

    sources.edhrec_ok = True
    return data


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------


def _find_low_synergy(
    decklist: list[str],
    synergy_lookup: dict[str, EDHRECCard],
) -> list[tuple[str, float]]:
    """Find the 5 lowest-synergy cards in the decklist."""
    scored: list[tuple[str, float]] = []
    for name in decklist:
        edhrec_card = synergy_lookup.get(name.lower())
        if edhrec_card is not None:
            scored.append((name, edhrec_card.synergy))

    scored.sort(key=lambda x: x[1])
    return scored[:5]


def _compute_budget(
    resolved_cards: list[_ResolvedCard],
) -> tuple[float, float, int]:
    """Compute total and average price from resolved cards.

    Returns (total, average, priced_count).
    """
    total = 0.0
    priced = 0
    for card in resolved_cards:
        if card.price_usd is not None:
            try:
                total += float(card.price_usd)
                priced += 1
            except ValueError:
                log.warning("compute_budget.bad_price", card=card.name, price=card.price_usd)

    avg = total / priced if priced > 0 else 0.0
    return total, avg, priced


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _format_output(
    *,
    commander_name: str,
    deck_size: int,
    mana_curve: _ManaCurve,
    color_pips: _ColorPips,
    bracket: BracketEstimate | None,
    deck_combos: DecklistCombos | None,
    total_price: float,
    avg_price: float,
    priced_count: int,
    low_synergy: list[tuple[str, float]],
    failures: list[str],
    sources: _DataSources,
) -> str:
    """Build the markdown output for deck analysis."""
    lines: list[str] = []
    lines.append(f"# Deck Analysis \u2014 {commander_name}")
    lines.append("")

    # Mana Curve
    lines.append("## Mana Curve")
    lines.append("")
    lines.append("| CMC | " + " | ".join(_CMC_HEADER) + " |")
    lines.append("|-----|" + "|".join("---" for _ in _CMC_HEADER) + "|")
    counts = " | ".join(str(mana_curve.buckets.get(i, 0)) for i in range(8))
    lines.append(f"| Cards | {counts} |")
    lines.append("")
    lines.append(f"**Total mana value:** {mana_curve.total_mana_value:.0f}")
    if deck_size > 0:
        lines.append(f"**Average mana value:** {mana_curve.total_mana_value / deck_size:.1f}")
    lines.append("")

    # Color Requirements
    lines.append("## Color Requirements")
    lines.append("")
    pip_parts = [
        f"{c}: {int(count) if count == int(count) else count}"
        for c, count in color_pips.pips.items()
        if count > 0
    ]
    if pip_parts:
        lines.append(", ".join(pip_parts))
    else:
        lines.append("No colored mana pips found.")
    lines.append("")

    # Combos & Bracket
    lines.append("## Combos & Bracket")
    lines.append("")
    if bracket is not None:
        lines.append(f"**Bracket:** {bracket.bracket_tag or 'Unknown'}")
    else:
        lines.append("**Bracket:** Unknown (Spellbook unavailable)")

    if deck_combos is not None:
        lines.append(f"**Included combos:** {len(deck_combos.included)}")
        lines.append(f"**Almost included:** {len(deck_combos.almost_included)}")
    else:
        lines.append("**Included combos:** Unknown (Spellbook unavailable)")
        lines.append("**Almost included:** Unknown (Spellbook unavailable)")
    lines.append("")

    # Budget
    lines.append("## Budget")
    lines.append("")
    if priced_count > 0:
        lines.append(f"**Total:** ${total_price:.2f}")
        lines.append(f"**Average card:** ${avg_price:.2f}")
        if priced_count < deck_size:
            lines.append(f"*({priced_count}/{deck_size} cards priced)*")
    else:
        lines.append("No price data available.")
    lines.append("")

    # Lowest Synergy Cards
    lines.append("## Lowest Synergy Cards")
    lines.append("")
    if low_synergy:
        for i, (name, synergy) in enumerate(low_synergy, 1):
            sign = "+" if synergy >= 0 else ""
            lines.append(f"{i}. **{name}** \u2014 synergy: {sign}{synergy:.0%}")
    else:
        if sources.edhrec_available:
            if sources.edhrec_ok:
                lines.append("No synergy data found for cards in this decklist.")
            else:
                lines.append(f"EDHREC unavailable: {sources.edhrec_error}")
        else:
            lines.append("EDHREC not enabled \u2014 synergy data not available.")
    lines.append("")

    # Card resolution failures
    if failures:
        lines.append("## Unresolved Cards")
        lines.append("")
        for name in failures:
            lines.append(f"- {name}")
        lines.append("")

    # Data Sources footer
    lines.append("---")
    lines.append("**Data Sources:**")
    lines.append(f"- [Scryfall](https://scryfall.com): {'OK' if sources.scryfall_ok else 'Failed'}")

    if sources.spellbook_ok:
        lines.append("- [Commander Spellbook](https://commanderspellbook.com): OK")
    elif sources.spellbook_error is not None:
        lines.append(
            f"- [Commander Spellbook](https://commanderspellbook.com): "
            f"Failed ({sources.spellbook_error})"
        )
    else:
        lines.append("- [Commander Spellbook](https://commanderspellbook.com): Failed")

    if not sources.edhrec_available:
        lines.append("- [EDHREC](https://edhrec.com): Disabled")
    elif sources.edhrec_ok:
        lines.append("- [EDHREC](https://edhrec.com): OK")
    elif sources.edhrec_error is not None:
        lines.append(f"- [EDHREC](https://edhrec.com): Failed ({sources.edhrec_error})")
    else:
        lines.append("- [EDHREC](https://edhrec.com): Failed")

    if sources.bulk_data_available:
        lines.append("- [Scryfall Bulk Data](https://scryfall.com/docs/api/bulk-data): OK")
    else:
        lines.append("- [Scryfall Bulk Data](https://scryfall.com/docs/api/bulk-data): Disabled")

    log.info("deck_analysis.complete", commander=commander_name, deck_size=deck_size)
    return "\n".join(lines)
