"""Scryfall bulk data MCP provider -- rate-limit-free card lookup and search.

Uses Scryfall's Oracle Cards bulk file for rate-limit-free in-memory card data
including prices, legalities, and EDHREC rank.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated, Literal

import structlog
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.lifespan import lifespan
from pydantic import Field

from mtg_mcp_server.config import Settings
from mtg_mcp_server.providers import (
    ATTRIBUTION_SCRYFALL_BULK,
    TAGS_ALL_FORMATS,
    TAGS_LOOKUP,
    TAGS_SEARCH,
    TAGS_VALIDATE,
    TOOL_ANNOTATIONS,
    format_legalities,
)
from mtg_mcp_server.services.scryfall_bulk import ScryfallBulkClient, ScryfallBulkError
from mtg_mcp_server.utils.color_identity import is_within_identity, parse_color_identity
from mtg_mcp_server.utils.query_parser import parse_query

# Lightweight format alias map — maps common abbreviations to Scryfall legality
# keys. Unlike utils.format_rules.normalize_format, this does NOT reject unknown
# formats so it can pass through any Scryfall legality key (historic, alchemy, etc.).
_FORMAT_ALIASES: dict[str, str] = {
    "edh": "commander",
    "cedh": "commander",
    "cmdr": "commander",
    "draft": "limited",
    "sealed": "limited",
}


def normalize_format(raw: str) -> str:
    """Normalize a format name for Scryfall legality lookup (no validation)."""
    lowered = raw.strip().lower()
    return _FORMAT_ALIASES.get(lowered, lowered)


if TYPE_CHECKING:
    from mtg_mcp_server.types import Card

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


def _format_card_detail(card: Card) -> list[str]:
    """Build the standard card detail lines used by card_lookup and random_card."""
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
    lines.append(f"Legalities: {format_legalities(card.legalities)}")
    return lines


def _score_similarity(source: Card, candidate: Card) -> float:
    """Score how similar a candidate card is to a source card."""
    source_keywords = {k.lower() for k in source.keywords}
    source_type_words = {
        w.lower() for w in source.type_line.replace("\u2014", " ").split() if len(w) > 2
    }
    source_text_words: set[str] = set()
    if source.oracle_text:
        source_text_words = {
            w.lower()
            for w in source.oracle_text.replace(",", " ").replace(".", " ").split()
            if len(w) > 4
        }

    score = 0.0
    if candidate.keywords:
        card_keywords = {k.lower() for k in candidate.keywords}
        score += len(source_keywords & card_keywords) * 2.0
    card_type_words = {
        w.lower() for w in candidate.type_line.replace("\u2014", " ").split() if len(w) > 2
    }
    score += len(source_type_words & card_type_words) * 1.5
    if abs(candidate.cmc - source.cmc) <= 1:
        score += 1.0
    if candidate.oracle_text and source_text_words:
        card_text_words = {
            w.lower()
            for w in candidate.oracle_text.replace(",", " ").replace(".", " ").split()
            if len(w) > 4
        }
        score += len(source_text_words & card_text_words) * 1.0
    return score


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

    return "\n".join(_format_card_detail(card)) + ATTRIBUTION_SCRYFALL_BULK


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


# Preferred format display order for card_in_formats.
_FORMAT_DISPLAY_ORDER = [
    "standard",
    "pioneer",
    "modern",
    "legacy",
    "vintage",
    "commander",
    "pauper",
]


# ---------------------------------------------------------------------------
# Cross-format tools
# ---------------------------------------------------------------------------


@scryfall_bulk_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_VALIDATE)
async def format_legality(
    cards: Annotated[
        list[str],
        Field(description="List of card names to check legality for"),
    ],
    format: Annotated[
        str,
        Field(description="Format to check (e.g. 'commander', 'modern', 'standard', 'legacy')"),
    ],
) -> str:
    """Batch legality check for cards in a specific format.

    Returns a markdown table showing the legality status of each card
    in the specified format. Handles common format aliases (e.g. 'edh'
    for 'commander').
    """
    if not cards:
        raise ToolError("Provide at least one card name to check.")

    client = _get_client()
    fmt = normalize_format(format)

    try:
        resolved = await client.get_cards(cards)
    except ScryfallBulkError as exc:
        raise ToolError(f"Scryfall bulk data error: {exc}") from exc

    lines = [f"## Legality Check: {fmt.title()}", "", "| Card | Status |", "|------|--------|"]

    for name in cards:
        card = resolved.get(name)
        if card is None:
            lines.append(f"| {name} | Not Found |")
        else:
            status = card.legalities.get(fmt, "unknown")
            display_status = status.replace("_", " ").title()
            lines.append(f"| {card.name} | {display_status} |")

    return "\n".join(lines) + ATTRIBUTION_SCRYFALL_BULK


@scryfall_bulk_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_SEARCH)
async def format_search(
    format: Annotated[
        str,
        Field(description="Format to search in (e.g. 'commander', 'modern', 'standard')"),
    ],
    query: Annotated[
        str,
        Field(
            description="Search query -- card name, type, or oracle text substring (e.g. 'flying creatures', 'destroy target')"
        ),
    ],
    color_identity: Annotated[
        str | None,
        Field(
            description="Color identity filter (e.g. 'sultai', 'WU', 'red'). Only returns cards within this identity."
        ),
    ] = None,
    max_price: Annotated[
        float | None,
        Field(description="Maximum USD price filter"),
    ] = None,
    rarity: Annotated[
        str | None,
        Field(description="Rarity filter (e.g. 'common', 'uncommon', 'rare', 'mythic')"),
    ] = None,
    limit: Annotated[int, Field(description="Maximum results to return")] = 20,
) -> str:
    """Search for legal cards in a specific format using natural language.

    Combines format legality filtering with name/type/text search and
    optional color identity, price, and rarity constraints. Results are
    sorted by EDHREC rank (most popular first).
    """
    if not query.strip():
        raise ToolError("Provide a search query.")

    client = _get_client()
    fmt = normalize_format(format)
    try:
        identity = parse_color_identity(color_identity) if color_identity else None
    except ValueError as exc:
        raise ToolError(str(exc)) from exc

    try:
        all_cards = await client.all_cards()
    except ScryfallBulkError as exc:
        raise ToolError(f"Scryfall bulk data error: {exc}") from exc

    # Parse natural language into structured filters
    parsed = parse_query(query)

    # Pre-lowercase parsed terms to avoid re-lowering per card
    type_lower_terms = [t.lower() for t in parsed.type_contains] if parsed.type_contains else None
    text_any_lower = [p.lower() for p in parsed.text_any] if parsed.text_any else None
    text_contains_lower = (
        [t.lower() for t in parsed.text_contains] if parsed.text_contains else None
    )
    rarity_lower = rarity.lower() if rarity else None

    MAX_CANDIDATES = 5000  # Cap accumulation for very broad queries
    matches: list[Card] = []
    for card in all_cards:
        # Format legality check
        if card.legalities.get(fmt) != "legal":
            continue
        # Color identity check
        if identity is not None and not is_within_identity(card.color_identity, identity):
            continue
        # Price check
        if max_price is not None:
            price_str = card.prices.usd
            if price_str is None:
                continue
            try:
                if float(price_str) > max_price:
                    continue
            except ValueError:
                continue
        # Rarity check
        if rarity_lower is not None and card.rarity.lower() != rarity_lower:
            continue
        # CMC checks from parsed query
        if parsed.cmc_eq is not None and card.cmc != parsed.cmc_eq:
            continue
        if parsed.cmc_lte is not None and card.cmc > parsed.cmc_lte:
            continue
        # Type check from parsed query
        if type_lower_terms is not None:
            type_lower = card.type_line.lower()
            if not all(t in type_lower for t in type_lower_terms):
                continue
        # Text matching -- use parsed filters
        oracle_lower = (card.oracle_text or "").lower()
        if text_any_lower is not None and not any(p in oracle_lower for p in text_any_lower):
            continue
        if text_contains_lower is not None:
            name_lower = card.name.lower()
            type_lower_text = card.type_line.lower()
            if not all(
                t in name_lower or t in type_lower_text or t in oracle_lower
                for t in text_contains_lower
            ):
                continue

        matches.append(card)
        if len(matches) >= MAX_CANDIDATES:
            break

    if not matches:
        raise ToolError(
            f"No legal {fmt} cards found matching '{query}'"
            + (f" in {color_identity}" if color_identity else "")
            + "."
        )

    # Sort by EDHREC rank (lower = more popular), None last
    matches.sort(key=lambda c: (c.edhrec_rank is None, c.edhrec_rank or 0))
    matches = matches[:limit]

    desc = parsed.description or query
    lines = [f"## {fmt.title()} Cards: {desc}"]
    if color_identity:
        lines[0] += f" ({color_identity})"
    lines.append(f"Found {len(matches)} result(s):")
    lines.append("")
    for card in matches:
        cost = f" {card.mana_cost}" if card.mana_cost else ""
        price = f" (${card.prices.usd})" if card.prices.usd else ""
        lines.append(f"  {card.name}{cost} -- {card.type_line}{price}")

    return "\n".join(lines) + ATTRIBUTION_SCRYFALL_BULK


@scryfall_bulk_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_SEARCH)
async def format_staples(
    format: Annotated[
        str,
        Field(description="Format to find staples for (e.g. 'commander', 'modern', 'legacy')"),
    ],
    color: Annotated[
        str | None,
        Field(
            description="Color identity filter (e.g. 'sultai', 'WU', 'red'). Only returns cards within this identity."
        ),
    ] = None,
    card_type: Annotated[
        str | None,
        Field(description="Card type filter (e.g. 'creature', 'instant', 'land')"),
    ] = None,
    limit: Annotated[int, Field(description="Maximum results to return")] = 20,
) -> str:
    """Find the most popular (staple) cards legal in a format.

    Returns cards sorted by EDHREC rank (most popular first). Cards
    without a rank are excluded. Optionally filter by color identity
    and card type.
    """
    client = _get_client()
    fmt = normalize_format(format)
    try:
        identity = parse_color_identity(color) if color else None
    except ValueError as exc:
        raise ToolError(str(exc)) from exc

    try:
        all_cards = await client.all_cards()
    except ScryfallBulkError as exc:
        raise ToolError(f"Scryfall bulk data error: {exc}") from exc

    matches: list[Card] = []
    for card in all_cards:
        if card.legalities.get(fmt) != "legal":
            continue
        if card.edhrec_rank is None:
            continue
        if identity is not None and not is_within_identity(card.color_identity, identity):
            continue
        if card_type is not None and card_type.lower() not in card.type_line.lower():
            continue
        matches.append(card)

    if not matches:
        raise ToolError(f"No staples found for {fmt}" + (f" ({color})" if color else "") + ".")

    matches.sort(key=lambda c: c.edhrec_rank or 0)
    matches = matches[:limit]

    lines = [f"## {fmt.title()} Staples"]
    if color:
        lines[0] += f" ({color})"
    if card_type:
        lines[0] += f" -- {card_type.title()}"
    lines.append("")
    lines.append("| Rank | Card | Mana Cost | Type |")
    lines.append("|------|------|-----------|------|")
    for card in matches:
        cost = card.mana_cost or ""
        lines.append(f"| #{card.edhrec_rank} | {card.name} | {cost} | {card.type_line} |")

    return "\n".join(lines) + ATTRIBUTION_SCRYFALL_BULK


@scryfall_bulk_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_SEARCH)
async def similar_cards(
    card_name: Annotated[
        str,
        Field(description="Name of the card to find similar cards for"),
    ],
    format: Annotated[
        str | None,
        Field(description="Format filter (e.g. 'commander', 'modern'). Only returns legal cards."),
    ] = None,
    max_price: Annotated[
        float | None,
        Field(description="Maximum USD price filter"),
    ] = None,
    limit: Annotated[int, Field(description="Maximum results to return")] = 10,
) -> str:
    """Find cards similar to a given card.

    Scores similarity based on shared keywords, type words, CMC
    proximity, and oracle text overlap. Optionally filter by format
    legality and price.
    """
    client = _get_client()

    try:
        source = await client.get_card(card_name)
        all_cards = await client.all_cards()
    except ScryfallBulkError as exc:
        raise ToolError(f"Scryfall bulk data error: {exc}") from exc

    if source is None:
        raise ToolError(f"Card not found: '{card_name}'. Check spelling.")

    fmt = normalize_format(format) if format else None

    scored: list[tuple[float, Card]] = []
    source_name_lower = source.name.lower()

    for card in all_cards:
        if card.name.lower() == source_name_lower:
            continue
        if fmt and card.legalities.get(fmt) != "legal":
            continue
        if max_price is not None:
            price_str = card.prices.usd
            if price_str is None:
                continue
            try:
                if float(price_str) > max_price:
                    continue
            except ValueError:
                continue

        score = _score_similarity(source, card)
        if score > 0:
            scored.append((score, card))

    if not scored:
        raise ToolError(f"No similar cards found for '{source.name}'.")

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:limit]

    lines = [
        f"## Cards Similar to {source.name}",
        f"*{source.mana_cost or 'No cost'} -- {source.type_line}*",
        "",
    ]
    for score, card in top:
        cost = f" {card.mana_cost}" if card.mana_cost else ""
        price = f" (${card.prices.usd})" if card.prices.usd else ""
        lines.append(f"  {card.name}{cost} -- {card.type_line}{price} [score: {score:.1f}]")

    return "\n".join(lines) + ATTRIBUTION_SCRYFALL_BULK


@scryfall_bulk_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_LOOKUP)
async def random_card(
    format: Annotated[
        str | None,
        Field(description="Format filter (e.g. 'commander', 'modern'). Only returns legal cards."),
    ] = None,
    color_identity: Annotated[
        str | None,
        Field(
            description="Color identity filter (e.g. 'sultai', 'WU', 'red'). Only returns cards within this identity."
        ),
    ] = None,
    card_type: Annotated[
        str | None,
        Field(description="Card type filter (e.g. 'creature', 'instant', 'land')"),
    ] = None,
    rarity: Annotated[
        str | None,
        Field(description="Rarity filter (e.g. 'common', 'uncommon', 'rare', 'mythic')"),
    ] = None,
) -> str:
    """Get a random Magic card, optionally filtered by format, color, type, and rarity.

    Returns full card details in the same format as card_lookup.
    """
    client = _get_client()
    fmt = normalize_format(format) if format else None
    try:
        identity = parse_color_identity(color_identity) if color_identity else None
    except ValueError as exc:
        raise ToolError(str(exc)) from exc

    try:
        card = await client.random_card(
            format=fmt,
            color_identity=identity,
            type_contains=card_type,
            rarity=rarity.lower() if rarity else None,
        )
    except ScryfallBulkError as exc:
        raise ToolError(f"Scryfall bulk data error: {exc}") from exc

    if card is None:
        raise ToolError("No cards match the specified filters.")

    return "\n".join(_format_card_detail(card)) + ATTRIBUTION_SCRYFALL_BULK


@scryfall_bulk_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_ALL_FORMATS)
async def ban_list(
    format: Annotated[
        str,
        Field(description="Format to check ban list for (e.g. 'commander', 'modern', 'standard')"),
    ],
) -> str:
    """Get the banned and restricted cards for a format.

    Returns alphabetically sorted lists of banned and restricted cards,
    including their type lines.
    """
    if not format.strip():
        raise ToolError("Provide a format name.")

    client = _get_client()
    fmt = normalize_format(format)

    try:
        banned = await client.cards_by_legality(fmt, "banned")
        restricted = await client.cards_by_legality(fmt, "restricted")
    except ScryfallBulkError as exc:
        raise ToolError(f"Scryfall bulk data error: {exc}") from exc

    banned.sort(key=lambda c: c.name)
    restricted.sort(key=lambda c: c.name)

    lines = [f"## {fmt.title()} Ban List"]

    if banned:
        lines.append("")
        lines.append(f"### Banned ({len(banned)} cards)")
        lines.append("")
        for card in banned:
            lines.append(f"  - **{card.name}** -- {card.type_line}")
    else:
        lines.append("")
        lines.append("No banned cards in this format.")

    if restricted:
        lines.append("")
        lines.append(f"### Restricted ({len(restricted)} cards)")
        lines.append("")
        for card in restricted:
            lines.append(f"  - **{card.name}** -- {card.type_line}")

    if not banned and not restricted:
        lines[-1] = "No banned or restricted cards in this format."

    return "\n".join(lines) + ATTRIBUTION_SCRYFALL_BULK


@scryfall_bulk_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_LOOKUP)
async def card_in_formats(
    card_name: Annotated[
        str,
        Field(description="Card name to check format legality for"),
    ],
) -> str:
    """Show a card's legality across all Magic formats.

    Returns a table with the card's legality status in each format,
    ordered with the most common formats first.
    """
    client = _get_client()

    try:
        card = await client.get_card(card_name)
    except ScryfallBulkError as exc:
        raise ToolError(f"Scryfall bulk data error: {exc}") from exc

    if card is None:
        raise ToolError(f"Card not found: '{card_name}'. Check spelling.")

    lines = [
        f"## {card.name} -- Format Legality",
        f"*{card.type_line}*",
    ]
    if card.prices.usd:
        lines.append(f"Price: ${card.prices.usd}")
    lines.append("")
    lines.append("| Format | Status |")
    lines.append("|--------|--------|")

    # Show priority formats first, then the rest alphabetically
    seen: set[str] = set()
    for fmt in _FORMAT_DISPLAY_ORDER:
        if fmt in card.legalities:
            status = card.legalities[fmt].replace("_", " ").title()
            lines.append(f"| {fmt.title()} | {status} |")
            seen.add(fmt)

    for fmt in sorted(card.legalities.keys()):
        if fmt not in seen:
            status = card.legalities[fmt].replace("_", " ").title()
            lines.append(f"| {fmt.title()} | {status} |")

    return "\n".join(lines) + ATTRIBUTION_SCRYFALL_BULK


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@scryfall_bulk_mcp.resource("mtg://format/{format}/legal-cards")
async def format_legal_cards_resource(format: str) -> str:
    """Count of legal cards in a format as JSON."""
    client = _get_client()
    fmt = normalize_format(format)
    try:
        legal = await client.cards_by_legality(fmt, "legal")
    except ScryfallBulkError as exc:
        log.warning("resource.format_legal_cards_error", format=fmt, error=str(exc))
        return json.dumps({"error": f"Scryfall bulk data error: {exc}"})

    return json.dumps({"format": fmt, "legal_card_count": len(legal)})


@scryfall_bulk_mcp.resource("mtg://format/{format}/banned")
async def format_banned_resource(format: str) -> str:
    """Banned card list for a format as JSON."""
    client = _get_client()
    fmt = normalize_format(format)
    try:
        banned_cards = await client.cards_by_legality(fmt, "banned")
    except ScryfallBulkError as exc:
        log.warning("resource.format_banned_error", format=fmt, error=str(exc))
        return json.dumps({"error": f"Scryfall bulk data error: {exc}"})

    banned = [{"name": c.name, "type_line": c.type_line} for c in banned_cards]
    banned.sort(key=lambda c: c["name"])
    return json.dumps(banned)


@scryfall_bulk_mcp.resource("mtg://card/{name}/formats")
async def card_formats_resource(name: str) -> str:
    """Card legality map as JSON."""
    client = _get_client()
    try:
        card = await client.get_card(name)
    except ScryfallBulkError as exc:
        log.warning("resource.card_formats_error", name=name, error=str(exc))
        return json.dumps({"error": f"Scryfall bulk data error: {exc}"})
    if card is None:
        return json.dumps({"error": f"Card not found: {name}"})
    return json.dumps(card.legalities)


@scryfall_bulk_mcp.resource("mtg://card/{name}/similar")
async def card_similar_resource(name: str) -> str:
    """Similar cards as JSON (top 10 by similarity score)."""
    client = _get_client()
    try:
        source = await client.get_card(name)
        all_cards = await client.all_cards()
    except ScryfallBulkError as exc:
        log.warning("resource.card_similar_error", name=name, error=str(exc))
        return json.dumps({"error": f"Scryfall bulk data error: {exc}"})
    if source is None:
        return json.dumps({"error": f"Card not found: {name}"})

    scored: list[tuple[float, Card]] = []
    source_name_lower = source.name.lower()

    for card in all_cards:
        if card.name.lower() == source_name_lower:
            continue
        score = _score_similarity(source, card)
        if score > 0:
            scored.append((score, card))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:10]

    result = [{"name": c.name, "score": round(s, 1)} for s, c in top]
    return json.dumps(result)


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
