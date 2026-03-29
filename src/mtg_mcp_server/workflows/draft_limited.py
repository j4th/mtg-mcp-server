"""Limited format workflow tools -- sealed pool building, draft signal reading, draft log review.

Pure async functions with no MCP awareness. Accept service clients as keyword
arguments and return ``WorkflowResult``. The workflow server (``server.py``)
registers them as MCP tools and handles ToolError conversion.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from typing import TYPE_CHECKING, Literal

import structlog

from mtg_mcp_server.providers import ATTRIBUTION_17LANDS
from mtg_mcp_server.workflows import WorkflowResult
from mtg_mcp_server.workflows.draft import _fmt_pct

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mtg_mcp_server.services.scryfall_bulk import ScryfallBulkClient
    from mtg_mcp_server.services.seventeen_lands import SeventeenLandsClient
    from mtg_mcp_server.types import Card, DraftCardRating

log = structlog.get_logger(service="workflow.draft_limited")


# ---------------------------------------------------------------------------
# Internal data structures
# ---------------------------------------------------------------------------


@dataclass
class _SealedBuild:
    """A candidate sealed deck build for a color pair."""

    colors: str
    score: float
    deck: list[str]
    land_split: dict[str, int]
    playable_count: int
    curve: dict[int, int]

    def to_dict(self) -> dict[str, object]:
        """Convert to a plain dict for WorkflowResult.data."""
        return {
            "colors": self.colors,
            "score": round(self.score, 3),
            "deck": self.deck,
            "land_split": self.land_split,
            "playable_count": self.playable_count,
            "curve": self.curve,
        }


@dataclass
class _PickData:
    """Internal data for a single pick during signal analysis."""

    name: str
    pick_position: int
    colors: list[str]
    alsa: float | None
    gih_wr: float | None

    def to_dict(self) -> dict[str, object]:
        """Convert to a plain dict for WorkflowResult.data."""
        return {
            "name": self.name,
            "pick_position": self.pick_position,
            "colors": self.colors,
            "alsa": self.alsa,
            "gih_wr": self.gih_wr,
        }


@dataclass
class _PickAnalysis:
    """Internal data for a single pick during log review."""

    pick_label: str
    name: str
    color: str
    rarity: str
    gih_wr: float | None

    def to_dict(self) -> dict[str, object]:
        """Convert to a plain dict for WorkflowResult.data."""
        return {
            "pick_label": self.pick_label,
            "name": self.name,
            "color": self.color,
            "rarity": self.rarity,
            "gih_wr": self.gih_wr,
        }


# All five MTG colors for pair enumeration.
_COLORS = ["W", "U", "B", "R", "G"]

# Two-color pair combinations (10 total).
_COLOR_PAIRS: list[tuple[str, str]] = list(combinations(_COLORS, 2))

# Cards per pack in a standard draft (used for pack/pick number formatting).
_CARDS_PER_PACK = 14

# Default number of nonland cards in a limited deck.
_NONLAND_TARGET = 23

# Default number of lands in a limited deck.
_LAND_TARGET = 17

# How many top builds to show.
_MAX_BUILDS = 3

# Minimum on-color playable cards to consider a color pair viable.
# In a real sealed pool (~84 cards) you'd typically have 20+ in your best pair.
# Lowered to allow small pools (testing) to still produce builds.
_MIN_PLAYABLES = 8

# Regex to detect land type lines.
_LAND_RE = re.compile(r"\bLand\b", re.IGNORECASE)

# Grade thresholds based on average GIH WR (17Lands baseline is ~56%).
_GRADE_THRESHOLDS: list[tuple[float, str]] = [
    (0.62, "A+"),
    (0.60, "A"),
    (0.58, "A-"),
    (0.57, "B+"),
    (0.56, "B"),
    (0.55, "B-"),
    (0.54, "C+"),
    (0.53, "C"),
    (0.52, "C-"),
    (0.50, "D"),
]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _is_land(card: Card) -> bool:
    """Return True if a card is a land (not a playable spell)."""
    return bool(_LAND_RE.search(card.type_line))


def _build_rating_lookup(ratings: list[DraftCardRating]) -> dict[str, DraftCardRating]:
    """Build a case-insensitive lookup dict from card ratings."""
    return {r.name.lower(): r for r in ratings}


def _card_colors(card: Card) -> set[str]:
    """Extract colors from a card. Uses colors field, falls back to color_identity."""
    if card.colors:
        return set(card.colors)
    return set(card.color_identity)


def _heuristic_score(card: Card) -> float:
    """Score a card heuristically when no 17Lands data is available.

    Scoring:
    - Mythic/rare with removal or card advantage keywords: 5.0
    - Uncommon removal or efficient creature: 4.0
    - Solid creature (on-curve): 3.0
    - Filler: 1.5
    - Truly bad: 0.5
    """
    text = (card.oracle_text or "").lower()
    rarity = card.rarity.lower()
    type_line = card.type_line.lower()
    keywords = {k.lower() for k in card.keywords}

    # Check for removal indicators
    is_removal = any(
        kw in text for kw in ("destroy", "exile", "damage", "fight", "-x/-x", "gets -")
    )
    # Check for card advantage
    is_card_advantage = "draw" in text or "create" in text

    # Check for evasion keywords
    has_evasion = bool(keywords & {"flying", "trample", "menace", "unblockable"})

    if rarity in ("mythic", "rare"):
        if is_removal or is_card_advantage or has_evasion:
            return 5.0
        return 4.0
    if rarity == "uncommon":
        if is_removal or is_card_advantage:
            return 4.0
        if has_evasion:
            return 3.5
        return 3.0
    # Common
    if is_removal:
        return 3.5
    if is_card_advantage:
        return 3.0
    if has_evasion:
        return 3.0
    if "creature" in type_line:
        # On-curve creature: decent stats for its cost
        return 2.0
    return 1.5


def _grade_from_avg_wr(avg_wr: float) -> str:
    """Convert an average GIH WR to a letter grade."""
    for threshold, grade in _GRADE_THRESHOLDS:
        if avg_wr >= threshold:
            return grade
    return "F"


def _format_mana_curve(cards: list[Card]) -> str:
    """Build a simple text-based mana curve visualization."""
    buckets: dict[int, int] = {i: 0 for i in range(8)}
    for card in cards:
        if _is_land(card):
            continue
        cmc = int(card.cmc) if card.cmc < 7 else 7
        buckets[cmc] = buckets.get(cmc, 0) + 1

    headers = ["0", "1", "2", "3", "4", "5", "6", "7+"]
    counts = [str(buckets[i]) for i in range(8)]
    return (
        "| "
        + " | ".join(headers)
        + " |\n|"
        + "|".join("---" for _ in headers)
        + "|\n| "
        + " | ".join(counts)
        + " |"
    )


def _pick_label(pick_index: int) -> str:
    """Convert a 0-based pick index to P<pack>P<pick> format."""
    pack = (pick_index // _CARDS_PER_PACK) + 1
    pick = (pick_index % _CARDS_PER_PACK) + 1
    return f"P{pack}P{pick}"


# ---------------------------------------------------------------------------
# sealed_pool_build
# ---------------------------------------------------------------------------


async def sealed_pool_build(
    pool: list[str],
    set_code: str,
    *,
    bulk: ScryfallBulkClient,
    seventeen_lands: SeventeenLandsClient | None = None,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Suggest the best 40-card sealed deck builds from a card pool.

    Args:
        pool: Card names in the sealed pool (typically 84-90 cards).
        set_code: Three-letter set code (e.g. "LRW").
        bulk: Initialized ScryfallBulkClient for card resolution.
        seventeen_lands: Optional 17Lands client for GIH WR scoring.
        on_progress: Optional progress callback (step, total).
        response_format: "detailed" or "concise".

    Returns:
        WorkflowResult with markdown builds and structured data.
    """
    log.info("sealed_pool_build.start", set_code=set_code, pool_size=len(pool))

    if not pool:
        return WorkflowResult(
            markdown=f"# Sealed Pool Build -- {set_code}\n\nNo cards in pool.",
            data={"set_code": set_code, "builds": [], "unresolved": []},
        )

    # Step 1/3: Resolve pool cards via bulk data
    if on_progress is not None:
        await on_progress(1, 3)

    card_map = await bulk.get_cards(pool)
    resolved: list[Card] = []
    unresolved: list[str] = []
    for name in pool:
        card = card_map.get(name)
        if card is not None:
            resolved.append(card)
        else:
            unresolved.append(name)

    # Separate lands from nonlands
    nonlands = [c for c in resolved if not _is_land(c)]

    # Step 2/3: Fetch 17Lands ratings if available
    if on_progress is not None:
        await on_progress(2, 3)

    rating_lookup: dict[str, DraftCardRating] = {}
    has_ratings = False
    if seventeen_lands is not None:
        try:
            ratings = await seventeen_lands.card_ratings(set_code)
            rating_lookup = _build_rating_lookup(ratings)
            has_ratings = True
        except Exception:
            log.warning("sealed_pool_build.17lands_failed", set_code=set_code)

    # Step 3/3: Evaluate builds per color pair
    if on_progress is not None:
        await on_progress(3, 3)

    builds: list[_SealedBuild] = []
    for c1, c2 in _COLOR_PAIRS:
        pair_colors = {c1, c2}
        pair_label = c1 + c2

        # Collect on-color nonland cards
        on_color: list[Card] = []
        for card in nonlands:
            card_clrs = _card_colors(card)
            if not card_clrs or card_clrs <= pair_colors:
                on_color.append(card)

        if len(on_color) < _MIN_PLAYABLES:
            continue

        # Score each card
        scored: list[tuple[Card, float]] = []
        for card in on_color:
            if has_ratings:
                rating = rating_lookup.get(card.name.lower())
                if rating is not None and rating.ever_drawn_win_rate is not None:
                    scored.append((card, rating.ever_drawn_win_rate))
                else:
                    scored.append((card, _heuristic_score(card) / 10.0))
            else:
                scored.append((card, _heuristic_score(card) / 10.0))

        # Sort by score descending
        scored.sort(key=lambda t: -t[1])

        # Take best _NONLAND_TARGET cards for the deck
        deck_cards = scored[:_NONLAND_TARGET]
        total_score = sum(s for _, s in deck_cards)

        # Mana curve bonus: penalize builds with too many expensive cards
        cmc_counts: dict[int, int] = {i: 0 for i in range(8)}
        for card, _ in deck_cards:
            bucket = int(card.cmc) if card.cmc < 7 else 7
            cmc_counts[bucket] += 1
        # Ideal: peak at 2-3 CMC
        curve_bonus = (cmc_counts.get(2, 0) + cmc_counts.get(3, 0)) * 0.01

        # Bomb bonus for mythic/rare high-score cards
        bomb_bonus = sum(
            0.05
            for card, score in deck_cards
            if card.rarity.lower() in ("mythic", "rare") and score >= 0.55
        )

        deck_score = total_score + curve_bonus + bomb_bonus

        # Compute land split based on color pip ratio
        color_pip_counts: Counter[str] = Counter()
        for card, _ in deck_cards:
            for clr in _card_colors(card):
                if clr in pair_colors:
                    color_pip_counts[clr] += 1

        total_pips = sum(color_pip_counts.values()) or 1
        land_split: dict[str, int] = {}
        remaining_lands = _LAND_TARGET
        for color in sorted(pair_colors):
            ratio = color_pip_counts.get(color, 0) / total_pips
            land_count = max(1, round(ratio * _LAND_TARGET))
            land_split[color] = land_count
            remaining_lands -= land_count
        # Distribute leftover to the heavier color
        if remaining_lands != 0:
            heavier = max(pair_colors, key=lambda c: color_pip_counts.get(c, 0))
            land_split[heavier] = land_split.get(heavier, 0) + remaining_lands

        builds.append(
            _SealedBuild(
                colors=pair_label,
                score=round(deck_score, 3),
                deck=[card.name for card, _ in deck_cards],
                land_split=land_split,
                playable_count=len(on_color),
                curve=dict(cmc_counts),
            )
        )

    # Sort builds by score descending
    builds.sort(key=lambda b: -b.score)
    top_builds = builds[:_MAX_BUILDS]

    # Format output
    lines: list[str] = []
    lines.append(f"# Sealed Pool Build -- {set_code}")
    lines.append("")
    lines.append(f"**Pool size:** {len(resolved)} resolved ({len(unresolved)} unresolved)")
    lines.append(f"**Nonland cards:** {len(nonlands)}")
    scoring_method = "17Lands GIH WR" if has_ratings else "Heuristic"
    lines.append(f"**Scoring:** {scoring_method}")
    lines.append("")

    if not top_builds:
        lines.append("No viable 2-color builds found. Pool may be too shallow.")
    else:
        for i, build in enumerate(top_builds, 1):
            lines.append(f"## Build {i}: {build.colors} (score: {build.score:.2f})")
            lines.append("")

            # Deck list
            lines.append(f"**Spells ({len(build.deck)}):** {', '.join(build.deck[:10])}")
            if len(build.deck) > 10 and response_format == "detailed":
                lines.append(f"  ...and {len(build.deck) - 10} more")
            lines.append("")

            # Lands
            land_parts = [f"{count} {color}" for color, count in sorted(build.land_split.items())]
            lines.append(f"**Lands ({_LAND_TARGET}):** {', '.join(land_parts)}")
            lines.append("")

            # Mana curve
            if response_format == "detailed":
                lines.append("**Mana Curve:**")
                lines.append("")
                deck_names = set(build.deck)
                deck_obj_list = [c for c in nonlands if c.name in deck_names]
                lines.append(_format_mana_curve(deck_obj_list))
                lines.append("")

            # Key cards (top 5 by score)
            if response_format == "detailed":
                lines.append("**Key cards:** " + ", ".join(build.deck[:5]))
                lines.append("")

    if unresolved:
        lines.append("### Unresolved Cards")
        lines.append("")
        for name in unresolved:
            lines.append(f"- {name}")
        lines.append("")

    lines.append(ATTRIBUTION_17LANDS if has_ratings else "")

    log.info(
        "sealed_pool_build.complete",
        set_code=set_code,
        builds=len(top_builds),
        unresolved=len(unresolved),
    )

    return WorkflowResult(
        markdown="\n".join(lines),
        data={
            "set_code": set_code,
            "builds": [b.to_dict() for b in top_builds],
            "unresolved": unresolved,
            "scoring_method": scoring_method,
        },
    )


# ---------------------------------------------------------------------------
# draft_signal_read
# ---------------------------------------------------------------------------


async def draft_signal_read(
    picks: list[str],
    set_code: str,
    *,
    bulk: ScryfallBulkClient,
    seventeen_lands: SeventeenLandsClient,
    current_pack: list[str] | None = None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Analyze draft picks to detect open color signals and recommend direction.

    Args:
        picks: Card names picked so far, in draft order.
        set_code: Three-letter set code.
        bulk: Initialized ScryfallBulkClient for card resolution.
        seventeen_lands: Initialized SeventeenLandsClient.
        current_pack: Optional current pack contents to rank.
        response_format: "detailed" or "concise".

    Returns:
        WorkflowResult with signal analysis and optional pack ranking.
    """
    log.info("draft_signal_read.start", set_code=set_code, pick_count=len(picks))

    if not picks:
        return WorkflowResult(
            markdown=f"# Draft Signal Analysis -- {set_code}\n\nNo picks to analyze.",
            data={"set_code": set_code, "signals": {}, "color_counts": {}, "recommendation": ""},
        )

    # Fetch 17Lands ratings
    ratings = await seventeen_lands.card_ratings(set_code)
    rating_lookup = _build_rating_lookup(ratings)

    # Resolve picks via bulk data for color info (batch)
    pick_card_map = await bulk.get_cards(picks)
    color_counts: Counter[str] = Counter()
    pick_data: list[_PickData] = []

    for i, name in enumerate(picks):
        card = pick_card_map.get(name)
        rating = rating_lookup.get(name.lower())
        pick_position = i + 1  # 1-based

        card_colors: set[str] = set()
        if card is not None:
            card_colors = _card_colors(card)
        elif rating is not None and rating.color:
            card_colors = set(rating.color)

        for clr in card_colors:
            color_counts[clr] += 1

        pick_data.append(
            _PickData(
                name=name,
                pick_position=pick_position,
                colors=sorted(card_colors),
                alsa=rating.avg_seen if rating is not None else None,
                gih_wr=rating.ever_drawn_win_rate if rating is not None else None,
            )
        )

    # Signal detection: positive signal = color is open (cards seen later than ALSA)
    # For each pick, if pick_position > ALSA, the card was seen later than expected
    # which means fewer people are drafting that color.
    # We approximate: if you took a card at pick N and its ALSA is M,
    # then signal = N - M (positive = open, negative = contested).
    color_signals: dict[str, float] = {c: 0.0 for c in _COLORS}
    for pd in pick_data:
        if pd.alsa is not None:
            # Pack-relative position for signal calculation
            pack_pos = ((pd.pick_position - 1) % _CARDS_PER_PACK) + 1
            signal = pack_pos - pd.alsa
            for clr in pd.colors:
                if clr in color_signals:
                    color_signals[clr] += signal

    # Format output
    lines: list[str] = []
    lines.append(f"# Draft Signal Analysis -- {set_code}")
    lines.append("")

    # Color commitment
    if color_counts:
        total_picks = sum(color_counts.values())
        lines.append("## Color Commitment")
        lines.append("")
        for clr, cnt in color_counts.most_common():
            pct = cnt / total_picks * 100
            lines.append(f"- **{clr}**: {cnt} picks ({pct:.0f}%)")
        lines.append("")

    # Signal analysis
    lines.append("## Color Signals")
    lines.append("")
    lines.append("Positive = color appears open. Negative = contested.")
    lines.append("")

    sorted_signals = sorted(color_signals.items(), key=lambda t: -t[1])
    for clr, signal in sorted_signals:
        indicator = "OPEN" if signal > 1.0 else "contested" if signal < -1.0 else "neutral"
        lines.append(f"- **{clr}**: {signal:+.1f} ({indicator})")
    lines.append("")

    # Recommendation
    committed_colors = [clr for clr, _ in color_counts.most_common(2)] if color_counts else []
    open_colors = [clr for clr, sig in sorted_signals if sig > 0.5]

    recommendation = ""
    if committed_colors and open_colors:
        overlap = set(committed_colors) & set(open_colors)
        if overlap:
            recommendation = (
                f"Stay the course in {'/'.join(sorted(overlap))} -- your colors appear open."
            )
        else:
            recommendation = f"Your picks lean {'/'.join(committed_colors)} but signals favor {'/'.join(open_colors[:2])}. Consider pivoting if early enough."
    elif committed_colors:
        recommendation = f"Committed to {'/'.join(committed_colors)}. Signal data is neutral."
    else:
        recommendation = "Too early to determine direction."

    lines.append(f"**Recommendation:** {recommendation}")
    lines.append("")

    # Current pack ranking
    if current_pack:
        lines.append("## Current Pack")
        lines.append("")

        pack_ranked: list[tuple[str, float | None, bool]] = []
        committed_set = set(committed_colors)
        for card_name in current_pack:
            rating = rating_lookup.get(card_name.lower())
            gih_wr = rating.ever_drawn_win_rate if rating is not None else None
            card_clrs: set[str] = set()
            if rating is not None and rating.color:
                card_clrs = set(rating.color)
            on_color = bool(card_clrs & committed_set) if committed_set else True
            pack_ranked.append((card_name, gih_wr, on_color))

        # Sort: on-color with high GIH WR first, then off-color bombs
        pack_ranked.sort(key=lambda t: (not t[2], -(t[1] or 0.0)))

        if response_format == "detailed":
            lines.append("| Rank | Card | GIH WR | Color Fit |")
            lines.append("|------|------|--------|-----------|")
            for rank, (card_name, gih_wr, on_color) in enumerate(pack_ranked, 1):
                fit = "on-color" if on_color else "off-color"
                lines.append(f"| {rank}. | {card_name} | {_fmt_pct(gih_wr)} | {fit} |")
        else:
            for rank, (card_name, gih_wr, on_color) in enumerate(pack_ranked, 1):
                fit = "[on]" if on_color else "[off]"
                lines.append(f"{rank}. {card_name} ({_fmt_pct(gih_wr)}) {fit}")
        lines.append("")

    lines.append(ATTRIBUTION_17LANDS)

    log.info("draft_signal_read.complete", set_code=set_code, pick_count=len(picks))

    return WorkflowResult(
        markdown="\n".join(lines),
        data={
            "set_code": set_code,
            "signals": color_signals,
            "color_counts": dict(color_counts),
            "recommendation": recommendation,
            "picks": [p.to_dict() for p in pick_data],
        },
    )


# ---------------------------------------------------------------------------
# draft_log_review
# ---------------------------------------------------------------------------


async def draft_log_review(
    picks: list[str],
    set_code: str,
    *,
    bulk: ScryfallBulkClient,
    seventeen_lands: SeventeenLandsClient,
    final_deck: list[str] | None = None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Review a completed draft -- pick-by-pick analysis with grade.

    Args:
        picks: Card names in draft order (P1P1 through P3P14).
        set_code: Three-letter set code.
        bulk: Initialized ScryfallBulkClient for card resolution.
        seventeen_lands: Initialized SeventeenLandsClient.
        final_deck: Optional final deck list for inclusion analysis.
        response_format: "detailed" or "concise".

    Returns:
        WorkflowResult with pick-by-pick analysis and overall grade.
    """
    log.info("draft_log_review.start", set_code=set_code, pick_count=len(picks))

    if not picks:
        return WorkflowResult(
            markdown=f"# Draft Log Review -- {set_code}\n\nNo picks to review.",
            data={
                "set_code": set_code,
                "picks": [],
                "avg_gih_wr": None,
                "color_counts": {},
                "grade": "F",
            },
        )

    # Fetch 17Lands ratings
    ratings = await seventeen_lands.card_ratings(set_code)
    rating_lookup = _build_rating_lookup(ratings)

    # Analyze each pick (batch card resolution)
    log_card_map = await bulk.get_cards(picks)
    pick_analysis: list[_PickAnalysis] = []
    gih_wr_values: list[float] = []
    color_counts: Counter[str] = Counter()

    for i, name in enumerate(picks):
        label = _pick_label(i)
        rating = rating_lookup.get(name.lower())
        card = log_card_map.get(name)

        gih_wr: float | None = None
        color = ""
        rarity = ""

        if rating is not None:
            gih_wr = rating.ever_drawn_win_rate
            color = rating.color
            rarity = rating.rarity
        elif card is not None:
            color = "".join(sorted(card.colors)) if card.colors else ""
            rarity = card.rarity

        if gih_wr is not None:
            gih_wr_values.append(gih_wr)

        # Track colors
        for clr in color:
            if clr in _COLORS:
                color_counts[clr] += 1

        pick_analysis.append(
            _PickAnalysis(
                pick_label=label,
                name=name,
                color=color,
                rarity=rarity,
                gih_wr=gih_wr,
            )
        )

    # Compute overall metrics
    avg_gih_wr = statistics.mean(gih_wr_values) if gih_wr_values else None
    grade = _grade_from_avg_wr(avg_gih_wr) if avg_gih_wr is not None else "N/A"

    # Final deck analysis
    final_deck_set: set[str] | None = None
    sideboard_high_wr: list[dict[str, object]] = []
    deck_inclusion_rate: float | None = None

    if final_deck is not None:
        final_deck_set = {n.lower() for n in final_deck}
        picks_in_deck = sum(1 for p in picks if p.lower() in final_deck_set)
        deck_inclusion_rate = picks_in_deck / len(picks) if picks else None

        # Find sideboarded cards with high GIH WR
        for pa in pick_analysis:
            if (
                pa.name.lower() not in final_deck_set
                and pa.gih_wr is not None
                and pa.gih_wr >= 0.55
            ):
                sideboard_high_wr.append({"name": pa.name, "gih_wr": pa.gih_wr})

    # Format output
    lines: list[str] = []
    lines.append(f"# Draft Log Review -- {set_code}")
    lines.append("")
    lines.append(f"**Total picks:** {len(picks)}")
    if avg_gih_wr is not None:
        lines.append(f"**Average GIH WR:** {_fmt_pct(avg_gih_wr)}")
    lines.append(f"**Draft Grade:** {grade}")
    lines.append("")

    # Color breakdown
    if color_counts:
        lines.append("## Color Distribution")
        lines.append("")
        for clr, cnt in color_counts.most_common():
            lines.append(f"- **{clr}**: {cnt} picks")
        lines.append("")

    # Pick-by-pick table
    lines.append("## Pick-by-Pick")
    lines.append("")

    if response_format == "detailed":
        lines.append("| Pick | Card | Color | Rarity | GIH WR |")
        lines.append("|------|------|-------|--------|--------|")
        for pa in pick_analysis:
            wr_str = _fmt_pct(pa.gih_wr) if pa.gih_wr is not None else "N/A"
            in_deck = ""
            if final_deck_set is not None:
                in_deck = " *" if pa.name.lower() not in final_deck_set else ""
            lines.append(
                f"| {pa.pick_label} | {pa.name}{in_deck} | {pa.color} | {pa.rarity} | {wr_str} |"
            )
    else:
        for pa in pick_analysis:
            wr_str = _fmt_pct(pa.gih_wr) if pa.gih_wr is not None else "N/A"
            lines.append(f"- {pa.pick_label}: {pa.name} ({wr_str})")

    lines.append("")

    # Key decision points (detailed only)
    if response_format == "detailed" and len(pick_analysis) >= 3:
        lines.append("## Key Moments")
        lines.append("")
        # Highlight top 3 highest GIH WR picks
        rated_picks = [(pa, pa.gih_wr) for pa in pick_analysis if pa.gih_wr is not None]
        if rated_picks:
            rated_picks.sort(key=lambda t: -(t[1] or 0.0))
            lines.append("**Best picks:**")
            for pa, wr in rated_picks[:3]:
                lines.append(f"- {pa.pick_label} {pa.name} ({_fmt_pct(wr)})")
            lines.append("")

    # Final deck analysis
    if final_deck is not None:
        lines.append("## Final Deck Analysis")
        lines.append("")
        if deck_inclusion_rate is not None:
            lines.append(f"**Cards drafted that made the cut:** {deck_inclusion_rate:.0%}")
        if sideboard_high_wr:
            lines.append("")
            lines.append("**High-WR cards left in sideboard** (potential mistakes):")
            for sb in sideboard_high_wr:
                sb_name = sb["name"]
                sb_wr = sb["gih_wr"]
                if isinstance(sb_wr, float):
                    lines.append(f"- {sb_name} (GIH WR: {_fmt_pct(sb_wr)})")
        lines.append("")

    lines.append(ATTRIBUTION_17LANDS)

    log.info(
        "draft_log_review.complete",
        set_code=set_code,
        picks=len(picks),
        avg_gih_wr=avg_gih_wr,
        grade=grade,
    )

    data: dict[str, object] = {
        "set_code": set_code,
        "picks": [pa.to_dict() for pa in pick_analysis],
        "avg_gih_wr": avg_gih_wr,
        "color_counts": dict(color_counts),
        "grade": grade,
    }
    if final_deck is not None:
        data["deck_inclusion_rate"] = deck_inclusion_rate
        data["sideboard_high_wr"] = sideboard_high_wr

    return WorkflowResult(markdown="\n".join(lines), data=data)
