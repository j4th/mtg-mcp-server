"""Integration tests for the workflow server with composed tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import Client


class TestWorkflowToolsRegistered:
    """Verify all workflow tools are registered on the workflow server."""

    async def test_all_workflow_tools_present(self, mcp_client: Client):
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        assert "commander_overview" in tool_names
        assert "evaluate_upgrade" in tool_names
        assert "draft_pack_pick" in tool_names
        assert "suggest_cuts" in tool_names
