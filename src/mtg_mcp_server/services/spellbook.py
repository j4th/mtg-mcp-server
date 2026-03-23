"""Commander Spellbook API client for combo search and bracket estimation.

Wraps the Commander Spellbook REST API (https://backend.commanderspellbook.com)
which uses Django REST Framework with paginated responses. The API returns
camelCase JSON; parsing helpers map it to our snake_case Pydantic models.
"""

from __future__ import annotations

from cachetools import TTLCache

from mtg_mcp_server.services.base import BaseClient, ServiceError
from mtg_mcp_server.services.cache import _decklist_key, _method_key, async_cached
from mtg_mcp_server.types import BracketEstimate, Combo, ComboCard, ComboResult, DecklistCombos


class SpellbookError(ServiceError):
    """Commander Spellbook API error."""


class ComboNotFoundError(SpellbookError):
    """Combo was not found on Commander Spellbook."""


def _parse_combo(data: dict) -> Combo:
    """Parse a raw Spellbook combo variant into a Combo model.

    The API response nests card data inside ``uses[].card`` and result data
    inside ``produces[].feature``. This function flattens those structures
    into our :class:`ComboCard` and :class:`ComboResult` models.

    Args:
        data: Raw JSON dict for a single combo variant.

    Returns:
        Parsed Combo model.
    """
    # Each "use" wraps card info: {"card": {"name": ..., "oracleId": ...}, "zoneLocations": [...]}
    cards = [
        ComboCard(
            name=use["card"]["name"],
            oracleId=use["card"].get("oracleId"),
            typeLine=use["card"].get("typeLine", ""),
            zoneLocations=use.get("zoneLocations", []),
            mustBeCommander=use.get("mustBeCommander", False),
        )
        for use in data.get("uses", [])
    ]

    # Each "produce" wraps a feature: {"feature": {"name": ...}, "quantity": N}
    produces = [
        ComboResult(
            feature_name=prod["feature"]["name"],
            quantity=prod.get("quantity", 1),
        )
        for prod in data.get("produces", [])
    ]

    return Combo(
        id=data["id"],
        status=data.get("status", ""),
        cards=cards,
        produces=produces,
        identity=data.get("identity", ""),
        mana_needed=data.get("manaNeeded", ""),
        description=data.get("description", ""),
        easy_prerequisites=data.get("easyPrerequisites", ""),
        notable_prerequisites=data.get("notablePrerequisites", ""),
        popularity=data.get("popularity", 0),
        bracket_tag=data.get("bracketTag"),
        legalities=data.get("legalities", {}),
        prices=data.get("prices", {}),
    )


def _build_decklist_body(commanders: list[str], decklist: list[str]) -> dict:
    """Build the JSON body for ``/find-my-combos`` and ``/estimate-bracket``.

    The API expects ``{"commanders": [{"card": ..., "quantity": 1}], "main": [...]}``.

    Args:
        commanders: Commander card names.
        decklist: Main deck card names.

    Returns:
        Request body dict ready for ``json=`` in httpx.
    """
    return {
        "commanders": [{"card": name, "quantity": 1} for name in commanders],
        "main": [{"card": name, "quantity": 1} for name in decklist],
    }


class SpellbookClient(BaseClient):
    """Async client for the Commander Spellbook REST API.

    Args:
        base_url: Spellbook API base URL.
        rate_limit_rps: Max requests per second.
    """

    # Combo data changes infrequently (24h TTL).
    # Decklist analysis results are less cacheable (12h TTL) since users
    # may update their decklist between calls.
    _combos_cache: TTLCache = TTLCache(maxsize=200, ttl=86400)  # 24h
    _combo_cache: TTLCache = TTLCache(maxsize=100, ttl=86400)  # 24h
    _decklist_combos_cache: TTLCache = TTLCache(maxsize=50, ttl=43200)  # 12h
    _bracket_cache: TTLCache = TTLCache(maxsize=50, ttl=43200)  # 12h

    def __init__(
        self,
        base_url: str = "https://backend.commanderspellbook.com",
        rate_limit_rps: float = 3.0,
    ) -> None:
        super().__init__(
            base_url=base_url,
            rate_limit_rps=rate_limit_rps,
        )

    @async_cached(_combos_cache, key=_method_key)
    async def find_combos(
        self,
        card_name: str,
        color_identity: str | None = None,
        limit: int = 10,
    ) -> list[Combo]:
        """Search for combos involving a specific card.

        Args:
            card_name: Card name to search for.
            color_identity: Optional color identity filter (e.g. ``"sultai"``, ``"BUG"``).
            limit: Maximum number of results to return.

        Returns:
            List of matching combos.

        Raises:
            SpellbookError: On API errors.
        """
        # Spellbook search syntax: card:"Name" coloridentity:XXX
        query = f'card:"{card_name}"'
        if color_identity:
            query += f" coloridentity:{color_identity}"

        try:
            response = await self._get(
                "/variants/",
                params={"q": query, "limit": str(limit)},
            )
        except ServiceError as exc:
            raise SpellbookError(exc.message, status_code=exc.status_code) from exc

        # Response is a DRF paginated envelope: {count, next, previous, results: [...]}
        data = response.json()
        return [_parse_combo(r) for r in data.get("results", [])]

    @async_cached(_combo_cache, key=_method_key)
    async def get_combo(self, combo_id: str) -> Combo:
        """Get detailed information about a specific combo by ID.

        Args:
            combo_id: Spellbook combo variant ID (e.g. "1414-2730-5131-5256").

        Returns:
            The combo variant.

        Raises:
            ComboNotFoundError: If the combo ID does not exist.
        """
        try:
            response = await self._get(f"/variants/{combo_id}/")
        except ServiceError as exc:
            if exc.status_code == 404:
                raise ComboNotFoundError(f"Combo not found: '{combo_id}'", status_code=404) from exc
            raise SpellbookError(exc.message, status_code=exc.status_code) from exc

        return _parse_combo(response.json())

    @async_cached(_decklist_combos_cache, key=_decklist_key)
    async def find_decklist_combos(
        self,
        commanders: list[str],
        decklist: list[str],
    ) -> DecklistCombos:
        """Find combos present in (or nearly present in) a decklist.

        Args:
            commanders: List of commander card names.
            decklist: List of card names in the main deck.

        Returns:
            Combos categorized as included or almost-included.

        Raises:
            SpellbookError: On API errors.
        """
        body = _build_decklist_body(commanders, decklist)
        try:
            response = await self._post("/find-my-combos", json=body)
        except ServiceError as exc:
            raise SpellbookError(exc.message, status_code=exc.status_code) from exc

        data = response.json()
        # The API wraps the result in a paginated envelope: {count, next, previous, results}
        # where 'results' is a single dict with identity, included, almostIncluded, etc.
        inner = data.get("results", {})
        return DecklistCombos(
            identity=inner.get("identity", ""),
            included=[_parse_combo(c) for c in inner.get("included", [])],
            almost_included=[_parse_combo(c) for c in inner.get("almostIncluded", [])],
        )

    @async_cached(_bracket_cache, key=_decklist_key)
    async def estimate_bracket(
        self,
        commanders: list[str],
        decklist: list[str],
    ) -> BracketEstimate:
        """Estimate the Commander bracket for a decklist.

        Args:
            commanders: List of commander card names.
            decklist: List of card names in the main deck.

        Returns:
            Bracket estimation with relevant details.

        Raises:
            SpellbookError: On API errors.
        """
        body = _build_decklist_body(commanders, decklist)
        try:
            response = await self._post("/estimate-bracket", json=body)
        except ServiceError as exc:
            raise SpellbookError(exc.message, status_code=exc.status_code) from exc

        return BracketEstimate.model_validate(response.json())
