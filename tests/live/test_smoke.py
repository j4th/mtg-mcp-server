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
        # 1 ping + 6 scryfall + 4 spellbook + 2 draft + 2 edhrec + 9 bulk + 22 workflows + 5 rules = 51
        assert len(tool_names) == 51, (
            f"Expected 51 tools, got {len(tool_names)}: {sorted(tool_names)}"
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


class TestDeckBuildingLive:
    """Hit real bulk data with deck building workflows."""

    async def test_theme_search(self, live_client):
        result = await live_client.call_tool(
            "theme_search", {"theme": "sacrifice", "format": "commander", "limit": 5}
        )
        text = result.content[0].text
        assert "sacrifice" in text.lower() or "Sacrifice" in text

    async def test_tribal_staples(self, live_client):
        result = await live_client.call_tool(
            "tribal_staples", {"tribe": "Elf", "format": "commander"}
        )
        text = result.content[0].text
        assert "Elf" in text

    async def test_color_identity_staples(self, live_client):
        result = await live_client.call_tool("color_identity_staples", {"color_identity": "simic"})
        text = result.content[0].text
        assert len(text) > 100  # Should have real card data

    async def test_rotation_check(self, live_client):
        result = await live_client.call_tool("rotation_check", {})
        text = result.content[0].text
        assert "Standard" in text


class TestCommanderDepthLive:
    """Hit real APIs with commander depth workflows."""

    async def test_commander_comparison(self, live_client):
        result = await live_client.call_tool(
            "commander_comparison",
            {"commanders": ["Muldrotha, the Gravetide", "Meren of Clan Nel Toth"]},
        )
        text = result.content[0].text
        assert "Muldrotha" in text
        assert "Meren" in text


class TestValidationLive:
    """Hit real bulk data with validation and utility workflows."""

    async def test_deck_validate_catches_illegal(self, live_client):
        result = await live_client.call_tool(
            "deck_validate",
            {
                "decklist": ["4 Lightning Bolt", "4 Sol Ring", "52 Island"],
                "format": "modern",
            },
        )
        text = result.content[0].text
        assert "INVALID" in text or "not legal" in text.lower()

    async def test_price_comparison(self, live_client):
        result = await live_client.call_tool(
            "price_comparison", {"cards": ["Sol Ring", "Lightning Bolt"]}
        )
        text = result.content[0].text
        assert "$" in text


class TestRulesEngineLive:
    """Hit the real rules engine (downloads Comprehensive Rules on first access)."""

    async def test_rules_lookup_by_number(self, live_client):
        result = await live_client.call_tool("rules_lookup", {"query": "704.5k"})
        text = result.content[0].text
        assert "704.5k" in text
        assert "world" in text.lower()

    async def test_keyword_explain(self, live_client):
        result = await live_client.call_tool("keyword_explain", {"keyword": "deathtouch"})
        text = result.content[0].text
        assert "deathtouch" in text.lower()
        assert "702" in text  # deathtouch rules section

    async def test_rules_interaction(self, live_client):
        result = await live_client.call_tool(
            "rules_interaction", {"mechanic_a": "deathtouch", "mechanic_b": "trample"}
        )
        text = result.content[0].text
        assert "deathtouch" in text.lower()
        assert "trample" in text.lower()

    async def test_rules_scenario(self, live_client):
        result = await live_client.call_tool(
            "rules_scenario",
            {"scenario": "A 1/1 with deathtouch blocks a 5/5 creature"},
        )
        text = result.content[0].text
        assert "deathtouch" in text.lower()

    async def test_combat_calculator(self, live_client):
        result = await live_client.call_tool(
            "combat_calculator",
            {"attackers": ["Typhoid Rats"], "blockers": ["Grizzly Bears"]},
        )
        text = result.content[0].text
        assert "combat" in text.lower() or "damage" in text.lower()


class TestDeckBuildingDepthLive:
    """Branch B deck building tools against real data."""

    async def test_build_around(self, live_client):
        result = await live_client.call_tool(
            "build_around",
            {"cards": ["Muldrotha, the Gravetide"], "format": "commander"},
        )
        text = result.content[0].text
        assert "Muldrotha" in text or len(text) > 100

    async def test_complete_deck(self, live_client):
        result = await live_client.call_tool(
            "complete_deck",
            {
                "decklist": ["Sol Ring", "Spore Frog", "Sakura-Tribe Elder"],
                "format": "commander",
                "commander": "Muldrotha, the Gravetide",
            },
        )
        text = result.content[0].text
        assert len(text) > 100  # Should have gap analysis

    async def test_precon_upgrade(self, live_client):
        result = await live_client.call_tool(
            "precon_upgrade",
            {
                "decklist": [
                    "Sol Ring",
                    "Spore Frog",
                    "Sakura-Tribe Elder",
                    "Mulldrifter",
                    "Coiling Oracle",
                    "Ravenous Chupacabra",
                ],
                "commander": "Muldrotha, the Gravetide",
                "budget": 5.0,
                "num_upgrades": 3,
            },
        )
        text = result.content[0].text
        assert len(text) > 50


class TestLimitedLive:
    """Branch B limited tools against real data."""

    async def test_sealed_pool_build(self, live_client):
        # Minimal pool — just enough to test the tool runs
        pool = [
            "Plains",
            "Island",
            "Swamp",
            "Mountain",
            "Forest",
            "Serra Angel",
            "Air Elemental",
            "Doom Blade",
            "Giant Growth",
            "Lightning Bolt",
            "Cancel",
            "Grizzly Bears",
            "Wind Drake",
            "Glory Seeker",
        ]
        result = await live_client.call_tool("sealed_pool_build", {"pool": pool, "set_code": "FDN"})
        text = result.content[0].text
        assert len(text) > 50

    async def test_draft_signal_read(self, live_client):
        result = await live_client.call_tool(
            "draft_signal_read",
            {
                "picks": ["Serra Angel", "Doom Blade", "Wind Drake"],
                "set_code": "FDN",
            },
        )
        text = result.content[0].text
        assert "signal" in text.lower() or "color" in text.lower() or len(text) > 50

    async def test_draft_log_review(self, live_client):
        result = await live_client.call_tool(
            "draft_log_review",
            {
                "picks": [
                    "Serra Angel",
                    "Doom Blade",
                    "Wind Drake",
                    "Lightning Bolt",
                    "Grizzly Bears",
                    "Cancel",
                ],
                "set_code": "FDN",
            },
        )
        text = result.content[0].text
        assert len(text) > 50


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
