"""Card resolver — bulk-data-first card resolution with Scryfall fallback."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from mtg_mcp_server.services.base import ServiceError

if TYPE_CHECKING:
    from mtg_mcp_server.services.scryfall import ScryfallClient
    from mtg_mcp_server.services.scryfall_bulk import ScryfallBulkClient
    from mtg_mcp_server.types import Card

log = structlog.get_logger(service="workflow.card_resolver")

# Cap concurrent Scryfall fallback lookups to avoid overwhelming the
# connection pool (mirrors deck_analysis's bound).
_MAX_FALLBACK_CONCURRENCY = 10


async def resolve_card(
    name: str,
    *,
    bulk: ScryfallBulkClient | None,
    scryfall: ScryfallClient,
) -> Card:
    """Resolve a card using bulk data first, falling back to Scryfall.

    When bulk data is available, tries it first for rate-limit-free lookup.
    Falls back to Scryfall if the card is not found in bulk data or if
    bulk data is disabled.

    Args:
        name: Card name to look up.
        bulk: Initialized ScryfallBulkClient, or None if disabled.
        scryfall: Initialized ScryfallClient (always available).

    Returns:
        A Card object (from bulk data or Scryfall — same type either way).

    Raises:
        CardNotFoundError: If the card is not found in any source.
    """
    if bulk is not None:
        try:
            card = await bulk.get_card(name)
        except Exception:
            log.warning("resolve_card.bulk_error", name=name, exc_info=True)
            card = None

        if card is not None:
            log.debug("resolve_card.bulk_hit", name=name)
            return card
        log.debug("resolve_card.bulk_miss", name=name)

    log.debug("resolve_card.scryfall_lookup", name=name)
    return await scryfall.get_card_by_name(name)


async def resolve_cards(
    names: list[str],
    *,
    bulk: ScryfallBulkClient | None,
    scryfall: ScryfallClient,
) -> dict[str, Card | None]:
    """Resolve many cards by name: bulk-data-first with Scryfall fallback.

    Batch counterpart to :func:`resolve_card` with the same degradation
    semantics, but using a single ``bulk.get_cards`` call for the bulk
    stage: a bulk error or bulk miss for a card falls back to Scryfall for
    that card (concurrency-capped). A card not found anywhere maps to
    ``None`` — this function never raises for individual cards, matching
    ``bulk.get_cards``' shape.

    Args:
        names: Card names to look up.
        bulk: Initialized ScryfallBulkClient, or None if disabled.
        scryfall: Initialized ScryfallClient (fallback source).

    Returns:
        Dict mapping each input name (original casing preserved) to its
        Card, or None if not found in any source.
    """
    # Dedupe input names (decklists repeat cards) so the bulk batch and
    # each fallback path fetch every distinct name at most once.
    unique_names = list(dict.fromkeys(names))
    resolved: dict[str, Card | None] = {name: None for name in unique_names}
    missing: list[str] = unique_names

    if bulk is not None:
        try:
            bulk_map = await bulk.get_cards(unique_names)
        except Exception:
            log.warning("resolve_cards.bulk_error", count=len(unique_names), exc_info=True)
        else:
            missing = []
            for name in unique_names:
                card = bulk_map.get(name)
                if card is not None:
                    resolved[name] = card
                else:
                    missing.append(name)
            if missing:
                log.debug(
                    "resolve_cards.bulk_miss",
                    total=len(unique_names),
                    missing=len(missing),
                )

    if not missing:
        return resolved

    log.debug("resolve_cards.scryfall_fallback", count=len(missing))
    sem = asyncio.Semaphore(_MAX_FALLBACK_CONCURRENCY)

    async def _fetch(name: str) -> tuple[str, Card | None]:
        async with sem:
            try:
                card = await scryfall.get_card_by_name(name)
            except ServiceError as exc:
                log.warning(
                    "resolve_cards.scryfall_failed",
                    card=name,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                return name, None
            return name, card

    fallback = await asyncio.gather(*(_fetch(name) for name in missing))
    for name, card in fallback:
        resolved[name] = card
    return resolved
