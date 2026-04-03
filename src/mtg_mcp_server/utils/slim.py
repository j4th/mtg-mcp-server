"""Slim dict builders for reducing structured_content response sizes.

Each function extracts only the essential fields from a Pydantic model,
producing a plain dict suitable for ``ToolResult.structured_content``.
Full model data remains available via single-card tools or resource URIs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mtg_mcp_server.types import Card, Combo, DraftCardRating, EDHRECCard, Rule


def slim_card(card: Card) -> dict:
    """Essential card fields for list/search contexts."""
    return {
        "name": card.name,
        "mana_cost": card.mana_cost,
        "type_line": card.type_line,
        "rarity": card.rarity,
        "price_usd": card.prices.usd,
        "edhrec_rank": card.edhrec_rank,
    }


def slim_rating(card: DraftCardRating) -> dict:
    """Essential draft rating fields (GIH WR, ALSA, IWD)."""
    return {
        "name": card.name,
        "color": card.color,
        "rarity": card.rarity,
        "gih_wr": card.ever_drawn_win_rate,
        "alsa": card.avg_seen,
        "iwd": card.drawn_improvement_win_rate,
        "game_count": card.game_count,
    }


def slim_edhrec_card(card: EDHRECCard) -> dict:
    """Essential EDHREC card fields (synergy, inclusion, deck count)."""
    return {
        "name": card.name,
        "synergy": card.synergy,
        "inclusion": card.inclusion,
        "num_decks": card.num_decks,
    }


def slim_combo(combo: Combo) -> dict:
    """Essential combo fields (card names, results, color identity)."""
    return {
        "id": combo.id,
        "cards": [c.name for c in combo.cards],
        "results": [r.feature_name for r in combo.produces],
        "color_identity": combo.identity,
    }


def slim_rule(rule: Rule) -> dict:
    """Essential rule fields (number + text, no recursive subrules).

    Includes ``subrule_count`` so consumers know when to do a more
    specific lookup for child rules.
    """
    return {
        "number": rule.number,
        "text": rule.text,
        "subrule_count": len(rule.subrules),
    }
