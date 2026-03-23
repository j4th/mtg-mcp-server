"""Tests for MTGJSON MCP provider resource templates."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastmcp import Client

from mtg_mcp.providers.mtgjson import mtgjson_mcp

FIXTURES = Path(__file__).parent.parent / "fixtures" / "mtgjson"


def _load_fixture_bytes() -> bytes:
    return (FIXTURES / "atomic_cards_sample.json.gz").read_bytes()


def _mock_httpx_response(content: bytes, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code=status_code, content=content)


@pytest.fixture
async def client():
    """In-memory MCP client connected to the MTGJSON provider.

    Mocks the httpx download so no real network calls happen.
    """
    fixture_bytes = _load_fixture_bytes()
    mock_response = _mock_httpx_response(fixture_bytes)

    with patch("mtg_mcp.services.mtgjson.httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_response)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_http

        async with Client(transport=mtgjson_mcp) as c:
            yield c


class TestCardDataResource:
    async def test_returns_card_json(self, client: Client):
        result = await client.read_resource("mtg://card-data/Sol Ring")
        data = json.loads(result[0].text)
        assert data["name"] == "Sol Ring"
        assert "mana_cost" in data
        assert "type_line" in data

    async def test_card_not_found_returns_error_json(self, client: Client):
        result = await client.read_resource("mtg://card-data/Nonexistent Card")
        data = json.loads(result[0].text)
        assert "error" in data
        assert "Card not found" in data["error"]


class TestResourceTemplateRegistration:
    async def test_resource_templates_registered(self, client: Client):
        templates = await client.list_resource_templates()
        template_uris = {t.uriTemplate for t in templates}
        assert "mtg://card-data/{name}" in template_uris
