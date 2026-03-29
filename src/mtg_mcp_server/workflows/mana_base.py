"""Mana base suggestion workflow — analyze color needs and recommend lands.

Pure async function with no MCP awareness. Accepts a bulk data client as a
keyword argument and returns a formatted markdown string. The workflow server
(``server.py``) registers this as an MCP tool and handles ToolError conversion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import structlog

from mtg_mcp_server.utils.decklist import parse_decklist
from mtg_mcp_server.utils.format_rules import normalize_format
from mtg_mcp_server.utils.mana import count_pips, suggest_land_count

if TYPE_CHECKING:
    from mtg_mcp_server.services.scryfall_bulk import ScryfallBulkClient
    from mtg_mcp_server.types import Card

log = structlog.get_logger(service="workflow.mana_base")

_COLOR_NAMES: dict[str, str] = {
    "W": "White",
    "U": "Blue",
    "B": "Black",
    "R": "Red",
    "G": "Green",
}

_BASIC_LAND_FOR_COLOR: dict[str, str] = {
    "W": "Plains",
    "U": "Island",
    "B": "Swamp",
    "R": "Mountain",
    "G": "Forest",
}


async def suggest_mana_base(
    decklist: list[str],
    format: str,
    *,
    total_lands: int | None = None,
    bulk: ScryfallBulkClient,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> str:
    """Suggest a mana base based on color pip distribution.

    Analyzes the mana costs of non-land cards, counts color pips weighted
    by quantity, recommends a land count and basic land distribution, and
    suggests format-legal dual lands.

    Args:
        decklist: Card entries (e.g. ``["4x Lightning Bolt"]``). Lands are filtered internally.
        format: Format for legality checks (e.g. ``"commander"``).
        total_lands: Override the recommended total land count.
        bulk: Initialized ScryfallBulkClient.

    Returns:
        Formatted markdown with mana base recommendations.
    """
    log.info("suggest_mana_base.start", format=format, cards=len(decklist))

    # --- Normalize format (ValueError propagates to server.py → ToolError) ---
    fmt = normalize_format(format)

    # --- Parse and resolve ---
    parsed = parse_decklist(decklist)
    if not parsed:
        return "# Mana Base Suggestion\n\nNo cards provided."

    unique_names = list(dict.fromkeys(name for _, name in parsed))
    resolved = await bulk.get_cards(unique_names)

    # --- Count pips from non-land cards ---
    total_pips: dict[str, float] = {}
    non_land_cmcs: list[float] = []
    resolved_count = 0
    unresolved_count = 0

    for qty, name in parsed:
        card: Card | None = resolved.get(name)
        if card is None:
            unresolved_count += 1
            continue
        resolved_count += 1

        # Skip lands - we only want spell mana costs
        if "Land" in card.type_line:
            continue

        pips = count_pips(card.mana_cost)
        for color, count in pips.items():
            total_pips[color] = total_pips.get(color, 0.0) + count * qty

        non_land_cmcs.extend([card.cmc] * qty)

    # --- Calculate averages ---
    avg_cmc = sum(non_land_cmcs) / len(non_land_cmcs) if non_land_cmcs else 0.0

    # --- Land count ---
    land_count = total_lands if total_lands is not None else suggest_land_count(avg_cmc, fmt)

    # --- Pip ratios and basic land distribution ---
    pip_total = sum(total_pips.values())
    deck_colors: set[str] = set()
    pip_ratios: dict[str, float] = {}

    if pip_total > 0:
        for color in ("W", "U", "B", "R", "G"):
            if color in total_pips:
                deck_colors.add(color)
                pip_ratios[color] = total_pips[color] / pip_total

    # Distribute basic lands by ratio
    basic_lands: dict[str, int] = {}
    if deck_colors:
        # Largest-remainder method for fair rounding
        raw_alloc = {c: pip_ratios[c] * land_count for c in deck_colors}
        floored = {c: int(v) for c, v in raw_alloc.items()}
        remainder = land_count - sum(floored.values())

        # Sort by fractional remainder descending
        remainders = sorted(
            deck_colors,
            key=lambda c: raw_alloc[c] - floored[c],
            reverse=True,
        )
        for i, color in enumerate(remainders):
            floored[color] += 1 if i < remainder else 0

        basic_lands = {_BASIC_LAND_FOR_COLOR[c]: floored[c] for c in deck_colors}
    else:
        # Colorless deck
        basic_lands = {"Wastes": land_count}

    # --- Dual land suggestions ---
    dual_lands: list[Card] = []
    if len(deck_colors) >= 2:
        try:
            dual_lands = await bulk.filter_cards(
                format=fmt,
                type_contains=["Land"],
                color_identity=frozenset(deck_colors),
                limit=20,
            )
        except Exception:
            log.warning("suggest_mana_base.dual_land_search_failed", format=fmt)
            dual_lands = []
        # Filter to only dual/multi lands (must produce colored mana)
        dual_lands = [
            card for card in dual_lands if card.color_identity and len(card.color_identity) >= 2
        ][:8]

    # --- Heavy color warnings ---
    heavy_warnings: list[str] = []
    for color, pips in total_pips.items():
        if pips >= 5.0:
            heavy_warnings.append(
                f"{_COLOR_NAMES.get(color, color)}: {pips:.1f} pips "
                f"- consider extra {_COLOR_NAMES.get(color, color).lower()} sources"
            )

    # --- Build output ---
    lines: list[str] = [
        f"# Mana Base Suggestion - {fmt.title()}",
        "",
        f"**Average CMC:** {avg_cmc:.2f}",
        f"**Recommended Lands:** {land_count}",
        "",
    ]

    if response_format == "concise":
        # Basic land distribution only
        for land_name, count in sorted(basic_lands.items()):
            if count > 0:
                lines.append(f"- {count}x {land_name}")
    else:
        # Pip distribution table
        if total_pips:
            lines.append("## Color Pip Distribution")
            lines.append("")
            lines.append("| Color | Pips | Ratio |")
            lines.append("|-------|------|-------|")
            for color in ("W", "U", "B", "R", "G"):
                if color in total_pips:
                    pips = total_pips[color]
                    ratio = pip_ratios.get(color, 0.0)
                    lines.append(f"| {_COLOR_NAMES[color]} ({color}) | {pips:.1f} | {ratio:.0%} |")
            lines.append("")
        else:
            lines.append("## Color Pip Distribution")
            lines.append("")
            lines.append("Colorless deck - no colored mana requirements.")
            lines.append("")

        # Basic land distribution
        lines.append("## Suggested Basic Lands")
        lines.append("")
        for land_name, count in sorted(basic_lands.items()):
            if count > 0:
                lines.append(f"- {count}x {land_name}")
        lines.append("")

        # Dual land suggestions
        if dual_lands:
            lines.append("## Recommended Dual Lands")
            lines.append("")
            for card in dual_lands:
                colors = ", ".join(card.color_identity)
                price = f"${card.prices.usd}" if card.prices.usd is not None else "N/A"
                lines.append(f"- **{card.name}** ({colors}) - {price}")
            lines.append("")

        # Warnings
        if heavy_warnings:
            lines.append("## Warnings")
            lines.append("")
            for warn in heavy_warnings:
                lines.append(f"- {warn}")
            lines.append("")

        # Summary
        lines.append("---")
        summary_parts = [f"{resolved_count} cards analyzed"]
        if unresolved_count:
            summary_parts.append(f"{unresolved_count} unresolved")
        lines.append(f"*{', '.join(summary_parts)}*")

    log.info("suggest_mana_base.complete", format=fmt, land_count=land_count)
    return "\n".join(lines)
