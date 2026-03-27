"""Workflow MCP server — composed tools calling multiple backend services.

This module is the wiring layer between MCP and the pure workflow functions
in ``commander.py``, ``draft.py``, ``deck.py``, and ``analysis.py``.  Each tool
here wraps a pure async function, injecting the service clients from the
module-level state and converting service exceptions to ``ToolError``.

The workflow server is mounted on the orchestrator **without** a namespace
so tool names stay clean (e.g. ``commander_overview``, not
``workflow_commander_overview``).
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Annotated

import structlog
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.lifespan import lifespan
from pydantic import Field

from mtg_mcp_server.config import Settings
from mtg_mcp_server.providers import (
    TAGS_COMMANDER,
    TAGS_DRAFT,
    TAGS_PRICING,
    TOOL_ANNOTATIONS,
)
from mtg_mcp_server.services.base import ServiceError
from mtg_mcp_server.services.edhrec import CommanderNotFoundError, EDHRECClient
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


@lifespan
async def workflow_lifespan(server: FastMCP):
    """Initialize all service clients needed by workflow tools.

    Uses ``AsyncExitStack`` to manage multiple clients in a single lifespan.
    Feature-flagged backends (17Lands, EDHREC, Scryfall bulk data) are only created
    when their corresponding ``Settings`` flag is enabled. All clients are torn down
    when the server shuts down.
    """
    global _scryfall, _spellbook, _seventeen_lands, _edhrec, _bulk
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
        yield {}
    _scryfall = None
    _spellbook = None
    _seventeen_lands = None
    _edhrec = None
    _bulk = None


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
) -> str:
    """Comprehensive commander profile combining data from all available sources.

    Returns card details, top combos, EDHREC staples, and synergy scores.
    Degrades gracefully if optional sources (EDHREC, Spellbook) are unavailable.
    """
    from mtg_mcp_server.workflows.commander import commander_overview as impl

    if not commander_name.strip():
        raise ToolError("Commander name cannot be empty.")

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
        raise ToolError(f"commander_overview failed: {exc}") from exc


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_COMMANDER)
async def evaluate_upgrade(
    card_name: Annotated[
        str, Field(description="Card to evaluate for the deck (e.g. 'Spore Frog')")
    ],
    commander_name: Annotated[str, Field(description="Commander the deck is built around")],
) -> str:
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
) -> str:
    """Rank cards in a draft pack using 17Lands win rate data.

    Provides GIH WR, ALSA, IWD stats, and color fit analysis based on current picks.
    Requires 17Lands to be enabled.
    """
    from mtg_mcp_server.workflows.draft import draft_pack_pick as impl

    try:
        return await impl(
            pack,
            set_code,
            seventeen_lands=_require_seventeen_lands(),
            current_picks=current_picks,
        )
    except ServiceError as exc:
        raise ToolError(f"17Lands error: {exc}") from exc


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_COMMANDER)
async def suggest_cuts(
    decklist: Annotated[list[str], Field(description="List of card names in the deck")],
    commander_name: Annotated[str, Field(description="Commander the deck is built around")],
    num_cuts: Annotated[int, Field(description="Number of cut candidates to suggest")] = 5,
) -> str:
    """Identify the weakest cards to cut from a commander decklist.

    Scores cards by synergy, inclusion rate, and combo membership.
    Degrades gracefully if EDHREC or Spellbook backends fail (uses whatever data is available).
    """
    from mtg_mcp_server.workflows.deck import suggest_cuts as impl

    if not commander_name.strip():
        raise ToolError("Commander name cannot be empty.")

    try:
        return await impl(
            decklist,
            commander_name,
            spellbook=_require_spellbook(),
            edhrec=_edhrec,
            num_cuts=num_cuts,
        )
    except ServiceError as exc:
        raise ToolError(f"suggest_cuts failed: {exc}") from exc


@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_COMMANDER)
async def card_comparison(
    cards: Annotated[list[str], Field(description="2-5 card names to compare side-by-side")],
    commander_name: Annotated[str, Field(description="Commander the deck is built around")],
    ctx: Context,
) -> str:
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
        return await impl(
            cards,
            commander_name,
            scryfall=_require_scryfall(),
            spellbook=_require_spellbook(),
            edhrec=_edhrec,
            on_progress=lambda step, total: _progress(ctx, step, total),
        )
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
    *,
    ctx: Context,
) -> str:
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
        return await impl(
            commander_name,
            budget=budget,
            num_suggestions=num_suggestions,
            scryfall=_require_scryfall(),
            edhrec=_require_edhrec(),
            on_progress=lambda step, total: _progress(ctx, step, total),
        )
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
) -> str:
    """Full decklist health check — mana curve, colors, combos, bracket, budget, synergy.

    Uses all available backends: Scryfall bulk data for rate-limit-free card resolution,
    Scryfall API as fallback, Spellbook for combos and bracket estimation, EDHREC for
    synergy scores. Degrades gracefully if optional backends are unavailable.
    """
    from mtg_mcp_server.workflows.analysis import deck_analysis as impl

    if not decklist:
        raise ToolError("Provide at least one card in the decklist.")

    try:
        return await impl(
            decklist,
            commander_name,
            bulk=_bulk,
            scryfall=_require_scryfall(),
            spellbook=_require_spellbook(),
            edhrec=_edhrec,
            on_progress=lambda step, total: _progress(ctx, step, total),
        )
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
    *,
    ctx: Context,
) -> str:
    """Draft format overview — top commons/uncommons and trap rares.

    Uses 17Lands card ratings to provide a data-driven format breakdown.
    Requires 17Lands to be enabled.
    """
    from mtg_mcp_server.workflows.draft import set_overview as impl

    try:
        return await impl(
            set_code,
            event_type=event_type,
            seventeen_lands=_require_seventeen_lands(),
            on_progress=lambda step, total: _progress(ctx, step, total),
        )
    except ServiceError as exc:
        raise ToolError(f"17Lands error: {exc}") from exc


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
