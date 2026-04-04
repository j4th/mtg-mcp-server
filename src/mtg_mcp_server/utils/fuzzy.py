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

    # Pass 2: ratio-based fuzzy match
    query_lower = query.lower()
    best_name: str | None = None
    best_ratio = 0.0

    for name in archetypes:
        ratio = SequenceMatcher(None, query_lower, name.lower()).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_name = name

    if best_ratio >= threshold:
        return best_name
    return None
