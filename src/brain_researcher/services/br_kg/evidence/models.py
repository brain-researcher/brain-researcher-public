"""
Evidence models for the Neuro Knowledge Layer.

Provides unified data structures for search results from multiple knowledge sources.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, HttpUrl


class EvidenceSource(str, Enum):
    """Canonical source identifiers for evidence items."""

    PUBMED = "pubmed"
    NEUROSTORE = "neurostore"
    DATASET_CATALOG = "dataset_catalog"
    TOOL_CATALOG = "tool_catalog"
    BR_KG = "br_kg"


class EvidenceType(str, Enum):
    """Type of evidence item."""

    PUBLICATION = "publication"
    DATASET = "dataset"
    TOOL = "tool"
    CONCEPT = "concept"
    BRAIN_REGION = "brain_region"
    STATISTICAL_MAP = "statistical_map"
    COORDINATE = "coordinate"


class EvidenceItem(BaseModel):
    """
    Unified search result from any evidence source.

    This model is designed to be source-agnostic while preserving
    enough structure for downstream consumers.
    """

    # Identity
    id: str = Field(..., description="Unique identifier within source")
    source: EvidenceSource = Field(..., description="Source system")
    item_type: EvidenceType = Field(..., description="Type of evidence")

    # Core content
    title: str = Field(..., description="Human-readable title")
    description: Optional[str] = Field(
        None, description="Summary/abstract (max ~300 chars)"
    )

    # Links
    url: Optional[HttpUrl] = Field(None, description="External URL")
    doi: Optional[str] = Field(None, description="DOI if applicable")

    # Relevance
    score: float = Field(default=1.0, ge=0.0, le=1.0, description="Relevance score 0-1")

    # Source-specific metadata
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Source-specific data"
    )

    # Provenance
    fetched_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        frozen = True  # Immutable for caching
        json_encoders = {datetime: lambda v: v.isoformat()}

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return self.model_dump(mode="json")


class EvidenceBundle(BaseModel):
    """
    Aggregated results from gather_evidence().

    Contains items from multiple sources along with metadata about
    the query execution.
    """

    query: str = Field(..., description="Original search query")
    items: list[EvidenceItem] = Field(default_factory=list)
    sources_queried: list[EvidenceSource] = Field(default_factory=list)
    errors: dict[str, str] = Field(
        default_factory=dict, description="Source -> error message for failed queries"
    )
    query_time_ms: float = Field(
        default=0.0, description="Total query time in milliseconds"
    )

    @property
    def by_source(self) -> dict[EvidenceSource, list[EvidenceItem]]:
        """Group items by source."""
        result: dict[EvidenceSource, list[EvidenceItem]] = {}
        for item in self.items:
            result.setdefault(item.source, []).append(item)
        return result

    @property
    def by_type(self) -> dict[EvidenceType, list[EvidenceItem]]:
        """Group items by type."""
        result: dict[EvidenceType, list[EvidenceItem]] = {}
        for item in self.items:
            result.setdefault(item.item_type, []).append(item)
        return result

    def top_items(self, k: int = 10) -> list[EvidenceItem]:
        """Get top k items by relevance score."""
        return sorted(self.items, key=lambda x: x.score, reverse=True)[:k]

    def filter_by_source(self, source: EvidenceSource) -> list[EvidenceItem]:
        """Get items from a specific source."""
        return [item for item in self.items if item.source == source]

    def filter_by_type(self, item_type: EvidenceType) -> list[EvidenceItem]:
        """Get items of a specific type."""
        return [item for item in self.items if item.item_type == item_type]

    @property
    def total_count(self) -> int:
        """Total number of items."""
        return len(self.items)

    @property
    def has_errors(self) -> bool:
        """Check if any sources failed."""
        return bool(self.errors)

    def summary(self) -> dict[str, Any]:
        """Generate a summary of the bundle."""
        return {
            "query": self.query,
            "total_items": self.total_count,
            "sources_queried": [s.value for s in self.sources_queried],
            "items_by_source": {
                s.value: len(items) for s, items in self.by_source.items()
            },
            "errors": self.errors,
            "query_time_ms": self.query_time_ms,
        }
