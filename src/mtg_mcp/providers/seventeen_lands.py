"""17Lands MCP provider — draft card ratings and archetype statistics."""

from __future__ import annotations

import json

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.lifespan import lifespan

from mtg_mcp.config import Settings
from mtg_mcp.providers import TAGS_DRAFT, TOOL_ANNOTATIONS
from mtg_mcp.services.seventeen_lands import SeventeenLandsClient, SeventeenLandsError

_client: SeventeenLandsClient | None = None


@lifespan
async def draft_lifespan(server: FastMCP):
    global _client
    settings = Settings()
    client = SeventeenLandsClient(base_url=settings.seventeen_lands_base_url)
    async with client:
        _client = client
        yield {}
    _client = None


draft_mcp = FastMCP("17Lands", lifespan=draft_lifespan)


def _get_client() -> SeventeenLandsClient:
    if _client is None:
        raise RuntimeError("SeventeenLandsClient not initialized — server lifespan not running")
    return _client


@draft_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_DRAFT)
async def card_ratings(
    set_code: str,
    event_type: str = "PremierDraft",
) -> str:
    """Get win rate and draft performance data for cards in a set.

    Key metrics: GIH WR (ever_drawn_win_rate), ALSA (avg_seen), OH WR
    (opening_hand_win_rate), IWD (drawn_improvement_win_rate).

    Note: 17Lands data skews toward above-average players (~56% baseline WR).
    Cards with <500 games may not have reliable data.

    Args:
        set_code: Three-letter set code (e.g. "LCI", "MKM", "OTJ").
        event_type: Draft format — "PremierDraft" (default) or "TradDraft".
    """
    client = _get_client()
    try:
        ratings = await client.card_ratings(set_code, event_type=event_type)
    except SeventeenLandsError as exc:
        raise ToolError(f"17Lands API error: {exc}") from exc

    if not ratings:
        return f"No card rating data available for {set_code} ({event_type})."

    lines = [f"Card ratings for {set_code} ({event_type}) — {len(ratings)} cards:"]
    lines.append("")
    for card in ratings:
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
        lines.append(
            f"  {card.name} ({card.color}, {card.rarity}) — "
            f"GIH WR: {gih_wr}, ALSA: {alsa}, IWD: {iwd}, Games: {games}"
        )
    return "\n".join(lines)


@draft_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_DRAFT)
async def archetype_stats(
    set_code: str,
    start_date: str,
    end_date: str,
    event_type: str = "PremierDraft",
) -> str:
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
        return f"No archetype data available for {set_code} ({event_type})."

    lines = [f"Archetype stats for {set_code} ({event_type}, {start_date} to {end_date}):"]
    lines.append("")
    for arch in ratings:
        wr = f"{arch.win_rate:.1%}" if arch.win_rate is not None else "N/A"
        games = f"{arch.games:,}"
        prefix = "  [Summary] " if arch.is_summary else "  "
        lines.append(f"{prefix}{arch.color_name} — WR: {wr}, Games: {games}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@draft_mcp.resource("mtg://draft/{set_code}/ratings")
async def draft_ratings_resource(set_code: str) -> str:
    """Get card ratings for a set as JSON."""
    client = _get_client()
    ratings = await client.card_ratings(set_code)
    return json.dumps([r.model_dump() for r in ratings])
