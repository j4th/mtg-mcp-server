"""Deck building workflow functions — theme search, build-around, and deck completion.

These are pure async functions with no MCP awareness. They accept service
clients as keyword arguments and return ``WorkflowResult``. The workflow
server (``server.py``) registers them as MCP tools and handles ToolError
conversion.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Literal

import structlog

from mtg_mcp_server.utils.color_identity import parse_color_identity
from mtg_mcp_server.workflows import WorkflowResult

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mtg_mcp_server.services.scryfall_bulk import ScryfallBulkClient
    from mtg_mcp_server.services.spellbook import SpellbookClient
    from mtg_mcp_server.types import Card, Combo

log = structlog.get_logger(service="workflow.building")

# ---------------------------------------------------------------------------
# Theme mappings: mechanical, tribal, and abstract themes
# ---------------------------------------------------------------------------

# Mechanical themes: map to oracle-text search patterns (AND/OR groups).
# Each entry is (text_any, text_contains) where text_any uses OR and
# text_contains uses AND semantics.
THEME_MAPPINGS: dict[str, dict[str, list[str] | str | None]] = {
    "aristocrats": {
        "text_any": [
            "whenever a creature dies",
            "whenever another creature dies",
            "sacrifice a creature",
            "when this creature dies",
        ],
    },
    "voltron": {
        "text_any": [
            "equipped creature",
            "enchanted creature gets",
            "attach",
            "equip",
            "aura",
        ],
    },
    "tokens": {
        "text_any": [
            "create",
        ],
        "text_contains": ["token"],
    },
    "reanimator": {
        "text_any": [
            "return",
        ],
        "text_contains": ["graveyard", "battlefield"],
    },
    "storm": {
        "text_any": [
            "storm",
            "whenever you cast",
            "magecraft",
            "cast an instant or sorcery",
        ],
    },
    "stax": {
        "text_any": [
            "can't",
            "don't untap",
            "each upkeep",
            "opponents can't",
        ],
    },
    "blink": {
        "text_any": [
            "exile",
        ],
        "text_contains": ["return", "battlefield"],
    },
    "mill": {
        "text_any": [
            "mill",
            "put the top",
            "cards from the top of",
        ],
    },
    "landfall": {
        "text_any": [
            "landfall",
            "whenever a land enters",
            "whenever you play a land",
        ],
    },
    "spellslinger": {
        "text_any": [
            "whenever you cast an instant or sorcery",
            "magecraft",
            "instant or sorcery",
            "prowess",
        ],
    },
    "sacrifice": {
        "text_any": [
            "sacrifice a creature",
            "sacrifice a permanent",
            "sacrifice another",
            "whenever you sacrifice",
            "whenever a creature you control dies",
        ],
    },
    "lifegain": {
        "text_any": [
            "you gain life",
            "whenever you gain life",
            "lifelink",
            "pay life",
        ],
    },
    "ramp": {
        "text_any": [
            "search your library for a basic land",
            "add one mana of any color",
            "add {C}",
            "add {G}",
            "search your library for a land card",
        ],
    },
    "draw": {
        "text_any": [
            "draw a card",
            "draw two cards",
            "draw cards",
            "whenever you draw",
        ],
    },
    "discard": {
        "text_any": [
            "discard a card",
            "each opponent discards",
            "whenever a player discards",
            "discard their hand",
        ],
    },
    "counters": {
        "text_any": [
            "+1/+1 counter",
            "proliferate",
            "whenever a counter",
            "put a counter",
        ],
    },
    "removal": {
        "text_any": [
            "destroy target",
            "exile target",
            "deals damage to target",
            "target creature gets -",
        ],
    },
}

# Aliases: common synonyms that map to canonical theme keys above.
THEME_ALIASES: dict[str, str] = {
    "sac": "sacrifice",
    "aristocrat": "aristocrats",
    "dies": "aristocrats",
    "death triggers": "aristocrats",
    "flicker": "blink",
    "bounce": "blink",
    "life gain": "lifegain",
    "life": "lifegain",
    "card draw": "draw",
    "cantrip": "draw",
    "mana ramp": "ramp",
    "acceleration": "ramp",
    "land ramp": "ramp",
    "graveyard": "reanimator",
    "recursion": "reanimator",
    "burn": "removal",
    "+1/+1": "counters",
    "+1/+1 counters": "counters",
    "proliferate": "counters",
    "spells": "spellslinger",
    "spellslinger": "spellslinger",
    "control": "stax",
    "tax": "stax",
    "go wide": "tokens",
    "token": "tokens",
}

# Abstract themes: search by card name and oracle text synonyms.
ABSTRACT_THEMES: dict[str, list[str]] = {
    "music": ["song", "sing", "melody", "bard", "perform", "hymn", "choir", "tune"],
    "death": ["die", "dies", "destroy", "graveyard", "kill", "death", "dead", "perish"],
    "ocean": ["sea", "island", "fish", "merfolk", "whale", "tide", "ocean", "deep"],
    "fire": ["fire", "burn", "flame", "blaze", "inferno", "ember", "scorch"],
    "nature": ["forest", "growth", "bloom", "wild", "beast", "primal", "verdant"],
    "darkness": ["dark", "shadow", "night", "void", "abyss", "doom", "dread"],
    "light": ["light", "dawn", "radiant", "holy", "divine", "celestial", "angel"],
}


def _fmt_card_line(card: Card) -> str:
    """Format a single card as a markdown line."""
    cost = card.mana_cost or ""
    price = f"${card.prices.usd}" if card.prices.usd is not None else ""
    return f"- **{card.name}** {cost} -- {card.type_line}" + (f" ({price})" if price else "")


def _fmt_card_concise(card: Card) -> str:
    """Format a card as a concise one-liner."""
    cost = card.mana_cost or ""
    return f"- {card.name} {cost}"


# ---------------------------------------------------------------------------
# theme_search
# ---------------------------------------------------------------------------


async def theme_search(
    theme: str,
    *,
    bulk: ScryfallBulkClient,
    color_identity: str | None = None,
    format: str | None = None,
    max_price: float | None = None,
    limit: int = 20,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Find cards matching a theme -- mechanical, tribal, or abstract.

    Searches bulk data using oracle text patterns for mechanical themes,
    type line for tribal themes, and name/text for abstract themes.

    Args:
        theme: Theme name (e.g. 'aristocrats', 'merfolk', 'music').
        bulk: Initialized ScryfallBulkClient.
        color_identity: Color filter (e.g. 'BG', 'sultai').
        format: Format legality filter (e.g. 'commander').
        max_price: Maximum USD price per card.
        limit: Maximum results.
        response_format: Output verbosity.

    Returns:
        WorkflowResult with themed cards and structured data.
    """
    log.info("theme_search.start", theme=theme)

    theme_lower = theme.lower().strip()
    # Resolve aliases to canonical theme keys
    theme_lower = THEME_ALIASES.get(theme_lower, theme_lower)
    ci_filter: frozenset[str] | None = None
    if color_identity:
        try:
            ci_filter = parse_color_identity(color_identity)
        except ValueError:
            return WorkflowResult(
                markdown=f"Unrecognized color identity: '{color_identity}'. "
                "Try names like 'sultai' or letter codes like 'BUG'.",
                data={"theme": theme, "error": f"Invalid color identity: {color_identity}"},
            )

    cards: list[Card] = []

    if theme_lower in THEME_MAPPINGS:
        # Mechanical theme -- use text_any / text_contains from mapping
        mapping = THEME_MAPPINGS[theme_lower]
        raw_any = mapping.get("text_any")
        raw_contains = mapping.get("text_contains")
        text_any_list: list[str] | None = raw_any if isinstance(raw_any, list) else None
        if isinstance(raw_contains, list):
            text_contains_list: list[str] | None = raw_contains
        elif isinstance(raw_contains, str):
            text_contains_list = [raw_contains]
        else:
            text_contains_list = None
        cards = await bulk.filter_cards(
            text_any=text_any_list,
            text_contains=text_contains_list,
            color_identity=ci_filter,
            format=format,
            max_price=max_price,
            limit=limit,
        )
    elif theme_lower in ABSTRACT_THEMES:
        # Abstract theme -- search name and text for synonyms
        cards = await bulk.filter_cards(
            text_any=ABSTRACT_THEMES[theme_lower],
            color_identity=ci_filter,
            format=format,
            max_price=max_price,
            limit=limit,
        )
    else:
        # Assume tribal or unknown -- try type line first, then text search
        cards = await bulk.filter_cards(
            type_contains=[theme_lower],
            color_identity=ci_filter,
            format=format,
            max_price=max_price,
            limit=limit,
        )

        if not cards:
            # Fall back to oracle text search (no name_contains — AND with
            # text_any causes false negatives, returning only literal name matches)
            cards = await bulk.filter_cards(
                text_any=[theme_lower],
                color_identity=ci_filter,
                format=format,
                max_price=max_price,
                limit=limit,
            )

    # Build output
    total = len(cards)
    lines: list[str] = []

    if response_format == "concise":
        lines.append(f"# Theme: {theme} ({total} cards)")
        lines.append("")
        for card in cards[:limit]:
            lines.append(_fmt_card_concise(card))
    else:
        lines.append(f"# Theme Search: {theme}")
        lines.append("")
        if ci_filter:
            lines.append(f"**Color identity:** {', '.join(sorted(ci_filter))}")
        if format:
            lines.append(f"**Format:** {format}")
        if max_price is not None:
            lines.append(f"**Max price:** ${max_price:.2f}")
        lines.append(f"**Found:** {total} cards")
        lines.append("")

        if not cards:
            lines.append("No cards found matching this theme.")
        else:
            for card in cards[:limit]:
                lines.append(_fmt_card_line(card))

    log.info("theme_search.complete", theme=theme, found=total)
    data: dict[str, object] = {
        "theme": theme_lower,
        "total_found": total,
        "cards": [
            {
                "name": c.name,
                "mana_cost": c.mana_cost,
                "type_line": c.type_line,
                "price_usd": c.prices.usd,
            }
            for c in cards[:limit]
        ],
    }
    return WorkflowResult(markdown="\n".join(lines), data=data)


# ---------------------------------------------------------------------------
# build_around
# ---------------------------------------------------------------------------


def _extract_keywords_from_text(oracle_text: str) -> list[str]:
    """Extract mechanical keywords from oracle text for synergy search."""
    keywords: list[str] = []
    text_lower = oracle_text.lower()

    # Common mechanical patterns
    patterns = [
        ("sacrifice", "sacrifice"),
        ("dies", "dies"),
        ("graveyard", "graveyard"),
        ("exile", "exile"),
        ("token", "token"),
        ("counter", "counter"),
        ("draw", "draw"),
        ("discard", "discard"),
        ("destroy", "destroy"),
        ("return", "return"),
        ("untap", "untap"),
        ("life", "life"),
        ("damage", "damage"),
        ("mill", "mill"),
        ("scry", "scry"),
        ("flying", "flying"),
        ("trample", "trample"),
    ]
    for pattern, keyword in patterns:
        if pattern in text_lower:
            keywords.append(keyword)

    return keywords


async def build_around(
    cards: list[str],
    format: str,
    *,
    bulk: ScryfallBulkClient,
    spellbook: SpellbookClient,
    budget: float | None = None,
    limit: int = 20,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Find synergistic cards for 1-5 build-around pieces.

    Resolves build-around cards, parses their mechanics, searches for
    synergistic cards, and checks for combos.

    Args:
        cards: Build-around card names (1-5).
        format: Format for legality filtering.
        bulk: Initialized ScryfallBulkClient.
        spellbook: Initialized SpellbookClient.
        budget: Optional max price per card in USD.
        limit: Maximum suggestions.
        response_format: Output verbosity.

    Returns:
        WorkflowResult with synergistic cards and structured data.
    """
    log.info("build_around.start", cards=cards, format=format)

    # Step 1: Resolve build-around cards (batch)
    card_map = await bulk.get_cards(cards)
    resolved: list[Card] = []
    unresolved: list[str] = []
    for name in cards:
        card = card_map.get(name)
        if card is not None:
            resolved.append(card)
        else:
            unresolved.append(name)

    # Step 2: Extract keywords from resolved cards for synergy search
    all_keywords: list[str] = []
    for card in resolved:
        if card.oracle_text:
            all_keywords.extend(_extract_keywords_from_text(card.oracle_text))
        all_keywords.extend(kw.lower() for kw in card.keywords)

    # Deduplicate keywords
    unique_keywords = list(dict.fromkeys(all_keywords))

    # Step 3: Search for synergistic cards
    synergy_cards: list[Card] = []
    if unique_keywords:
        # Search for cards with overlapping mechanics
        synergy_cards = await bulk.filter_cards(
            text_any=unique_keywords[:10],  # Cap to avoid overly broad search
            format=format,
            max_price=budget,
            limit=limit,
        )

    # Remove build-around cards from results
    ba_names = {c.name.lower() for c in resolved}
    synergy_cards = [c for c in synergy_cards if c.name.lower() not in ba_names]

    # Step 4: Check Spellbook for combos
    combo_tasks = [spellbook.find_combos(name, limit=5) for name in cards]
    combo_results = await asyncio.gather(*combo_tasks, return_exceptions=True)

    all_combos: list[Combo] = []
    for i, result_item in enumerate(combo_results):
        if isinstance(result_item, BaseException):
            log.warning("build_around.combo_error", card=cards[i], error=str(result_item))
            continue
        all_combos.extend(result_item)

    # Build output
    lines: list[str] = []

    if response_format == "concise":
        lines.append(f"# Build Around ({format})")
        lines.append("")
        lines.append(f"**Cards:** {', '.join(c.name for c in resolved)}")
        if unresolved:
            lines.append(f"**Not found:** {', '.join(unresolved)}")
        lines.append(f"**Synergies found:** {len(synergy_cards)}")
        lines.append(f"**Combos found:** {len(all_combos)}")
        lines.append("")
        for card in synergy_cards[:limit]:
            lines.append(_fmt_card_concise(card))
    else:
        lines.append(f"# Build Around: {', '.join(cards)}")
        lines.append(f"*Format: {format}*")
        lines.append("")

        # Build-around card details
        lines.append("## Build-Around Cards")
        lines.append("")
        for card in resolved:
            lines.append(f"### {card.name}")
            lines.append(f"**Type:** {card.type_line}")
            if card.oracle_text:
                lines.append(f"**Text:** {card.oracle_text}")
            lines.append("")

        if unresolved:
            lines.append("### Not Found")
            for name in unresolved:
                lines.append(f"- {name}")
            lines.append("")

        # Combos
        if all_combos:
            lines.append("## Combos")
            lines.append("")
            seen_ids: set[str] = set()
            for combo in all_combos:
                if combo.id in seen_ids:
                    continue
                seen_ids.add(combo.id)
                card_names = ", ".join(c.name for c in combo.cards)
                results = ", ".join(p.feature_name for p in combo.produces) or "N/A"
                lines.append(f"- **[{combo.id}]** {card_names}")
                lines.append(f"  Produces: {results}")
            lines.append("")

        # Synergistic cards
        lines.append("## Synergistic Cards")
        lines.append("")
        if synergy_cards:
            for card in synergy_cards[:limit]:
                lines.append(_fmt_card_line(card))
        else:
            lines.append("No additional synergistic cards found.")

    log.info(
        "build_around.complete",
        cards=cards,
        synergies=len(synergy_cards),
        combos=len(all_combos),
    )
    data: dict[str, object] = {
        "build_around_cards": [c.name for c in resolved],
        "unresolved": unresolved,
        "format": format,
        "synergy_cards": [
            {
                "name": c.name,
                "mana_cost": c.mana_cost,
                "type_line": c.type_line,
                "price_usd": c.prices.usd,
            }
            for c in synergy_cards[:limit]
        ],
        "combos_found": len(all_combos),
    }
    return WorkflowResult(markdown="\n".join(lines), data=data)


# ---------------------------------------------------------------------------
# complete_deck
# ---------------------------------------------------------------------------

# Target deck sizes by format
_TARGET_SIZES: dict[str, int] = {
    "commander": 100,
    "standard": 60,
    "modern": 60,
    "legacy": 60,
    "vintage": 60,
    "pioneer": 60,
    "pauper": 60,
    "limited": 40,
    "sealed": 40,
    "draft": 40,
}

# Healthy card category ratios for Commander (out of 100)
_COMMANDER_RATIOS: dict[str, tuple[int, int]] = {
    "lands": (36, 38),
    "ramp": (10, 12),
    "card_draw": (8, 10),
    "removal": (8, 10),
    "creatures": (20, 30),
}


def _categorize_card(card: Card) -> str:
    """Categorize a card by its primary role."""
    type_lower = card.type_line.lower()
    oracle_lower = (card.oracle_text or "").lower()

    if "land" in type_lower and "creature" not in type_lower:
        return "lands"
    if any(t in oracle_lower for t in ["add {", "add one mana", "search your library for a"]) and (
        "land" in oracle_lower or "mana" in oracle_lower
    ):
        return "ramp"
    if any(t in oracle_lower for t in ["draw a card", "draw cards", "draw two", "draw three"]):
        return "card_draw"
    if any(t in oracle_lower for t in ["destroy target", "exile target", "deals", "damage to"]):
        return "removal"
    if "creature" in type_lower:
        return "creatures"
    if "instant" in type_lower or "sorcery" in type_lower:
        return "spells"
    if "enchantment" in type_lower:
        return "enchantments"
    if "artifact" in type_lower:
        return "artifacts"
    if "planeswalker" in type_lower:
        return "planeswalkers"
    return "other"


async def complete_deck(
    decklist: list[str],
    format: str,
    *,
    bulk: ScryfallBulkClient,
    commander: str | None = None,
    budget: float | None = None,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Identify gaps in a partial decklist and suggest cards to fill them.

    Resolves all cards, categorizes them, compares to format-appropriate ratios,
    and suggests cards for underrepresented categories.

    Args:
        decklist: Partial list of card names.
        format: Format for target size and legality.
        bulk: Initialized ScryfallBulkClient.
        commander: Commander name (unused currently, reserved for future enrichment).
        budget: Optional max price per card.
        on_progress: Optional progress callback.
        response_format: Output verbosity.

    Returns:
        WorkflowResult with gap analysis and suggestions.
    """
    log.info("complete_deck.start", cards=len(decklist), format=format)

    total_steps = 3
    if on_progress is not None:
        await on_progress(1, total_steps)

    # Step 1: Resolve all cards
    resolved_map = await bulk.get_cards(decklist)
    resolved: list[Card] = []
    unresolved: list[str] = []

    for name in decklist:
        card = resolved_map.get(name)
        if card is not None:
            resolved.append(card)
        else:
            unresolved.append(name)

    # Step 2: Categorize resolved cards
    if on_progress is not None:
        await on_progress(2, total_steps)

    categories: dict[str, list[Card]] = {}
    for card in resolved:
        cat = _categorize_card(card)
        categories.setdefault(cat, []).append(card)

    target_size = _TARGET_SIZES.get(format.lower(), 60)
    cards_needed = max(0, target_size - len(resolved))

    # Step 3: Identify gaps and find suggestions
    if on_progress is not None:
        await on_progress(3, total_steps)

    gaps: dict[str, int] = {}
    if format.lower() == "commander":
        for cat, (low, _high) in _COMMANDER_RATIOS.items():
            current = len(categories.get(cat, []))
            if current < low:
                gaps[cat] = low - current

    # Search for suggestions in underrepresented categories
    suggestions: dict[str, list[Card]] = {}
    for cat, needed in gaps.items():
        cat_limit = min(needed + 3, 10)  # A few extra for variety
        fmt = format.lower()

        # Map category to search criteria
        cat_text_any: list[str] | None = None
        cat_type_contains: list[str] | None = None
        if cat == "ramp":
            cat_text_any = ["add {", "search your library for a basic land"]
        elif cat == "card_draw":
            cat_text_any = ["draw a card", "draw cards"]
        elif cat == "removal":
            cat_text_any = ["destroy target", "exile target"]
        elif cat == "creatures":
            cat_type_contains = ["creature"]
        elif cat == "lands":
            cat_type_contains = ["land"]

        cat_suggestions = await bulk.filter_cards(
            text_any=cat_text_any,
            type_contains=cat_type_contains,
            format=fmt,
            max_price=budget,
            limit=cat_limit,
        )
        # Exclude cards already in the deck
        existing_names = {c.name.lower() for c in resolved}
        cat_suggestions = [c for c in cat_suggestions if c.name.lower() not in existing_names]
        if cat_suggestions:
            suggestions[cat] = cat_suggestions

    # Build output
    lines: list[str] = []

    if response_format == "concise":
        lines.append(f"# Deck Completion ({format})")
        lines.append("")
        lines.append(f"Cards: {len(resolved)}/{target_size} | Need: {cards_needed}")
        if gaps:
            gap_parts = [f"{cat}: need {n}" for cat, n in gaps.items()]
            lines.append(f"Gaps: {', '.join(gap_parts)}")
        if unresolved:
            lines.append(f"Unresolved: {', '.join(unresolved)}")
    else:
        lines.append("# Deck Completion Analysis")
        lines.append(f"*Format: {format} | Target: {target_size} cards*")
        lines.append("")

        # Current status
        lines.append("## Current Deck")
        lines.append(f"**Cards resolved:** {len(resolved)}/{len(decklist)}")
        lines.append(f"**Cards needed:** {cards_needed}")
        lines.append("")

        # Category breakdown
        lines.append("## Category Breakdown")
        lines.append("")
        lines.append("| Category | Count |")
        lines.append("|----------|-------|")
        for cat in sorted(categories.keys()):
            lines.append(f"| {cat.replace('_', ' ').title()} | {len(categories[cat])} |")
        lines.append("")

        # Gaps
        if gaps:
            lines.append("## Gaps to Fill")
            lines.append("")
            for cat, needed in gaps.items():
                current = len(categories.get(cat, []))
                label = cat.replace("_", " ").title()
                target_low = _COMMANDER_RATIOS[cat][0]
                lines.append(f"- **{label}:** {current}/{target_low} (need {needed} more)")
            lines.append("")

        # Suggestions
        if suggestions:
            lines.append("## Suggestions")
            lines.append("")
            for cat, cat_cards in suggestions.items():
                label = cat.replace("_", " ").title()
                lines.append(f"### {label}")
                for card in cat_cards[:5]:
                    lines.append(_fmt_card_line(card))
                lines.append("")

        if unresolved:
            lines.append("## Unresolved Cards")
            lines.append("")
            for name in unresolved:
                lines.append(f"- {name}")

    log.info(
        "complete_deck.complete",
        resolved=len(resolved),
        target=target_size,
        gaps=len(gaps),
    )
    data: dict[str, object] = {
        "format": format,
        "deck_size_current": len(resolved),
        "target_size": target_size,
        "cards_needed": cards_needed,
        "categories": {cat: len(cards_list) for cat, cards_list in categories.items()},
        "gaps": gaps,
        "suggestions": {
            cat: [c.name for c in cards_list[:5]] for cat, cards_list in suggestions.items()
        },
        "unresolved": unresolved,
    }
    return WorkflowResult(markdown="\n".join(lines), data=data)
