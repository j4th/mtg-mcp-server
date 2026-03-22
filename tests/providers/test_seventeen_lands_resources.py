"""Tests for 17Lands MCP provider resource templates."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from fastmcp import Client

from mtg_mcp.providers.seventeen_lands import draft_mcp

FIXTURES = Path(__file__).parent.parent / "fixtures" / "seventeen_lands"
BASE_URL = "https://www.17lands.com"


def _load_fixture(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
async def client():
    async with Client(transport=draft_mcp) as c:
        yield c


class TestDraftRatingsResource:
    @respx.mock
    async def test_returns_ratings_json(self, client: Client):
        fixture = _load_fixture("card_ratings_lci.json")
        respx.get(
            f"{BASE_URL}/card_ratings/data",
            params={"expansion": "LCI", "event_type": "PremierDraft"},
        ).mock(return_value=httpx.Response(200, json=fixture))

        result = await client.read_resource("mtg://draft/LCI/ratings")
        data = json.loads(result[0].text)
        assert isinstance(data, list)
        assert len(data) > 0
        assert "name" in data[0]
        assert "ever_drawn_win_rate" in data[0]

    @respx.mock
    async def test_server_error_propagates(self, client: Client):
        respx.get(
            f"{BASE_URL}/card_ratings/data",
            params={"expansion": "FAKE", "event_type": "PremierDraft"},
        ).mock(return_value=httpx.Response(500, text="Internal Server Error"))

        with pytest.raises(Exception, match="500"):
            await client.read_resource("mtg://draft/FAKE/ratings")


class TestResourceTemplateRegistration:
    async def test_resource_templates_registered(self, client: Client):
        templates = await client.list_resource_templates()
        template_uris = {t.uriTemplate for t in templates}
        assert "mtg://draft/{set_code}/ratings" in template_uris
