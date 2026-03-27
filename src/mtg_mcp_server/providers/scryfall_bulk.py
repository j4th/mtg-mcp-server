"""Scryfall bulk data MCP provider -- rate-limit-free card lookup and search.

Uses Scryfall's Oracle Cards bulk file for rate-limit-free in-memory card data
including prices, legalities, and EDHREC rank.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal

import structlog
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.lifespan import lifespan
from pydantic import Field

from mtg_mcp_server.config import Settings
from mtg_mcp_server.providers import (
    ATTRIBUTION_SCRYFALL_BULK,
    TAGS_LOOKUP,
    TAGS_SEARCH,
    TOOL_ANNOTATIONS,
)
from mtg_mcp_server.services.scryfall_bulk import ScryfallBulkClient, ScryfallBulkError

# Module-level client set by the lifespan. See scryfall.py for pattern rationale.
_client: ScryfallBulkClient | None = None


@lifespan
async def scryfall_bulk_lifespan(server: FastMCP):
    """Initialize the ScryfallBulkClient and start its background refresh timer.

    Data is loaded lazily on the first tool call, not during startup. The
    background task periodically re-downloads data at the configured interval.
    """
    global _client
    settings = Settings()
    client = ScryfallBulkClient(
        base_url=settings.scryfall_base_url,
        refresh_hours=settings.bulk_data_refresh_hours,
    )
    async with client:
        _client = client
        client.start_background_refresh()
        yield {}
    _client = None


scryfall_bulk_mcp = FastMCP(
    "Scryfall Bulk Data", lifespan=scryfall_bulk_lifespan, mask_error_details=True
)

log = structlog.get_logger(provider="scryfall_bulk")


def _get_client() -> ScryfallBulkClient:
    """Return the initialized client or raise if the lifespan hasn't started."""
    if _client is None:
        raise RuntimeError("ScryfallBulkClient not initialized -- server lifespan not running")
    return _client


def _format_legalities(legalities: dict[str, str]) -> str:
    """Format a legalities dict as a comma-separated list of legal format names."""
    legal = [fmt for fmt, status in legalities.items() if status == "legal"]
    if not legal:
        return "Not legal in any format"
    return ", ".join(legal)


@scryfall_bulk_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_LOOKUP)
async def card_lookup(
    name: Annotated[
        str,
        Field(description="Card name for exact lookup, case-insensitive (e.g. 'Sol Ring')"),
    ],
) -> str:
    """Look up a Magic card by exact name using Scryfall bulk data.

    Returns full card details including mana cost, type, oracle text,
    colors, power/toughness, prices, legalities, and EDHREC rank.
    Case-insensitive.
    """
    client = _get_client()
    try:
        card = await client.get_card(name)
    except ScryfallBulkError as exc:
        raise ToolError(f"Scryfall bulk data error: {exc}") from exc

    if card is None:
        raise ToolError(f"Card not found: '{name}'. Check spelling.")

    lines = [
        f"**{card.name}** {card.mana_cost or ''}",
        f"Type: {card.type_line}",
    ]
    if card.oracle_text:
        lines.append(f"Text: {card.oracle_text}")
    if card.power is not None and card.toughness is not None:
        lines.append(f"P/T: {card.power}/{card.toughness}")
    lines.append(f"Colors: {', '.join(card.colors) or 'Colorless'}")
    lines.append(f"Color Identity: {', '.join(card.color_identity) or 'Colorless'}")
    if card.keywords:
        lines.append(f"Keywords: {', '.join(card.keywords)}")
    if card.set_code:
        lines.append(f"Set: {card.set_code.upper()} ({card.rarity})")
    if card.prices.usd:
        lines.append(f"Price: ${card.prices.usd} (foil: ${card.prices.usd_foil or 'N/A'})")
    if card.edhrec_rank is not None:
        lines.append(f"EDHREC Rank: {card.edhrec_rank}")
    lines.append(f"Legalities: {_format_legalities(card.legalities)}")
    return "\n".join(lines) + ATTRIBUTION_SCRYFALL_BULK


@scryfall_bulk_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_SEARCH)
async def card_search(
    query: Annotated[str, Field(description="Substring to search for, case-insensitive")],
    search_field: Annotated[
        Literal["name", "type", "text"],
        Field(
            description="Field to search in -- 'name' (card name), 'type' (type line), or 'text' (oracle text)"
        ),
    ] = "name",
    limit: Annotated[int, Field(description="Maximum number of results to return")] = 20,
) -> str:
    """Search for Magic cards in Scryfall bulk data.

    Args:
        query: Substring to search for (case-insensitive).
        search_field: Field to search in -- "name", "type", or "text".
        limit: Maximum number of results to return (default 20).
    """
    client = _get_client()

    try:
        if search_field == "name":
            results = await client.search_cards(query, limit=limit)
        elif search_field == "type":
            results = await client.search_by_type(query, limit=limit)
        else:  # search_field == "text"
            results = await client.search_by_text(query, limit=limit)
    except ScryfallBulkError as exc:
        raise ToolError(f"Scryfall bulk data error: {exc}") from exc

    if not results:
        raise ToolError(f"No cards found for {search_field} search: '{query}'.")

    lines = [f"Found {len(results)} card(s) matching {search_field}='{query}':"]
    for card in results:
        cost = f" {card.mana_cost}" if card.mana_cost else ""
        lines.append(f"  {card.name}{cost} -- {card.type_line}")
    return "\n".join(lines) + ATTRIBUTION_SCRYFALL_BULK


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@scryfall_bulk_mcp.resource("mtg://card-data/{name}")
async def card_data_resource(name: str) -> str:
    """Get card data from Scryfall bulk data as JSON."""
    client = _get_client()
    try:
        card = await client.get_card(name)
    except ScryfallBulkError as exc:
        log.warning("resource.card_data_error", name=name, error=str(exc))
        return json.dumps({"error": f"Scryfall bulk data error: {exc}"})
    if card is None:
        log.debug("resource.card_data_not_found", name=name)
        return json.dumps({"error": f"Card not found: {name}"})
    return card.model_dump_json()
