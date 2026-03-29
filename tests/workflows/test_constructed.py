"""Tests for constructed workflow functions (rotation_check).

These are unit tests of pure async functions. Service clients are mocked with
AsyncMock -- no respx/httpx needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mtg_mcp_server.types import Card, CardPrices, SetInfo
from mtg_mcp_server.workflows.constructed import rotation_check

# ---------------------------------------------------------------------------
# Helper: create mock Card objects
# ---------------------------------------------------------------------------


def _mock_card(
    name: str,
    *,
    set_code: str = "test",
    legalities: dict[str, str] | None = None,
) -> Card:
    return Card(
        id=f"test-{name.lower().replace(' ', '-')}",
        name=name,
        set=set_code,
        legalities=legalities or {"standard": "legal", "commander": "legal"},
        prices=CardPrices(usd="1.00"),
    )


def _mock_set(
    code: str,
    name: str,
    *,
    set_type: str = "expansion",
    released_at: str = "2025-01-01",
) -> SetInfo:
    return SetInfo(
        code=code,
        name=name,
        set_type=set_type,
        released_at=released_at,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_scryfall() -> AsyncMock:
    """Provide an AsyncMock ScryfallClient."""
    client = AsyncMock()
    client.get_sets = AsyncMock(return_value=[])
    return client


@pytest.fixture
def mock_bulk() -> AsyncMock:
    """Provide an AsyncMock ScryfallBulkClient."""
    client = AsyncMock()
    client.get_card = AsyncMock(return_value=None)
    client.get_cards = AsyncMock(return_value={})
    return client


# ===========================================================================
# rotation_check tests
# ===========================================================================


class TestRotationCheck:
    """Tests for the rotation_check workflow."""

    async def test_lists_standard_legal_sets(
        self, mock_scryfall: AsyncMock, mock_bulk: AsyncMock
    ) -> None:
        """Returns a list of Standard-legal sets."""
        sets = [
            _mock_set("one", "Phyrexia: All Will Be One", released_at="2023-02-03"),
            _mock_set("mom", "March of the Machine", released_at="2023-04-21"),
            _mock_set("woe", "Wilds of Eldraine", released_at="2023-09-08"),
            _mock_set("lci", "The Lost Caverns of Ixalan", released_at="2023-11-17"),
            _mock_set("mkm", "Murders at Karlov Manor", released_at="2024-02-09"),
            _mock_set("otj", "Outlaws of Thunder Junction", released_at="2024-04-19"),
            _mock_set("blb", "Bloomburrow", released_at="2024-07-26"),
            _mock_set("dsk", "Duskmourn: House of Horror", released_at="2024-09-27"),
        ]
        mock_scryfall.get_sets = AsyncMock(return_value=sets)

        result = await rotation_check(
            scryfall=mock_scryfall,
            bulk=mock_bulk,
        )

        assert result.markdown is not None
        assert result.data["standard_sets"] is not None

    async def test_check_specific_cards(
        self, mock_scryfall: AsyncMock, mock_bulk: AsyncMock
    ) -> None:
        """Checks which cards are in rotating sets."""
        sets = [
            _mock_set("one", "Phyrexia: All Will Be One", released_at="2023-02-03"),
            _mock_set("dsk", "Duskmourn: House of Horror", released_at="2024-09-27"),
        ]
        mock_scryfall.get_sets = AsyncMock(return_value=sets)

        card_a = _mock_card("Card A", set_code="one", legalities={"standard": "legal"})
        card_b = _mock_card("Card B", set_code="dsk", legalities={"standard": "legal"})
        mock_bulk.get_cards = AsyncMock(return_value={"Card A": card_a, "Card B": card_b})

        result = await rotation_check(
            scryfall=mock_scryfall,
            bulk=mock_bulk,
            cards=["Card A", "Card B"],
        )

        assert result.data["cards_checked"] is not None
        assert len(result.data["cards_checked"]) == 2

    async def test_no_cards_provided(self, mock_scryfall: AsyncMock, mock_bulk: AsyncMock) -> None:
        """Without specific cards, shows set info only."""
        sets = [
            _mock_set("dsk", "Duskmourn: House of Horror", released_at="2024-09-27"),
        ]
        mock_scryfall.get_sets = AsyncMock(return_value=sets)

        result = await rotation_check(
            scryfall=mock_scryfall,
            bulk=mock_bulk,
        )

        assert "cards_checked" not in result.data or result.data["cards_checked"] is None
        assert result.markdown is not None

    async def test_concise_format(self, mock_scryfall: AsyncMock, mock_bulk: AsyncMock) -> None:
        """Concise format produces shorter output."""
        sets = [
            _mock_set("dsk", "Duskmourn: House of Horror", released_at="2024-09-27"),
        ]
        mock_scryfall.get_sets = AsyncMock(return_value=sets)

        result = await rotation_check(
            scryfall=mock_scryfall,
            bulk=mock_bulk,
            response_format="concise",
        )

        assert result.markdown is not None

    async def test_handles_non_standard_sets(
        self, mock_scryfall: AsyncMock, mock_bulk: AsyncMock
    ) -> None:
        """Filters out non-standard set types (commander, supplemental, etc.)."""
        sets = [
            _mock_set(
                "dsk", "Duskmourn: House of Horror", set_type="expansion", released_at="2024-09-27"
            ),
            _mock_set("cmm", "Commander Masters", set_type="masters", released_at="2023-08-04"),
            _mock_set(
                "mh3", "Modern Horizons 3", set_type="draft_innovation", released_at="2024-06-14"
            ),
        ]
        mock_scryfall.get_sets = AsyncMock(return_value=sets)

        result = await rotation_check(
            scryfall=mock_scryfall,
            bulk=mock_bulk,
        )

        # Commander Masters and Modern Horizons should not appear in standard sets
        standard_set_codes = [s["code"] for s in result.data["standard_sets"]]
        assert "cmm" not in standard_set_codes
        assert "mh3" not in standard_set_codes

    async def test_unresolved_cards(self, mock_scryfall: AsyncMock, mock_bulk: AsyncMock) -> None:
        """Cards that cannot be found in bulk data are noted."""
        sets = [
            _mock_set("dsk", "Duskmourn: House of Horror", released_at="2024-09-27"),
        ]
        mock_scryfall.get_sets = AsyncMock(return_value=sets)
        mock_bulk.get_cards = AsyncMock(return_value={"Missing Card": None})

        result = await rotation_check(
            scryfall=mock_scryfall,
            bulk=mock_bulk,
            cards=["Missing Card"],
        )

        # Should note unresolved cards
        assert (
            "not found" in result.markdown.lower()
            or "unresolved" in result.markdown.lower()
            or result.data.get("unresolved") is not None
        )

    async def test_empty_sets_response(
        self, mock_scryfall: AsyncMock, mock_bulk: AsyncMock
    ) -> None:
        """Handles empty sets list gracefully."""
        mock_scryfall.get_sets = AsyncMock(return_value=[])

        result = await rotation_check(
            scryfall=mock_scryfall,
            bulk=mock_bulk,
        )

        assert result.markdown is not None
        assert result.data["standard_sets"] is not None
