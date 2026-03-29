"""Price comparison workflow — compare card prices side by side.

Pure async function with no MCP awareness. Accepts a bulk data client as a
keyword argument and returns a formatted markdown string. The workflow server
(``server.py``) registers this as an MCP tool and handles ToolError conversion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import structlog

from mtg_mcp_server.workflows import WorkflowResult

if TYPE_CHECKING:
    from mtg_mcp_server.services.scryfall_bulk import ScryfallBulkClient
    from mtg_mcp_server.types import Card

log = structlog.get_logger(service="workflow.pricing")


def _price_sort_key(usd: str | None) -> tuple[int, float]:
    """Sort key for USD prices. Cards with prices sort before N/A, descending."""
    if usd is None:
        return (1, 0.0)
    try:
        return (0, -float(usd))
    except ValueError:
        log.debug("price_sort.invalid_usd", usd=usd)
        return (1, 0.0)


async def price_comparison(
    cards: list[str],
    *,
    bulk: ScryfallBulkClient,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Compare prices across multiple cards using Scryfall bulk data.

    Deduplicates card names, looks up prices via bulk data, and returns
    a markdown table sorted by USD price descending. Includes a total row.

    Args:
        cards: Card names to compare (deduplication handled internally).
        bulk: Initialized ScryfallBulkClient.

    Returns:
        WorkflowResult with markdown and structured data.
    """
    log.info("price_comparison.start", cards=len(cards))

    # Deduplicate while preserving order
    unique_cards = list(dict.fromkeys(cards))
    resolved = await bulk.get_cards(unique_cards)

    # Build price data
    rows: list[tuple[str, str | None, str | None, str | None, bool]] = []
    # (name, usd, usd_foil, eur, found)

    for name in unique_cards:
        card: Card | None = resolved.get(name)
        if card is None:
            rows.append((name, None, None, None, False))
        else:
            rows.append(
                (
                    card.name,
                    card.prices.usd,
                    card.prices.usd_foil,
                    card.prices.eur,
                    True,
                )
            )

    # Sort by USD descending (None values last)
    rows.sort(key=lambda r: _price_sort_key(r[1]))

    # Build table
    lines: list[str] = [
        "# Price Comparison",
        "",
        "| Card | USD | USD Foil | EUR |",
        "|------|-----|----------|-----|",
    ]

    total_usd = 0.0
    total_usd_available = False

    for name, usd, usd_foil, eur, found in rows:
        if not found:
            lines.append(f"| {name} | Not Found | - | - |")
            continue

        usd_str = f"${usd}" if usd is not None else "N/A"
        foil_str = f"${usd_foil}" if usd_foil is not None else "N/A"
        eur_str = f"{eur} EUR" if eur is not None else "N/A"

        lines.append(f"| {name} | {usd_str} | {foil_str} | {eur_str} |")

        if usd is not None:
            try:
                total_usd += float(usd)
                total_usd_available = True
            except ValueError:
                log.debug("price_comparison.invalid_usd", card=name, usd=usd)

    found_count = sum(1 for _, _, _, _, found in rows if found)

    if response_format != "concise":
        # Total row
        lines.append("|------|-----|----------|-----|")
        if total_usd_available:
            lines.append(f"| **Total** | **${total_usd:.2f}** | - | - |")
        else:
            lines.append("| **Total** | **N/A** | - | - |")

        # Summary
        not_found_count = len(rows) - found_count
        lines.append("")
        summary = f"*{found_count} of {len(rows)} cards priced*"
        if not_found_count:
            summary += f" ({not_found_count} not found)"
        lines.append(summary)

        lines.append("")
        lines.append("*Prices from Scryfall bulk data (updated daily)*")

    log.info("price_comparison.complete", cards=len(unique_cards), priced=found_count)
    data = {
        "cards": [
            {"name": name, "usd": usd, "usd_foil": usd_foil, "eur": eur, "found": found}
            for name, usd, usd_foil, eur, found in rows
        ],
        "total_usd": total_usd if total_usd_available else None,
        "found_count": found_count,
        "not_found_count": len(rows) - found_count,
    }
    return WorkflowResult(markdown="\n".join(lines), data=data)
