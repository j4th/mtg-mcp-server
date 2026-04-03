"""Spicerack API client for fetching tournament results and decklists.

Spicerack provides a documented public REST API for tournament data at
``api.spicerack.gg``.  No authentication is required, though an optional
``X-API-Key`` header is supported for higher rate limits.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from typing import Any
from cachetools import TTLCache

from mtg_mcp_server.services.base import BaseClient, ServiceError
from mtg_mcp_server.services.cache import async_cached
from mtg_mcp_server.types import SpicerackStanding, SpicerackTournament

log = structlog.get_logger(service="spicerack")


def _safe_str(val: object, default: str = "") -> str:
    """Return ``str(val)`` if *val* is not None, else *default*."""
    if val is None:
        return default
    return str(val)


def _safe_int(val: object) -> int:
    """Return ``int(val)`` if *val* is numeric (int or float), else ``0``."""
    if isinstance(val, bool):
        return 0
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    return 0


class SpicerackError(ServiceError):
    """Spicerack API error."""


class InvalidFormatError(SpicerackError):
    """Invalid format parameter (HTTP 400)."""


class SpicerackClient(BaseClient):
    """Async client for the Spicerack tournament results API.

    Args:
        base_url: Spicerack API base URL.
        api_key: Optional API key for ``X-API-Key`` header.
        rate_limit_rps: Max requests per second.
    """

    # 4h cache — tournament data changes infrequently during a session.
    _tournaments_cache: TTLCache = TTLCache(maxsize=50, ttl=14400)

    def __init__(
        self,
        *,
        base_url: str = "https://api.spicerack.gg",
        api_key: str = "",
        rate_limit_rps: float = 1.0,
    ) -> None:
        super().__init__(base_url=base_url, rate_limit_rps=rate_limit_rps)
        self._api_key = api_key

    @async_cached(_tournaments_cache)
    async def get_tournaments(
        self,
        num_days: int = 14,
        event_format: str | None = None,
    ) -> list[SpicerackTournament]:
        """Fetch recent tournaments, optionally filtered by format.

        Args:
            num_days: Number of days to look back (default 14).
            event_format: Optional format filter (e.g. "Legacy", "Modern").

        Returns:
            List of parsed tournament results.

        Raises:
            InvalidFormatError: If the format is not recognized (HTTP 400).
            SpicerackError: On other API errors.
        """
        params: dict[str, str | int] = {"num_days": num_days}
        if event_format is not None:
            params["event_format"] = event_format

        log.debug("get_tournaments", num_days=num_days, event_format=event_format)

        headers: dict[str, str] = {}
        if self._api_key:
            headers["X-API-Key"] = self._api_key

        try:
            response = await self._get(
                "/api/export-decklists/",
                params=params,
                headers=headers,
            )
        except ServiceError as exc:
            if exc.status_code == 400:
                raise InvalidFormatError(
                    f"Invalid format: '{event_format}'",
                    status_code=400,
                ) from exc
            raise SpicerackError(exc.message, status_code=exc.status_code) from exc

        try:
            data = response.json()
        except (ValueError, UnicodeDecodeError) as exc:
            raise SpicerackError("Spicerack returned invalid JSON") from exc

        return self._parse_tournaments(data)

    def _parse_tournaments(self, data: Any) -> list[SpicerackTournament]:
        """Defensively parse tournament array from API response.

        Handles missing fields, malformed entries, and non-list responses
        gracefully with warnings rather than crashes.
        """
        if not isinstance(data, list):
            log.warning("parse_tournaments.unexpected_type", data_type=type(data).__name__)
            raise SpicerackError(f"Expected JSON array, got {type(data).__name__}")

        tournaments: list[SpicerackTournament] = []
        for entry in data:
            if not isinstance(entry, dict):
                log.warning("parse_tournaments.skip_non_dict", entry_type=type(entry).__name__)
                continue
            tournament = self._parse_single_tournament(entry)
            tournaments.append(tournament)

        log.debug("parse_tournaments.complete", count=len(tournaments))
        return tournaments

    def _parse_single_tournament(self, entry: Any) -> SpicerackTournament:
        """Parse a single tournament dict into a SpicerackTournament."""
        # Convert Unix timestamp to ISO date string
        date_str = ""
        start_date = entry.get("startDate")
        if isinstance(start_date, int | float):
            try:
                date_str = datetime.fromtimestamp(start_date, tz=UTC).strftime("%Y-%m-%d")
            except (OSError, OverflowError, ValueError):
                log.warning("parse_tournament.bad_date", start_date=start_date)

        # Parse standings
        raw_standings = entry.get("standings")
        standings = self._parse_standings(raw_standings)

        return SpicerackTournament(
            tournament_id=_safe_str(entry.get("TID")),
            name=_safe_str(entry.get("tournamentName")),
            format=_safe_str(entry.get("format")),
            bracket_url=_safe_str(entry.get("bracketUrl")),
            player_count=_safe_int(entry.get("players")),
            date=date_str,
            rounds_swiss=_safe_int(entry.get("swissRounds")),
            top_cut=_safe_int(entry.get("topCut")),
            standings=standings,
        )

    def _parse_standings(self, raw_standings: Any) -> list[SpicerackStanding]:
        """Parse standings array, assigning 1-based ranks from array position."""
        if not isinstance(raw_standings, list):
            log.debug("parse_standings.not_list", raw_type=type(raw_standings).__name__)
            return []

        standings: list[SpicerackStanding] = []
        rank = 1
        for idx, entry in enumerate(raw_standings):
            if not isinstance(entry, dict):
                log.warning("parse_standings.skip_non_dict", index=idx)
                continue

            standing = self._parse_single_standing(rank, entry)
            standings.append(standing)
            rank += 1

        return standings

    def _parse_single_standing(self, rank: int, entry: Any) -> SpicerackStanding:
        """Parse a single standing dict into a SpicerackStanding."""
        return SpicerackStanding(
            rank=rank,
            player_name=_safe_str(entry.get("name")),
            decklist_url=_safe_str(entry.get("decklist")),
            wins=_safe_int(entry.get("winsSwiss")),
            losses=_safe_int(entry.get("lossesSwiss")),
            draws=_safe_int(entry.get("draws")),
            bracket_wins=_safe_int(entry.get("winsBracket")),
            bracket_losses=_safe_int(entry.get("lossesBracket")),
        )
