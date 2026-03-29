"""Tests for rules workflow functions.

These are unit tests of pure async functions. Service clients are mocked with
AsyncMock -- no respx/httpx needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mtg_mcp_server.types import Card, CardPrices, GlossaryEntry, Rule
from mtg_mcp_server.workflows import WorkflowResult
from mtg_mcp_server.workflows.rules import (
    combat_calculator,
    keyword_explain,
    rules_interaction,
    rules_lookup,
    rules_scenario,
)

# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_rules() -> AsyncMock:
    """Create a mock RulesService with reasonable defaults."""
    mock = AsyncMock()
    mock.lookup_by_number = AsyncMock(
        return_value=Rule(
            number="704.5k",
            text=(
                "If a player controls two or more legendary permanents with the "
                "same name, that player chooses one of them, and the rest are put "
                "into their owners' graveyards. This is called the 'legend rule'."
            ),
        )
    )
    mock.resolve_section = AsyncMock(
        side_effect=lambda s: s if s.replace(".", "").isdigit() else None
    )
    mock.keyword_search = AsyncMock(
        return_value=[
            Rule(number="702.2a", text="Deathtouch is a static ability."),
            Rule(
                number="702.2b",
                text=(
                    "A creature with toughness greater than 0 that's been dealt "
                    "damage by a source with deathtouch since the last time "
                    "state-based actions were checked is destroyed as a "
                    "state-based action."
                ),
            ),
        ]
    )
    mock.glossary_lookup = AsyncMock(
        return_value=GlossaryEntry(
            term="Deathtouch",
            definition=(
                "A keyword ability that causes a creature to be destroyed "
                "if it's dealt damage by a source with deathtouch."
            ),
        )
    )
    mock.list_keywords = AsyncMock(return_value=[{"term": "Deathtouch", "section": "702.2"}])
    mock.list_sections = AsyncMock(return_value=[{"number": "1", "name": "Game Concepts"}])
    mock.section_rules = AsyncMock(
        return_value=[
            Rule(
                number="100.1",
                text="These Magic rules apply to any Magic game with two or more players.",
            ),
        ]
    )
    return mock


def _make_bulk() -> AsyncMock:
    """Create a mock ScryfallBulkClient."""
    mock = AsyncMock()
    mock.search_by_text = AsyncMock(return_value=[])
    mock.get_card = AsyncMock(return_value=None)
    return mock


def _make_card(
    name: str = "Typhoid Rats",
    oracle_text: str = "Deathtouch",
    power: str = "1",
    toughness: str = "1",
    keywords: list[str] | None = None,
) -> Card:
    """Create a minimal Card for test purposes."""
    return Card(
        id="test-id",
        name=name,
        type_line="Creature",
        oracle_text=oracle_text,
        power=power,
        toughness=toughness,
        keywords=keywords or [],
        prices=CardPrices(),
    )


# ---------------------------------------------------------------------------
# rules_lookup
# ---------------------------------------------------------------------------


class TestRulesLookup:
    """Tests for the rules_lookup workflow function."""

    @pytest.mark.anyio
    async def test_lookup_by_rule_number(self) -> None:
        """Looking up a rule number should use lookup_by_number."""
        rules = _make_rules()

        result = await rules_lookup("704.5k", rules=rules)

        assert isinstance(result, WorkflowResult)
        assert "704.5k" in result.markdown
        assert "legend rule" in result.markdown
        rules.lookup_by_number.assert_awaited_once_with("704.5k")

    @pytest.mark.anyio
    async def test_lookup_by_rule_number_with_letter(self) -> None:
        """Rule numbers with letter suffixes (e.g. 702.2a) are detected."""
        rules = _make_rules()
        rules.lookup_by_number.return_value = Rule(
            number="702.2a", text="Deathtouch is a static ability."
        )

        result = await rules_lookup("702.2a", rules=rules)

        assert "702.2a" in result.markdown
        rules.lookup_by_number.assert_awaited_once_with("702.2a")

    @pytest.mark.anyio
    async def test_keyword_search(self) -> None:
        """Non-numeric queries should use keyword_search."""
        rules = _make_rules()

        result = await rules_lookup("deathtouch", rules=rules)

        assert isinstance(result, WorkflowResult)
        assert "702.2a" in result.markdown
        assert "702.2b" in result.markdown
        rules.keyword_search.assert_awaited_once_with("deathtouch")

    @pytest.mark.anyio
    async def test_section_filter(self) -> None:
        """When section is provided, filter results to that section."""
        rules = _make_rules()
        rules.keyword_search.return_value = [
            Rule(number="702.2a", text="Deathtouch is a static ability."),
            Rule(number="100.1", text="These rules apply to any Magic game."),
        ]

        result = await rules_lookup("deathtouch", rules=rules, section="702")

        assert "702.2a" in result.markdown
        assert "100.1" not in result.markdown

    @pytest.mark.anyio
    async def test_rule_number_not_found(self) -> None:
        """When a rule number lookup returns None, show not found."""
        rules = _make_rules()
        rules.lookup_by_number.return_value = None

        result = await rules_lookup("999.99", rules=rules)

        assert "not found" in result.markdown.lower() or "no rule" in result.markdown.lower()

    @pytest.mark.anyio
    async def test_keyword_search_no_results(self) -> None:
        """When keyword search returns empty, show no results."""
        rules = _make_rules()
        rules.keyword_search.return_value = []

        result = await rules_lookup("xyzzynonexistent", rules=rules)

        assert "no" in result.markdown.lower()

    @pytest.mark.anyio
    async def test_concise_format(self) -> None:
        """Concise format should be shorter than detailed."""
        rules = _make_rules()

        detailed = await rules_lookup("deathtouch", rules=rules, response_format="detailed")
        concise = await rules_lookup("deathtouch", rules=rules, response_format="concise")

        assert len(concise.markdown) <= len(detailed.markdown)

    @pytest.mark.anyio
    async def test_data_contains_rules(self) -> None:
        """The data dict should contain rules information."""
        rules = _make_rules()

        result = await rules_lookup("deathtouch", rules=rules)

        assert "rules" in result.data
        assert len(result.data["rules"]) > 0

    @pytest.mark.anyio
    async def test_simple_rule_number_formats(self) -> None:
        """Various rule number formats should be detected as numeric."""
        rules = _make_rules()

        # Bare number
        await rules_lookup("100", rules=rules)
        rules.lookup_by_number.assert_awaited()

        rules.lookup_by_number.reset_mock()

        # Dotted number
        await rules_lookup("100.1", rules=rules)
        rules.lookup_by_number.assert_awaited()


# ---------------------------------------------------------------------------
# keyword_explain
# ---------------------------------------------------------------------------


class TestKeywordExplain:
    """Tests for the keyword_explain workflow function."""

    @pytest.mark.anyio
    async def test_with_glossary_hit(self) -> None:
        """Should include glossary definition and related rules."""
        rules = _make_rules()

        result = await keyword_explain("deathtouch", rules=rules)

        assert isinstance(result, WorkflowResult)
        assert "Deathtouch" in result.markdown
        assert "keyword ability" in result.markdown
        assert "702.2a" in result.markdown
        rules.glossary_lookup.assert_awaited_once_with("deathtouch")
        rules.keyword_search.assert_awaited_once_with("deathtouch")

    @pytest.mark.anyio
    async def test_with_bulk_examples(self) -> None:
        """When bulk is provided, should include example cards."""
        rules = _make_rules()
        bulk = _make_bulk()
        bulk.search_by_text.return_value = [
            _make_card(name="Typhoid Rats", oracle_text="Deathtouch"),
            _make_card(name="Acidic Slime", oracle_text="Deathtouch"),
        ]

        result = await keyword_explain("deathtouch", rules=rules, bulk=bulk)

        assert "Typhoid Rats" in result.markdown
        assert "Acidic Slime" in result.markdown
        bulk.search_by_text.assert_awaited_once()

    @pytest.mark.anyio
    async def test_without_bulk(self) -> None:
        """When bulk is None, should still return glossary + rules."""
        rules = _make_rules()

        result = await keyword_explain("deathtouch", rules=rules, bulk=None)

        assert "Deathtouch" in result.markdown
        assert "702.2a" in result.markdown

    @pytest.mark.anyio
    async def test_glossary_not_found(self) -> None:
        """When glossary lookup returns None, should note it."""
        rules = _make_rules()
        rules.glossary_lookup.return_value = None

        result = await keyword_explain("nonsense", rules=rules)

        assert "no glossary" in result.markdown.lower() or "not found" in result.markdown.lower()

    @pytest.mark.anyio
    async def test_concise_format(self) -> None:
        """Concise format: definition + rule numbers only."""
        rules = _make_rules()

        detailed = await keyword_explain("deathtouch", rules=rules, response_format="detailed")
        concise = await keyword_explain("deathtouch", rules=rules, response_format="concise")

        assert len(concise.markdown) <= len(detailed.markdown)

    @pytest.mark.anyio
    async def test_interactions_included(self) -> None:
        """Keywords with known interactions should include an Interactions section."""
        rules = _make_rules()

        result = await keyword_explain("deathtouch", rules=rules)

        assert "## Interactions" in result.markdown
        assert "Trample" in result.markdown
        assert "First Strike" in result.markdown
        assert "Indestructible" in result.markdown
        # Data dict should also have interactions
        assert "interactions" in result.data
        assert len(result.data["interactions"]) == 3

    @pytest.mark.anyio
    async def test_no_interactions_for_unknown_keyword(self) -> None:
        """Keywords without known interactions should not have an Interactions section."""
        rules = _make_rules()
        rules.glossary_lookup.return_value = GlossaryEntry(
            term="Menace", definition="Can't be blocked except by two or more creatures."
        )
        rules.keyword_search.return_value = [
            Rule(number="702.110a", text="Menace is an evasion ability.")
        ]

        result = await keyword_explain("menace", rules=rules)

        assert "## Interactions" not in result.markdown
        assert result.data["interactions"] == []

    @pytest.mark.anyio
    async def test_data_contains_glossary(self) -> None:
        """The data dict should contain glossary and rules."""
        rules = _make_rules()

        result = await keyword_explain("deathtouch", rules=rules)

        assert "glossary" in result.data
        assert "rules" in result.data


# ---------------------------------------------------------------------------
# rules_interaction
# ---------------------------------------------------------------------------


class TestRulesInteraction:
    """Tests for the rules_interaction workflow function."""

    @pytest.mark.anyio
    async def test_two_mechanics_found(self) -> None:
        """Should search rules for both mechanics and combine them."""
        rules = _make_rules()
        rules.keyword_search.side_effect = [
            [Rule(number="702.2a", text="Deathtouch is a static ability.")],
            [Rule(number="702.19a", text="Trample is a static ability.")],
        ]
        rules.glossary_lookup.side_effect = [
            GlossaryEntry(term="Deathtouch", definition="Lethal with any damage."),
            GlossaryEntry(term="Trample", definition="Excess damage goes through."),
        ]

        result = await rules_interaction("deathtouch", "trample", rules=rules)

        assert isinstance(result, WorkflowResult)
        assert "Deathtouch" in result.markdown or "deathtouch" in result.markdown.lower()
        assert "Trample" in result.markdown or "trample" in result.markdown.lower()
        assert "702.2a" in result.markdown
        assert "702.19a" in result.markdown

    @pytest.mark.anyio
    async def test_one_not_found(self) -> None:
        """When one mechanic has no rules, still return what we can."""
        rules = _make_rules()
        rules.keyword_search.side_effect = [
            [Rule(number="702.2a", text="Deathtouch is a static ability.")],
            [],
        ]
        rules.glossary_lookup.side_effect = [
            GlossaryEntry(term="Deathtouch", definition="Lethal with any damage."),
            None,
        ]

        result = await rules_interaction("deathtouch", "nonsense", rules=rules)

        assert "702.2a" in result.markdown
        assert "no rules found" in result.markdown.lower() or "nonsense" in result.markdown.lower()

    @pytest.mark.anyio
    async def test_with_bulk(self) -> None:
        """When bulk is provided, should try to look up mechanics as cards."""
        rules = _make_rules()
        bulk = _make_bulk()
        rules.keyword_search.side_effect = [
            [Rule(number="702.2a", text="Deathtouch is a static ability.")],
            [Rule(number="702.19a", text="Trample is a static ability.")],
        ]
        rules.glossary_lookup.side_effect = [
            GlossaryEntry(term="Deathtouch", definition="Lethal with any damage."),
            GlossaryEntry(term="Trample", definition="Excess damage goes through."),
        ]

        result = await rules_interaction("deathtouch", "trample", rules=rules, bulk=bulk)

        assert isinstance(result, WorkflowResult)

    @pytest.mark.anyio
    async def test_concise_format(self) -> None:
        """Concise format should be shorter."""
        rules = _make_rules()
        rules.keyword_search.side_effect = [
            [Rule(number="702.2a", text="Deathtouch is a static ability.")],
            [Rule(number="702.19a", text="Trample is a static ability.")],
        ]
        rules.glossary_lookup.side_effect = [
            GlossaryEntry(term="Deathtouch", definition="Lethal with any damage."),
            GlossaryEntry(term="Trample", definition="Excess damage goes through."),
        ]
        detailed = await rules_interaction(
            "deathtouch", "trample", rules=rules, response_format="detailed"
        )
        rules.keyword_search.side_effect = [
            [Rule(number="702.2a", text="Deathtouch is a static ability.")],
            [Rule(number="702.19a", text="Trample is a static ability.")],
        ]
        rules.glossary_lookup.side_effect = [
            GlossaryEntry(term="Deathtouch", definition="Lethal with any damage."),
            GlossaryEntry(term="Trample", definition="Excess damage goes through."),
        ]
        concise = await rules_interaction(
            "deathtouch", "trample", rules=rules, response_format="concise"
        )

        assert len(concise.markdown) <= len(detailed.markdown)

    @pytest.mark.anyio
    async def test_interaction_note_included(self) -> None:
        """Known interactions should include an Interaction section with note."""
        rules = _make_rules()
        rules.keyword_search.side_effect = [
            [Rule(number="702.2a", text="Deathtouch is a static ability.")],
            [Rule(number="702.19a", text="Trample is a static ability.")],
        ]
        rules.glossary_lookup.side_effect = [
            GlossaryEntry(term="Deathtouch", definition="Lethal with any damage."),
            GlossaryEntry(term="Trample", definition="Excess damage goes through."),
        ]

        result = await rules_interaction("deathtouch", "trample", rules=rules)

        assert "## Interaction" in result.markdown
        assert "lethal" in result.markdown.lower()
        assert "702.2b" in result.markdown or "702.19b" in result.markdown
        assert result.data["interaction"] is not None

    @pytest.mark.anyio
    async def test_interaction_note_reverse_order(self) -> None:
        """Interaction note should be found regardless of argument order."""
        rules = _make_rules()
        rules.keyword_search.side_effect = [
            [Rule(number="702.19a", text="Trample is a static ability.")],
            [Rule(number="702.2a", text="Deathtouch is a static ability.")],
        ]
        rules.glossary_lookup.side_effect = [
            GlossaryEntry(term="Trample", definition="Excess damage goes through."),
            GlossaryEntry(term="Deathtouch", definition="Lethal with any damage."),
        ]

        result = await rules_interaction("trample", "deathtouch", rules=rules)

        assert "## Interaction" in result.markdown
        assert result.data["interaction"] is not None

    @pytest.mark.anyio
    async def test_no_interaction_note_for_unrelated(self) -> None:
        """Mechanics without known interactions should not have an Interaction section."""
        rules = _make_rules()
        rules.keyword_search.side_effect = [
            [Rule(number="702.2a", text="Deathtouch is a static ability.")],
            [],
        ]
        rules.glossary_lookup.side_effect = [
            GlossaryEntry(term="Deathtouch", definition="Lethal with any damage."),
            None,
        ]

        result = await rules_interaction("deathtouch", "nonsense", rules=rules)

        assert "## Interaction" not in result.markdown
        assert result.data["interaction"] is None

    @pytest.mark.anyio
    async def test_data_contains_both_mechanics(self) -> None:
        """The data dict should contain rules for both mechanics."""
        rules = _make_rules()
        rules.keyword_search.side_effect = [
            [Rule(number="702.2a", text="Deathtouch is a static ability.")],
            [Rule(number="702.19a", text="Trample is a static ability.")],
        ]
        rules.glossary_lookup.side_effect = [
            GlossaryEntry(term="Deathtouch", definition="Lethal with any damage."),
            GlossaryEntry(term="Trample", definition="Excess damage goes through."),
        ]

        result = await rules_interaction("deathtouch", "trample", rules=rules)

        assert "mechanic_a" in result.data
        assert "mechanic_b" in result.data


# ---------------------------------------------------------------------------
# rules_scenario
# ---------------------------------------------------------------------------


class TestRulesScenario:
    """Tests for the rules_scenario workflow function."""

    @pytest.mark.anyio
    async def test_returns_relevant_rules(self) -> None:
        """Should extract keywords from scenario and find rules."""
        rules = _make_rules()
        rules.keyword_search.return_value = [
            Rule(number="702.2a", text="Deathtouch is a static ability."),
        ]

        result = await rules_scenario(
            "A creature with deathtouch blocks a 5/5",
            rules=rules,
        )

        assert isinstance(result, WorkflowResult)
        assert "702.2a" in result.markdown
        rules.keyword_search.assert_awaited()

    @pytest.mark.anyio
    async def test_concise_format(self) -> None:
        """Concise format should be shorter."""
        rules = _make_rules()

        detailed = await rules_scenario(
            "A creature with deathtouch blocks a 5/5",
            rules=rules,
            response_format="detailed",
        )
        concise = await rules_scenario(
            "A creature with deathtouch blocks a 5/5",
            rules=rules,
            response_format="concise",
        )

        assert len(concise.markdown) <= len(detailed.markdown)

    @pytest.mark.anyio
    async def test_data_contains_rules(self) -> None:
        """Data dict should have rules and scenario echo."""
        rules = _make_rules()

        result = await rules_scenario(
            "A creature with deathtouch blocks a 5/5",
            rules=rules,
        )

        assert "rules" in result.data
        assert "scenario" in result.data

    @pytest.mark.anyio
    async def test_empty_scenario(self) -> None:
        """An empty scenario should still return a result."""
        rules = _make_rules()
        rules.keyword_search.return_value = []

        result = await rules_scenario("", rules=rules)

        assert isinstance(result, WorkflowResult)


# ---------------------------------------------------------------------------
# combat_calculator
# ---------------------------------------------------------------------------


class TestCombatCalculator:
    """Tests for the combat_calculator workflow function."""

    @pytest.mark.anyio
    async def test_basic_combat(self) -> None:
        """Should return combat phase steps and relevant rules."""
        rules = _make_rules()
        rules.keyword_search.return_value = [
            Rule(number="508.1", text="First, the active player declares attackers."),
        ]

        result = await combat_calculator(
            attackers=["Grizzly Bears"],
            blockers=["Hill Giant"],
            rules=rules,
        )

        assert isinstance(result, WorkflowResult)
        # Should reference combat steps
        assert "attack" in result.markdown.lower() or "combat" in result.markdown.lower()

    @pytest.mark.anyio
    async def test_with_keywords(self) -> None:
        """When keywords are provided, look up rules for each."""
        rules = _make_rules()
        rules.keyword_search.side_effect = [
            # Combat rules search
            [Rule(number="508.1", text="Declare attackers step.")],
            # deathtouch keyword search
            [Rule(number="702.2a", text="Deathtouch is a static ability.")],
        ]

        result = await combat_calculator(
            attackers=["Typhoid Rats"],
            blockers=["Hill Giant"],
            rules=rules,
            keywords=["deathtouch"],
        )

        assert "702.2a" in result.markdown or "deathtouch" in result.markdown.lower()

    @pytest.mark.anyio
    async def test_with_bulk_lookup(self) -> None:
        """When bulk is provided, look up card P/T and keywords."""
        rules = _make_rules()
        bulk = _make_bulk()
        attacker = _make_card(
            name="Typhoid Rats",
            oracle_text="Deathtouch",
            power="1",
            toughness="1",
            keywords=["Deathtouch"],
        )
        blocker = _make_card(
            name="Hill Giant",
            oracle_text="",
            power="3",
            toughness="3",
        )
        bulk.get_card.side_effect = [attacker, blocker]

        result = await combat_calculator(
            attackers=["Typhoid Rats"],
            blockers=["Hill Giant"],
            rules=rules,
            bulk=bulk,
        )

        assert "Typhoid Rats" in result.markdown
        assert "Hill Giant" in result.markdown

    @pytest.mark.anyio
    async def test_concise_format(self) -> None:
        """Concise format should be shorter."""
        rules = _make_rules()

        detailed = await combat_calculator(
            attackers=["Grizzly Bears"],
            blockers=["Hill Giant"],
            rules=rules,
            response_format="detailed",
        )
        concise = await combat_calculator(
            attackers=["Grizzly Bears"],
            blockers=["Hill Giant"],
            rules=rules,
            response_format="concise",
        )

        assert len(concise.markdown) <= len(detailed.markdown)

    @pytest.mark.anyio
    async def test_data_contains_combat_info(self) -> None:
        """Data dict should contain structured combat information."""
        rules = _make_rules()

        result = await combat_calculator(
            attackers=["Grizzly Bears"],
            blockers=["Hill Giant"],
            rules=rules,
        )

        assert "attackers" in result.data
        assert "blockers" in result.data

    @pytest.mark.anyio
    async def test_empty_blockers(self) -> None:
        """Should handle unblocked combat."""
        rules = _make_rules()

        result = await combat_calculator(
            attackers=["Grizzly Bears"],
            blockers=[],
            rules=rules,
        )

        assert isinstance(result, WorkflowResult)
        assert "unblocked" in result.markdown.lower() or "no blockers" in result.markdown.lower()
