"""Commander Spellbook MCP provider — combo search, decklist analysis, bracket estimation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated

import structlog
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.lifespan import lifespan
from fastmcp.tools import ToolResult
from pydantic import Field

from mtg_mcp_server.config import Settings
from mtg_mcp_server.providers import (
    ATTRIBUTION_SPELLBOOK,
    TAGS_COMBO,
    TAGS_LOOKUP,
    TAGS_SEARCH,
    TOOL_ANNOTATIONS,
)
from mtg_mcp_server.services.spellbook import (
    ComboNotFoundError,
    SpellbookClient,
    SpellbookError,
)
from mtg_mcp_server.utils.slim import slim_combo

if TYPE_CHECKING:
    from mtg_mcp_server.types import Combo

# Spellbook API uses single-letter zone codes in combo card data.
# Map them to human-readable names for tool output.
_ZONE_NAMES = {
    "B": "Battlefield",
    "H": "Hand",
    "G": "Graveyard",
    "E": "Exile",
    "L": "Library",
    "C": "Command Zone",
}

# Module-level client set by the lifespan. See scryfall.py for pattern rationale.
_client: SpellbookClient | None = None


@lifespan
async def spellbook_lifespan(server: FastMCP):
    """Manage the SpellbookClient lifecycle."""
    global _client
    settings = Settings()
    client = SpellbookClient(base_url=settings.spellbook_base_url)
    async with client:
        _client = client
        yield {}
    _client = None


spellbook_mcp = FastMCP("Spellbook", lifespan=spellbook_lifespan, mask_error_details=True)

log = structlog.get_logger(provider="spellbook")


def _get_client() -> SpellbookClient:
    """Return the initialized client or raise if the lifespan hasn't started."""
    if _client is None:
        raise RuntimeError("SpellbookClient not initialized — server lifespan not running")
    return _client


@spellbook_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_SEARCH | TAGS_COMBO)
async def find_combos(
    card_name: Annotated[
        str, Field(description="Card name to search for combos (e.g. 'Muldrotha, the Gravetide')")
    ],
    color_identity: Annotated[
        str | None,
        Field(
            description="Filter by color identity — name ('sultai'), letters ('BUG'), or 'wubrg'"
        ),
    ] = None,
    limit: Annotated[int, Field(description="Maximum number of combos to return")] = 10,
) -> ToolResult:
    """Search for known combos involving a specific card.

    Optionally filter by color identity (e.g. "sultai", "BUG", "wubrg").
    Returns up to `limit` combos with cards involved and results produced.
    """
    client = _get_client()
    try:
        combos = await client.find_combos(card_name, color_identity=color_identity, limit=limit)
    except SpellbookError as exc:
        raise ToolError(f"Spellbook API error: {exc}") from exc

    if not combos:
        return ToolResult(
            content=f"No combos found involving '{card_name}'." + ATTRIBUTION_SPELLBOOK,
            structured_content={
                "card_name": card_name,
                "total_combos": 0,
                "combos": [],
            },
        )

    lines = [f"Found {len(combos)} combo(s) involving {card_name}:"]
    for combo in combos:
        lines.append("")
        lines.extend(_format_combo_summary(combo))
        if combo.bracket_tag:
            lines.append(f"    Bracket: {combo.bracket_tag}")
        lines.append(f"    Popularity: {combo.popularity}")
    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_SPELLBOOK,
        structured_content={
            "card_name": card_name,
            "total_combos": len(combos),
            "combos": [slim_combo(combo) for combo in combos],
        },
    )


@spellbook_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_LOOKUP | TAGS_COMBO)
async def combo_details(
    combo_id: Annotated[
        str,
        Field(
            description="Spellbook combo ID from find_combos results (e.g. '1414-2730-5131-5256')"
        ),
    ],
) -> ToolResult:
    """Get detailed steps for a specific combo by its Spellbook ID.

    Use an ID from find_combos results (e.g. "1414-2730-5131-5256").
    """
    client = _get_client()
    try:
        combo = await client.get_combo(combo_id)
    except ComboNotFoundError as exc:
        raise ToolError(f"Combo not found: '{combo_id}'. Check the ID.") from exc
    except SpellbookError as exc:
        raise ToolError(f"Spellbook API error: {exc}") from exc

    lines = [f"**Combo {combo.id}** (Identity: {combo.identity})"]
    lines.append(f"Cards: {', '.join(c.name for c in combo.cards)}")

    for card in combo.cards:
        zones = ", ".join(_zone_name(z) for z in card.zone_locations)
        commander_note = " (Commander)" if card.must_be_commander else ""
        lines.append(f"  - {card.name}: {zones}{commander_note}")

    if combo.easy_prerequisites:
        lines.append(f"Prerequisites: {combo.easy_prerequisites}")
    if combo.notable_prerequisites:
        lines.append(f"Notable prerequisites: {combo.notable_prerequisites}")

    lines.append(f"\nSteps:\n{combo.description}")

    results = ", ".join(p.feature_name for p in combo.produces)
    lines.append(f"\nResults: {results}")

    if combo.bracket_tag:
        lines.append(f"Bracket: {combo.bracket_tag}")
    lines.append(f"Popularity: {combo.popularity}")

    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_SPELLBOOK,
        structured_content=combo.model_dump(mode="json"),
    )


@spellbook_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_COMBO)
async def find_decklist_combos(
    commanders: Annotated[
        list[str], Field(description="Commander card name(s) (e.g. ['Muldrotha, the Gravetide'])")
    ],
    decklist: Annotated[list[str], Field(description="List of card names in the main deck")],
) -> ToolResult:
    """Find combos present in (or nearly present in) a Commander decklist.

    Provide commander name(s) and a list of card names in the main deck.
    Returns combos that are fully included and those that are almost included.
    """
    client = _get_client()
    try:
        result = await client.find_decklist_combos(commanders, decklist)
    except SpellbookError as exc:
        raise ToolError(f"Spellbook API error: {exc}") from exc

    lines = [f"Decklist combo analysis (Identity: {result.identity}):"]

    if result.included:
        lines.append(f"\n**Included combos ({len(result.included)}):**")
        for combo in result.included:
            lines.extend(_format_combo_summary(combo))
    else:
        lines.append("\nNo fully included combos found.")

    if result.almost_included:
        lines.append(f"\n**Almost included combos ({len(result.almost_included)}):**")
        for combo in result.almost_included:
            lines.extend(_format_combo_summary(combo))

    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_SPELLBOOK,
        structured_content=result.model_dump(mode="json"),
    )


@spellbook_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_COMBO)
async def estimate_bracket(
    commanders: Annotated[
        list[str], Field(description="Commander card name(s) (e.g. ['Muldrotha, the Gravetide'])")
    ],
    decklist: Annotated[list[str], Field(description="List of card names in the main deck")],
) -> ToolResult:
    """Estimate the Commander bracket (power level) for a decklist.

    Provide commander name(s) and a list of card names in the main deck.
    Returns bracket tag and any bracket-relevant findings.
    """
    client = _get_client()
    try:
        result = await client.estimate_bracket(commanders, decklist)
    except SpellbookError as exc:
        raise ToolError(f"Spellbook API error: {exc}") from exc

    lines = [f"**Bracket Estimate:** {result.bracket_tag or 'Unknown'}"]

    if result.banned_cards:
        lines.append(f"Banned cards: {', '.join(result.banned_cards)}")
    if result.game_changer_cards:
        lines.append(f"Game-changer cards: {', '.join(result.game_changer_cards)}")
    if result.two_card_combos:
        lines.append(f"Two-card combos: {', '.join(str(c) for c in result.two_card_combos)}")
    if result.lock_combos:
        lines.append(f"Lock combos: {', '.join(str(c) for c in result.lock_combos)}")

    if not any(
        [
            result.banned_cards,
            result.game_changer_cards,
            result.two_card_combos,
            result.lock_combos,
        ]
    ):
        lines.append("No bracket-relevant concerns found.")

    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_SPELLBOOK,
        structured_content=result.model_dump(mode="json"),
    )


def _zone_name(code: str) -> str:
    """Map single-letter zone codes to human-readable names."""
    return _ZONE_NAMES.get(code, code)


def _format_combo_summary(combo: Combo) -> list[str]:
    """Format a combo as two indented summary lines: card list and produced results."""
    card_names = ", ".join(c.name for c in combo.cards) or "(no cards listed)"
    results = ", ".join(p.feature_name for p in combo.produces) or "(no results listed)"
    return [f"  [{combo.id}] {card_names}", f"    Produces: {results}"]


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@spellbook_mcp.resource("mtg://combo/{combo_id}")
async def combo_resource(combo_id: str) -> str:
    """Get combo details as JSON by Spellbook ID."""
    client = _get_client()
    try:
        combo = await client.get_combo(combo_id)
        return combo.model_dump_json()
    except ComboNotFoundError:
        log.debug("resource.combo_not_found", combo_id=combo_id)
        return json.dumps({"error": f"Combo not found: {combo_id}"})
    except SpellbookError as exc:
        log.warning("resource.combo_error", combo_id=combo_id, error=str(exc))
        return json.dumps({"error": f"Spellbook error: {exc}"})
