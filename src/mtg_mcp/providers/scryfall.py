"""Scryfall MCP provider — card search, lookup, pricing, and rulings."""

from __future__ import annotations

import json

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.lifespan import lifespan

from mtg_mcp.config import Settings
from mtg_mcp.providers import (
    ATTRIBUTION_SCRYFALL,
    TAGS_LOOKUP,
    TAGS_PRICING,
    TAGS_SEARCH,
    TOOL_ANNOTATIONS,
)
from mtg_mcp.services.scryfall import CardNotFoundError, ScryfallClient, ScryfallError

# Module-level client set by the lifespan. This pattern is required because
# FastMCP's Depends()/lifespan_context DI doesn't propagate through mount().
_client: ScryfallClient | None = None


@lifespan
async def scryfall_lifespan(server: FastMCP):
    """Manage the ScryfallClient lifecycle.

    Create the client once at startup using settings (honoring env var overrides),
    keep the httpx connection pool open for the server's lifetime, then tear down.
    """
    global _client
    settings = Settings()
    client = ScryfallClient(base_url=settings.scryfall_base_url)
    async with client:
        _client = client
        yield {}
    _client = None


scryfall_mcp = FastMCP("Scryfall", lifespan=scryfall_lifespan)


def _get_client() -> ScryfallClient:
    """Return the initialized client or raise if the lifespan hasn't started."""
    if _client is None:
        raise RuntimeError("ScryfallClient not initialized — server lifespan not running")
    return _client


@scryfall_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_SEARCH)
async def search_cards(
    query: str,
    page: int = 1,
) -> str:
    """Search for Magic cards using Scryfall syntax.

    Examples: "f:commander id:sultai t:creature", "o:destroy t:instant cmc<=3"
    See https://scryfall.com/docs/syntax for full syntax reference.
    """
    client = _get_client()
    try:
        result = await client.search_cards(query, page=page)
    except CardNotFoundError as exc:
        raise ToolError(f"No cards found for query: '{query}'. Check your search syntax.") from exc
    except ScryfallError as exc:
        raise ToolError(f"Scryfall API error: {exc}") from exc

    lines = [f"Found {result.total_cards} cards (showing {len(result.data)}, page {page}):"]
    for card in result.data:
        price = f" · ${card.prices.usd}" if card.prices.usd else ""
        lines.append(f"  {card.name} {card.mana_cost or ''} — {card.type_line}{price}")
    if result.has_more:
        lines.append(f"\nMore results available — use page={page + 1}")
    return "\n".join(lines) + ATTRIBUTION_SCRYFALL


@scryfall_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_LOOKUP)
async def card_details(
    name: str,
    fuzzy: bool = False,
) -> str:
    """Get full details for a Magic card by exact or fuzzy name."""
    client = _get_client()
    try:
        card = await client.get_card_by_name(name, fuzzy=fuzzy)
    except CardNotFoundError as exc:
        raise ToolError(f"Card not found: '{name}'. Check spelling or try fuzzy=true.") from exc
    except ScryfallError as exc:
        raise ToolError(f"Scryfall API error: {exc}") from exc

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
    lines.append(f"Set: {card.set_code.upper()} ({card.rarity})")
    if card.prices.usd:
        lines.append(f"Price: ${card.prices.usd} (foil: ${card.prices.usd_foil or 'N/A'})")
    if card.edhrec_rank is not None:
        lines.append(f"EDHREC Rank: {card.edhrec_rank}")
    lines.append(f"Legalities: {_format_legalities(card.legalities)}")
    lines.append(f"Scryfall: {card.scryfall_uri}")
    return "\n".join(lines) + ATTRIBUTION_SCRYFALL


@scryfall_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_PRICING)
async def card_price(
    name: str,
) -> str:
    """Get current prices for a Magic card. Prices update once per day."""
    client = _get_client()
    try:
        card = await client.get_card_by_name(name)
    except CardNotFoundError as exc:
        raise ToolError(f"Card not found: '{name}'. Check spelling.") from exc
    except ScryfallError as exc:
        raise ToolError(f"Scryfall API error: {exc}") from exc

    lines = [f"**{card.name}** — Prices"]
    if card.prices.usd:
        lines.append(f"  USD: ${card.prices.usd}")
    if card.prices.usd_foil:
        lines.append(f"  USD (foil): ${card.prices.usd_foil}")
    if card.prices.eur:
        lines.append(f"  EUR: \u20ac{card.prices.eur}")
    if not any([card.prices.usd, card.prices.usd_foil, card.prices.eur]):
        lines.append("  No price data available.")
    return "\n".join(lines) + ATTRIBUTION_SCRYFALL


@scryfall_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_LOOKUP)
async def card_rulings(
    name: str,
) -> str:
    """Get official rulings and clarifications for a Magic card."""
    client = _get_client()
    try:
        card = await client.get_card_by_name(name)
        rulings = await client.get_rulings(card.id)
    except CardNotFoundError as exc:
        raise ToolError(f"Card not found: '{name}'. Check spelling.") from exc
    except ScryfallError as exc:
        raise ToolError(f"Scryfall API error: {exc}") from exc

    if not rulings:
        return f"**{card.name}** — No rulings available." + ATTRIBUTION_SCRYFALL

    lines = [f"**{card.name}** — {len(rulings)} ruling(s):"]
    for ruling in rulings:
        lines.append(f"  [{ruling.published_at}] {ruling.comment}")
    return "\n".join(lines) + ATTRIBUTION_SCRYFALL


def _format_legalities(legalities: dict[str, str]) -> str:
    """Format a legalities dict as a comma-separated list of legal format names."""
    legal = [fmt for fmt, status in legalities.items() if status == "legal"]
    if not legal:
        return "Not legal in any format"
    return ", ".join(legal)


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@scryfall_mcp.resource("mtg://card/{name}")
async def card_resource(name: str) -> str:
    """Get card data as JSON by exact name."""
    client = _get_client()
    try:
        card = await client.get_card_by_name(name)
        return card.model_dump_json()
    except CardNotFoundError:
        return json.dumps({"error": f"Card not found: {name}"})


@scryfall_mcp.resource("mtg://card/{name}/rulings")
async def card_rulings_resource(name: str) -> str:
    """Get card rulings as JSON by card name."""
    client = _get_client()
    try:
        card = await client.get_card_by_name(name)
        rulings = await client.get_rulings(card.id)
        return json.dumps([r.model_dump() for r in rulings])
    except CardNotFoundError:
        return json.dumps({"error": f"Card not found: {name}"})
