"""Scryfall MCP provider — card search, lookup, pricing, and rulings."""

from __future__ import annotations

from fastmcp import Context, FastMCP
from fastmcp.dependencies import CurrentContext, Depends
from fastmcp.exceptions import ToolError
from fastmcp.server.lifespan import lifespan
from mcp.types import ToolAnnotations

from mtg_mcp.services.scryfall import CardNotFoundError, ScryfallClient, ScryfallError

_ANNOTATIONS = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)


@lifespan
async def scryfall_lifespan(server: FastMCP):
    async with ScryfallClient() as client:
        yield {"scryfall_client": client}


scryfall_mcp = FastMCP("Scryfall", lifespan=scryfall_lifespan)


def get_client(ctx: Context = CurrentContext()) -> ScryfallClient:
    return ctx.lifespan_context["scryfall_client"]


@scryfall_mcp.tool(annotations=_ANNOTATIONS)
async def search_cards(
    query: str,
    page: int = 1,
    client: ScryfallClient = Depends(get_client),
) -> str:
    """Search for Magic cards using Scryfall syntax.

    Examples: "f:commander id:sultai t:creature", "o:destroy t:instant cmc<=3"
    See https://scryfall.com/docs/syntax for full syntax reference.
    """
    try:
        result = await client.search_cards(query, page=page)
    except CardNotFoundError:
        raise ToolError(f"No cards found for query: '{query}'. Check your search syntax.")
    except ScryfallError as exc:
        raise ToolError(f"Scryfall API error: {exc}")

    lines = [f"Found {result.total_cards} cards (showing {len(result.data)}, page {page}):"]
    for card in result.data:
        price = f" · ${card.prices.usd}" if card.prices.usd else ""
        lines.append(f"  {card.name} {card.mana_cost or ''} — {card.type_line}{price}")
    if result.has_more:
        lines.append(f"\nMore results available — use page={page + 1}")
    return "\n".join(lines)


@scryfall_mcp.tool(annotations=_ANNOTATIONS)
async def card_details(
    name: str,
    fuzzy: bool = False,
    client: ScryfallClient = Depends(get_client),
) -> str:
    """Get full details for a Magic card by exact or fuzzy name."""
    try:
        card = await client.get_card_by_name(name, fuzzy=fuzzy)
    except CardNotFoundError:
        raise ToolError(f"Card not found: '{name}'. Check spelling or try fuzzy=true.")
    except ScryfallError as exc:
        raise ToolError(f"Scryfall API error: {exc}")

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
    if card.edhrec_rank:
        lines.append(f"EDHREC Rank: {card.edhrec_rank}")
    lines.append(f"Legalities: {_format_legalities(card.legalities)}")
    lines.append(f"Scryfall: {card.scryfall_uri}")
    return "\n".join(lines)


@scryfall_mcp.tool(annotations=_ANNOTATIONS)
async def card_price(
    name: str,
    client: ScryfallClient = Depends(get_client),
) -> str:
    """Get current prices for a Magic card. Prices update once per day."""
    try:
        card = await client.get_card_by_name(name)
    except CardNotFoundError:
        raise ToolError(f"Card not found: '{name}'. Check spelling.")
    except ScryfallError as exc:
        raise ToolError(f"Scryfall API error: {exc}")

    lines = [f"**{card.name}** — Prices"]
    if card.prices.usd:
        lines.append(f"  USD: ${card.prices.usd}")
    if card.prices.usd_foil:
        lines.append(f"  USD (foil): ${card.prices.usd_foil}")
    if card.prices.eur:
        lines.append(f"  EUR: \u20ac{card.prices.eur}")
    if not any([card.prices.usd, card.prices.usd_foil, card.prices.eur]):
        lines.append("  No price data available.")
    return "\n".join(lines)


@scryfall_mcp.tool(annotations=_ANNOTATIONS)
async def card_rulings(
    name: str,
    client: ScryfallClient = Depends(get_client),
) -> str:
    """Get official rulings and clarifications for a Magic card."""
    try:
        card = await client.get_card_by_name(name)
        rulings = await client.get_rulings(card.id)
    except CardNotFoundError:
        raise ToolError(f"Card not found: '{name}'. Check spelling.")
    except ScryfallError as exc:
        raise ToolError(f"Scryfall API error: {exc}")

    if not rulings:
        return f"**{card.name}** — No rulings available."

    lines = [f"**{card.name}** — {len(rulings)} ruling(s):"]
    for ruling in rulings:
        lines.append(f"  [{ruling.published_at}] {ruling.comment}")
    return "\n".join(lines)


def _format_legalities(legalities: dict[str, str]) -> str:
    legal = [fmt for fmt, status in legalities.items() if status == "legal"]
    if not legal:
        return "Not legal in any format"
    return ", ".join(legal)
