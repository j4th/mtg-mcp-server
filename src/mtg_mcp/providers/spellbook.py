"""Commander Spellbook MCP provider — combo search, decklist analysis, bracket estimation."""

from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.lifespan import lifespan
from mcp.types import ToolAnnotations

from mtg_mcp.services.spellbook import (
    ComboNotFoundError,
    SpellbookClient,
    SpellbookError,
)

_ANNOTATIONS = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)

_client: SpellbookClient | None = None


@lifespan
async def spellbook_lifespan(server: FastMCP):
    global _client
    client = SpellbookClient()
    async with client:
        _client = client
        yield {}
    _client = None


spellbook_mcp = FastMCP("Spellbook", lifespan=spellbook_lifespan)


def _get_client() -> SpellbookClient:
    if _client is None:
        raise RuntimeError("SpellbookClient not initialized — server lifespan not running")
    return _client


@spellbook_mcp.tool(annotations=_ANNOTATIONS)
async def find_combos(
    card_name: str,
    color_identity: str | None = None,
    limit: int = 10,
) -> str:
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
        return f"No combos found involving '{card_name}'."

    lines = [f"Found {len(combos)} combo(s) involving {card_name}:"]
    for combo in combos:
        card_names = ", ".join(c.name for c in combo.cards)
        results = ", ".join(p.feature_name for p in combo.produces)
        lines.append(f"\n  [{combo.id}] {card_names}")
        lines.append(f"    Produces: {results}")
        if combo.bracket_tag:
            lines.append(f"    Bracket: {combo.bracket_tag}")
        lines.append(f"    Popularity: {combo.popularity}")
    return "\n".join(lines)


@spellbook_mcp.tool(annotations=_ANNOTATIONS)
async def combo_details(
    combo_id: str,
) -> str:
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

    return "\n".join(lines)


@spellbook_mcp.tool(annotations=_ANNOTATIONS)
async def find_decklist_combos(
    commanders: list[str],
    decklist: list[str],
) -> str:
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
            card_names = ", ".join(c.name for c in combo.cards)
            results = ", ".join(p.feature_name for p in combo.produces)
            lines.append(f"  [{combo.id}] {card_names}")
            lines.append(f"    Produces: {results}")
    else:
        lines.append("\nNo fully included combos found.")

    if result.almost_included:
        lines.append(f"\n**Almost included combos ({len(result.almost_included)}):**")
        for combo in result.almost_included:
            card_names = ", ".join(c.name for c in combo.cards)
            results = ", ".join(p.feature_name for p in combo.produces)
            lines.append(f"  [{combo.id}] {card_names}")
            lines.append(f"    Produces: {results}")

    return "\n".join(lines)


@spellbook_mcp.tool(annotations=_ANNOTATIONS)
async def estimate_bracket(
    commanders: list[str],
    decklist: list[str],
) -> str:
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

    return "\n".join(lines)


def _zone_name(code: str) -> str:
    """Map single-letter zone codes to human-readable names."""
    zones = {
        "B": "Battlefield",
        "H": "Hand",
        "G": "Graveyard",
        "E": "Exile",
        "L": "Library",
        "C": "Command Zone",
    }
    return zones.get(code, code)
