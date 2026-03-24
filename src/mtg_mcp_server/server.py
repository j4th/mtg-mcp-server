"""MTG MCP Server — orchestrator that mounts all provider backends.

Creates the root ``FastMCP("MTG")`` server and mounts each provider sub-server
with a namespace prefix (e.g. ``scryfall_``, ``draft_``). The workflow server is
mounted **without** a namespace so its tools have clean names like
``commander_overview`` rather than ``workflow_commander_overview``.

Feature-flagged backends (17Lands, EDHREC, MTGJSON) are conditionally mounted
based on ``Settings`` values loaded from ``MTG_MCP_*`` env vars.
"""

from __future__ import annotations

import sys

import structlog
from fastmcp import FastMCP
from fastmcp.server.middleware.response_limiting import ResponseLimitingMiddleware

from mtg_mcp_server.config import Settings
from mtg_mcp_server.logging import configure_logging
from mtg_mcp_server.providers import TOOL_ANNOTATIONS
from mtg_mcp_server.providers.edhrec import edhrec_mcp
from mtg_mcp_server.providers.mtgjson import mtgjson_mcp
from mtg_mcp_server.providers.scryfall import scryfall_mcp
from mtg_mcp_server.providers.seventeen_lands import draft_mcp
from mtg_mcp_server.providers.spellbook import spellbook_mcp
from mtg_mcp_server.services.cache import disable_all_caches
from mtg_mcp_server.workflows.server import workflow_mcp

mcp = FastMCP(
    "MTG",
    mask_error_details=True,
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
        "Prompts guide multi-step analysis workflows.\n\n"
        "mtg-mcp-server is unofficial Fan Content permitted under the Fan Content Policy. "
        "Not approved/endorsed by Wizards. Portions of the materials used are "
        "property of Wizards of the Coast. \u00a9 Wizards of the Coast LLC."
    ),
)

# Ensure logging is configured before any module-level code that might log.
# main() will reconfigure with the user's actual log level from Settings.
configure_logging()

# Always-on backends: Scryfall and Spellbook are stable public APIs.
mcp.mount(scryfall_mcp, namespace="scryfall")
mcp.mount(spellbook_mcp, namespace="spellbook")

_settings = Settings()
if _settings.disable_cache:
    disable_all_caches()

# Feature-flagged backends: enabled by default but can be disabled via env vars.
# 17Lands rate-limits aggressively; EDHREC scrapes undocumented endpoints;
# MTGJSON requires a ~100MB bulk file download on first access.
if _settings.enable_17lands:
    mcp.mount(draft_mcp, namespace="draft")
if _settings.enable_edhrec:
    mcp.mount(edhrec_mcp, namespace="edhrec")
if _settings.enable_mtgjson:
    mcp.mount(mtgjson_mcp, namespace="mtgjson")

# Workflow tools mounted without namespace for clean names.
mcp.mount(workflow_mcp)

# Limit response sizes to 500KB to prevent edge-case payloads from overwhelming
# LLM context windows. Most tool outputs are well under 10KB.
mcp.add_middleware(ResponseLimitingMiddleware(max_size=500_000))


@mcp.tool(annotations=TOOL_ANNOTATIONS)
async def ping() -> str:
    """Health check — returns 'pong'."""
    return "pong"


def main() -> None:  # pragma: no cover
    """Entry point: load settings, configure logging, start transport."""
    try:
        configure_logging(_settings.log_level)

        transport = _settings.transport
        if len(sys.argv) > 1:
            transport = sys.argv[1]

        if transport == "http":
            mcp.run(transport="streamable-http", host="127.0.0.1", port=_settings.http_port)
        else:
            mcp.run(transport="stdio")
    except KeyboardInterrupt:
        pass
    except Exception:
        structlog.get_logger(service="startup").exception("fatal_startup_error")
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
