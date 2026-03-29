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
    TAGS_DRAFT,
    TAGS_PRICING,
    TAGS_RULES,
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
            response_format=response_format,
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
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
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
            response_format=response_format,
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
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
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
            response_format=response_format,
        )
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
            response_format=response_format,
        )
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
            response_format=response_format,
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
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
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
            response_format=response_format,
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
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
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
            response_format=response_format,
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
    response_format: Annotated[
        Literal["detailed", "concise"],
        Field(description="Output verbosity: 'detailed' (default) or 'concise'"),
    ] = "detailed",
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
            response_format=response_format,
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
) -> str:
    """Validate a decklist against a format's construction rules.

    Checks legality, deck size, copy limits, color identity (Commander), singleton
    rules, and Pauper rarity. Returns VALID or INVALID with actionable error messages.
    """
    from mtg_mcp_server.workflows.validation import deck_validate as impl

    if not decklist:
        raise ToolError("Provide at least one card in the decklist.")

    try:
        return await impl(
            decklist,
            format,
            commander=commander,
            sideboard=sideboard,
            bulk=_require_bulk(),
            response_format=response_format,
        )
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
) -> str:
    """Suggest a mana base for a decklist based on color pip distribution.

    Analyzes color requirements, recommends land count, and suggests format-legal
    dual lands. Handles hybrid and phyrexian mana.
    """
    from mtg_mcp_server.workflows.mana_base import suggest_mana_base as impl

    if not decklist:
        raise ToolError("Provide at least one card in the decklist.")

    try:
        return await impl(
            decklist,
            format,
            total_lands=total_lands,
            bulk=_require_bulk(),
            response_format=response_format,
        )
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
) -> str:
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
        return await impl(
            cards,
            bulk=_require_bulk(),
            response_format=response_format,
        )
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
async def get_rule(number: str) -> dict:
    """Rule text by number (e.g. mtg://rules/704.5k)."""
    rules = _require_rules()
    rule = await rules.lookup_by_number(number)
    return rule.model_dump(mode="json") if rule else {"error": f"Rule {number} not found"}


@workflow_mcp.resource("mtg://rules/glossary/{term}")
async def get_glossary_term(term: str) -> dict:
    """Glossary definition by term."""
    rules = _require_rules()
    entry = await rules.glossary_lookup(term)
    return entry.model_dump(mode="json") if entry else {"error": f"Term '{term}' not found"}


@workflow_mcp.resource("mtg://rules/keywords")
async def list_keywords() -> list[dict]:
    """All keywords with brief definitions."""
    rules = _require_rules()
    return await rules.list_keywords()


@workflow_mcp.resource("mtg://rules/sections")
async def list_sections() -> list[dict]:
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
