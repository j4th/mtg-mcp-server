"""Constructed metagame workflow tools.

Pure async functions composing MTGGoldfish, Spicerack, and Scryfall bulk data
to answer competitive format questions.  No MCP imports — ``server.py`` wraps
these as tools.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from mtg_mcp_server.workflows import WorkflowResult  # noqa: TC001 — runtime in impl

if TYPE_CHECKING:
    from mtg_mcp_server.services.mtggoldfish import MTGGoldfishClient
    from mtg_mcp_server.services.scryfall_bulk import ScryfallBulkClient
    from mtg_mcp_server.services.spicerack import SpicerackClient


async def metagame_snapshot(
    format: str,
    *,
    mtggoldfish: MTGGoldfishClient | None,
    spicerack: SpicerackClient | None,
    bulk: ScryfallBulkClient | None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Get the current metagame breakdown for a competitive format."""
    raise NotImplementedError


async def archetype_decklist(
    format: str,
    archetype: str,
    *,
    mtggoldfish: MTGGoldfishClient,
    bulk: ScryfallBulkClient | None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Get the stock decklist for a competitive archetype."""
    raise NotImplementedError


async def archetype_comparison(
    format: str,
    archetypes: list[str],
    *,
    mtggoldfish: MTGGoldfishClient,
    bulk: ScryfallBulkClient | None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Compare 2-4 competitive archetypes side-by-side."""
    raise NotImplementedError


async def format_entry_guide(
    format: str,
    *,
    mtggoldfish: MTGGoldfishClient | None,
    spicerack: SpicerackClient | None,
    bulk: ScryfallBulkClient | None,
    budget: float | None = None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Get a beginner-oriented guide for entering a competitive format."""
    raise NotImplementedError
