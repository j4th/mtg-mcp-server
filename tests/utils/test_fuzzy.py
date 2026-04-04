"""Tests for archetype fuzzy matching utility."""

from mtg_mcp_server.utils.fuzzy import match_archetype

SAMPLE_ARCHETYPES = [
    "Boros Energy",
    "Mono-Blue Terror",
    "Azorius Control",
    "Golgari Midrange",
    "Rakdos Scam",
]


class TestMatchArchetype:
    """Tests for match_archetype()."""

    def test_exact_match(self):
        result = match_archetype("Boros Energy", SAMPLE_ARCHETYPES)
        assert result == "Boros Energy"

    def test_case_insensitive(self):
        result = match_archetype("boros energy", SAMPLE_ARCHETYPES)
        assert result == "Boros Energy"

    def test_fuzzy_match_close_spelling(self):
        result = match_archetype("mono blue terror", SAMPLE_ARCHETYPES)
        assert result == "Mono-Blue Terror"

    def test_fuzzy_match_partial(self):
        result = match_archetype("azorius ctrl", SAMPLE_ARCHETYPES)
        assert result == "Azorius Control"

    def test_below_threshold_returns_none(self):
        result = match_archetype("completely unrelated name", SAMPLE_ARCHETYPES)
        assert result is None

    def test_empty_list_returns_none(self):
        result = match_archetype("Boros Energy", [])
        assert result is None

    def test_slug_match_strips_punctuation(self):
        result = match_archetype("mono-blue-terror", SAMPLE_ARCHETYPES)
        assert result == "Mono-Blue Terror"

    def test_custom_threshold(self):
        # With a very high threshold, fuzzy matches should fail
        result = match_archetype("boros aggro", SAMPLE_ARCHETYPES, threshold=0.95)
        assert result is None

    def test_best_match_chosen(self):
        result = match_archetype("Golgari", SAMPLE_ARCHETYPES)
        assert result == "Golgari Midrange"
