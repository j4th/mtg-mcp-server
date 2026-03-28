"""Deck validation workflow — check a decklist against format construction rules.

Pure async function with no MCP awareness. Accepts a bulk data client as a
keyword argument and returns a formatted markdown string. The workflow server
(``server.py``) registers this as an MCP tool and handles ToolError conversion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from mtg_mcp_server.utils.color_identity import is_within_identity
from mtg_mcp_server.utils.decklist import parse_decklist
from mtg_mcp_server.utils.format_rules import (
    FormatRules,
    get_format_rules,
    is_basic_land,
    normalize_format,
)

if TYPE_CHECKING:
    from mtg_mcp_server.services.scryfall_bulk import ScryfallBulkClient
    from mtg_mcp_server.types import Card

log = structlog.get_logger(service="workflow.validation")


async def deck_validate(
    decklist: list[str],
    format: str,
    *,
    commander: str | None = None,
    sideboard: list[str] | None = None,
    bulk: ScryfallBulkClient,
) -> str:
    """Validate a decklist against a format's construction rules.

    Checks deck size, legality, copy limits, color identity (Commander),
    Pauper rarity, and Vintage restricted list. Returns a formatted
    markdown string with VALID/INVALID status and actionable messages.

    Args:
        decklist: Card entries (e.g. ``["4x Lightning Bolt", "Sol Ring"]``).
        format: Format name (e.g. ``"commander"``, ``"modern"``).
        commander: Commander card name (required for Commander-like formats).
        sideboard: Optional sideboard entries.
        bulk: Initialized ScryfallBulkClient.

    Returns:
        Formatted markdown validation result.
    """
    log.info("deck_validate.start", format=format, cards=len(decklist))

    # --- Normalize format ---
    try:
        fmt = normalize_format(format)
    except ValueError as exc:
        return f"# Deck Validation Error\n\n{exc}"

    rules: FormatRules = get_format_rules(fmt)

    # --- Parse decklist ---
    parsed = parse_decklist(decklist)
    if not parsed:
        return f"# Deck Validation - {fmt.title()}\n\nNo cards provided."

    parsed_sideboard = parse_decklist(sideboard) if sideboard else []

    # --- Collect unique names for bulk lookup ---
    unique_names: list[str] = list(
        dict.fromkeys(
            [name for _, name in parsed]
            + [name for _, name in parsed_sideboard]
            + ([commander] if commander else [])
        )
    )
    resolved = await bulk.get_cards(unique_names)

    # --- Run validation checks ---
    errors: list[str] = []
    warnings: list[str] = []

    total_main = sum(qty for qty, _ in parsed)
    total_with_commander = total_main + (1 if commander else 0)

    # Deck size
    if rules.singleton and rules.check_color_identity:
        # Commander-like format: must be exactly min_main (100 for commander)
        if total_with_commander != rules.min_main:
            errors.append(
                f"Deck size: {total_with_commander} cards "
                f"(expected exactly {rules.min_main} including commander)"
            )
    elif total_main < rules.min_main:
        errors.append(f"Deck size: {total_main} cards (minimum {rules.min_main})")

    # Sideboard size
    if rules.max_sideboard is not None and parsed_sideboard:
        sb_total = sum(qty for qty, _ in parsed_sideboard)
        if sb_total > rules.max_sideboard:
            errors.append(f"Sideboard size: {sb_total} cards (maximum {rules.max_sideboard})")

    # Copy limits (aggregate quantities per card name)
    card_quantities: dict[str, int] = {}
    for qty, name in parsed:
        card_quantities[name] = card_quantities.get(name, 0) + qty
    for qty, name in parsed_sideboard:
        card_quantities[name] = card_quantities.get(name, 0) + qty

    if rules.max_copies is not None:
        for name, total_qty in card_quantities.items():
            if is_basic_land(name):
                continue
            if total_qty > rules.max_copies:
                errors.append(f"Too many copies of '{name}': {total_qty} (max {rules.max_copies})")

    # Commander color identity
    commander_identity: frozenset[str] | None = None
    if rules.check_color_identity and commander:
        commander_card = resolved.get(commander)
        if commander_card is not None:
            commander_identity = frozenset(commander_card.color_identity)
        else:
            warnings.append(
                f"Commander '{commander}' not found in bulk data - cannot check color identity"
            )

    # Per-card checks
    resolved_count = 0
    unresolved_names: list[str] = []

    all_entries = list(parsed) + list(parsed_sideboard)
    checked_names: set[str] = set()

    for _, name in all_entries:
        if name in checked_names:
            continue
        checked_names.add(name)

        card: Card | None = resolved.get(name)
        if card is None:
            unresolved_names.append(name)
            continue
        resolved_count += 1

        # Legality
        legality = card.legalities.get(fmt, "not_legal")
        if legality == "banned":
            errors.append(f"'{name}' is banned in {fmt}")
        elif legality == "restricted":
            if not rules.restricted_as_one:
                errors.append(f"'{name}' is restricted in {fmt}")
            # For Vintage, restricted means max 1 copy (checked below)
        elif legality not in ("legal",):
            errors.append(f"'{name}' is not legal in {fmt} (status: {legality})")

        # Vintage restricted: at most 1 copy
        if rules.restricted_as_one and legality == "restricted":
            qty = card_quantities.get(name, 0)
            if qty > 1:
                errors.append(f"'{name}' is restricted in {fmt}: {qty} copies (max 1)")

        # Pauper rarity
        if rules.check_rarity == "common" and card.rarity != "common":
            errors.append(f"'{name}' is {card.rarity} (Pauper requires common rarity)")

        # Color identity
        if (
            commander_identity is not None
            and not is_basic_land(name)
            and not is_within_identity(card.color_identity, commander_identity)
        ):
            card_colors = ", ".join(card.color_identity) or "colorless"
            cmd_colors = ", ".join(sorted(commander_identity)) or "colorless"
            errors.append(
                f"'{name}' ({card_colors}) is outside commander's color identity ({cmd_colors})"
            )

    # Unresolved cards
    if unresolved_names:
        warnings.append(
            f"{len(unresolved_names)} card(s) not found: "
            + ", ".join(unresolved_names[:10])
            + ("..." if len(unresolved_names) > 10 else "")
        )

    # --- Format output ---
    is_valid = len(errors) == 0
    header = "VALID" if is_valid else "INVALID"

    lines: list[str] = [f"# {'V' if is_valid else 'X'} {header} - {fmt.title()}", ""]

    if errors:
        lines.append(f"**{len(errors)} error(s):**")
        lines.append("")
        for err in errors:
            lines.append(f"- {err}")
        lines.append("")

    if warnings:
        lines.append(f"**{len(warnings)} warning(s):**")
        lines.append("")
        for warn in warnings:
            lines.append(f"- {warn}")
        lines.append("")

    if not errors and not warnings:
        lines.append("All checks passed.")
        lines.append("")

    lines.append("---")
    lines.append(
        f"*{sum(qty for qty, _ in parsed)} cards checked, "
        f"{resolved_count} resolved, "
        f"{len(unresolved_names)} unresolved*"
    )

    log.info("deck_validate.complete", format=fmt, valid=is_valid, errors=len(errors))
    return "\n".join(lines)
