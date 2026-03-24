"""Tests for 17Lands MCP provider resource templates."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from fastmcp import Client

from mtg_mcp_server.providers.seventeen_lands import draft_mcp

FIXTURES = Path(__file__).parent.parent / "fixtures" / "seventeen_lands"
BASE_URL = "https://www.17lands.com"


def _load_fixture(name: str) -> list[dict]:
    """Load a 17Lands JSON fixture file by name."""
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
async def client():
    """Provide an in-memory MCP client connected to the 17Lands provider."""
    async with Client(transport=draft_mcp) as c:
        yield c


class TestDraftRatingsResource:
    """17Lands mtg://draft/{set_code}/ratings resource behavior."""

    @respx.mock
    async def test_returns_ratings_json(self, client: Client):
        """Draft ratings resource returns JSON list with card names and win rates."""
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
    async def test_server_error_returns_error_json(self, client: Client):
        """Draft ratings resource returns error JSON on 17Lands server failure."""
        respx.get(
            f"{BASE_URL}/card_ratings/data",
            params={"expansion": "FAKE", "event_type": "PremierDraft"},
        ).mock(return_value=httpx.Response(500, text="Internal Server Error"))

        result = await client.read_resource("mtg://draft/FAKE/ratings")
        data = json.loads(result[0].text)
        assert "error" in data
        assert "17Lands error" in data["error"]


class TestResourceTemplateRegistration:
    """17Lands resource template registration."""

    async def test_resource_templates_registered(self, client: Client):
        """Draft ratings resource template is registered on the provider."""
        templates = await client.list_resource_templates()
        template_uris = {t.uriTemplate for t in templates}
        assert "mtg://draft/{set_code}/ratings" in template_uris
