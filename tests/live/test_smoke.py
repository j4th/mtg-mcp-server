"""Live smoke tests — starts a real server and hits real external APIs.

These tests are SLOW (30+ seconds for bulk data download) and require network
access. They are excluded from the default test run and must be invoked
explicitly via ``mise run test:live`` or ``pytest -m live``.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.live


class TestServerHealth:
    """Basic server health and tool registration checks."""

    async def test_ping(self, live_client):
        result = await live_client.call_tool("ping", {})
        assert result.content[0].text == "pong"

    async def test_all_tools_registered(self, live_client):
        tools = await live_client.list_tools()
        tool_names = {t.name for t in tools}
        # 1 ping + 6 scryfall + 4 spellbook + 2 draft + 2 edhrec + 9 bulk + 11 workflows = 35
        assert len(tool_names) == 35, (
            f"Expected 35 tools, got {len(tool_names)}: {sorted(tool_names)}"
        )

    async def test_no_mtgjson_tools(self, live_client):
        tools = await live_client.list_tools()
        mtgjson_tools = [t.name for t in tools if "mtgjson" in t.name]
        assert mtgjson_tools == [], f"Unexpected MTGJSON tools: {mtgjson_tools}"


class TestBulkDataLive:
    """Hit the real Scryfall bulk data. First call triggers a ~30MB download."""

    async def test_sol_ring_is_artifact(self, live_client):
        result = await live_client.call_tool("bulk_card_lookup", {"name": "Sol Ring"})
        assert "Artifact" in result.content[0].text

    async def test_sol_ring_has_prices(self, live_client):
        result = await live_client.call_tool("bulk_card_lookup", {"name": "Sol Ring"})
        assert "$" in result.content[0].text

    async def test_sol_ring_has_legalities(self, live_client):
        result = await live_client.call_tool("bulk_card_lookup", {"name": "Sol Ring"})
        assert "commander" in result.content[0].text.lower()

    async def test_sol_ring_has_edhrec_rank(self, live_client):
        result = await live_client.call_tool("bulk_card_lookup", {"name": "Sol Ring"})
        assert "EDHREC Rank" in result.content[0].text

    async def test_search_returns_results(self, live_client):
        result = await live_client.call_tool("bulk_card_search", {"query": "Lightning Bolt"})
        assert "Found" in result.content[0].text

    async def test_dfc_lookup(self, live_client):
        result = await live_client.call_tool("bulk_card_lookup", {"name": "Delver of Secrets"})
        text = result.content[0].text
        assert "Delver of Secrets" in text


class TestScryfallLive:
    """Hit the real Scryfall API."""

    async def test_card_details(self, live_client):
        result = await live_client.call_tool("scryfall_card_details", {"name": "Sol Ring"})
        assert "Artifact" in result.content[0].text

    async def test_search_cards(self, live_client):
        result = await live_client.call_tool(
            "scryfall_search_cards", {"query": "t:creature c:green cmc=1"}
        )
        assert "Found" in result.content[0].text

    async def test_set_info(self, live_client):
        result = await live_client.call_tool("scryfall_set_info", {"set_code": "dom"})
        text = result.content[0].text
        assert "Dominaria" in text


class TestCrossFormatLive:
    """New cross-format tools against real data."""

    async def test_ban_list_modern(self, live_client):
        result = await live_client.call_tool("bulk_ban_list", {"format": "modern"})
        text = result.content[0].text
        # Modern has banned cards
        assert "Banned" in text or "banned" in text

    async def test_format_staples_commander(self, live_client):
        result = await live_client.call_tool(
            "bulk_format_staples", {"format": "commander", "limit": 5}
        )
        text = result.content[0].text
        assert "Sol Ring" in text or "Commander" in text.lower()

    async def test_card_in_formats(self, live_client):
        result = await live_client.call_tool(
            "bulk_card_in_formats", {"card_name": "Lightning Bolt"}
        )
        text = result.content[0].text
        assert "Lightning Bolt" in text
        assert "modern" in text.lower()
