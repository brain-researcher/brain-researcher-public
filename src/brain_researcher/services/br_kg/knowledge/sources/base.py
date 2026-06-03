"""Base protocol for evidence sources in Track K+.

All evidence source adapters must implement this protocol.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import KnowledgeItem


@dataclass
class SourceCapabilities:
    """Declares what an evidence source can provide."""

    supports_text_search: bool = False
    supports_semantic_search: bool = False
    supports_coordinate_lookup: bool = False
    supports_entity_resolution: bool = False
    supports_streaming: bool = False

    max_results_per_query: int = 100
    default_timeout_seconds: float = 10.0

    # Whether this source requires external network calls
    is_local: bool = True

    # Tags for categorization
    tags: list[str] = field(default_factory=list)


class BaseEvidenceSource(ABC):
    """Abstract base class for evidence sources.

    Each source adapter wraps an existing service (KG, PubMed, NiCLIP, etc.)
    and converts results to KnowledgeItem format.
    """

    @property
    @abstractmethod
    def source_id(self) -> str:
        """Unique identifier for this source (e.g., 'br_kg', 'pubmed')."""
        ...

    @property
    @abstractmethod
    def capabilities(self) -> SourceCapabilities:
        """What this source can do."""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if the source is currently reachable."""
        ...

    @abstractmethod
    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        filters: dict | None = None,
    ) -> Sequence[KnowledgeItem]:
        """Search for evidence items matching the query.

        Args:
            query: Search query string
            limit: Maximum number of results
            filters: Optional source-specific filters

        Returns:
            Sequence of KnowledgeItem objects
        """
        ...

    async def get_by_id(self, item_id: str) -> KnowledgeItem | None:
        """Retrieve a specific item by its identifier.

        Default implementation returns None. Override if the source supports
        direct item lookup.
        """
        return None

    async def close(self) -> None:
        """Clean up resources. Override if needed."""
        pass


__all__ = [
    "BaseEvidenceSource",
    "SourceCapabilities",
]
