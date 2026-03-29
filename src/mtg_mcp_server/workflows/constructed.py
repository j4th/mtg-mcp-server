"""Constructed format workflow functions -- Standard rotation checking.

These are pure async functions with no MCP awareness. They accept service
clients as keyword arguments and return ``WorkflowResult``. The workflow
server (``server.py``) registers them as MCP tools and handles ToolError
conversion.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

import structlog

from mtg_mcp_server.workflows import WorkflowResult

if TYPE_CHECKING:
    from mtg_mcp_server.services.scryfall import ScryfallClient
    from mtg_mcp_server.services.scryfall_bulk import ScryfallBulkClient
    from mtg_mcp_server.types import SetInfo

log = structlog.get_logger(service="workflow.constructed")

# Set types that are eligible for Standard rotation.
# "expansion" covers main sets; "core" covers Core Sets (e.g. M21).
_STANDARD_SET_TYPES: frozenset[str] = frozenset({"expansion", "core"})

# Standard rotation uses a 3-year window from a set's release date.
# Sets released more than ~3 years ago rotate out when the fall set arrives.
_STANDARD_WINDOW_YEARS = 3


def _is_standard_eligible(set_info: SetInfo) -> bool:
    """Check if a set is eligible for Standard (expansion or core set)."""
    return set_info.set_type in _STANDARD_SET_TYPES


def _parse_date(date_str: str | None) -> datetime | None:
    """Parse an ISO date string into a datetime, or None on failure."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def _estimate_rotation_date(standard_sets: list[SetInfo]) -> str | None:
    """Estimate when the next rotation happens.

    Standard rotation occurs when the fall set releases. The oldest sets
    rotate out. Returns an approximate date string or None.
    """
    if not standard_sets:
        return None

    # Find the most recent set release date
    latest: datetime | None = None
    for s in standard_sets:
        dt = _parse_date(s.released_at)
        if dt is not None and (latest is None or dt > latest):
            latest = dt

    if latest is None:
        return None

    # Next rotation is approximately the following September/October
    # from the latest set's release year
    next_year = latest.year
    if latest.month >= 9:
        next_year += 1

    return f"~September {next_year}"


async def rotation_check(
    *,
    scryfall: ScryfallClient,
    bulk: ScryfallBulkClient,
    cards: list[str] | None = None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Check Standard rotation status and which cards are in rotating sets.

    Fetches all sets from Scryfall, identifies Standard-legal sets,
    determines rotation timing, and optionally checks which provided
    cards are in sets that will rotate.

    Args:
        scryfall: Initialized ScryfallClient.
        bulk: Initialized ScryfallBulkClient.
        cards: Optional list of card names to check for rotation.
        response_format: Output verbosity.

    Returns:
        WorkflowResult with rotation info and structured data.
    """
    log.info("rotation_check.start", cards_count=len(cards) if cards else 0)

    # Step 1: Fetch all sets
    all_sets = await scryfall.get_sets()

    # Step 2: Filter to Standard-eligible sets (expansion/core)
    now = datetime.now(tz=UTC)
    cutoff = now.replace(year=now.year - _STANDARD_WINDOW_YEARS)

    standard_sets: list[SetInfo] = []
    for s in all_sets:
        if not _is_standard_eligible(s):
            continue
        released = _parse_date(s.released_at)
        if released is None:
            continue
        # Must be released (not future) and within the Standard window
        if released <= now and released > cutoff:
            standard_sets.append(s)

    # Sort by release date (oldest first)
    standard_sets.sort(key=lambda s: s.released_at or "")

    rotation_date = _estimate_rotation_date(standard_sets)

    # Step 3: Check specific cards if provided
    cards_checked: list[dict[str, object]] | None = None
    unresolved: list[str] = []

    if cards:
        resolved_map = await bulk.get_cards(cards)
        cards_checked = []

        standard_codes = {s.code for s in standard_sets}

        # Pre-compute oldest year once (not per card)
        oldest_year = _oldest_standard_year(standard_sets)

        for name in cards:
            card = resolved_map.get(name)
            if card is None:
                unresolved.append(name)
                continue

            is_standard = card.legalities.get("standard") == "legal"
            in_set = card.set_code if hasattr(card, "set_code") else ""
            rotating = in_set in standard_codes and _is_set_rotating(
                in_set, standard_sets, oldest_year
            )

            cards_checked.append(
                {
                    "name": card.name,
                    "set_code": in_set,
                    "standard_legal": is_standard,
                    "rotating_soon": rotating,
                }
            )

    # Build output
    lines: list[str] = []

    if response_format == "concise":
        lines.append("# Standard Rotation")
        lines.append("")
        lines.append(f"**Sets in Standard:** {len(standard_sets)}")
        if rotation_date:
            lines.append(f"**Next rotation:** {rotation_date}")
        if cards_checked:
            rotating_count = sum(1 for c in cards_checked if c.get("rotating_soon"))
            lines.append(f"**Cards checked:** {len(cards_checked)} ({rotating_count} rotating)")
    else:
        lines.append("# Standard Rotation Check")
        lines.append("")
        if rotation_date:
            lines.append(f"**Next rotation:** {rotation_date}")
        lines.append(f"**Sets in Standard:** {len(standard_sets)}")
        lines.append("")

        # Set list
        lines.append("## Standard-Legal Sets")
        lines.append("")
        if standard_sets:
            lines.append("| Set | Code | Released |")
            lines.append("|-----|------|----------|")
            for s in standard_sets:
                lines.append(f"| {s.name} | {s.code.upper()} | {s.released_at or 'N/A'} |")
        else:
            lines.append("No Standard-legal sets found.")
        lines.append("")

        # Card check results
        if cards_checked:
            lines.append("## Card Rotation Status")
            lines.append("")
            lines.append("| Card | Set | Standard Legal | Rotating Soon |")
            lines.append("|------|-----|----------------|---------------|")
            for c in cards_checked:
                legal = "Yes" if c["standard_legal"] else "No"
                rotating = "Yes" if c.get("rotating_soon") else "No"
                lines.append(f"| {c['name']} | {c['set_code']} | {legal} | {rotating} |")
            lines.append("")

        if unresolved:
            lines.append("## Not Found")
            lines.append("")
            for name in unresolved:
                lines.append(f"- {name}")

    log.info(
        "rotation_check.complete",
        standard_sets=len(standard_sets),
        cards_checked=len(cards_checked) if cards_checked else 0,
    )

    data: dict[str, object] = {
        "standard_sets": [
            {
                "code": s.code,
                "name": s.name,
                "released_at": s.released_at,
                "set_type": s.set_type,
            }
            for s in standard_sets
        ],
        "rotation_date": rotation_date,
        "cards_checked": cards_checked,
        "unresolved": unresolved if unresolved else None,
    }
    return WorkflowResult(markdown="\n".join(lines), data=data)


def _oldest_standard_year(standard_sets: list[SetInfo]) -> int | None:
    """Find the oldest release year among Standard-legal sets."""
    oldest: int | None = None
    for s in standard_sets:
        dt = _parse_date(s.released_at)
        if dt is not None and (oldest is None or dt.year < oldest):
            oldest = dt.year
    return oldest


def _is_set_rotating(
    set_code: str,
    standard_sets: list[SetInfo],
    oldest_year: int | None,
) -> bool:
    """Check if a set is among the oldest that will rotate next."""
    if not standard_sets or oldest_year is None:
        return False

    target_set: SetInfo | None = None
    for s in standard_sets:
        if s.code == set_code:
            target_set = s
            break

    if target_set is None:
        return False

    released = _parse_date(target_set.released_at)
    if released is None:
        return False

    return released.year == oldest_year
