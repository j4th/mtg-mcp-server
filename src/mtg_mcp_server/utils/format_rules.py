"""Format rules and normalization for Magic: The Gathering constructed/limited formats."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FormatRules:
    """Deck construction rules for a Magic format."""

    min_main: int
    max_sideboard: int | None  # None = unlimited (limited formats)
    max_copies: int | None  # None = unlimited (limited formats)
    singleton: bool = False
    check_color_identity: bool = False
    restricted_as_one: bool = False  # Vintage


_FORMAT_ALIASES: dict[str, str] = {
    "edh": "commander",
    "cedh": "commander",
    "draft": "limited",
    "sealed": "limited",
}

_FORMAT_RULES: dict[str, FormatRules] = {
    "standard": FormatRules(min_main=60, max_sideboard=15, max_copies=4),
    "pioneer": FormatRules(min_main=60, max_sideboard=15, max_copies=4),
    "modern": FormatRules(min_main=60, max_sideboard=15, max_copies=4),
    "legacy": FormatRules(min_main=60, max_sideboard=15, max_copies=4),
    "vintage": FormatRules(min_main=60, max_sideboard=15, max_copies=4, restricted_as_one=True),
    "pauper": FormatRules(min_main=60, max_sideboard=15, max_copies=4),
    "commander": FormatRules(
        min_main=100,
        max_sideboard=0,
        max_copies=1,
        singleton=True,
        check_color_identity=True,
    ),
    "limited": FormatRules(min_main=40, max_sideboard=None, max_copies=None),
    "brawl": FormatRules(
        min_main=60,
        max_sideboard=0,
        max_copies=1,
        singleton=True,
        check_color_identity=True,
    ),
    "oathbreaker": FormatRules(
        min_main=60,
        max_sideboard=0,
        max_copies=1,
        singleton=True,
        check_color_identity=True,
    ),
}

_BASIC_LANDS: frozenset[str] = frozenset(
    {
        "Plains",
        "Island",
        "Swamp",
        "Mountain",
        "Forest",
        "Wastes",
        "Snow-Covered Plains",
        "Snow-Covered Island",
        "Snow-Covered Swamp",
        "Snow-Covered Mountain",
        "Snow-Covered Forest",
    }
)


def normalize_format(raw: str) -> str:
    """Normalize a format name to its canonical form.

    Handles aliases (edh -> commander, draft -> limited) and case insensitivity.
    Raises ValueError for unknown formats.
    """
    lowered = raw.lower()
    resolved = _FORMAT_ALIASES.get(lowered, lowered)
    if resolved not in _FORMAT_RULES:
        msg = f"Unknown format: '{raw}'. Valid formats: {', '.join(sorted(_FORMAT_RULES))}"
        raise ValueError(msg)
    return resolved


def get_format_rules(format_name: str) -> FormatRules:
    """Get deck construction rules for a format.

    Input must be a normalized format name (use normalize_format() first).
    Raises KeyError for unknown formats.
    """
    return _FORMAT_RULES[format_name]


def is_basic_land(name: str) -> bool:
    """Check if a card name is a basic land (exempt from copy limits).

    Uses exact, case-sensitive matching against the canonical basic land names.
    """
    return name in _BASIC_LANDS
