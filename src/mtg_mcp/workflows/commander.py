"""Commander workflow functions — composed tools calling multiple services.

These are pure async functions with no MCP awareness. They accept service
clients as keyword arguments and return formatted markdown strings. The
workflow server (``server.py``) registers them as MCP tools and handles
ToolError conversion.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mtg_mcp.services.edhrec import EDHRECClient
    from mtg_mcp.services.scryfall import ScryfallClient
    from mtg_mcp.services.spellbook import SpellbookClient
    from mtg_mcp.types import Card, Combo, EDHRECCard, EDHRECCommanderData

log = structlog.get_logger(service="workflow.commander")

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

_MAX_COMBOS = 5
_MAX_STAPLES = 10


def _fmt_synergy(value: float) -> str:
    """Format a synergy score with sign prefix (e.g. '+61%' or '-5%')."""
    return f"+{value:.0%}" if value >= 0 else f"{value:.0%}"


def _format_card_header(card: Card) -> list[str]:
    """Format the card header section for a commander overview."""
    lines = [
        f"# {card.name}",
        "",
        f"**Mana Cost:** {card.mana_cost or 'N/A'}",
        f"**Type:** {card.type_line}",
    ]
    if card.oracle_text:
        lines.append(f"**Text:** {card.oracle_text}")
    if card.color_identity:
        lines.append(f"**Color Identity:** {', '.join(card.color_identity)}")
    if card.power is not None and card.toughness is not None:
        lines.append(f"**P/T:** {card.power}/{card.toughness}")
    lines.append(f"**Rarity:** {card.rarity}")
    if card.edhrec_rank is not None:
        lines.append(f"**EDHREC Rank:** {card.edhrec_rank}")
    return lines


def _format_card_details(card: Card) -> list[str]:
    """Format card details for an upgrade evaluation."""
    lines = [
        f"# {card.name}",
        "",
        f"**Mana Cost:** {card.mana_cost or 'N/A'}",
        f"**Type:** {card.type_line}",
    ]
    if card.oracle_text:
        lines.append(f"**Text:** {card.oracle_text}")
    price = card.prices.usd
    if price is not None:
        lines.append(f"**Price:** ${price}")
    else:
        lines.append("**Price:** N/A")
    if card.edhrec_rank is not None:
        lines.append(f"**EDHREC Rank:** {card.edhrec_rank}")
    return lines


def _format_combos_section(combos: list[Combo]) -> list[str]:
    """Format the combos section."""
    lines = ["", "## Combos", ""]
    if not combos:
        lines.append("No combos found for this card.")
        return lines
    lines.append(f"Found {len(combos)} combo(s):")
    for combo in combos[:_MAX_COMBOS]:
        card_names = ", ".join(c.name for c in combo.cards) or "(no cards listed)"
        results = ", ".join(p.feature_name for p in combo.produces) or "(no results listed)"
        lines.append(f"- **[{combo.id}]** {card_names}")
        lines.append(f"  Produces: {results}")
    return lines


def _format_edhrec_staples(data: EDHRECCommanderData) -> list[str]:
    """Format the EDHREC staples section."""
    lines = ["", "## EDHREC Staples", ""]
    lines.append(f"Based on {data.total_decks} decks:")
    lines.append("")

    # Collect all cards across all cardlists, take top N by inclusion
    all_cards: list[EDHRECCard] = []
    for cardlist in data.cardlists:
        all_cards.extend(cardlist.cardviews)
    all_cards.sort(key=lambda c: c.inclusion, reverse=True)

    for card in all_cards[:_MAX_STAPLES]:
        lines.append(
            f"- **{card.name}** — {card.inclusion}% inclusion, "
            f"{_fmt_synergy(card.synergy)} synergy ({card.num_decks} decks)"
        )
    return lines


def _format_synergy_section(synergy: EDHRECCard | None, commander_name: str) -> list[str]:
    """Format the EDHREC synergy section for an upgrade evaluation."""
    lines = ["", "## Synergy with " + commander_name, ""]
    if synergy is None:
        lines.append("No synergy data found for this card with this commander.")
        return lines
    lines.append(f"**Synergy Score:** {_fmt_synergy(synergy.synergy)}")
    lines.append(f"**Inclusion Rate:** {synergy.inclusion}%")
    lines.append(f"**In Decks:** {synergy.num_decks}")
    if synergy.label:
        lines.append(f"**Label:** {synergy.label}")
    return lines


# ---------------------------------------------------------------------------
# Data source status tracking
# ---------------------------------------------------------------------------


def _source_status(
    *,
    scryfall_ok: bool,
    spellbook_ok: bool,
    spellbook_error: str | None,
    edhrec_ok: bool | None,
    edhrec_error: str | None,
    edhrec_enabled: bool,
) -> list[str]:
    """Build the Data Sources footer section."""
    lines = ["", "---", "**Data Sources:**"]

    scryfall_status = "OK" if scryfall_ok else "error"
    lines.append(f"- Scryfall: {scryfall_status}")

    if spellbook_ok:
        lines.append("- Spellbook: OK")
    else:
        lines.append(f"- Spellbook: error ({spellbook_error})")

    if not edhrec_enabled:
        lines.append("- EDHREC: not enabled")
    elif edhrec_ok is None:
        lines.append("- EDHREC: not queried")
    elif edhrec_ok:
        lines.append("- EDHREC: OK")
    else:
        lines.append(f"- EDHREC: error ({edhrec_error})")

    return lines


# ---------------------------------------------------------------------------
# Workflow functions
# ---------------------------------------------------------------------------


async def commander_overview(
    commander_name: str,
    *,
    scryfall: ScryfallClient,
    spellbook: SpellbookClient,
    edhrec: EDHRECClient | None,
) -> str:
    """Get a comprehensive overview of a commander from all available sources.

    Concurrently fetches card details (Scryfall), combos (Spellbook), and
    top staples (EDHREC). Scryfall is required; Spellbook and EDHREC degrade
    gracefully on failure.

    Args:
        commander_name: The commander's full name.
        scryfall: Initialized ScryfallClient.
        spellbook: Initialized SpellbookClient.
        edhrec: Initialized EDHRECClient, or None if disabled.

    Returns:
        Formatted markdown string combining all available data.

    Raises:
        CardNotFoundError: If the commander is not found on Scryfall.
        ScryfallError: On other Scryfall API errors.
    """
    log.info("commander_overview.start", commander=commander_name)

    # Build concurrent tasks
    tasks: list[asyncio.Task] = []

    # Index 0: Scryfall (required)
    scryfall_task = asyncio.ensure_future(scryfall.get_card_by_name(commander_name))
    tasks.append(scryfall_task)

    # Index 1: Spellbook (optional)
    spellbook_task = asyncio.ensure_future(spellbook.find_combos(commander_name, limit=_MAX_COMBOS))
    tasks.append(spellbook_task)

    # Index 2: EDHREC (optional, may be None)
    if edhrec is not None:
        edhrec_task = asyncio.ensure_future(edhrec.commander_top_cards(commander_name))
        tasks.append(edhrec_task)

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # --- Unpack Scryfall (required) ---
    scryfall_result = results[0]
    if isinstance(scryfall_result, BaseException):
        log.error("commander_overview.scryfall_failed", error=str(scryfall_result))
        raise scryfall_result

    card: Card = scryfall_result

    # --- Unpack Spellbook (optional) ---
    spellbook_result = results[1]
    combos: list[Combo] = []
    spellbook_ok = True
    spellbook_error: str | None = None
    if isinstance(spellbook_result, BaseException):
        log.warning(
            "commander_overview.spellbook_failed",
            error=str(spellbook_result),
            error_type=type(spellbook_result).__name__,
        )
        spellbook_ok = False
        spellbook_error = str(spellbook_result)
    else:
        combos = spellbook_result

    # --- Unpack EDHREC (optional) ---
    edhrec_data: EDHRECCommanderData | None = None
    edhrec_ok: bool | None = None
    edhrec_error: str | None = None
    edhrec_enabled = edhrec is not None

    if edhrec is not None and len(results) > 2:
        edhrec_result = results[2]
        if isinstance(edhrec_result, BaseException):
            log.warning(
                "commander_overview.edhrec_failed",
                error=str(edhrec_result),
                error_type=type(edhrec_result).__name__,
            )
            edhrec_ok = False
            edhrec_error = str(edhrec_result)
        else:
            edhrec_ok = True
            edhrec_data = edhrec_result

    # --- Build output ---
    lines: list[str] = []
    lines.extend(_format_card_header(card))

    if spellbook_ok:
        lines.extend(_format_combos_section(combos))
    else:
        lines.append("")
        lines.append("## Combos")
        lines.append("")
        lines.append(f"Spellbook unavailable: {spellbook_error}")

    if edhrec_enabled and edhrec_ok and edhrec_data is not None:
        lines.extend(_format_edhrec_staples(edhrec_data))
    elif edhrec_enabled and edhrec_ok is False:
        lines.append("")
        lines.append("## EDHREC Staples")
        lines.append("")
        lines.append(f"EDHREC unavailable: {edhrec_error}")

    lines.extend(
        _source_status(
            scryfall_ok=True,
            spellbook_ok=spellbook_ok,
            spellbook_error=spellbook_error,
            edhrec_ok=edhrec_ok,
            edhrec_error=edhrec_error,
            edhrec_enabled=edhrec_enabled,
        )
    )

    log.info("commander_overview.complete", commander=commander_name)
    return "\n".join(lines)


async def evaluate_upgrade(
    card_name: str,
    commander_name: str,
    *,
    scryfall: ScryfallClient,
    spellbook: SpellbookClient,
    edhrec: EDHRECClient | None,
) -> str:
    """Evaluate whether a card is worth adding to a specific commander deck.

    Concurrently fetches card details (Scryfall), combos (Spellbook), and
    synergy data (EDHREC). Scryfall is required; Spellbook and EDHREC degrade
    gracefully on failure.

    Args:
        card_name: The card to evaluate.
        commander_name: The commander to evaluate against.
        scryfall: Initialized ScryfallClient.
        spellbook: Initialized SpellbookClient.
        edhrec: Initialized EDHRECClient, or None if disabled.

    Returns:
        Formatted markdown string with evaluation data.

    Raises:
        CardNotFoundError: If the card is not found on Scryfall.
        ScryfallError: On other Scryfall API errors.
    """
    log.info("evaluate_upgrade.start", card=card_name, commander=commander_name)

    # Build concurrent tasks
    tasks: list[asyncio.Task] = []

    # Index 0: Scryfall (required)
    scryfall_task = asyncio.ensure_future(scryfall.get_card_by_name(card_name))
    tasks.append(scryfall_task)

    # Index 1: Spellbook (optional)
    spellbook_task = asyncio.ensure_future(spellbook.find_combos(card_name, limit=_MAX_COMBOS))
    tasks.append(spellbook_task)

    # Index 2: EDHREC (optional, may be None)
    if edhrec is not None:
        edhrec_task = asyncio.ensure_future(edhrec.card_synergy(card_name, commander_name))
        tasks.append(edhrec_task)

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # --- Unpack Scryfall (required) ---
    scryfall_result = results[0]
    if isinstance(scryfall_result, BaseException):
        log.error("evaluate_upgrade.scryfall_failed", error=str(scryfall_result))
        raise scryfall_result

    card: Card = scryfall_result

    # --- Unpack Spellbook (optional) ---
    spellbook_result = results[1]
    combos: list[Combo] = []
    spellbook_ok = True
    spellbook_error: str | None = None
    if isinstance(spellbook_result, BaseException):
        log.warning(
            "evaluate_upgrade.spellbook_failed",
            error=str(spellbook_result),
            error_type=type(spellbook_result).__name__,
        )
        spellbook_ok = False
        spellbook_error = str(spellbook_result)
    else:
        combos = spellbook_result

    # --- Unpack EDHREC (optional) ---
    synergy_card: EDHRECCard | None = None
    edhrec_ok: bool | None = None
    edhrec_error: str | None = None
    edhrec_enabled = edhrec is not None

    if edhrec is not None and len(results) > 2:
        edhrec_result = results[2]
        if isinstance(edhrec_result, BaseException):
            log.warning(
                "evaluate_upgrade.edhrec_failed",
                error=str(edhrec_result),
                error_type=type(edhrec_result).__name__,
            )
            edhrec_ok = False
            edhrec_error = str(edhrec_result)
        else:
            edhrec_ok = True
            synergy_card = edhrec_result

    # --- Build output ---
    lines: list[str] = []
    lines.extend(_format_card_details(card))

    # Synergy section
    if edhrec_enabled and edhrec_ok:
        lines.extend(_format_synergy_section(synergy_card, commander_name))
    elif edhrec_enabled and edhrec_ok is False:
        lines.append("")
        lines.append(f"## Synergy with {commander_name}")
        lines.append("")
        lines.append(f"EDHREC unavailable: {edhrec_error}")
    else:
        lines.append("")
        lines.append(f"## Synergy with {commander_name}")
        lines.append("")
        lines.append("EDHREC not enabled — synergy data not available.")

    # Combos section
    if spellbook_ok:
        lines.extend(_format_combos_section(combos))
    else:
        lines.append("")
        lines.append("## Combos")
        lines.append("")
        lines.append(f"Spellbook unavailable: {spellbook_error}")

    lines.extend(
        _source_status(
            scryfall_ok=True,
            spellbook_ok=spellbook_ok,
            spellbook_error=spellbook_error,
            edhrec_ok=edhrec_ok,
            edhrec_error=edhrec_error,
            edhrec_enabled=edhrec_enabled,
        )
    )

    log.info("evaluate_upgrade.complete", card=card_name, commander=commander_name)
    return "\n".join(lines)


async def card_comparison(
    cards: list[str],
    commander_name: str,
    *,
    scryfall: ScryfallClient,
    spellbook: SpellbookClient,
    edhrec: EDHRECClient | None,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> str:
    """Compare multiple cards side-by-side for a specific commander deck.

    Resolves each card via Scryfall (prices required), then fetches synergy
    (EDHREC) and combo count (Spellbook) data for each. Outputs a markdown
    comparison table.

    Args:
        cards: Card names to compare (2-5).
        commander_name: The commander to evaluate against.
        scryfall: Initialized ScryfallClient.
        spellbook: Initialized SpellbookClient.
        edhrec: Initialized EDHRECClient, or None if disabled.
        on_progress: Optional callback for progress reporting.

    Returns:
        Formatted markdown comparison table.

    Raises:
        CardNotFoundError: If a card is not found on Scryfall (propagated).
    """
    from mtg_mcp.types import Card as ScryfallCard
    from mtg_mcp.types import MTGJSONCard

    log.info("card_comparison.start", cards=cards, commander=commander_name)

    # Step 1/3: Resolve cards (always Scryfall — prices required)
    if on_progress is not None:
        await on_progress(1, 3)

    resolve_tasks = [scryfall.get_card_by_name(name) for name in cards]
    resolved = await asyncio.gather(*resolve_tasks, return_exceptions=True)

    # Check for resolution failures — propagate first CardNotFoundError
    card_data: list[ScryfallCard | MTGJSONCard] = []
    for i, result in enumerate(resolved):
        if isinstance(result, BaseException):
            log.error("card_comparison.resolve_failed", card=cards[i], error=str(result))
            raise result
        card_data.append(result)

    # Step 2/3: Fetch synergy + combo data
    if on_progress is not None:
        await on_progress(2, 3)

    # EDHREC synergy lookups (parallel)
    synergy_results: list[EDHRECCard | None | BaseException] = []
    if edhrec is not None:
        synergy_tasks = [edhrec.card_synergy(card.name, commander_name) for card in card_data]
        synergy_results = await asyncio.gather(*synergy_tasks, return_exceptions=True)
    else:
        synergy_results = [None] * len(card_data)

    # Spellbook combo count lookups (parallel)
    combo_tasks = [spellbook.find_combos(card.name, limit=_MAX_COMBOS) for card in card_data]
    combo_results = await asyncio.gather(*combo_tasks, return_exceptions=True)

    # Step 3/3: Build output
    if on_progress is not None:
        await on_progress(3, 3)

    lines: list[str] = [
        f"# Card Comparison for {commander_name}",
        "",
        "| Name | Mana Cost | Type | Synergy | Inclusion % | Combos | Price |",
        "|------|-----------|------|---------|-------------|--------|-------|",
    ]

    for i, card in enumerate(card_data):
        # Extract mana cost and type
        mana_cost = getattr(card, "mana_cost", None) or "N/A"
        type_line = getattr(card, "type_line", "") or ""

        # Extract synergy
        syn_result = synergy_results[i]
        if isinstance(syn_result, BaseException):
            log.warning(
                "card_comparison.edhrec_failed",
                card=card.name,
                error=str(syn_result),
            )
            synergy_str = "N/A"
            inclusion_str = "N/A"
        elif syn_result is not None:
            synergy_str = _fmt_synergy(syn_result.synergy)
            inclusion_str = f"{syn_result.inclusion}%"
        else:
            synergy_str = "N/A"
            inclusion_str = "N/A"

        # Extract combo count
        cmb_result = combo_results[i]
        if isinstance(cmb_result, BaseException):
            log.warning(
                "card_comparison.spellbook_failed",
                card=card.name,
                error=str(cmb_result),
            )
            combo_str = "N/A"
        else:
            combo_str = str(len(cmb_result))

        # Extract price (only available on Scryfall Card, not MTGJSONCard)
        if isinstance(card, ScryfallCard) and card.prices.usd is not None:
            price_str = f"${card.prices.usd}"
        else:
            price_str = "N/A"

        lines.append(
            f"| {card.name} | {mana_cost} | {type_line} | "
            f"{synergy_str} | {inclusion_str} | {combo_str} | {price_str} |"
        )

    log.info("card_comparison.complete", cards=cards, commander=commander_name)
    return "\n".join(lines)


async def budget_upgrade(
    commander_name: str,
    *,
    budget: float,
    num_suggestions: int = 10,
    scryfall: ScryfallClient,
    edhrec: EDHRECClient | None,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> str:
    """Suggest budget-friendly upgrades ranked by synergy-per-dollar.

    Fetches EDHREC staples for the commander, looks up Scryfall prices,
    then ranks affordable cards by synergy/$.

    Args:
        commander_name: The commander to find upgrades for.
        budget: Maximum price per card in USD.
        num_suggestions: Number of top suggestions to return.
        scryfall: Initialized ScryfallClient.
        edhrec: Initialized EDHRECClient, or None if disabled.
        on_progress: Optional callback for progress reporting.

    Returns:
        Formatted markdown with ranked budget upgrade suggestions.
    """
    log.info("budget_upgrade.start", commander=commander_name, budget=budget)

    # EDHREC is required for this workflow
    if edhrec is None:
        return (
            "EDHREC is not enabled — budget upgrade requires EDHREC staples data.\n\n"
            "Set MTG_MCP_ENABLE_EDHREC=true to enable."
        )

    # Step 1/2: Fetch EDHREC staples
    if on_progress is not None:
        await on_progress(1, 2)

    edhrec_data = await edhrec.commander_top_cards(commander_name)

    # Collect all cards across all cardlists
    all_edhrec_cards: list[EDHRECCard] = []
    for cardlist in edhrec_data.cardlists:
        all_edhrec_cards.extend(cardlist.cardviews)

    if not all_edhrec_cards:
        return (
            f"No staples found for '{commander_name}' on EDHREC.\n\n"
            "The commander may be too new or rarely played."
        )

    # Step 2/2: Fetch Scryfall prices in parallel
    if on_progress is not None:
        await on_progress(2, 2)

    sem = asyncio.Semaphore(10)

    async def _fetch_price(name: str) -> Card:
        async with sem:
            return await scryfall.get_card_by_name(name)

    price_tasks = [_fetch_price(ecard.name) for ecard in all_edhrec_cards]
    price_results = await asyncio.gather(*price_tasks, return_exceptions=True)

    # Build candidates: pair EDHREC data with Scryfall prices
    candidates: list[tuple[EDHRECCard, float, float]] = []  # (edhrec, price, synergy_per_dollar)
    for ecard, price_result in zip(all_edhrec_cards, price_results, strict=True):
        if isinstance(price_result, BaseException):
            log.debug("budget_upgrade.price_failed", card=ecard.name, error=str(price_result))
            continue
        scryfall_card: Card = price_result
        if scryfall_card.prices.usd is None:
            continue
        price = float(scryfall_card.prices.usd)
        if price > budget:
            continue
        synergy_per_dollar = ecard.synergy / max(price, 0.25)
        candidates.append((ecard, price, synergy_per_dollar))

    if not candidates:
        return (
            f"No cards found under ${budget:.2f} for {commander_name}.\n\n"
            "Try increasing the budget ceiling."
        )

    # Sort by synergy-per-dollar descending
    candidates.sort(key=lambda c: c[2], reverse=True)
    top = candidates[:num_suggestions]

    # Format output
    lines: list[str] = [
        f"# Budget Upgrades for {commander_name}",
        f"*Budget ceiling: ${budget:.2f} per card*",
        "",
        "| # | Name | Synergy | Inclusion % | Price | Synergy/$ |",
        "|---|------|---------|-------------|-------|-----------|",
    ]

    for rank, (ecard, price, spd) in enumerate(top, 1):
        lines.append(
            f"| {rank} | {ecard.name} | {_fmt_synergy(ecard.synergy)} | "
            f"{ecard.inclusion}% | ${price:.2f} | {spd:.2f} |"
        )

    log.info("budget_upgrade.complete", commander=commander_name, suggestions=len(top))
    return "\n".join(lines)
