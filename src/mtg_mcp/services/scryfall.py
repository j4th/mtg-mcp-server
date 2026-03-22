"""Scryfall API client for card search, lookup, and rulings."""

from __future__ import annotations

from cachetools import TTLCache

from mtg_mcp.services.base import BaseClient, ServiceError
from mtg_mcp.services.cache import _method_key, async_cached
from mtg_mcp.types import Card, CardSearchResult, Ruling


class ScryfallError(ServiceError):
    """Scryfall API error."""


class CardNotFoundError(ScryfallError):
    """Card was not found on Scryfall."""


class ScryfallClient(BaseClient):
    """Async client for the Scryfall REST API."""

    _card_name_cache: TTLCache = TTLCache(maxsize=500, ttl=86400)
    _card_id_cache: TTLCache = TTLCache(maxsize=500, ttl=86400)
    _search_cache: TTLCache = TTLCache(maxsize=100, ttl=3600)
    _rulings_cache: TTLCache = TTLCache(maxsize=200, ttl=86400)

    def __init__(
        self,
        base_url: str = "https://api.scryfall.com",
        rate_limit_rps: float = 10.0,
        user_agent: str = "mtg-mcp/0.1.0",
    ) -> None:
        super().__init__(
            base_url=base_url,
            rate_limit_rps=rate_limit_rps,
            user_agent=user_agent,
        )

    @async_cached(_card_name_cache, key=_method_key)
    async def get_card_by_name(self, name: str, *, fuzzy: bool = False) -> Card:
        """Look up a card by exact or fuzzy name."""
        param_key = "fuzzy" if fuzzy else "exact"
        try:
            response = await self._get("/cards/named", params={param_key: name})
        except ServiceError as exc:
            if exc.status_code == 404:
                raise CardNotFoundError(f"Card not found: '{name}'", status_code=404) from exc
            raise ScryfallError(exc.message, status_code=exc.status_code) from exc
        return Card.model_validate(response.json())

    @async_cached(_search_cache, key=_method_key)
    async def search_cards(self, query: str, page: int = 1) -> CardSearchResult:
        """Search for cards using Scryfall syntax."""
        try:
            response = await self._get("/cards/search", params={"q": query, "page": str(page)})
        except ServiceError as exc:
            if exc.status_code == 404:
                raise CardNotFoundError(
                    f"No cards found for query: '{query}'", status_code=404
                ) from exc
            raise ScryfallError(exc.message, status_code=exc.status_code) from exc
        return CardSearchResult.model_validate(response.json())

    @async_cached(_card_id_cache, key=_method_key)
    async def get_card_by_id(self, scryfall_id: str) -> Card:
        """Look up a card by Scryfall UUID."""
        try:
            response = await self._get(f"/cards/{scryfall_id}")
        except ServiceError as exc:
            if exc.status_code == 404:
                raise CardNotFoundError(
                    f"Card not found: '{scryfall_id}'", status_code=404
                ) from exc
            raise ScryfallError(exc.message, status_code=exc.status_code) from exc
        return Card.model_validate(response.json())

    @async_cached(_rulings_cache, key=_method_key)
    async def get_rulings(self, scryfall_id: str) -> list[Ruling]:
        """Get official rulings for a card by Scryfall UUID."""
        try:
            response = await self._get(f"/cards/{scryfall_id}/rulings")
        except ServiceError as exc:
            raise ScryfallError(exc.message, status_code=exc.status_code) from exc
        data = response.json()
        return [Ruling.model_validate(r) for r in data["data"]]
