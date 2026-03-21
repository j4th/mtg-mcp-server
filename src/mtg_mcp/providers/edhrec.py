"""EDHREC MCP provider — commander staples and card synergy tools.

Uses undocumented EDHREC endpoints. Behind the MTG_MCP_ENABLE_EDHREC feature flag.
"""

from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.lifespan import lifespan
from mcp.types import ToolAnnotations

from mtg_mcp.services.edhrec import CommanderNotFoundError, EDHRECClient, EDHRECError

_ANNOTATIONS = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)

_client: EDHRECClient | None = None


@lifespan
async def edhrec_lifespan(server: FastMCP):
    global _client
    client = EDHRECClient()
    async with client:
        _client = client
        yield {}
    _client = None


edhrec_mcp = FastMCP("EDHREC", lifespan=edhrec_lifespan)


def _get_client() -> EDHRECClient:
    if _client is None:
        raise RuntimeError("EDHRECClient not initialized — server lifespan not running")
    return _client


@edhrec_mcp.tool(annotations=_ANNOTATIONS)
async def commander_staples(
    commander_name: str,
    category: str | None = None,
) -> str:
    """Get the most-played cards for a commander with synergy scores and inclusion rates.

    Shows which cards are most commonly played with this commander and how
    synergistic they are (vs. generic popularity).

    Args:
        commander_name: Full commander name (e.g. "Muldrotha, the Gravetide").
        category: Optional filter by card type (e.g. "creatures", "enchantments", "lands").
    """
    client = _get_client()
    try:
        data = await client.commander_top_cards(commander_name, category=category)
    except CommanderNotFoundError as exc:
        raise ToolError(
            f"Commander not found on EDHREC: '{commander_name}'. "
            "Check spelling — EDHREC uses exact names."
        ) from exc
    except EDHRECError as exc:
        raise ToolError(f"EDHREC API error: {exc}") from exc

    lines = [f"**{data.commander_name}** — EDHREC Data ({data.total_decks} decks)"]

    if not data.cardlists:
        lines.append("No card data available.")
        return "\n".join(lines)

    for cardlist in data.cardlists:
        lines.append(f"\n### {cardlist.header}")
        for card in cardlist.cardviews:
            pct = _inclusion_pct(card.num_decks, data.total_decks)
            synergy_str = f"+{card.synergy:.0%}" if card.synergy >= 0 else f"{card.synergy:.0%}"
            lines.append(
                f"  {card.name} — synergy: {synergy_str}, in {pct}% of decks ({card.num_decks})"
            )

    return "\n".join(lines)


@edhrec_mcp.tool(annotations=_ANNOTATIONS)
async def card_synergy(
    card_name: str,
    commander_name: str,
) -> str:
    """Get synergy data for a specific card with a specific commander.

    Shows how synergistic the card is with the commander compared to its
    general popularity, plus how many decks include it.

    Args:
        card_name: The card to check (e.g. "Spore Frog").
        commander_name: The commander to check against (e.g. "Muldrotha, the Gravetide").
    """
    client = _get_client()
    try:
        card = await client.card_synergy(card_name, commander_name)
    except CommanderNotFoundError as exc:
        raise ToolError(
            f"Commander not found on EDHREC: '{commander_name}'. "
            "Check spelling — EDHREC uses exact names."
        ) from exc
    except EDHRECError as exc:
        raise ToolError(f"EDHREC API error: {exc}") from exc

    if card is None:
        return (
            f"'{card_name}' was not found in EDHREC data for '{commander_name}'. "
            "The card may not be commonly played with this commander."
        )

    synergy_str = f"+{card.synergy:.0%}" if card.synergy >= 0 else f"{card.synergy:.0%}"
    pct = _inclusion_pct(card.num_decks, card.potential_decks)
    lines = [
        f"**{card.name}** with {commander_name}",
        f"Synergy: {synergy_str}",
        f"Inclusion: {pct}% of decks ({card.num_decks} of {card.potential_decks})",
    ]
    if card.synergy >= 0.3:
        lines.append("This is a high-synergy card for this commander.")
    return "\n".join(lines)


def _inclusion_pct(num_decks: int, total_decks: int) -> str:
    """Calculate inclusion percentage, handling division by zero."""
    if total_decks == 0:
        return "0"
    return f"{num_decks / total_decks * 100:.1f}"
