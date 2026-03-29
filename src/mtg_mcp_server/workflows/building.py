"""Deck building workflow tools — theme search, build-around, and deck completion.

These tools are format-agnostic: they accept a ``format`` parameter and filter
results by legality.  They compose bulk data (oracle text, type line, keywords),
Spellbook (combo potential), and EDHREC (synergy, optional) into higher-order
deck-building analysis.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import structlog

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mtg_mcp_server.services.edhrec import EDHRECClient
    from mtg_mcp_server.services.scryfall_bulk import ScryfallBulkClient
    from mtg_mcp_server.services.spellbook import SpellbookClient
    from mtg_mcp_server.workflows import WorkflowResult

log = structlog.get_logger(service="workflow.building")


async def theme_search(
    theme: str,
    *,
    bulk: ScryfallBulkClient,
    edhrec: EDHRECClient | None = None,
    color_identity: str | None = None,
    format: str | None = None,
    max_price: float | None = None,
    limit: int = 20,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Find cards matching a theme — mechanical, tribal, or abstract/flavorful."""
    raise NotImplementedError("theme_search not yet implemented")


async def build_around(
    cards: list[str],
    format: str,
    *,
    bulk: ScryfallBulkClient,
    spellbook: SpellbookClient,
    edhrec: EDHRECClient | None = None,
    budget: float | None = None,
    limit: int = 20,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Given 1-5 build-around cards, find synergistic cards for a deck."""
    raise NotImplementedError("build_around not yet implemented")


async def complete_deck(
    decklist: list[str],
    format: str,
    *,
    bulk: ScryfallBulkClient,
    edhrec: EDHRECClient | None = None,
    commander: str | None = None,
    budget: float | None = None,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Given a partial decklist, identify gaps and suggest cards to fill them."""
    raise NotImplementedError("complete_deck not yet implemented")
