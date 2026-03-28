"""Parse MTG color identity strings from community formats to canonical sets.

Handles guild names (azorius), shard names (bant), wedge names (sultai),
four-color names (glint), five-color (wubrg/5c), color words (blue),
letter sequences (BUG), and colorless.
"""

from __future__ import annotations

VALID_COLORS = frozenset({"W", "U", "B", "R", "G"})

FIVE_COLOR = VALID_COLORS

_NAMED_IDENTITIES: dict[str, frozenset[str]] = {
    # Guilds (two-color)
    "azorius": frozenset({"W", "U"}),
    "dimir": frozenset({"U", "B"}),
    "rakdos": frozenset({"B", "R"}),
    "gruul": frozenset({"R", "G"}),
    "selesnya": frozenset({"G", "W"}),
    "orzhov": frozenset({"W", "B"}),
    "izzet": frozenset({"U", "R"}),
    "golgari": frozenset({"B", "G"}),
    "boros": frozenset({"R", "W"}),
    "simic": frozenset({"G", "U"}),
    # Shards (three-color, allied)
    "bant": frozenset({"W", "U", "G"}),
    "esper": frozenset({"W", "U", "B"}),
    "grixis": frozenset({"U", "B", "R"}),
    "jund": frozenset({"B", "R", "G"}),
    "naya": frozenset({"R", "G", "W"}),
    # Wedges (three-color, enemy)
    "abzan": frozenset({"W", "B", "G"}),
    "jeskai": frozenset({"W", "U", "R"}),
    "sultai": frozenset({"B", "G", "U"}),
    "mardu": frozenset({"W", "B", "R"}),
    "temur": frozenset({"U", "R", "G"}),
    # Four-color (Nephilim names)
    "glint": frozenset({"U", "B", "R", "G"}),
    "dune": frozenset({"W", "B", "R", "G"}),
    "ink": frozenset({"W", "U", "R", "G"}),
    "witch": frozenset({"W", "U", "B", "G"}),
    "yore": frozenset({"W", "U", "B", "R"}),
    # Five-color
    "wubrg": FIVE_COLOR,
    "5c": FIVE_COLOR,
    # Color words
    "white": frozenset({"W"}),
    "blue": frozenset({"U"}),
    "black": frozenset({"B"}),
    "red": frozenset({"R"}),
    "green": frozenset({"G"}),
    # Colorless
    "colorless": frozenset(),
    "c": frozenset(),
}


def parse_color_identity(value: str) -> frozenset[str]:
    """Parse a color identity string into a frozenset of color letters.

    Accepts guild/shard/wedge/four-color names, color words, letter
    sequences (e.g. ``"BUG"``), ``"wubrg"``/``"5c"``, or ``"colorless"``.
    Case-insensitive.

    Raises:
        ValueError: If the input cannot be parsed as a valid color identity.
    """
    normalized = value.strip().lower()

    if normalized == "":
        return frozenset()

    # Named identity lookup
    if normalized in _NAMED_IDENTITIES:
        return _NAMED_IDENTITIES[normalized]

    # Letter sequence: every character must be a valid color letter
    upper = value.strip().upper()
    letters = frozenset(upper)
    if letters <= VALID_COLORS and len(upper) > 0:
        return letters

    msg = f"Unrecognized color identity: {value!r}"
    raise ValueError(msg)


def is_within_identity(card_identity: list[str], commander_identity: frozenset[str]) -> bool:
    """Check if a card's color identity fits within a commander's identity."""
    return frozenset(card_identity) <= commander_identity
