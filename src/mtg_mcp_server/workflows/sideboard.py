"""Sideboard analysis workflow tools for Bo3 constructed formats.

Pure async functions composing Scryfall bulk data and MTGGoldfish to provide
sideboard recommendations, matchup guides, and boarding matrices.  No MCP
imports — ``server.py`` wraps these as tools.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from mtg_mcp_server.workflows import WorkflowResult  # noqa: TC001 — runtime in impl

if TYPE_CHECKING:
    from mtg_mcp_server.services.mtggoldfish import MTGGoldfishClient
    from mtg_mcp_server.services.scryfall_bulk import ScryfallBulkClient


async def suggest_sideboard(
    decklist: list[str],
    format: str,
    *,
    bulk: ScryfallBulkClient,
    mtggoldfish: MTGGoldfishClient | None,
    meta_context: str | None = None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Suggest a 15-card sideboard for a competitive deck."""
    raise NotImplementedError


async def sideboard_guide(
    decklist: list[str],
    sideboard: list[str],
    format: str,
    matchup: str,
    *,
    bulk: ScryfallBulkClient,
    mtggoldfish: MTGGoldfishClient | None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Get a specific sideboard in/out plan for a named matchup."""
    raise NotImplementedError


async def sideboard_matrix(
    decklist: list[str],
    sideboard: list[str],
    format: str,
    *,
    bulk: ScryfallBulkClient,
    mtggoldfish: MTGGoldfishClient | None,
    matchups: list[str] | None = None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Generate a sideboard matrix for a deck across common matchups."""
    raise NotImplementedError
