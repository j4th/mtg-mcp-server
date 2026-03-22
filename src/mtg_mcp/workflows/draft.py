"""Draft workflow tools — rank picks using 17Lands data."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mtg_mcp.services.seventeen_lands import SeventeenLandsClient
    from mtg_mcp.types import DraftCardRating


def _fmt_pct(value: float | None) -> str:
    """Format a float as a percentage string, or 'N/A' if None."""
    if value is None:
        return "N/A"
    return f"{value * 100:.1f}%"


def _fmt_iwd(value: float | None) -> str:
    """Format IWD with a sign prefix, or 'N/A' if None."""
    if value is None:
        return "N/A"
    pct = value * 100
    if pct >= 0:
        return f"+{pct:.1f}%"
    return f"{pct:.1f}%"


def _fmt_float(value: float | None) -> str:
    """Format a float to one decimal place, or 'N/A' if None."""
    if value is None:
        return "N/A"
    return f"{value:.1f}"


def _sort_key(rating: DraftCardRating) -> tuple[int, float]:
    """Sort key: cards with GIH WR first (descending), None GIH WR last."""
    if rating.ever_drawn_win_rate is None:
        return (1, 0.0)
    return (0, -rating.ever_drawn_win_rate)


def _build_color_counts(
    picks: list[str],
    lookup: dict[str, DraftCardRating],
) -> Counter[str]:
    """Count colors across current picks using the ratings lookup."""
    counts: Counter[str] = Counter()
    for pick in picks:
        rating = lookup.get(pick.lower())
        if rating is not None and rating.color:
            for char in rating.color:
                counts[char] += 1
    return counts


async def draft_pack_pick(
    pack: list[str],
    set_code: str,
    *,
    seventeen_lands: SeventeenLandsClient,
    current_picks: list[str] | None = None,
) -> str:
    """Rank cards in a draft pack using 17Lands win rate data.

    Args:
        pack: Card names in the current pack.
        set_code: Three-letter set code (e.g. "LRW").
        seventeen_lands: Initialized SeventeenLandsClient.
        current_picks: Cards already drafted (for color fit analysis).

    Returns:
        Formatted markdown string with ranked cards and stats.
    """
    if not pack:
        return f"# Draft Pack Analysis \u2014 {set_code}\n\nNo cards in pack."

    # Fetch all card ratings for this set
    ratings = await seventeen_lands.card_ratings(set_code)

    # Build case-insensitive lookup
    lookup: dict[str, DraftCardRating] = {r.name.lower(): r for r in ratings}

    # Match pack cards against lookup
    found: list[DraftCardRating] = []
    no_data: list[str] = []
    for card_name in pack:
        rating = lookup.get(card_name.lower())
        if rating is not None:
            found.append(rating)
        else:
            no_data.append(card_name)

    # Sort found cards by GIH WR descending, None GIH WR to end
    found.sort(key=_sort_key)

    # Color analysis from current picks
    pick_colors: Counter[str] | None = None
    if current_picks:
        pick_colors = _build_color_counts(current_picks, lookup)
        # If no colors were found (all picks missing from data), treat as no analysis
        if not pick_colors:
            pick_colors = None

    # Build output
    lines: list[str] = []
    lines.append(f"# Draft Pack Analysis \u2014 {set_code}")
    lines.append("")

    # Color distribution of current picks
    if pick_colors is not None:
        color_parts = [f"{c}({n})" for c, n in pick_colors.most_common()]
        lines.append(f"**Current colors:** {' '.join(color_parts)}")
        lines.append("")

    # Ranked list
    if found:
        lines.append("| Rank | Card | Color | Rarity | GIH WR | ALSA | IWD | Games |")
        lines.append("|------|------|-------|--------|--------|------|-----|-------|")
        for i, rating in enumerate(found, 1):
            color_fit = ""
            if pick_colors is not None:
                card_colors = set(rating.color) if rating.color else set()
                pick_color_set = set(pick_colors.keys())
                color_fit = " [on-color]" if card_colors & pick_color_set else " [off-color]"

            lines.append(
                f"| {i}. | {rating.name}{color_fit} | {rating.color} "
                f"| {rating.rarity} | {_fmt_pct(rating.ever_drawn_win_rate)} "
                f"| {_fmt_float(rating.avg_seen)} | {_fmt_iwd(rating.drawn_improvement_win_rate)} "
                f"| {rating.game_count} |"
            )

    # No data section
    if no_data:
        lines.append("")
        lines.append("### No data")
        lines.append("")
        lines.append("The following cards were not found in 17Lands data for this set:")
        lines.append("")
        for card_name in no_data:
            lines.append(f"- {card_name}")

    return "\n".join(lines)
