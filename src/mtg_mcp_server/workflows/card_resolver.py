"""Card resolver — MTGJSON-first card resolution with Scryfall fallback."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from mtg_mcp_server.services.mtgjson import MTGJSONClient
    from mtg_mcp_server.services.scryfall import ScryfallClient
    from mtg_mcp_server.types import Card, MTGJSONCard

log = structlog.get_logger(service="workflow.card_resolver")


async def resolve_card(
    name: str,
    *,
    mtgjson: MTGJSONClient | None,
    scryfall: ScryfallClient,
    need_prices: bool = False,
) -> Card | MTGJSONCard:
    """Resolve a card using MTGJSON first, falling back to Scryfall.

    When MTGJSON is available and prices are not needed, tries MTGJSON
    first for rate-limit-free lookup. Falls back to Scryfall if the card
    is not found in MTGJSON or if prices are required.

    Args:
        name: Card name to look up.
        mtgjson: Initialized MTGJSONClient, or None if disabled.
        scryfall: Initialized ScryfallClient (always available).
        need_prices: If True, go directly to Scryfall (MTGJSON has no prices).

    Returns:
        A Card (from Scryfall) or MTGJSONCard (from MTGJSON).

    Raises:
        CardNotFoundError: If the card is not found in any source.
    """
    if mtgjson is not None and not need_prices:
        card = await mtgjson.get_card(name)
        if card is not None:
            log.debug("resolve_card.mtgjson_hit", name=name)
            return card
        log.debug("resolve_card.mtgjson_miss", name=name)

    log.debug("resolve_card.scryfall_lookup", name=name)
    return await scryfall.get_card_by_name(name)
