"""Tests for the MTGJSON MCP provider."""

from __future__ import annotations

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


class TestToolRegistration:
    """MTGJSON provider tool registration."""

    async def test_all_tools_registered(self, client: Client):
        """Both MTGJSON tools are registered on the provider."""
        tools = await client.list_tools()
        tool_names = {t.name for t in tools}
        assert tool_names == {"card_lookup", "card_search"}


class TestCardLookup:
    """MTGJSON card_lookup tool behavior."""

    async def test_exact_lookup(self, client: Client):
        """card_lookup returns full card data for an exact name match."""
        result = await client.call_tool("card_lookup", {"name": "Sol Ring"})
        text = result.content[0].text
        assert "Sol Ring" in text
        assert "{1}" in text
        assert "Artifact" in text
        assert "{T}: Add {C}{C}." in text
        assert "Data provided by [MTGJSON]" in text

    async def test_legendary_creature(self, client: Client):
        """card_lookup returns power/toughness and supertypes for legendary creatures."""
        result = await client.call_tool("card_lookup", {"name": "Muldrotha, the Gravetide"})
        text = result.content[0].text
        assert "Muldrotha, the Gravetide" in text
        assert "6/6" in text
        assert "Legendary" in text

    async def test_case_insensitive(self, client: Client):
        """card_lookup matches card names case-insensitively."""
        result = await client.call_tool("card_lookup", {"name": "sol ring"})
        text = result.content[0].text
        assert "Sol Ring" in text

    async def test_not_found_returns_error(self, client: Client):
        """card_lookup returns an error response for nonexistent cards."""
        result = await client.call_tool(
            "card_lookup", {"name": "Nonexistent Card"}, raise_on_error=False
        )
        assert result.is_error
        text = result.content[0].text
        assert "not found" in text.lower()

    async def test_special_characters(self, client: Client):
        """card_lookup handles special Unicode characters in card names."""
        result = await client.call_tool("card_lookup", {"name": "Jötun Grunt"})
        text = result.content[0].text
        assert "Jötun Grunt" in text
        assert "4/4" in text


class TestCardSearch:
    """MTGJSON card_search tool behavior."""

    async def test_search_by_name(self, client: Client):
        """card_search finds cards by substring match on name."""
        result = await client.call_tool("card_search", {"query": "bolt"})
        text = result.content[0].text
        assert "Lightning Bolt" in text

    async def test_search_by_type(self, client: Client):
        """card_search finds cards by type line when search_field is 'type'."""
        result = await client.call_tool("card_search", {"query": "Instant", "search_field": "type"})
        text = result.content[0].text
        assert "Lightning Bolt" in text
        assert "Counterspell" in text

    async def test_search_by_text(self, client: Client):
        """card_search finds cards by oracle text when search_field is 'text'."""
        result = await client.call_tool(
            "card_search", {"query": "graveyard", "search_field": "text"}
        )
        text = result.content[0].text
        assert "Muldrotha" in text

    async def test_search_no_results(self, client: Client):
        """card_search returns an error response when no cards match the query."""
        result = await client.call_tool(
            "card_search", {"query": "xyzzynonexistent"}, raise_on_error=False
        )
        assert result.is_error
        text = result.content[0].text
        assert "no cards found" in text.lower()

    async def test_search_with_limit(self, client: Client):
        """card_search respects the limit parameter for result count."""
        result = await client.call_tool("card_search", {"query": "", "limit": 3})
        text = result.content[0].text
        assert "Found 3" in text

    async def test_invalid_search_field(self, client: Client):
        """card_search returns a validation error for unsupported search_field values."""
        result = await client.call_tool(
            "card_search",
            {"query": "test", "search_field": "invalid"},
            raise_on_error=False,
        )
        assert result.is_error
        text = result.content[0].text
        # Pydantic validates Literal type before our code runs
        assert "'name'" in text or "literal_error" in text
