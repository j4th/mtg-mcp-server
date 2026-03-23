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
TAGS_BETA = {"beta"}
