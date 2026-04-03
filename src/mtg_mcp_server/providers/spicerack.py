"""Spicerack MCP provider -- tournament results and decklists.

Uses the Spicerack public REST API for competitive paper tournament data.
Behind the MTG_MCP_ENABLE_SPICERACK feature flag.
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
from mtg_mcp_server.providers import ATTRIBUTION_SPICERACK, TAGS_CONSTRUCTED, TOOL_ANNOTATIONS
from mtg_mcp_server.services.spicerack import InvalidFormatError, SpicerackClient, SpicerackError
from mtg_mcp_server.utils.formatters import ResponseFormat  # noqa: TC001 — runtime for FastMCP
from mtg_mcp_server.utils.slim import slim_standing, slim_tournament

# Module-level client set by the lifespan. See edhrec.py for pattern rationale.
_client: SpicerackClient | None = None


@lifespan
async def spicerack_lifespan(server: FastMCP):
    """Manage the SpicerackClient lifecycle."""
    global _client
    settings = Settings()
    client = SpicerackClient(
        base_url=settings.spicerack_base_url,
        api_key=settings.spicerack_api_key,
    )
    async with client:
        _client = client
        yield {}
    _client = None


spicerack_mcp = FastMCP("Spicerack", lifespan=spicerack_lifespan, mask_error_details=True)

log = structlog.get_logger(provider="spicerack")


def _get_client() -> SpicerackClient:
    """Return the initialized client or raise if the lifespan hasn't started."""
    if _client is None:
        raise RuntimeError("SpicerackClient not initialized — server lifespan not running")
    return _client


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@spicerack_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_CONSTRUCTED)
async def recent_tournaments(
    format: Annotated[
        str,
        Field(description="MTG format name (e.g. 'Modern', 'Legacy', 'Pauper')"),
    ],
    num_days: Annotated[
        int,
        Field(description="Number of days to look back (default 14)"),
    ] = 14,
    limit: Annotated[
        int,
        Field(description="Maximum number of tournaments to return (default 10)"),
    ] = 10,
    response_format: Annotated[
        ResponseFormat,
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """List recent tournaments for a format with dates, player counts, and IDs.

    Use the tournament ID from the results with ``tournament_results`` to
    see full standings and decklists.
    """
    client = _get_client()
    try:
        tournaments = await client.get_tournaments(num_days=num_days, event_format=format)
    except InvalidFormatError as exc:
        raise ToolError(f"Invalid format: '{format}'. Check the format name.") from exc
    except SpicerackError as exc:
        raise ToolError(f"Spicerack API error: {exc}") from exc

    tournaments = tournaments[:limit]

    if not tournaments:
        return ToolResult(
            content=f"No {format} tournaments found in the last {num_days} days."
            + ATTRIBUTION_SPICERACK,
            structured_content={"format": format, "tournaments": []},
        )

    lines: list[str] = [f"## Recent {format} Tournaments\n"]

    if response_format == "concise":
        for t in tournaments:
            lines.append(
                f"- **{t.name}** ({t.date}) — {t.player_count} players | ID: {t.tournament_id}"
            )
    else:
        lines.append("| Name | Date | Players | Standings | ID |")
        lines.append("|------|------|---------|-----------|-----|")
        for t in tournaments:
            lines.append(
                f"| {t.name} | {t.date} | {t.player_count} "
                f"| {len(t.standings)} | {t.tournament_id} |"
            )

    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_SPICERACK,
        structured_content={
            "format": format,
            "tournaments": [slim_tournament(t) for t in tournaments],
        },
    )


@spicerack_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_CONSTRUCTED)
async def tournament_results(
    tournament_id: Annotated[
        str,
        Field(description="Spicerack tournament ID (e.g. '3135276')"),
    ],
    format: Annotated[
        str | None,
        Field(description="Format to search within (optional, helps narrow results)"),
    ] = None,
    num_days: Annotated[
        int,
        Field(description="Number of days to look back (default 30)"),
    ] = 30,
    top_n: Annotated[
        int,
        Field(description="Number of top standings to show (default 8)"),
    ] = 8,
    response_format: Annotated[
        ResponseFormat,
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Get full standings and decklists for a specific tournament.

    Look up a tournament by its Spicerack ID. Use ``recent_tournaments``
    first to find tournament IDs.
    """
    client = _get_client()
    try:
        tournaments = await client.get_tournaments(num_days=num_days, event_format=format)
    except InvalidFormatError as exc:
        raise ToolError(f"Invalid format: '{format}'. Check the format name.") from exc
    except SpicerackError as exc:
        raise ToolError(f"Spicerack API error: {exc}") from exc

    # Find the specific tournament
    tournament = None
    for t in tournaments:
        if t.tournament_id == tournament_id:
            tournament = t
            break

    if tournament is None:
        raise ToolError(
            f"Tournament not found: '{tournament_id}'. Check the ID or try a longer num_days range."
        )

    standings = tournament.standings[:top_n]

    lines: list[str] = [f"## {tournament.name}\n"]

    if response_format == "concise":
        lines.append(f"{tournament.date} | {tournament.player_count} players\n")
    else:
        lines.append(f"**Date:** {tournament.date}")
        lines.append(f"**Format:** {tournament.format}")
        lines.append(f"**Players:** {tournament.player_count}")
        lines.append(f"**Swiss Rounds:** {tournament.rounds_swiss}")
        if tournament.top_cut > 0:
            lines.append(f"**Top Cut:** {tournament.top_cut}")
        lines.append("")

    # Standings table
    lines.append("| Rank | Player | Record | Bracket | Decklist |")
    lines.append("|------|--------|--------|---------|----------|")
    for s in standings:
        record = f"{s.wins}-{s.losses}-{s.draws}"
        bracket = ""
        if s.bracket_wins > 0 or s.bracket_losses > 0:
            bracket = f"{s.bracket_wins}-{s.bracket_losses}"
        decklist = f"[Link]({s.decklist_url})" if s.decklist_url else "\u2014"
        lines.append(f"| {s.rank} | {s.player_name} | {record} | {bracket} | {decklist} |")

    structured: dict = {
        "tournament_id": tournament.tournament_id,
        "name": tournament.name,
        "format": tournament.format,
        "date": tournament.date,
        "player_count": tournament.player_count,
        "rounds_swiss": tournament.rounds_swiss,
        "top_cut": tournament.top_cut,
        "standings": [slim_standing(s) for s in standings],
    }

    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_SPICERACK,
        structured_content=structured,
    )


@spicerack_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_CONSTRUCTED)
async def format_decklists(
    format: Annotated[
        str,
        Field(description="MTG format name (e.g. 'Modern', 'Legacy', 'Pauper')"),
    ],
    num_days: Annotated[
        int,
        Field(description="Number of days to look back (default 14)"),
    ] = 14,
    limit: Annotated[
        int,
        Field(description="Maximum number of decklists to return (default 10)"),
    ] = 10,
    response_format: Annotated[
        ResponseFormat,
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Find top-performing decklists across recent tournaments for a format.

    Collects top-4 finishers with Moxfield decklists from recent events.
    Use ``moxfield_decklist`` to fetch the full card list for a deck.
    """
    client = _get_client()
    try:
        tournaments = await client.get_tournaments(num_days=num_days, event_format=format)
    except InvalidFormatError as exc:
        raise ToolError(f"Invalid format: '{format}'. Check the format name.") from exc
    except SpicerackError as exc:
        raise ToolError(f"Spicerack API error: {exc}") from exc

    # Collect top-4 standings with decklists from all tournaments
    decklists: list[dict] = []
    for t in tournaments:
        for s in t.standings:
            if s.rank <= 4 and s.decklist_url:
                decklists.append(
                    {
                        "player": s.player_name,
                        "rank": s.rank,
                        "record": f"{s.wins}-{s.losses}-{s.draws}",
                        "tournament": t.name,
                        "tournament_date": t.date,
                        "decklist_url": s.decklist_url,
                    }
                )

    # Sort by rank (best first), then truncate
    decklists.sort(key=lambda d: d["rank"])
    decklists = decklists[:limit]

    if not decklists:
        return ToolResult(
            content=f"No decklists available for {format} tournaments "
            f"in the last {num_days} days." + ATTRIBUTION_SPICERACK,
            structured_content={"format": format, "decklists": []},
        )

    lines: list[str] = [f"## Top {format} Decklists\n"]

    for d in decklists:
        if response_format == "concise":
            lines.append(f"- **{d['player']}** ({d['record']}) — {d['decklist_url']}")
        else:
            lines.append(
                f"- **{d['player']}** ({d['record']}) "
                f"at {d['tournament']} — [Decklist]({d['decklist_url']})"
            )

    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_SPICERACK,
        structured_content={"format": format, "decklists": decklists},
    )


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@spicerack_mcp.resource("mtg://tournament/{event_format}/recent")
async def get_recent_tournaments(event_format: str) -> str:
    """Recent tournament data as JSON for a format."""
    client = _get_client()
    try:
        tournaments = await client.get_tournaments(event_format=event_format)
        return json.dumps(
            [t.model_dump() for t in tournaments],
            default=str,
        )
    except InvalidFormatError:
        log.debug("resource.invalid_format", format=event_format)
        return json.dumps({"error": f"Invalid format: {event_format}"})
    except SpicerackError as exc:
        log.warning("resource.tournament_error", format=event_format, error=str(exc))
        return json.dumps({"error": f"Spicerack error: {exc}"})
