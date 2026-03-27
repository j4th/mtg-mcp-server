"""Scryfall bulk card data service — lazy download and in-memory card cache.

Download Scryfall's Oracle Cards bulk data once and keep it in memory for O(1)
card lookups and fast substring searches. Refresh automatically when the data
becomes stale (default 12h). On refresh failure with existing data, serve stale
data rather than propagating the error.

Unlike :class:`BaseClient`, this is a standalone service managing its own HTTP
downloads. It does not use rate limiting or retries — the bulk-data endpoint is
a single lightweight request and the bulk download is a large file fetch, neither
benefiting from the per-request rate-limit pattern that ``BaseClient`` provides.

Returns :class:`~mtg_mcp_server.types.Card` objects with prices, legalities,
EDHREC rank, and image URIs. Checks the ``/bulk-data/oracle_cards`` metadata
endpoint before download, supports ETag-based conditional downloads, uses
``asyncio.Lock`` to prevent duplicate concurrent downloads, and runs a
background refresh loop via ``asyncio.create_task()``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from typing import Self

import httpx
import structlog
from pydantic import ValidationError

from mtg_mcp_server.services.base import DEFAULT_USER_AGENT, ServiceError
from mtg_mcp_server.types import Card

__all__ = ["ScryfallBulkClient", "ScryfallBulkDownloadError", "ScryfallBulkError"]

log = structlog.get_logger(service="ScryfallBulkClient")

# Scryfall Oracle Cards includes non-playable entries (minigames, art series,
# tokens, emblems) that can share names with real cards. Filter these out during
# parsing. Uses a deny-list so new playable layouts are included by default.
_EXCLUDED_LAYOUTS: frozenset[str] = frozenset(
    {
        "art_series",
        "double_faced_token",
        "emblem",
        "minigame",
        "placeholder",
        "token",
    }
)


class ScryfallBulkError(ServiceError):
    """Base exception for Scryfall bulk data service errors.

    Always passes ``status_code=None`` since bulk data operations don't map
    cleanly to a single HTTP status.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=None)


class ScryfallBulkDownloadError(ScryfallBulkError):
    """Error downloading Scryfall bulk data (network or HTTP failure)."""


class ScryfallBulkClient:
    """Manages Scryfall Oracle Cards bulk data with lazy download and refresh.

    Downloads the Oracle Cards JSON on first access and caches parsed
    :class:`Card` models in memory. Refreshes automatically when
    ``refresh_hours`` has elapsed, using ETag-based conditional downloads
    to avoid re-parsing unchanged data.

    Use as an async context manager::

        async with ScryfallBulkClient(base_url=...) as client:
            card = await client.get_card("Sol Ring")
    """

    def __init__(
        self,
        *,
        base_url: str = "https://api.scryfall.com",
        refresh_hours: int = 12,
    ) -> None:
        """Initialize the Scryfall bulk client.

        Args:
            base_url: Scryfall API base URL (for metadata endpoint).
            refresh_hours: Hours before re-downloading data.
        """
        self._base_url = base_url
        self._refresh_seconds = refresh_hours * 3600

        # _cards: lowercase-name -> Card for O(1) exact lookup.
        # _unique_cards: deduplicated list for linear substring search.
        # Separation avoids double-counting DFCs which have two keys
        # in _cards (front-face name + full "//" name) but one entry
        # in _unique_cards.
        self._cards: dict[str, Card] = {}
        self._unique_cards: list[Card] = []
        self._loaded_at: float = 0.0  # monotonic timestamp; 0 = never loaded

        # ETag for conditional download (HTTP 304 Not Modified)
        self._etag: str | None = None
        self._etag_url: str | None = None  # URL the ETag applies to

        # asyncio.Lock prevents duplicate concurrent downloads
        self._load_lock = asyncio.Lock()

        # Background refresh task
        self._refresh_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> Self:
        """Enter async context. Data is loaded lazily on first access, not here."""
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Cancel background refresh and release in-memory data."""
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._refresh_task
            self._refresh_task = None

        self._cards.clear()
        self._unique_cards.clear()
        self._loaded_at = 0.0

    def start_background_refresh(self) -> None:
        """Start the background refresh loop.

        Creates an ``asyncio.Task`` that periodically calls
        :meth:`ensure_loaded` at the refresh interval. The task is
        cancelled in :meth:`__aexit__`.
        """
        if self._refresh_task is not None:
            return  # Already running
        self._refresh_task = asyncio.create_task(self._refresh_loop())

    async def ensure_loaded(self) -> None:
        """Download and parse Oracle Cards if not loaded or stale.

        On first load failure, the error propagates (server cannot start
        without data). On **refresh** failure (data was previously loaded),
        logs a warning and serves stale data.

        Uses ``asyncio.Lock`` to prevent duplicate concurrent downloads.

        Raises:
            ScryfallBulkDownloadError: On first-load network/HTTP failure.
            ScryfallBulkError: On first-load parse failure.
        """
        if not self._is_stale():
            return

        async with self._load_lock:
            # Double-check after acquiring lock — another coroutine may have
            # already completed the load while we were waiting.
            if not self._is_stale():
                return

            is_refresh = self._loaded_at > 0
            log.info("scryfall_bulk.loading", base_url=self._base_url, is_refresh=is_refresh)

            try:
                # Step 1: Fetch metadata to get the current download URL
                metadata = await self._fetch_metadata()
                download_url = metadata.get("download_uri")
                if not download_url or not isinstance(download_url, str):
                    raise ScryfallBulkError(
                        f"Bulk metadata missing 'download_uri'. Keys: {list(metadata.keys())}"
                    )

                # Step 2: Download the bulk data (with ETag if URL matches)
                result = await self._download(download_url)

                if result is not None:
                    # Got new data — parse it
                    self._parse(result)

                # Either we parsed new data or got 304 — update timestamp
                self._loaded_at = time.monotonic()
                log.info(
                    "scryfall_bulk.loaded",
                    card_count=len(self._unique_cards),
                )
            except ScryfallBulkError:
                if is_refresh:
                    # Stale data is better than no data — retry in 5 min, not full interval
                    log.warning(
                        "scryfall_bulk.refresh_failed",
                        base_url=self._base_url,
                        exc_info=True,
                    )
                    self._loaded_at = time.monotonic() - self._refresh_seconds + 300
                    return
                raise

    async def get_card(self, name: str) -> Card | None:
        """Look up a card by exact name (case-insensitive).

        Args:
            name: Card name (front-face or full ``//`` name for DFCs).

        Returns:
            Card data, or None if not found.
        """
        await self.ensure_loaded()
        return self._cards.get(name.lower())

    async def search_cards(self, query: str, limit: int = 20) -> list[Card]:
        """Search cards by name substring (case-insensitive).

        Args:
            query: Substring to match against card names.
            limit: Maximum results to return.

        Returns:
            Matching cards, up to ``limit``.
        """
        await self.ensure_loaded()
        query_lower = query.lower()
        results: list[Card] = []
        for card in self._unique_cards:
            if query_lower in card.name.lower():
                results.append(card)
                if len(results) >= limit:
                    break
        return results

    async def search_by_type(self, type_query: str, limit: int = 20) -> list[Card]:
        """Search cards by type line substring (case-insensitive).

        Args:
            type_query: Substring to match against type lines.
            limit: Maximum results to return.

        Returns:
            Matching cards, up to ``limit``.
        """
        await self.ensure_loaded()
        query_lower = type_query.lower()
        results: list[Card] = []
        for card in self._unique_cards:
            if query_lower in card.type_line.lower():
                results.append(card)
                if len(results) >= limit:
                    break
        return results

    async def search_by_text(self, text_query: str, limit: int = 20) -> list[Card]:
        """Search cards by oracle text substring (case-insensitive).

        Args:
            text_query: Substring to match against oracle text.
            limit: Maximum results to return.

        Returns:
            Matching cards, up to ``limit``.
        """
        await self.ensure_loaded()
        query_lower = text_query.lower()
        results: list[Card] = []
        for card in self._unique_cards:
            oracle = card.oracle_text or ""
            if query_lower in oracle.lower():
                results.append(card)
                if len(results) >= limit:
                    break
        return results

    # -------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------

    def _is_stale(self) -> bool:
        """Check if the loaded data has exceeded the refresh interval."""
        if self._loaded_at == 0.0:
            return True
        return (time.monotonic() - self._loaded_at) >= self._refresh_seconds

    async def _fetch_metadata(self) -> dict:
        """Fetch the bulk-data metadata to get the current download URI.

        Raises:
            ScryfallBulkDownloadError: On HTTP errors or network failures.
        """
        url = f"{self._base_url}/bulk-data/oracle_cards"
        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Accept": "application/json",
                },
            ) as http:
                response = await http.get(url)
                if response.status_code != 200:
                    raise ScryfallBulkDownloadError(
                        f"HTTP {response.status_code} fetching bulk metadata from {url}"
                    )
                try:
                    return response.json()
                except (json.JSONDecodeError, ValueError) as exc:
                    raise ScryfallBulkDownloadError(
                        f"Metadata response is not valid JSON from {url}: {exc}"
                    ) from exc
        except httpx.RequestError as exc:
            raise ScryfallBulkDownloadError(f"Network error fetching bulk metadata: {exc}") from exc

    async def _download(self, url: str) -> bytes | None:
        """Download the Oracle Cards bulk data file.

        Sends ``If-None-Match`` header when the URL matches the previous
        download's URL and we have a saved ETag. Returns ``None`` on HTTP
        304 (data unchanged).

        Raises:
            ScryfallBulkDownloadError: On HTTP errors or network failures.
        """
        headers: dict[str, str] = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "application/json",
        }

        # Only send If-None-Match if the URL matches the one we got the ETag from
        if self._etag is not None and self._etag_url == url:
            headers["If-None-Match"] = self._etag

        try:
            async with httpx.AsyncClient(timeout=120.0, headers=headers) as http:
                response = await http.get(url)

                if response.status_code == 304:
                    log.info("scryfall_bulk.not_modified", url=url)
                    return None

                if response.status_code != 200:
                    raise ScryfallBulkDownloadError(
                        f"HTTP {response.status_code} downloading bulk data from {url}"
                    )

                # Save ETag for future conditional requests
                etag = response.headers.get("ETag")
                if etag:
                    self._etag = etag
                    self._etag_url = url

                return response.content
        except httpx.RequestError as exc:
            raise ScryfallBulkDownloadError(f"Network error downloading bulk data: {exc}") from exc

    def _parse(self, raw_bytes: bytes) -> None:
        """Parse Oracle Cards JSON array into the in-memory card dicts.

        The bulk data is a JSON array of Scryfall card objects. Each is
        validated through ``Card.model_validate()``.

        For DFCs, ``card.name`` contains the full ``"Front // Back"`` name.
        We key lookups by both the full name and the front face name
        (``name.split(" // ")[0]``).

        Raises:
            ScryfallBulkError: If JSON is malformed.
        """
        try:
            raw = json.loads(raw_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ScryfallBulkError(f"Failed to parse bulk data: {exc}") from exc

        if not isinstance(raw, list):
            raise ScryfallBulkError("Bulk data is not a JSON array")

        cards: dict[str, Card] = {}
        unique: list[Card] = []
        skipped = 0

        for entry in raw:
            if not isinstance(entry, dict):
                skipped += 1
                continue

            layout = entry.get("layout", "")
            if layout in _EXCLUDED_LAYOUTS:
                skipped += 1
                continue

            try:
                card = Card.model_validate(entry)
            except (ValidationError, ValueError) as exc:
                log.warning(
                    "scryfall_bulk.card_parse_error",
                    card_name=entry.get("name", "unknown"),
                    error=str(exc),
                )
                skipped += 1
                continue

            unique.append(card)

            # Key by full lowercase name for O(1) case-insensitive lookup
            full_name_lower = card.name.lower()
            cards[full_name_lower] = card

            # For DFCs, card.name is "Front // Back". Also key by front-face
            # name so lookup by either form works.
            if " // " in card.name:
                front_face = card.name.split(" // ")[0].lower()
                if front_face != full_name_lower:
                    cards[front_face] = card

        if skipped:
            log.info("scryfall_bulk.parse_summary", skipped=skipped, loaded=len(unique))

        if not unique:
            raise ScryfallBulkError(
                f"Parsed 0 cards from {len(raw)} entries ({skipped} skipped). "
                "Scryfall bulk data schema may have changed."
            )

        self._cards = cards
        self._unique_cards = unique

    async def _refresh_loop(self) -> None:
        """Background loop that periodically calls ensure_loaded().

        Runs until cancelled (via __aexit__). Errors are logged but do
        not stop the loop.
        """
        while True:
            await asyncio.sleep(self._refresh_seconds)
            try:
                await self.ensure_loaded()
            except ScryfallBulkError:
                log.warning("scryfall_bulk.background_refresh_error", exc_info=True)
            except Exception:
                log.error("scryfall_bulk.background_refresh_unexpected_error", exc_info=True)
