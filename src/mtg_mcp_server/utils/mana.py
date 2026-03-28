"""Mana pip counting and land suggestion utilities."""

from __future__ import annotations

import re

# Process hybrid BEFORE standard to avoid double-counting letters.
# E.g. {G/W} should give G:0.5, W:0.5 — not G:1, W:1 from separate matches.
_HYBRID_RE = re.compile(r"\{([WUBRG])/([WUBRG])\}")
_PHYREXIAN_RE = re.compile(r"\{([WUBRG])/P\}")
_STANDARD_RE = re.compile(r"\{([WUBRG])\}")

_COMMANDER_FORMATS = frozenset({"commander", "brawl", "oathbreaker", "duel"})


def count_pips(mana_cost: str | None) -> dict[str, float]:
    """Count color pips in a mana cost string, returning color -> count.

    Handles:
    - Standard pips: {W}, {U}, {B}, {R}, {G} -> 1.0 each
    - Hybrid pips: {G/W} -> 0.5 to each color
    - Phyrexian pips: {W/P} -> 0.5 (can be paid with life)
    - Generic {1}, {2}, colorless {C}, {X} -> ignored (not color pips)
    """
    if not mana_cost:
        return {}

    counts: dict[str, float] = {}

    # Strip out hybrid pips first so they don't match as standard pips.
    remaining = mana_cost

    for match in _HYBRID_RE.finditer(remaining):
        c1, c2 = match.group(1), match.group(2)
        counts[c1] = counts.get(c1, 0.0) + 0.5
        counts[c2] = counts.get(c2, 0.0) + 0.5
    remaining = _HYBRID_RE.sub("", remaining)

    # Strip phyrexian pips next (before standard, since {W/P} contains {W}).
    for match in _PHYREXIAN_RE.finditer(remaining):
        color = match.group(1)
        counts[color] = counts.get(color, 0.0) + 0.5
    remaining = _PHYREXIAN_RE.sub("", remaining)

    # Now match standard single-color pips on the remaining string.
    for match in _STANDARD_RE.finditer(remaining):
        color = match.group(1)
        counts[color] = counts.get(color, 0.0) + 1.0

    return counts


def suggest_land_count(avg_cmc: float, format_name: str) -> int:
    """Suggest total land count based on average CMC and format.

    - 60-card formats: roughly 19 + avg_cmc * 2, clamped to [20, 26]
    - Commander-style formats: roughly 33 + avg_cmc * 1.5, clamped to [33, 40]
    """
    if format_name.lower() in _COMMANDER_FORMATS:
        return max(33, min(40, round(33 + avg_cmc * 1.5)))
    return max(20, min(26, round(19 + avg_cmc * 2)))
