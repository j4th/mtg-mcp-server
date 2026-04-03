"""MTGGoldfish metagame service — stub for scaffold.

Full implementation in Phase 2. This module provides the client class
and error types that other modules depend on.
"""

from __future__ import annotations

from cachetools import TTLCache

from mtg_mcp_server.services.base import BaseClient, ServiceError


class MTGGoldfishError(ServiceError):
    """Base error for MTGGoldfish service failures."""


class FormatNotFoundError(MTGGoldfishError):
    """Raised when a format page returns 404."""


class ArchetypeNotFoundError(MTGGoldfishError):
    """Raised when an archetype page returns 404."""


class MTGGoldfishClient(BaseClient):
    """HTTP client for scraping MTGGoldfish metagame data.

    Full implementation in Phase 2. Stubs provide cache attributes
    for conftest cache clearing.
    """

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
        )
