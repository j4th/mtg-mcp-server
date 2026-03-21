"""17Lands API client for draft card ratings and archetype statistics."""

from __future__ import annotations

from mtg_mcp.services.base import BaseClient, ServiceError
from mtg_mcp.types import ArchetypeRating, DraftCardRating


class SeventeenLandsError(ServiceError):
    """17Lands API error."""


class SeventeenLandsClient(BaseClient):
    """Async client for the 17Lands draft data API.

    Rate limit is aggressive (1 req/sec max). Cache responses wherever possible.
    """

    def __init__(
        self,
        base_url: str = "https://www.17lands.com",
        rate_limit_rps: float = 1.0,
        user_agent: str = "mtg-mcp/0.1.0",
    ) -> None:
        super().__init__(
            base_url=base_url,
            rate_limit_rps=rate_limit_rps,
            user_agent=user_agent,
        )

    async def card_ratings(
        self,
        set_code: str,
        event_type: str = "PremierDraft",
    ) -> list[DraftCardRating]:
        """Get card performance data for a set.

        Args:
            set_code: Set code (e.g. "LCI", "MKM").
            event_type: Draft format (e.g. "PremierDraft", "TradDraft").

        Returns:
            List of card ratings with win rates, pick rates, etc.
        """
        try:
            response = await self._get(
                "/card_ratings/data",
                params={"expansion": set_code, "event_type": event_type},
            )
        except ServiceError as exc:
            raise SeventeenLandsError(exc.message, status_code=exc.status_code) from exc
        return [DraftCardRating.model_validate(item) for item in response.json()]

    async def color_ratings(
        self,
        set_code: str,
        start_date: str,
        end_date: str,
        event_type: str = "PremierDraft",
    ) -> list[ArchetypeRating]:
        """Get archetype win rates by color pair for a set.

        Args:
            set_code: Set code (e.g. "LCI", "MKM").
            start_date: Start date in YYYY-MM-DD format (required by API).
            end_date: End date in YYYY-MM-DD format (required by API).
            event_type: Draft format (e.g. "PremierDraft", "TradDraft").

        Returns:
            List of archetype ratings with wins, games, and derived win rates.
        """
        try:
            response = await self._get(
                "/color_ratings/data",
                params={
                    "expansion": set_code,
                    "event_type": event_type,
                    "start_date": start_date,
                    "end_date": end_date,
                },
            )
        except ServiceError as exc:
            raise SeventeenLandsError(exc.message, status_code=exc.status_code) from exc
        return [ArchetypeRating.model_validate(item) for item in response.json()]
