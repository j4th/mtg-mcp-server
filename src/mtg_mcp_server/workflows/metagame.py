"""Constructed metagame workflow functions — competitive format analytics.

These are pure async functions with no MCP awareness. They accept service
clients as keyword arguments and return ``WorkflowResult``. The workflow
server (``server.py``) registers them as MCP tools and handles ToolError
conversion.

Tools:
    ``metagame_snapshot`` — Current metagame breakdown with tier assignment.
    ``archetype_decklist`` — Stock decklist for a competitive archetype.
    ``archetype_comparison`` — Side-by-side comparison of 2-4 archetypes.
    ``format_entry_guide`` — Beginner-oriented guide for entering a format.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import TYPE_CHECKING, Literal

import structlog

from mtg_mcp_server.utils.decklist import parse_decklist
from mtg_mcp_server.utils.format_rules import get_format_rules
from mtg_mcp_server.utils.fuzzy import match_archetype
from mtg_mcp_server.utils.slim import slim_archetype
from mtg_mcp_server.workflows import WorkflowResult

if TYPE_CHECKING:
    from mtg_mcp_server.services.mtggoldfish import MTGGoldfishClient
    from mtg_mcp_server.services.scryfall_bulk import ScryfallBulkClient
    from mtg_mcp_server.services.spicerack import SpicerackClient
    from mtg_mcp_server.types import GoldfishArchetype, GoldfishMetaSnapshot

log = structlog.get_logger(service="workflow.metagame")


# ---------------------------------------------------------------------------
# Tier thresholds
# ---------------------------------------------------------------------------

_T1_THRESHOLD = 10.0  # meta share > 10%
_T2_THRESHOLD = 3.0  # meta share 3-10%


def _match_archetype(
    query: str,
    archetypes: list[GoldfishArchetype],
) -> GoldfishArchetype | None:
    """Fuzzy-match a user query against archetype names.

    Delegates to the shared :func:`match_archetype` utility and maps
    the matched name back to the corresponding archetype object.
    """
    names = [a.name for a in archetypes]
    matched_name = match_archetype(query, names)
    if matched_name is None:
        return None
    return next((a for a in archetypes if a.name == matched_name), None)


# ---------------------------------------------------------------------------
# Tier classification
# ---------------------------------------------------------------------------


def _classify_tiers(
    archetypes: list[GoldfishArchetype],
) -> dict[str, list[GoldfishArchetype]]:
    """Classify archetypes into T1/T2/T3 based on meta share."""
    tiers: dict[str, list[GoldfishArchetype]] = {"T1": [], "T2": [], "T3": []}
    for arch in archetypes:
        if arch.meta_share > _T1_THRESHOLD:
            tiers["T1"].append(arch)
        elif arch.meta_share >= _T2_THRESHOLD:
            tiers["T2"].append(arch)
        else:
            tiers["T3"].append(arch)
    return tiers


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _fmt_price(price: int) -> str:
    """Format a paper price integer (USD)."""
    if price > 0:
        return f"${price:,}"
    return "N/A"


def _fmt_meta_share(share: float) -> str:
    """Format meta share percentage."""
    return f"{share:.1f}%"


def _format_tier_table(
    tier_name: str,
    archetypes: list[GoldfishArchetype],
    *,
    concise: bool = False,
) -> list[str]:
    """Format a tier section with table rows."""
    if not archetypes:
        return []
    lines: list[str] = []
    lines.append(f"### {tier_name}")
    lines.append("")
    if concise:
        for arch in archetypes:
            lines.append(
                f"- {arch.name} ({_fmt_meta_share(arch.meta_share)}, "
                f"{_fmt_price(arch.price_paper)})"
            )
    else:
        lines.append("| Archetype | Meta % | Decks | Price |")
        lines.append("|-----------|--------|-------|-------|")
        for arch in archetypes:
            lines.append(
                f"| {arch.name} | {_fmt_meta_share(arch.meta_share)} | "
                f"{arch.deck_count} | {_fmt_price(arch.price_paper)} |"
            )
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Spicerack fallback helpers
# ---------------------------------------------------------------------------


def _estimate_metagame_from_tournaments(
    tournaments: list,
    format_name: str,
) -> WorkflowResult:
    """Estimate meta shares from Spicerack tournament standings.

    Counts archetype appearances via decklist URLs (each unique URL prefix
    is treated as an archetype). Since Spicerack doesn't provide archetype
    names, we count player appearances per tournament and report top
    tournament winners as proxy for "metagame".
    """
    # Count how many top finishes each tournament has
    tournament_count = len(tournaments)
    total_players = sum(t.player_count for t in tournaments)

    lines: list[str] = [
        f"# {format_name} Metagame (Tournament Data)",
        "",
        f"*Based on {tournament_count} recent tournaments ({total_players} total players)*",
        "",
        "**Note:** Archetype breakdown unavailable (MTGGoldfish disabled). "
        "Showing tournament activity summary instead.",
        "",
    ]

    # Show top tournaments
    lines.append("| Tournament | Date | Players |")
    lines.append("|------------|------|---------|")
    for t in tournaments[:10]:
        lines.append(f"| {t.name} | {t.date} | {t.player_count} |")

    data: dict[str, object] = {
        "format": format_name,
        "source": "spicerack",
        "tournament_count": tournament_count,
        "total_players": total_players,
        "tiers": {"T1": [], "T2": [], "T3": []},
        "archetypes": [],
    }
    return WorkflowResult(markdown="\n".join(lines), data=data)


# ---------------------------------------------------------------------------
# Workflow functions
# ---------------------------------------------------------------------------


async def metagame_snapshot(
    format: str,
    *,
    mtggoldfish: MTGGoldfishClient | None,
    spicerack: SpicerackClient | None,
    bulk: ScryfallBulkClient | None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Get the current metagame breakdown for a competitive format.

    Primary path uses MTGGoldfish for archetype-level data. Falls back to
    Spicerack tournament frequency if MTGGoldfish is unavailable. Returns
    an error message if neither source is available.

    Args:
        format: Format name (e.g. "Modern", "Legacy", "Pioneer").
        mtggoldfish: Initialized MTGGoldfishClient, or None if disabled.
        spicerack: Initialized SpicerackClient, or None if disabled.
        bulk: Initialized ScryfallBulkClient, or None if disabled.
        response_format: "detailed" or "concise".

    Returns:
        WorkflowResult with markdown and structured data.
    """
    log.info("metagame_snapshot.start", format=format)
    concise = response_format == "concise"

    # Primary path: MTGGoldfish
    if mtggoldfish is not None:
        try:
            snapshot: GoldfishMetaSnapshot = await mtggoldfish.get_metagame(format)
        except Exception as exc:
            log.warning(
                "metagame_snapshot.mtggoldfish_failed",
                format=format,
                error=str(exc),
            )
            # Fall through to Spicerack
        else:
            tiers = _classify_tiers(snapshot.archetypes)
            lines: list[str] = [
                f"# {format.title()} Metagame",
                "",
                f"*Source: MTGGoldfish ({snapshot.total_decks} decks analyzed)*",
                "",
            ]

            for tier_name in ("T1", "T2", "T3"):
                lines.extend(_format_tier_table(tier_name, tiers[tier_name], concise=concise))

            if not concise:
                lines.append("---")
                lines.append("**Data Sources:** [MTGGoldfish](https://www.mtggoldfish.com)")

            log.info(
                "metagame_snapshot.complete",
                format=format,
                source="mtggoldfish",
                archetypes=len(snapshot.archetypes),
            )

            data: dict[str, object] = {
                "format": format,
                "source": "mtggoldfish",
                "tiers": {k: [slim_archetype(a) for a in v] for k, v in tiers.items()},
                "archetypes": [slim_archetype(a) for a in snapshot.archetypes],
            }
            return WorkflowResult(markdown="\n".join(lines), data=data)

    # Fallback path: Spicerack
    if spicerack is not None:
        try:
            tournaments = await spicerack.get_tournaments(
                event_format=format.title(),
            )
        except Exception as exc:
            log.warning(
                "metagame_snapshot.spicerack_failed",
                format=format,
                error=str(exc),
            )
        else:
            if tournaments:
                log.info(
                    "metagame_snapshot.complete",
                    format=format,
                    source="spicerack",
                    tournaments=len(tournaments),
                )
                return _estimate_metagame_from_tournaments(tournaments, format.title())

    # Neither source available
    log.warning("metagame_snapshot.no_sources", format=format)
    return WorkflowResult(
        markdown=(
            f"No metagame data available for {format}.\n\n"
            "Enable MTGGoldfish (`MTG_MCP_ENABLE_MTGGOLDFISH=true`) or "
            "Spicerack (`MTG_MCP_ENABLE_SPICERACK=true`) for metagame data."
        ),
        data={
            "format": format,
            "source": None,
            "tiers": {"T1": [], "T2": [], "T3": []},
            "archetypes": [],
        },
    )


async def archetype_decklist(
    format: str,
    archetype: str,
    *,
    mtggoldfish: MTGGoldfishClient,
    bulk: ScryfallBulkClient | None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Get the stock decklist for a competitive archetype.

    Uses MTGGoldfish metagame data to fuzzy-match the archetype name, then
    fetches the full decklist. Optionally resolves cards via bulk data for
    pricing.

    Args:
        format: Format name (e.g. "Modern").
        archetype: Archetype name (e.g. "Boros Energy").
        mtggoldfish: Initialized MTGGoldfishClient (required).
        bulk: Initialized ScryfallBulkClient, or None if disabled.
        response_format: "detailed" or "concise".

    Returns:
        WorkflowResult with markdown and structured data.
    """
    log.info("archetype_decklist.start", format=format, archetype=archetype)
    concise = response_format == "concise"

    # Get metagame for archetype matching
    snapshot = await mtggoldfish.get_metagame(format)
    matched = _match_archetype(archetype, snapshot.archetypes)

    if matched is None:
        available = [a.name for a in snapshot.archetypes[:20]]
        return WorkflowResult(
            markdown=(
                f"Archetype '{archetype}' not found in {format.title()} metagame.\n\n"
                f"Available archetypes:\n" + "\n".join(f"- {name}" for name in available)
            ),
            data={
                "format": format,
                "archetype": archetype,
                "error": "not_found",
                "available_archetypes": available,
            },
        )

    # Fetch the archetype detail using the matched name (not slug — slug is already format-prefixed)
    detail = await mtggoldfish.get_archetype(format, matched.name)

    # Optionally resolve card prices via bulk data
    total_price: float | None = None
    if bulk is not None and detail.mainboard:
        parsed = parse_decklist(detail.mainboard)
        card_names = [name for _, name in parsed]
        quantities = {name: qty for qty, name in parsed}

        try:
            cards = await bulk.get_cards(card_names)
            price_sum = 0.0
            has_prices = False
            for name, card in cards.items():
                if card is not None and card.prices.usd is not None:
                    price_sum += float(card.prices.usd) * quantities.get(name, 1)
                    has_prices = True
            if has_prices:
                total_price = round(price_sum, 2)
        except Exception as exc:
            log.warning(
                "archetype_decklist.bulk_pricing_failed",
                error=str(exc),
            )

    # Build markdown
    lines: list[str] = [
        f"# {matched.name} ({format.title()})",
        "",
    ]

    if not concise:
        if detail.author:
            lines.append(f"**Author:** {detail.author}")
        if detail.event:
            lines.append(f"**Event:** {detail.event}")
        if detail.result:
            lines.append(f"**Result:** {detail.result}")
        if detail.date:
            lines.append(f"**Date:** {detail.date}")
        lines.append(f"**Meta Share:** {_fmt_meta_share(matched.meta_share)}")
        if total_price is not None:
            lines.append(f"**Estimated Price:** ${total_price:,.2f}")
        elif matched.price_paper > 0:
            lines.append(f"**Estimated Price:** {_fmt_price(matched.price_paper)}")
        lines.append("")

    # Mainboard
    if detail.mainboard:
        lines.append("## Mainboard")
        lines.append("")
        for entry in detail.mainboard:
            lines.append(f"- {entry}")
        lines.append("")

    # Sideboard
    if detail.sideboard:
        lines.append("## Sideboard")
        lines.append("")
        for entry in detail.sideboard:
            lines.append(f"- {entry}")
        lines.append("")

    if not concise:
        lines.append("---")
        lines.append("**Data Sources:** [MTGGoldfish](https://www.mtggoldfish.com)")

    log.info(
        "archetype_decklist.complete",
        format=format,
        archetype=matched.name,
        mainboard_count=len(detail.mainboard),
        sideboard_count=len(detail.sideboard),
    )

    data: dict[str, object] = {
        "format": format,
        "archetype": matched.name,
        "slug": matched.slug,
        "meta_share": matched.meta_share,
        "mainboard": detail.mainboard,
        "sideboard": detail.sideboard,
        "total_price": total_price,
        "author": detail.author,
        "event": detail.event,
        "result": detail.result,
        "date": detail.date,
    }
    return WorkflowResult(markdown="\n".join(lines), data=data)


async def archetype_comparison(
    format: str,
    archetypes: list[str],
    *,
    mtggoldfish: MTGGoldfishClient,
    bulk: ScryfallBulkClient | None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Compare 2-4 competitive archetypes side-by-side.

    Gets metagame data, fuzzy-matches each archetype name, fetches decklists
    concurrently, and builds a comparison table with shared staples.

    Args:
        format: Format name (e.g. "Modern").
        archetypes: 2-4 archetype names to compare.
        mtggoldfish: Initialized MTGGoldfishClient (required).
        bulk: Initialized ScryfallBulkClient, or None if disabled.
        response_format: "detailed" or "concise".

    Returns:
        WorkflowResult with markdown and structured data.
    """
    log.info(
        "archetype_comparison.start",
        format=format,
        archetypes=archetypes,
    )
    concise = response_format == "concise"

    # Get metagame for archetype matching
    snapshot = await mtggoldfish.get_metagame(format)

    # Match each archetype name
    matched_archetypes: list[GoldfishArchetype] = []
    not_found: list[str] = []
    for name in archetypes:
        matched = _match_archetype(name, snapshot.archetypes)
        if matched is not None:
            matched_archetypes.append(matched)
        else:
            not_found.append(name)

    if len(matched_archetypes) < 2:
        available = [a.name for a in snapshot.archetypes[:20]]
        return WorkflowResult(
            markdown=(
                f"Could not match enough archetypes for comparison.\n\n"
                f"Not found: {', '.join(not_found)}\n\n"
                f"Available archetypes:\n" + "\n".join(f"- {name}" for name in available)
            ),
            data={
                "format": format,
                "error": "insufficient_matches",
                "not_found": not_found,
                "available_archetypes": available,
            },
        )

    # Fetch decklists concurrently
    fetch_tasks = [mtggoldfish.get_archetype(format, arch.slug) for arch in matched_archetypes]
    detail_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

    # Build comparison table
    lines: list[str] = [
        f"# Archetype Comparison: {format.title()}",
        "",
    ]

    # Comparison table header
    header = "| Metric | " + " | ".join(a.name for a in matched_archetypes) + " |"
    separator = "|--------|" + "|".join("-----" for _ in matched_archetypes) + "|"
    lines.append(header)
    lines.append(separator)

    # Meta share row
    row = (
        "| Meta Share | "
        + " | ".join(_fmt_meta_share(a.meta_share) for a in matched_archetypes)
        + " |"
    )
    lines.append(row)

    # Deck count row
    row = "| Deck Count | " + " | ".join(str(a.deck_count) for a in matched_archetypes) + " |"
    lines.append(row)

    # Price row
    row = "| Price | " + " | ".join(_fmt_price(a.price_paper) for a in matched_archetypes) + " |"
    lines.append(row)

    # Colors row
    row = (
        "| Colors | "
        + " | ".join(", ".join(a.colors) if a.colors else "N/A" for a in matched_archetypes)
        + " |"
    )
    lines.append(row)

    # Mainboard/Sideboard size rows
    mainboard_sizes: list[str] = []
    sideboard_sizes: list[str] = []
    all_mainboard_cards: list[Counter[str]] = []

    for i, result in enumerate(detail_results):
        if isinstance(result, BaseException):
            log.warning(
                "archetype_comparison.fetch_failed",
                archetype=matched_archetypes[i].name,
                error=str(result),
            )
            mainboard_sizes.append("N/A")
            sideboard_sizes.append("N/A")
            all_mainboard_cards.append(Counter())
        else:
            mainboard_sizes.append(str(len(result.mainboard)))
            sideboard_sizes.append(str(len(result.sideboard)))
            parsed = parse_decklist(result.mainboard)
            all_mainboard_cards.append(Counter(name for _, name in parsed))

    row = "| Mainboard | " + " | ".join(mainboard_sizes) + " |"
    lines.append(row)
    row = "| Sideboard | " + " | ".join(sideboard_sizes) + " |"
    lines.append(row)

    lines.append("")

    # Shared staples: cards appearing in 2+ archetypes
    if not concise and len(all_mainboard_cards) >= 2:
        # Count how many archetypes each card appears in
        card_archetype_count: Counter[str] = Counter()
        for cards_counter in all_mainboard_cards:
            for card_name in cards_counter:
                card_archetype_count[card_name] += 1

        shared = [name for name, count in card_archetype_count.most_common() if count >= 2]

        if shared:
            lines.append("## Shared Staples")
            lines.append("")
            lines.append(f"Cards appearing in 2+ archetypes ({len(shared)} total):")
            lines.append("")
            for name in shared[:15]:
                in_count = card_archetype_count[name]
                lines.append(f"- **{name}** (in {in_count} archetypes)")
            if len(shared) > 15:
                lines.append(f"- ...and {len(shared) - 15} more")
            lines.append("")

    if not_found:
        lines.append(f"**Not found:** {', '.join(not_found)}")
        lines.append("")

    if not concise:
        lines.append("---")
        lines.append("**Data Sources:** [MTGGoldfish](https://www.mtggoldfish.com)")

    log.info(
        "archetype_comparison.complete",
        format=format,
        compared=len(matched_archetypes),
        not_found=not_found,
    )

    data: dict[str, object] = {
        "format": format,
        "archetypes": [slim_archetype(a) for a in matched_archetypes],
        "not_found": not_found,
    }
    return WorkflowResult(markdown="\n".join(lines), data=data)


async def format_entry_guide(
    format: str,
    *,
    mtggoldfish: MTGGoldfishClient | None,
    spicerack: SpicerackClient | None,
    bulk: ScryfallBulkClient | None,
    budget: float | None = None,
    response_format: Literal["detailed", "concise"] = "detailed",
) -> WorkflowResult:
    """Beginner-oriented guide for entering a competitive format.

    Combines metagame data with format rules and budget filtering to help
    new players choose their first deck.

    Args:
        format: Format name (e.g. "Modern").
        mtggoldfish: Initialized MTGGoldfishClient, or None if disabled.
        spicerack: Initialized SpicerackClient, or None if disabled.
        bulk: Initialized ScryfallBulkClient, or None if disabled.
        budget: Optional maximum budget in USD for deck filtering.
        response_format: "detailed" or "concise".

    Returns:
        WorkflowResult with markdown and structured data.
    """
    log.info("format_entry_guide.start", format=format, budget=budget)
    concise = response_format == "concise"

    # Try to get typed metagame data directly for the mtggoldfish path,
    # falling back to metagame_snapshot() for spicerack/no-source paths.
    source: str | None = None
    goldfish_archetypes: list[GoldfishArchetype] = []

    if mtggoldfish is not None:
        try:
            snapshot = await mtggoldfish.get_metagame(format)
            source = "mtggoldfish"
            goldfish_archetypes = snapshot.archetypes
        except Exception as exc:
            log.warning(
                "format_entry_guide.mtggoldfish_failed",
                format=format,
                error=str(exc),
            )

    # Fallback: use metagame_snapshot for spicerack or no-source
    snapshot_result: WorkflowResult | None = None
    if source is None:
        snapshot_result = await metagame_snapshot(
            format,
            mtggoldfish=None,  # Already failed or unavailable
            spicerack=spicerack,
            bulk=bulk,
            response_format=response_format,
        )
        raw_source = snapshot_result.data.get("source")
        source = str(raw_source) if raw_source is not None else None

    lines: list[str] = [
        f"# {format.title()} Format Entry Guide",
        "",
    ]

    # Format rules section
    format_lower = format.lower()
    rules = None
    try:
        rules = get_format_rules(format_lower)
    except KeyError:
        log.debug("format_entry_guide.no_format_rules", format=format)

    if rules is not None and not concise:
        lines.append("## Format Rules")
        lines.append("")
        lines.append(f"- **Minimum deck size:** {rules.min_main} cards")
        if rules.max_sideboard is not None:
            lines.append(f"- **Maximum sideboard:** {rules.max_sideboard} cards")
        if rules.max_copies is not None:
            lines.append(f"- **Maximum copies:** {rules.max_copies} per card")
        if rules.singleton:
            lines.append("- **Singleton:** Yes (1 copy per card)")
        if rules.restricted_as_one:
            lines.append("- **Restricted cards:** Limited to 1 copy (Vintage)")
        lines.append("")

    # Budget-sorted archetypes (typed path — no dict[str, object] issues)
    if source == "mtggoldfish" and goldfish_archetypes:
        # Sort by price (cheapest first), filter to priced archetypes
        priced = [a for a in goldfish_archetypes if a.price_paper > 0]
        priced.sort(key=lambda a: a.price_paper)

        # Apply budget filter
        if budget is not None:
            priced = [a for a in priced if a.price_paper <= budget]

        lines.append("## Archetypes by Budget")
        lines.append("")

        if priced:
            if budget is not None:
                lines.append(f"*Showing archetypes under ${budget:,.0f}*")
                lines.append("")

            if concise:
                for arch in priced:
                    lines.append(
                        f"- {arch.name} "
                        f"({_fmt_price(arch.price_paper)}, "
                        f"{_fmt_meta_share(arch.meta_share)})"
                    )
            else:
                lines.append("| Archetype | Price | Meta % | Decks |")
                lines.append("|-----------|-------|--------|-------|")
                for arch in priced:
                    lines.append(
                        f"| {arch.name} | "
                        f"{_fmt_price(arch.price_paper)} | "
                        f"{_fmt_meta_share(arch.meta_share)} | "
                        f"{arch.deck_count} |"
                    )
            lines.append("")
        else:
            if budget is not None:
                lines.append(
                    f"No archetypes found under ${budget:,.0f}. Consider increasing your budget."
                )
            else:
                lines.append("No pricing data available for archetypes.")
            lines.append("")

        # Recommended first deck
        if priced and not concise:
            cheapest = priced[0]
            lines.append("## Recommended First Deck")
            lines.append("")
            lines.append(
                f"**{cheapest.name}** at "
                f"{_fmt_price(cheapest.price_paper)} "
                f"is the most affordable option with "
                f"{_fmt_meta_share(cheapest.meta_share)} meta share."
            )
            lines.append("")

    elif source == "spicerack":
        lines.append("## Tournament Activity")
        lines.append("")
        lines.append(
            "Archetype pricing unavailable (MTGGoldfish disabled). "
            "Enable it for budget-sorted deck recommendations."
        )
        lines.append("")
    else:
        lines.append("## Metagame Data")
        lines.append("")
        if snapshot_result is not None:
            lines.append(snapshot_result.markdown)
        else:
            lines.append("No metagame data available.")
        lines.append("")

    # Cross-archetype staples from bulk data
    if bulk is not None and not concise:
        try:
            staples = await bulk.filter_cards(
                format=format_lower,
                limit=10,
            )
            if staples:
                lines.append("## Format Staples")
                lines.append("")
                lines.append("Most commonly played cards in the format:")
                lines.append("")
                for card in staples[:10]:
                    price_str = f"${card.prices.usd}" if card.prices.usd is not None else "N/A"
                    lines.append(f"- **{card.name}** ({card.type_line}) — {price_str}")
                lines.append("")
        except Exception as exc:
            log.warning(
                "format_entry_guide.bulk_staples_failed",
                error=str(exc),
            )

    if not concise:
        sources: list[str] = []
        if source == "mtggoldfish":
            sources.append("[MTGGoldfish](https://www.mtggoldfish.com)")
        if source == "spicerack":
            sources.append("[Spicerack](https://spicerack.gg)")
        if bulk is not None:
            sources.append("[Scryfall](https://scryfall.com)")
        if sources:
            lines.append("---")
            lines.append(f"**Data Sources:** {', '.join(sources)}")

    log.info(
        "format_entry_guide.complete",
        format=format,
        source=source,
        budget=budget,
    )

    data: dict[str, object] = {
        "format": format,
        "source": source,
        "budget": budget,
        "rules": {
            "min_main": rules.min_main,
            "max_sideboard": rules.max_sideboard,
            "max_copies": rules.max_copies,
            "singleton": rules.singleton,
        }
        if rules is not None
        else None,
        "archetypes": [slim_archetype(a) for a in goldfish_archetypes]
        if goldfish_archetypes
        else [],
    }
    return WorkflowResult(markdown="\n".join(lines), data=data)
