"""Base HTTP client with rate limiting, retries, and structured logging.

All service clients inherit from BaseClient to get consistent behavior for
rate limiting, retry logic, and observability.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import TYPE_CHECKING, Self

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from mtg_mcp_server import __version__

DEFAULT_USER_AGENT = f"mtg-mcp-server/{__version__}"

if TYPE_CHECKING:
    from typing import Any

    from tenacity import RetryCallState


class ServiceError(Exception):
    """Base exception for service client errors.

    Args:
        message: Human-readable error description.
        status_code: HTTP status code, or None for network-level errors.
        retry_after: Seconds to wait before retrying (from Retry-After header).
    """

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
    """Return True if the exception represents a retryable HTTP/network error.

    Network errors (``status_code is None``) are always retryable. HTTP errors
    are retryable only for rate limiting (429) and server errors (500, 502, 503, 504).
    """
    if not isinstance(exc, ServiceError):
        return False
    if exc.status_code is None:
        return True  # Network-level error (timeout, DNS, connection) — always retry
    return exc.status_code in (429, 500, 502, 503, 504)


def _wait_for_retry_after(retry_state: RetryCallState) -> float:
    """Determine how long to wait before retrying a failed request.

    Fallback chain:
        1. ``Retry-After`` header value (if present on the exception).
        2. Fixed 1-second delay for 429 responses without a header.
        3. Exponential backoff (1s-30s) for all other retryable errors.
    """
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, ServiceError) and exc.retry_after is not None:
        return exc.retry_after
    if isinstance(exc, ServiceError) and exc.status_code == 429:
        return 1.0  # 429 without Retry-After: conservative 1s default
    return wait_exponential(multiplier=1, min=1, max=30)(retry_state)


class BaseClient:
    """Async HTTP client with rate limiting, retries, and structured logging.

    Subclass this for each external API. The base class provides:
        - httpx.AsyncClient lifecycle via async context manager
        - Per-request rate limiting via semaphore + sleep
        - Automatic retry with exponential backoff (tenacity)
        - Structured logging of every request and error

    Use as an async context manager::

        async with ScryfallClient() as client:
            card = await client.get_card_by_name("Sol Ring")

    Args:
        base_url: API base URL (prepended to all request paths).
        rate_limit_rps: Maximum requests per second.
        user_agent: User-Agent header sent with every request.
        timeout: Request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        rate_limit_rps: float = 10.0,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 30.0,
    ) -> None:
        if rate_limit_rps <= 0:
            raise ValueError(f"rate_limit_rps must be positive, got {rate_limit_rps}")
        self._base_url = base_url
        self._rate_limit_rps = rate_limit_rps
        self._user_agent = user_agent
        self._timeout = timeout
        # Semaphore(1) serializes requests to enforce rate limiting
        self._semaphore = asyncio.Semaphore(1)
        self._client: httpx.AsyncClient | None = None
        self._log: structlog.stdlib.BoundLogger = structlog.get_logger(
            service=self.__class__.__name__,
        )

    async def __aenter__(self) -> Self:
        """Create the httpx client. Return ``Self`` (not ``BaseClient``) for correct type inference through ``AsyncExitStack``."""
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
        """Close the httpx client, swallowing close errors."""
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
        """Make an HTTP request with rate limiting, logging, and retry.

        Args:
            method: HTTP method (``"GET"``, ``"POST"``, etc.).
            path: URL path appended to ``base_url``.
            **kwargs: Passed through to ``httpx.AsyncClient.request()``.

        Returns:
            Successful HTTP response.

        Raises:
            ServiceError: On HTTP 4xx/5xx or network errors.
            RuntimeError: If called outside the async context manager.
        """
        if self._client is None:
            raise RuntimeError(
                f"{self.__class__.__name__} is not initialized. "
                "Use it as an async context manager: 'async with Client() as client:'"
            )

        async with self._semaphore:
            min_interval = 1.0 / self._rate_limit_rps
            start = time.monotonic()
            try:
                response = await self._client.request(method, path, **kwargs)
                elapsed = time.monotonic() - start

                self._log.debug(
                    "http_request",
                    method=method,
                    url=f"{self._base_url}{path}",
                    status=response.status_code,
                    elapsed_ms=round(elapsed * 1000, 1),
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
            except httpx.RequestError as exc:
                self._log.error(
                    "http_request_error",
                    method=method,
                    url=f"{self._base_url}{path}",
                    error=type(exc).__name__,
                )
                raise ServiceError(
                    f"Network error during {method} {path}: {exc}", status_code=None
                ) from exc
            finally:
                # Enforce minimum interval between requests regardless of success/failure.
                # Combined with Semaphore(1), this limits throughput to rate_limit_rps.
                remaining = min_interval - (time.monotonic() - start)
                if remaining > 0:
                    await asyncio.sleep(remaining)

    async def _get(self, path: str, **kwargs: Any) -> httpx.Response:
        """Make a GET request."""
        return await self._request("GET", path, **kwargs)

    async def _post(self, path: str, **kwargs: Any) -> httpx.Response:
        """Make a POST request."""
        return await self._request("POST", path, **kwargs)
