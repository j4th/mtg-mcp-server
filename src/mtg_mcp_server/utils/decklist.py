"""Decklist parsing utilities shared across workflow modules."""

from __future__ import annotations

import re

_QTY_RE = re.compile(r"^(\d+)x?\s+(.+)$")


def parse_decklist(entries: list[str]) -> list[tuple[int, str]]:
    """Parse decklist entries into (quantity, card_name) tuples.

    Supports "4x Card Name", "4 Card Name", and "Card Name" (default qty 1).
    """
    parsed: list[tuple[int, str]] = []
    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue
        m = _QTY_RE.match(entry)
        if m:
            qty = int(m.group(1))
            name = m.group(2).strip()
        else:
            qty = 1
            name = entry
        if name:
            parsed.append((qty, name))
    return parsed
