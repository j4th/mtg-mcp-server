"""MTG MCP provider sub-servers.

Each provider is an independent FastMCP server that wraps a single service client.
Providers are mounted on the orchestrator (``server.py``) with namespaces to avoid
tool-name collisions (e.g. ``scryfall_search_cards``, ``draft_card_ratings``).

This package exports shared constants used by all provider modules:

- ``TOOL_ANNOTATIONS`` — MCP metadata applied to every tool.
- ``TAGS_*`` — Tag sets for tool categorization and filtering.

.. note::

   Do **not** import provider sub-modules here — that creates circular imports
   since each provider imports from this package.
"""

from mcp.types import ToolAnnotations

__all__ = [
    "ATTRIBUTION_17LANDS",
    "ATTRIBUTION_EDHREC",
    "ATTRIBUTION_SCRYFALL",
    "ATTRIBUTION_SCRYFALL_BULK",
    "ATTRIBUTION_SPELLBOOK",
    "TAGS_ALL_FORMATS",
    "TAGS_BETA",
    "TAGS_BUILD",
    "TAGS_COMBO",
    "TAGS_COMMANDER",
    "TAGS_DRAFT",
    "TAGS_LOOKUP",
    "TAGS_PRICING",
    "TAGS_SEARCH",
    "TAGS_VALIDATE",
    "TOOL_ANNOTATIONS",
]

# All tools are read-only (query external APIs, never mutate) and idempotent
# (same inputs always produce same outputs). openWorldHint signals that tools
# access external networks.
TOOL_ANNOTATIONS = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)

# Tag sets for MCP tool categorization. Clients can filter by tag to discover
# relevant tools. "stable" indicates well-tested, public-API-backed tools;
# "beta" marks tools backed by undocumented/fragile endpoints.
TAGS_LOOKUP = {"lookup", "stable"}
TAGS_SEARCH = {"search", "stable"}
TAGS_COMMANDER = {"commander", "analysis", "stable"}
TAGS_DRAFT = {"draft", "analysis", "stable"}
TAGS_COMBO = {"combo", "stable"}
TAGS_PRICING = {"pricing", "stable"}
TAGS_VALIDATE = {"validate", "all-formats", "stable"}
TAGS_BUILD = {"build", "analyze", "all-formats", "stable"}
TAGS_ALL_FORMATS = {"all-formats", "stable"}
TAGS_BETA = {"beta"}

# Attribution lines appended to tool outputs. These ensure compliance with
# upstream usage terms and enable both the LLM and end user to identify the
# data source.
ATTRIBUTION_SCRYFALL = "\n\n*Data provided by [Scryfall](https://scryfall.com)*"
ATTRIBUTION_SCRYFALL_BULK = "\n\n*Data: Scryfall bulk data (Oracle Cards)*"
ATTRIBUTION_SPELLBOOK = (
    "\n\n*Data provided by [Commander Spellbook](https://commanderspellbook.com)*"
)
ATTRIBUTION_17LANDS = "\n\n*Data provided by [17Lands](https://www.17lands.com)*"
ATTRIBUTION_EDHREC = "\n\n*Data provided by [EDHREC](https://edhrec.com)*"


def format_legalities(legalities: dict[str, str]) -> str:
    """Format a legalities dict as a comma-separated list of legal format names."""
    legal = [fmt for fmt, status in legalities.items() if status == "legal"]
    if not legal:
        return "Not legal in any format"
    return ", ".join(legal)
