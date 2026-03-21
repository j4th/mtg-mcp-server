"""Base HTTP client with rate limiting, retries, and structured logging.

All service clients inherit from BaseClient to get consistent behavior for
rate limiting, retry logic, and observability.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import TYPE_CHECKING

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

if TYPE_CHECKING:
    from typing import Any

    from tenacity import RetryCallState


class ServiceError(Exception):
    """Base exception for service client errors."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.retry_after = retry_after


def _is_retryable(exc: BaseException) -> bool:
    """Return True if the exception represents a retryable error."""
    if not isinstance(exc, ServiceError):
        return False
    if exc.status_code is None:
        return True  # Network-level error (timeout, DNS, connection) — always retry
    return exc.status_code in (429, 500, 502, 503, 504)


def _wait_for_retry_after(retry_state: RetryCallState) -> float:
    """Use Retry-After header value when available, otherwise exponential backoff."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, ServiceError) and exc.retry_after is not None:
        return exc.retry_after
    if isinstance(exc, ServiceError) and exc.status_code == 429:
        return 1.0
    return wait_exponential(multiplier=1, min=1, max=30)(retry_state)


class BaseClient:
    """Async HTTP client with rate limiting, retries, and structured logging.

    Use as an async context manager::

        async with ScryfallClient() as client:
            card = await client.get_card_by_name("Sol Ring")
    """

    def __init__(
        self,
        base_url: str,
        rate_limit_rps: float = 10.0,
        user_agent: str = "mtg-mcp/0.1.0",
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url
        self._rate_limit_rps = rate_limit_rps
        self._user_agent = user_agent
        self._timeout = timeout
        self._semaphore = asyncio.Semaphore(1)
        self._client: httpx.AsyncClient | None = None
        self._log: structlog.stdlib.BoundLogger = structlog.get_logger(
            service=self.__class__.__name__,
        )

    async def __aenter__(self) -> BaseClient:
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            headers={
                "User-Agent": self._user_agent,
                "Accept": "application/json",
            },
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client:
            try:
                await self._client.aclose()
            except Exception:
                self._log.warning("client_close_error")
            finally:
                self._client = None

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=_wait_for_retry_after,
        reraise=True,
    )
    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Make an HTTP request with rate limiting, logging, and retry."""
        if self._client is None:
            raise RuntimeError(
                f"{self.__class__.__name__} is not initialized. "
                "Use it as an async context manager: 'async with Client() as client:'"
            )

        async with self._semaphore:
            delay = 1.0 / self._rate_limit_rps
            try:
                start = time.monotonic()
                response = await self._client.request(method, path, **kwargs)
                elapsed_ms = (time.monotonic() - start) * 1000

                self._log.debug(
                    "http_request",
                    method=method,
                    url=f"{self._base_url}{path}",
                    status=response.status_code,
                    elapsed_ms=round(elapsed_ms, 1),
                )

                if response.status_code >= 400:
                    body = response.text[:500]
                    retry_after = None
                    if response.status_code == 429:
                        raw = response.headers.get("Retry-After")
                        if raw is not None:
                            with contextlib.suppress(ValueError):
                                retry_after = float(raw)
                    self._log.error(
                        "http_error",
                        method=method,
                        url=f"{self._base_url}{path}",
                        status=response.status_code,
                        body=body,
                    )
                    raise ServiceError(
                        f"HTTP {response.status_code}: {body}",
                        status_code=response.status_code,
                        retry_after=retry_after,
                    )

                return response
            except httpx.TimeoutException as exc:
                self._log.error("http_timeout", method=method, url=f"{self._base_url}{path}")
                raise ServiceError(f"Request timed out: {method} {path}", status_code=None) from exc
            except httpx.ConnectError as exc:
                self._log.error("http_connect_error", method=method, url=f"{self._base_url}{path}")
                raise ServiceError(f"Connection failed: {method} {path}", status_code=None) from exc
            finally:
                await asyncio.sleep(delay)

    async def _get(self, path: str, **kwargs: Any) -> httpx.Response:
        """Make a GET request."""
        return await self._request("GET", path, **kwargs)

    async def _post(self, path: str, **kwargs: Any) -> httpx.Response:
        """Make a POST request."""
        return await self._request("POST", path, **kwargs)
