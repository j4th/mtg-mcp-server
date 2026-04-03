"""Verify every tool parameter has a description for Smithery compliance."""

from __future__ import annotations

import pytest
from fastmcp import Client

from mtg_mcp_server.providers.edhrec import edhrec_mcp
from mtg_mcp_server.providers.moxfield import moxfield_mcp
from mtg_mcp_server.providers.mtggoldfish import mtggoldfish_mcp
from mtg_mcp_server.providers.scryfall import scryfall_mcp
from mtg_mcp_server.providers.scryfall_bulk import scryfall_bulk_mcp
from mtg_mcp_server.providers.seventeen_lands import draft_mcp
from mtg_mcp_server.providers.spellbook import spellbook_mcp
from mtg_mcp_server.providers.spicerack import spicerack_mcp
from mtg_mcp_server.workflows.server import workflow_mcp


@pytest.mark.parametrize(
    ("server", "server_name"),
    [
        (scryfall_mcp, "scryfall"),
        (spellbook_mcp, "spellbook"),
        (draft_mcp, "draft"),
        (edhrec_mcp, "edhrec"),
        (moxfield_mcp, "moxfield"),
        (scryfall_bulk_mcp, "scryfall_bulk"),
        (spicerack_mcp, "spicerack"),
        (mtggoldfish_mcp, "mtggoldfish"),
        (workflow_mcp, "workflow"),
    ],
)
async def test_all_tool_params_have_descriptions(server, server_name):
    """Every tool parameter must have a description for MCP schema compliance."""
    async with Client(transport=server) as client:
        tools = await client.list_tools()
        missing = []
        for tool in tools:
            props = tool.inputSchema.get("properties", {})
            for param_name, param_schema in props.items():
                if "description" not in param_schema:
                    missing.append(f"{tool.name}.{param_name}")
        assert not missing, f"{server_name}: {len(missing)} params missing descriptions: {missing}"
