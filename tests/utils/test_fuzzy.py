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

    def test_word_overlap_reordered(self):
        """Word overlap pass matches reordered multi-word queries (>= 2 shared words)."""
        result = match_archetype("Control Azorius", SAMPLE_ARCHETYPES)
        assert result == "Azorius Control"

    def test_single_word_overlap_uses_substring_not_overlap(self):
        """Single shared word matches via substring pass, not word overlap (>= 2 required)."""
        result = match_archetype("Boros", SAMPLE_ARCHETYPES)
        assert result == "Boros Energy"

    def test_word_overlap_boundary_one_word_high_threshold(self):
        """With high threshold and no substring match, single shared word should NOT match."""
        # "xyzzy energy" shares 1 word with "Boros Energy" — word overlap requires >= 2
        # No substring match either ("xyzzy energy" ∉ "boros energy" and vice versa)
        # Ratio too low for threshold=0.95 → returns None
        result = match_archetype("xyzzy energy", SAMPLE_ARCHETYPES, threshold=0.95)
        assert result is None
