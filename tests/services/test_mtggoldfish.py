"""Tests for the MTGGoldfish metagame service client."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from cachetools import TTLCache

from mtg_mcp_server.services.mtggoldfish import (
    ArchetypeNotFoundError,
    FormatNotFoundError,
    MTGGoldfishClient,
    MTGGoldfishError,
)
from mtg_mcp_server.types import (
    GoldfishArchetype,
    GoldfishArchetypeDetail,
    GoldfishFormatStaple,
    GoldfishMetaSnapshot,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "mtggoldfish"
BASE_URL = "https://www.mtggoldfish.com"


@pytest.fixture(autouse=True)
def _clear_goldfish_cache():
    """Clear MTGGoldfishClient caches before every test to prevent leakage."""
    MTGGoldfishClient._metagame_cache.clear()
    MTGGoldfishClient._archetype_cache.clear()
    MTGGoldfishClient._staples_cache.clear()
    MTGGoldfishClient._price_cache.clear()


def _load_fixture(name: str) -> str:
    """Load an MTGGoldfish HTML/text fixture by filename."""
    return (FIXTURES / name).read_text()


class TestSlugify:
    """Test the shared slugify function used by MTGGoldfish for archetype URLs."""

    def test_basic_name(self):
        """Simple two-word name converts to lowercase hyphenated slug."""
        from mtg_mcp_server.utils.formatters import slugify

        assert slugify("Boros Energy") == "boros-energy"

    def test_comma_removed(self):
        """Commas are stripped from the slug."""
        from mtg_mcp_server.utils.formatters import slugify

        assert slugify("Azorius Control, Revised") == "azorius-control-revised"

    def test_apostrophe_removed(self):
        """Apostrophes are stripped from the slug."""
        from mtg_mcp_server.utils.formatters import slugify

        assert slugify("Izzet Delver's Choice") == "izzet-delvers-choice"

    def test_multiple_spaces_collapsed(self):
        """Consecutive spaces are collapsed into a single hyphen."""
        from mtg_mcp_server.utils.formatters import slugify

        assert slugify("The  Big   Deck") == "the-big-deck"

    def test_period_removed(self):
        """Periods are stripped from the slug."""
        from mtg_mcp_server.utils.formatters import slugify

        assert slugify("U.W. Control") == "uw-control"

    def test_already_slug(self):
        """Already-slugified name passes through unchanged."""
        from mtg_mcp_server.utils.formatters import slugify

        assert slugify("boros-energy") == "boros-energy"

    def test_leading_trailing_hyphens_stripped(self):
        """Leading/trailing hyphens from special chars are removed."""
        from mtg_mcp_server.utils.formatters import slugify

        assert slugify("'Hello World'") == "hello-world"


class TestAcceptHeader:
    """Verify MTGGoldfishClient sets Accept: text/html (not application/json)."""

    async def test_accept_header_is_html(self):
        """Client must send Accept: text/html to avoid HTTP 406 from MTGGoldfish."""
        client = MTGGoldfishClient(base_url=BASE_URL)
        async with client:
            accept = client._client.headers["accept"]
            assert "text/html" in accept
            assert "application/json" not in accept


class TestFormatNormalization:
    """Verify format names are lowercased before building URLs."""

    @respx.mock
    async def test_title_case_format_lowered(self):
        """Title-case 'Modern' is normalized to 'modern' in the URL."""
        html = _load_fixture("metagame_modern.html")
        respx.get(f"{BASE_URL}/metagame/modern/full").mock(
            return_value=httpx.Response(
                200, content=html.encode(), headers={"Content-Type": "text/html"}
            )
        )
        async with MTGGoldfishClient(base_url=BASE_URL) as client:
            result = await client.get_metagame("Modern")

        assert result.format == "modern"
        assert len(result.archetypes) == 3


class TestGetMetagame:
    """Tests for metagame page parsing."""

    @respx.mock
    async def test_parses_three_archetypes(self):
        """Fixture with 3 archetype tiles returns 3 GoldfishArchetype objects."""
        html = _load_fixture("metagame_modern.html")
        respx.get(f"{BASE_URL}/metagame/modern/full").mock(
            return_value=httpx.Response(
                200, content=html.encode(), headers={"Content-Type": "text/html"}
            )
        )
        async with MTGGoldfishClient(base_url=BASE_URL) as client:
            result = await client.get_metagame("modern")

        assert isinstance(result, GoldfishMetaSnapshot)
        assert result.format == "modern"
        assert len(result.archetypes) == 3

    @respx.mock
    async def test_archetype_fields_mapped(self):
        """First archetype tile fields are correctly parsed."""
        html = _load_fixture("metagame_modern.html")
        respx.get(f"{BASE_URL}/metagame/modern/full").mock(
            return_value=httpx.Response(
                200, content=html.encode(), headers={"Content-Type": "text/html"}
            )
        )
        async with MTGGoldfishClient(base_url=BASE_URL) as client:
            result = await client.get_metagame("modern")

        arch = result.archetypes[0]
        assert isinstance(arch, GoldfishArchetype)
        assert arch.name == "Boros Energy"
        assert arch.slug == "modern-boros-energy"
        assert arch.meta_share == pytest.approx(20.3)
        assert arch.deck_count == 572
        assert arch.price_paper == 860
        assert arch.colors == ["W", "R"]
        assert "Phlage, Titan of Fire's Fury" in arch.key_cards
        assert "Ragavan, Nimble Pilferer" in arch.key_cards
        assert "Ocelot Pride" in arch.key_cards

    @respx.mock
    async def test_second_archetype_parsed(self):
        """Second archetype (Jeskai Blink) is correctly parsed."""
        html = _load_fixture("metagame_modern.html")
        respx.get(f"{BASE_URL}/metagame/modern/full").mock(
            return_value=httpx.Response(
                200, content=html.encode(), headers={"Content-Type": "text/html"}
            )
        )
        async with MTGGoldfishClient(base_url=BASE_URL) as client:
            result = await client.get_metagame("modern")

        arch = result.archetypes[1]
        assert arch.name == "Jeskai Blink"
        assert arch.slug == "modern-jeskai-blink"
        assert arch.meta_share == pytest.approx(11.0)
        assert arch.deck_count == 308
        assert arch.price_paper == 1014
        assert arch.colors == ["W", "U", "R"]

    @respx.mock
    async def test_third_archetype_parsed(self):
        """Third archetype (Affinity) is correctly parsed."""
        html = _load_fixture("metagame_modern.html")
        respx.get(f"{BASE_URL}/metagame/modern/full").mock(
            return_value=httpx.Response(
                200, content=html.encode(), headers={"Content-Type": "text/html"}
            )
        )
        async with MTGGoldfishClient(base_url=BASE_URL) as client:
            result = await client.get_metagame("modern")

        arch = result.archetypes[2]
        assert arch.name == "Affinity"
        assert arch.slug == "modern-affinity"
        assert arch.meta_share == pytest.approx(6.7)
        assert arch.deck_count == 189
        assert arch.price_paper == 1065
        assert arch.colors == ["U", "R"]

    @respx.mock
    async def test_total_decks_is_sum(self):
        """total_decks is sum of all archetype deck_counts."""
        html = _load_fixture("metagame_modern.html")
        respx.get(f"{BASE_URL}/metagame/modern/full").mock(
            return_value=httpx.Response(
                200, content=html.encode(), headers={"Content-Type": "text/html"}
            )
        )
        async with MTGGoldfishClient(base_url=BASE_URL) as client:
            result = await client.get_metagame("modern")

        assert result.total_decks == 572 + 308 + 189

    @respx.mock
    async def test_404_raises_format_not_found(self):
        """404 response raises FormatNotFoundError."""
        html = _load_fixture("error_not_found.html")
        respx.get(f"{BASE_URL}/metagame/invalid_format/full").mock(
            return_value=httpx.Response(404, content=html.encode())
        )
        async with MTGGoldfishClient(base_url=BASE_URL) as client:
            with pytest.raises(FormatNotFoundError, match="invalid_format"):
                await client.get_metagame("invalid_format")

    @respx.mock
    async def test_empty_page_returns_empty_archetypes(self):
        """Page with no archetype tiles returns empty snapshot."""
        html = "<html><body><div class='archetype-tile-container'></div></body></html>"
        respx.get(f"{BASE_URL}/metagame/modern/full").mock(
            return_value=httpx.Response(
                200, content=html.encode(), headers={"Content-Type": "text/html"}
            )
        )
        async with MTGGoldfishClient(base_url=BASE_URL) as client:
            result = await client.get_metagame("modern")

        assert result.archetypes == []
        assert result.total_decks == 0


class TestGetArchetype:
    """Tests for archetype detail page parsing."""

    @respx.mock
    async def test_parses_archetype_detail(self):
        """Archetype page + deck download returns GoldfishArchetypeDetail."""
        arch_html = _load_fixture("archetype_boros_energy.html")
        deck_txt = _load_fixture("deck_download.txt")
        respx.get(f"{BASE_URL}/archetype/modern-boros-energy").mock(
            return_value=httpx.Response(
                200, content=arch_html.encode(), headers={"Content-Type": "text/html"}
            )
        )
        respx.get(f"{BASE_URL}/deck/download/7708470").mock(
            return_value=httpx.Response(
                200, content=deck_txt.encode(), headers={"Content-Type": "text/plain"}
            )
        )
        async with MTGGoldfishClient(base_url=BASE_URL) as client:
            result = await client.get_archetype("modern", "Boros Energy")

        assert isinstance(result, GoldfishArchetypeDetail)
        assert result.name == "Boros Energy"
        assert result.author == "Linden Koot"
        assert result.deck_id == "7708470"

    @respx.mock
    async def test_event_and_result_parsed(self):
        """Event name and result are extracted from deck info."""
        arch_html = _load_fixture("archetype_boros_energy.html")
        deck_txt = _load_fixture("deck_download.txt")
        respx.get(f"{BASE_URL}/archetype/modern-boros-energy").mock(
            return_value=httpx.Response(
                200, content=arch_html.encode(), headers={"Content-Type": "text/html"}
            )
        )
        respx.get(f"{BASE_URL}/deck/download/7708470").mock(
            return_value=httpx.Response(
                200, content=deck_txt.encode(), headers={"Content-Type": "text/plain"}
            )
        )
        async with MTGGoldfishClient(base_url=BASE_URL) as client:
            result = await client.get_archetype("modern", "Boros Energy")

        assert "LDXP SEA26" in result.event
        assert result.result == "1st Place, 8-1-1"

    @respx.mock
    async def test_date_extracted(self):
        """Deck date is extracted from the page."""
        arch_html = _load_fixture("archetype_boros_energy.html")
        deck_txt = _load_fixture("deck_download.txt")
        respx.get(f"{BASE_URL}/archetype/modern-boros-energy").mock(
            return_value=httpx.Response(
                200, content=arch_html.encode(), headers={"Content-Type": "text/html"}
            )
        )
        respx.get(f"{BASE_URL}/deck/download/7708470").mock(
            return_value=httpx.Response(
                200, content=deck_txt.encode(), headers={"Content-Type": "text/plain"}
            )
        )
        async with MTGGoldfishClient(base_url=BASE_URL) as client:
            result = await client.get_archetype("modern", "Boros Energy")

        assert result.date == "Mar 29, 2026"

    @respx.mock
    async def test_mainboard_parsed(self):
        """Mainboard cards are parsed from deck download."""
        arch_html = _load_fixture("archetype_boros_energy.html")
        deck_txt = _load_fixture("deck_download.txt")
        respx.get(f"{BASE_URL}/archetype/modern-boros-energy").mock(
            return_value=httpx.Response(
                200, content=arch_html.encode(), headers={"Content-Type": "text/html"}
            )
        )
        respx.get(f"{BASE_URL}/deck/download/7708470").mock(
            return_value=httpx.Response(
                200, content=deck_txt.encode(), headers={"Content-Type": "text/plain"}
            )
        )
        async with MTGGoldfishClient(base_url=BASE_URL) as client:
            result = await client.get_archetype("modern", "Boros Energy")

        assert len(result.mainboard) > 0
        assert "4 Ajani, Nacatl Pariah" in result.mainboard
        assert "4 Ragavan, Nimble Pilferer" in result.mainboard

    @respx.mock
    async def test_sideboard_parsed(self):
        """Sideboard cards are parsed from deck download."""
        arch_html = _load_fixture("archetype_boros_energy.html")
        deck_txt = _load_fixture("deck_download.txt")
        respx.get(f"{BASE_URL}/archetype/modern-boros-energy").mock(
            return_value=httpx.Response(
                200, content=arch_html.encode(), headers={"Content-Type": "text/html"}
            )
        )
        respx.get(f"{BASE_URL}/deck/download/7708470").mock(
            return_value=httpx.Response(
                200, content=deck_txt.encode(), headers={"Content-Type": "text/plain"}
            )
        )
        async with MTGGoldfishClient(base_url=BASE_URL) as client:
            result = await client.get_archetype("modern", "Boros Energy")

        assert len(result.sideboard) > 0
        assert "2 High Noon" in result.sideboard
        assert "2 Surgical Extraction" in result.sideboard

    @respx.mock
    async def test_404_raises_archetype_not_found(self):
        """404 on archetype page raises ArchetypeNotFoundError."""
        html = _load_fixture("error_not_found.html")
        respx.get(f"{BASE_URL}/archetype/modern-nonexistent-deck").mock(
            return_value=httpx.Response(404, content=html.encode())
        )
        async with MTGGoldfishClient(base_url=BASE_URL) as client:
            with pytest.raises(ArchetypeNotFoundError, match="Nonexistent Deck"):
                await client.get_archetype("modern", "Nonexistent Deck")

    @respx.mock
    async def test_slugified_archetype_url(self):
        """Archetype name is slugified for the URL."""
        html = _load_fixture("error_not_found.html")
        respx.get(f"{BASE_URL}/archetype/modern-boros-energy").mock(
            return_value=httpx.Response(404, content=html.encode())
        )
        async with MTGGoldfishClient(base_url=BASE_URL) as client:
            with pytest.raises(ArchetypeNotFoundError):
                await client.get_archetype("modern", "Boros Energy")

        # Verify the URL used the slugified name
        assert respx.calls.last.request.url.path == "/archetype/modern-boros-energy"


class TestGetFormatStaples:
    """Tests for format staples page parsing."""

    @respx.mock
    async def test_parses_ten_staples(self):
        """Fixture with 10 rows returns 10 GoldfishFormatStaple objects."""
        html = _load_fixture("format_staples_modern.html")
        respx.get(f"{BASE_URL}/format-staples/modern").mock(
            return_value=httpx.Response(
                200, content=html.encode(), headers={"Content-Type": "text/html"}
            )
        )
        async with MTGGoldfishClient(base_url=BASE_URL) as client:
            result = await client.get_format_staples("modern")

        assert len(result) == 10
        assert all(isinstance(s, GoldfishFormatStaple) for s in result)

    @respx.mock
    async def test_staple_fields_mapped(self):
        """First staple's fields are correctly parsed."""
        html = _load_fixture("format_staples_modern.html")
        respx.get(f"{BASE_URL}/format-staples/modern").mock(
            return_value=httpx.Response(
                200, content=html.encode(), headers={"Content-Type": "text/html"}
            )
        )
        async with MTGGoldfishClient(base_url=BASE_URL) as client:
            result = await client.get_format_staples("modern")

        first = result[0]
        assert first.rank == 1
        assert first.name == "Consign to Memory"
        assert first.pct_of_decks == pytest.approx(50.0)
        assert first.copies_played == pytest.approx(3.4)

    @respx.mock
    async def test_last_staple_parsed(self):
        """Last staple (rank 10) is correctly parsed."""
        html = _load_fixture("format_staples_modern.html")
        respx.get(f"{BASE_URL}/format-staples/modern").mock(
            return_value=httpx.Response(
                200, content=html.encode(), headers={"Content-Type": "text/html"}
            )
        )
        async with MTGGoldfishClient(base_url=BASE_URL) as client:
            result = await client.get_format_staples("modern")

        last = result[-1]
        assert last.rank == 10
        assert last.name == "Wear // Tear"
        assert last.pct_of_decks == pytest.approx(31.0)
        assert last.copies_played == pytest.approx(1.7)

    @respx.mock
    async def test_limit_parameter(self):
        """Limit parameter restricts number of results."""
        html = _load_fixture("format_staples_modern.html")
        respx.get(f"{BASE_URL}/format-staples/modern").mock(
            return_value=httpx.Response(
                200, content=html.encode(), headers={"Content-Type": "text/html"}
            )
        )
        async with MTGGoldfishClient(base_url=BASE_URL) as client:
            result = await client.get_format_staples("modern", limit=3)

        assert len(result) == 3
        assert result[0].rank == 1
        assert result[2].rank == 3

    @respx.mock
    async def test_404_raises_format_not_found(self):
        """404 on staples page raises FormatNotFoundError."""
        html = _load_fixture("error_not_found.html")
        respx.get(f"{BASE_URL}/format-staples/invalid").mock(
            return_value=httpx.Response(404, content=html.encode())
        )
        async with MTGGoldfishClient(base_url=BASE_URL) as client:
            with pytest.raises(FormatNotFoundError, match="invalid"):
                await client.get_format_staples("invalid")


class TestGetDeckPrice:
    """Tests for deck price retrieval."""

    @respx.mock
    async def test_returns_price_dict(self):
        """get_deck_price returns price metadata from metagame + archetype."""
        meta_html = _load_fixture("metagame_modern.html")
        arch_html = _load_fixture("archetype_boros_energy.html")
        deck_txt = _load_fixture("deck_download.txt")
        respx.get(f"{BASE_URL}/metagame/modern/full").mock(
            return_value=httpx.Response(
                200, content=meta_html.encode(), headers={"Content-Type": "text/html"}
            )
        )
        respx.get(f"{BASE_URL}/archetype/modern-boros-energy").mock(
            return_value=httpx.Response(
                200, content=arch_html.encode(), headers={"Content-Type": "text/html"}
            )
        )
        respx.get(f"{BASE_URL}/deck/download/7708470").mock(
            return_value=httpx.Response(
                200, content=deck_txt.encode(), headers={"Content-Type": "text/plain"}
            )
        )
        async with MTGGoldfishClient(base_url=BASE_URL) as client:
            result = await client.get_deck_price("modern", "Boros Energy")

        assert isinstance(result, dict)
        assert result["archetype"] == "Boros Energy"
        assert result["price_paper"] == 860
        assert result["mainboard_count"] > 0
        assert result["sideboard_count"] > 0

    @respx.mock
    async def test_archetype_not_in_metagame(self):
        """ArchetypeNotFoundError when archetype name not in metagame snapshot."""
        meta_html = _load_fixture("metagame_modern.html")
        respx.get(f"{BASE_URL}/metagame/modern/full").mock(
            return_value=httpx.Response(
                200, content=meta_html.encode(), headers={"Content-Type": "text/html"}
            )
        )
        async with MTGGoldfishClient(base_url=BASE_URL) as client:
            with pytest.raises(ArchetypeNotFoundError, match="Unknown Deck"):
                await client.get_deck_price("modern", "Unknown Deck")


class TestCaching:
    """Tests for TTL cache behavior."""

    @respx.mock
    async def test_metagame_second_call_uses_cache(self):
        """Second identical get_metagame call returns cached result."""
        html = _load_fixture("metagame_modern.html")
        respx.get(f"{BASE_URL}/metagame/modern/full").mock(
            return_value=httpx.Response(
                200, content=html.encode(), headers={"Content-Type": "text/html"}
            )
        )
        async with MTGGoldfishClient(base_url=BASE_URL) as client:
            result1 = await client.get_metagame("modern")
            result2 = await client.get_metagame("modern")

        assert result1 == result2
        assert len(respx.calls) == 1  # Only one HTTP call

    @respx.mock
    async def test_different_formats_cached_separately(self):
        """Different format parameters create separate cache entries."""
        html = _load_fixture("metagame_modern.html")
        empty = "<html><body><div class='archetype-tile-container'></div></body></html>"
        respx.get(f"{BASE_URL}/metagame/modern/full").mock(
            return_value=httpx.Response(
                200, content=html.encode(), headers={"Content-Type": "text/html"}
            )
        )
        respx.get(f"{BASE_URL}/metagame/legacy/full").mock(
            return_value=httpx.Response(
                200, content=empty.encode(), headers={"Content-Type": "text/html"}
            )
        )
        async with MTGGoldfishClient(base_url=BASE_URL) as client:
            result1 = await client.get_metagame("modern")
            result2 = await client.get_metagame("legacy")

        assert len(result1.archetypes) == 3
        assert len(result2.archetypes) == 0
        assert len(respx.calls) == 2

    @respx.mock
    async def test_staples_cached(self):
        """Second identical get_format_staples call returns cached result."""
        html = _load_fixture("format_staples_modern.html")
        respx.get(f"{BASE_URL}/format-staples/modern").mock(
            return_value=httpx.Response(
                200, content=html.encode(), headers={"Content-Type": "text/html"}
            )
        )
        async with MTGGoldfishClient(base_url=BASE_URL) as client:
            result1 = await client.get_format_staples("modern")
            result2 = await client.get_format_staples("modern")

        assert result1 == result2
        assert len(respx.calls) == 1

    def test_cache_attributes_exist(self):
        """Cache attributes are accessible for clearing in conftest."""
        assert hasattr(MTGGoldfishClient.get_metagame, "cache")
        assert isinstance(MTGGoldfishClient.get_metagame.cache, TTLCache)
        assert hasattr(MTGGoldfishClient.get_archetype, "cache")
        assert isinstance(MTGGoldfishClient.get_archetype.cache, TTLCache)
        assert hasattr(MTGGoldfishClient.get_format_staples, "cache")
        assert isinstance(MTGGoldfishClient.get_format_staples.cache, TTLCache)
        assert hasattr(MTGGoldfishClient.get_deck_price, "cache")
        assert isinstance(MTGGoldfishClient.get_deck_price.cache, TTLCache)


class TestErrorHandling:
    """Tests for HTTP errors and non-HTML responses."""

    @respx.mock
    async def test_500_raises_mtggoldfish_error(self):
        """HTTP 500 raises MTGGoldfishError."""
        respx.get(f"{BASE_URL}/metagame/modern/full").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        async with MTGGoldfishClient(base_url=BASE_URL) as client:
            with pytest.raises(MTGGoldfishError):
                await client.get_metagame("modern")

    @respx.mock
    async def test_archetype_500_raises_mtggoldfish_error(self):
        """HTTP 500 on archetype page raises MTGGoldfishError."""
        respx.get(f"{BASE_URL}/archetype/modern-boros-energy").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        async with MTGGoldfishClient(base_url=BASE_URL) as client:
            with pytest.raises(MTGGoldfishError):
                await client.get_archetype("modern", "Boros Energy")

    @respx.mock
    async def test_user_agent_is_browser_like(self):
        """Client sends a browser-like User-Agent, not the default bot UA."""
        respx.get(f"{BASE_URL}/metagame/modern/full").mock(
            return_value=httpx.Response(
                200,
                content=b"<html><body></body></html>",
                headers={"Content-Type": "text/html"},
            )
        )
        async with MTGGoldfishClient(base_url=BASE_URL) as client:
            await client.get_metagame("modern")

        ua = respx.calls.last.request.headers.get("user-agent", "")
        # Should NOT be the default mtg-mcp-server UA
        assert "mtg-mcp-server" not in ua
        # Should look browser-like
        assert "Mozilla" in ua
