"""Sideboard workflow functions — suggest, guide, and matrix for competitive sideboards.

These are pure async functions with no MCP awareness. They accept service
clients as keyword arguments and return ``WorkflowResult``. The workflow
server (``server.py``) registers them as MCP tools and handles ToolError
conversion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import structlog

from mtg_mcp_server.utils.decklist import parse_decklist
from mtg_mcp_server.workflows import WorkflowResult

if TYPE_CHECKING:
    from mtg_mcp_server.services.mtggoldfish import MTGGoldfishClient
    from mtg_mcp_server.services.scryfall_bulk import ScryfallBulkClient
    from mtg_mcp_server.types import Card

log = structlog.get_logger(service="workflow.sideboard")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALL_COLORS = frozenset({"W", "U", "B", "R", "G"})

# Default archetype categories used when MTGGoldfish is unavailable.
_DEFAULT_ARCHETYPES = ["Aggro", "Control", "Midrange", "Combo", "Tempo"]

# Maximum sideboard size for competitive formats.
_MAX_SIDEBOARD = 15

# ---------------------------------------------------------------------------
# Sideboard category definitions
# ---------------------------------------------------------------------------

SIDEBOARD_CATEGORIES: dict[str, dict[str, list[str]]] = {
    "Graveyard Hate": {
        "text_any": [
            "exile target card from a graveyard",
            "exile all cards from all graveyards",
            "exile all graveyards",
        ],
    },
    "Artifact Removal": {
        "text_any": [
            "destroy target artifact",
            "destroy all artifacts",
            "exile target artifact",
        ],
    },
    "Enchantment Removal": {
        "text_any": [
            "destroy target enchantment",
            "destroy all enchantments",
            "exile target enchantment",
        ],
    },
    "Counterspells": {
        "text_any": [
            "counter target spell",
            "counter target noncreature",
        ],
    },
    "Board Wipes": {
        "text_any": [
            "destroy all creatures",
            "all creatures get -",
            "exile all creatures",
        ],
    },
    "Direct Damage": {
        "text_any": [
            "damage to any target",
            "damage to each opponent",
        ],
    },
    "Lifegain Hate": {
        "text_any": [
            "can't gain life",
            "damage can't be prevented",
        ],
    },
}

# ---------------------------------------------------------------------------
# Archetype strategy mapping for sideboard guide
# ---------------------------------------------------------------------------

# Maps archetype style keywords to sideboard strategy advice.
_ARCHETYPE_STRATEGIES: dict[str, dict[str, list[str] | str]] = {
    "aggro": {
        "cut_types": ["sorcery", "enchantment"],
        "cut_cmc_above": [],  # Handled via cmc heuristic
        "bring_categories": ["Board Wipes", "Lifegain Hate", "Direct Damage"],
        "cut_reasoning": "Slow/expensive cards are liabilities against aggressive strategies",
        "bring_reasoning": "Sweepers and lifegain stabilize against fast creature decks",
    },
    "control": {
        "cut_types": [],
        "cut_cmc_above": [],
        "bring_categories": ["Counterspells", "Direct Damage"],
        "cut_reasoning": "Removal spells have fewer targets against control",
        "bring_reasoning": "Threats and disruption pressure control's answers",
    },
    "midrange": {
        "cut_types": [],
        "cut_cmc_above": [],
        "bring_categories": ["Graveyard Hate", "Board Wipes"],
        "cut_reasoning": "Narrow interaction is less effective against versatile threats",
        "bring_reasoning": "Hate pieces and sweepers break midrange value engines",
    },
    "combo": {
        "cut_types": ["creature"],
        "cut_cmc_above": [],
        "bring_categories": ["Counterspells", "Graveyard Hate"],
        "cut_reasoning": "Creature removal is dead against spell-based combo",
        "bring_reasoning": "Disruption and hate pieces interact with combo's game plan",
    },
    "tempo": {
        "cut_types": [],
        "cut_cmc_above": [],
        "bring_categories": ["Board Wipes", "Direct Damage"],
        "cut_reasoning": "Slow cards get punished by tempo's efficiency",
        "bring_reasoning": "Sweepers and removal catch up against tempo's early pressure",
    },
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _extract_deck_colors(resolved: dict[str, Card | None]) -> set[str]:
    """Extract the set of colors present in the main deck from resolved cards."""
    colors: set[str] = set()
    for card in resolved.values():
        if card is not None:
            colors.update(card.colors)
    return colors


def _opposing_colors(deck_colors: set[str]) -> frozenset[str] | set[str]:
    """Return colors not in the deck's color set."""
    return ALL_COLORS - deck_colors


def _match_archetype_name(query: str, archetypes: list[str], threshold: float = 0.5) -> str | None:
    """Simple substring-based archetype matching.

    Returns the first archetype whose name contains the query (case-insensitive),
    or the query if it matches a known strategy keyword.
    """
    query_lower = query.lower().strip()
    if not query_lower:
        return None

    # Direct match against archetype list
    for arch in archetypes:
        if query_lower in arch.lower() or arch.lower() in query_lower:
            return arch

    # Check if query matches a strategy keyword
    for keyword in _ARCHETYPE_STRATEGIES:
        if keyword in query_lower or query_lower in keyword:
            return query

    return query  # Return as-is for custom matchup names


def _classify_archetype_strategy(matchup: str) -> str:
    """Classify a matchup name into a broad strategy category.

    Returns one of: "aggro", "control", "midrange", "combo", "tempo".
    Defaults to "midrange" for unknown archetypes.
    """
    matchup_lower = matchup.lower()

    strategy_keywords: dict[str, list[str]] = {
        "aggro": ["aggro", "burn", "red deck", "mono-red", "mono red", "sligh", "zoo", "prowess"],
        "control": ["control", "draw-go", "uw", "azorius", "esper"],
        "combo": ["combo", "storm", "through the breach", "scapeshift", "living end", "tron"],
        "tempo": ["tempo", "delver", "murktide", "faeries"],
        "midrange": ["midrange", "jund", "energy", "rock", "abzan", "shadow"],
    }

    for strategy, keywords in strategy_keywords.items():
        for kw in keywords:
            if kw in matchup_lower:
                return strategy

    return "midrange"  # Default


def _card_addresses_matchup(card: Card | None, matchup_strategy: str) -> str:
    """Determine if a sideboard card addresses a given matchup strategy.

    Returns "IN", "OUT", or "FLEX".
    """
    if card is None:
        return "FLEX"

    oracle = (card.oracle_text or "").lower()
    type_line = card.type_line.lower()
    strategy = _ARCHETYPE_STRATEGIES.get(matchup_strategy, {})
    bring_categories = strategy.get("bring_categories", [])

    # Check if the card's text matches any of the bring categories
    for category_name in bring_categories:
        category_def = SIDEBOARD_CATEGORIES.get(category_name, {})
        text_patterns = category_def.get("text_any", [])
        for pattern in text_patterns:
            if pattern.lower() in oracle:
                return "IN"

    # Check cut types -- if the card IS one of the types to cut, it's OUT
    cut_types = strategy.get("cut_types", [])
    for ct in cut_types:
        if ct in type_line:
            return "OUT"

    return "FLEX"


def _is_sb_card_relevant(card: Card | None, category_texts: list[str]) -> bool:
    """Check if a card's oracle text matches any sideboard category text patterns."""
    if card is None:
        return False
    oracle = (card.oracle_text or "").lower()
    return any(pattern.lower() in oracle for pattern in category_texts)


# ---------------------------------------------------------------------------
# 1. suggest_sideboard
# ---------------------------------------------------------------------------


async def suggest_sideboard(
    decklist: list[str],
    format: str,
    *,
    bulk: ScryfallBulkClient,
    mtggoldfish: MTGGoldfishClient | None = None,
    meta_context: str | None = None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Suggest a 15-card sideboard for a competitive deck.

    Uses bulk data to find sideboard candidates by category (graveyard hate,
    artifact removal, counterspells, etc.). Optionally enriches with MTGGoldfish
    format staples to boost popular sideboard cards.

    Args:
        decklist: Main deck card list (e.g. ``["4x Lightning Bolt", ...]``).
        format: Format name (e.g. ``"modern"``, ``"legacy"``).
        bulk: ScryfallBulkClient for card lookup and filtering.
        mtggoldfish: Optional MTGGoldfishClient for format staple data.
        meta_context: Optional metagame context string for prioritization.
        response_format: ``"detailed"`` or ``"concise"``.

    Returns:
        WorkflowResult with markdown and structured data.
    """
    if not decklist:
        return WorkflowResult(
            markdown=f"# Sideboard Suggestions for {format.title()}\n\nNo main deck cards provided.",
            data={"format": format, "categories": {}, "suggested_cards": [], "total_cards": 0},
        )

    # Parse decklist to get card names
    parsed = parse_decklist(decklist)
    card_names = [name for _qty, name in parsed]

    if not card_names:
        return WorkflowResult(
            markdown=f"# Sideboard Suggestions for {format.title()}\n\nCould not parse any card names from the decklist.",
            data={"format": format, "categories": {}, "suggested_cards": [], "total_cards": 0},
        )

    # Resolve main deck cards
    resolved = await bulk.get_cards(card_names)
    deck_colors = _extract_deck_colors(resolved)
    main_deck_lower = {name.lower() for name in card_names}

    log.debug(
        "suggest_sideboard.resolved",
        deck_colors=sorted(deck_colors),
        resolved_count=sum(1 for v in resolved.values() if v is not None),
    )

    # Fetch format staples if MTGGoldfish available
    staple_names: set[str] = set()
    if mtggoldfish is not None:
        try:
            staples = await mtggoldfish.get_format_staples(format.lower(), limit=50)
            staple_names = {s.name.lower() for s in staples}
            log.debug("suggest_sideboard.staples_loaded", count=len(staple_names))
        except Exception:
            log.warning("suggest_sideboard.mtggoldfish_failed", exc_info=True)

    # Parse meta_context for category prioritization
    priority_categories: list[str] = []
    if meta_context:
        meta_lower = meta_context.lower()
        for cat_name in SIDEBOARD_CATEGORIES:
            # Boost categories mentioned in context
            if any(word in meta_lower for word in cat_name.lower().split()):
                priority_categories.append(cat_name)

        # Check for strategy hints
        if any(kw in meta_lower for kw in ["aggro", "burn", "mono-red", "red deck"]):
            if "Board Wipes" not in priority_categories:
                priority_categories.append("Board Wipes")
            if "Lifegain Hate" not in priority_categories:
                priority_categories.append("Lifegain Hate")
        if (
            any(kw in meta_lower for kw in ["graveyard", "reanimator", "dredge"])
            and "Graveyard Hate" not in priority_categories
        ):
            priority_categories.append("Graveyard Hate")
        if (
            any(kw in meta_lower for kw in ["combo", "storm"])
            and "Counterspells" not in priority_categories
        ):
            priority_categories.append("Counterspells")

    # Build candidates per category
    categories_result: dict[str, list[dict[str, str]]] = {}
    all_suggested: list[dict[str, str]] = []
    seen_names: set[str] = set()  # Deduplicate across categories

    # Process categories -- priority ones first, then the rest
    ordered_categories = list(SIDEBOARD_CATEGORIES.keys())
    if priority_categories:
        ordered_categories = priority_categories + [
            c for c in ordered_categories if c not in priority_categories
        ]

    # Cards per category: distribute across categories
    slots_per_category = max(1, _MAX_SIDEBOARD // max(len(ordered_categories), 1))

    for cat_name in ordered_categories:
        if len(all_suggested) >= _MAX_SIDEBOARD:
            break

        cat_def = SIDEBOARD_CATEGORIES.get(cat_name, {})
        if not cat_def:
            continue

        # Build filter args
        text_any: list[str] | None = cat_def.get("text_any")  # type: ignore[assignment]

        try:
            candidates = await bulk.filter_cards(
                format=format.lower(),
                limit=10,
                text_any=text_any,
            )
        except Exception:
            log.warning("suggest_sideboard.filter_failed", category=cat_name, exc_info=True)
            continue

        # Filter out main deck cards and already-suggested cards
        cat_cards: list[dict[str, str]] = []
        for card in candidates:
            if card.name.lower() in main_deck_lower:
                continue
            if card.name.lower() in seen_names:
                continue
            if len(cat_cards) >= slots_per_category:
                break
            if len(all_suggested) + len(cat_cards) >= _MAX_SIDEBOARD:
                break

            # Compute reasoning
            reasons = []
            if card.name.lower() in staple_names:
                reasons.append("format staple")
            reasons.append(f"addresses {cat_name.lower()}")
            if card.prices.usd is not None:
                reasons.append(f"${card.prices.usd}")

            entry = {
                "name": card.name,
                "category": cat_name,
                "reasoning": "; ".join(reasons),
                "type_line": card.type_line,
                "mana_cost": card.mana_cost or "",
            }
            cat_cards.append(entry)
            seen_names.add(card.name.lower())

        if cat_cards:
            categories_result[cat_name] = cat_cards
            all_suggested.extend(cat_cards)

    # Add Color Hosers dynamically based on opposing colors
    if len(all_suggested) < _MAX_SIDEBOARD:
        opposing = _opposing_colors(deck_colors)
        if opposing:
            # Search for "protection from {color}" or anti-color effects
            color_names = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}
            hoser_patterns = []
            for c in opposing:
                cname = color_names.get(c, "")
                if cname:
                    hoser_patterns.append(f"protection from {cname}")

            if hoser_patterns:
                try:
                    hosers = await bulk.filter_cards(
                        format=format.lower(),
                        text_any=hoser_patterns,
                        limit=5,
                    )
                    hoser_cards: list[dict[str, str]] = []
                    for card in hosers:
                        if card.name.lower() in main_deck_lower:
                            continue
                        if card.name.lower() in seen_names:
                            continue
                        if len(all_suggested) + len(hoser_cards) >= _MAX_SIDEBOARD:
                            break

                        entry = {
                            "name": card.name,
                            "category": "Color Hosers",
                            "reasoning": f"hoses opposing colors ({', '.join(sorted(opposing))})",
                            "type_line": card.type_line,
                            "mana_cost": card.mana_cost or "",
                        }
                        hoser_cards.append(entry)
                        seen_names.add(card.name.lower())

                    if hoser_cards:
                        categories_result["Color Hosers"] = hoser_cards
                        all_suggested.extend(hoser_cards)
                except Exception:
                    log.warning("suggest_sideboard.hoser_search_failed", exc_info=True)

    # Format output
    markdown = _format_suggest_sideboard(
        format, categories_result, all_suggested, staple_names, response_format
    )
    data: dict[str, object] = {
        "format": format,
        "categories": {k: [c["name"] for c in v] for k, v in categories_result.items()},
        "suggested_cards": all_suggested,
        "total_cards": len(all_suggested),
    }

    return WorkflowResult(markdown=markdown, data=data)


def _format_suggest_sideboard(
    format: str,
    categories: dict[str, list[dict[str, str]]],
    all_suggested: list[dict[str, str]],
    staple_names: set[str],
    response_format: Literal["detailed", "concise"],
) -> str:
    """Format suggest_sideboard results as markdown."""
    lines: list[str] = [f"# Sideboard Suggestions for {format.title()}", ""]

    if response_format != "concise":
        lines.append(f"**Total Cards:** {len(all_suggested)} / {_MAX_SIDEBOARD}")
        lines.append("")

    for cat_name, cards in categories.items():
        lines.append(f"### {cat_name}")
        for card in cards:
            marker = " *" if card["name"].lower() in staple_names else ""
            if response_format == "concise":
                lines.append(f"- {card['name']}{marker}")
            else:
                lines.append(
                    f"- **{card['name']}** ({card['mana_cost']}) -- {card['reasoning']}{marker}"
                )
        lines.append("")

    if response_format != "concise" and staple_names:
        lines.append("*\\* = format staple (MTGGoldfish)*")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 2. sideboard_guide
# ---------------------------------------------------------------------------


async def sideboard_guide(
    decklist: list[str],
    sideboard: list[str],
    format: str,
    matchup: str,
    *,
    bulk: ScryfallBulkClient,
    mtggoldfish: MTGGoldfishClient | None = None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Produce an IN/OUT sideboard plan for a specific matchup.

    Analyzes the main deck and sideboard against a named matchup, determining
    which cards to board in and which to cut.

    Args:
        decklist: Main deck card list.
        sideboard: Sideboard card list.
        format: Format name.
        matchup: Matchup archetype name (e.g. ``"Mono-Red Aggro"``).
        bulk: ScryfallBulkClient for card lookup.
        mtggoldfish: Optional MTGGoldfishClient for archetype matching.
        response_format: ``"detailed"`` or ``"concise"``.

    Returns:
        WorkflowResult with IN/OUT plan and reasoning.
    """
    if not decklist or not sideboard:
        return WorkflowResult(
            markdown=f"# Sideboard Guide vs {matchup}\n\nBoth a main deck and sideboard are required.",
            data={
                "matchup": matchup,
                "ins": [],
                "outs": [],
                "reasoning": "Missing decklist or sideboard",
            },
        )

    # Parse both lists
    main_parsed = parse_decklist(decklist)
    sb_parsed = parse_decklist(sideboard)
    main_names = [name for _qty, name in main_parsed]
    sb_names = [name for _qty, name in sb_parsed]
    main_qty = {name: qty for qty, name in main_parsed}
    sb_qty = {name: qty for qty, name in sb_parsed}

    if not main_names or not sb_names:
        return WorkflowResult(
            markdown=f"# Sideboard Guide vs {matchup}\n\nCould not parse card names.",
            data={"matchup": matchup, "ins": [], "outs": [], "reasoning": "Parse error"},
        )

    # Resolve all cards
    all_names = list(set(main_names + sb_names))
    resolved = await bulk.get_cards(all_names)

    # Match the archetype
    known_archetypes = list(_DEFAULT_ARCHETYPES)
    if mtggoldfish is not None:
        try:
            meta = await mtggoldfish.get_metagame(format.lower())
            known_archetypes = (
                [a.name for a in meta.archetypes] if meta.archetypes else known_archetypes
            )
        except Exception:
            log.warning("sideboard_guide.mtggoldfish_failed", exc_info=True)

    matched_name = _match_archetype_name(matchup, known_archetypes) or matchup
    strategy = _classify_archetype_strategy(matched_name)

    log.debug(
        "sideboard_guide.classified",
        matchup=matchup,
        matched=matched_name,
        strategy=strategy,
    )

    strategy_info = _ARCHETYPE_STRATEGIES.get(strategy, _ARCHETYPE_STRATEGIES["midrange"])

    # Determine INs -- which sideboard cards address the matchup
    ins: list[dict[str, str | int]] = []
    for name in sb_names:
        card = resolved.get(name)
        verdict = _card_addresses_matchup(card, strategy)
        if verdict == "IN":
            ins.append(
                {
                    "name": name,
                    "quantity": sb_qty.get(name, 1),
                    "reasoning": _explain_in(card, strategy),
                }
            )
        elif verdict == "FLEX":
            # Include FLEX cards if we have room
            ins.append(
                {
                    "name": name,
                    "quantity": sb_qty.get(name, 1),
                    "reasoning": "Flexible option -- may be useful depending on opponent's build",
                }
            )

    # Determine OUTs -- which main deck cards are weak against this matchup
    outs: list[dict[str, str | int]] = []
    cut_types = strategy_info.get("cut_types", [])
    for name in main_names:
        card = resolved.get(name)
        if card is None:
            continue

        type_line_lower = card.type_line.lower()
        cmc = card.cmc

        should_cut = False
        cut_reason = ""

        # Check if card type is weak against this matchup
        for ct in cut_types:
            if ct in type_line_lower:
                should_cut = True
                cut_reason = f"{card.type_line} -- weak against {strategy}"
                break

        # Against aggro: cut expensive cards (cmc >= 5)
        if not should_cut and strategy == "aggro" and cmc >= 5:
            should_cut = True
            cut_reason = f"CMC {cmc:.0f} -- too slow against aggro"

        # Against control: cut creature removal
        if not should_cut and strategy == "control":
            oracle = (card.oracle_text or "").lower()
            if any(
                p in oracle
                for p in [
                    "destroy target creature",
                    "exile target creature",
                    "damage to target creature",
                ]
            ):
                should_cut = True
                cut_reason = "Creature removal -- fewer targets against control"

        if should_cut:
            outs.append(
                {
                    "name": name,
                    "quantity": main_qty.get(name, 1),
                    "reasoning": cut_reason,
                }
            )

    # Balance ins/outs -- can't board in more than we board out
    total_in = sum(int(i.get("quantity", 1)) for i in ins)
    total_out = sum(int(o.get("quantity", 1)) for o in outs)

    # If more INs than OUTs, trim INs to match
    if total_in > total_out and outs:
        trimmed_ins: list[dict[str, str | int]] = []
        running = 0
        for i in ins:
            qty = int(i.get("quantity", 1))
            if running + qty <= total_out:
                trimmed_ins.append(i)
                running += qty
            elif running < total_out:
                remaining = total_out - running
                trimmed_ins.append({**i, "quantity": remaining})
                running += remaining
                break
        ins = trimmed_ins
    elif total_out > total_in and ins:
        trimmed_outs: list[dict[str, str | int]] = []
        running = 0
        for o in outs:
            qty = int(o.get("quantity", 1))
            if running + qty <= total_in:
                trimmed_outs.append(o)
                running += qty
            elif running < total_in:
                remaining = total_in - running
                trimmed_outs.append({**o, "quantity": remaining})
                running += remaining
                break
        outs = trimmed_outs

    overall_reasoning = strategy_info.get("bring_reasoning", "Adjust for the matchup")
    cut_reasoning = strategy_info.get("cut_reasoning", "Trim underperformers")
    combined_reasoning = f"IN: {overall_reasoning}. OUT: {cut_reasoning}."

    # Format
    markdown = _format_sideboard_guide(matched_name, ins, outs, combined_reasoning, response_format)
    data: dict[str, object] = {
        "matchup": matched_name,
        "strategy": strategy,
        "ins": [{"name": i["name"], "quantity": i["quantity"]} for i in ins],
        "outs": [{"name": o["name"], "quantity": o["quantity"]} for o in outs],
        "reasoning": combined_reasoning,
    }

    return WorkflowResult(markdown=markdown, data=data)


def _explain_in(card: Card | None, strategy: str) -> str:
    """Build a reasoning string for bringing a sideboard card in."""
    if card is None:
        return "Unknown card"
    oracle = (card.oracle_text or "").lower()

    for cat_name, cat_def in SIDEBOARD_CATEGORIES.items():
        text_patterns = cat_def.get("text_any", [])
        for pattern in text_patterns:
            if pattern.lower() in oracle:
                return f"{cat_name} -- effective against {strategy}"

    return f"General utility against {strategy}"


def _format_sideboard_guide(
    matchup: str,
    ins: list[dict[str, str | int]],
    outs: list[dict[str, str | int]],
    reasoning: str,
    response_format: Literal["detailed", "concise"],
) -> str:
    """Format sideboard guide results as markdown."""
    lines: list[str] = [f"### vs {matchup}", ""]

    if ins:
        lines.append("**IN:**")
        for card in ins:
            qty = card.get("quantity", 1)
            if response_format == "concise":
                lines.append(f"+ {qty} {card['name']}")
            else:
                lines.append(f"+ {qty} {card['name']} -- {card.get('reasoning', '')}")
        lines.append("")

    if outs:
        lines.append("**OUT:**")
        for card in outs:
            qty = card.get("quantity", 1)
            if response_format == "concise":
                lines.append(f"- {qty} {card['name']}")
            else:
                lines.append(f"- {qty} {card['name']} -- {card.get('reasoning', '')}")
        lines.append("")

    if not ins and not outs:
        lines.append("No clear sideboard changes for this matchup.")
        lines.append("")

    if response_format != "concise":
        lines.append(f"**Reasoning:** {reasoning}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3. sideboard_matrix
# ---------------------------------------------------------------------------


async def sideboard_matrix(
    decklist: list[str],
    sideboard: list[str],
    format: str,
    *,
    bulk: ScryfallBulkClient,
    mtggoldfish: MTGGoldfishClient | None = None,
    matchups: list[str] | None = None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Build a sideboard matrix: cards as rows, matchups as columns, cells = IN/OUT/FLEX.

    Args:
        decklist: Main deck card list.
        sideboard: Sideboard card list.
        format: Format name.
        bulk: ScryfallBulkClient for card lookup.
        mtggoldfish: Optional MTGGoldfishClient for metagame archetypes.
        matchups: Optional explicit matchup names. If not provided, uses
                  MTGGoldfish top archetypes or asks user to provide names.
        response_format: ``"detailed"`` or ``"concise"``.

    Returns:
        WorkflowResult with matrix table and structured data.
    """
    # Determine matchup list
    matchup_names: list[str] = []
    if matchups:
        matchup_names = matchups
    elif mtggoldfish is not None:
        try:
            meta = await mtggoldfish.get_metagame(format.lower())
            if meta.archetypes:
                matchup_names = [a.name for a in meta.archetypes[:6]]
        except Exception:
            log.warning("sideboard_matrix.mtggoldfish_failed", exc_info=True)

    if not matchup_names:
        return WorkflowResult(
            markdown=(
                f"# Sideboard Matrix for {format.title()}\n\n"
                "No matchups available. Please provide matchup names via the `matchups` parameter, "
                "or enable MTGGoldfish for automatic metagame detection."
            ),
            data={"format": format, "matchups": [], "matrix": {}, "error": "no_matchups"},
        )

    if not sideboard:
        return WorkflowResult(
            markdown=f"# Sideboard Matrix for {format.title()}\n\nNo sideboard cards provided.",
            data={"format": format, "matchups": matchup_names, "matrix": {}},
        )

    # Parse sideboard
    sb_parsed = parse_decklist(sideboard)
    sb_names = [name for _qty, name in sb_parsed]

    if not sb_names:
        return WorkflowResult(
            markdown=f"# Sideboard Matrix for {format.title()}\n\nCould not parse sideboard card names.",
            data={"format": format, "matchups": matchup_names, "matrix": {}},
        )

    # Resolve sideboard cards
    resolved = await bulk.get_cards(sb_names)

    # Build matrix
    matrix: dict[str, dict[str, str]] = {}
    for name in sb_names:
        card = resolved.get(name)
        row: dict[str, str] = {}
        for mu in matchup_names:
            strategy = _classify_archetype_strategy(mu)
            verdict = _card_addresses_matchup(card, strategy)
            row[mu] = verdict
        matrix[name] = row

    # Format
    markdown = _format_sideboard_matrix(format, sb_names, matchup_names, matrix, response_format)
    data: dict[str, object] = {
        "format": format,
        "matchups": matchup_names,
        "matrix": matrix,
    }

    return WorkflowResult(markdown=markdown, data=data)


def _format_sideboard_matrix(
    format: str,
    sb_names: list[str],
    matchup_names: list[str],
    matrix: dict[str, dict[str, str]],
    response_format: Literal["detailed", "concise"],
) -> str:
    """Format sideboard matrix as a markdown table."""
    lines: list[str] = [f"# Sideboard Matrix for {format.title()}", ""]

    # Abbreviate matchup names for column headers (use first word if too long)
    headers = []
    for mu in matchup_names:
        if len(mu) > 15:
            # Take first two words
            parts = mu.split()
            headers.append(" ".join(parts[:2]) if len(parts) > 1 else parts[0])
        else:
            headers.append(mu)

    # Table header
    header_row = "| Card | " + " | ".join(headers) + " |"
    separator = "|------|" + "|".join(["------" for _ in headers]) + "|"
    lines.append(header_row)
    lines.append(separator)

    # Table rows
    for name in sb_names:
        row_cells = []
        for mu in matchup_names:
            cell = matrix.get(name, {}).get(mu, "FLEX")
            row_cells.append(cell)
        lines.append(f"| {name} | " + " | ".join(row_cells) + " |")

    lines.append("")

    if response_format != "concise":
        lines.append("**Legend:** IN = bring in, OUT = do not bring in, FLEX = context-dependent")
        lines.append("")

    return "\n".join(lines)
