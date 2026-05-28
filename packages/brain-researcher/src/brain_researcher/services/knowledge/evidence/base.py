"""Core types for the Knowledge Layer evidence system.

This module defines the fundamental abstractions:
- EvidenceResult: A single piece of evidence from any source
- EvidenceBundle: Aggregated evidence from multiple sources
- EvidenceQuery: Query specification for evidence sources
- EvidenceSource: Protocol for implementing evidence source adapters
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


class EvidenceSourceType(str, Enum):
    """Types of evidence sources supported by the Knowledge Layer."""

    KNOWLEDGE_GRAPH = "kg"
    LITERATURE = "pubmed"
    NEUROSTORE = "neurostore"
    DATASET_CATALOG = "datasets"
    TOOL_REGISTRY = "tools"
    NICLIP = "niclip"


@dataclass
class EvidenceResult:
    """A single piece of evidence from any source.

    This is the universal return type for all evidence sources, enabling
    uniform handling regardless of the underlying data source.
    """

    source: EvidenceSourceType
    id: str
    title: str | None
    relevance_score: float  # 0.0 - 1.0
    confidence: float  # 0.0 - 1.0
    payload: Dict[str, Any] = field(default_factory=dict)
    url: str | None = None
    summary: str | None = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "source": self.source.value,
            "id": self.id,
            "title": self.title,
            "relevance_score": self.relevance_score,
            "confidence": self.confidence,
            "payload": self.payload,
            "url": self.url,
            "summary": self.summary,
        }


@dataclass
class EvidenceQuery:
    """Query specification for evidence sources.

    This provides a unified way to query evidence from multiple sources
    with optional filtering by entities, coordinates, and other criteria.
    """

    text: str
    entities: List[Dict[str, Any]] = field(default_factory=list)
    coordinates: Optional[List[tuple]] = None
    filters: Dict[str, Any] = field(default_factory=dict)
    limit: int = 10

    # Source-specific filters
    node_types: Optional[List[str]] = None  # For KG queries
    modality: Optional[str] = None  # For dataset queries
    min_subjects: Optional[int] = None  # For dataset queries
    year_min: Optional[int] = None  # For literature queries
    year_max: Optional[int] = None  # For literature queries


@dataclass
class EvidenceBundle:
    """Aggregated evidence from multiple sources.

    This bundles evidence from different sources into a single structure
    that the Knowledge Planner can reason over.
    """

    concepts: List[EvidenceResult] = field(default_factory=list)
    brain_regions: List[EvidenceResult] = field(default_factory=list)
    datasets: List[EvidenceResult] = field(default_factory=list)
    tools: List[EvidenceResult] = field(default_factory=list)
    papers: List[EvidenceResult] = field(default_factory=list)
    query_interpretation: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "concepts": [e.to_dict() for e in self.concepts],
            "brain_regions": [e.to_dict() for e in self.brain_regions],
            "datasets": [e.to_dict() for e in self.datasets],
            "tools": [e.to_dict() for e in self.tools],
            "papers": [e.to_dict() for e in self.papers],
            "query_interpretation": self.query_interpretation,
            "metadata": self.metadata,
        }

    @property
    def total_count(self) -> int:
        """Total number of evidence items across all categories."""
        return (
            len(self.concepts)
            + len(self.brain_regions)
            + len(self.datasets)
            + len(self.tools)
            + len(self.papers)
        )

    def is_empty(self) -> bool:
        """Check if the bundle contains no evidence."""
        return self.total_count == 0


@runtime_checkable
class EvidenceSource(Protocol):
    """Protocol for evidence source implementations.

    All evidence sources must implement this interface to be used by the
    Knowledge Layer. The protocol uses async methods for uniformity -
    sync implementations can use asyncio.to_thread() internally.
    """

    @property
    def source_type(self) -> EvidenceSourceType:
        """Return the type of this evidence source."""
        ...

    @property
    def source_id(self) -> str:
        """Return unique identifier for this source."""
        ...

    async def query(self, query: EvidenceQuery) -> List[EvidenceResult]:
        """Query this source for evidence.

        Args:
            query: Query specification with text, filters, and limits.

        Returns:
            List of EvidenceResult objects matching the query.
        """
        ...

    async def health_check(self) -> bool:
        """Check if this source is available and healthy.

        Returns:
            True if the source is operational, False otherwise.
        """
        ...


class SyncEvidenceSourceAdapter:
    """Adapter to convert sync evidence sources to async interface.

    Use this as a base class when wrapping synchronous services.
    """

    @property
    def source_type(self) -> EvidenceSourceType:
        raise NotImplementedError

    @property
    def source_id(self) -> str:
        raise NotImplementedError

    def query_sync(self, query: EvidenceQuery) -> List[EvidenceResult]:
        """Synchronous query implementation - override this."""
        raise NotImplementedError

    def health_check_sync(self) -> bool:
        """Synchronous health check - override this."""
        return True

    async def query(self, query: EvidenceQuery) -> List[EvidenceResult]:
        """Async wrapper around sync query."""
        return await asyncio.to_thread(self.query_sync, query)

    async def health_check(self) -> bool:
        """Async wrapper around sync health check."""
        return await asyncio.to_thread(self.health_check_sync)


__all__ = [
    "EvidenceBundle",
    "EvidenceQuery",
    "EvidenceResult",
    "EvidenceSource",
    "EvidenceSourceType",
    "SyncEvidenceSourceAdapter",
]
