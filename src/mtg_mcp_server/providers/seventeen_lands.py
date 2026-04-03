"""17Lands MCP provider — draft card ratings and archetype statistics."""

from __future__ import annotations

import json
from typing import Annotated

import structlog
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.lifespan import lifespan
from fastmcp.tools.tool import ToolResult
from pydantic import Field

from mtg_mcp_server.config import Settings
from mtg_mcp_server.providers import ATTRIBUTION_17LANDS, TAGS_DRAFT, TOOL_ANNOTATIONS
from mtg_mcp_server.services.seventeen_lands import SeventeenLandsClient, SeventeenLandsError
from mtg_mcp_server.utils.formatters import ResponseFormat  # noqa: TC001 — runtime for FastMCP
from mtg_mcp_server.utils.slim import slim_rating

# Module-level client set by the lifespan. See scryfall.py for pattern rationale.
_client: SeventeenLandsClient | None = None


@lifespan
async def draft_lifespan(server: FastMCP):
    """Manage the SeventeenLandsClient lifecycle."""
    global _client
    settings = Settings()
    client = SeventeenLandsClient(base_url=settings.seventeen_lands_base_url)
    async with client:
        _client = client
        yield {}
    _client = None


draft_mcp = FastMCP("17Lands", lifespan=draft_lifespan, mask_error_details=True)

log = structlog.get_logger(provider="17lands")


def _get_client() -> SeventeenLandsClient:
    """Return the initialized client or raise if the lifespan hasn't started."""
    if _client is None:
        raise RuntimeError("SeventeenLandsClient not initialized — server lifespan not running")
    return _client


@draft_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_DRAFT)
async def card_ratings(
    set_code: Annotated[
        str, Field(description="Three-letter set code (e.g. 'LCI', 'MKM', 'OTJ', 'BLB')")
    ],
    event_type: Annotated[
        str, Field(description="Draft format — 'PremierDraft' (default) or 'TradDraft'")
    ] = "PremierDraft",
    limit: Annotated[int, Field(description="Max cards to return (default 50, 0 for all)")] = 50,
    sort_by: Annotated[
        str, Field(description="Sort order: 'gih_wr' (default), 'alsa', 'iwd', 'name'")
    ] = "gih_wr",
    response_format: Annotated[
        ResponseFormat,
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Get win rate and draft performance data for cards in a set.

    Key metrics: GIH WR (ever_drawn_win_rate), ALSA (avg_seen), OH WR
    (opening_hand_win_rate), IWD (drawn_improvement_win_rate).

    Note: 17Lands data skews toward above-average players (~56% baseline WR).
    Cards with <500 games may not have reliable data.
    """
    client = _get_client()
    try:
        ratings = await client.card_ratings(set_code, event_type=event_type)
    except SeventeenLandsError as exc:
        raise ToolError(f"17Lands API error: {exc}") from exc

    if not ratings:
        return ToolResult(
            content=f"No card rating data available for {set_code} ({event_type})."
            + ATTRIBUTION_17LANDS,
            structured_content={
                "set_code": set_code,
                "event_type": event_type,
                "total_cards": 0,
                "cards": [],
            },
        )

    sort_configs = {
        "gih_wr": (
            lambda c: c.ever_drawn_win_rate if c.ever_drawn_win_rate is not None else -1.0,
            True,
        ),
        "alsa": (lambda c: c.avg_seen if c.avg_seen is not None else 999.0, False),
        "iwd": (
            lambda c: (
                c.drawn_improvement_win_rate if c.drawn_improvement_win_rate is not None else -1.0
            ),
            True,
        ),
        "name": (lambda c: c.name.lower(), False),
    }
    if sort_by not in sort_configs:
        raise ToolError(
            f"Invalid sort_by: '{sort_by}'. Valid options: {', '.join(sorted(sort_configs))}"
        )
    key_fn, reverse = sort_configs[sort_by]
    sorted_ratings = sorted(ratings, key=key_fn, reverse=reverse)

    if limit < 0:
        raise ToolError(f"limit must be >= 0 (0 for all), got {limit}")
    total = len(sorted_ratings)
    cards = sorted_ratings if limit == 0 else sorted_ratings[:limit]
    showing = len(cards)

    lines = [
        f"Card ratings for {set_code} ({event_type}) — "
        f"showing {showing} of {total} cards (sorted by {sort_by}):"
    ]
    lines.append("")
    for card in cards:
        gih_wr = (
            f"{card.ever_drawn_win_rate:.1%}" if card.ever_drawn_win_rate is not None else "N/A"
        )
        alsa = f"{card.avg_seen:.1f}" if card.avg_seen is not None else "N/A"
        iwd = (
            f"{card.drawn_improvement_win_rate:+.1%}"
            if card.drawn_improvement_win_rate is not None
            else "N/A"
        )
        games = f"{card.game_count:,}"
        if response_format == "concise":
            lines.append(f"  {card.name} — GIH WR: {gih_wr}")
        else:
            lines.append(
                f"  {card.name} ({card.color}, {card.rarity}) — "
                f"GIH WR: {gih_wr}, ALSA: {alsa}, IWD: {iwd}, Games: {games}"
            )
    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_17LANDS,
        structured_content={
            "set_code": set_code,
            "event_type": event_type,
            "total_cards": total,
            "showing": showing,
            "full_data_uri": f"mtg://draft/{set_code}/ratings",
            "cards": [slim_rating(card) for card in cards],
        },
    )


@draft_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_DRAFT)
async def archetype_stats(
    set_code: Annotated[
        str, Field(description="Three-letter set code (e.g. 'LCI', 'MKM', 'OTJ', 'BLB')")
    ],
    start_date: Annotated[
        str, Field(description="Start date in YYYY-MM-DD format (required by 17Lands API)")
    ],
    end_date: Annotated[
        str, Field(description="End date in YYYY-MM-DD format (required by 17Lands API)")
    ],
    event_type: Annotated[
        str, Field(description="Draft format — 'PremierDraft' (default) or 'TradDraft'")
    ] = "PremierDraft",
) -> ToolResult:
    """Get win rates by color pair/archetype for a draft set.

    Note: start_date and end_date are required by the 17Lands API.

    Args:
        set_code: Three-letter set code (e.g. "LCI", "MKM", "OTJ").
        start_date: Start date in YYYY-MM-DD format.
        end_date: End date in YYYY-MM-DD format.
        event_type: Draft format — "PremierDraft" (default) or "TradDraft".
    """
    client = _get_client()
    try:
        ratings = await client.color_ratings(
            set_code, start_date=start_date, end_date=end_date, event_type=event_type
        )
    except SeventeenLandsError as exc:
        raise ToolError(f"17Lands API error: {exc}") from exc

    if not ratings:
        return ToolResult(
            content=f"No archetype data available for {set_code} ({event_type})."
            + ATTRIBUTION_17LANDS,
            structured_content={
                "set_code": set_code,
                "event_type": event_type,
                "start_date": start_date,
                "end_date": end_date,
                "total_archetypes": 0,
                "archetypes": [],
            },
        )

    lines = [f"Archetype stats for {set_code} ({event_type}, {start_date} to {end_date}):"]
    lines.append("")
    for arch in ratings:
        wr = f"{arch.win_rate:.1%}" if arch.win_rate is not None else "N/A"
        games = f"{arch.games:,}"
        prefix = "  [Summary] " if arch.is_summary else "  "
        lines.append(f"{prefix}{arch.color_name} — WR: {wr}, Games: {games}")
    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_17LANDS,
        structured_content={
            "set_code": set_code,
            "event_type": event_type,
            "start_date": start_date,
            "end_date": end_date,
            "total_archetypes": len(ratings),
            "archetypes": [
                {
                    "is_summary": arch.is_summary,
                    "color_name": arch.color_name,
                    "wins": arch.wins,
                    "games": arch.games,
                    "win_rate": arch.win_rate,
                }
                for arch in ratings
            ],
        },
    )


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@draft_mcp.resource("mtg://draft/{set_code}/ratings")
async def draft_ratings_resource(set_code: str) -> str:
    """Get card ratings for a set as JSON."""
    client = _get_client()
    try:
        ratings = await client.card_ratings(set_code)
        return json.dumps([r.model_dump() for r in ratings])
    except SeventeenLandsError as exc:
        log.warning("resource.ratings_error", set_code=set_code, error=str(exc))
        return json.dumps({"error": f"17Lands error: {exc}"})
