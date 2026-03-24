"""Smoke tests for the MTG MCP server scaffold."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mtg_mcp_server.config import Settings
from mtg_mcp_server.logging import configure_logging, get_logger
from mtg_mcp_server.server import mcp

if TYPE_CHECKING:
    from fastmcp import Client


class TestServer:
    """Verify the orchestrator server is correctly configured."""

    def test_server_exists(self):
        assert mcp is not None

    def test_server_name(self):
        assert mcp.name == "MTG"

    async def test_ping_tool_registered(self, mcp_client: Client):
        tools = await mcp_client.list_tools()
        tool_names = [t.name for t in tools]
        assert "ping" in tool_names

    async def test_ping_returns_pong(self, mcp_client: Client):
        result = await mcp_client.call_tool("ping", {})
        assert result.data == "pong"

    async def test_ping_tool_annotations(self, mcp_client: Client):
        tools = await mcp_client.list_tools()
        ping_tool = next(t for t in tools if t.name == "ping")
        assert ping_tool.annotations.readOnlyHint is True
        assert ping_tool.annotations.idempotentHint is True
        assert ping_tool.annotations.openWorldHint is True

    def test_mask_error_details_enabled(self):
        assert mcp._mask_error_details is True


class TestSubServerMaskErrorDetails:
    """Verify mask_error_details is set on all sub-servers."""

    def test_scryfall_mask_error_details(self):
        from mtg_mcp_server.providers.scryfall import scryfall_mcp

        assert scryfall_mcp._mask_error_details is True

    def test_spellbook_mask_error_details(self):
        from mtg_mcp_server.providers.spellbook import spellbook_mcp

        assert spellbook_mcp._mask_error_details is True

    def test_seventeen_lands_mask_error_details(self):
        from mtg_mcp_server.providers.seventeen_lands import draft_mcp

        assert draft_mcp._mask_error_details is True

    def test_edhrec_mask_error_details(self):
        from mtg_mcp_server.providers.edhrec import edhrec_mcp

        assert edhrec_mcp._mask_error_details is True

    def test_mtgjson_mask_error_details(self):
        from mtg_mcp_server.providers.mtgjson import mtgjson_mcp

        assert mtgjson_mcp._mask_error_details is True

    def test_workflow_mask_error_details(self):
        from mtg_mcp_server.workflows.server import workflow_mcp

        assert workflow_mcp._mask_error_details is True


class TestConfig:
    """Verify Settings loads with sensible defaults."""

    def test_config_loads_defaults(self):
        settings = Settings()
        assert settings.transport == "stdio"
        assert settings.http_port == 8000
        assert settings.log_level == "INFO"
        assert settings.scryfall_base_url == "https://api.scryfall.com"
        assert settings.enable_edhrec is True
        assert settings.enable_17lands is True
        assert settings.disable_cache is False
        assert settings.enable_mtgjson is True

    def test_config_reads_env_vars(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("MTG_MCP_LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("MTG_MCP_HTTP_PORT", "9000")
        settings = Settings()
        assert settings.log_level == "DEBUG"
        assert settings.http_port == 9000


class TestLogging:
    """Verify structlog configuration."""

    @pytest.mark.parametrize("level", ["INFO", "DEBUG", "WARNING", "ERROR"])
    def test_logging_accepts_all_levels(self, level: str):
        configure_logging(level)

    def test_get_logger_returns_bound_logger(self):
        configure_logging("INFO")
        log = get_logger("test_service")
        assert log is not None

    def test_invalid_log_level_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid log level"):
            configure_logging("VERBOSE")
