"""Shared formatting helpers for card data across providers and workflows."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from mtg_mcp_server.types import Card

ResponseFormat = Literal["detailed", "concise"]


def format_card_line(card: Card, *, response_format: ResponseFormat = "detailed") -> str:
    """Format a single card as a one-line summary.

    Detailed: "  Name {cost} -- Type · $price"
    Concise: "  Name {cost}"
    """
    if response_format == "concise":
        return f"  {card.name} {card.mana_cost or ''}"
    price = f" · ${card.prices.usd}" if card.prices.usd else ""
    return f"  {card.name} {card.mana_cost or ''} — {card.type_line}{price}"


def format_card_detail(card: Card, *, response_format: ResponseFormat = "detailed") -> list[str]:
    """Format full card details as a list of lines.

    Detailed: Full output with all fields.
    Concise: Name, mana cost, type, and price only.
    """
    if response_format == "concise":
        lines = [
            f"**{card.name}** {card.mana_cost or ''}",
            f"Type: {card.type_line}",
        ]
        if card.prices.usd:
            lines.append(f"Price: ${card.prices.usd}")
        return lines

    # Detailed (default) -- full output
    lines = [
        f"**{card.name}** {card.mana_cost or ''}",
        f"Type: {card.type_line}",
    ]
    if card.oracle_text:
        lines.append(f"Text: {card.oracle_text}")
    if card.power is not None and card.toughness is not None:
        lines.append(f"P/T: {card.power}/{card.toughness}")
    lines.append(f"Colors: {', '.join(card.colors) or 'Colorless'}")
    lines.append(f"Color Identity: {', '.join(card.color_identity) or 'Colorless'}")
    if card.keywords:
        lines.append(f"Keywords: {', '.join(card.keywords)}")
    if card.set_code:
        lines.append(f"Set: {card.set_code.upper()} ({card.rarity})")
    if card.prices.usd:
        lines.append(f"Price: ${card.prices.usd} (foil: ${card.prices.usd_foil or 'N/A'})")
    if card.edhrec_rank is not None:
        lines.append(f"EDHREC Rank: {card.edhrec_rank}")
    return lines
