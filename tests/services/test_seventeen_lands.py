"""Tests for the 17Lands service client."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from mtg_mcp_server.services.seventeen_lands import SeventeenLandsClient, SeventeenLandsError
from mtg_mcp_server.types import ArchetypeRating, DraftCardRating

FIXTURES = Path(__file__).parent.parent / "fixtures" / "seventeen_lands"
BASE_URL = "https://www.17lands.com"


def _load_fixture(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text())


class TestCardRatings:
    @respx.mock
    async def test_returns_card_ratings(self):
        fixture = _load_fixture("card_ratings_lci.json")
        respx.get(
            f"{BASE_URL}/card_ratings/data",
            params={"expansion": "LCI", "event_type": "PremierDraft"},
        ).mock(return_value=httpx.Response(200, json=fixture))

        async with SeventeenLandsClient(base_url=BASE_URL) as client:
            ratings = await client.card_ratings("LCI")

        assert len(ratings) == 5
        assert all(isinstance(r, DraftCardRating) for r in ratings)
        first = ratings[0]
        assert first.name == "Abuelo's Awakening"
        assert first.color == "W"
        assert first.rarity == "rare"
        assert first.seen_count == 34070
        assert first.avg_seen == pytest.approx(4.633, abs=0.01)
        assert first.ever_drawn_win_rate == pytest.approx(0.5014, abs=0.001)

    @respx.mock
    async def test_passes_event_type_parameter(self):
        fixture = _load_fixture("card_ratings_lci.json")
        respx.get(
            f"{BASE_URL}/card_ratings/data",
            params={"expansion": "LCI", "event_type": "TradDraft"},
        ).mock(return_value=httpx.Response(200, json=fixture))

        async with SeventeenLandsClient(base_url=BASE_URL) as client:
            ratings = await client.card_ratings("LCI", event_type="TradDraft")

        assert len(ratings) == 5

    @respx.mock
    async def test_empty_response(self):
        respx.get(
            f"{BASE_URL}/card_ratings/data",
            params={"expansion": "FAKE", "event_type": "PremierDraft"},
        ).mock(return_value=httpx.Response(200, json=[]))

        async with SeventeenLandsClient(base_url=BASE_URL) as client:
            ratings = await client.card_ratings("FAKE")

        assert ratings == []

    @respx.mock
    async def test_server_error_raises(self):
        respx.get(
            f"{BASE_URL}/card_ratings/data",
            params={"expansion": "LCI", "event_type": "PremierDraft"},
        ).mock(return_value=httpx.Response(500, text="Internal Server Error"))

        async with SeventeenLandsClient(base_url=BASE_URL) as client:
            with pytest.raises(SeventeenLandsError):
                await client.card_ratings("LCI")


class TestColorRatings:
    @respx.mock
    async def test_returns_archetype_ratings(self):
        fixture = _load_fixture("color_ratings_lci.json")
        respx.get(
            f"{BASE_URL}/color_ratings/data",
            params={
                "expansion": "LCI",
                "event_type": "PremierDraft",
                "start_date": "2023-11-07",
                "end_date": "2024-02-07",
            },
        ).mock(return_value=httpx.Response(200, json=fixture))

        async with SeventeenLandsClient(base_url=BASE_URL) as client:
            ratings = await client.color_ratings(
                "LCI", start_date="2023-11-07", end_date="2024-02-07"
            )

        assert len(ratings) == 11
        assert all(isinstance(r, ArchetypeRating) for r in ratings)

        # Check summary row
        summary = ratings[0]
        assert summary.is_summary is True
        assert summary.color_name == "Two-color"
        assert summary.wins == 445484
        assert summary.games == 791280
        assert summary.win_rate == pytest.approx(0.5631, abs=0.001)

        # Check a non-summary row
        azorius = ratings[1]
        assert azorius.is_summary is False
        assert azorius.color_name == "Azorius (WU)"
        assert azorius.win_rate == pytest.approx(0.5793, abs=0.001)

    @respx.mock
    async def test_passes_event_type_parameter(self):
        fixture = _load_fixture("color_ratings_lci.json")
        respx.get(
            f"{BASE_URL}/color_ratings/data",
            params={
                "expansion": "LCI",
                "event_type": "TradDraft",
                "start_date": "2023-11-07",
                "end_date": "2024-02-07",
            },
        ).mock(return_value=httpx.Response(200, json=fixture))

        async with SeventeenLandsClient(base_url=BASE_URL) as client:
            ratings = await client.color_ratings(
                "LCI",
                start_date="2023-11-07",
                end_date="2024-02-07",
                event_type="TradDraft",
            )

        assert len(ratings) == 11

    @respx.mock
    async def test_server_error_raises(self):
        respx.get(
            f"{BASE_URL}/color_ratings/data",
            params={
                "expansion": "LCI",
                "event_type": "PremierDraft",
                "start_date": "2023-11-07",
                "end_date": "2024-02-07",
            },
        ).mock(return_value=httpx.Response(500, text="Internal Server Error"))

        async with SeventeenLandsClient(base_url=BASE_URL) as client:
            with pytest.raises(SeventeenLandsError):
                await client.color_ratings("LCI", start_date="2023-11-07", end_date="2024-02-07")


class TestArchetypeRatingWinRate:
    def test_win_rate_calculated(self):
        rating = ArchetypeRating(color_name="Azorius (WU)", wins=87307, games=150735)
        assert rating.win_rate == pytest.approx(0.5793, abs=0.001)

    def test_win_rate_zero_games(self):
        rating = ArchetypeRating(color_name="Empty", wins=0, games=0)
        assert rating.win_rate is None
