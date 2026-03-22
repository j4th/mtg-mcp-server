"""MTGJSON bulk card data service — lazy download and in-memory card cache.

Downloads AtomicCards.json.gz once and keeps it in memory for O(1) card lookups
and fast substring searches. Refreshes when the data becomes stale.
"""

from __future__ import annotations

import gzip
import json
import time
from typing import Self

import httpx
import structlog
from pydantic import ValidationError

from mtg_mcp.services.base import ServiceError
from mtg_mcp.types import MTGJSONCard

log = structlog.get_logger(service="MTGJSONClient")


class MTGJSONError(ServiceError):
    """Base exception for MTGJSON service errors."""

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=None)


class MTGJSONDownloadError(MTGJSONError):
    """Error downloading or decompressing MTGJSON data."""


class MTGJSONClient:
    """Manages MTGJSON bulk card data with lazy download and refresh.

    Downloads AtomicCards.json.gz on first access and caches parsed data
    in memory. Refreshes automatically when ``refresh_hours`` has elapsed.

    Use as an async context manager::

        async with MTGJSONClient(data_url=...) as client:
            card = await client.get_card("Sol Ring")
    """

    def __init__(self, data_url: str, refresh_hours: int = 24) -> None:
        self._data_url = data_url
        self._refresh_seconds = refresh_hours * 3600
        self._cards: dict[str, MTGJSONCard] = {}
        self._unique_cards: list[MTGJSONCard] = []
        self._loaded_at: float = 0.0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._cards.clear()
        self._unique_cards.clear()
        self._loaded_at = 0.0

    async def ensure_loaded(self) -> None:
        """Download and parse AtomicCards if not loaded or stale.

        On refresh failure (data was previously loaded), logs a warning
        and serves stale data rather than propagating the error.
        """
        if not self._is_stale():
            return

        is_refresh = self._loaded_at > 0
        log.info("mtgjson.loading", url=self._data_url, stale=is_refresh)
        try:
            raw_bytes = await self._download()
            decompressed = self._decompress(raw_bytes)
            self._parse(decompressed)
            self._loaded_at = time.monotonic()
            log.info("mtgjson.loaded", card_count=len(self._unique_cards))
        except MTGJSONError:
            if is_refresh:
                log.warning("mtgjson.refresh_failed", url=self._data_url)
                self._loaded_at = time.monotonic()
                return
            raise

    async def get_card(self, name: str) -> MTGJSONCard | None:
        """Exact card lookup by name (case-insensitive)."""
        await self.ensure_loaded()
        return self._cards.get(name.lower())

    async def search_cards(self, query: str, limit: int = 20) -> list[MTGJSONCard]:
        """Search cards by name substring (case-insensitive)."""
        await self.ensure_loaded()
        query_lower = query.lower()
        results: list[MTGJSONCard] = []
        for card in self._unique_cards:
            if query_lower in card.name.lower():
                results.append(card)
                if len(results) >= limit:
                    break
        return results

    async def search_by_type(self, type_query: str, limit: int = 20) -> list[MTGJSONCard]:
        """Search cards by type line substring (case-insensitive)."""
        await self.ensure_loaded()
        query_lower = type_query.lower()
        results: list[MTGJSONCard] = []
        for card in self._unique_cards:
            if query_lower in card.type_line.lower():
                results.append(card)
                if len(results) >= limit:
                    break
        return results

    async def search_by_text(self, text_query: str, limit: int = 20) -> list[MTGJSONCard]:
        """Search cards by oracle text substring (case-insensitive)."""
        await self.ensure_loaded()
        query_lower = text_query.lower()
        results: list[MTGJSONCard] = []
        for card in self._unique_cards:
            if query_lower in card.oracle_text.lower():
                results.append(card)
                if len(results) >= limit:
                    break
        return results

    def _is_stale(self) -> bool:
        """Check if the loaded data has exceeded the refresh interval."""
        if self._loaded_at == 0.0:
            return True
        return (time.monotonic() - self._loaded_at) >= self._refresh_seconds

    async def _download(self) -> bytes:
        """Download the gzipped AtomicCards file."""
        try:
            async with httpx.AsyncClient(timeout=120.0) as http:
                response = await http.get(self._data_url)
                if response.status_code != 200:
                    raise MTGJSONDownloadError(
                        f"HTTP {response.status_code} downloading MTGJSON data"
                    )
                return response.content
        except httpx.RequestError as exc:
            raise MTGJSONDownloadError(f"Network error downloading MTGJSON data: {exc}") from exc

    def _decompress(self, raw_bytes: bytes) -> str:
        """Decompress gzipped data to a JSON string."""
        try:
            return gzip.decompress(raw_bytes).decode("utf-8")
        except (gzip.BadGzipFile, OSError, UnicodeDecodeError) as exc:
            raise MTGJSONError(f"Failed to decompress MTGJSON data: {exc}") from exc

    def _parse(self, json_str: str) -> None:
        """Parse AtomicCards JSON into the in-memory card dict."""
        try:
            raw = json.loads(json_str)
        except json.JSONDecodeError as exc:
            raise MTGJSONError(f"Failed to parse MTGJSON data: {exc}") from exc

        if not isinstance(raw, dict) or "data" not in raw:
            raise MTGJSONError("MTGJSON data missing 'data' key")

        data = raw["data"]
        cards: dict[str, MTGJSONCard] = {}
        unique: list[MTGJSONCard] = []

        for card_name, printings in data.items():
            if not isinstance(printings, list) or len(printings) == 0:
                continue

            # Use the first printing (index 0) for oracle data.
            # For double-faced cards, use the front face (side=null or side="a").
            printing = printings[0]
            if not isinstance(printing, dict):
                continue

            try:
                card = MTGJSONCard(
                    name=str(printing.get("name", card_name)),
                    mana_cost=str(printing.get("manaCost", "") or ""),
                    type_line=str(printing.get("type", "") or ""),
                    oracle_text=str(printing.get("text", "") or ""),
                    colors=printing.get("colors") or [],
                    color_identity=printing.get("colorIdentity") or [],
                    types=printing.get("types") or [],
                    subtypes=printing.get("subtypes") or [],
                    supertypes=printing.get("supertypes") or [],
                    keywords=printing.get("keywords") or [],
                    power=printing.get("power"),
                    toughness=printing.get("toughness"),
                    mana_value=float(printing.get("manaValue", 0.0) or 0.0),
                )
            except (ValidationError, ValueError, TypeError) as exc:
                log.warning("mtgjson.card_parse_error", card_name=card_name, error=str(exc))
                continue

            unique.append(card)
            # Key by lowercase card name for O(1) case-insensitive lookup.
            # For double-faced cards, also key by the full "//" name.
            cards[card.name.lower()] = card
            if card_name.lower() != card.name.lower():
                cards[card_name.lower()] = card

        self._cards = cards
        self._unique_cards = unique
