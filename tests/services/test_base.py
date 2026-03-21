"""Tests for the BaseClient HTTP client infrastructure."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from mtg_mcp.services.base import BaseClient, ServiceError


class TestBaseClientLifecycle:
    """Verify async context manager creates and closes the httpx client."""

    async def test_client_created_on_enter(self):
        async with BaseClient(base_url="https://example.com") as client:
            assert client._client is not None

    async def test_client_closed_on_exit(self):
        client = BaseClient(base_url="https://example.com")
        async with client:
            inner = client._client
        assert client._client is None
        assert inner is not None

    async def test_request_outside_context_raises_runtime_error(self):
        client = BaseClient(base_url="https://example.com")
        with pytest.raises(RuntimeError, match="not initialized"):
            await client._get("/test")


class TestBaseClientRequests:
    """Verify HTTP requests are made correctly."""

    @respx.mock
    async def test_get_returns_response(self):
        respx.get("https://example.com/test").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        async with BaseClient(base_url="https://example.com", rate_limit_rps=1000) as client:
            response = await client._get("/test")
            assert response.status_code == 200
            assert response.json() == {"ok": True}

    @respx.mock
    async def test_post_returns_response(self):
        respx.post("https://example.com/submit").mock(
            return_value=httpx.Response(200, json={"created": True})
        )
        async with BaseClient(base_url="https://example.com", rate_limit_rps=1000) as client:
            response = await client._post("/submit", json={"data": 1})
            assert response.status_code == 200


class TestBaseClientErrors:
    """Verify error handling for non-2xx responses."""

    @respx.mock
    async def test_4xx_raises_service_error_without_retry(self):
        route = respx.get("https://example.com/missing")
        route.mock(return_value=httpx.Response(404, text="Not Found"))
        async with BaseClient(base_url="https://example.com", rate_limit_rps=1000) as client:
            with pytest.raises(ServiceError, match="404") as exc_info:
                await client._get("/missing")
            assert exc_info.value.status_code == 404
            assert route.call_count == 1  # Not retried

    @respx.mock
    async def test_5xx_raises_service_error(self):
        respx.get("https://example.com/error").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        async with BaseClient(base_url="https://example.com", rate_limit_rps=1000) as client:
            with pytest.raises(ServiceError, match="500"):
                await client._get("/error")

    @respx.mock
    async def test_timeout_raises_service_error(self):
        respx.get("https://example.com/slow").mock(side_effect=httpx.ReadTimeout("timed out"))
        async with BaseClient(base_url="https://example.com", rate_limit_rps=1000) as client:
            with pytest.raises(ServiceError, match="Network error"):
                await client._get("/slow")

    @respx.mock
    async def test_connect_error_raises_service_error(self):
        respx.get("https://example.com/down").mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        async with BaseClient(base_url="https://example.com", rate_limit_rps=1000) as client:
            with pytest.raises(ServiceError, match="Network error"):
                await client._get("/down")

    def test_zero_rate_limit_raises_value_error(self):
        with pytest.raises(ValueError, match="positive"):
            BaseClient(base_url="https://example.com", rate_limit_rps=0)


class TestBaseClientRateLimiting:
    """Verify rate limiting delays between requests."""

    @respx.mock
    async def test_rate_limit_delay_enforced(self):
        respx.get("https://example.com/data").mock(return_value=httpx.Response(200, json={}))
        with patch("mtg_mcp.services.base.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            async with BaseClient(base_url="https://example.com", rate_limit_rps=10.0) as client:
                await client._get("/data")
                mock_sleep.assert_awaited_once()
                slept = mock_sleep.await_args[0][0]
                assert 0 < slept <= 0.1

    @respx.mock
    async def test_rate_limit_delay_enforced_on_error(self):
        respx.get("https://example.com/fail").mock(
            return_value=httpx.Response(404, text="Not Found")
        )
        with patch("mtg_mcp.services.base.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            async with BaseClient(base_url="https://example.com", rate_limit_rps=10.0) as client:
                with pytest.raises(ServiceError):
                    await client._get("/fail")
                mock_sleep.assert_awaited_once()
                slept = mock_sleep.await_args[0][0]
                assert 0 < slept <= 0.1


class TestBaseClientRetry:
    """Verify retry behavior on transient errors."""

    @respx.mock
    async def test_retries_on_429_then_succeeds(self):
        route = respx.get("https://example.com/rate-limited")
        route.side_effect = [
            httpx.Response(429, text="Too Many Requests"),
            httpx.Response(200, json={"ok": True}),
        ]
        async with BaseClient(base_url="https://example.com", rate_limit_rps=1000) as client:
            response = await client._get("/rate-limited")
            assert response.status_code == 200
            assert route.call_count == 2

    @respx.mock
    async def test_retries_on_429_respects_retry_after_header(self):
        route = respx.get("https://example.com/throttled")
        route.side_effect = [
            httpx.Response(429, text="Too Many Requests", headers={"Retry-After": "3"}),
            httpx.Response(200, json={"ok": True}),
        ]
        with patch("tenacity.asyncio._portable_async_sleep", new_callable=AsyncMock):
            async with BaseClient(base_url="https://example.com", rate_limit_rps=1000) as client:
                response = await client._get("/throttled")
                assert response.status_code == 200

    @respx.mock
    async def test_retries_on_503_then_succeeds(self):
        route = respx.get("https://example.com/unavailable")
        route.side_effect = [
            httpx.Response(503, text="Service Unavailable"),
            httpx.Response(200, json={"ok": True}),
        ]
        async with BaseClient(base_url="https://example.com", rate_limit_rps=1000) as client:
            response = await client._get("/unavailable")
            assert response.status_code == 200
            assert route.call_count == 2

    @respx.mock
    async def test_gives_up_after_max_retries(self):
        respx.get("https://example.com/always-fail").mock(
            return_value=httpx.Response(500, text="Server Error")
        )
        async with BaseClient(base_url="https://example.com", rate_limit_rps=1000) as client:
            with pytest.raises(ServiceError, match="500"):
                await client._get("/always-fail")

    @respx.mock
    async def test_retries_on_network_error_then_succeeds(self):
        route = respx.get("https://example.com/flaky")
        route.side_effect = [
            httpx.ConnectError("connection refused"),
            httpx.Response(200, json={"ok": True}),
        ]
        async with BaseClient(base_url="https://example.com", rate_limit_rps=1000) as client:
            response = await client._get("/flaky")
            assert response.status_code == 200
            assert route.call_count == 2
