"""MTGGoldfish metagame data provider — format metagame, archetypes, staples.

Scrapes MTGGoldfish HTML pages. Behind the MTG_MCP_ENABLE_MTGGOLDFISH feature flag.
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
from mtg_mcp_server.providers import ATTRIBUTION_MTGGOLDFISH, TAGS_BETA, TOOL_ANNOTATIONS
from mtg_mcp_server.services.mtggoldfish import (
    ArchetypeNotFoundError,
    FormatNotFoundError,
    MTGGoldfishClient,
    MTGGoldfishError,
)
from mtg_mcp_server.utils.formatters import ResponseFormat  # noqa: TC001 — runtime for FastMCP
from mtg_mcp_server.utils.slim import slim_archetype, slim_format_staple

# Module-level client set by the lifespan. See edhrec.py for pattern rationale.
_client: MTGGoldfishClient | None = None


@lifespan
async def mtggoldfish_lifespan(server: FastMCP):
    """Manage the MTGGoldfishClient lifecycle."""
    global _client
    settings = Settings()
    client = MTGGoldfishClient(base_url=settings.mtggoldfish_base_url)
    async with client:
        _client = client
        yield {}
    _client = None


mtggoldfish_mcp = FastMCP("MTGGoldfish", lifespan=mtggoldfish_lifespan, mask_error_details=True)

log = structlog.get_logger(provider="mtggoldfish")


def _get_client() -> MTGGoldfishClient:
    """Return the initialized client or raise if the lifespan hasn't started."""
    if _client is None:
        raise RuntimeError("MTGGoldfishClient not initialized — server lifespan not running")
    return _client


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mtggoldfish_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_BETA)
async def metagame(
    format: Annotated[
        str,
        Field(description="MTG format name (e.g. 'Modern', 'Legacy', 'Pioneer', 'Pauper')"),
    ],
    response_format: Annotated[
        ResponseFormat,
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Get the current metagame breakdown for a competitive format.

    Shows top archetypes with meta share percentages, deck counts, and
    estimated paper prices.
    """
    client = _get_client()
    try:
        snapshot = await client.get_metagame(format)
    except FormatNotFoundError as exc:
        raise ToolError(f"Format not found: '{format}'. Check the format name.") from exc
    except MTGGoldfishError as exc:
        raise ToolError(f"MTGGoldfish error: {exc}") from exc

    if not snapshot.archetypes:
        return ToolResult(
            content=f"No metagame data available for {format}." + ATTRIBUTION_MTGGOLDFISH,
            structured_content={"format": format, "archetypes": [], "total_decks": 0},
        )

    lines: list[str] = [f"## {format} Metagame\n"]

    if response_format == "concise":
        for a in snapshot.archetypes:
            lines.append(f"- **{a.name}** — {a.meta_share:.1f}% ({a.deck_count} decks)")
    else:
        lines.append("| Rank | Archetype | Meta % | Decks | Price |")
        lines.append("|------|-----------|--------|-------|-------|")
        for i, a in enumerate(snapshot.archetypes, 1):
            price_str = f"${a.price_paper:,}" if a.price_paper > 0 else "N/A"
            lines.append(f"| {i} | {a.name} | {a.meta_share:.1f}% | {a.deck_count} | {price_str} |")

    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_MTGGOLDFISH,
        structured_content={
            "format": format,
            "archetypes": [slim_archetype(a) for a in snapshot.archetypes],
            "total_decks": snapshot.total_decks,
        },
    )


@mtggoldfish_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_BETA)
async def archetype_list(
    format: Annotated[
        str,
        Field(description="MTG format name (e.g. 'Modern', 'Legacy', 'Pioneer')"),
    ],
    archetype: Annotated[
        str,
        Field(description="Archetype name (e.g. 'Boros Energy', 'Azorius Control')"),
    ],
    response_format: Annotated[
        ResponseFormat,
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Get a sample decklist for an archetype in a format.

    Returns deck metadata (author, event, result, date) and the full
    mainboard and sideboard card list.
    """
    client = _get_client()
    try:
        detail = await client.get_archetype(format, archetype)
    except ArchetypeNotFoundError as exc:
        raise ToolError(
            f"Archetype not found: '{archetype}' in {format}. Check the archetype name."
        ) from exc
    except FormatNotFoundError as exc:
        raise ToolError(f"Format not found: '{format}'. Check the format name.") from exc
    except MTGGoldfishError as exc:
        raise ToolError(f"MTGGoldfish error: {exc}") from exc

    lines: list[str] = [f"## {detail.name}\n"]

    if response_format == "concise":
        if detail.event:
            lines.append(f"{detail.result} at {detail.event} ({detail.date})")
    else:
        if detail.author:
            lines.append(f"**Author:** {detail.author}")
        if detail.event:
            lines.append(f"**Event:** {detail.event}")
        if detail.result:
            lines.append(f"**Result:** {detail.result}")
        if detail.date:
            lines.append(f"**Date:** {detail.date}")
        lines.append("")

    # Mainboard
    if detail.mainboard:
        lines.append("### Mainboard")
        for card in detail.mainboard:
            lines.append(f"- {card}")

    # Sideboard
    if detail.sideboard:
        lines.append("\n### Sideboard")
        for card in detail.sideboard:
            lines.append(f"- {card}")

    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_MTGGOLDFISH,
        structured_content=detail.model_dump(),
    )


@mtggoldfish_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_BETA)
async def format_staples(
    format: Annotated[
        str,
        Field(description="MTG format name (e.g. 'Modern', 'Legacy', 'Pioneer')"),
    ],
    limit: Annotated[
        int,
        Field(description="Maximum number of staples to return (default 20)"),
    ] = 20,
    response_format: Annotated[
        ResponseFormat,
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Get the most-played cards in a format with deck inclusion percentages.

    Shows which cards appear most frequently across all archetypes in
    the format, with average copies played per deck.
    """
    client = _get_client()
    try:
        staples = await client.get_format_staples(format, limit)
    except FormatNotFoundError as exc:
        raise ToolError(f"Format not found: '{format}'. Check the format name.") from exc
    except MTGGoldfishError as exc:
        raise ToolError(f"MTGGoldfish error: {exc}") from exc

    if not staples:
        return ToolResult(
            content=f"No staple data available for {format}." + ATTRIBUTION_MTGGOLDFISH,
            structured_content={"format": format, "staples": []},
        )

    lines: list[str] = [f"## {format} Format Staples\n"]

    if response_format == "concise":
        for s in staples:
            lines.append(f"- **{s.name}** — {s.pct_of_decks:.1f}% of decks")
    else:
        lines.append("| Rank | Card | % of Decks | Avg Copies |")
        lines.append("|------|------|------------|------------|")
        for s in staples:
            lines.append(f"| {s.rank} | {s.name} | {s.pct_of_decks:.1f}% | {s.copies_played:.1f} |")

    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_MTGGOLDFISH,
        structured_content={
            "format": format,
            "staples": [slim_format_staple(s) for s in staples],
        },
    )


@mtggoldfish_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_BETA)
async def deck_price(
    format: Annotated[
        str,
        Field(description="MTG format name (e.g. 'Modern', 'Legacy', 'Pioneer')"),
    ],
    archetype: Annotated[
        str,
        Field(description="Archetype name (e.g. 'Boros Energy', 'Azorius Control')"),
    ],
    response_format: Annotated[
        ResponseFormat,
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Get the estimated paper price for an archetype deck.

    Returns the total estimated cost of the deck based on current card
    prices from MTGGoldfish.
    """
    client = _get_client()
    try:
        price_data = await client.get_deck_price(format, archetype)
    except ArchetypeNotFoundError as exc:
        raise ToolError(
            f"Archetype not found: '{archetype}' in {format}. Check the archetype name."
        ) from exc
    except FormatNotFoundError as exc:
        raise ToolError(f"Format not found: '{format}'. Check the format name.") from exc
    except MTGGoldfishError as exc:
        raise ToolError(f"MTGGoldfish error: {exc}") from exc

    archetype_name = price_data.get("archetype", archetype)
    price_paper = price_data.get("price_paper", 0)
    card_count = price_data.get("mainboard_count", 0) + price_data.get("sideboard_count", 0)

    lines: list[str] = [f"## {archetype_name} — Price Estimate\n"]

    if response_format == "concise":
        lines.append(f"**${price_paper:,}** ({card_count} cards)")
    else:
        lines.append(f"**Archetype:** {archetype_name}")
        lines.append(f"**Estimated Price:** ${price_paper:,}")
        if card_count > 0:
            lines.append(f"**Card Count:** {card_count}")

    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_MTGGOLDFISH,
        structured_content=price_data,
    )


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@mtggoldfish_mcp.resource("mtg://metagame/{format}")
async def metagame_resource(format: str) -> str:
    """Metagame data as JSON for a format."""
    client = _get_client()
    try:
        snapshot = await client.get_metagame(format)
        return snapshot.model_dump_json()
    except FormatNotFoundError:
        log.debug("resource.format_not_found", format=format)
        return json.dumps({"error": f"Format not found: {format}"})
    except MTGGoldfishError as exc:
        log.warning("resource.metagame_error", format=format, error=str(exc))
        return json.dumps({"error": f"MTGGoldfish error: {exc}"})
