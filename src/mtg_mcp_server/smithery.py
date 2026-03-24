"""Smithery deployment integration.

Provides a ``create_server`` factory function decorated with the Smithery SDK
so that Smithery can discover and serve this MCP server with session-scoped
configuration.  The config schema is exposed to the Smithery platform via the
``_smithery_config_schema`` attribute set by the ``@smithery.server()``
decorator.

This module is referenced from ``[tool.smithery]`` in *pyproject.toml* and
only imported when running under Smithery — it is **not** imported by the
normal ``mtg-mcp-server`` entry point.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from smithery.decorators import smithery


class SmitheryConfig(BaseModel):
    """Session configuration exposed to Smithery users."""

    MTG_MCP_ENABLE_17LANDS: bool = Field(
        default=True,
        title="Enable 17Lands",
        description="Enable 17Lands draft analytics backend for card ratings and archetype stats",
    )
    MTG_MCP_ENABLE_EDHREC: bool = Field(
        default=True,
        title="Enable EDHREC",
        description="Enable EDHREC commander metagame backend (uses undocumented endpoints)",
    )
    MTG_MCP_ENABLE_MTGJSON: bool = Field(
        default=True,
        title="Enable MTGJSON",
        description="Enable MTGJSON bulk card data for rate-limit-free lookups (~100 MB download on first use)",
    )
    MTG_MCP_LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        title="Log Level",
        description="Server logging level",
    )
    MTG_MCP_SCRYFALL_RATE_LIMIT_MS: int = Field(
        default=100,
        title="Scryfall Rate Limit (ms)",
        description="Minimum delay between Scryfall API calls in milliseconds",
        ge=10,
        le=5000,
    )
    MTG_MCP_MTGJSON_REFRESH_HOURS: int = Field(
        default=24,
        title="MTGJSON Refresh Interval (hours)",
        description="Hours between MTGJSON bulk data refreshes",
        ge=1,
        le=168,
    )


@smithery.server(config_schema=SmitheryConfig)
def create_server():
    from mtg_mcp_server.server import mcp

    return mcp
