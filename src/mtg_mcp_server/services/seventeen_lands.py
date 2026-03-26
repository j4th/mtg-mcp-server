"""17Lands API client for draft card ratings and archetype statistics.

Wraps 17Lands' undocumented but widely-used REST endpoints for card win rates
and color pair performance data. Rate limited aggressively (1 req/sec max).
"""

from __future__ import annotations

from cachetools import TTLCache

from mtg_mcp_server.services.base import DEFAULT_USER_AGENT, BaseClient, ServiceError
from mtg_mcp_server.services.cache import _method_key, async_cached
from mtg_mcp_server.types import ArchetypeRating, DraftCardRating


class SeventeenLandsError(ServiceError):
    """17Lands API error."""


class SeventeenLandsClient(BaseClient):
    """Async client for the 17Lands draft data API.

    Rate limit is aggressive (1 req/sec max). All responses are cached with
    a 4-hour TTL to minimize API pressure.

    Args:
        base_url: 17Lands base URL.
        rate_limit_rps: Max requests per second (default 1.0).
        user_agent: User-Agent header value.
    """

    _card_ratings_cache: TTLCache = TTLCache(maxsize=20, ttl=14400)  # 4h
    _color_ratings_cache: TTLCache = TTLCache(maxsize=20, ttl=14400)  # 4h

    def __init__(
        self,
        base_url: str = "https://www.17lands.com",
        rate_limit_rps: float = 1.0,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        super().__init__(
            base_url=base_url,
            rate_limit_rps=rate_limit_rps,
            user_agent=user_agent,
        )

    @async_cached(_card_ratings_cache, key=_method_key)
    async def card_ratings(
        self,
        set_code: str,
        event_type: str = "PremierDraft",
    ) -> list[DraftCardRating]:
        """Get card performance data for a set.

        Args:
            set_code: Set code (e.g. ``"LCI"``, ``"MKM"``).
            event_type: Draft format (e.g. ``"PremierDraft"``, ``"TradDraft"``).

        Returns:
            List of card ratings with win rates, pick rates, etc.

        Raises:
            SeventeenLandsError: On API errors.
        """
        try:
            response = await self._get(
                "/card_ratings/data",
                params={"expansion": set_code.upper(), "event_type": event_type},
            )
        except ServiceError as exc:
            raise SeventeenLandsError(exc.message, status_code=exc.status_code) from exc
        return [DraftCardRating.model_validate(item) for item in response.json()]

    @async_cached(_color_ratings_cache, key=_method_key)
    async def color_ratings(
        self,
        set_code: str,
        start_date: str,
        end_date: str,
        event_type: str = "PremierDraft",
    ) -> list[ArchetypeRating]:
        """Get archetype win rates by color pair for a set.

        Args:
            set_code: Set code (e.g. ``"LCI"``, ``"MKM"``).
            start_date: Start date in YYYY-MM-DD format (required by API).
            end_date: End date in YYYY-MM-DD format (required by API).
            event_type: Draft format (e.g. ``"PremierDraft"``, ``"TradDraft"``).

        Returns:
            List of archetype ratings with wins, games, and derived win rates.

        Raises:
            SeventeenLandsError: On API errors (including 400 if dates are missing).
        """
        try:
            response = await self._get(
                "/color_ratings/data",
                params={
                    "expansion": set_code.upper(),
                    "event_type": event_type,
                    "start_date": start_date,
                    "end_date": end_date,
                },
            )
        except ServiceError as exc:
            raise SeventeenLandsError(exc.message, status_code=exc.status_code) from exc
        return [ArchetypeRating.model_validate(item) for item in response.json()]
