"""Natural-language MTG card query parser.

Translates natural-language queries like "2-drop creatures" or "removal"
into structured filter criteria for bulk data search.
"""

import re
from dataclasses import dataclass

# Pre-compiled patterns for N-drop queries
_NDROP_TYPE_RE = re.compile(r"(\d+)[- ]?drops?\s+(\w+)", re.IGNORECASE)
_NDROP_RE = re.compile(r"(\d+)[- ]?drops?$", re.IGNORECASE)

# Type word singularization: plural -> singular (title-cased for type_line matching)
_TYPE_SINGULAR: dict[str, str] = {
    "creatures": "Creature",
    "instants": "Instant",
    "sorceries": "Sorcery",
    "enchantments": "Enchantment",
    "artifacts": "Artifact",
    "planeswalkers": "Planeswalker",
    "lands": "Land",
}


@dataclass(frozen=True)
class QueryFilters:
    """Structured filter criteria parsed from a natural-language query."""

    type_contains: tuple[str, ...] = ()
    text_contains: tuple[str, ...] = ()
    text_any: tuple[str, ...] = ()
    cmc_eq: float | None = None
    cmc_lte: float | None = None
    description: str = ""


def _normalize_type_word(word: str) -> str:
    """Convert a type word to its title-cased singular form for type_line matching."""
    lower = word.lower()
    if lower in _TYPE_SINGULAR:
        return _TYPE_SINGULAR[lower]
    # Already singular or unknown -- title-case it
    return word.capitalize()


def parse_query(query: str) -> QueryFilters:
    """Parse a natural-language MTG card query into structured filters.

    Supports patterns like:
    - "2-drop creatures" -> cmc_eq=2.0, type_contains=("Creature",)
    - "removal" -> text_any with destroy/exile/damage patterns
    - "card draw" -> text_any with draw patterns
    - "ramp" -> text_any with mana/land search patterns
    - "board wipe" / "wrath" -> text_any with "destroy all" etc.
    - "counter" / "counterspell" -> text_any + type_contains=("Instant",)
    - "tutor" -> text_any with "search your library"
    - Unrecognized -> text_contains=(query,) (oracle text substring)
    """
    query_stripped = query.strip()
    query_lower = query_stripped.lower()

    # 1. N-drop with type: "2-drop creatures", "3 drop instants"
    m = _NDROP_TYPE_RE.match(query_stripped)
    if m:
        cmc = float(m.group(1))
        type_word = _normalize_type_word(m.group(2))
        return QueryFilters(
            cmc_eq=cmc,
            type_contains=(type_word,),
            description=f"CMC {int(cmc)} {type_word} cards",
        )

    # 2. N-drop without type: "3-drops"
    m = _NDROP_RE.match(query_stripped)
    if m:
        cmc = float(m.group(1))
        return QueryFilters(cmc_eq=cmc, description=f"CMC {int(cmc)} cards")

    # 3. Board wipe / wrath / mass removal (checked before generic "removal")
    if "board wipe" in query_lower or "wrath" in query_lower or "mass removal" in query_lower:
        return QueryFilters(
            text_any=("destroy all", "exile all", "all creatures get -"),
            description="Board wipes and mass removal",
        )

    # 4. Removal (after board wipe so "mass removal" matches correctly)
    if "removal" in query_lower:
        return QueryFilters(
            text_any=(
                "destroy target",
                "exile target",
                "deals damage to",
                "-X/-X",
                "target creature gets",
            ),
            description="Removal spells (destroy, exile, damage)",
        )

    # 5. Card draw
    if "card draw" in query_lower or "draw" in query_lower:
        return QueryFilters(
            text_any=("draw a card", "draw cards", "draws a card"),
            description="Card draw effects",
        )

    # 6. Ramp (consumer lowercases oracle text, so patterns are lowercase)
    if "ramp" in query_lower:
        return QueryFilters(
            text_any=(
                "add {",
                "search your library for a basic land",
                "search your library for a land",
            ),
            description="Mana ramp effects",
        )

    # 7. Counter / counterspell
    if "counter" in query_lower:
        return QueryFilters(
            text_any=("counter target spell", "counter target"),
            type_contains=("Instant",),
            description="Counterspells",
        )

    # 8. Tutor
    if "tutor" in query_lower:
        return QueryFilters(
            text_any=("search your library",),
            description="Tutor effects (search library)",
        )

    # 9. Fallback: treat as oracle text substring
    return QueryFilters(
        text_contains=(query_stripped,),
        description=f"Oracle text contains '{query_stripped}'",
    )
