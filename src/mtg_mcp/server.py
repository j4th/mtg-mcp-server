"""MTG MCP Server — orchestrator that mounts all provider backends."""

from __future__ import annotations

import sys

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from mtg_mcp.config import Settings
from mtg_mcp.logging import configure_logging
from mtg_mcp.providers.edhrec import edhrec_mcp
from mtg_mcp.providers.mtgjson import mtgjson_mcp
from mtg_mcp.providers.scryfall import scryfall_mcp
from mtg_mcp.providers.seventeen_lands import draft_mcp
from mtg_mcp.providers.spellbook import spellbook_mcp
from mtg_mcp.services.cache import disable_all_caches
from mtg_mcp.workflows.server import workflow_mcp

mcp = FastMCP(
    "MTG",
    instructions=(
        "Magic: The Gathering data and analytics server.\n\n"
        "Tool categories:\n"
        "- scryfall_*: Card search, details, prices, rulings (Scryfall API)\n"
        "- spellbook_*: Combo search, decklist analysis, bracket estimation (Commander Spellbook)\n"
        "- draft_*: Draft card ratings and archetype stats (17Lands)\n"
        "- edhrec_*: Commander staples and synergy scores (EDHREC, beta)\n"
        "- mtgjson_*: Rate-limit-free card lookup and search (MTGJSON bulk data)\n\n"
        "Workflow tools (no prefix):\n"
        "- commander_overview: Full commander profile from all sources\n"
        "- evaluate_upgrade: Assess a card for a commander deck\n"
        "- card_comparison: Side-by-side comparison of 2-5 cards\n"
        "- budget_upgrade: Price-constrained upgrade suggestions\n"
        "- deck_analysis: Full decklist health check\n"
        "- set_overview: Draft format card ratings overview and trap rares\n"
        "- draft_pack_pick: Rank cards in a draft pack\n"
        "- suggest_cuts: Identify weakest cards to cut\n\n"
        "Resources (mtg:// URIs) provide cached card, combo, and rating data.\n"
        "Prompts guide multi-step analysis workflows."
    ),
)

mcp.mount(scryfall_mcp, namespace="scryfall")
mcp.mount(spellbook_mcp, namespace="spellbook")

_settings = Settings()
if _settings.disable_cache:
    disable_all_caches()
if _settings.enable_17lands:
    mcp.mount(draft_mcp, namespace="draft")
if _settings.enable_edhrec:
    mcp.mount(edhrec_mcp, namespace="edhrec")
if _settings.enable_mtgjson:
    mcp.mount(mtgjson_mcp, namespace="mtgjson")

mcp.mount(workflow_mcp)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
async def ping() -> str:
    """Health check — returns 'pong'."""
    return "pong"


def main() -> None:  # pragma: no cover
    """Entry point: load settings, configure logging, start transport."""
    configure_logging(_settings.log_level)

    transport = _settings.transport
    if len(sys.argv) > 1:
        transport = sys.argv[1]

    if transport == "http":
        mcp.run(transport="streamable-http", host="127.0.0.1", port=_settings.http_port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
