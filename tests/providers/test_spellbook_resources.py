"""Tests for Commander Spellbook MCP provider resource templates."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from fastmcp import Client

from mtg_mcp.providers.spellbook import spellbook_mcp

FIXTURES = Path(__file__).parent.parent / "fixtures" / "spellbook"
BASE_URL = "https://backend.commanderspellbook.com"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
async def client():
    async with Client(transport=spellbook_mcp) as c:
        yield c


class TestComboResource:
    @respx.mock
    async def test_returns_combo_json(self, client: Client):
        fixture = _load_fixture("combo_detail.json")
        respx.get(f"{BASE_URL}/variants/1414-2730-5131-5256/").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result = await client.read_resource("mtg://combo/1414-2730-5131-5256")
        data = json.loads(result[0].text)
        assert data["id"] == "1414-2730-5131-5256"
        assert data["identity"] == "BGU"
        assert len(data["cards"]) > 0

    @respx.mock
    async def test_combo_not_found_returns_error_json(self, client: Client):
        respx.get(f"{BASE_URL}/variants/9999-9999/").mock(
            return_value=httpx.Response(404, json={"detail": "Not found."})
        )

        result = await client.read_resource("mtg://combo/9999-9999")
        data = json.loads(result[0].text)
        assert "error" in data
        assert "Combo not found" in data["error"]


class TestResourceTemplateRegistration:
    async def test_resource_templates_registered(self, client: Client):
        templates = await client.list_resource_templates()
        template_uris = {t.uriTemplate for t in templates}
        assert "mtg://combo/{combo_id}" in template_uris
