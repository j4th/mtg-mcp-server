"""Shared integration test fixtures for the MTG MCP server.

Provides fixtures that spin up the full orchestrator with all HTTP backends
mocked via respx and fixture data. Tests exercise the complete MCP pipeline:
client -> orchestrator -> provider -> service -> mocked HTTP.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest
import respx

from mtg_mcp_server.services.scryfall_bulk import ScryfallBulkClient

FIXTURES = Path(__file__).parent.parent / "fixtures"
SCRYFALL_FIXTURES = FIXTURES / "scryfall"
SPELLBOOK_FIXTURES = FIXTURES / "spellbook"
SEVENTEEN_LANDS_FIXTURES = FIXTURES / "seventeen_lands"
EDHREC_FIXTURES = FIXTURES / "edhrec"
SCRYFALL_BULK_FIXTURES = FIXTURES / "scryfall_bulk"

SCRYFALL_BASE = "https://api.scryfall.com"
SPELLBOOK_BASE = "https://backend.commanderspellbook.com"
SEVENTEEN_LANDS_BASE = "https://www.17lands.com"
EDHREC_BASE = "https://json.edhrec.com"


def _load_json(path: Path) -> dict | list:
    """Load a JSON fixture file."""
    return json.loads(path.read_text())


def _load_bulk_metadata() -> dict:
    """Load the Scryfall bulk-data metadata fixture."""
    return json.loads((SCRYFALL_BULK_FIXTURES / "bulk_metadata.json").read_text())


def _bulk_download_url() -> str:
    """Derive the bulk download URL from the metadata fixture."""
    return _load_bulk_metadata()["download_uri"]


def _load_oracle_cards_bytes() -> bytes:
    """Load the oracle cards sample fixture as bytes."""
    return (SCRYFALL_BULK_FIXTURES / "oracle_cards_sample.json").read_bytes()


@pytest.fixture
async def bulk_client():
    """A ScryfallBulkClient loaded with fixture data via respx-mocked HTTP.

    Follows the same pattern as the ``loaded_client`` fixture in
    ``tests/services/test_scryfall_bulk.py``.
    """
    with respx.mock:
        respx.get(f"{SCRYFALL_BASE}/bulk-data/oracle_cards").mock(
            return_value=httpx.Response(200, json=_load_bulk_metadata())
        )
        respx.get(_bulk_download_url()).mock(
            return_value=httpx.Response(
                200, content=_load_oracle_cards_bytes(), headers={"ETag": '"integration-test"'}
            )
        )

        client = ScryfallBulkClient(base_url=SCRYFALL_BASE, refresh_hours=24)
        async with client:
            await client.ensure_loaded()
            yield client


@pytest.fixture
async def mcp_client():
    """Full orchestrator MCP client with ALL HTTP mocked via respx.

    Mocks every backend HTTP endpoint with fixture data so the entire
    orchestrator can be exercised through the MCP protocol without
    hitting any real APIs. Uses strict mode (default) so any unmocked
    request raises immediately.
    """
    from fastmcp import Client

    from mtg_mcp_server.server import mcp

    with respx.mock:
        # --- Scryfall API routes ---
        respx.get(f"{SCRYFALL_BASE}/cards/named").mock(
            return_value=httpx.Response(
                200, json=_load_json(SCRYFALL_FIXTURES / "card_sol_ring.json")
            )
        )
        respx.get(f"{SCRYFALL_BASE}/cards/search").mock(
            return_value=httpx.Response(
                200, json=_load_json(SCRYFALL_FIXTURES / "search_sultai_commander.json")
            )
        )
        # Rulings endpoint — regex with escaped base URL
        respx.get(url__regex=re.escape(SCRYFALL_BASE) + r"/cards/.+/rulings").mock(
            return_value=httpx.Response(
                200, json=_load_json(SCRYFALL_FIXTURES / "rulings_sol_ring.json")
            )
        )
        # Sets endpoint — regex for any set code
        respx.get(url__regex=re.escape(SCRYFALL_BASE) + r"/sets/\w+").mock(
            return_value=httpx.Response(
                200, json=_load_json(SCRYFALL_FIXTURES / "set_dominaria.json")
            )
        )

        # --- Spellbook routes ---
        respx.get(f"{SPELLBOOK_BASE}/variants/").mock(
            return_value=httpx.Response(
                200, json=_load_json(SPELLBOOK_FIXTURES / "combos_muldrotha.json")
            )
        )

        # --- 17Lands routes ---
        respx.get(f"{SEVENTEEN_LANDS_BASE}/card_ratings/data").mock(
            return_value=httpx.Response(
                200, json=_load_json(SEVENTEEN_LANDS_FIXTURES / "card_ratings_lci.json")
            )
        )

        # --- EDHREC routes ---
        respx.get(url__regex=re.escape(EDHREC_BASE) + r"/pages/commanders/.+\.json").mock(
            return_value=httpx.Response(
                200, json=_load_json(EDHREC_FIXTURES / "commander_muldrotha.json")
            )
        )
        respx.get(url__regex=re.escape(EDHREC_BASE) + r"/pages/cards/.+\.json").mock(
            return_value=httpx.Response(
                200, json=_load_json(EDHREC_FIXTURES / "commander_muldrotha.json")
            )
        )

        # --- Scryfall Bulk Data routes ---
        respx.get(f"{SCRYFALL_BASE}/bulk-data/oracle_cards").mock(
            return_value=httpx.Response(200, json=_load_bulk_metadata())
        )
        respx.get(_bulk_download_url()).mock(
            return_value=httpx.Response(
                200, content=_load_oracle_cards_bytes(), headers={"ETag": '"integration-test"'}
            )
        )

        async with Client(transport=mcp) as client:
            yield client
