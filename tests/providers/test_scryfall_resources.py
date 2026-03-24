"""Tests for Scryfall MCP provider resource templates."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from fastmcp import Client

from mtg_mcp_server.providers.scryfall import scryfall_mcp

FIXTURES = Path(__file__).parent.parent / "fixtures" / "scryfall"
BASE_URL = "https://api.scryfall.com"


def _load_fixture(name: str) -> dict:
    """Load a Scryfall JSON fixture file by name."""
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
async def client():
    """Provide an in-memory MCP client connected to the Scryfall provider."""
    async with Client(transport=scryfall_mcp) as c:
        yield c


class TestCardResource:
    """Scryfall mtg://card/{name} resource behavior."""

    @respx.mock
    async def test_returns_card_json(self, client: Client):
        """Card resource returns JSON with card name and type line."""
        fixture = _load_fixture("card_sol_ring.json")
        respx.get(f"{BASE_URL}/cards/named", params={"exact": "Sol Ring"}).mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result = await client.read_resource("mtg://card/Sol Ring")
        data = json.loads(result[0].text)
        assert data["name"] == "Sol Ring"
        assert data["type_line"] == fixture["type_line"]

    @respx.mock
    async def test_card_not_found_returns_error_json(self, client: Client):
        """Card resource returns error JSON for nonexistent cards."""
        fixture = _load_fixture("card_not_found.json")
        respx.get(f"{BASE_URL}/cards/named", params={"exact": "Xyzzy"}).mock(
            return_value=httpx.Response(404, json=fixture)
        )

        result = await client.read_resource("mtg://card/Xyzzy")
        data = json.loads(result[0].text)
        assert "error" in data
        assert "Card not found" in data["error"]


class TestCardRulingsResource:
    """Scryfall mtg://card/{name}/rulings resource behavior."""

    @respx.mock
    async def test_returns_rulings_json(self, client: Client):
        """Rulings resource returns a list of ruling objects with comments."""
        card_fixture = _load_fixture("card_muldrotha.json")
        rulings_fixture = _load_fixture("rulings_muldrotha.json")
        card_id = card_fixture["id"]

        respx.get(f"{BASE_URL}/cards/named", params={"exact": "Muldrotha, the Gravetide"}).mock(
            return_value=httpx.Response(200, json=card_fixture)
        )
        respx.get(f"{BASE_URL}/cards/{card_id}/rulings").mock(
            return_value=httpx.Response(200, json=rulings_fixture)
        )

        result = await client.read_resource("mtg://card/Muldrotha, the Gravetide/rulings")
        data = json.loads(result[0].text)
        assert isinstance(data, list)
        assert len(data) > 0
        assert "comment" in data[0]

    @respx.mock
    async def test_card_not_found_returns_error_json(self, client: Client):
        """Rulings resource returns error JSON for nonexistent cards."""
        fixture = _load_fixture("card_not_found.json")
        respx.get(f"{BASE_URL}/cards/named", params={"exact": "Xyzzy"}).mock(
            return_value=httpx.Response(404, json=fixture)
        )

        result = await client.read_resource("mtg://card/Xyzzy/rulings")
        data = json.loads(result[0].text)
        assert "error" in data
        assert "Card not found" in data["error"]

    @respx.mock
    async def test_server_error_returns_error_json(self, client: Client):
        """Card resource returns error JSON on Scryfall server failure."""
        respx.get(f"{BASE_URL}/cards/named", params={"exact": "Sol Ring"}).mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        result = await client.read_resource("mtg://card/Sol Ring")
        data = json.loads(result[0].text)
        assert "error" in data
        assert "Scryfall error" in data["error"]


class TestCardRulingsServerError:
    """Scryfall rulings resource server error handling."""

    @respx.mock
    async def test_server_error_returns_error_json(self, client: Client):
        """Rulings resource returns error JSON on Scryfall server failure."""
        respx.get(f"{BASE_URL}/cards/named", params={"exact": "Sol Ring"}).mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        result = await client.read_resource("mtg://card/Sol Ring/rulings")
        data = json.loads(result[0].text)
        assert "error" in data
        assert "Scryfall error" in data["error"]


class TestResourceTemplateRegistration:
    """Scryfall resource template registration."""

    async def test_resource_templates_registered(self, client: Client):
        """Both card and rulings resource templates are registered."""
        templates = await client.list_resource_templates()
        template_uris = {t.uriTemplate for t in templates}
        assert "mtg://card/{name}" in template_uris
        assert "mtg://card/{name}/rulings" in template_uris
