"""EDHREC API client for commander staples and card synergy data.

EDHREC has no official public API. This client uses undocumented internal JSON
endpoints that may break without notice. All access is behind a feature flag
(MTG_MCP_ENABLE_EDHREC) and should fail gracefully.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from cachetools import TTLCache

from mtg_mcp.services.base import BaseClient, ServiceError
from mtg_mcp.services.cache import _method_key, async_cached
from mtg_mcp.types import EDHRECCard, EDHRECCardList, EDHRECCommanderData

_RE_SPECIAL_CHARS = re.compile(r"[,.'\"!?:;()]+")
_RE_WHITESPACE = re.compile(r"\s+")
_RE_MULTI_HYPHEN = re.compile(r"-+")

if TYPE_CHECKING:
    # httpx.Response.json() returns Any; we alias for clarity in parsing helpers.
    from typing import Any as JSONData


class EDHRECError(ServiceError):
    """EDHREC API error."""


class CommanderNotFoundError(EDHRECError):
    """Commander was not found on EDHREC."""


class EDHRECClient(BaseClient):
    """Async client for EDHREC's internal JSON endpoints.

    These endpoints are undocumented and fragile. Use defensive parsing
    with .get() chains and default to empty values when fields are missing.
    """

    _commander_cache: TTLCache = TTLCache(maxsize=100, ttl=86400)
    _synergy_cache: TTLCache = TTLCache(maxsize=200, ttl=86400)

    def __init__(
        self,
        base_url: str = "https://json.edhrec.com",
        rate_limit_rps: float = 0.5,
        user_agent: str = "mtg-mcp/0.1.0",
    ) -> None:
        super().__init__(
            base_url=base_url,
            rate_limit_rps=rate_limit_rps,
            user_agent=user_agent,
        )

    def _slugify(self, name: str) -> str:
        """Convert a card name to an EDHREC URL slug.

        Lowercase, replace spaces with hyphens, remove commas, apostrophes,
        periods, and other special characters. Collapse multiple hyphens.
        """
        slug = name.lower()
        slug = _RE_SPECIAL_CHARS.sub("", slug)
        slug = _RE_WHITESPACE.sub("-", slug)
        slug = _RE_MULTI_HYPHEN.sub("-", slug)
        return slug.strip("-")

    @async_cached(_commander_cache, key=_method_key)
    async def commander_top_cards(
        self, commander_name: str, category: str | None = None
    ) -> EDHRECCommanderData:
        """Get top cards for a commander with synergy and inclusion data.

        Args:
            commander_name: The commander's full name (e.g. "Muldrotha, the Gravetide").
            category: Optional category filter (e.g. "creatures", "enchantments").
                      Matches against the cardlist tag field.

        Returns:
            EDHRECCommanderData with parsed cardlists.

        Raises:
            CommanderNotFoundError: If the commander page doesn't exist.
            EDHRECError: On other API errors.
        """
        slug = self._slugify(commander_name)
        try:
            response = await self._get(f"/pages/commanders/{slug}.json")
        except ServiceError as exc:
            if exc.status_code in (404, 403):
                raise CommanderNotFoundError(
                    f"Commander not found on EDHREC: '{slug}'", status_code=exc.status_code
                ) from exc
            raise EDHRECError(exc.message, status_code=exc.status_code) from exc

        data = response.json()
        return self._parse_commander_data(data, commander_name, category)

    @async_cached(_synergy_cache, key=_method_key)
    async def card_synergy(self, card_name: str, commander_name: str) -> EDHRECCard | None:
        """Get synergy data for a specific card with a commander.

        Fetches the commander page and searches all cardlists for the card.

        Args:
            card_name: The card to look up.
            commander_name: The commander to check synergy against.

        Returns:
            EDHRECCard if the card is found, None otherwise.

        Raises:
            CommanderNotFoundError: If the commander page doesn't exist.
            EDHRECError: On other API errors.
        """
        result = await self.commander_top_cards(commander_name)
        card_name_lower = card_name.lower()
        for cardlist in result.cardlists:
            for card in cardlist.cardviews:
                if card.name.lower() == card_name_lower:
                    return card
        return None

    def _parse_commander_data(
        self,
        data: JSONData,
        commander_name: str,
        category: str | None = None,
    ) -> EDHRECCommanderData:
        """Defensively parse a commander page JSON response.

        Uses isinstance checks and .get() chains throughout to handle
        missing or changed fields in this undocumented API.
        """
        if not isinstance(data, dict):
            return EDHRECCommanderData(commander_name=commander_name)

        # Extract header — fall back to provided commander name
        raw_header = data.get("header", commander_name)
        header = str(raw_header) if raw_header is not None else commander_name
        # Strip " (Commander)" suffix if present
        if header.endswith(" (Commander)"):
            header = header[: -len(" (Commander)")]

        raw_total = data.get("num_decks_avg", 0)
        total_decks = int(raw_total) if isinstance(raw_total, (int, float)) else 0

        # Navigate the deeply nested container structure defensively
        container = data.get("container")
        json_dict = container.get("json_dict") if isinstance(container, dict) else None
        raw_cardlists = json_dict.get("cardlists", []) if isinstance(json_dict, dict) else []
        if not isinstance(raw_cardlists, list):
            raw_cardlists = []

        cardlists: list[EDHRECCardList] = []
        for raw_cl in raw_cardlists:
            if not isinstance(raw_cl, dict):
                continue
            tag = str(raw_cl.get("tag", ""))
            cl_header = str(raw_cl.get("header", ""))
            raw_views = raw_cl.get("cardviews", [])
            if not isinstance(raw_views, list):
                raw_views = []

            cards: list[EDHRECCard] = []
            for raw_card in raw_views:
                if not isinstance(raw_card, dict):
                    continue
                cards.append(
                    EDHRECCard(
                        name=str(raw_card.get("name", "")),
                        sanitized=str(raw_card.get("sanitized", "")),
                        synergy=float(raw_card.get("synergy", 0.0) or 0.0),
                        inclusion=int(raw_card.get("inclusion", 0) or 0),
                        num_decks=int(raw_card.get("num_decks", 0) or 0),
                        potential_decks=int(raw_card.get("potential_decks", 0) or 0),
                        label=str(raw_card.get("label", "")),
                    )
                )

            cardlists.append(EDHRECCardList(header=cl_header, tag=tag, cardviews=cards))

        # Apply category filter if requested
        if category is not None:
            category_lower = category.lower()
            cardlists = [cl for cl in cardlists if cl.tag.lower() == category_lower]

        return EDHRECCommanderData(
            commander_name=header,
            cardlists=cardlists,
            total_decks=total_decks,
        )
