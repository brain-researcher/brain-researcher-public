"""
Evidence connector protocol definitions.

Defines the interface that all evidence connectors must implement.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .models import EvidenceItem, EvidenceSource


@runtime_checkable
class EvidenceConnector(Protocol):
    """
    Protocol for evidence source connectors.

    Connectors are stateless query interfaces to external knowledge sources.
    They handle the translation from our unified query model to source-specific
    APIs and back.

    All connectors must implement async search methods for parallel execution.
    """

    @property
    def source(self) -> EvidenceSource:
        """Return the source identifier for this connector."""
        ...

    @property
    def is_available(self) -> bool:
        """
        Check if the connector is operational.

        Returns False if required dependencies are missing, API is unreachable,
        or the connector is otherwise disabled.
        """
        ...

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[EvidenceItem]:
        """
        Search for evidence matching the query.

        Args:
            query: Natural language search query
            limit: Maximum number of results to return
            filters: Source-specific filter parameters

        Returns:
            List of evidence items, ordered by relevance (highest first)

        Raises:
            ConnectorError: If the search fails
        """
        ...

    async def get_by_id(
        self,
        item_id: str,
    ) -> EvidenceItem | None:
        """
        Retrieve a specific evidence item by ID.

        Args:
            item_id: Source-specific identifier

        Returns:
            The evidence item, or None if not found
        """
        ...


class ConnectorError(Exception):
    """
    Base exception for connector errors.

    Captures the source, message, and optional underlying cause for
    debugging and error aggregation.
    """

    def __init__(
        self,
        source: EvidenceSource,
        message: str,
        cause: Exception | None = None,
    ):
        self.source = source
        self.message = message
        self.cause = cause
        super().__init__(f"[{source.value}] {message}")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "source": self.source.value,
            "message": self.message,
            "cause": str(self.cause) if self.cause else None,
        }


class ConnectorTimeoutError(ConnectorError):
    """Raised when a connector times out."""

    pass


class ConnectorRateLimitError(ConnectorError):
    """Raised when a connector hits rate limits."""

    def __init__(
        self,
        source: EvidenceSource,
        retry_after: float | None = None,
        cause: Exception | None = None,
    ):
        super().__init__(source, "Rate limit exceeded", cause)
        self.retry_after = retry_after


class ConnectorAuthError(ConnectorError):
    """Raised when authentication fails."""

    pass
