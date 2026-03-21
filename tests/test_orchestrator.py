"""Integration tests for the MTG orchestrator with mounted backends."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import respx

if TYPE_CHECKING:
    from fastmcp import Client

FIXTURES = Path(__file__).parent / "fixtures" / "edhrec"
EDHREC_BASE_URL = "https://json.edhrec.com"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class TestEdhrecMounted:
    """Verify EDHREC tools appear with edhrec_ namespace on the orchestrator."""

    async def test_namespaced_tools_appear(self, mcp_client: Client):
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        assert "edhrec_commander_staples" in tool_names
        assert "edhrec_card_synergy" in tool_names

    @respx.mock
    async def test_end_to_end_commander_staples(self, mcp_client: Client):
        fixture = _load_fixture("commander_muldrotha.json")
        respx.get(f"{EDHREC_BASE_URL}/pages/commanders/muldrotha-the-gravetide.json").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result = await mcp_client.call_tool(
            "edhrec_commander_staples",
            {"commander_name": "Muldrotha, the Gravetide"},
        )
        text = result.content[0].text
        assert "Muldrotha, the Gravetide" in text
        assert "Spore Frog" in text

    async def test_ping_still_available(self, mcp_client: Client):
        result = await mcp_client.call_tool("ping", {})
        assert result.data == "pong"
