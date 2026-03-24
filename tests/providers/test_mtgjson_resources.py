"""Tests for MTGJSON MCP provider resource templates."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastmcp import Client

from mtg_mcp_server.providers.mtgjson import mtgjson_mcp

FIXTURES = Path(__file__).parent.parent / "fixtures" / "mtgjson"


def _load_fixture_bytes() -> bytes:
    """Load the gzipped MTGJSON sample fixture as raw bytes."""
    return (FIXTURES / "atomic_cards_sample.json.gz").read_bytes()


def _mock_httpx_response(content: bytes, status_code: int = 200) -> httpx.Response:
    """Build a mock httpx response with the given content and status code."""
    return httpx.Response(status_code=status_code, content=content)


@pytest.fixture
async def client():
    """In-memory MCP client connected to the MTGJSON provider.

    Mocks the httpx download so no real network calls happen.
    """
    fixture_bytes = _load_fixture_bytes()
    mock_response = _mock_httpx_response(fixture_bytes)

    with patch("mtg_mcp_server.services.mtgjson.httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_response)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_http

        async with Client(transport=mtgjson_mcp) as c:
            yield c


class TestCardDataResource:
    """MTGJSON mtg://card-data/{name} resource behavior."""

    async def test_returns_card_json(self, client: Client):
        """Card data resource returns JSON with card name, mana cost, and type line."""
        result = await client.read_resource("mtg://card-data/Sol Ring")
        data = json.loads(result[0].text)
        assert data["name"] == "Sol Ring"
        assert "mana_cost" in data
        assert "type_line" in data

    async def test_card_not_found_returns_error_json(self, client: Client):
        """Card data resource returns error JSON for nonexistent cards."""
        result = await client.read_resource("mtg://card-data/Nonexistent Card")
        data = json.loads(result[0].text)
        assert "error" in data
        assert "Card not found" in data["error"]


class TestCardDataServerError:
    """MTGJSON card data resource server error handling."""

    async def test_mtgjson_error_returns_error_json(self):
        """Simulate a download failure triggering MTGJSONError."""
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(
            return_value=httpx.Response(status_code=500, content=b"Server Error")
        )
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("mtg_mcp_server.services.mtgjson.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = mock_http

            async with Client(transport=mtgjson_mcp) as c:
                result = await c.read_resource("mtg://card-data/Sol Ring")
                data = json.loads(result[0].text)
                assert "error" in data
                assert "MTGJSON error" in data["error"]


class TestResourceTemplateRegistration:
    """MTGJSON resource template registration."""

    async def test_resource_templates_registered(self, client: Client):
        """Card data resource template is registered on the provider."""
        templates = await client.list_resource_templates()
        template_uris = {t.uriTemplate for t in templates}
        assert "mtg://card-data/{name}" in template_uris
