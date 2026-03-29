"""Commander depth workflow functions — deeper commander analytics.

These are pure async functions with no MCP awareness. They accept service
clients as keyword arguments and return ``WorkflowResult``. The workflow
server (``server.py``) registers them as MCP tools and handles ToolError
conversion.

Tools:
    ``commander_comparison`` — Compare 2-5 commanders head-to-head.
    ``tribal_staples`` — Best cards for a creature type within a color identity.
    ``precon_upgrade`` — Analyze a precon and suggest swaps.
    ``color_identity_staples`` — Top cards across all commanders in a color identity.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import structlog

from mtg_mcp_server.utils.color_identity import is_within_identity, parse_color_identity
from mtg_mcp_server.workflows import WorkflowResult

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mtg_mcp_server.services.edhrec import EDHRECClient
    from mtg_mcp_server.services.scryfall_bulk import ScryfallBulkClient
    from mtg_mcp_server.services.spellbook import SpellbookClient
    from mtg_mcp_server.types import Card, DecklistCombos, EDHRECCard, EDHRECCommanderData

log = structlog.get_logger(service="workflow.commander_depth")

# Cap output to keep tool responses concise for LLM context windows.
_MAX_STAPLES_PER_COMMANDER = 10
_MAX_SHARED_STAPLES = 3
_MAX_UNIQUE_STAPLES = 3


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _fmt_synergy(value: float) -> str:
    """Format a synergy score with sign prefix (e.g. '+61%' or '-5%')."""
    return f"+{value:.0%}" if value >= 0 else f"{value:.0%}"


def _fmt_price(card: Card) -> str:
    """Format a card's USD price."""
    if card.prices.usd is not None:
        return f"${card.prices.usd}"
    return "N/A"


def _fmt_identity(card: Card) -> str:
    """Format a card's color identity."""
    return ", ".join(card.color_identity) if card.color_identity else "C"


# ---------------------------------------------------------------------------
# Type mappings for category filter
# ---------------------------------------------------------------------------

_CATEGORY_TYPE_MAP: dict[str, str] = {
    "creatures": "creature",
    "creature": "creature",
    "instants": "instant",
    "instant": "instant",
    "sorceries": "sorcery",
    "sorcery": "sorcery",
    "enchantments": "enchantment",
    "enchantment": "enchantment",
    "artifacts": "artifact",
    "artifact": "artifact",
    "planeswalkers": "planeswalker",
    "planeswalker": "planeswalker",
    "lands": "land",
    "land": "land",
}


# ---------------------------------------------------------------------------
# Internal data structures
# ---------------------------------------------------------------------------


@dataclass
class _CommanderStats:
    """Aggregated stats for one commander."""

    name: str
    card: Card
    combo_count: int = 0
    combo_error: str | None = None
    staples: list[EDHRECCard] = field(default_factory=list)
    edhrec_total_decks: int = 0
    edhrec_error: str | None = None


@dataclass
class _CardScore:
    """Scoring data for a single card in the precon."""

    name: str
    synergy_score: float = 0.0
    inclusion_rate: int = 0
    is_combo_piece: bool = False
    has_edhrec_data: bool = False
    has_data: bool = False
    cuttability: float = 0.0


@dataclass
class _Swap:
    """A cut/add pair for precon upgrade."""

    cut: str
    cut_cuttability: float
    cut_synergy: float
    add: str
    add_synergy: float
    add_inclusion: int
    add_price: float


# ---------------------------------------------------------------------------
# Tool 1: commander_comparison
# ---------------------------------------------------------------------------


async def commander_comparison(
    commanders: list[str],
    *,
    bulk: ScryfallBulkClient,
    spellbook: SpellbookClient,
    edhrec: EDHRECClient | None = None,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Compare 2-5 commanders head-to-head.

    Args:
        commanders: Commander names to compare (2-5).
        bulk: Initialized ScryfallBulkClient.
        spellbook: Initialized SpellbookClient.
        edhrec: Initialized EDHRECClient, or None if disabled.
        on_progress: Optional callback for progress reporting.
        response_format: 'detailed' or 'concise'.

    Returns:
        WorkflowResult with markdown comparison table and structured data.

    Raises:
        ValueError: If a commander is not found in bulk data.
    """
    log.info("commander_comparison.start", commanders=commanders)

    # Step 1/3: Resolve all commanders via bulk data
    if on_progress is not None:
        await on_progress(1, 3)

    resolve_tasks = [bulk.get_card(name) for name in commanders]
    resolved = await asyncio.gather(*resolve_tasks)

    stats_list: list[_CommanderStats] = []
    for i, card in enumerate(resolved):
        if card is None:
            raise ValueError(f"Commander not found: '{commanders[i]}'")
        stats_list.append(_CommanderStats(name=card.name, card=card))

    # Step 2/3: Fetch combo counts and EDHREC data
    if on_progress is not None:
        await on_progress(2, 3)

    # Spellbook combo counts (parallel)
    combo_tasks = [spellbook.find_combos(s.name) for s in stats_list]
    combo_results = await asyncio.gather(*combo_tasks, return_exceptions=True)

    for i, result in enumerate(combo_results):
        if isinstance(result, BaseException):
            log.warning(
                "commander_comparison.combo_failed",
                commander=stats_list[i].name,
                error=str(result),
            )
            stats_list[i].combo_error = str(result)
        else:
            stats_list[i].combo_count = len(result)

    # EDHREC staples (parallel)
    if edhrec is not None:
        edhrec_tasks = [edhrec.commander_top_cards(s.name) for s in stats_list]
        edhrec_results = await asyncio.gather(*edhrec_tasks, return_exceptions=True)

        for i, result in enumerate(edhrec_results):
            if isinstance(result, BaseException):
                log.warning(
                    "commander_comparison.edhrec_failed",
                    commander=stats_list[i].name,
                    error=str(result),
                )
                stats_list[i].edhrec_error = str(result)
            else:
                edhrec_data: EDHRECCommanderData = result
                stats_list[i].edhrec_total_decks = edhrec_data.total_decks
                all_cards: list[EDHRECCard] = []
                for cardlist in edhrec_data.cardlists:
                    all_cards.extend(cardlist.cardviews)
                all_cards.sort(key=lambda c: c.inclusion, reverse=True)
                stats_list[i].staples = all_cards[:_MAX_STAPLES_PER_COMMANDER]

    # Step 3/3: Format output
    if on_progress is not None:
        await on_progress(3, 3)

    lines = _format_commander_comparison(stats_list, edhrec is not None, response_format)

    log.info("commander_comparison.complete", commanders=commanders)
    data = {
        "commanders": [
            {
                "name": s.name,
                "mana_cost": s.card.mana_cost,
                "color_identity": s.card.color_identity,
                "type_line": s.card.type_line,
                "power": s.card.power,
                "toughness": s.card.toughness,
                "edhrec_rank": s.card.edhrec_rank,
                "combo_count": s.combo_count,
                "edhrec_total_decks": s.edhrec_total_decks,
                "staples": [
                    {"name": st.name, "synergy": st.synergy, "inclusion": st.inclusion}
                    for st in s.staples
                ],
            }
            for s in stats_list
        ],
    }
    return WorkflowResult(markdown="\n".join(lines), data=data)


def _format_commander_comparison(
    stats: list[_CommanderStats],
    edhrec_enabled: bool,
    response_format: Literal["detailed", "concise"],
) -> list[str]:
    """Format the commander comparison output."""
    lines: list[str] = ["# Commander Comparison", ""]

    # Main comparison table
    lines.append("| Stat | " + " | ".join(s.name for s in stats) + " |")
    lines.append("|------|" + "|".join("---" for _ in stats) + "|")

    # Mana cost row
    lines.append("| Mana Cost | " + " | ".join(s.card.mana_cost or "N/A" for s in stats) + " |")
    # Color identity row
    lines.append("| Color Identity | " + " | ".join(_fmt_identity(s.card) for s in stats) + " |")
    # Type row
    lines.append("| Type | " + " | ".join(s.card.type_line for s in stats) + " |")
    # P/T row
    pt_values = []
    for s in stats:
        if s.card.power is not None and s.card.toughness is not None:
            pt_values.append(f"{s.card.power}/{s.card.toughness}")
        else:
            pt_values.append("N/A")
    lines.append("| P/T | " + " | ".join(pt_values) + " |")

    # EDHREC rank row
    rank_values = []
    for s in stats:
        if s.card.edhrec_rank is not None:
            rank_values.append(str(s.card.edhrec_rank))
        else:
            rank_values.append("N/A")
    lines.append("| EDHREC Rank | " + " | ".join(rank_values) + " |")

    # Combo count row
    combo_values = []
    for s in stats:
        if s.combo_error is not None:
            combo_values.append("N/A")
        else:
            combo_values.append(str(s.combo_count))
    lines.append("| Combos | " + " | ".join(combo_values) + " |")

    if response_format == "concise":
        return lines

    # Shared and unique staples (only with EDHREC data)
    if edhrec_enabled and any(s.staples for s in stats):
        lines.extend(_format_staples_analysis(stats))

    # Data Sources footer
    lines.append("")
    lines.append("---")
    lines.append("**Data Sources:**")
    lines.append("- [Scryfall Bulk Data](https://scryfall.com): OK")

    any_combo_ok = any(s.combo_error is None for s in stats)
    if any_combo_ok:
        lines.append("- [Commander Spellbook](https://commanderspellbook.com): OK")
    else:
        lines.append("- [Commander Spellbook](https://commanderspellbook.com): Failed")

    if not edhrec_enabled:
        lines.append("- [EDHREC](https://edhrec.com): Disabled")
    elif any(s.staples for s in stats):
        lines.append("- [EDHREC](https://edhrec.com): OK")
    elif all(s.edhrec_error is not None for s in stats):
        lines.append("- [EDHREC](https://edhrec.com): Failed")
    else:
        lines.append("- [EDHREC](https://edhrec.com): Partial")

    return lines


def _format_staples_analysis(stats: list[_CommanderStats]) -> list[str]:
    """Analyze shared and unique staples across commanders."""
    lines: list[str] = []

    # Build name -> list of commanders mapping
    card_to_commanders: dict[str, list[str]] = {}
    for s in stats:
        for staple in s.staples:
            key = staple.name.lower()
            if key not in card_to_commanders:
                card_to_commanders[key] = []
            card_to_commanders[key].append(s.name)

    # Shared staples (appearing in 2+ commanders' lists)
    shared = [name for name, cmds in card_to_commanders.items() if len(cmds) >= 2]
    if shared:
        lines.append("")
        lines.append("## Shared Staples")
        lines.append("")
        # Get the actual card names (proper casing) from first commander's data
        name_map: dict[str, str] = {}
        for s in stats:
            for staple in s.staples:
                name_map[staple.name.lower()] = staple.name
        for name_lower in shared[:_MAX_SHARED_STAPLES]:
            proper_name = name_map.get(name_lower, name_lower)
            cmd_names = card_to_commanders[name_lower]
            lines.append(f"- **{proper_name}** (in {', '.join(cmd_names)})")

    # Unique staples per commander
    lines.append("")
    lines.append("## Unique Staples")
    lines.append("")
    for s in stats:
        unique = [
            staple
            for staple in s.staples
            if len(card_to_commanders.get(staple.name.lower(), [])) == 1
        ]
        if unique:
            lines.append(f"**{s.name}:**")
            for staple in unique[:_MAX_UNIQUE_STAPLES]:
                lines.append(
                    f"- {staple.name} ({_fmt_synergy(staple.synergy)}, "
                    f"{staple.inclusion}% inclusion)"
                )

    return lines


# ---------------------------------------------------------------------------
# Tool 2: tribal_staples
# ---------------------------------------------------------------------------


async def tribal_staples(
    tribe: str,
    *,
    bulk: ScryfallBulkClient,
    edhrec: EDHRECClient | None = None,
    color_identity: str | None = None,
    format: str | None = None,
    limit: int = 20,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Find the best cards for a creature type within a color identity.

    Searches for tribal lords/anthems, synergy cards, tribe members, and
    general tribal support. Optionally filters by color identity and format.

    Args:
        tribe: Creature type (e.g. "Zombie", "Elf", "Dragon").
        bulk: Initialized ScryfallBulkClient.
        edhrec: Initialized EDHRECClient, or None if disabled.
        color_identity: Color identity filter (e.g. "sultai", "BG").
        format: Format legality filter (e.g. "commander").
        limit: Maximum total cards to return.
        response_format: 'detailed' or 'concise'.

    Returns:
        WorkflowResult with categorized tribal cards.
    """
    log.info("tribal_staples.start", tribe=tribe, color_identity=color_identity)

    # Parse color identity if provided
    identity: frozenset[str] | None = None
    if color_identity is not None:
        try:
            identity = parse_color_identity(color_identity)
        except ValueError:
            return WorkflowResult(
                markdown=f"Unrecognized color identity: '{color_identity}'",
                data={"tribe": tribe, "error": f"Invalid color identity: {color_identity}"},
            )

    tribe_lower = tribe.lower()

    # Search in parallel for different card categories
    # 1. Lords/anthems: cards that buff the tribe
    lord_query = f"{tribe_lower} creatures you control get"
    lords_task = bulk.search_by_text(lord_query, limit=limit)

    # 2. Tribal synergy: cards that mention the tribe name
    synergy_task = bulk.search_by_text(tribe_lower, limit=limit * 2)

    # 3. Best members: creatures of the tribe type
    members_task = bulk.search_by_type(tribe, limit=limit * 3)

    # 4. Tribal support: "Kindred" or "choose a creature type"
    support_task = bulk.filter_cards(
        text_any=["kindred", "choose a creature type", "chosen type"],
        format=format,
        color_identity=identity,
        limit=limit,
    )

    lords_result, synergy_result, members_result, support_result = await asyncio.gather(
        lords_task, synergy_task, members_task, support_task
    )

    # Filter by color identity and format
    def _filter(cards: list[Card]) -> list[Card]:
        filtered: list[Card] = []
        for card in cards:
            if identity is not None and not is_within_identity(card.color_identity, identity):
                continue
            if format is not None and card.legalities.get(format) != "legal":
                continue
            filtered.append(card)
        return filtered

    lords = _filter(lords_result)
    synergy_cards = _filter(synergy_result)
    members = _filter(members_result)
    support = _filter(support_result)

    # Deduplicate: track seen card names, assign to best category
    seen: set[str] = set()

    def _dedup(cards: list[Card]) -> list[Card]:
        result: list[Card] = []
        for card in cards:
            key = card.name.lower()
            if key not in seen:
                seen.add(key)
                result.append(card)
        return result

    lords = _dedup(lords)
    # Synergy cards that are also members get classified as synergy
    synergy_only = [c for c in _dedup(synergy_cards) if tribe_lower not in c.type_line.lower()]
    members = _dedup(members)
    support = _dedup(support)

    # Sort members by edhrec_rank (lower = more popular)
    members.sort(key=lambda c: c.edhrec_rank if c.edhrec_rank is not None else 999999)

    # Apply overall limit
    categories: list[tuple[str, list[Card]]] = [
        ("Lords & Anthems", lords),
        ("Tribal Synergy", synergy_only),
        (f"{tribe} Creatures", members),
        ("Tribal Support", support),
    ]

    remaining = limit
    capped_categories: list[tuple[str, list[Card]]] = []
    for cat_name, cat_cards in categories:
        if remaining <= 0:
            break
        capped = cat_cards[:remaining]
        if capped:
            capped_categories.append((cat_name, capped))
            remaining -= len(capped)

    # Format output
    total_found = sum(len(cards) for _, cards in capped_categories)
    lines = _format_tribal_staples(tribe, capped_categories, total_found, response_format)

    log.info("tribal_staples.complete", tribe=tribe, total=total_found)
    data = {
        "tribe": tribe,
        "color_identity": color_identity,
        "format": format,
        "total_found": total_found,
        "categories": [
            {
                "name": cat_name,
                "cards": [
                    {
                        "name": c.name,
                        "mana_cost": c.mana_cost,
                        "type_line": c.type_line,
                        "edhrec_rank": c.edhrec_rank,
                    }
                    for c in cat_cards
                ],
            }
            for cat_name, cat_cards in capped_categories
        ],
    }
    return WorkflowResult(markdown="\n".join(lines), data=data)


def _format_tribal_staples(
    tribe: str,
    categories: list[tuple[str, list[Card]]],
    total: int,
    response_format: Literal["detailed", "concise"],
) -> list[str]:
    """Format tribal staples output."""
    lines: list[str] = [f"# {tribe} Tribal Staples", ""]

    if total == 0:
        lines.append(f"No tribal cards found for '{tribe}'.")
        return lines

    lines.append(f"Found {total} card(s):")
    lines.append("")

    for cat_name, cards in categories:
        lines.append(f"## {cat_name}")
        lines.append("")
        for card in cards:
            mana = card.mana_cost or ""
            rank_str = f" (EDHREC #{card.edhrec_rank})" if card.edhrec_rank is not None else ""
            if response_format == "concise":
                lines.append(f"- {card.name} {mana}")
            else:
                lines.append(f"- **{card.name}** {mana} -- {card.type_line}{rank_str}")
        lines.append("")

    return lines


# ---------------------------------------------------------------------------
# Tool 3: precon_upgrade
# ---------------------------------------------------------------------------


async def _fetch_precon_data(
    commander: str,
    decklist: list[str],
    *,
    spellbook: SpellbookClient,
    edhrec: EDHRECClient | None,
) -> tuple[DecklistCombos | None, EDHRECCommanderData | None, bool, bool]:
    """Fetch combo and EDHREC data concurrently, returning results + status flags.

    Returns:
        (combo_data, edhrec_data, spellbook_ok, edhrec_ok)
    """
    combo_data: DecklistCombos | None = None
    edhrec_data: EDHRECCommanderData | None = None
    spellbook_ok = False
    edhrec_ok = False

    try:
        combo_data = await spellbook.find_decklist_combos([commander], decklist)
        spellbook_ok = True
    except Exception as exc:
        log.warning("precon_upgrade.spellbook_failed", error=str(exc))

    if edhrec is not None:
        try:
            edhrec_data = await edhrec.commander_top_cards(commander)
            edhrec_ok = True
        except Exception as exc:
            log.warning("precon_upgrade.edhrec_failed", error=str(exc))

    return combo_data, edhrec_data, spellbook_ok, edhrec_ok


async def precon_upgrade(
    decklist: list[str],
    commander: str,
    *,
    bulk: ScryfallBulkClient,
    spellbook: SpellbookClient,
    edhrec: EDHRECClient | None = None,
    budget: float = 50.0,
    num_upgrades: int = 10,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Analyze and upgrade a Commander precon.

    Identifies the weakest cards in the decklist and suggests replacements
    from EDHREC staples that fit under the budget ceiling.

    Args:
        decklist: Card names in the current decklist.
        commander: Commander name.
        bulk: Initialized ScryfallBulkClient.
        spellbook: Initialized SpellbookClient.
        edhrec: Initialized EDHRECClient, or None if disabled.
        budget: Maximum price per card in USD.
        num_upgrades: Number of upgrade swaps to suggest.
        on_progress: Optional callback for progress reporting.
        response_format: 'detailed' or 'concise'.

    Returns:
        WorkflowResult with ranked swap suggestions.
    """
    log.info("precon_upgrade.start", commander=commander, budget=budget)

    if not decklist:
        return WorkflowResult(
            markdown=f"# Precon Upgrade for {commander}\n\nNo cards in decklist to evaluate.",
            data={"commander": commander, "cuts": [], "upgrades": [], "swaps": []},
        )

    # Step 1/4: Resolve all cards via bulk data
    if on_progress is not None:
        await on_progress(1, 4)

    await bulk.get_cards(decklist)  # Ensure data is loaded / warm

    # Step 2/4: Analyze for cuts (combo data + synergy data)
    if on_progress is not None:
        await on_progress(2, 4)

    combo_data, edhrec_data, spellbook_ok, edhrec_ok = await _fetch_precon_data(
        commander, decklist, spellbook=spellbook, edhrec=edhrec
    )

    # Extract combo pieces
    combo_pieces: set[str] = set()
    if combo_data is not None:
        for combo in combo_data.included:
            for card in combo.cards:
                combo_pieces.add(card.name.lower())

    # Build synergy lookup from EDHREC
    synergy_lookup: dict[str, EDHRECCard] = {}
    if edhrec_data is not None:
        for cardlist in edhrec_data.cardlists:
            for ecard in cardlist.cardviews:
                synergy_lookup[ecard.name.lower()] = ecard

    # Score each card for cuttability
    scored: list[_CardScore] = []
    for card_name in decklist:
        cs = _CardScore(name=card_name)
        key = card_name.lower()

        ecard = synergy_lookup.get(key)
        if ecard is not None:
            cs.synergy_score = ecard.synergy
            cs.inclusion_rate = ecard.inclusion
            cs.has_edhrec_data = True
            cs.has_data = True

        cs.is_combo_piece = key in combo_pieces
        if cs.is_combo_piece:
            cs.has_data = True

        # Cuttability formula (same as suggest_cuts)
        cuttability = 0.0
        if cs.has_edhrec_data:
            cuttability += 1.0 - cs.synergy_score
            cuttability += (100 - cs.inclusion_rate) / 100.0
        if cs.is_combo_piece:
            cuttability -= 2.0
        if not cs.has_data:
            cuttability += 0.5

        cs.cuttability = cuttability
        scored.append(cs)

    scored.sort(key=lambda c: c.cuttability, reverse=True)
    top_cuts = scored[:num_upgrades]

    # Step 3/4: Find upgrades from EDHREC staples
    if on_progress is not None:
        await on_progress(3, 4)

    swaps: list[_Swap] = []
    decklist_lower = {name.lower() for name in decklist}

    if edhrec_data is not None:
        # Collect all EDHREC staples not already in the decklist
        all_staples: list[EDHRECCard] = []
        for cardlist in edhrec_data.cardlists:
            for ecard in cardlist.cardviews:
                if ecard.name.lower() not in decklist_lower:
                    all_staples.append(ecard)

        # Sort by synergy descending
        all_staples.sort(key=lambda c: c.synergy, reverse=True)

        # Look up prices for top staples via bulk data
        upgrade_candidates: list[tuple[EDHRECCard, float]] = []
        for ecard in all_staples[: num_upgrades * 3]:
            card_data = await bulk.get_card(ecard.name)
            if card_data is not None and card_data.prices.usd is not None:
                try:
                    price = float(card_data.prices.usd)
                except ValueError:
                    continue
                if price <= budget:
                    upgrade_candidates.append((ecard, price))

        # Pair cuts with upgrades
        for i, cut in enumerate(top_cuts):
            if i >= len(upgrade_candidates):
                break
            upgrade_ecard, upgrade_price = upgrade_candidates[i]
            swaps.append(
                _Swap(
                    cut=cut.name,
                    cut_cuttability=cut.cuttability,
                    cut_synergy=cut.synergy_score,
                    add=upgrade_ecard.name,
                    add_synergy=upgrade_ecard.synergy,
                    add_inclusion=upgrade_ecard.inclusion,
                    add_price=upgrade_price,
                )
            )

    # Step 4/4: Format output
    if on_progress is not None:
        await on_progress(4, 4)

    lines = _format_precon_upgrade(
        commander, top_cuts, swaps, spellbook_ok, edhrec_ok, edhrec is not None, response_format
    )

    log.info("precon_upgrade.complete", commander=commander, swaps=len(swaps))
    data = {
        "commander": commander,
        "budget": budget,
        "cuts": [
            {
                "name": cs.name,
                "cuttability": cs.cuttability,
                "synergy_score": cs.synergy_score,
                "inclusion_rate": cs.inclusion_rate,
                "is_combo_piece": cs.is_combo_piece,
            }
            for cs in top_cuts
        ],
        "upgrades": [
            {"name": s.add, "synergy": s.add_synergy, "price": s.add_price} for s in swaps
        ],
        "swaps": [
            {
                "cut": s.cut,
                "cut_cuttability": s.cut_cuttability,
                "cut_synergy": s.cut_synergy,
                "add": s.add,
                "add_synergy": s.add_synergy,
                "add_inclusion": s.add_inclusion,
                "add_price": s.add_price,
            }
            for s in swaps
        ],
        "sources": {"spellbook": spellbook_ok, "edhrec": edhrec_ok},
    }
    return WorkflowResult(markdown="\n".join(lines), data=data)


def _format_precon_upgrade(
    commander: str,
    cuts: list[_CardScore],
    swaps: list[_Swap],
    spellbook_ok: bool,
    edhrec_ok: bool,
    edhrec_enabled: bool,
    response_format: Literal["detailed", "concise"],
) -> list[str]:
    """Format the precon upgrade output."""
    lines: list[str] = [f"# Precon Upgrade for {commander}", ""]

    if swaps:
        lines.append("## Suggested Swaps")
        lines.append("")
        lines.append("| # | Cut | Add | Synergy Improvement | Price |")
        lines.append("|---|-----|-----|---------------------|-------|")
        for i, swap in enumerate(swaps, 1):
            improvement = swap.add_synergy - swap.cut_synergy
            imp_str = f"+{improvement:.0%}" if improvement >= 0 else f"{improvement:.0%}"
            lines.append(f"| {i} | {swap.cut} | {swap.add} | {imp_str} | ${swap.add_price:.2f} |")
    else:
        lines.append("No swap suggestions available.")
        if not edhrec_enabled:
            lines.append("")
            lines.append("EDHREC is disabled -- enable it for upgrade suggestions.")

    if response_format == "concise":
        return lines

    # Show cuts detail
    if cuts:
        lines.append("")
        lines.append("## Weakest Cards")
        lines.append("")
        for i, cs in enumerate(cuts, 1):
            parts: list[str] = []
            if cs.has_edhrec_data:
                parts.append(f"Synergy: {cs.synergy_score:.0%}, Inclusion: {cs.inclusion_rate}%")
            if cs.is_combo_piece:
                parts.append("PROTECTED \u2014 combo piece")
            if not cs.has_data:
                parts.append("Low confidence \u2014 no data found")
            reasoning = " | ".join(parts) if parts else "No data"
            lines.append(f"{i}. **{cs.name}** \u2014 {reasoning}")

    # Data Sources footer
    lines.append("")
    lines.append("---")
    lines.append("**Data Sources:**")
    lines.append("- [Scryfall Bulk Data](https://scryfall.com): OK")
    if spellbook_ok:
        lines.append("- [Commander Spellbook](https://commanderspellbook.com): OK")
    else:
        lines.append("- [Commander Spellbook](https://commanderspellbook.com): Failed")
    if not edhrec_enabled:
        lines.append("- [EDHREC](https://edhrec.com): Disabled")
    elif edhrec_ok:
        lines.append("- [EDHREC](https://edhrec.com): OK")
    else:
        lines.append("- [EDHREC](https://edhrec.com): Failed")

    return lines


# ---------------------------------------------------------------------------
# Tool 4: color_identity_staples
# ---------------------------------------------------------------------------


async def color_identity_staples(
    color_identity: str,
    *,
    bulk: ScryfallBulkClient,
    edhrec: EDHRECClient | None = None,
    category: str | None = None,
    limit: int = 20,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Top cards across all commanders in a color identity.

    Searches bulk data for commander-legal cards within the given color
    identity, sorted by EDHREC rank (lower = more popular).

    Args:
        color_identity: Color identity string (e.g. "sultai", "BUG", "mono-red").
        bulk: Initialized ScryfallBulkClient.
        edhrec: Initialized EDHRECClient, or None if disabled.
        category: Optional card type filter (e.g. "creatures", "instants").
        limit: Maximum results to return.
        response_format: 'detailed' or 'concise'.

    Returns:
        WorkflowResult with ranked staple cards.
    """
    log.info(
        "color_identity_staples.start",
        color_identity=color_identity,
        category=category,
    )

    # Parse color identity
    try:
        identity = parse_color_identity(color_identity)
    except ValueError:
        return WorkflowResult(
            markdown=f"Unrecognized color identity: '{color_identity}'",
            data={"color_identity": color_identity, "error": "Invalid color identity", "cards": []},
        )

    # Map category to type filter
    type_contains: list[str] | None = None
    if category is not None:
        mapped = _CATEGORY_TYPE_MAP.get(category.lower())
        if mapped is not None:
            type_contains = [mapped]

    # Use filter_cards for a single efficient pass
    cards = await bulk.filter_cards(
        format="commander",
        color_identity=identity,
        type_contains=type_contains,
        limit=limit * 5,  # Over-fetch to allow sorting
    )

    # Sort by edhrec_rank (lower = more popular). Cards without rank go last.
    cards.sort(key=lambda c: c.edhrec_rank if c.edhrec_rank is not None else 999999)

    # Take top `limit`
    top_cards = cards[:limit]

    # Format output
    identity_str = ", ".join(sorted(identity)) if identity else "Colorless"
    lines = _format_color_identity_staples(
        color_identity, identity_str, top_cards, category, response_format
    )

    log.info("color_identity_staples.complete", count=len(top_cards))
    data = {
        "color_identity": color_identity,
        "parsed_colors": sorted(identity),
        "category": category,
        "cards": [
            {
                "name": c.name,
                "mana_cost": c.mana_cost,
                "type_line": c.type_line,
                "edhrec_rank": c.edhrec_rank,
                "price": c.prices.usd,
            }
            for c in top_cards
        ],
    }
    return WorkflowResult(markdown="\n".join(lines), data=data)


def _format_color_identity_staples(
    input_identity: str,
    identity_str: str,
    cards: list[Card],
    category: str | None,
    response_format: Literal["detailed", "concise"],
) -> list[str]:
    """Format color identity staples output."""
    cat_label = f" ({category})" if category else ""
    lines: list[str] = [
        f"# {input_identity.title()} Staples{cat_label}",
        f"*Color identity: {identity_str}*",
        "",
    ]

    if not cards:
        lines.append("No cards found matching the criteria.")
        return lines

    lines.append(f"Found {len(cards)} card(s):")
    lines.append("")

    if response_format == "concise":
        for i, card in enumerate(cards, 1):
            mana = card.mana_cost or ""
            lines.append(f"{i}. {card.name} {mana}")
    else:
        lines.append("| # | Name | Mana Cost | Type | EDHREC Rank | Price |")
        lines.append("|---|------|-----------|------|-------------|-------|")
        for i, card in enumerate(cards, 1):
            mana = card.mana_cost or "N/A"
            rank = str(card.edhrec_rank) if card.edhrec_rank is not None else "N/A"
            price = _fmt_price(card)
            lines.append(f"| {i} | {card.name} | {mana} | {card.type_line} | {rank} | {price} |")

        # Data Sources footer
        lines.append("")
        lines.append("---")
        lines.append("**Data Sources:**")
        lines.append("- [Scryfall Bulk Data](https://scryfall.com): OK")

    return lines
