"""
Base connector with shared async HTTP utilities.

Provides common functionality for connectors that need to make HTTP requests,
including retry logic, rate limiting, and error handling.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

from ..models import EvidenceItem, EvidenceSource
from ..protocols import ConnectorError, ConnectorRateLimitError, ConnectorTimeoutError


class BaseConnector(ABC):
    """
    Abstract base class for evidence connectors.

    Provides:
    - Async HTTP client management
    - Retry with exponential backoff
    - Logging
    - Common error handling
    """

    def __init__(
        self,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff_factor: float = 1.0,
    ):
        """
        Initialize the connector.

        Args:
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
            backoff_factor: Multiplier for exponential backoff
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._client: "httpx.AsyncClient | None" = None

    @property
    @abstractmethod
    def source(self) -> EvidenceSource:
        """Return the source identifier for this connector."""
        ...

    @property
    def is_available(self) -> bool:
        """Default availability check - override for specific requirements."""
        return True

    @abstractmethod
    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[EvidenceItem]:
        """Implement source-specific search."""
        ...

    async def get_by_id(self, item_id: str) -> EvidenceItem | None:
        """Default implementation - override if source supports direct lookup."""
        return None

    async def _get_client(self) -> "httpx.AsyncClient":
        """Get or create async HTTP client."""
        if httpx is None:
            raise ImportError("httpx is required for HTTP connectors. Install with: pip install httpx")

        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={"User-Agent": "BrainResearcher/1.0"},
                follow_redirects=True,
            )
        return self._client

    async def _fetch_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        method: str = "GET",
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Fetch JSON from URL with retry and error handling.

        Uses exponential backoff for transient errors (429, 5xx).

        Args:
            url: Target URL
            params: Query parameters
            method: HTTP method (GET or POST)
            json_body: JSON body for POST requests

        Returns:
            Parsed JSON response

        Raises:
            ConnectorError: On permanent failure
            ConnectorRateLimitError: On 429 after all retries
            ConnectorTimeoutError: On timeout
        """
        if httpx is None:
            raise ImportError("httpx is required for HTTP connectors")

        client = await self._get_client()
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                if method.upper() == "GET":
                    response = await client.get(url, params=params)
                else:
                    response = await client.post(url, params=params, json=json_body)

                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as e:
                status = e.response.status_code

                if status == 429:
                    # Rate limited - check for Retry-After header
                    retry_after = e.response.headers.get("Retry-After")
                    wait_time = float(retry_after) if retry_after else (self.backoff_factor * (2**attempt))
                    self.logger.warning(f"Rate limited, waiting {wait_time:.1f}s (attempt {attempt + 1})")
                    await asyncio.sleep(wait_time)
                    last_error = ConnectorRateLimitError(self.source, wait_time, e)

                elif status >= 500:
                    # Server error - retry with backoff
                    wait_time = self.backoff_factor * (2**attempt)
                    self.logger.warning(f"Server error {status}, retrying in {wait_time:.1f}s")
                    await asyncio.sleep(wait_time)
                    last_error = e

                else:
                    # Client error - don't retry
                    raise ConnectorError(self.source, f"HTTP {status}: {e.response.text[:200]}", e)

            except httpx.TimeoutException as e:
                wait_time = self.backoff_factor * (2**attempt)
                self.logger.warning(f"Timeout, retrying in {wait_time:.1f}s")
                await asyncio.sleep(wait_time)
                last_error = ConnectorTimeoutError(self.source, "Request timed out", e)

            except httpx.RequestError as e:
                # Network error - retry with backoff
                wait_time = self.backoff_factor * (2**attempt)
                self.logger.warning(f"Request error: {e}, retrying in {wait_time:.1f}s")
                await asyncio.sleep(wait_time)
                last_error = e

        # All retries exhausted
        if isinstance(last_error, ConnectorError):
            raise last_error
        raise ConnectorError(self.source, f"Failed after {self.max_retries} retries", last_error)

    async def _fetch_xml(
        self,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> str:
        """
        Fetch XML content from URL with retry.

        Returns raw XML string for parsing by the caller.
        """
        if httpx is None:
            raise ImportError("httpx is required for HTTP connectors")

        client = await self._get_client()
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                response = await client.get(url, params=params)
                response.raise_for_status()
                return response.text

            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                if status == 429 or status >= 500:
                    wait_time = self.backoff_factor * (2**attempt)
                    await asyncio.sleep(wait_time)
                    last_error = e
                else:
                    raise ConnectorError(self.source, f"HTTP {status}", e)

            except (httpx.TimeoutException, httpx.RequestError) as e:
                wait_time = self.backoff_factor * (2**attempt)
                await asyncio.sleep(wait_time)
                last_error = e

        raise ConnectorError(self.source, f"Failed after {self.max_retries} retries", last_error)

    async def close(self) -> None:
        """Close HTTP client and release resources."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "BaseConnector":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()


class SyncWrapperConnector(BaseConnector):
    """
    Base class for connectors that wrap synchronous functions.

    Runs sync code in a thread pool executor to avoid blocking the event loop.
    """

    async def _run_sync(self, func, *args, **kwargs):
        """Run a synchronous function in a thread pool executor."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))
