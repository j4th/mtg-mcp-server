"""EDHREC MCP provider — commander staples and card synergy tools.

Uses undocumented EDHREC endpoints. Behind the MTG_MCP_ENABLE_EDHREC feature flag.
"""

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
from mtg_mcp_server.providers import ATTRIBUTION_EDHREC, TAGS_BETA, TOOL_ANNOTATIONS
from mtg_mcp_server.services.edhrec import CommanderNotFoundError, EDHRECClient, EDHRECError
from mtg_mcp_server.utils.slim import slim_edhrec_card

# Module-level client set by the lifespan. See scryfall.py for pattern rationale.
_client: EDHRECClient | None = None


@lifespan
async def edhrec_lifespan(server: FastMCP):
    """Manage the EDHRECClient lifecycle."""
    global _client
    settings = Settings()
    client = EDHRECClient(base_url=settings.edhrec_base_url)
    async with client:
        _client = client
        yield {}
    _client = None


edhrec_mcp = FastMCP("EDHREC", lifespan=edhrec_lifespan, mask_error_details=True)

log = structlog.get_logger(provider="edhrec")


def _get_client() -> EDHRECClient:
    """Return the initialized client or raise if the lifespan hasn't started."""
    if _client is None:
        raise RuntimeError("EDHRECClient not initialized — server lifespan not running")
    return _client


@edhrec_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_BETA)
async def commander_staples(
    commander_name: Annotated[
        str, Field(description="Full commander name (e.g. 'Muldrotha, the Gravetide')")
    ],
    category: Annotated[
        str | None,
        Field(
            description="Filter by card type: 'creatures', 'enchantments', 'artifacts', 'instants', 'sorceries', 'lands', 'planeswalkers'"
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(description="Max cards per category (default 10, 0 for all)"),
    ] = 10,
) -> ToolResult:
    """Get the most-played cards for a commander with synergy scores and inclusion rates.

    Shows which cards are most commonly played with this commander and how
    synergistic they are (vs. generic popularity).
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
        return ToolResult(
            content="\n".join(lines) + ATTRIBUTION_EDHREC,
            structured_content={
                "commander_name": data.commander_name,
                "total_decks": data.total_decks,
                "categories": [],
            },
        )

    for cardlist in data.cardlists:
        cards = cardlist.cardviews if limit == 0 else cardlist.cardviews[:limit]
        lines.append(f"\n### {cardlist.header}")
        for card in cards:
            pct = _inclusion_pct(card.num_decks, data.total_decks)
            synergy_str = f"+{card.synergy:.0%}" if card.synergy >= 0 else f"{card.synergy:.0%}"
            lines.append(
                f"  {card.name} — synergy: {synergy_str}, in {pct}% of decks ({card.num_decks})"
            )

    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_EDHREC,
        structured_content={
            "commander_name": data.commander_name,
            "total_decks": data.total_decks,
            "categories": [
                {
                    "header": cardlist.header,
                    "cards": [
                        slim_edhrec_card(card)
                        for card in (
                            cardlist.cardviews if limit == 0 else cardlist.cardviews[:limit]
                        )
                    ],
                }
                for cardlist in data.cardlists
            ],
        },
    )


@edhrec_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_BETA)
async def card_synergy(
    card_name: Annotated[str, Field(description="Card to check synergy for (e.g. 'Spore Frog')")],
    commander_name: Annotated[
        str,
        Field(description="Commander to check synergy against (e.g. 'Muldrotha, the Gravetide')"),
    ],
) -> ToolResult:
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
        markdown = (
            f"'{card_name}' was not found in EDHREC data for '{commander_name}'. "
            "The card may not be commonly played with this commander." + ATTRIBUTION_EDHREC
        )
        return ToolResult(
            content=markdown,
            structured_content={
                "card_name": card_name,
                "commander_name": commander_name,
                "found": False,
            },
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
    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION_EDHREC,
        structured_content={
            "card_name": card.name,
            "commander_name": commander_name,
            "found": True,
            "synergy": card.synergy,
            "num_decks": card.num_decks,
            "potential_decks": card.potential_decks,
            "inclusion_pct": float(pct),
        },
    )


def _inclusion_pct(num_decks: int, total_decks: int) -> str:
    """Calculate inclusion percentage, handling division by zero."""
    if total_decks == 0:
        return "0"
    return f"{num_decks / total_decks * 100:.1f}"


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@edhrec_mcp.resource("mtg://commander/{name}/staples")
async def commander_staples_resource(name: str) -> str:
    """Get commander staples data as JSON."""
    client = _get_client()
    try:
        data = await client.commander_top_cards(name)
        return data.model_dump_json()
    except CommanderNotFoundError:
        log.debug("resource.commander_not_found", name=name)
        return json.dumps({"error": f"Commander not found: {name}"})
    except EDHRECError as exc:
        log.warning("resource.staples_error", name=name, error=str(exc))
        return json.dumps({"error": f"EDHREC error: {exc}"})
