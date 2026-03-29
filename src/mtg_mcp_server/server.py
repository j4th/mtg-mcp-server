"""MTG MCP Server — orchestrator that mounts all provider backends.

Creates the root ``FastMCP("MTG")`` server and mounts each provider sub-server
with a namespace prefix (e.g. ``scryfall_``, ``draft_``). The workflow server is
mounted **without** a namespace so its tools have clean names like
``commander_overview`` rather than ``workflow_commander_overview``.

Feature-flagged backends (17Lands, EDHREC, Scryfall bulk data) are conditionally
mounted based on ``Settings`` values loaded from ``MTG_MCP_*`` env vars.
"""

from __future__ import annotations

import sys

import structlog
from fastmcp import FastMCP
from fastmcp.server.middleware.response_limiting import ResponseLimitingMiddleware
from mcp.types import Icon, ToolAnnotations

from mtg_mcp_server import __version__
from mtg_mcp_server.config import Settings
from mtg_mcp_server.logging import configure_logging
from mtg_mcp_server.providers.edhrec import edhrec_mcp
from mtg_mcp_server.providers.scryfall import scryfall_mcp
from mtg_mcp_server.providers.scryfall_bulk import scryfall_bulk_mcp
from mtg_mcp_server.providers.seventeen_lands import draft_mcp
from mtg_mcp_server.providers.spellbook import spellbook_mcp
from mtg_mcp_server.services.cache import disable_all_caches
from mtg_mcp_server.workflows.server import workflow_mcp

mcp = FastMCP(
    "MTG",
    version=__version__,
    mask_error_details=True,
    website_url="https://github.com/j4th/mtg-mcp-server",
    icons=[
        Icon(
            src="https://raw.githubusercontent.com/j4th/mtg-mcp-server/main/icon.svg",
            mimeType="image/svg+xml",
            sizes=["512x512"],
        )
    ],
    instructions=(
        "Magic: The Gathering data and analytics server.\n\n"
        "Tool categories:\n"
        "- scryfall_*: Card search, details, prices, rulings (Scryfall API)\n"
        "- spellbook_*: Combo search, decklist analysis, bracket estimation (Commander Spellbook)\n"
        "- draft_*: Draft card ratings and archetype stats (17Lands)\n"
        "- edhrec_*: Commander staples and synergy scores (EDHREC, beta)\n"
        "- bulk_*: Rate-limit-free card lookup and search (Scryfall bulk data)\n\n"
        "Workflow tools (no prefix):\n"
        "- commander_overview: Full commander profile from all sources\n"
        "- evaluate_upgrade: Assess a card for a commander deck\n"
        "- card_comparison: Side-by-side comparison of 2-5 cards\n"
        "- budget_upgrade: Price-constrained upgrade suggestions\n"
        "- deck_analysis: Full decklist health check\n"
        "- set_overview: Draft format card ratings overview and trap rares\n"
        "- draft_pack_pick: Rank cards in a draft pack\n"
        "- suggest_cuts: Identify weakest cards to cut\n"
        "- deck_validate: Validate a decklist against format rules\n"
        "- suggest_mana_base: Suggest lands for a decklist\n"
        "- price_comparison: Compare card prices side-by-side\n\n"
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

try:
    _settings = Settings()
except Exception:
    structlog.get_logger(service="startup").exception("invalid_configuration")
    sys.exit(1)

if _settings.disable_cache:
    disable_all_caches()

# Feature-flagged backends: enabled by default but can be disabled via env vars.
# 17Lands rate-limits aggressively; EDHREC scrapes undocumented endpoints;
# Scryfall bulk data requires a ~30MB download on first access.
if _settings.enable_17lands:
    mcp.mount(draft_mcp, namespace="draft")
if _settings.enable_edhrec:
    mcp.mount(edhrec_mcp, namespace="edhrec")
if _settings.enable_bulk_data:
    mcp.mount(scryfall_bulk_mcp, namespace="bulk")

# Workflow tools mounted without namespace for clean names.
mcp.mount(workflow_mcp)

# Limit response sizes to 500KB to prevent edge-case payloads from overwhelming
# LLM context windows. Most tool outputs are well under 10KB.
mcp.add_middleware(ResponseLimitingMiddleware(max_size=500_000))

# CodeMode: experimental transform that replaces individual tools with meta-tools
# for discovery and code execution. Useful at 40+ tools to reduce LLM context.
if _settings.enable_code_mode:
    try:
        from fastmcp.experimental.transforms.code_mode import CodeMode

        mcp.add_transform(CodeMode())
        structlog.get_logger(service="startup").info("code_mode.enabled")
    except ImportError:
        structlog.get_logger(service="startup").warning(
            "code_mode.unavailable",
            hint='Install with: pip install "mtg-mcp-server[code-mode]"',
        )


# Ping is a local health check — no network access, so openWorldHint=False.
_PING_ANNOTATIONS = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)


@mcp.tool(annotations=_PING_ANNOTATIONS)
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
