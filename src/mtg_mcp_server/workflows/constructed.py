"""Constructed format workflow tools — Standard rotation tracking.

Provides format-specific analysis tools for constructed formats (Standard,
Pioneer, Modern, etc.).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import structlog

if TYPE_CHECKING:
    from mtg_mcp_server.services.scryfall import ScryfallClient
    from mtg_mcp_server.services.scryfall_bulk import ScryfallBulkClient
    from mtg_mcp_server.workflows import WorkflowResult

log = structlog.get_logger(service="workflow.constructed")


async def rotation_check(
    *,
    scryfall: ScryfallClient,
    bulk: ScryfallBulkClient,
    cards: list[str] | None = None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Check Standard rotation status and identify rotating cards."""
    raise NotImplementedError("rotation_check not yet implemented")
