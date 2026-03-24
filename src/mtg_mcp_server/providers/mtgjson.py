"""MTGJSON MCP provider — rate-limit-free card lookup and search.

Uses the MTGJSON AtomicCards bulk file for in-memory card data.
"""

from __future__ import annotations

import json
from typing import Literal

import structlog
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.lifespan import lifespan

from mtg_mcp_server.config import Settings
from mtg_mcp_server.providers import ATTRIBUTION_MTGJSON, TAGS_LOOKUP, TAGS_SEARCH, TOOL_ANNOTATIONS
from mtg_mcp_server.services.mtgjson import MTGJSONClient, MTGJSONError

# Module-level client set by the lifespan. See scryfall.py for pattern rationale.
_client: MTGJSONClient | None = None


@lifespan
async def mtgjson_lifespan(server: FastMCP):
    """Manage the MTGJSONClient lifecycle.

    Downloads (or refreshes) the AtomicCards bulk file on first access,
    then keeps the in-memory card index available for the server's lifetime.
    """
    global _client
    settings = Settings()
    client = MTGJSONClient(
        data_url=settings.mtgjson_data_url,
        refresh_hours=settings.mtgjson_refresh_hours,
    )
    async with client:
        _client = client
        yield {}
    _client = None


mtgjson_mcp = FastMCP("MTGJSON", lifespan=mtgjson_lifespan)

log = structlog.get_logger(provider="mtgjson")


def _get_client() -> MTGJSONClient:
    """Return the initialized client or raise if the lifespan hasn't started."""
    if _client is None:
        raise RuntimeError("MTGJSONClient not initialized — server lifespan not running")
    return _client


@mtgjson_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_LOOKUP)
async def card_lookup(name: str) -> str:
    """Look up a Magic card by exact name using MTGJSON bulk data.

    Returns full card details including mana cost, type, oracle text,
    colors, power/toughness, and keywords. Case-insensitive.
    """
    client = _get_client()
    try:
        card = await client.get_card(name)
    except MTGJSONError as exc:
        raise ToolError(f"MTGJSON error: {exc}") from exc

    if card is None:
        raise ToolError(f"Card not found: '{name}'. Check spelling.")

    lines = [
        f"**{card.name}** {card.mana_cost}",
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
    if card.supertypes:
        lines.append(f"Supertypes: {', '.join(card.supertypes)}")
    if card.subtypes:
        lines.append(f"Subtypes: {', '.join(card.subtypes)}")
    lines.append(f"Mana Value: {card.mana_value}")
    return "\n".join(lines) + ATTRIBUTION_MTGJSON


@mtgjson_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_SEARCH)
async def card_search(
    query: str,
    search_field: Literal["name", "type", "text"] = "name",
    limit: int = 20,
) -> str:
    """Search for Magic cards in MTGJSON bulk data.

    Args:
        query: Substring to search for (case-insensitive).
        search_field: Field to search in — "name", "type", or "text".
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
    except MTGJSONError as exc:
        raise ToolError(f"MTGJSON error: {exc}") from exc

    if not results:
        raise ToolError(f"No cards found for {search_field} search: '{query}'.")

    lines = [f"Found {len(results)} card(s) matching {search_field}='{query}':"]
    for card in results:
        cost = f" {card.mana_cost}" if card.mana_cost else ""
        lines.append(f"  {card.name}{cost} — {card.type_line}")
    return "\n".join(lines) + ATTRIBUTION_MTGJSON


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@mtgjson_mcp.resource("mtg://card-data/{name}")
async def card_data_resource(name: str) -> str:
    """Get card data from MTGJSON bulk data as JSON."""
    client = _get_client()
    try:
        card = await client.get_card(name)
    except MTGJSONError as exc:
        log.warning("resource.card_data_error", name=name, error=str(exc))
        return json.dumps({"error": f"MTGJSON error: {exc}"})
    if card is None:
        log.debug("resource.card_data_not_found", name=name)
        return json.dumps({"error": f"Card not found: {name}"})
    return card.model_dump_json()
