"""Commander depth workflow tools — comparison, tribal, precon upgrade, CI staples.

These tools extend the Commander analysis beyond the core ``commander.py`` tools,
providing deeper comparative analysis and format-specific deck-building workflows.
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

log = structlog.get_logger(service="workflow.commander_depth")


async def commander_comparison(
    commanders: list[str],
    *,
    bulk: ScryfallBulkClient,
    spellbook: SpellbookClient,
    edhrec: EDHRECClient | None = None,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Compare 2-5 commanders head-to-head."""
    raise NotImplementedError("commander_comparison not yet implemented")


async def tribal_staples(
    tribe: str,
    *,
    bulk: ScryfallBulkClient,
    edhrec: EDHRECClient | None = None,
    color_identity: str | None = None,
    format: str | None = None,
    limit: int = 20,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Best cards for a creature type within a color identity."""
    raise NotImplementedError("tribal_staples not yet implemented")


async def precon_upgrade(
    decklist: list[str],
    commander: str,
    *,
    bulk: ScryfallBulkClient,
    spellbook: SpellbookClient,
    edhrec: EDHRECClient | None = None,
    budget: float = 50.0,
    num_upgrades: int = 10,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Analyze and upgrade an official Commander precon."""
    raise NotImplementedError("precon_upgrade not yet implemented")


async def color_identity_staples(
    color_identity: str,
    *,
    bulk: ScryfallBulkClient,
    edhrec: EDHRECClient | None = None,
    category: str | None = None,
    limit: int = 20,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Top cards across all commanders in a color identity."""
    raise NotImplementedError("color_identity_staples not yet implemented")
