"""MTGGoldfish metagame service — HTML scraping client.

MTGGoldfish has no JSON API. All data is scraped from HTML pages using
selectolax. This client uses a browser-like User-Agent since MTGGoldfish
blocks bot UAs. All access should be behind a feature flag due to the
fragile scraping nature.
"""

from __future__ import annotations

import contextlib
import re
from typing import Self

import structlog
from cachetools import TTLCache
from selectolax.parser import HTMLParser, Node

from mtg_mcp_server.services.base import BaseClient, ServiceError
from mtg_mcp_server.services.cache import _method_key, async_cached
from mtg_mcp_server.types import (
    GoldfishArchetype,
    GoldfishArchetypeDetail,
    GoldfishFormatStaple,
    GoldfishMetaSnapshot,
)
from mtg_mcp_server.utils.formatters import slugify

log = structlog.get_logger(service="mtggoldfish")

# Pre-compiled regexes for HTML parsing.
# Match deck_id from initializeDeckComponents JS call.
# Pattern: initializeDeckComponents('guid', 'DECK_ID', ...)
_RE_DECK_ID = re.compile(r"initializeDeckComponents\(\s*'[^']*'\s*,\s*'(\d+)'")

# Match metagame share percentage like "20.3%"
_RE_META_PCT = re.compile(r"([\d.]+)%")

# Match deck count in parentheses like "(572)"
_RE_DECK_COUNT = re.compile(r"\((\d[\d,]*)\)")

# Match price like "$ 860" or "$ 1,014"
_RE_PRICE = re.compile(r"\$\s*([\d,]+)")

# Browser-like User-Agent (MTGGoldfish blocks bot UAs).
_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Mana symbol class → color letter mapping.
_MANA_COLOR_MAP: dict[str, str] = {
    "ms-w": "W",
    "ms-u": "U",
    "ms-b": "B",
    "ms-r": "R",
    "ms-g": "G",
}


class MTGGoldfishError(ServiceError):
    """Base error for MTGGoldfish service failures."""


class FormatNotFoundError(MTGGoldfishError):
    """Raised when a format page returns 404."""


class ArchetypeNotFoundError(MTGGoldfishError):
    """Raised when an archetype page returns 404."""


class MTGGoldfishClient(BaseClient):
    """HTTP client for scraping MTGGoldfish metagame data.

    Scrapes HTML pages for metagame breakdowns, archetype details,
    format staples, and deck prices. Uses selectolax for fast HTML
    parsing with defensive extraction patterns.

    Args:
        base_url: MTGGoldfish base URL.
        rate_limit_rps: Max requests per second (0.5 = conservative for scraped sites).
    """

    # Cache TTLs match the data change frequency:
    _metagame_cache: TTLCache = TTLCache(maxsize=50, ttl=21600)  # 6h
    _archetype_cache: TTLCache = TTLCache(maxsize=100, ttl=43200)  # 12h
    _staples_cache: TTLCache = TTLCache(maxsize=50, ttl=43200)  # 12h
    _price_cache: TTLCache = TTLCache(maxsize=100, ttl=86400)  # 24h

    def __init__(
        self,
        base_url: str = "https://www.mtggoldfish.com",
        rate_limit_rps: float = 0.5,
    ) -> None:
        super().__init__(
            base_url=base_url,
            rate_limit_rps=rate_limit_rps,
            user_agent=_BROWSER_UA,
        )

    async def __aenter__(self) -> Self:
        """Override Accept header for HTML scraping.

        BaseClient defaults to ``Accept: application/json`` which causes
        MTGGoldfish to return HTTP 406 (Not Acceptable). This override
        sets a browser-standard Accept header for HTML content.
        """
        await super().__aenter__()
        if self._client is not None:
            self._client.headers["accept"] = (
                "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            )
        return self

    @async_cached(_metagame_cache, key=_method_key)
    async def get_metagame(self, format: str) -> GoldfishMetaSnapshot:
        """Get metagame breakdown for a format.

        Args:
            format: Format name (e.g. "modern", "legacy", "pauper").

        Returns:
            GoldfishMetaSnapshot with parsed archetypes.

        Raises:
            FormatNotFoundError: If the format page returns 404.
            MTGGoldfishError: On other HTTP errors.
        """
        log.debug("get_metagame", format=format)
        try:
            response = await self._get(f"/metagame/{format}/full")
        except ServiceError as exc:
            if exc.status_code == 404:
                raise FormatNotFoundError(
                    f"Format not found on MTGGoldfish: '{format}'",
                    status_code=404,
                ) from exc
            raise MTGGoldfishError(exc.message, status_code=exc.status_code) from exc

        html = response.text
        archetypes = self._parse_metagame_html(html)
        total_decks = sum(a.deck_count for a in archetypes)

        log.debug("get_metagame.complete", format=format, archetype_count=len(archetypes))
        return GoldfishMetaSnapshot(
            format=format,
            archetypes=archetypes,
            total_decks=total_decks,
        )

    @async_cached(_archetype_cache, key=_method_key)
    async def get_archetype(self, format: str, archetype: str) -> GoldfishArchetypeDetail:
        """Get archetype detail with decklist.

        Fetches the archetype HTML page for metadata, extracts the deck_id
        from embedded JavaScript, then downloads the plaintext decklist.

        Args:
            format: Format name (e.g. "modern").
            archetype: Archetype name (e.g. "Boros Energy").

        Returns:
            GoldfishArchetypeDetail with deck metadata and decklist.

        Raises:
            ArchetypeNotFoundError: If the archetype page returns 404.
            MTGGoldfishError: On other HTTP errors.
        """
        slug = slugify(archetype)
        url_slug = f"{format}-{slug}"
        log.debug("get_archetype", format=format, archetype=archetype, slug=url_slug)

        try:
            response = await self._get(f"/archetype/{url_slug}")
        except ServiceError as exc:
            if exc.status_code == 404:
                raise ArchetypeNotFoundError(
                    f"Archetype not found on MTGGoldfish: '{archetype}'",
                    status_code=404,
                ) from exc
            raise MTGGoldfishError(exc.message, status_code=exc.status_code) from exc

        html = response.text
        detail = self._parse_archetype_html(html, archetype)

        # Download the decklist if we found a deck_id
        if detail.deck_id:
            try:
                deck_response = await self._get(f"/deck/download/{detail.deck_id}")
                mainboard, sideboard = self._parse_decklist(deck_response.text)
                detail = detail.model_copy(update={"mainboard": mainboard, "sideboard": sideboard})
            except ServiceError:
                log.warning(
                    "get_archetype.deck_download_failed",
                    deck_id=detail.deck_id,
                    archetype=archetype,
                )

        log.debug(
            "get_archetype.complete",
            archetype=archetype,
            mainboard_count=len(detail.mainboard),
            sideboard_count=len(detail.sideboard),
        )
        return detail

    @async_cached(_staples_cache, key=_method_key)
    async def get_format_staples(self, format: str, limit: int = 20) -> list[GoldfishFormatStaple]:
        """Get most-played cards in a format.

        Args:
            format: Format name (e.g. "modern").
            limit: Maximum number of staples to return (default 20).

        Returns:
            List of GoldfishFormatStaple sorted by rank.

        Raises:
            FormatNotFoundError: If the format page returns 404.
            MTGGoldfishError: On other HTTP errors.
        """
        log.debug("get_format_staples", format=format, limit=limit)
        try:
            response = await self._get(f"/format-staples/{format}")
        except ServiceError as exc:
            if exc.status_code == 404:
                raise FormatNotFoundError(
                    f"Format not found on MTGGoldfish: '{format}'",
                    status_code=404,
                ) from exc
            raise MTGGoldfishError(exc.message, status_code=exc.status_code) from exc

        html = response.text
        staples = self._parse_staples_html(html)

        if limit > 0:
            staples = staples[:limit]

        log.debug("get_format_staples.complete", format=format, count=len(staples))
        return staples

    @async_cached(_price_cache, key=_method_key)
    async def get_deck_price(self, format: str, archetype: str) -> dict:
        """Get price metadata for an archetype.

        Uses get_metagame() to find the archetype's price from the metagame
        page, and get_archetype() for the decklist card count.

        Args:
            format: Format name (e.g. "modern").
            archetype: Archetype name (e.g. "Boros Energy").

        Returns:
            Dict with archetype name, paper price, and card counts.

        Raises:
            ArchetypeNotFoundError: If the archetype is not found in the metagame.
            MTGGoldfishError: On other HTTP errors.
        """
        log.debug("get_deck_price", format=format, archetype=archetype)

        # Find archetype in metagame snapshot for price
        meta = await self.get_metagame(format)
        needle = archetype.lower()
        matching = [a for a in meta.archetypes if a.name.lower() == needle]
        if not matching:
            raise ArchetypeNotFoundError(
                f"Archetype not found in metagame: '{archetype}'",
                status_code=None,
            )

        price_paper = matching[0].price_paper

        # Get the decklist for card counts
        detail = await self.get_archetype(format, archetype)

        return {
            "archetype": archetype,
            "price_paper": price_paper,
            "mainboard_count": len(detail.mainboard),
            "sideboard_count": len(detail.sideboard),
        }

    # -----------------------------------------------------------------------
    # HTML parsing helpers (all defensive — wrap in try/except, log warnings)
    # -----------------------------------------------------------------------

    def _parse_metagame_html(self, html: str) -> list[GoldfishArchetype]:
        """Parse archetype tiles from a metagame page.

        Each archetype is a ``div.archetype-tile`` containing:
        - Name from ``span.deck-price-paper a``
        - Slug from the href attribute
        - Meta% from ``div.metagame-percentage .archetype-tile-statistic-value``
        - Deck count from ``span.archetype-tile-statistic-value-extra-data``
        - Price from ``div.deck-price-paper .archetype-tile-statistic-value``
        - Colors from ``span.manacost i`` class names
        - Key cards from ``ul li``
        """
        tree = HTMLParser(html)
        tiles = tree.css("div.archetype-tile")
        archetypes: list[GoldfishArchetype] = []

        for tile in tiles:
            try:
                arch = self._parse_single_tile(tile)
                archetypes.append(arch)
            except Exception:
                log.warning("parse_metagame.tile_failed", exc_info=True)
                continue

        return archetypes

    def _parse_single_tile(self, tile: Node) -> GoldfishArchetype:
        """Parse a single archetype tile element."""
        # Name and slug from the paper price link
        name = ""
        slug = ""
        name_link = tile.css_first("span.deck-price-paper a")
        if name_link is not None:
            name = (name_link.text(strip=True) or "").strip()
            href = name_link.attributes.get("href") or ""
            # href is like "/archetype/modern-boros-energy#paper"
            slug = href.split("/archetype/")[-1].split("#")[0] if "/archetype/" in href else ""

        # Meta share percentage
        meta_share = 0.0
        meta_div = tile.css_first("div.metagame-percentage .archetype-tile-statistic-value")
        if meta_div is not None:
            meta_text = meta_div.text(strip=True) or ""
            pct_match = _RE_META_PCT.search(meta_text)
            if pct_match:
                with contextlib.suppress(ValueError):
                    meta_share = float(pct_match.group(1))

        # Deck count from extra data span
        deck_count = 0
        count_span = tile.css_first("span.archetype-tile-statistic-value-extra-data")
        if count_span is not None:
            count_text = count_span.text(strip=True) or ""
            count_match = _RE_DECK_COUNT.search(count_text)
            if count_match:
                with contextlib.suppress(ValueError):
                    deck_count = int(count_match.group(1).replace(",", ""))

        # Paper price from deck-price-paper statistic
        price_paper = 0
        price_div = tile.css_first(
            "div.archetype-tile-statistic.deck-price-paper .archetype-tile-statistic-value"
        )
        if price_div is not None:
            price_text = price_div.text(strip=True) or ""
            price_match = _RE_PRICE.search(price_text)
            if price_match:
                with contextlib.suppress(ValueError):
                    price_paper = int(price_match.group(1).replace(",", ""))

        # Colors from mana cost icons
        colors: list[str] = []
        mana_icons = tile.css("span.manacost i")
        for icon in mana_icons:
            classes = (icon.attributes.get("class", "") or "").split()
            for cls in classes:
                if cls in _MANA_COLOR_MAP and _MANA_COLOR_MAP[cls] not in colors:
                    colors.append(_MANA_COLOR_MAP[cls])

        # Key cards from the list
        key_cards: list[str] = []
        li_elements = tile.css("ul li")
        for li in li_elements:
            card_name = (li.text(strip=True) or "").strip()
            if card_name:
                key_cards.append(card_name)

        return GoldfishArchetype(
            name=name,
            slug=slug,
            meta_share=meta_share,
            deck_count=deck_count,
            price_paper=price_paper,
            colors=colors,
            key_cards=key_cards,
        )

    def _parse_archetype_html(self, html: str, archetype: str) -> GoldfishArchetypeDetail:
        """Parse archetype detail page for metadata.

        Extracts:
        - Name from ``h1.title`` text
        - Author from ``span.author``
        - Event and result from ``p.deck-container-information``
        - Deck ID from ``initializeDeckComponents`` JS call
        - Date from "Deck Date:" line
        """
        tree = HTMLParser(html)

        # Name from h1.title
        name = archetype
        h1 = tree.css_first("h1.title")
        if h1 is not None:
            # h1 may contain child elements (span.author) — get direct text
            name_text = h1.text(strip=True) or ""
            # Remove the "by Author" part if present
            author_span = h1.css_first("span.author")
            if author_span is not None:
                author_text = author_span.text(strip=True) or ""
                name_text = name_text.replace(author_text, "").strip()
            name = name_text or archetype

        # Author from span.author
        author = ""
        author_el = tree.css_first("span.author")
        if author_el is not None:
            author_text = (author_el.text(strip=True) or "").strip()
            # Remove "by " prefix
            if author_text.lower().startswith("by "):
                author_text = author_text[3:].strip()
            author = author_text

        # Event, result, and date from p.deck-container-information
        event = ""
        result = ""
        date = ""
        info_p = tree.css_first("p.deck-container-information")
        if info_p is not None:
            info_text = info_p.text() or ""
            # Parse event from the "Event:" line
            event_link = info_p.css_first("a")
            if event_link is not None:
                event = (event_link.text(strip=True) or "").strip()

            # Parse result — it follows the event link, formatted as ", 1st Place, 8-1-1"
            for line in info_text.split("\n"):
                line = line.strip()
                if line.startswith("Event:"):
                    # The result is everything after the event name and the comma
                    # Format: "Event: LDXP SEA26...,  1st Place, 8-1-1"
                    parts = line.split(",", 1)
                    if len(parts) > 1:
                        result = parts[1].strip().rstrip(",").strip()
                elif line.startswith("Deck Date:"):
                    date = line.replace("Deck Date:", "").strip()

        # Deck ID from initializeDeckComponents JS
        deck_id = ""
        scripts = tree.css("script")
        for script in scripts:
            script_text = script.text() or ""
            deck_match = _RE_DECK_ID.search(script_text)
            if deck_match:
                deck_id = deck_match.group(1)
                break

        return GoldfishArchetypeDetail(
            name=name,
            author=author,
            event=event,
            result=result,
            deck_id=deck_id,
            date=date,
        )

    def _parse_decklist(self, text: str) -> tuple[list[str], list[str]]:
        """Parse a plaintext decklist into mainboard and sideboard.

        Lines are in format ``4 Card Name``. A blank line separates
        mainboard from sideboard.
        """
        mainboard: list[str] = []
        sideboard: list[str] = []
        current = mainboard

        for line in text.strip().splitlines():
            stripped = line.strip()
            if not stripped:
                # Blank line switches to sideboard
                current = sideboard
                continue
            current.append(stripped)

        return mainboard, sideboard

    def _parse_staples_html(self, html: str) -> list[GoldfishFormatStaple]:
        """Parse format staples from the first table on the page.

        The first ``table.table-staples`` is "Top Cards Overall".
        Each row has: rank (td[0]), name (td[1] a text), pct_of_decks (td[3]),
        copies_played (td[4]).
        """
        tree = HTMLParser(html)
        table = tree.css_first("table.table-staples")
        if table is None:
            log.warning("parse_staples.no_table")
            return []

        rows = table.css("tr")
        staples: list[GoldfishFormatStaple] = []

        for row in rows:
            tds = row.css("td")
            if len(tds) < 5:
                continue  # Skip header row or malformed rows

            try:
                rank_text = (tds[0].text(strip=True) or "").strip()
                rank = int(rank_text) if rank_text else 0

                # Card name from the link inside the second td
                name = ""
                name_link = tds[1].css_first("a")
                if name_link is not None:
                    name = (name_link.text(strip=True) or "").strip()

                pct_text = (tds[3].text(strip=True) or "").strip().rstrip("%")
                pct_of_decks = float(pct_text) if pct_text else 0.0

                copies_text = (tds[4].text(strip=True) or "").strip()
                copies_played = float(copies_text) if copies_text else 0.0

                staples.append(
                    GoldfishFormatStaple(
                        rank=rank,
                        name=name,
                        pct_of_decks=pct_of_decks,
                        copies_played=copies_played,
                    )
                )
            except (ValueError, IndexError):
                log.warning("parse_staples.row_failed", exc_info=True)
                continue

        return staples
