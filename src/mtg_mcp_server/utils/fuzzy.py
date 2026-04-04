"""Fuzzy matching for archetype and matchup names."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    """Lowercase and strip all non-alphanumeric characters."""
    return _SLUG_RE.sub("", name.lower())


def match_archetype(
    query: str,
    archetypes: list[str],
    threshold: float = 0.6,
) -> str | None:
    """Find the best-matching archetype name for a query string.

    Tries slug-based exact match first, then falls back to
    ``difflib.SequenceMatcher`` ratio scoring.  Returns ``None``
    when no match meets *threshold*.
    """
    if not archetypes:
        return None

    query_slug = _slugify(query)

    # Pass 1: exact slug match
    for name in archetypes:
        if _slugify(name) == query_slug:
            return name

    # Pass 2: substring match (handles partial names like "Boros" → "Boros Energy")
    query_lower = query.lower()
    for name in archetypes:
        name_lower = name.lower()
        if query_lower in name_lower or name_lower in query_lower:
            return name

    # Pass 3: word overlap (handles reordering like "Control Azorius" → "Azorius Control")
    query_words = set(query_lower.split())
    best_name: str | None = None
    best_overlap = 0
    for name in archetypes:
        overlap = len(query_words & set(name.lower().split()))
        if overlap > best_overlap:
            best_overlap = overlap
            best_name = name

    if best_overlap >= 2:
        return best_name

    # Pass 4: ratio-based fuzzy match
    best_name = None
    best_ratio = 0.0

    for name in archetypes:
        ratio = SequenceMatcher(None, query_lower, name.lower()).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_name = name

    if best_ratio >= threshold:
        return best_name
    return None
