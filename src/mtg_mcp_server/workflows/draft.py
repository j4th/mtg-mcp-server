"""Draft workflow tools — rank picks and set overviews using 17Lands data."""

from __future__ import annotations

import statistics
from collections import Counter
from typing import TYPE_CHECKING, Literal

import structlog

from mtg_mcp_server.providers import ATTRIBUTION_17LANDS
from mtg_mcp_server.workflows import WorkflowResult

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mtg_mcp_server.services.seventeen_lands import SeventeenLandsClient
    from mtg_mcp_server.types import DraftCardRating

log = structlog.get_logger(service="workflow.draft")


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


def _append_rarity_table(lines: list[str], heading: str, cards: list[DraftCardRating]) -> None:
    """Append a ranked rarity table section to output lines."""
    lines.append(f"## {heading}")
    lines.append("")
    if cards:
        lines.append("| Rank | Name | Color | GIH WR | ALSA | IWD | Games |")
        lines.append("|------|------|-------|--------|------|-----|-------|")
        for i, r in enumerate(cards, 1):
            lines.append(
                f"| {i}. | {r.name} | {r.color} "
                f"| {_fmt_pct(r.ever_drawn_win_rate)} "
                f"| {_fmt_float(r.avg_seen)} | {_fmt_iwd(r.drawn_improvement_win_rate)} "
                f"| {r.game_count} |"
            )
    else:
        rarity = heading.split()[-1].lower()
        lines.append(f"No {rarity} cards with data.")
    lines.append("")


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
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Rank cards in a draft pack using 17Lands win rate data.

    Args:
        pack: Card names in the current pack.
        set_code: Three-letter set code (e.g. "LRW").
        seventeen_lands: Initialized SeventeenLandsClient.
        current_picks: Cards already drafted (for color fit analysis).

    Returns:
        WorkflowResult with markdown and structured data.
    """
    log.info("draft_pack_pick.start", set_code=set_code, pack_size=len(pack))

    if not pack:
        return WorkflowResult(
            markdown=f"# Draft Pack Analysis \u2014 {set_code}\n\nNo cards in pack.{ATTRIBUTION_17LANDS}",
            data={"set_code": set_code, "rankings": [], "no_data": []},
        )

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
        if response_format == "concise":
            lines.append("| Rank | Card | GIH WR | ALSA |")
            lines.append("|------|------|--------|------|")
            for i, rating in enumerate(found, 1):
                color_fit = ""
                if pick_colors is not None:
                    card_colors = set(rating.color) if rating.color else set()
                    pick_color_set = set(pick_colors.keys())
                    color_fit = " [on-color]" if card_colors & pick_color_set else " [off-color]"

                lines.append(
                    f"| {i}. | {rating.name}{color_fit} "
                    f"| {_fmt_pct(rating.ever_drawn_win_rate)} "
                    f"| {_fmt_float(rating.avg_seen)} |"
                )
        else:
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

    lines.append(ATTRIBUTION_17LANDS)

    log.info("draft_pack_pick.complete", set_code=set_code, found=len(found), no_data=len(no_data))
    data = {
        "set_code": set_code,
        "rankings": [
            {
                "rank": i,
                "name": r.name,
                "color": r.color,
                "rarity": r.rarity,
                "gih_wr": r.ever_drawn_win_rate,
                "alsa": r.avg_seen,
                "iwd": r.drawn_improvement_win_rate,
                "game_count": r.game_count,
            }
            for i, r in enumerate(found, 1)
        ],
        "no_data": no_data,
    }
    return WorkflowResult(markdown="\n".join(lines), data=data)


# ---------------------------------------------------------------------------
# Set overview
# ---------------------------------------------------------------------------

# Number of top-performing cards to show per rarity in set_overview.
_TOP_N = 10


async def set_overview(
    set_code: str,
    *,
    event_type: str = "PremierDraft",
    seventeen_lands: SeventeenLandsClient,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Draft format overview with top commons, top uncommons, and trap rares.

    Args:
        set_code: Three-letter set code (e.g. "LRW").
        event_type: Draft event type (default "PremierDraft").
        seventeen_lands: Initialized SeventeenLandsClient.
        on_progress: Optional progress callback (step, total).

    Returns:
        WorkflowResult with markdown and structured data.
    """
    log.info("set_overview.start", set_code=set_code, event_type=event_type)

    if on_progress is not None:
        await on_progress(1, 2)

    # Fetch card ratings
    ratings = await seventeen_lands.card_ratings(set_code, event_type=event_type)

    # Filter out cards with no GIH WR
    rated: list[DraftCardRating] = [r for r in ratings if r.ever_drawn_win_rate is not None]

    if on_progress is not None:
        await on_progress(2, 2)

    if not rated:
        return WorkflowResult(
            markdown=(
                f"# Set Overview \u2014 {set_code}\n\n"
                f"No card data available for this set. "
                f"Check the set code is correct and that 17Lands has data for {event_type}."
                f"{ATTRIBUTION_17LANDS}"
            ),
            data={
                "set_code": set_code,
                "event_type": event_type,
                "median_gih_wr": None,
                "top_commons": [],
                "top_uncommons": [],
                "trap_rares": [],
            },
        )

    # Single-pass: group by rarity and collect GIH WR values
    by_rarity: dict[str, list[DraftCardRating]] = {
        "common": [],
        "uncommon": [],
        "rare": [],
        "mythic": [],
    }
    all_gih: list[float] = []
    for r in rated:
        rarity = r.rarity.lower()
        if rarity in by_rarity:
            by_rarity[rarity].append(r)
        if r.ever_drawn_win_rate is not None:
            all_gih.append(r.ever_drawn_win_rate)

    median_gih = statistics.median(all_gih) if all_gih else 0.5

    # Sort commons/uncommons by GIH WR descending, take top N
    by_rarity["common"].sort(key=_sort_key)
    by_rarity["uncommon"].sort(key=_sort_key)
    top_n = 5 if response_format == "concise" else _TOP_N
    top_commons = by_rarity["common"][:top_n]
    top_uncommons = by_rarity["uncommon"][:top_n]

    # "Trap" rares/mythics: high-rarity cards that underperform the set median.
    # Drafters often over-pick rares; flagging underperformers helps avoid that.
    trap_rares = [
        r
        for r in by_rarity["rare"] + by_rarity["mythic"]
        if r.ever_drawn_win_rate is not None and r.ever_drawn_win_rate < median_gih
    ]
    trap_rares.sort(key=_sort_key)

    # --- Build output ---
    lines: list[str] = []
    lines.append(f"# Set Overview \u2014 {set_code}")
    lines.append("")
    lines.append(f"**Event type:** {event_type}")
    lines.append(f"**Median GIH WR:** {_fmt_pct(median_gih)}")
    lines.append(f"**Cards with data:** {len(rated)}")
    lines.append("")

    # Top commons and uncommons (same table format)
    _append_rarity_table(lines, "Top Commons", top_commons)
    _append_rarity_table(lines, "Top Uncommons", top_uncommons)

    # Trap rares (detailed only)
    if response_format != "concise":
        lines.append("## Trap Rares/Mythics")
        lines.append("")
        lines.append(
            f"Rares and mythics with GIH WR below the set median ({_fmt_pct(median_gih)}):"
        )
        lines.append("")
        if trap_rares:
            for r in trap_rares:
                lines.append(
                    f"- **{r.name}** ({r.rarity}) \u2014 "
                    f"GIH WR: {_fmt_pct(r.ever_drawn_win_rate)}, "
                    f"ALSA: {_fmt_float(r.avg_seen)}"
                )
        else:
            lines.append("No trap rares found \u2014 all rares/mythics are above the median.")

    lines.append(ATTRIBUTION_17LANDS)

    log.info(
        "set_overview.complete",
        set_code=set_code,
        commons=len(top_commons),
        uncommons=len(top_uncommons),
        trap_rares=len(trap_rares),
    )

    def _rating_dict(r: DraftCardRating) -> dict[str, object]:
        return {
            "name": r.name,
            "color": r.color,
            "rarity": r.rarity,
            "gih_wr": r.ever_drawn_win_rate,
            "alsa": r.avg_seen,
            "iwd": r.drawn_improvement_win_rate,
            "game_count": r.game_count,
        }

    data = {
        "set_code": set_code,
        "event_type": event_type,
        "median_gih_wr": median_gih,
        "top_commons": [_rating_dict(r) for r in top_commons],
        "top_uncommons": [_rating_dict(r) for r in top_uncommons],
        "trap_rares": [_rating_dict(r) for r in trap_rares],
    }
    return WorkflowResult(markdown="\n".join(lines), data=data)
