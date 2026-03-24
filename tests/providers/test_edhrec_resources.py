"""Tests for EDHREC MCP provider resource templates."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from fastmcp import Client

from mtg_mcp_server.providers.edhrec import edhrec_mcp

FIXTURES = Path(__file__).parent.parent / "fixtures" / "edhrec"
BASE_URL = "https://json.edhrec.com"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
async def client():
    async with Client(transport=edhrec_mcp) as c:
        yield c


class TestCommanderStaplesResource:
    @respx.mock
    async def test_returns_staples_json(self, client: Client):
        fixture = _load_fixture("commander_muldrotha.json")
        respx.get(f"{BASE_URL}/pages/commanders/muldrotha-the-gravetide.json").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result = await client.read_resource("mtg://commander/Muldrotha, the Gravetide/staples")
        data = json.loads(result[0].text)
        assert data["commander_name"] == "Muldrotha, the Gravetide"
        assert "cardlists" in data
        assert data["total_decks"] > 0

    @respx.mock
    async def test_commander_not_found_returns_error_json(self, client: Client):
        respx.get(f"{BASE_URL}/pages/commanders/xyzzy-nonexistent.json").mock(
            return_value=httpx.Response(404, text="Not Found")
        )

        result = await client.read_resource("mtg://commander/Xyzzy Nonexistent/staples")
        data = json.loads(result[0].text)
        assert "error" in data
        assert "Commander not found" in data["error"]

    @respx.mock
    async def test_server_error_returns_error_json(self, client: Client):
        respx.get(f"{BASE_URL}/pages/commanders/muldrotha-the-gravetide.json").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        result = await client.read_resource("mtg://commander/Muldrotha, the Gravetide/staples")
        data = json.loads(result[0].text)
        assert "error" in data
        assert "EDHREC error" in data["error"]


class TestResourceTemplateRegistration:
    async def test_resource_templates_registered(self, client: Client):
        templates = await client.list_resource_templates()
        template_uris = {t.uriTemplate for t in templates}
        assert "mtg://commander/{name}/staples" in template_uris
