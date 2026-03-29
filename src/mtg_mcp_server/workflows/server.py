"""Workflow MCP server — composed tools calling multiple backend services.

This module is the wiring layer between MCP and the pure workflow functions
in ``commander.py``, ``commander_depth.py``, ``draft.py``, ``draft_limited.py``,
``deck.py``, ``analysis.py``, ``building.py``, ``constructed.py``,
``validation.py``, ``mana_base.py``, ``pricing.py``, and ``rules.py``.  Each tool
here wraps a pure async function, injecting the service clients from the
module-level state and converting service exceptions to ``ToolError``.

The workflow server is mounted on the orchestrator **without** a namespace
so tool names stay clean (e.g. ``commander_overview``, not
``workflow_commander_overview``).
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Annotated, Literal

import structlog
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.lifespan import lifespan
from fastmcp.tools.tool import ToolResult
from pydantic import Field

from mtg_mcp_server.config import Settings
from mtg_mcp_server.providers import (
    TAGS_BUILD,
    TAGS_COMMANDER,
    TAGS_CONSTRUCTED,
    TAGS_DRAFT,
    TAGS_LIMITED,
    TAGS_PRICING,
    TAGS_RULES,
    TAGS_SEARCH,
    TAGS_VALIDATE,
    TOOL_ANNOTATIONS,
)
from mtg_mcp_server.services.base import ServiceError
from mtg_mcp_server.services.edhrec import CommanderNotFoundError, EDHRECClient
from mtg_mcp_server.services.rules import RulesService
from mtg_mcp_server.services.scryfall import CardNotFoundError, ScryfallClient
from mtg_mcp_server.services.scryfall_bulk import ScryfallBulkClient
from mtg_mcp_server.services.seventeen_lands import SeventeenLandsClient
from mtg_mcp_server.services.spellbook import SpellbookClient

# Module-level clients managed by the lifespan via AsyncExitStack.
# Workflows need multiple clients simultaneously; AsyncExitStack is cleaner
# than nested `async with` blocks when some clients are feature-flagged.
_scryfall: ScryfallClient | None = None
_spellbook: SpellbookClient | None = None
_seventeen_lands: SeventeenLandsClient | None = None
_edhrec: EDHRECClient | None = None
_bulk: ScryfallBulkClient | None = None
_rules: RulesService | None = None


@lifespan
async def workflow_lifespan(server: FastMCP):
    """Initialize all service clients needed by workflow tools.

    Uses ``AsyncExitStack`` to manage multiple clients in a single lifespan.
    Feature-flagged backends (17Lands, EDHREC, Scryfall bulk data) are only created
    when their corresponding ``Settings`` flag is enabled. All clients are torn down
    when the server shuts down.
    """
    global _scryfall, _spellbook, _seventeen_lands, _edhrec, _bulk, _rules
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
        if settings.enable_bulk_data:
            client = ScryfallBulkClient(
                base_url=settings.scryfall_base_url,
                refresh_hours=settings.bulk_data_refresh_hours,
            )
            _bulk = await stack.enter_async_context(client)
            _bulk.start_background_refresh()
        if settings.enable_rules:
            _rules = RulesService(
                rules_url=settings.rules_url,
                refresh_hours=settings.rules_refresh_hours,
            )
            try:
                await _rules.ensure_loaded()
            except Exception:
                _log.warning(
                    "rules.startup_load_failed",
                    exc_info=True,
                    hint="Rules tools will attempt to load on first use",
                )
        yield {}
    _scryfall = None
    _spellbook = None
    _seventeen_lands = None
    _edhrec = None
    _bulk = None
    _rules = None


workflow_mcp = FastMCP("Workflows", lifespan=workflow_lifespan, mask_error_details=True)


def _require_scryfall() -> ScryfallClient:
    """Return Scryfall client or raise RuntimeError if lifespan hasn't started."""
    if _scryfall is None:
        raise RuntimeError("ScryfallClient not initialized — workflow lifespan not running")
    return _scryfall


def _require_spellbook() -> SpellbookClient:
    """Return Spellbook client or raise RuntimeError if lifespan hasn't started."""
    if _spellbook is None:
        raise RuntimeError("SpellbookClient not initialized — workflow lifespan not running")
    return _spellbook


def _require_seventeen_lands() -> SeventeenLandsClient:
    """Return 17Lands client or raise ToolError if the feature flag is off."""
    if _seventeen_lands is None:
        raise ToolError("17Lands data is not enabled. Set MTG_MCP_ENABLE_17LANDS=true.")
    return _seventeen_lands


def _require_edhrec() -> EDHRECClient:
    """Return EDHREC client or raise ToolError if the feature flag is off."""
    if _edhrec is None:
        raise ToolError("EDHREC is not enabled. Set MTG_MCP_ENABLE_EDHREC=true.")
    return _edhrec


def _require_bulk() -> ScryfallBulkClient:
    """Return bulk data client or raise ToolError if the feature flag is off."""
    if _bulk is None:
        raise ToolError("Bulk data is not enabled. Set MTG_MCP_ENABLE_BULK_DATA=true.")
    return _bulk


def _require_rules() -> RulesService:
    """Return rules service or raise ToolError if the feature flag is off."""
    if _rules is None:
        raise ToolError("Rules engine is not enabled. Set MTG_MCP_ENABLE_RULES=true.")
    return _rules


_log = structlog.get_logger(service="workflows")


async def _progress(ctx: Context, step: int, total: int) -> None:
    """Report progress to the MCP client. Never raises — progress is best-effort."""
    try:
        await ctx.report_progress(progress=step, total=total)
    except Exception:
        _log.warning("progress_report_failed", step=step, total=total, exc_info=True)


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_COMMANDER)
async def commander_overview(
    commander_name: Annotated[
        str, Field(description="Commander card name (e.g. 'Muldrotha, the Gravetide')")
    ],
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Comprehensive commander profile combining data from all available sources.

    Returns card details, top combos, EDHREC staples, and synergy scores.
    Degrades gracefully if optional sources (EDHREC, Spellbook) are unavailable.
    """
    from mtg_mcp_server.workflows.commander import commander_overview as impl

    if not commander_name.strip():
        raise ToolError("Commander name cannot be empty.")

    try:
        result = await impl(
            commander_name,
            scryfall=_require_scryfall(),
            spellbook=_require_spellbook(),
            edhrec=_edhrec,
            response_format=response_format,
        )
        return ToolResult(content=result.markdown, structured_content=result.data)
    except CardNotFoundError as exc:
        raise ToolError(
            f"Commander not found: '{commander_name}'. Check spelling or try a different name."
        ) from exc
    except ServiceError as exc:
        raise ToolError(f"commander_overview failed: {exc}") from exc


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_COMMANDER)
async def evaluate_upgrade(
    card_name: Annotated[
        str, Field(description="Card to evaluate for the deck (e.g. 'Spore Frog')")
    ],
    commander_name: Annotated[str, Field(description="Commander the deck is built around")],
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Assess whether a card is worth adding to a specific commander deck.

    Returns card details, price, synergy score, and combos enabled for the caller to assess.
    Degrades gracefully if optional sources (EDHREC, Spellbook) are unavailable.
    """
    from mtg_mcp_server.workflows.commander import evaluate_upgrade as impl

    if not card_name.strip():
        raise ToolError("Card name cannot be empty.")
    if not commander_name.strip():
        raise ToolError("Commander name cannot be empty.")

    try:
        result = await impl(
            card_name,
            commander_name,
            scryfall=_require_scryfall(),
            spellbook=_require_spellbook(),
            edhrec=_edhrec,
            response_format=response_format,
        )
        return ToolResult(content=result.markdown, structured_content=result.data)
    except CardNotFoundError as exc:
        raise ToolError(
            f"Card not found: '{card_name}'. Check spelling or try a different name."
        ) from exc
    except ServiceError as exc:
        raise ToolError(f"evaluate_upgrade failed: {exc}") from exc


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_DRAFT)
async def draft_pack_pick(
    pack: Annotated[list[str], Field(description="List of card names currently in the draft pack")],
    set_code: Annotated[
        str, Field(description="Three-letter set code for the draft format (e.g. 'LCI', 'MKM')")
    ],
    current_picks: Annotated[
        list[str] | None,
        Field(description="Cards already drafted — enables color fit analysis when provided"),
    ] = None,
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Rank cards in a draft pack using 17Lands win rate data.

    Provides GIH WR, ALSA, IWD stats, and color fit analysis based on current picks.
    Requires 17Lands to be enabled.
    """
    from mtg_mcp_server.workflows.draft import draft_pack_pick as impl

    try:
        result = await impl(
            pack,
            set_code,
            seventeen_lands=_require_seventeen_lands(),
            current_picks=current_picks,
            response_format=response_format,
        )
        return ToolResult(content=result.markdown, structured_content=result.data)
    except ServiceError as exc:
        raise ToolError(f"17Lands error: {exc}") from exc


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_COMMANDER)
async def suggest_cuts(
    decklist: Annotated[list[str], Field(description="List of card names in the deck")],
    commander_name: Annotated[str, Field(description="Commander the deck is built around")],
    num_cuts: Annotated[int, Field(description="Number of cut candidates to suggest")] = 5,
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Identify the weakest cards to cut from a commander decklist.

    Scores cards by synergy, inclusion rate, and combo membership.
    Degrades gracefully if EDHREC or Spellbook backends fail (uses whatever data is available).
    """
    from mtg_mcp_server.workflows.deck import suggest_cuts as impl

    if not commander_name.strip():
        raise ToolError("Commander name cannot be empty.")

    try:
        result = await impl(
            decklist,
            commander_name,
            spellbook=_require_spellbook(),
            edhrec=_edhrec,
            num_cuts=num_cuts,
            response_format=response_format,
        )
        return ToolResult(content=result.markdown, structured_content=result.data)
    except ServiceError as exc:
        raise ToolError(f"suggest_cuts failed: {exc}") from exc


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_COMMANDER)
async def card_comparison(
    cards: Annotated[list[str], Field(description="2-5 card names to compare side-by-side")],
    commander_name: Annotated[str, Field(description="Commander the deck is built around")],
    ctx: Context,
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Compare 2-5 cards side-by-side for a specific commander deck.

    Shows mana cost, type, synergy, inclusion rate, combo count, and price for each card.
    Scryfall and Spellbook required; EDHREC optional.
    """
    from mtg_mcp_server.workflows.commander import card_comparison as impl

    if not commander_name.strip():
        raise ToolError("Commander name cannot be empty.")

    cards = list(dict.fromkeys(cards))  # Deduplicate, preserving order

    if len(cards) < 2:
        raise ToolError("Provide at least 2 cards to compare.")
    if len(cards) > 5:
        raise ToolError("Maximum 5 cards can be compared at once.")

    try:
        result = await impl(
            cards,
            commander_name,
            scryfall=_require_scryfall(),
            spellbook=_require_spellbook(),
            edhrec=_edhrec,
            on_progress=lambda step, total: _progress(ctx, step, total),
            response_format=response_format,
        )
        return ToolResult(content=result.markdown, structured_content=result.data)
    except CardNotFoundError as exc:
        raise ToolError(f"{exc}. Check spelling.") from exc
    except ServiceError as exc:
        raise ToolError(f"card_comparison failed: {exc}") from exc


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_COMMANDER | TAGS_PRICING)
async def budget_upgrade(
    commander_name: Annotated[str, Field(description="Commander the deck is built around")],
    budget: Annotated[
        float, Field(description="Maximum price per card in USD (e.g. 5.0 for cards under $5)")
    ],
    num_suggestions: Annotated[
        int, Field(description="Number of upgrade suggestions to return")
    ] = 10,
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
    *,
    ctx: Context,
) -> ToolResult:
    """Suggest budget-friendly upgrades for a commander deck.

    Ranks EDHREC staples by synergy-per-dollar within the given budget ceiling.
    Requires EDHREC (for staples) and Scryfall (for prices).
    """
    from mtg_mcp_server.workflows.commander import budget_upgrade as impl

    if not commander_name.strip():
        raise ToolError("Commander name cannot be empty.")
    if budget <= 0:
        raise ToolError("Budget must be a positive number.")

    try:
        result = await impl(
            commander_name,
            budget=budget,
            num_suggestions=num_suggestions,
            scryfall=_require_scryfall(),
            edhrec=_require_edhrec(),
            on_progress=lambda step, total: _progress(ctx, step, total),
            response_format=response_format,
        )
        return ToolResult(content=result.markdown, structured_content=result.data)
    except CommanderNotFoundError as exc:
        raise ToolError(f"Commander not found: '{commander_name}'.") from exc
    except ServiceError as exc:
        raise ToolError(f"budget_upgrade failed: {exc}") from exc


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_COMMANDER)
async def deck_analysis(
    decklist: Annotated[
        list[str], Field(description="List of card names in the deck (99 cards for Commander)")
    ],
    commander_name: Annotated[str, Field(description="Commander the deck is built around")],
    ctx: Context,
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Full decklist health check — mana curve, colors, combos, bracket, budget, synergy.

    Uses all available backends: Scryfall bulk data for rate-limit-free card resolution,
    Scryfall API as fallback, Spellbook for combos and bracket estimation, EDHREC for
    synergy scores. Degrades gracefully if optional backends are unavailable.
    """
    from mtg_mcp_server.workflows.analysis import deck_analysis as impl

    if not decklist:
        raise ToolError("Provide at least one card in the decklist.")

    try:
        result = await impl(
            decklist,
            commander_name,
            bulk=_bulk,
            scryfall=_require_scryfall(),
            spellbook=_require_spellbook(),
            edhrec=_edhrec,
            on_progress=lambda step, total: _progress(ctx, step, total),
            response_format=response_format,
        )
        return ToolResult(content=result.markdown, structured_content=result.data)
    except ServiceError as exc:
        raise ToolError(f"deck_analysis failed: {exc}") from exc


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_DRAFT)
async def set_overview(
    set_code: Annotated[
        str, Field(description="Three-letter set code for the draft format (e.g. 'LCI', 'MKM')")
    ],
    event_type: Annotated[
        str, Field(description="Draft format — 'PremierDraft' (default) or 'TradDraft'")
    ] = "PremierDraft",
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
    *,
    ctx: Context,
) -> ToolResult:
    """Draft format overview — top commons/uncommons and trap rares.

    Uses 17Lands card ratings to provide a data-driven format breakdown.
    Requires 17Lands to be enabled.
    """
    from mtg_mcp_server.workflows.draft import set_overview as impl

    try:
        result = await impl(
            set_code,
            event_type=event_type,
            seventeen_lands=_require_seventeen_lands(),
            on_progress=lambda step, total: _progress(ctx, step, total),
            response_format=response_format,
        )
        return ToolResult(content=result.markdown, structured_content=result.data)
    except ServiceError as exc:
        raise ToolError(f"17Lands error: {exc}") from exc


# ---------------------------------------------------------------------------
# Deck Building Workflow Tools
# ---------------------------------------------------------------------------


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_SEARCH | TAGS_BUILD)
async def theme_search(
    theme: Annotated[
        str,
        Field(
            description="Theme to search for — mechanical (aristocrats, voltron, tokens), tribal (goblin, merfolk), or abstract (music, death, ocean)"
        ),
    ],
    color_identity: Annotated[
        str | None, Field(description="Color identity filter (e.g. 'sultai', 'BUG', 'WR')")
    ] = None,
    format: Annotated[
        str | None,
        Field(description="Format legality filter (e.g. 'standard', 'modern', 'commander')"),
    ] = None,
    max_price: Annotated[float | None, Field(description="Maximum card price in USD")] = None,
    limit: Annotated[int, Field(description="Maximum number of results")] = 20,
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Find cards matching a theme — mechanical, tribal, or abstract/flavorful.

    Maps themes to oracle text patterns and searches bulk data. Groups results
    by relevance tier (strong match, moderate match, flavor match).
    """
    from mtg_mcp_server.workflows.building import theme_search as impl

    if not theme.strip():
        raise ToolError("Theme cannot be empty.")

    try:
        result = await impl(
            theme,
            bulk=_require_bulk(),
            edhrec=_edhrec,
            color_identity=color_identity,
            format=format,
            max_price=max_price,
            limit=limit,
            response_format=response_format,
        )
        return ToolResult(content=result.markdown, structured_content=result.data)
    except ServiceError as exc:
        raise ToolError(f"theme_search failed: {exc}") from exc


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_BUILD)
async def build_around(
    cards: Annotated[list[str], Field(description="1-5 card names to build around")],
    format: Annotated[
        str,
        Field(description="Format to build for (e.g. 'standard', 'modern', 'commander')"),
    ],
    budget: Annotated[float | None, Field(description="Maximum price per card in USD")] = None,
    limit: Annotated[int, Field(description="Maximum number of suggestions")] = 20,
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Find synergistic cards for 1-5 build-around cards in any format.

    Analyzes oracle text for key mechanics, searches for synergies,
    and checks combo potential. Groups results by role (enablers, payoffs, support).
    """
    from mtg_mcp_server.workflows.building import build_around as impl

    cards = list(dict.fromkeys(cards))
    if not cards:
        raise ToolError("Provide at least 1 card to build around.")
    if len(cards) > 5:
        raise ToolError("Maximum 5 build-around cards.")

    try:
        result = await impl(
            cards,
            format,
            bulk=_require_bulk(),
            spellbook=_require_spellbook(),
            edhrec=_edhrec,
            budget=budget,
            limit=limit,
            response_format=response_format,
        )
        return ToolResult(content=result.markdown, structured_content=result.data)
    except CardNotFoundError as exc:
        raise ToolError(f"{exc}. Check spelling.") from exc
    except ServiceError as exc:
        raise ToolError(f"build_around failed: {exc}") from exc


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_BUILD)
async def complete_deck(
    decklist: Annotated[
        list[str], Field(description="Partial decklist — card names already chosen")
    ],
    format: Annotated[
        str,
        Field(description="Format to build for (e.g. 'standard', 'modern', 'commander')"),
    ],
    commander: Annotated[
        str | None, Field(description="Commander name (required for Commander format)")
    ] = None,
    budget: Annotated[
        float | None, Field(description="Maximum price per suggested card in USD")
    ] = None,
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
    *,
    ctx: Context,
) -> ToolResult:
    """Identify gaps in a partial decklist and suggest cards to fill them.

    Analyzes mana curve, card roles, and format-specific ratios, then suggests
    cards for underrepresented categories.
    """
    from mtg_mcp_server.workflows.building import complete_deck as impl

    if not decklist:
        raise ToolError("Provide at least one card in the decklist.")

    try:
        result = await impl(
            decklist,
            format,
            bulk=_require_bulk(),
            edhrec=_edhrec,
            commander=commander,
            budget=budget,
            on_progress=lambda step, total: _progress(ctx, step, total),
            response_format=response_format,
        )
        return ToolResult(content=result.markdown, structured_content=result.data)
    except ServiceError as exc:
        raise ToolError(f"complete_deck failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Commander Depth Workflow Tools
# ---------------------------------------------------------------------------


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_COMMANDER)
async def commander_comparison(
    commanders: Annotated[
        list[str], Field(description="2-5 commander names to compare head-to-head")
    ],
    ctx: Context,
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Compare 2-5 commanders head-to-head: stats, combos, staples, popularity.

    Side-by-side comparison table with mana cost, color identity, EDHREC rank,
    combo count, and shared/unique staples.
    """
    from mtg_mcp_server.workflows.commander_depth import commander_comparison as impl

    commanders = list(dict.fromkeys(commanders))
    if len(commanders) < 2:
        raise ToolError("Provide at least 2 commanders to compare.")
    if len(commanders) > 5:
        raise ToolError("Maximum 5 commanders can be compared.")

    try:
        result = await impl(
            commanders,
            bulk=_require_bulk(),
            spellbook=_require_spellbook(),
            edhrec=_edhrec,
            on_progress=lambda step, total: _progress(ctx, step, total),
            response_format=response_format,
        )
        return ToolResult(content=result.markdown, structured_content=result.data)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    except CardNotFoundError as exc:
        raise ToolError(f"{exc}. Check spelling.") from exc
    except ServiceError as exc:
        raise ToolError(f"commander_comparison failed: {exc}") from exc


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_COMMANDER | TAGS_SEARCH)
async def tribal_staples(
    tribe: Annotated[str, Field(description="Creature type (e.g. 'Goblin', 'Merfolk', 'Samurai')")],
    color_identity: Annotated[
        str | None, Field(description="Color identity filter (e.g. 'sultai', 'WR')")
    ] = None,
    format: Annotated[
        str | None, Field(description="Format legality filter (e.g. 'commander', 'modern')")
    ] = None,
    limit: Annotated[int, Field(description="Maximum number of results")] = 20,
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Best cards for a creature type — lords, synergy pieces, and top members.

    Groups results by: lords/anthems, tribal synergy, best members, tribal support.
    """
    from mtg_mcp_server.workflows.commander_depth import tribal_staples as impl

    if not tribe.strip():
        raise ToolError("Tribe cannot be empty.")

    try:
        result = await impl(
            tribe,
            bulk=_require_bulk(),
            edhrec=_edhrec,
            color_identity=color_identity,
            format=format,
            limit=limit,
            response_format=response_format,
        )
        return ToolResult(content=result.markdown, structured_content=result.data)
    except ServiceError as exc:
        raise ToolError(f"tribal_staples failed: {exc}") from exc


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_COMMANDER | TAGS_BUILD)
async def precon_upgrade(
    decklist: Annotated[list[str], Field(description="Full precon decklist — card names")],
    commander: Annotated[str, Field(description="Commander card name")],
    budget: Annotated[float, Field(description="Maximum price per upgrade card in USD")] = 50.0,
    num_upgrades: Annotated[int, Field(description="Number of upgrade suggestions")] = 10,
    ctx: Context = None,  # type: ignore[assignment]
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Analyze and upgrade a Commander precon — identify weakest cards, suggest replacements.

    Pairs each upgrade with a specific cut, explaining the synergy improvement.
    """
    from mtg_mcp_server.workflows.commander_depth import precon_upgrade as impl

    if not decklist:
        raise ToolError("Provide the precon decklist.")
    if not commander.strip():
        raise ToolError("Commander name cannot be empty.")

    try:
        result = await impl(
            decklist,
            commander,
            bulk=_require_bulk(),
            spellbook=_require_spellbook(),
            edhrec=_edhrec,
            budget=budget,
            num_upgrades=num_upgrades,
            on_progress=lambda step, total: _progress(ctx, step, total),
            response_format=response_format,
        )
        return ToolResult(content=result.markdown, structured_content=result.data)
    except CardNotFoundError as exc:
        raise ToolError(f"{exc}. Check spelling.") from exc
    except ServiceError as exc:
        raise ToolError(f"precon_upgrade failed: {exc}") from exc


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_COMMANDER | TAGS_SEARCH)
async def color_identity_staples(
    color_identity: Annotated[
        str,
        Field(description="Color identity (e.g. 'sultai', 'BUG', 'WR', 'mono-red')"),
    ],
    category: Annotated[
        str | None,
        Field(description="Card category filter (e.g. 'creatures', 'instants', 'lands')"),
    ] = None,
    limit: Annotated[int, Field(description="Maximum number of results")] = 20,
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Top cards across ALL commanders in a color identity.

    Uses EDHREC aggregated data when available, falls back to EDHREC rank from bulk data.
    """
    from mtg_mcp_server.workflows.commander_depth import color_identity_staples as impl

    if not color_identity.strip():
        raise ToolError("Color identity cannot be empty.")

    try:
        result = await impl(
            color_identity,
            bulk=_require_bulk(),
            edhrec=_edhrec,
            category=category,
            limit=limit,
            response_format=response_format,
        )
        return ToolResult(content=result.markdown, structured_content=result.data)
    except ServiceError as exc:
        raise ToolError(f"color_identity_staples failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Limited Expansion Workflow Tools
# ---------------------------------------------------------------------------


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_LIMITED | TAGS_BUILD)
async def sealed_pool_build(
    pool: Annotated[
        list[str], Field(description="Card names in the sealed pool (typically 84-90)")
    ],
    set_code: Annotated[str, Field(description="Three-letter set code (e.g. 'LCI', 'MKM')")],
    ctx: Context,
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Build 1-3 decks from a sealed pool using card quality and color pair analysis.

    Evaluates each 2-color pair, selects best cards, and suggests land splits.
    Uses 17Lands data when available for card quality scoring.
    """
    from mtg_mcp_server.workflows.draft_limited import sealed_pool_build as impl

    if not pool:
        raise ToolError("Provide at least one card in the sealed pool.")

    try:
        result = await impl(
            pool,
            set_code,
            bulk=_require_bulk(),
            seventeen_lands=_seventeen_lands,
            on_progress=lambda step, total: _progress(ctx, step, total),
            response_format=response_format,
        )
        return ToolResult(content=result.markdown, structured_content=result.data)
    except ServiceError as exc:
        raise ToolError(f"sealed_pool_build failed: {exc}") from exc


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_LIMITED)
async def draft_signal_read(
    picks: Annotated[list[str], Field(description="Cards already drafted, in pick order")],
    set_code: Annotated[str, Field(description="Three-letter set code (e.g. 'LCI', 'MKM')")],
    current_pack: Annotated[
        list[str] | None,
        Field(
            description="Current pack contents — if provided, cards are ranked with signal context"
        ),
    ] = None,
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Analyze draft picks and recommend a direction based on color signals.

    Uses ALSA data to detect which colors are open (cards seen later than expected = open).
    """
    from mtg_mcp_server.workflows.draft_limited import draft_signal_read as impl

    if not picks:
        raise ToolError("Provide at least one pick.")

    try:
        result = await impl(
            picks,
            set_code,
            bulk=_require_bulk(),
            seventeen_lands=_require_seventeen_lands(),
            current_pack=current_pack,
            response_format=response_format,
        )
        return ToolResult(content=result.markdown, structured_content=result.data)
    except ServiceError as exc:
        raise ToolError(f"draft_signal_read failed: {exc}") from exc


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_LIMITED)
async def draft_log_review(
    picks: Annotated[
        list[str],
        Field(description="Cards drafted in order (pack 1 pick 1 through pack 3 pick 14)"),
    ],
    set_code: Annotated[str, Field(description="Three-letter set code (e.g. 'LCI', 'MKM')")],
    final_deck: Annotated[
        list[str] | None,
        Field(description="Final deck submitted — enables 'made the deck' analysis"),
    ] = None,
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Review a completed draft — pick-by-pick GIH WR analysis and key decision points.

    Identifies where you could have taken a higher-WR card, pivot points,
    and overall draft grade.
    """
    from mtg_mcp_server.workflows.draft_limited import draft_log_review as impl

    if not picks:
        raise ToolError("Provide at least one pick.")

    try:
        result = await impl(
            picks,
            set_code,
            bulk=_require_bulk(),
            seventeen_lands=_require_seventeen_lands(),
            final_deck=final_deck,
            response_format=response_format,
        )
        return ToolResult(content=result.markdown, structured_content=result.data)
    except ServiceError as exc:
        raise ToolError(f"draft_log_review failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Constructed Format Workflow Tools
# ---------------------------------------------------------------------------


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_CONSTRUCTED)
async def rotation_check(
    cards: Annotated[
        list[str] | None,
        Field(description="Card names to check for rotation — omit for general rotation info"),
    ] = None,
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Check Standard rotation status and identify which cards are rotating.

    Shows sets currently in Standard with rotation dates. If cards provided,
    identifies which are in rotating sets and suggests replacements.
    """
    from mtg_mcp_server.workflows.constructed import rotation_check as impl

    try:
        result = await impl(
            scryfall=_require_scryfall(),
            bulk=_require_bulk(),
            cards=cards,
            response_format=response_format,
        )
        return ToolResult(content=result.markdown, structured_content=result.data)
    except ServiceError as exc:
        raise ToolError(f"rotation_check failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


@workflow_mcp.prompt()
def evaluate_commander_swap(
    commander: Annotated[str, Field(description="Commander the deck is built around")],
    adding: Annotated[str, Field(description="Card name being added to the deck")],
    cutting: Annotated[str, Field(description="Card name being cut from the deck")],
) -> str:
    """Evaluate swapping a card in a Commander deck."""
    return f"""Evaluate this Commander deck change:
Commander: {commander}
Adding: {adding}
Cutting: {cutting}

Step 1: Look up both cards with scryfall_card_details for full oracle text and stats.
Step 2: Compare synergy scores — use card_comparison with both cards and the commander.
Step 3: Check if the new card enables any combos via spellbook_find_combos.
Step 4: Check if cutting the old card breaks existing combos via spellbook_find_combos.

Evaluation criteria:
- Synergy: above +30% is strong, +10-30% is moderate, below +10% is weak
- Combo potential: enabling a new combo is a strong reason to add
- Breaking a combo: a strong reason NOT to cut
- Price: note the price difference between the two cards
- Mana curve: does the swap change the mana cost? Is that good or bad for the deck?

Give a clear recommendation: SWAP, KEEP, or CONSIDER with detailed reasoning."""


@workflow_mcp.prompt()
def deck_health_check(
    commander: Annotated[str, Field(description="Commander card name for the deck to analyze")],
) -> str:
    """Guide a comprehensive deck health assessment."""
    return f"""Run a full health check on the {commander} Commander deck.

Step 1: Use deck_analysis with the full decklist to get:
  - Mana curve distribution
  - Color pip requirements
  - Combo density and bracket estimate
  - Total deck budget
  - Lowest-synergy cards

Step 2: Use suggest_cuts to identify the weakest cards in the deck.

Step 3: Analyze the results:
  - Is the mana curve reasonable? (Commander decks typically want a curve peaking at 2-3 CMC)
  - Are color requirements manageable with the mana base?
  - Is the bracket estimate appropriate for the intended power level?
  - Are there obvious upgrades for the lowest-synergy cards?

Provide a prioritized list of recommendations."""


@workflow_mcp.prompt()
def draft_strategy(
    set_code: Annotated[str, Field(description="Three-letter set code (e.g. 'LCI', 'MKM', 'OTJ')")],
) -> str:
    """Guide a draft format preparation session."""
    return f"""Prepare a draft strategy guide for {set_code}.

Step 1: Use set_overview to get the card ratings breakdown:
  - Top commons and uncommons by GIH WR (which cards should you prioritize?)
  - Trap rares/mythics (which rares underperform the median?)

Step 2: For the top 2-3 archetypes, note:
  - Key commons that signal the archetype is open (ALSA > 5 = late picks = open lane)
  - The archetype's best uncommons
  - Key synergies to build around

Step 3: Draft heuristics:
  - GIH WR above 58% = premium card (always take)
  - GIH WR 55-58% = strong card (take in your colors)
  - GIH WR below 50% = avoid unless synergy-dependent
  - IWD above +5% = high-impact draw, good for aggressive decks
  - ALSA above 6 = late pick, good signal the color is open

Summarize as a concise cheat sheet for use during a draft."""


@workflow_mcp.prompt()
def find_upgrades(
    commander: Annotated[str, Field(description="Commander card name for upgrade suggestions")],
    budget: Annotated[float, Field(description="Maximum price per card in USD")],
) -> str:
    """Guide a budget upgrade session for a Commander deck."""
    return f"""Find budget upgrades for the {commander} Commander deck under ${budget:.2f} per card.

Step 1: Use budget_upgrade with commander="{commander}" and budget={budget} to get
ranked suggestions sorted by synergy-per-dollar.

Step 2: For the top 5 suggestions, use evaluate_upgrade to get detailed analysis:
  - Card details and oracle text
  - Synergy score with {commander}
  - Combo potential
  - Price

Step 3: Evaluation criteria:
  - Synergy/$: the primary ranking metric — high synergy at low cost is best
  - Combo enablers: cards that unlock combos are especially valuable upgrades
  - Inclusion rate: above 50% means the card is proven in this commander's decks
  - Category gaps: prioritize upgrades that fill roles the deck is missing

Recommend the top 3-5 upgrades with reasoning and estimated total cost."""


# ---------------------------------------------------------------------------
# Cross-Format Workflow Tools
# ---------------------------------------------------------------------------


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_VALIDATE)
async def deck_validate(
    decklist: Annotated[
        list[str],
        Field(
            description="Card names, optionally prefixed with quantity (e.g. '4x Lightning Bolt' or 'Lightning Bolt')"
        ),
    ],
    format: Annotated[
        str,
        Field(
            description="Format to validate against (e.g. 'commander', 'modern', 'standard', 'legacy')"
        ),
    ],
    commander: Annotated[
        str | None, Field(description="Commander card name (required for Commander format)")
    ] = None,
    sideboard: Annotated[
        list[str] | None, Field(description="Sideboard card names, same format as decklist")
    ] = None,
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Validate a decklist against a format's construction rules.

    Checks legality, deck size, copy limits, color identity (Commander), singleton
    rules, and Pauper rarity. Returns VALID or INVALID with actionable error messages.
    """
    from mtg_mcp_server.workflows.validation import deck_validate as impl

    if not decklist:
        raise ToolError("Provide at least one card in the decklist.")

    try:
        result = await impl(
            decklist,
            format,
            commander=commander,
            sideboard=sideboard,
            bulk=_require_bulk(),
            response_format=response_format,
        )
        return ToolResult(content=result.markdown, structured_content=result.data)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    except ServiceError as exc:
        raise ToolError(f"deck_validate failed: {exc}") from exc


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_BUILD)
async def suggest_mana_base(
    decklist: Annotated[list[str], Field(description="Non-land card names in the deck")],
    format: Annotated[
        str, Field(description="Format for land legality checking (e.g. 'commander', 'modern')")
    ],
    total_lands: Annotated[
        int | None,
        Field(description="Override total land count (default: auto-calculated from avg CMC)"),
    ] = None,
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Suggest a mana base for a decklist based on color pip distribution.

    Analyzes color requirements, recommends land count, and suggests format-legal
    dual lands. Handles hybrid and phyrexian mana.
    """
    from mtg_mcp_server.workflows.mana_base import suggest_mana_base as impl

    if not decklist:
        raise ToolError("Provide at least one card in the decklist.")

    try:
        result = await impl(
            decklist,
            format,
            total_lands=total_lands,
            bulk=_require_bulk(),
            response_format=response_format,
        )
        return ToolResult(content=result.markdown, structured_content=result.data)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    except ServiceError as exc:
        raise ToolError(f"suggest_mana_base failed: {exc}") from exc


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_PRICING)
async def price_comparison(
    cards: Annotated[list[str], Field(description="2-20 card names to compare prices")],
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Compare prices across multiple cards using Scryfall bulk data.

    Returns a markdown table with USD, USD foil, and EUR prices sorted by USD descending.
    """
    from mtg_mcp_server.workflows.pricing import price_comparison as impl

    cards = list(dict.fromkeys(cards))  # Deduplicate, preserving order

    if len(cards) < 2:
        raise ToolError("Provide at least 2 cards to compare prices.")
    if len(cards) > 20:
        raise ToolError("Maximum 20 cards for price comparison.")

    try:
        result = await impl(
            cards,
            bulk=_require_bulk(),
            response_format=response_format,
        )
        return ToolResult(content=result.markdown, structured_content=result.data)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    except ServiceError as exc:
        raise ToolError(f"price_comparison failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Cross-Format Prompts
# ---------------------------------------------------------------------------


@workflow_mcp.prompt()
def build_deck(
    concept: Annotated[
        str,
        Field(description="Deck concept or strategy (e.g. 'mono-red aggro', 'Azorius control')"),
    ],
    format: Annotated[
        str, Field(description="Format to build for (e.g. 'modern', 'commander', 'standard')")
    ],
    budget: Annotated[float | None, Field(description="Optional max price per card in USD")] = None,
) -> str:
    """Guide building a deck from scratch for any format."""
    budget_line = f" under ${budget:.2f} per card" if budget else ""
    return f"""Build a {format} deck around the concept: {concept}{budget_line}.

Step 1: Use bulk_format_search to find key cards matching the concept in {format}.
  - Search for creatures, spells, and enablers that fit the strategy.

Step 2: Use bulk_format_staples to find the most-played cards in {format} that complement the concept.

Step 3: Assemble a decklist considering:
  - Mana curve (most {format} decks peak at 2-3 CMC for 60-card, 3-4 for Commander)
  - Color consistency (don't stretch the mana base too thin)
  {"- Budget: filter cards under $" + f"{budget:.2f}" if budget else "- No budget constraint specified"}

Step 4: Use deck_validate to verify the decklist is legal for {format}.

Step 5: Use suggest_mana_base to get land recommendations.

Present the final decklist with categories and total estimated cost."""


@workflow_mcp.prompt()
def evaluate_collection(
    cards: Annotated[
        str, Field(description="Comma-separated list of card names in your collection")
    ],
) -> str:
    """Evaluate a collection of cards across formats."""
    return f"""Evaluate this card collection for format playability and value:
Cards: {cards}

Step 1: Use bulk_card_in_formats for each card to see where it's legal.

Step 2: Use price_comparison to see the current value of all cards.

Step 3: Analysis:
  - Which cards are format staples? (Check EDHREC rank, Modern/Legacy playability)
  - Which cards have the highest value?
  - Are there any banned cards that are only legal in specific formats?
  - Group cards by the formats where they're most useful.

Summarize: total collection value, best format fits, and any hidden gems."""


@workflow_mcp.prompt()
def format_intro(
    format: Annotated[
        str, Field(description="Format to learn about (e.g. 'modern', 'commander', 'pauper')")
    ],
) -> str:
    """Introduce a Magic format with key rules and staple cards."""
    return f"""Provide an introduction to the {format} format.

Step 1: Explain the format rules:
  - Deck size requirements
  - Copy limits (4-of, singleton, etc.)
  - Special rules (Commander tax, color identity, Pauper rarity restriction, etc.)
  - Banned/restricted list highlights

Step 2: Use bulk_ban_list to show the current banned cards in {format}.

Step 3: Use bulk_format_staples to show the most-played cards in {format}.

Step 4: For constructed formats, highlight:
  - Top archetypes and strategies
  - Key staple cards every player should know about
  - Budget-friendly entry points

Present as a beginner-friendly guide."""


@workflow_mcp.prompt()
def card_alternatives(
    card_name: Annotated[str, Field(description="Card to find alternatives for")],
    format: Annotated[str, Field(description="Format the alternatives must be legal in")],
    budget: Annotated[float, Field(description="Max price per card in USD")],
) -> str:
    """Find budget alternatives to an expensive or unavailable card."""
    return f"""Find alternatives to {card_name} for {format} under ${budget:.2f}.

Step 1: Use scryfall_card_details to understand what {card_name} does — its role, effect, and stats.

Step 2: Use bulk_similar_cards to find cards with similar effects in {format}.

Step 3: Use price_comparison on the top candidates to verify they're within budget.

Step 4: Evaluate each alternative:
  - How close is the effect to the original?
  - Any additional upsides or downsides?
  - Format legality confirmed?

Rank the top 3-5 alternatives with reasoning and price."""


# ---------------------------------------------------------------------------
# Rules Engine Tools
# ---------------------------------------------------------------------------


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_RULES)
async def rules_lookup(
    query: Annotated[
        str, Field(description="Rule number (e.g. '704.5k') or keyword to search for")
    ],
    section: Annotated[
        str | None,
        Field(
            description="Narrow search to a section (e.g. 'combat', 'stack', 'lands', 'state-based')"
        ),
    ] = None,
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Look up MTG Comprehensive Rules by number or keyword search.

    Returns matching rules with full text, parent context, and subrules.
    """
    from mtg_mcp_server.workflows.rules import rules_lookup as impl

    try:
        result = await impl(
            query,
            section=section,
            rules=_require_rules(),
            response_format=response_format,
        )
        return ToolResult(content=result.markdown, structured_content=result.data)
    except ServiceError as exc:
        raise ToolError(f"rules_lookup failed: {exc}") from exc


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_RULES)
async def keyword_explain(
    keyword: Annotated[
        str, Field(description="MTG keyword to explain (e.g. 'trample', 'deathtouch')")
    ],
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Explain an MTG keyword with rules text, examples, and interactions.

    Returns the rules definition, reminder text, and up to 5 example cards from bulk data.
    """
    from mtg_mcp_server.workflows.rules import keyword_explain as impl

    try:
        result = await impl(
            keyword,
            rules=_require_rules(),
            bulk=_bulk,
            response_format=response_format,
        )
        return ToolResult(content=result.markdown, structured_content=result.data)
    except ServiceError as exc:
        raise ToolError(f"keyword_explain failed: {exc}") from exc


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_RULES)
async def rules_interaction(
    mechanic_a: Annotated[str, Field(description="First mechanic or card name")],
    mechanic_b: Annotated[str, Field(description="Second mechanic or card name")],
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Explain how two mechanics or cards interact under MTG rules.

    Returns relevant rules, step-by-step resolution, and common misconceptions.
    """
    from mtg_mcp_server.workflows.rules import rules_interaction as impl

    try:
        result = await impl(
            mechanic_a,
            mechanic_b,
            rules=_require_rules(),
            bulk=_bulk,
            response_format=response_format,
        )
        return ToolResult(content=result.markdown, structured_content=result.data)
    except ServiceError as exc:
        raise ToolError(f"rules_interaction failed: {exc}") from exc


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_RULES)
async def rules_scenario(
    scenario: Annotated[
        str, Field(description="Game scenario to resolve (describe the board state and action)")
    ],
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Resolve a game scenario step-by-step using MTG rules.

    Covers priority, stack resolution, state-based actions, and triggers with rule citations.
    """
    from mtg_mcp_server.workflows.rules import rules_scenario as impl

    try:
        result = await impl(
            scenario,
            rules=_require_rules(),
            response_format=response_format,
        )
        return ToolResult(content=result.markdown, structured_content=result.data)
    except ServiceError as exc:
        raise ToolError(f"rules_scenario failed: {exc}") from exc


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_RULES)
async def combat_calculator(
    attackers: Annotated[list[str], Field(description="Attacking creature names or descriptions")],
    blockers: Annotated[list[str], Field(description="Blocking creature names or descriptions")],
    keywords: Annotated[
        list[str] | None,
        Field(
            description="Additional keyword abilities to consider (e.g. 'deathtouch', 'trample')"
        ),
    ] = None,
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
) -> ToolResult:
    """Calculate combat step-by-step with keyword interactions.

    Resolves declare attackers → declare blockers → damage steps → state-based actions.
    Looks up card keywords from bulk data if card names are provided.
    """
    from mtg_mcp_server.workflows.rules import combat_calculator as impl

    try:
        result = await impl(
            attackers,
            blockers,
            keywords=keywords,
            rules=_require_rules(),
            bulk=_bulk,
            response_format=response_format,
        )
        return ToolResult(content=result.markdown, structured_content=result.data)
    except ServiceError as exc:
        raise ToolError(f"combat_calculator failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Rules Resources
# ---------------------------------------------------------------------------


@workflow_mcp.resource("mtg://rules/{number}")
async def get_rule(number: str) -> dict[str, object]:
    """Rule text by number (e.g. mtg://rules/704.5k)."""
    rules = _require_rules()
    rule = await rules.lookup_by_number(number)
    return rule.model_dump(mode="json") if rule else {"error": f"Rule {number} not found"}


@workflow_mcp.resource("mtg://rules/glossary/{term}")
async def get_glossary_term(term: str) -> dict[str, object]:
    """Glossary definition by term."""
    rules = _require_rules()
    entry = await rules.glossary_lookup(term)
    return entry.model_dump(mode="json") if entry else {"error": f"Term '{term}' not found"}


@workflow_mcp.resource("mtg://rules/keywords")
async def list_keywords() -> list[dict[str, str]]:
    """All keywords with brief definitions."""
    rules = _require_rules()
    return await rules.list_keywords()


@workflow_mcp.resource("mtg://rules/sections")
async def list_sections() -> list[dict[str, str]]:
    """Section index for the Comprehensive Rules."""
    rules = _require_rules()
    return await rules.list_sections()


# ---------------------------------------------------------------------------
# Rules Prompt
# ---------------------------------------------------------------------------


@workflow_mcp.prompt()
def rules_question(
    question: Annotated[str, Field(description="The rules question to answer")],
) -> str:
    """Guide for answering an MTG rules question with citations."""
    return f"""Answer this MTG rules question: {question}

Step 1: Use rules_lookup to find the relevant rules. Try rule numbers if specific,
or keyword search for the mechanic/concept in question.

Step 2: If the question mentions specific cards, use scryfall_card_details or
bulk_card_lookup to get their oracle text and keywords.

Step 3: If the question involves keyword interactions, use keyword_explain
for each keyword involved, then rules_interaction for the combination.

Step 4: Explain the answer in plain language, citing specific rule numbers.
Include the exact rule text for the most important rules.

Important: MTG rules can be counterintuitive. Always cite the specific rule —
never guess or assume based on "how it should work."
"""


# ---------------------------------------------------------------------------
# Format Workflow Prompts
# ---------------------------------------------------------------------------


@workflow_mcp.prompt()
def build_around_deck(
    cards: Annotated[str, Field(description="Card names or win condition concept to build around")],
    format: Annotated[
        str, Field(description="Format to build for (e.g. 'standard', 'modern', 'commander')")
    ],
    budget: Annotated[float | None, Field(description="Max price per card in USD")] = None,
) -> str:
    """Build a deck around specific cards or a win condition in any format."""
    budget_line = f" under ${budget:.2f} per card" if budget else ""
    rotation_step = ""
    if format.lower() == "standard":
        rotation_step = """
Step 3: Use rotation_check with key cards to ensure nothing rotates soon.
  - Flag any cards rotating within 3 months.
  - Suggest non-rotating alternatives if found.
"""
    return f"""Build a {format} deck around: {cards}{budget_line}.

Step 1: Determine if this is a specific card or a concept:
  - If specific cards: use build_around with those cards and format="{format}"
  - If a concept/strategy: use theme_search to find the key payoff cards first,
    then use build_around with those payoffs

Step 2: From the synergy suggestions, assemble a core shell:
  - Enablers: cards that set up the win condition
  - Payoffs: cards that benefit from the strategy
  - Protection/interaction: cards that protect the plan or disrupt opponents
{rotation_step}
Step {"4" if rotation_step else "3"}: Use complete_deck to fill remaining slots:
  - Mana curve appropriate for {format}
  - {"4x copies of key cards, format-legal" if format.lower() != "commander" else "Singleton requirement, color identity legal"}
  {"- Budget: only suggest cards under $" + f"{budget:.2f}" if budget else ""}

Step {"5" if rotation_step else "4"}: Use deck_validate to verify legality for {format}.

Step {"6" if rotation_step else "5"}: Use suggest_mana_base for the land base.

Present: final decklist with categories, total cost, and key synergy explanations."""


@workflow_mcp.prompt()
def build_tribal_deck(
    tribe: Annotated[
        str, Field(description="Creature type to build around (e.g. 'Goblin', 'Merfolk')")
    ],
    format: Annotated[str, Field(description="Format (e.g. 'commander', 'modern')")],
    commander: Annotated[
        str | None, Field(description="Commander name (for Commander format)")
    ] = None,
    budget: Annotated[float | None, Field(description="Max price per card in USD")] = None,
) -> str:
    """Build a tribal deck for any format."""
    budget_line = f" under ${budget:.2f} per card" if budget else ""
    cmdr_line = f"\nCommander: {commander}" if commander else ""
    return f"""Build a {tribe} tribal deck for {format}{budget_line}.{cmdr_line}

Step 1: Use tribal_staples to find the best {tribe} cards:
  - Lords and anthems
  - Tribal synergy pieces
  - Best creatures of the type
  - Universal tribal support (Kindred cards, "choose a creature type" effects)

Step 2: Use build_around with the top 3-5 tribal payoffs and format="{format}".

Step 3: Use suggest_mana_base to build the land base.

Step 4: Use deck_validate to verify legality for {format}.

Present: decklist with tribal density analysis, key synergies, and total cost."""


@workflow_mcp.prompt()
def build_theme_deck(
    theme: Annotated[
        str, Field(description="Deck theme (e.g. 'aristocrats', 'voltron', 'tokens', 'mill')")
    ],
    format: Annotated[str, Field(description="Format (e.g. 'standard', 'commander', 'modern')")],
    color_identity: Annotated[
        str | None, Field(description="Color constraint (e.g. 'sultai', 'WR')")
    ] = None,
    budget: Annotated[float | None, Field(description="Max price per card in USD")] = None,
) -> str:
    """Build a themed deck around a strategy or archetype."""
    budget_line = f" under ${budget:.2f} per card" if budget else ""
    color_line = f" in {color_identity}" if color_identity else ""
    return f"""Build a {theme} deck for {format}{color_line}{budget_line}.

Step 1: Use theme_search with theme="{theme}" to discover cards that fit:
  - Look at strong matches (mechanically relevant oracle text)
  - Note moderate matches (type line or partial oracle text)
  - Consider flavor matches if building for fun

Step 2: Use build_around with the top theme payoffs and format="{format}".

Step 3: Use complete_deck to fill gaps:
  - Ensure sufficient removal, card draw, ramp
  - Balance curve for the format

Step 4: Use deck_validate to verify legality.

Step 5: Use suggest_mana_base for the land base.

Present: final decklist organized by role, with theme density analysis."""


@workflow_mcp.prompt()
def upgrade_precon(
    commander: Annotated[str, Field(description="Commander of the precon")],
    budget: Annotated[float, Field(description="Total upgrade budget in USD")],
) -> str:
    """Guide upgrading a Commander precon."""
    return f"""Upgrade the {commander} precon within a ${budget:.2f} total budget.

The user should provide their full precon decklist. If they haven't, ask for it.

Step 1: Use commander_overview to understand {commander}'s strategy and key synergies.

Step 2: Use deck_analysis with the full precon decklist to identify:
  - Mana curve issues
  - Color pip requirements vs land base
  - Combo density and bracket estimate

Step 3: Use suggest_cuts to find the weakest cards in the precon.

Step 4: Use precon_upgrade with the decklist, commander, and budget
  to get paired upgrade suggestions (card in → card out).

Step 5: Verify the upgraded list with deck_validate.

Present: prioritized upgrade list with total cost, explaining each swap."""


@workflow_mcp.prompt()
def sealed_session(
    set_code: Annotated[str, Field(description="Set code for the sealed format (e.g. 'LCI')")],
) -> str:
    """Guide a sealed deck building session."""
    return f"""Sealed deck building session for {set_code}.

The user should provide their sealed pool (84-90 card names from 6 packs).
If they haven't, ask them to list their pool.

Step 1: Use sealed_pool_build with the pool and set_code="{set_code}".
  This will suggest 1-3 builds with color pairs, decklists, and mana curves.

Step 2: For the recommended build:
  - Explain why this color pair is strongest (card quality, curve, bombs)
  - Highlight key cards and synergies
  - Note sideboard options for tough matchups

Step 3: If 17Lands data is available:
  - Note which of the suggested cards have the best GIH WR
  - Flag any cards that look good on paper but underperform statistically
  - Check the archetype win rate for the suggested colors

Help the user finalize their 40-card deck and plan sideboard adjustments."""


@workflow_mcp.prompt()
def draft_review(
    set_code: Annotated[str, Field(description="Set code for the draft format (e.g. 'LCI')")],
) -> str:
    """Guide a post-draft review session."""
    return f"""Post-draft review session for {set_code}.

The user should provide their draft picks in order (P1P1 through P3P14).
Optionally, they can also provide their final submitted deck.

Step 1: Use draft_log_review with the picks and set_code="{set_code}".
  This provides pick-by-pick GIH WR analysis.

Step 2: Analyze key decision points:
  - Where did you pass a significantly higher-WR card?
  - When did you commit to colors? Was it the right time?
  - Were there clear signals you missed or correctly read?

Step 3: If final deck provided:
  - What % of picks made the maindeck?
  - Were there sideboard cards that should have been maindeck?
  - Any cards that shouldn't have made the cut?

Step 4: Use draft_signal_read with the first 6-8 picks to retroactively analyze
  what colors were actually open during pack 1.

Provide a draft grade and 2-3 specific improvements for next time."""


@workflow_mcp.prompt()
def compare_commanders(
    commanders: Annotated[
        str, Field(description="Comma-separated commander names to compare (2-5)")
    ],
) -> str:
    """Compare commanders to help choose which to build."""
    return f"""Compare these commanders: {commanders}

Step 1: Use commander_comparison to get the side-by-side data:
  - Stats, color identity, EDHREC popularity
  - Combo count per commander
  - Shared vs unique staples

Step 2: For each commander, briefly note:
  - Primary strategy and win conditions
  - Power ceiling and floor
  - Budget entry point (are the key cards expensive?)

Step 3: Use spellbook_find_combos for each commander to compare combo density.

Step 4: Recommendation:
  - Which is most powerful? Most fun? Most budget-friendly?
  - Which has the most room for personal expression vs solved builds?
  - Match recommendation to the user's stated preferences if given.

Give a clear recommendation with reasoning."""


@workflow_mcp.prompt()
def rotation_plan() -> str:
    """Guide Standard rotation preparation."""
    return """Standard rotation planning session.

Step 1: Use rotation_check to see what sets are currently in Standard
  and which are next to rotate.

Step 2: If the user has a Standard deck, ask them to provide the decklist.
  Use rotation_check with their card list to identify rotating cards.

Step 3: For each rotating card:
  - How critical is it to the deck's strategy?
  - Use bulk_similar_cards to find replacements from non-rotating sets
  - Use price_comparison to check prices of replacements

Step 4: Assessment:
  - How many cards rotate? Is the deck's core intact post-rotation?
  - Estimated cost to replace rotating cards
  - Should the user pivot to a different strategy?

Present: rotation impact summary, replacement plan with costs, and recommendation."""


# ---------------------------------------------------------------------------
# Format Workflow Resources
# ---------------------------------------------------------------------------


@workflow_mcp.resource("mtg://theme/{theme}")
async def get_theme_mappings(theme: str) -> dict[str, object]:
    """Theme keyword mappings — oracle text patterns that define a theme."""
    from mtg_mcp_server.workflows.building import THEME_MAPPINGS

    theme_lower = theme.lower().strip()
    if theme_lower in THEME_MAPPINGS:
        mapping = THEME_MAPPINGS[theme_lower]
        return {"theme": theme, "patterns": {k: v for k, v in mapping.items()}}
    return {"theme": theme, "available_themes": sorted(THEME_MAPPINGS.keys())}


@workflow_mcp.resource("mtg://tribe/{tribe}/staples")
async def get_tribe_staples(tribe: str) -> dict[str, object]:
    """Top cards for a creature type — requires bulk data at runtime."""
    return {"tribe": tribe, "note": "Use the tribal_staples tool for full results"}


@workflow_mcp.resource("mtg://draft/{set_code}/signals")
async def get_draft_signals(set_code: str) -> dict[str, object]:
    """Color openness heuristics — requires 17Lands data at runtime."""
    return {"set_code": set_code, "note": "Use the draft_signal_read tool for full results"}
