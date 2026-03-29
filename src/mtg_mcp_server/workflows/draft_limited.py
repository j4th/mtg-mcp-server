"""Limited expansion workflow tools — sealed pool building, draft signals, log review.

These tools extend the Limited analysis beyond the core ``draft.py`` tools,
providing deeper draft strategy analysis and sealed pool deck construction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import structlog

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mtg_mcp_server.services.scryfall_bulk import ScryfallBulkClient
    from mtg_mcp_server.services.seventeen_lands import SeventeenLandsClient
    from mtg_mcp_server.workflows import WorkflowResult

log = structlog.get_logger(service="workflow.draft_limited")


async def sealed_pool_build(
    pool: list[str],
    set_code: str,
    *,
    bulk: ScryfallBulkClient,
    seventeen_lands: SeventeenLandsClient | None = None,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Given a sealed pool, suggest the best 40-card deck builds."""
    raise NotImplementedError("sealed_pool_build not yet implemented")


async def draft_signal_read(
    picks: list[str],
    set_code: str,
    *,
    bulk: ScryfallBulkClient,
    seventeen_lands: SeventeenLandsClient,
    current_pack: list[str] | None = None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Analyze draft picks so far and recommend a direction based on signals."""
    raise NotImplementedError("draft_signal_read not yet implemented")


async def draft_log_review(
    picks: list[str],
    set_code: str,
    *,
    bulk: ScryfallBulkClient,
    seventeen_lands: SeventeenLandsClient,
    final_deck: list[str] | None = None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Review a completed draft — pick-by-pick analysis with GIH WR comparison."""
    raise NotImplementedError("draft_log_review not yet implemented")
