"""Tests for the MTG Comprehensive Rules service."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
import respx

from mtg_mcp_server.services.rules import RulesService

FIXTURES = Path(__file__).parent.parent / "fixtures" / "rules"

_RULES_URL = "https://media.wizards.com/2025/downloads/MagicCompRules%2020250404.txt"


def _load_fixture_bytes() -> bytes:
    """Load the comprehensive rules fixture as bytes."""
    return (FIXTURES / "comprehensive_rules.txt").read_bytes()


def _mock_rules_download(
    router: respx.MockRouter,
    url: str = _RULES_URL,
    content: bytes | None = None,
    status_code: int = 200,
) -> respx.Route:
    """Register a rules download route on the respx mock router."""
    body = content if content is not None else _load_fixture_bytes()
    return router.get(url).mock(return_value=httpx.Response(status_code, content=body))


@pytest.fixture
async def service():
    """A RulesService with fixture data loaded via mocked HTTP."""
    with respx.mock:
        _mock_rules_download(respx)
        svc = RulesService(rules_url=_RULES_URL, refresh_hours=168)
        await svc.ensure_loaded()
        yield svc


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class TestParsing:
    """Rules file is correctly parsed into rules dict and glossary dict."""

    async def test_rules_dict_populated(self, service: RulesService) -> None:
        """Parsing creates a non-empty rules dictionary."""
        assert len(service._rules) > 0

    async def test_glossary_dict_populated(self, service: RulesService) -> None:
        """Parsing creates a non-empty glossary dictionary."""
        assert len(service._glossary) > 0

    async def test_specific_rule_parsed(self, service: RulesService) -> None:
        """Specific known rules are present with correct text."""
        rule = service._rules.get("100.1")
        assert rule is not None
        assert "Magic rules apply" in rule.text

    async def test_subrule_parsed(self, service: RulesService) -> None:
        """Subrules like 100.2a are present."""
        rule = service._rules.get("100.2a")
        assert rule is not None
        assert "constructed play" in rule.text.lower()

    async def test_rule_with_letter_suffix(self, service: RulesService) -> None:
        """Rules with letter suffixes like 704.5k are parsed."""
        rule = service._rules.get("704.5k")
        assert rule is not None
        assert "world rule" in rule.text.lower()

    async def test_glossary_entry_parsed(self, service: RulesService) -> None:
        """Glossary entries are correctly parsed."""
        entry = service._glossary.get("deathtouch")
        assert entry is not None
        assert entry.term == "Deathtouch"
        assert "damage" in entry.definition.lower()

    async def test_sections_populated(self, service: RulesService) -> None:
        """Section index is populated during parsing."""
        assert len(service._sections) > 0

    async def test_bom_handled(self) -> None:
        """UTF-8 BOM at start of file is stripped during parsing."""
        # The fixture file has a BOM — if parsing is broken, rules won't load
        with respx.mock:
            _mock_rules_download(respx)
            svc = RulesService(rules_url=_RULES_URL, refresh_hours=168)
            await svc.ensure_loaded()
            # First line should not contain BOM character
            first_rule = svc._rules.get("100.1")
            assert first_rule is not None


# ---------------------------------------------------------------------------
# lookup_by_number
# ---------------------------------------------------------------------------


class TestLookupByNumber:
    """O(1) rule lookup by number."""

    async def test_exact_match(self, service: RulesService) -> None:
        """Returns the correct Rule for a valid number."""
        rule = await service.lookup_by_number("704.5j")
        assert rule is not None
        assert rule.number == "704.5j"
        assert "legend rule" in rule.text.lower()

    async def test_not_found(self, service: RulesService) -> None:
        """Returns None for an invalid rule number."""
        rule = await service.lookup_by_number("999.99z")
        assert rule is None

    async def test_top_level_rule(self, service: RulesService) -> None:
        """Can look up a top-level rule like 704.1."""
        rule = await service.lookup_by_number("704.1")
        assert rule is not None
        assert "state-based actions" in rule.text.lower()

    async def test_period_suffix_rule(self, service: RulesService) -> None:
        """Rule number with trailing period is normalized."""
        rule = await service.lookup_by_number("100.1.")
        # Should still find 100.1 (strip trailing period)
        assert rule is not None
        assert rule.number == "100.1"

    async def test_subrule_hierarchy(self, service: RulesService) -> None:
        """Parent rules contain their subrules."""
        rule = await service.lookup_by_number("704.5")
        assert rule is not None
        assert len(rule.subrules) >= 4  # 704.5a, 704.5b, 704.5c, 704.5j, 704.5k
        subrule_numbers = {sr.number for sr in rule.subrules}
        assert "704.5a" in subrule_numbers
        assert "704.5j" in subrule_numbers

    async def test_subrule_hierarchy_keywords(self, service: RulesService) -> None:
        """Keyword section parent has subrules."""
        rule = await service.lookup_by_number("702.2")
        assert rule is not None
        assert len(rule.subrules) >= 3  # 702.2a, 702.2b, 702.2c, 702.2d
        subrule_numbers = {sr.number for sr in rule.subrules}
        assert "702.2a" in subrule_numbers
        assert "702.2b" in subrule_numbers


# ---------------------------------------------------------------------------
# keyword_search
# ---------------------------------------------------------------------------


class TestKeywordSearch:
    """Scan rule text for substring matches, ranked by relevance."""

    async def test_finds_matching_rules(self, service: RulesService) -> None:
        """Returns rules containing the keyword."""
        results = await service.keyword_search("deathtouch")
        assert len(results) > 0
        # All results should mention deathtouch
        for rule in results:
            assert "deathtouch" in rule.text.lower()

    async def test_case_insensitive(self, service: RulesService) -> None:
        """Search is case-insensitive."""
        results_lower = await service.keyword_search("deathtouch")
        results_upper = await service.keyword_search("DEATHTOUCH")
        assert len(results_lower) == len(results_upper)

    async def test_max_results(self, service: RulesService) -> None:
        """Returns at most 20 results."""
        results = await service.keyword_search("the")
        assert len(results) <= 20

    async def test_relevance_ranking(self, service: RulesService) -> None:
        """Exact/word-boundary matches rank higher than substring matches."""
        results = await service.keyword_search("flying")
        # The rule that defines "Flying" (702.9) should rank high
        numbers = [r.number for r in results]
        # 702.9 or 702.9a should appear early
        flying_indices = [i for i, n in enumerate(numbers) if n.startswith("702.9")]
        assert len(flying_indices) > 0
        # Flying definition rules should be in the top results
        assert flying_indices[0] < 5

    async def test_no_results(self, service: RulesService) -> None:
        """Returns empty list for a keyword with no matches."""
        results = await service.keyword_search("xyznonexistent123")
        assert results == []


# ---------------------------------------------------------------------------
# glossary_lookup
# ---------------------------------------------------------------------------


class TestGlossaryLookup:
    """Case-insensitive glossary lookup."""

    async def test_exact_match(self, service: RulesService) -> None:
        """Finds a glossary entry by exact term."""
        entry = await service.glossary_lookup("Deathtouch")
        assert entry is not None
        assert entry.term == "Deathtouch"

    async def test_case_insensitive(self, service: RulesService) -> None:
        """Lookup is case-insensitive."""
        entry = await service.glossary_lookup("FLYING")
        assert entry is not None
        assert entry.term == "Flying"

    async def test_not_found(self, service: RulesService) -> None:
        """Returns None for unknown terms."""
        entry = await service.glossary_lookup("Nonexistent Term")
        assert entry is None

    async def test_multi_word_term(self, service: RulesService) -> None:
        """Multi-word glossary terms work correctly."""
        entry = await service.glossary_lookup("legend rule")
        assert entry is not None
        assert "legendary" in entry.definition.lower()

    async def test_hyphenated_term(self, service: RulesService) -> None:
        """Hyphenated terms like 'State-Based Actions' work."""
        entry = await service.glossary_lookup("state-based actions")
        assert entry is not None


# ---------------------------------------------------------------------------
# list_keywords
# ---------------------------------------------------------------------------


class TestListKeywords:
    """Return glossary entries that are keywords (702.x rules)."""

    async def test_returns_keyword_list(self, service: RulesService) -> None:
        """Returns a non-empty list of keyword dicts."""
        keywords = await service.list_keywords()
        assert len(keywords) > 0

    async def test_keyword_has_expected_fields(self, service: RulesService) -> None:
        """Each keyword dict has 'term' and 'definition' keys."""
        keywords = await service.list_keywords()
        for kw in keywords:
            assert "term" in kw
            assert "definition" in kw

    async def test_known_keywords_present(self, service: RulesService) -> None:
        """Known keywords like Deathtouch, Flying, Trample are returned."""
        keywords = await service.list_keywords()
        terms = {kw["term"].lower() for kw in keywords}
        assert "deathtouch" in terms
        assert "flying" in terms
        assert "trample" in terms

    async def test_non_keywords_excluded(self, service: RulesService) -> None:
        """Non-keyword glossary entries (e.g., Legend Rule) are not returned."""
        keywords = await service.list_keywords()
        terms = {kw["term"].lower() for kw in keywords}
        assert "legend rule" not in terms


# ---------------------------------------------------------------------------
# list_sections
# ---------------------------------------------------------------------------


class TestListSections:
    """Return the section index."""

    async def test_returns_section_list(self, service: RulesService) -> None:
        """Returns a non-empty list of section dicts."""
        sections = await service.list_sections()
        assert len(sections) > 0

    async def test_section_has_expected_fields(self, service: RulesService) -> None:
        """Each section dict has 'number' and 'name' keys."""
        sections = await service.list_sections()
        for section in sections:
            assert "number" in section
            assert "name" in section

    async def test_known_sections_present(self, service: RulesService) -> None:
        """Known sections are present."""
        sections = await service.list_sections()
        section_map = {s["number"]: s["name"] for s in sections}
        assert "1" in section_map
        assert "Game Concepts" in section_map["1"]


# ---------------------------------------------------------------------------
# section_rules
# ---------------------------------------------------------------------------


class TestSectionRules:
    """Return all rules starting with a section prefix."""

    async def test_returns_matching_rules(self, service: RulesService) -> None:
        """Returns rules for a given section prefix."""
        rules = await service.section_rules("704")
        assert len(rules) > 0
        for rule in rules:
            assert rule.number.startswith("704")

    async def test_single_digit_prefix(self, service: RulesService) -> None:
        """Works with a single-digit section prefix."""
        rules = await service.section_rules("100")
        assert len(rules) > 0
        for rule in rules:
            assert rule.number.startswith("100")

    async def test_empty_for_unknown_section(self, service: RulesService) -> None:
        """Returns empty list for a non-existent section."""
        rules = await service.section_rules("999")
        assert rules == []


# ---------------------------------------------------------------------------
# Lazy loading
# ---------------------------------------------------------------------------


class TestLazyLoading:
    """First access triggers download; data is cached after."""

    async def test_first_access_triggers_download(self) -> None:
        """Calling a method on an unloaded service triggers download."""
        with respx.mock:
            route = _mock_rules_download(respx)
            svc = RulesService(rules_url=_RULES_URL, refresh_hours=168)
            # Not loaded yet
            assert not svc._loaded
            # Access triggers load
            await svc.lookup_by_number("100.1")
            assert svc._loaded
            assert route.called

    async def test_second_access_no_redownload(self) -> None:
        """Second access does not re-download."""
        with respx.mock:
            route = _mock_rules_download(respx)
            svc = RulesService(rules_url=_RULES_URL, refresh_hours=168)
            await svc.ensure_loaded()
            call_count_1 = route.call_count
            await svc.ensure_loaded()
            assert route.call_count == call_count_1

    async def test_concurrent_loads_single_download(self) -> None:
        """Concurrent ensure_loaded calls result in a single download."""
        with respx.mock:
            route = _mock_rules_download(respx)
            svc = RulesService(rules_url=_RULES_URL, refresh_hours=168)
            await asyncio.gather(
                svc.ensure_loaded(),
                svc.ensure_loaded(),
                svc.ensure_loaded(),
            )
            assert route.call_count == 1


# ---------------------------------------------------------------------------
# Stale data on refresh failure
# ---------------------------------------------------------------------------


class TestStaleData:
    """On refresh failure with existing data, serve stale data."""

    async def test_stale_data_served_on_failure(self) -> None:
        """After initial load, refresh failure keeps old data."""
        with respx.mock:
            _mock_rules_download(respx)
            svc = RulesService(rules_url=_RULES_URL, refresh_hours=0)
            await svc.ensure_loaded()
            # Verify data was loaded
            rule = await svc.lookup_by_number("100.1")
            assert rule is not None

        # Now simulate a failed refresh by mocking a 500 error
        with respx.mock:
            _mock_rules_download(respx, status_code=500)
            # Force stale by setting loaded_at to the past
            svc._loaded_at = 0.0
            # Should not raise — serves stale data
            await svc.ensure_loaded()
            # Data is still available
            rule = await svc.lookup_by_number("100.1")
            assert rule is not None

    async def test_first_load_failure_raises(self) -> None:
        """First load failure propagates the error."""
        with respx.mock:
            _mock_rules_download(respx, status_code=500)
            svc = RulesService(rules_url=_RULES_URL, refresh_hours=168)
            with pytest.raises(Exception, match="HTTP 500"):
                await svc.ensure_loaded()

    async def test_network_error_raises_download_error(self) -> None:
        """Network-level failure (connection refused, DNS timeout) raises RulesDownloadError."""
        with respx.mock:
            respx.get(_RULES_URL).mock(side_effect=httpx.ConnectError("connection refused"))
            svc = RulesService(rules_url=_RULES_URL, refresh_hours=168)
            with pytest.raises(Exception, match="Network error"):
                await svc.ensure_loaded()

    async def test_network_error_on_refresh_serves_stale(self) -> None:
        """Network error during refresh serves stale data."""
        with respx.mock:
            _mock_rules_download(respx)
            svc = RulesService(rules_url=_RULES_URL, refresh_hours=0)
            await svc.ensure_loaded()
            rule = await svc.lookup_by_number("100.1")
            assert rule is not None

        with respx.mock:
            respx.get(_RULES_URL).mock(side_effect=httpx.ConnectError("connection refused"))
            svc._loaded_at = 0.0
            await svc.ensure_loaded()
            rule = await svc.lookup_by_number("100.1")
            assert rule is not None
