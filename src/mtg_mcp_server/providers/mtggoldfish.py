"""MTGGoldfish metagame data provider — stub for scaffold.

Tools will be implemented in Phase 2. This module provides the FastMCP
server instance that the orchestrator imports and mounts.
"""

from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan

_client = None


@lifespan
async def mtggoldfish_lifespan(server: FastMCP):
    """Placeholder lifespan — Phase 2 will add MTGGoldfishClient."""
    global _client
    yield {}
    _client = None


mtggoldfish_mcp = FastMCP("MTGGoldfish", lifespan=mtggoldfish_lifespan, mask_error_details=True)
