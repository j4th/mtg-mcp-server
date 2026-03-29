"""Rules workflow functions — composed tools for MTG rules lookups.

These are pure async functions with no MCP awareness. They accept a
RulesService (and optionally a ScryfallBulkClient) as keyword arguments
and return ``WorkflowResult(markdown, data)``. The workflow server
(``server.py``) registers them as MCP tools and handles ToolError
conversion.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import structlog

from mtg_mcp_server.workflows import WorkflowResult

if TYPE_CHECKING:
    from collections.abc import Callable

    from mtg_mcp_server.services.rules import RulesService
    from mtg_mcp_server.services.scryfall_bulk import ScryfallBulkClient
    from mtg_mcp_server.types import Card, GlossaryEntry, Rule
    from mtg_mcp_server.utils.formatters import ResponseFormat

log = structlog.get_logger(service="workflow.rules")

# Pattern to detect rule numbers: digits and dots, optional trailing letter(s)
_RULE_NUMBER_RE = re.compile(r"^\d+(\.\d+[a-z]*)*$")

# Minimum word length to try as a keyword when extracting from scenario text
_MIN_KEYWORD_LEN = 4

# Common stop words to skip during scenario extraction
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "shall",
        "with",
        "from",
        "into",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        "they",
        "them",
        "their",
        "what",
        "when",
        "where",
        "which",
        "who",
        "how",
        "not",
        "and",
        "but",
        "or",
        "if",
        "then",
        "than",
        "for",
        "to",
        "of",
        "in",
        "on",
        "at",
        "by",
        "as",
        "all",
        "each",
        "any",
        "no",
        "some",
        "more",
        "other",
        "another",
        "about",
        "after",
        "before",
        "during",
        "while",
    }
)

# Known keyword interactions for keyword_explain and rules_interaction.
# Maps lowercased keyword to list of (related_keyword, interaction_note).
_KEYWORD_INTERACTIONS: dict[str, list[tuple[str, str]]] = {
    "deathtouch": [
        (
            "trample",
            "Only 1 damage needs to be assigned to each blocker for lethal (702.2b + 702.19b)",
        ),
        (
            "first strike",
            "Deathtouch applies in the first strike damage step — blockers die before dealing regular damage",
        ),
        (
            "indestructible",
            "Indestructible prevents destruction from deathtouch (702.2b references 704, but 702.12b overrides)",
        ),
    ],
    "trample": [
        (
            "deathtouch",
            "Only 1 damage needs to be assigned to each blocker for lethal (702.2b + 702.19b)",
        ),
        (
            "indestructible",
            "Must still assign lethal damage to indestructible blockers before trampling over",
        ),
        (
            "protection",
            "Can't assign damage to a creature with protection — all damage tramples through",
        ),
    ],
    "flying": [
        (
            "reach",
            "Reach allows a creature without flying to block a creature with flying (702.17b)",
        ),
    ],
    "first strike": [
        (
            "double strike",
            "Both deal damage in the first strike step; double strike also deals in the regular step",
        ),
        ("deathtouch", "First strike + deathtouch kills blockers before they deal regular damage"),
    ],
    "double strike": [
        (
            "first strike",
            "Both deal damage in the first strike step; double strike also deals in the regular step",
        ),
        ("trample", "Trample excess applies in both damage steps"),
        ("lifelink", "Lifelink triggers on both damage steps"),
    ],
    "lifelink": [
        ("double strike", "Lifelink triggers on both damage steps"),
        ("deathtouch", "No special interaction — both apply independently"),
    ],
    "indestructible": [
        ("deathtouch", "Indestructible prevents destruction from deathtouch"),
        ("trample", "Must still assign lethal damage before trampling over"),
        (
            "-1/-1 counters",
            "Indestructible doesn't prevent death from 0 toughness (state-based action 704.5f)",
        ),
    ],
}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _fmt_rule_concise(rule: Rule) -> str:
    """Format a rule for concise output: number + first sentence."""
    first_line = rule.text.split(".")[0] + "." if "." in rule.text else rule.text
    return f"**{rule.number}** {first_line}"


def _fmt_rule_detailed(rule: Rule) -> str:
    """Format a rule for detailed output: number + full text."""
    return f"**{rule.number}** {rule.text}"


def _get_rule_formatter(response_format: ResponseFormat) -> Callable[[Rule], str]:
    """Return the rule formatter matching the requested verbosity."""
    return _fmt_rule_concise if response_format == "concise" else _fmt_rule_detailed


def _is_rule_number(query: str) -> bool:
    """Check if a query looks like a rule number (e.g. '704.5k', '100.1')."""
    return bool(_RULE_NUMBER_RE.match(query.strip()))


def _fmt_card_example(card: Card) -> str:
    """Format a card as a brief example line."""
    parts = [f"**{card.name}**"]
    if card.type_line:
        parts.append(f"({card.type_line})")
    if card.oracle_text:
        # Truncate long oracle text
        text = card.oracle_text
        if len(text) > 120:
            text = text[:117] + "..."
        parts.append(f"-- {text}")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Workflow functions
# ---------------------------------------------------------------------------


async def rules_lookup(
    query: str,
    *,
    rules: RulesService,
    section: str | None = None,
    response_format: ResponseFormat = "detailed",
) -> WorkflowResult:
    """Look up Magic rules by number or keyword search.

    If *query* looks like a rule number (digits and dots, optional letter
    suffix), uses ``rules.lookup_by_number()``. Otherwise searches via
    ``rules.keyword_search()``.

    Args:
        query: A rule number (e.g. "704.5k") or keyword (e.g. "deathtouch").
        rules: Initialized RulesService.
        section: Optional section prefix to filter results.
        response_format: ``"detailed"`` (default) or ``"concise"``.

    Returns:
        WorkflowResult with formatted markdown and structured data.
    """
    log.info("rules_lookup.start", query=query, section=section)
    fmt = _get_rule_formatter(response_format)

    found_rules: list[Rule] = []

    if _is_rule_number(query.strip()):
        # Direct rule number lookup
        result = await rules.lookup_by_number(query.strip())
        if result is not None:
            found_rules = [result]
    else:
        # Keyword search
        found_rules = await rules.keyword_search(query)

    # Apply section filter
    if section and found_rules:
        found_rules = [r for r in found_rules if r.number.startswith(section)]

    # Build markdown
    lines: list[str] = []

    if not found_rules:
        lines.append(f"# Rules Lookup: {query}")
        lines.append("")
        lines.append(f"No rules found for '{query}'.")
        if section:
            lines.append(f"(filtered to section {section})")
    else:
        lines.append(f"# Rules: {query}")
        lines.append("")
        if section:
            lines.append(f"*Filtered to section {section}*")
            lines.append("")
        lines.append(f"Found {len(found_rules)} rule(s):")
        lines.append("")
        for rule in found_rules:
            lines.append(f"- {fmt(rule)}")

    # Build data
    data = {
        "query": query,
        "section": section,
        "rules": [r.model_dump(mode="json") for r in found_rules],
    }

    log.info("rules_lookup.complete", query=query, count=len(found_rules))
    return WorkflowResult(markdown="\n".join(lines), data=data)


async def keyword_explain(
    keyword: str,
    *,
    rules: RulesService,
    bulk: ScryfallBulkClient | None = None,
    response_format: ResponseFormat = "detailed",
) -> WorkflowResult:
    """Explain a Magic keyword with glossary definition, rules, and examples.

    Looks up the keyword in the glossary, searches for related rules, and
    optionally finds example cards with the keyword.

    Args:
        keyword: The keyword to explain (e.g. "deathtouch", "trample").
        rules: Initialized RulesService.
        bulk: Optional ScryfallBulkClient for card examples.
        response_format: ``"detailed"`` (default) or ``"concise"``.

    Returns:
        WorkflowResult with formatted markdown and structured data.
    """
    log.info("keyword_explain.start", keyword=keyword)
    fmt = _get_rule_formatter(response_format)

    # Fetch glossary entry and rules in sequence (rules service is local, fast)
    glossary: GlossaryEntry | None = await rules.glossary_lookup(keyword)
    related_rules: list[Rule] = await rules.keyword_search(keyword)

    # Fetch example cards if bulk is available
    example_cards: list[Card] = []
    if bulk is not None:
        try:
            example_cards = await bulk.search_by_text(keyword, limit=5)
        except Exception:
            log.debug("keyword_explain.bulk_failed", keyword=keyword)

    # Build markdown
    lines: list[str] = []
    lines.append(f"# {keyword.title()}")
    lines.append("")

    # Glossary section
    if glossary is not None:
        lines.append("## Definition")
        lines.append("")
        lines.append(glossary.definition)
        lines.append("")
    else:
        lines.append("*No glossary entry found for this keyword.*")
        lines.append("")

    # Rules section
    if related_rules:
        lines.append("## Rules")
        lines.append("")
        for rule in related_rules:
            lines.append(f"- {fmt(rule)}")
        lines.append("")

    # Interactions section — known interactions with other keywords
    interactions = _KEYWORD_INTERACTIONS.get(keyword.lower(), [])
    if interactions:
        lines.append("## Interactions")
        lines.append("")
        for related_kw, note in interactions:
            lines.append(f"- **{related_kw.title()}**: {note}")
        lines.append("")

    # Examples section (detailed only)
    if response_format == "detailed" and example_cards:
        lines.append("## Example Cards")
        lines.append("")
        for card in example_cards:
            lines.append(f"- {_fmt_card_example(card)}")
        lines.append("")

    # Build data
    data: dict = {
        "keyword": keyword,
        "glossary": glossary.model_dump(mode="json") if glossary else None,
        "rules": [r.model_dump(mode="json") for r in related_rules],
        "interactions": [{"keyword": kw, "note": note} for kw, note in interactions],
        "example_cards": [c.name for c in example_cards],
    }

    log.info("keyword_explain.complete", keyword=keyword, rules=len(related_rules))
    return WorkflowResult(markdown="\n".join(lines), data=data)


async def rules_interaction(
    mechanic_a: str,
    mechanic_b: str,
    *,
    rules: RulesService,
    bulk: ScryfallBulkClient | None = None,
    response_format: ResponseFormat = "detailed",
) -> WorkflowResult:
    """Explain how two mechanics interact with relevant rule citations.

    Searches rules for both mechanics and combines the findings. If bulk
    is provided, attempts to look up mechanics as card names.

    Args:
        mechanic_a: First mechanic or keyword (e.g. "deathtouch").
        mechanic_b: Second mechanic or keyword (e.g. "trample").
        rules: Initialized RulesService.
        bulk: Optional ScryfallBulkClient for card lookups.
        response_format: ``"detailed"`` (default) or ``"concise"``.

    Returns:
        WorkflowResult with formatted markdown and structured data.
    """
    log.info("rules_interaction.start", mechanic_a=mechanic_a, mechanic_b=mechanic_b)
    fmt = _get_rule_formatter(response_format)

    # Look up both mechanics
    glossary_a: GlossaryEntry | None = await rules.glossary_lookup(mechanic_a)
    rules_a: list[Rule] = await rules.keyword_search(mechanic_a)

    glossary_b: GlossaryEntry | None = await rules.glossary_lookup(mechanic_b)
    rules_b: list[Rule] = await rules.keyword_search(mechanic_b)

    # Optional card lookups via bulk
    card_a: Card | None = None
    card_b: Card | None = None
    if bulk is not None:
        try:
            card_a = await bulk.get_card(mechanic_a)
        except Exception:
            log.debug("rules_interaction.bulk_lookup_failed", name=mechanic_a)
        try:
            card_b = await bulk.get_card(mechanic_b)
        except Exception:
            log.debug("rules_interaction.bulk_lookup_failed", name=mechanic_b)

    # Build markdown
    lines: list[str] = []
    lines.append(f"# Interaction: {mechanic_a.title()} + {mechanic_b.title()}")
    lines.append("")

    # Mechanic A
    lines.append(f"## {mechanic_a.title()}")
    lines.append("")
    if glossary_a:
        lines.append(f"**Definition:** {glossary_a.definition}")
        lines.append("")
    if rules_a:
        for rule in rules_a:
            lines.append(f"- {fmt(rule)}")
        lines.append("")
    else:
        lines.append(f"No rules found for '{mechanic_a}'.")
        lines.append("")

    if response_format == "detailed" and card_a:
        lines.append(f"*Card: {_fmt_card_example(card_a)}*")
        lines.append("")

    # Mechanic B
    lines.append(f"## {mechanic_b.title()}")
    lines.append("")
    if glossary_b:
        lines.append(f"**Definition:** {glossary_b.definition}")
        lines.append("")
    if rules_b:
        for rule in rules_b:
            lines.append(f"- {fmt(rule)}")
        lines.append("")
    else:
        lines.append(f"No rules found for '{mechanic_b}'.")
        lines.append("")

    if response_format == "detailed" and card_b:
        lines.append(f"*Card: {_fmt_card_example(card_b)}*")
        lines.append("")

    # Interaction notes — cross-reference _KEYWORD_INTERACTIONS for both directions
    interaction_note: str | None = None
    a_lower = mechanic_a.lower()
    b_lower = mechanic_b.lower()
    for related_kw, note in _KEYWORD_INTERACTIONS.get(a_lower, []):
        if related_kw.lower() == b_lower:
            interaction_note = note
            break
    if interaction_note is None:
        for related_kw, note in _KEYWORD_INTERACTIONS.get(b_lower, []):
            if related_kw.lower() == a_lower:
                interaction_note = note
                break

    if interaction_note is not None:
        lines.append("## Interaction")
        lines.append("")
        lines.append(f"**{mechanic_a.title()} + {mechanic_b.title()}:** {interaction_note}")
        lines.append("")

    # Build data
    data = {
        "mechanic_a": {
            "name": mechanic_a,
            "glossary": glossary_a.model_dump(mode="json") if glossary_a else None,
            "rules": [r.model_dump(mode="json") for r in rules_a],
        },
        "mechanic_b": {
            "name": mechanic_b,
            "glossary": glossary_b.model_dump(mode="json") if glossary_b else None,
            "rules": [r.model_dump(mode="json") for r in rules_b],
        },
        "interaction": interaction_note,
    }

    log.info(
        "rules_interaction.complete",
        mechanic_a=mechanic_a,
        mechanic_b=mechanic_b,
        rules_a=len(rules_a),
        rules_b=len(rules_b),
    )
    return WorkflowResult(markdown="\n".join(lines), data=data)


async def rules_scenario(
    scenario: str,
    *,
    rules: RulesService,
    response_format: ResponseFormat = "detailed",
) -> WorkflowResult:
    """Provide rules framework for a game scenario.

    Extracts keywords/concepts from the scenario text, searches rules for
    each, and returns organized findings. The LLM does the reasoning --
    this tool provides the rules framework.

    Args:
        scenario: A description of the game situation.
        rules: Initialized RulesService.
        response_format: ``"detailed"`` (default) or ``"concise"``.

    Returns:
        WorkflowResult with formatted markdown and structured data.
    """
    log.info("rules_scenario.start", scenario_len=len(scenario))
    fmt = _get_rule_formatter(response_format)

    # Extract candidate keywords from the scenario
    words = re.findall(r"[a-zA-Z]+", scenario.lower())
    candidates = [w for w in words if len(w) >= _MIN_KEYWORD_LEN and w not in _STOP_WORDS]
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_candidates: list[str] = []
    for w in candidates:
        if w not in seen:
            seen.add(w)
            unique_candidates.append(w)

    # Search rules for each candidate keyword
    all_rules: dict[str, list[Rule]] = {}
    for candidate in unique_candidates:
        try:
            found = await rules.keyword_search(candidate)
            if found:
                all_rules[candidate] = found
        except Exception:
            log.debug("rules_scenario.search_failed", keyword=candidate)

    # Collect all unique rules (dedup by number)
    seen_numbers: set[str] = set()
    unique_rules: list[Rule] = []
    for rule_list in all_rules.values():
        for rule in rule_list:
            if rule.number not in seen_numbers:
                seen_numbers.add(rule.number)
                unique_rules.append(rule)

    # Build markdown
    lines: list[str] = []
    lines.append("# Rules Scenario Analysis")
    lines.append("")

    if response_format == "detailed":
        lines.append("## Scenario")
        lines.append("")
        lines.append(f"> {scenario}" if scenario else "> (empty scenario)")
        lines.append("")

    if not unique_rules:
        lines.append("No relevant rules found for this scenario.")
    else:
        lines.append(f"## Relevant Rules ({len(unique_rules)} found)")
        lines.append("")

        if response_format == "detailed":
            # Group by keyword
            for keyword, rule_list in all_rules.items():
                lines.append(f"### {keyword.title()}")
                lines.append("")
                for rule in rule_list:
                    lines.append(f"- {fmt(rule)}")
                lines.append("")
        else:
            # Concise: flat list
            for rule in unique_rules:
                lines.append(f"- {fmt(rule)}")

    # Build data
    data = {
        "scenario": scenario,
        "keywords_extracted": list(all_rules.keys()),
        "rules": [r.model_dump(mode="json") for r in unique_rules],
    }

    log.info("rules_scenario.complete", keywords=len(all_rules), rules=len(unique_rules))
    return WorkflowResult(markdown="\n".join(lines), data=data)


async def combat_calculator(
    attackers: list[str],
    blockers: list[str],
    *,
    rules: RulesService,
    bulk: ScryfallBulkClient | None = None,
    keywords: list[str] | None = None,
    response_format: ResponseFormat = "detailed",
) -> WorkflowResult:
    """Provide combat phase rules framework with card data.

    Looks up combat-related rules (section 5xx), resolves attacker/blocker
    cards via bulk data, and returns step-by-step combat phases with
    relevant rules.

    Args:
        attackers: Names of attacking creatures.
        blockers: Names of blocking creatures.
        rules: Initialized RulesService.
        bulk: Optional ScryfallBulkClient for card lookups.
        keywords: Optional specific keywords to look up rules for.
        response_format: ``"detailed"`` (default) or ``"concise"``.

    Returns:
        WorkflowResult with formatted markdown and structured data.
    """
    log.info(
        "combat_calculator.start",
        attackers=len(attackers),
        blockers=len(blockers),
    )
    fmt = _get_rule_formatter(response_format)

    # Look up combat rules
    combat_rules: list[Rule] = await rules.keyword_search("combat")

    # Look up keyword-specific rules
    keyword_rules: dict[str, list[Rule]] = {}
    if keywords:
        for kw in keywords:
            try:
                found = await rules.keyword_search(kw)
                if found:
                    keyword_rules[kw] = found
            except Exception:
                log.debug("combat_calculator.keyword_search_failed", keyword=kw)

    # Resolve cards via bulk data
    attacker_cards: dict[str, Card] = {}
    blocker_cards: dict[str, Card] = {}
    if bulk is not None:
        for names, target in [(attackers, attacker_cards), (blockers, blocker_cards)]:
            for name in names:
                try:
                    card = await bulk.get_card(name)
                    if card is not None:
                        target[name] = card
                except Exception:
                    log.debug("combat_calculator.bulk_failed", name=name)

    # Detect if first strike / double strike is relevant
    all_resolved = {**attacker_cards, **blocker_cards}
    has_first_strike = any(
        "First strike" in (c.keywords or []) or "Double strike" in (c.keywords or [])
        for c in all_resolved.values()
    )

    # Build markdown
    lines: list[str] = []
    lines.append("# Combat Calculator")
    lines.append("")

    # Attackers
    lines.append("## Attackers")
    lines.append("")
    if not attackers:
        lines.append("No attackers declared.")
    else:
        for name in attackers:
            card = attacker_cards.get(name)
            if card and card.power is not None and card.toughness is not None:
                kws = f" [{', '.join(card.keywords)}]" if card.keywords else ""
                lines.append(f"- **{name}** ({card.power}/{card.toughness}){kws}")
            else:
                lines.append(f"- **{name}**")
    lines.append("")

    # Blockers
    lines.append("## Blockers")
    lines.append("")
    if not blockers:
        lines.append("No blockers declared (unblocked combat).")
    else:
        for name in blockers:
            card = blocker_cards.get(name)
            if card and card.power is not None and card.toughness is not None:
                kws = f" [{', '.join(card.keywords)}]" if card.keywords else ""
                lines.append(f"- **{name}** ({card.power}/{card.toughness}){kws}")
            else:
                lines.append(f"- **{name}**")
    lines.append("")

    # Combat steps
    lines.append("## Combat Steps")
    lines.append("")
    lines.append("1. **Declare Attackers** -- Active player declares attackers")
    if blockers:
        lines.append("2. **Declare Blockers** -- Defending player assigns blockers")
    else:
        lines.append("2. **Declare Blockers** -- No blockers (unblocked)")

    if has_first_strike:
        lines.append("3. **First Strike Damage** -- First/double strike creatures deal damage")
        lines.append("4. **Regular Combat Damage** -- Remaining creatures deal damage")
        lines.append("5. **State-Based Actions** -- Check for lethal damage, destroy creatures")
    else:
        lines.append("3. **Combat Damage** -- All creatures deal damage simultaneously")
        lines.append("4. **State-Based Actions** -- Check for lethal damage, destroy creatures")
    lines.append("")

    # Combat rules
    if response_format == "detailed" and combat_rules:
        lines.append("## Relevant Combat Rules")
        lines.append("")
        for rule in combat_rules:
            lines.append(f"- {fmt(rule)}")
        lines.append("")

    # Keyword rules
    if keyword_rules:
        lines.append("## Keyword Rules")
        lines.append("")
        for kw, kw_rules in keyword_rules.items():
            if response_format == "detailed":
                lines.append(f"### {kw.title()}")
                lines.append("")
            for rule in kw_rules:
                lines.append(f"- {fmt(rule)}")
            lines.append("")

    # Build data
    data: dict = {
        "attackers": [
            {
                "name": name,
                "power": attacker_cards[name].power if name in attacker_cards else None,
                "toughness": attacker_cards[name].toughness if name in attacker_cards else None,
                "keywords": attacker_cards[name].keywords if name in attacker_cards else [],
            }
            for name in attackers
        ],
        "blockers": [
            {
                "name": name,
                "power": blocker_cards[name].power if name in blocker_cards else None,
                "toughness": blocker_cards[name].toughness if name in blocker_cards else None,
                "keywords": blocker_cards[name].keywords if name in blocker_cards else [],
            }
            for name in blockers
        ],
        "has_first_strike": has_first_strike,
        "combat_rules": [r.model_dump(mode="json") for r in combat_rules],
        "keyword_rules": {
            kw: [r.model_dump(mode="json") for r in kw_rules]
            for kw, kw_rules in keyword_rules.items()
        },
    }

    log.info(
        "combat_calculator.complete",
        attackers=len(attackers),
        blockers=len(blockers),
    )
    return WorkflowResult(markdown="\n".join(lines), data=data)
