"""Shared test fixtures for MTG MCP server tests."""

from __future__ import annotations

import pytest
from fastmcp import Client

from mtg_mcp_server.server import mcp
from mtg_mcp_server.services.edhrec import EDHRECClient
from mtg_mcp_server.services.scryfall import ScryfallClient
from mtg_mcp_server.services.seventeen_lands import SeventeenLandsClient
from mtg_mcp_server.services.spellbook import SpellbookClient


@pytest.fixture(autouse=True)
def _clear_caches():
    """Clear all service-level TTL caches before every test.

    Without this, cached results from one test leak into the next,
    causing spurious passes/failures (e.g., an error-path test gets
    a cached success from the happy-path test that ran first).
    """
    ScryfallClient._card_name_cache.clear()
    ScryfallClient._card_id_cache.clear()
    ScryfallClient._search_cache.clear()
    ScryfallClient._rulings_cache.clear()
    ScryfallClient._sets_cache.clear()
    SpellbookClient._combos_cache.clear()
    SpellbookClient._combo_cache.clear()
    SpellbookClient._decklist_combos_cache.clear()
    SpellbookClient._bracket_cache.clear()
    SeventeenLandsClient._card_ratings_cache.clear()
    SeventeenLandsClient._color_ratings_cache.clear()
    EDHRECClient._commander_cache.clear()
    EDHRECClient._synergy_cache.clear()


@pytest.fixture
async def mcp_client():
    """In-memory MCP client connected to the orchestrator."""
    async with Client(transport=mcp) as client:
        yield client
