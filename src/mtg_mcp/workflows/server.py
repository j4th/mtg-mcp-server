"""Workflow MCP server — composed tools calling multiple backend services."""

from __future__ import annotations

from contextlib import AsyncExitStack

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.lifespan import lifespan

from mtg_mcp.config import Settings
from mtg_mcp.providers import TOOL_ANNOTATIONS
from mtg_mcp.services.base import ServiceError
from mtg_mcp.services.edhrec import EDHRECClient
from mtg_mcp.services.mtgjson import MTGJSONClient
from mtg_mcp.services.scryfall import CardNotFoundError, ScryfallClient
from mtg_mcp.services.seventeen_lands import SeventeenLandsClient
from mtg_mcp.services.spellbook import SpellbookClient

_scryfall: ScryfallClient | None = None
_spellbook: SpellbookClient | None = None
_seventeen_lands: SeventeenLandsClient | None = None
_edhrec: EDHRECClient | None = None
_mtgjson: MTGJSONClient | None = None


@lifespan
async def workflow_lifespan(server: FastMCP):
    global _scryfall, _spellbook, _seventeen_lands, _edhrec, _mtgjson
    settings = Settings()
    async with AsyncExitStack() as stack:
        _scryfall = await stack.enter_async_context(
            ScryfallClient(base_url=settings.scryfall_base_url)
        )
        _spellbook = await stack.enter_async_context(
            SpellbookClient(base_url=settings.spellbook_base_url)
        )
        if settings.enable_17lands:
            _seventeen_lands = await stack.enter_async_context(
                SeventeenLandsClient(base_url=settings.seventeen_lands_base_url)
            )
        if settings.enable_edhrec:
            _edhrec = await stack.enter_async_context(
                EDHRECClient(base_url=settings.edhrec_base_url)
            )
        if settings.enable_mtgjson:
            _mtgjson = await stack.enter_async_context(
                MTGJSONClient(
                    data_url=settings.mtgjson_data_url,
                    refresh_hours=settings.mtgjson_refresh_hours,
                )
            )
        yield {}
    _scryfall = None
    _spellbook = None
    _seventeen_lands = None
    _edhrec = None
    _mtgjson = None


workflow_mcp = FastMCP("Workflows", lifespan=workflow_lifespan)


def _require_scryfall() -> ScryfallClient:
    if _scryfall is None:
        raise RuntimeError("ScryfallClient not initialized — workflow lifespan not running")
    return _scryfall


def _require_spellbook() -> SpellbookClient:
    if _spellbook is None:
        raise RuntimeError("SpellbookClient not initialized — workflow lifespan not running")
    return _spellbook


# --- Tool registrations ---


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS)
async def commander_overview(commander_name: str) -> str:
    """Comprehensive commander profile combining data from all available sources.

    Returns card details, top combos, EDHREC staples, and synergy data.
    Degrades gracefully if optional sources (EDHREC, Spellbook) are unavailable.
    """
    from mtg_mcp.workflows.commander import commander_overview as impl

    try:
        return await impl(
            commander_name,
            scryfall=_require_scryfall(),
            spellbook=_require_spellbook(),
            edhrec=_edhrec,
        )
    except CardNotFoundError as exc:
        raise ToolError(
            f"Commander not found: '{commander_name}'. Check spelling or try a different name."
        ) from exc
    except ServiceError as exc:
        raise ToolError(f"Service error: {exc}") from exc


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS)
async def evaluate_upgrade(card_name: str, commander_name: str) -> str:
    """Assess whether a card is worth adding to a specific commander deck.

    Returns card details, price, synergy score, and combos enabled for the caller to assess.
    Degrades gracefully if optional sources (EDHREC, Spellbook) are unavailable.
    """
    from mtg_mcp.workflows.commander import evaluate_upgrade as impl

    try:
        return await impl(
            card_name,
            commander_name,
            scryfall=_require_scryfall(),
            spellbook=_require_spellbook(),
            edhrec=_edhrec,
        )
    except CardNotFoundError as exc:
        raise ToolError(
            f"Card not found: '{card_name}'. Check spelling or try a different name."
        ) from exc
    except ServiceError as exc:
        raise ToolError(f"Service error: {exc}") from exc


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS)
async def draft_pack_pick(
    pack: list[str],
    set_code: str,
    current_picks: list[str] | None = None,
) -> str:
    """Rank cards in a draft pack using 17Lands win rate data.

    Provides GIH WR, ALSA, IWD stats, and color fit analysis based on current picks.
    Requires 17Lands to be enabled.
    """
    if _seventeen_lands is None:
        raise ToolError("17Lands data is not enabled. Set MTG_MCP_ENABLE_17LANDS=true.")
    from mtg_mcp.workflows.draft import draft_pack_pick as impl

    try:
        return await impl(
            pack,
            set_code,
            seventeen_lands=_seventeen_lands,
            current_picks=current_picks,
        )
    except ServiceError as exc:
        raise ToolError(f"17Lands error: {exc}") from exc


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS)
async def suggest_cuts(
    decklist: list[str],
    commander_name: str,
    num_cuts: int = 5,
) -> str:
    """Identify the weakest cards to cut from a commander decklist.

    Scores cards by synergy, inclusion rate, and combo membership.
    Degrades gracefully if EDHREC or Spellbook backends fail (uses whatever data is available).
    """
    from mtg_mcp.workflows.deck import suggest_cuts as impl

    try:
        return await impl(
            decklist,
            commander_name,
            spellbook=_require_spellbook(),
            edhrec=_edhrec,
            num_cuts=num_cuts,
        )
    except ServiceError as exc:
        raise ToolError(f"Service error: {exc}") from exc
