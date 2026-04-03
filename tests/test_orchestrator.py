"""Integration tests for the MTG orchestrator with mounted backends."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

if TYPE_CHECKING:
    from fastmcp import Client

SCRYFALL_FIXTURES = Path(__file__).parent / "fixtures" / "scryfall"
SPELLBOOK_FIXTURES = Path(__file__).parent / "fixtures" / "spellbook"
SEVENTEEN_LANDS_FIXTURES = Path(__file__).parent / "fixtures" / "seventeen_lands"
EDHREC_FIXTURES = Path(__file__).parent / "fixtures" / "edhrec"
MOXFIELD_FIXTURES = Path(__file__).parent / "fixtures" / "moxfield"
SCRYFALL_BULK_FIXTURES = Path(__file__).parent / "fixtures" / "scryfall_bulk"
SPICERACK_FIXTURES = Path(__file__).parent / "fixtures" / "spicerack"
SCRYFALL_BASE = "https://api.scryfall.com"
SPELLBOOK_BASE = "https://backend.commanderspellbook.com"
SEVENTEEN_LANDS_BASE = "https://www.17lands.com"
EDHREC_BASE = "https://json.edhrec.com"
MOXFIELD_BASE = "https://api2.moxfield.com"


def _load_scryfall_fixture(name: str) -> dict:
    """Load a Scryfall JSON fixture by filename."""
    return json.loads((SCRYFALL_FIXTURES / name).read_text())


def _load_spellbook_fixture(name: str) -> dict:
    """Load a Spellbook JSON fixture by filename."""
    return json.loads((SPELLBOOK_FIXTURES / name).read_text())


def _load_seventeen_lands_fixture(name: str) -> list[dict]:
    """Load a 17Lands JSON fixture by filename."""
    return json.loads((SEVENTEEN_LANDS_FIXTURES / name).read_text())


def _load_edhrec_fixture(name: str) -> dict:
    """Load an EDHREC JSON fixture by filename."""
    return json.loads((EDHREC_FIXTURES / name).read_text())


def _load_moxfield_fixture(name: str) -> dict:
    """Load a Moxfield JSON fixture by filename."""
    return json.loads((MOXFIELD_FIXTURES / name).read_text())


class TestScryfallMounted:
    """Verify Scryfall tools appear with scryfall_ namespace on the orchestrator."""

    async def test_namespaced_tools_appear(self, mcp_client: Client):
        """All four Scryfall tools are listed with the scryfall_ namespace prefix."""
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        assert "scryfall_search_cards" in tool_names
        assert "scryfall_card_details" in tool_names
        assert "scryfall_card_price" in tool_names
        assert "scryfall_card_rulings" in tool_names

    @respx.mock
    async def test_end_to_end_card_details(self, mcp_client: Client):
        """Calling scryfall_card_details through the orchestrator returns card data."""
        fixture = _load_scryfall_fixture("card_muldrotha.json")
        respx.get(
            f"{SCRYFALL_BASE}/cards/named",
            params={"exact": "Muldrotha, the Gravetide"},
        ).mock(return_value=httpx.Response(200, json=fixture))

        result = await mcp_client.call_tool(
            "scryfall_card_details", {"name": "Muldrotha, the Gravetide"}
        )
        text = result.content[0].text
        assert "Muldrotha, the Gravetide" in text
        assert "{3}{B}{G}{U}" in text

    async def test_ping_still_available(self, mcp_client: Client):
        """Ping health-check tool remains available alongside mounted backends."""
        result = await mcp_client.call_tool("ping", {})
        assert result.data == "pong"


class TestSpellbookMounted:
    """Verify Spellbook tools appear with spellbook_ namespace on the orchestrator."""

    async def test_namespaced_tools_appear(self, mcp_client: Client):
        """All four Spellbook tools are listed with the spellbook_ namespace prefix."""
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        assert "spellbook_find_combos" in tool_names
        assert "spellbook_combo_details" in tool_names
        assert "spellbook_find_decklist_combos" in tool_names
        assert "spellbook_estimate_bracket" in tool_names

    @respx.mock
    async def test_end_to_end_find_combos(self, mcp_client: Client):
        """Calling spellbook_find_combos through the orchestrator returns combo data."""
        fixture = _load_spellbook_fixture("combos_muldrotha.json")
        respx.get(
            f"{SPELLBOOK_BASE}/variants/",
            params={"q": 'card:"Muldrotha, the Gravetide"', "limit": "10"},
        ).mock(return_value=httpx.Response(200, json=fixture))

        result = await mcp_client.call_tool(
            "spellbook_find_combos", {"card_name": "Muldrotha, the Gravetide"}
        )
        text = result.content[0].text
        assert "combo" in text.lower()
        assert "Muldrotha" in text


class TestSeventeenLandsMounted:
    """Verify 17Lands tools appear with draft_ namespace on the orchestrator."""

    async def test_namespaced_tools_appear(self, mcp_client: Client):
        """Both 17Lands tools are listed with the draft_ namespace prefix."""
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        assert "draft_card_ratings" in tool_names
        assert "draft_archetype_stats" in tool_names

    @respx.mock
    async def test_end_to_end_card_ratings(self, mcp_client: Client):
        """Calling draft_card_ratings through the orchestrator returns rating data."""
        fixture = _load_seventeen_lands_fixture("card_ratings_lci.json")
        respx.get(
            f"{SEVENTEEN_LANDS_BASE}/card_ratings/data",
            params={"expansion": "LCI", "event_type": "PremierDraft"},
        ).mock(return_value=httpx.Response(200, json=fixture))

        result = await mcp_client.call_tool("draft_card_ratings", {"set_code": "LCI"})
        text = result.content[0].text
        assert len(text) > 0


class TestWorkflowsMounted:
    """Verify workflow tools appear without namespace on the orchestrator."""

    async def test_workflow_tools_appear(self, mcp_client: Client):
        """Workflow tools appear without any namespace prefix."""
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        assert "commander_overview" in tool_names
        assert "evaluate_upgrade" in tool_names
        assert "draft_pack_pick" in tool_names
        assert "suggest_cuts" in tool_names


class TestEdhrecMounted:
    """Verify EDHREC tools appear with edhrec_ namespace on the orchestrator."""

    async def test_namespaced_tools_appear(self, mcp_client: Client):
        """Both EDHREC tools are listed with the edhrec_ namespace prefix."""
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        assert "edhrec_commander_staples" in tool_names
        assert "edhrec_card_synergy" in tool_names

    @respx.mock
    async def test_end_to_end_commander_staples(self, mcp_client: Client):
        """Calling edhrec_commander_staples through the orchestrator returns staple data."""
        fixture = _load_edhrec_fixture("commander_muldrotha.json")
        respx.get(f"{EDHREC_BASE}/pages/commanders/muldrotha-the-gravetide.json").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result = await mcp_client.call_tool(
            "edhrec_commander_staples",
            {"commander_name": "Muldrotha, the Gravetide"},
        )
        text = result.content[0].text
        assert "Muldrotha, the Gravetide" in text


class TestMoxfieldMounted:
    """Verify Moxfield tools appear with moxfield_ namespace on the orchestrator."""

    async def test_namespaced_tools_appear(self, mcp_client: Client):
        """Both Moxfield tools are listed with the moxfield_ namespace prefix."""
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        assert "moxfield_decklist" in tool_names
        assert "moxfield_deck_info" in tool_names

    @respx.mock
    async def test_end_to_end_decklist(self, mcp_client: Client):
        """Calling moxfield_decklist through the orchestrator returns deck data."""
        fixture = _load_moxfield_fixture("deck_commander.json")
        respx.get(f"{MOXFIELD_BASE}/v3/decks/all/abc123").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        result = await mcp_client.call_tool("moxfield_decklist", {"deck_id": "abc123"})
        text = result.content[0].text
        assert "Muldrotha Self-Mill" in text
        assert "Sol Ring" in text


class TestSpicerackMounted:
    """Verify Spicerack tools appear with spicerack_ namespace on the orchestrator."""

    async def test_namespaced_tools_appear(self, mcp_client: Client):
        """All three Spicerack tools are listed with the spicerack_ namespace prefix."""
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        assert "spicerack_recent_tournaments" in tool_names
        assert "spicerack_tournament_results" in tool_names
        assert "spicerack_format_decklists" in tool_names


class TestScryfallBulkMounted:
    """Verify Scryfall bulk data tools appear with bulk_ namespace on the orchestrator."""

    async def test_namespaced_tools_appear(self, mcp_client: Client):
        """Both bulk data tools are listed with the bulk_ namespace prefix."""
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        assert "bulk_card_lookup" in tool_names
        assert "bulk_card_search" in tool_names

    async def test_end_to_end_card_lookup(self, mcp_client: Client):
        """Calling bulk_card_lookup through the orchestrator returns card data."""
        metadata = json.loads((SCRYFALL_BULK_FIXTURES / "bulk_metadata.json").read_text())
        oracle_cards = json.loads((SCRYFALL_BULK_FIXTURES / "oracle_cards_sample.json").read_text())
        mock_metadata_resp = httpx.Response(
            200,
            json=metadata,
            headers={"etag": '"test-etag"'},
        )
        mock_cards_resp = httpx.Response(200, json=oracle_cards)

        with patch("mtg_mcp_server.services.scryfall_bulk.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(side_effect=[mock_metadata_resp, mock_cards_resp])
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_http

            result = await mcp_client.call_tool("bulk_card_lookup", {"name": "Sol Ring"})
            text = result.content[0].text
            assert "Sol Ring" in text
            assert "Artifact" in text

    async def test_end_to_end_card_search(self, mcp_client: Client):
        """Calling bulk_card_search through the orchestrator returns search results."""
        metadata = json.loads((SCRYFALL_BULK_FIXTURES / "bulk_metadata.json").read_text())
        oracle_cards = json.loads((SCRYFALL_BULK_FIXTURES / "oracle_cards_sample.json").read_text())
        mock_metadata_resp = httpx.Response(
            200,
            json=metadata,
            headers={"etag": '"test-etag"'},
        )
        mock_cards_resp = httpx.Response(200, json=oracle_cards)

        with patch("mtg_mcp_server.services.scryfall_bulk.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(side_effect=[mock_metadata_resp, mock_cards_resp])
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_http

            result = await mcp_client.call_tool("bulk_card_search", {"query": "bolt"})
            text = result.content[0].text
            assert "Lightning Bolt" in text


# ---------------------------------------------------------------------------
# Server metadata tests
# ---------------------------------------------------------------------------


class TestServerMetadata:
    """Verify server-level metadata used by quality scorers (Smithery, etc.)."""

    def test_server_instructions_set(self):
        """Server instructions are non-empty and reference all tool categories."""
        from mtg_mcp_server.server import mcp as server

        assert server.instructions, "Server instructions must be set"
        assert "scryfall_*" in server.instructions
        assert "spellbook_*" in server.instructions
        assert "draft_*" in server.instructions
        assert "edhrec_*" in server.instructions
        assert "moxfield_*" in server.instructions
        assert "bulk_*" in server.instructions
        assert "spicerack_*" in server.instructions
        assert "Workflow" in server.instructions

    def test_server_name(self):
        """Server name is 'MTG'."""
        from mtg_mcp_server.server import mcp as server

        assert server.name == "MTG"

    def test_server_version_from_package(self):
        """Server version matches package version, not FastMCP version."""
        from mtg_mcp_server import __version__
        from mtg_mcp_server.server import mcp as server

        assert server.version == __version__

    def test_server_website_url(self):
        """Server has a website URL configured."""
        from mtg_mcp_server.server import mcp as server

        # _mcp_server is a FastMCP internal — no public API for website_url/icons
        url = server._mcp_server.website_url
        assert url is not None, "website_url must be set"
        assert url.startswith("https://"), f"website_url must start with https://, got: {url}"

    def test_server_icons_configured(self):
        """Server has at least one icon with src and mimeType."""
        from mtg_mcp_server.server import mcp as server

        icons = server._mcp_server.icons
        assert icons, "Server must have at least one icon"
        icon = icons[0]
        assert icon.src, "Icon must have a src attribute"
        assert icon.mimeType, "Icon must have a mimeType attribute"


# ---------------------------------------------------------------------------
# Tool schema completeness tests
# ---------------------------------------------------------------------------


class TestToolSchemaCompleteness:
    """Verify every tool has complete schema metadata — descriptions, annotations, etc."""

    async def test_all_tools_have_descriptions(self, mcp_client: Client):
        """Every tool must have a non-empty description."""
        tools = await mcp_client.list_tools()
        missing = [t.name for t in tools if not t.description]
        assert not missing, f"Tools missing descriptions: {missing}"

    async def test_all_parameters_have_descriptions(self, mcp_client: Client):
        """Every tool parameter must have a description in its JSON schema."""
        tools = await mcp_client.list_tools()
        missing = []
        for tool in tools:
            schema = tool.inputSchema
            properties = schema.get("properties", {})
            for param_name, param_schema in properties.items():
                if "description" not in param_schema:
                    missing.append(f"{tool.name}.{param_name}")
        if missing:
            pytest.fail(
                f"Parameters missing descriptions ({len(missing)}):\n"
                + "\n".join(f"  - {m}" for m in missing)
            )

    async def test_all_tools_have_annotations(self, mcp_client: Client):
        """Every tool must have annotations with readOnlyHint and idempotentHint."""
        tools = await mcp_client.list_tools()
        missing = []
        for tool in tools:
            if tool.annotations is None:
                missing.append(f"{tool.name} (no annotations)")
            else:
                if not tool.annotations.readOnlyHint:
                    missing.append(f"{tool.name} (readOnlyHint not True)")
                if not tool.annotations.idempotentHint:
                    missing.append(f"{tool.name} (idempotentHint not True)")
        assert not missing, f"Tools with missing/wrong annotations: {missing}"

    async def test_expected_tool_count(self, mcp_client: Client):
        """Server exposes the expected number of tools."""
        tools = await mcp_client.list_tools()
        tool_names = sorted(t.name for t in tools)
        assert len(tools) == 60, f"Expected 60 tools, got {len(tools)}.\nTools: {tool_names}"

    async def test_no_context_parameter_exposed(self, mcp_client: Client):
        """No tool should expose 'ctx' (Context) as a user-visible parameter."""
        tools = await mcp_client.list_tools()
        exposed = []
        for tool in tools:
            properties = tool.inputSchema.get("properties", {})
            if "ctx" in properties:
                exposed.append(tool.name)
        assert not exposed, f"Tools exposing 'ctx' parameter: {exposed}"


# ---------------------------------------------------------------------------
# Middleware configuration tests
# ---------------------------------------------------------------------------


class TestMiddlewareConfig:
    """Verify response-limiting middleware targets real tool names."""

    async def test_per_tool_middleware_targets_exist(self, mcp_client: Client):
        """Per-tool middleware tool names must match registered tools."""
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        heavy_tools = {"scryfall_search_cards", "draft_card_ratings", "edhrec_commander_staples"}
        missing = heavy_tools - tool_names
        assert not missing, f"Middleware targets not registered as tools: {missing}"


# ---------------------------------------------------------------------------
# Resource propagation tests
# ---------------------------------------------------------------------------


class TestResourcePropagation:
    """Verify resource templates from mounted backends are visible on the orchestrator."""

    async def test_all_resource_templates_listed(self, mcp_client: Client):
        """All resource templates from backend providers are accessible."""
        templates = await mcp_client.list_resource_templates()
        uri_set = {t.uriTemplate for t in templates}

        # When mounted with a namespace, FastMCP may transform URIs.
        # Check that each backend's resource is represented.
        expected_fragments = [
            "card/{name}",  # Scryfall card
            "rulings",  # Scryfall rulings
            "set/{code}",  # Scryfall set
            "combo/{combo_id}",  # Spellbook combo
            "ratings",  # 17Lands ratings
            "staples",  # EDHREC staples
            "card-data/{name}",  # Scryfall bulk card-data
            "format/{format}",  # Bulk format resources
            "similar",  # Bulk similar cards
            "rules/{number}",  # Rules by number
            "glossary/{term}",  # Rules glossary
            "theme/{theme}",  # Theme search
            "tribe/{tribe}",  # Tribal staples
            "signals",  # Draft signals
            "moxfield/",  # Moxfield deck
            "tournament/",  # Spicerack tournaments
            # rules/keywords and rules/sections are static (no URI params)
            # so they appear in list_resources(), not list_resource_templates()
        ]
        for fragment in expected_fragments:
            found = any(fragment in uri for uri in uri_set)
            assert found, (
                f"No resource template contains '{fragment}'.\nAvailable templates: {uri_set}"
            )

    async def test_resource_template_count(self, mcp_client: Client):
        """At least 18 resource templates are registered (20 total minus 2 static)."""
        templates = await mcp_client.list_resource_templates()
        assert len(templates) >= 18, (
            f"Expected >= 18 resource templates, got {len(templates)}.\n"
            f"Templates: {[t.uriTemplate for t in templates]}"
        )


# ---------------------------------------------------------------------------
# Prompt completeness tests
# ---------------------------------------------------------------------------


class TestPromptCompleteness:
    """Verify all prompts are registered and have complete argument metadata."""

    async def test_all_prompts_listed(self, mcp_client: Client):
        """All workflow prompts are registered."""
        prompts = await mcp_client.list_prompts()
        prompt_names = {p.name for p in prompts}
        expected = {
            "evaluate_commander_swap",
            "deck_health_check",
            "draft_strategy",
            "find_upgrades",
            "build_deck",
            "evaluate_collection",
            "format_intro",
            "card_alternatives",
            "rules_question",
            "build_around_deck",
            "build_tribal_deck",
            "build_theme_deck",
            "upgrade_precon",
            "sealed_session",
            "draft_review",
            "compare_commanders",
            "rotation_plan",
        }
        assert expected.issubset(prompt_names), (
            f"Missing prompts: {expected - prompt_names}.\nAvailable: {prompt_names}"
        )

    async def test_prompt_arguments_have_descriptions(self, mcp_client: Client):
        """Every prompt argument must have a non-empty description."""
        prompts = await mcp_client.list_prompts()
        missing = []
        for prompt in prompts:
            if prompt.arguments:
                for arg in prompt.arguments:
                    if not arg.description:
                        missing.append(f"{prompt.name}.{arg.name}")
        assert not missing, f"Prompt arguments missing descriptions: {missing}"


# ---------------------------------------------------------------------------
# Tool naming convention tests
# ---------------------------------------------------------------------------


class TestToolNamingConventions:
    """Verify tool naming follows the namespace conventions."""

    async def test_backend_tools_namespaced(self, mcp_client: Client):
        """Tools from mounted backends use their namespace prefix."""
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}

        # Expected namespace prefixes and at least one tool per backend
        backend_prefixes = {
            "scryfall_": ["scryfall_search_cards", "scryfall_card_details"],
            "spellbook_": ["spellbook_find_combos", "spellbook_combo_details"],
            "draft_": ["draft_card_ratings", "draft_archetype_stats"],
            "edhrec_": ["edhrec_commander_staples", "edhrec_card_synergy"],
            "moxfield_": ["moxfield_decklist", "moxfield_deck_info"],
            "bulk_": ["bulk_card_lookup", "bulk_card_search"],
            "spicerack_": ["spicerack_recent_tournaments", "spicerack_tournament_results"],
        }
        for prefix, expected_tools in backend_prefixes.items():
            for tool_name in expected_tools:
                assert tool_name in tool_names, (
                    f"Expected namespaced tool '{tool_name}' (prefix '{prefix}') not found"
                )

    async def test_workflow_tools_not_namespaced(self, mcp_client: Client):
        """Workflow tools are mounted without a namespace prefix."""
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        workflow_tools = [
            "commander_overview",
            "evaluate_upgrade",
            "card_comparison",
            "budget_upgrade",
            "deck_analysis",
            "set_overview",
            "draft_pack_pick",
            "suggest_cuts",
        ]
        for tool_name in workflow_tools:
            assert tool_name in tool_names, f"Workflow tool '{tool_name}' not found"

    async def test_ping_is_standalone(self, mcp_client: Client):
        """Ping tool is registered directly on the orchestrator (no prefix)."""
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        assert "ping" in tool_names
