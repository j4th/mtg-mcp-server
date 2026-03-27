"""Card resolver — bulk-data-first card resolution with Scryfall fallback."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from mtg_mcp_server.services.scryfall import ScryfallClient
    from mtg_mcp_server.services.scryfall_bulk import ScryfallBulkClient
    from mtg_mcp_server.types import Card

log = structlog.get_logger(service="workflow.card_resolver")


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
