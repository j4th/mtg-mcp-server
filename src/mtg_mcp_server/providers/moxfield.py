"""Moxfield MCP provider — deck fetching and metadata tools.

Uses reverse-engineered Moxfield v3 endpoints. Behind the MTG_MCP_ENABLE_MOXFIELD
feature flag. These endpoints may break without notice.
"""

from __future__ import annotations

import json
from typing import Annotated

import structlog
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.lifespan import lifespan
from fastmcp.tools import ToolResult
from pydantic import Field

from mtg_mcp_server.config import Settings
from mtg_mcp_server.providers import ATTRIBUTION_MOXFIELD, TAGS_BETA, TOOL_ANNOTATIONS
from mtg_mcp_server.services.moxfield import DeckNotFoundError, MoxfieldClient, MoxfieldError

# Module-level client set by the lifespan. See edhrec.py for pattern rationale.
_client: MoxfieldClient | None = None


@lifespan
async def moxfield_lifespan(server: FastMCP):
    """Manage the MoxfieldClient lifecycle."""
    global _client
    settings = Settings()
    base_url = settings.moxfield_base_url
    client = MoxfieldClient(base_url=base_url)
    async with client:
        _client = client
        yield {}
    _client = None


moxfield_mcp = FastMCP("Moxfield", lifespan=moxfield_lifespan, mask_error_details=True)

log = structlog.get_logger(provider="moxfield")


def _get_client() -> MoxfieldClient:
    """Return the initialized client or raise if the lifespan hasn't started."""
    if _client is None:
        raise RuntimeError("MoxfieldClient not initialized — server lifespan not running")
    return _client


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@moxfield_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_BETA)
async def decklist(
    deck_id: Annotated[
        str,
        Field(
            description=(
                "Moxfield deck ID or full URL "
                "(e.g. 'abc123' or 'https://www.moxfield.com/decks/abc123')"
            )
        ),
    ],
) -> ToolResult:
    """Fetch a full decklist from Moxfield by deck ID or URL.

    Returns the complete decklist organized by board (commanders, mainboard,
    sideboard, companions) with card names and quantities.
    """
    client = _get_client()
    try:
        result = await client.get_deck(deck_id)
    except DeckNotFoundError as exc:
        raise ToolError(
            f"Deck not found on Moxfield: '{deck_id}'. "
            "Check the deck ID or URL — the deck may be private or deleted."
        ) from exc
    except MoxfieldError as exc:
        raise ToolError(f"Moxfield API error: {exc}") from exc

    # Build markdown output
    lines: list[str] = []
    lines.append(f"**{result.deck.name}** ({result.deck.format})")
    if result.deck.author:
        lines.append(f"Author: {result.deck.author}")

    boards = [
        ("Commanders", result.commanders),
        ("Mainboard", result.mainboard),
        ("Sideboard", result.sideboard),
        ("Companions", result.companions),
    ]
    total_cards = 0
    for section_name, cards in boards:
        if cards:
            lines.append(f"\n### {section_name} ({len(cards)})")
            for card in cards:
                lines.append(f"{card.quantity}x {card.name}")
                total_cards += card.quantity

    # Build structured content
    structured = {
        "deck": {
            "id": result.deck.id,
            "name": result.deck.name,
            "format": result.deck.format,
            "description": result.deck.description,
            "author": result.deck.author,
            "public_url": result.deck.public_url,
            "created_at": result.deck.created_at,
            "updated_at": result.deck.updated_at,
        },
        "commanders": [{"name": c.name, "quantity": c.quantity} for c in result.commanders],
        "mainboard": [{"name": c.name, "quantity": c.quantity} for c in result.mainboard],
        "sideboard": [{"name": c.name, "quantity": c.quantity} for c in result.sideboard],
        "companions": [{"name": c.name, "quantity": c.quantity} for c in result.companions],
        "total_cards": total_cards,
    }

    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_MOXFIELD,
        structured_content=structured,
    )


@moxfield_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_BETA)
async def deck_info(
    deck_id: Annotated[
        str,
        Field(
            description=(
                "Moxfield deck ID or full URL "
                "(e.g. 'abc123' or 'https://www.moxfield.com/decks/abc123')"
            )
        ),
    ],
) -> ToolResult:
    """Get metadata for a Moxfield deck (name, format, author, dates).

    Returns deck metadata without the full card list. Use ``decklist``
    for the complete card list.
    """
    client = _get_client()
    try:
        result = await client.get_deck(deck_id)
    except DeckNotFoundError as exc:
        raise ToolError(
            f"Deck not found on Moxfield: '{deck_id}'. "
            "Check the deck ID or URL — the deck may be private or deleted."
        ) from exc
    except MoxfieldError as exc:
        raise ToolError(f"Moxfield API error: {exc}") from exc

    deck = result.deck
    lines: list[str] = [
        f"**{deck.name}**",
        f"Format: {deck.format}" if deck.format else "",
        f"Author: {deck.author}" if deck.author else "",
    ]
    if deck.description:
        lines.append(f"Description: {deck.description}")
    if deck.created_at:
        lines.append(f"Created: {deck.created_at}")
    if deck.updated_at:
        lines.append(f"Last updated: {deck.updated_at}")
    if deck.public_url:
        lines.append(f"URL: {deck.public_url}")

    # Card counts per board
    board_counts: dict[str, int] = {}
    for board_name, cards in [
        ("commanders", result.commanders),
        ("mainboard", result.mainboard),
        ("sideboard", result.sideboard),
        ("companions", result.companions),
    ]:
        if cards:
            board_counts[board_name] = sum(c.quantity for c in cards)

    if board_counts:
        lines.append("\nCard counts:")
        for board_name, count in board_counts.items():
            lines.append(f"  {board_name}: {count}")

    # Filter empty strings from conditional lines
    lines = [line for line in lines if line]

    structured = {
        "id": deck.id,
        "name": deck.name,
        "format": deck.format,
        "description": deck.description,
        "author": deck.author,
        "public_url": deck.public_url,
        "created_at": deck.created_at,
        "updated_at": deck.updated_at,
        "board_counts": board_counts,
    }

    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_MOXFIELD,
        structured_content=structured,
    )


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@moxfield_mcp.resource("mtg://moxfield/{deck_id}")
async def moxfield_deck_resource(deck_id: str) -> str:
    """Get Moxfield deck data as JSON."""
    client = _get_client()
    try:
        result = await client.get_deck(deck_id)
        return result.model_dump_json()
    except DeckNotFoundError:
        log.debug("resource.deck_not_found", deck_id=deck_id)
        return json.dumps({"error": f"Deck not found: {deck_id}"})
    except MoxfieldError as exc:
        log.warning("resource.deck_error", deck_id=deck_id, error=str(exc))
        return json.dumps({"error": f"Moxfield error: {exc}"})
