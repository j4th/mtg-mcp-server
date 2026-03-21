"""MTG MCP Server — orchestrator that mounts all provider backends."""

from __future__ import annotations

import sys

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from mtg_mcp.config import Settings
from mtg_mcp.logging import configure_logging
from mtg_mcp.providers.scryfall import scryfall_mcp

mcp = FastMCP("MTG", instructions="Magic: The Gathering data and analytics server.")

mcp.mount(scryfall_mcp, namespace="scryfall")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
async def ping() -> str:
    """Health check — returns 'pong'."""
    return "pong"


def main() -> None:  # pragma: no cover
    """Entry point: load settings, configure logging, start transport."""
    settings = Settings()
    configure_logging(settings.log_level)

    transport = settings.transport
    if len(sys.argv) > 1:
        transport = sys.argv[1]

    if transport == "http":
        mcp.run(transport="streamable-http", host="127.0.0.1", port=settings.http_port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
