"""Moxfield API client for fetching public decklists.

Moxfield has no official public API. This client uses the undocumented v3 REST
API at ``api2.moxfield.com``.  Access is behind a feature flag
(``MTG_MCP_ENABLE_MOXFIELD``) and should fail gracefully.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import structlog
from cachetools import TTLCache

from mtg_mcp_server.services.base import DEFAULT_USER_AGENT, BaseClient, ServiceError
from mtg_mcp_server.services.cache import async_cached
from mtg_mcp_server.types import MoxfieldCard, MoxfieldDeck, MoxfieldDecklist

if TYPE_CHECKING:
    # httpx.Response.json() returns Any; we alias for clarity in parsing helpers.
    from typing import Any as JSONData

log = structlog.get_logger(service="moxfield")

# Matches Moxfield deck URLs: https://www.moxfield.com/decks/{id}
_RE_MOXFIELD_URL = re.compile(
    r"^https?://(?:www\.)?moxfield\.com/decks/([^/?#]+)",
)

# Board keys in the v3 API response that we extract.
_BOARD_KEYS = ("commanders", "mainboard", "sideboard", "companions")


def _moxfield_deck_key(*args: object, **kwargs: object) -> object:
    """Cache key that normalizes URLs to deck IDs before hashing.

    Without this, ``get_deck("https://moxfield.com/decks/abc123")`` and
    ``get_deck("abc123")`` would be separate cache entries for the same deck.
    """
    from cachetools import keys

    # args[0] is self, args[1] is deck_id_or_url
    raw = args[1] if len(args) > 1 else kwargs.get("deck_id_or_url", "")
    normalized = MoxfieldClient.extract_deck_id(str(raw))
    return keys.hashkey(normalized)


class MoxfieldError(ServiceError):
    """Moxfield API error."""


class DeckNotFoundError(MoxfieldError):
    """Deck was not found on Moxfield."""


class MoxfieldClient(BaseClient):
    """Async client for Moxfield's undocumented v3 REST API.

    Endpoints are reverse-engineered and may break without notice.  Use
    defensive parsing with ``.get()`` chains and ``isinstance`` checks at
    every nesting level.

    Args:
        base_url: Moxfield API base URL.
        rate_limit_rps: Max requests per second.
        user_agent: User-Agent header value.
    """

    # 4h cache — decklists change infrequently during a session.
    _deck_cache: TTLCache = TTLCache(maxsize=100, ttl=14400)

    def __init__(
        self,
        base_url: str = "https://api2.moxfield.com",
        rate_limit_rps: float = 1.0,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        super().__init__(
            base_url=base_url,
            rate_limit_rps=rate_limit_rps,
            user_agent=user_agent,
        )

    @staticmethod
    def extract_deck_id(deck_id_or_url: str) -> str:
        """Extract a Moxfield deck ID from a URL or pass through a raw ID.

        Handles:
            - ``"abc123"`` -> ``"abc123"``
            - ``"https://www.moxfield.com/decks/abc123"`` -> ``"abc123"``
            - Trailing slashes and query parameters are stripped.
            - Non-Moxfield URLs pass through as-is.
        """
        m = _RE_MOXFIELD_URL.match(deck_id_or_url)
        if m:
            return m.group(1)
        return deck_id_or_url

    @async_cached(_deck_cache, key=_moxfield_deck_key)
    async def get_deck(self, deck_id_or_url: str) -> MoxfieldDecklist:
        """Fetch a public Moxfield deck by ID or URL.

        Args:
            deck_id_or_url: Either a raw deck ID or a full Moxfield URL.

        Returns:
            Fully parsed decklist with board sections.

        Raises:
            DeckNotFoundError: If the deck doesn't exist (404).
            MoxfieldError: On other API errors.
        """
        deck_id = self.extract_deck_id(deck_id_or_url)
        log.debug("get_deck", deck_id=deck_id)

        try:
            response = await self._get(f"/v3/decks/all/{deck_id}")
        except ServiceError as exc:
            if exc.status_code in (403, 404):
                raise DeckNotFoundError(
                    f"Deck not found on Moxfield: '{deck_id}'", status_code=exc.status_code
                ) from exc
            raise MoxfieldError(exc.message, status_code=exc.status_code) from exc

        try:
            data = response.json()
        except (ValueError, UnicodeDecodeError) as exc:
            raise MoxfieldError(f"Moxfield returned invalid JSON for deck '{deck_id}'") from exc
        return self._parse_deck(data)

    async def get_deck_info(self, deck_id_or_url: str) -> MoxfieldDeck:
        """Fetch deck metadata only (delegates to :meth:`get_deck`).

        The full decklist is fetched and cached; this method returns only
        the :class:`MoxfieldDeck` metadata portion.  Subsequent calls for
        the same input benefit from the ``get_deck`` cache for free.  The
        cache normalizes URLs to deck IDs, so URL and raw-ID lookups share
        entries.

        Args:
            deck_id_or_url: Either a raw deck ID or a full Moxfield URL.

        Returns:
            Deck metadata.

        Raises:
            DeckNotFoundError: If the deck doesn't exist (404).
            MoxfieldError: On other API errors.
        """
        decklist = await self.get_deck(deck_id_or_url)
        return decklist.deck

    def _parse_deck(self, data: JSONData) -> MoxfieldDecklist:
        """Defensively parse a v3 deck response into a :class:`MoxfieldDecklist`.

        The v3 shape is::

            {
              "id": "...",
              "name": "...",
              "format": "commander",
              "boards": {
                "commanders": {"count": N, "cards": {card_id: {...}, ...}},
                "mainboard":  {"count": N, "cards": {card_id: {...}, ...}},
                ...
              },
              "createdByUser": {"userName": "..."},
              ...
            }

        Every level uses ``isinstance`` and ``.get()`` with defaults because
        this undocumented API can change without notice.
        """
        if not isinstance(data, dict):
            log.warning("parse_deck.unexpected_type", data_type=type(data).__name__)
            raise MoxfieldError(
                f"Moxfield returned unexpected data format (expected JSON object, got {type(data).__name__})"
            )

        # --- Metadata ---
        created_by = data.get("createdByUser")
        author = ""
        if isinstance(created_by, dict):
            author = str(created_by.get("userName", ""))

        deck = MoxfieldDeck(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            format=str(data.get("format", "")),
            description=str(data.get("description", "")),
            author=author,
            public_url=str(data.get("publicUrl", "")),
            created_at=str(data.get("createdAtUtc", "")),
            updated_at=str(data.get("lastUpdatedAtUtc", "")),
        )

        # --- Boards ---
        boards = data.get("boards")
        if not isinstance(boards, dict):
            log.debug("parse_deck.no_boards", deck_id=deck.id)
            return MoxfieldDecklist(deck=deck)

        parsed_boards: dict[str, list[MoxfieldCard]] = {}
        for board_key in _BOARD_KEYS:
            board_data = boards.get(board_key)
            parsed_boards[board_key] = self._parse_board(board_data)

        return MoxfieldDecklist(
            deck=deck,
            commanders=parsed_boards["commanders"],
            mainboard=parsed_boards["mainboard"],
            sideboard=parsed_boards["sideboard"],
            companions=parsed_boards["companions"],
        )

    def _parse_board(self, board_data: JSONData) -> list[MoxfieldCard]:
        """Extract cards from a single board section.

        Each board has the shape::

            {"count": N, "cards": {card_id: {"quantity": int, "card": {"name": str, ...}}}}

        Malformed entries are skipped with a debug log.  Results are sorted
        alphabetically by card name for deterministic output.
        """
        if not isinstance(board_data, dict):
            return []

        cards_dict = board_data.get("cards")
        if not isinstance(cards_dict, dict):
            return []

        cards: list[MoxfieldCard] = []
        for card_id, entry in cards_dict.items():
            if not isinstance(entry, dict):
                log.debug("parse_board.skip_non_dict", card_id=card_id)
                continue

            quantity = entry.get("quantity")
            if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
                log.debug("parse_board.skip_bad_quantity", card_id=card_id, quantity=quantity)
                continue

            card_obj = entry.get("card")
            if not isinstance(card_obj, dict):
                log.debug("parse_board.skip_no_card", card_id=card_id)
                continue

            name = card_obj.get("name")
            if not isinstance(name, str) or not name:
                log.debug("parse_board.skip_no_name", card_id=card_id)
                continue

            cards.append(MoxfieldCard(name=name, quantity=quantity))

        # Sort alphabetically for deterministic output
        cards.sort(key=lambda c: c.name)
        return cards
