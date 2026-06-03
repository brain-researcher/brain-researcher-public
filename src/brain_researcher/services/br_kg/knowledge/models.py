"""Core data models for Track K+ - Neuro Knowledge Layer.

This module defines the data structures used throughout the knowledge layer:
- KnowledgeItem: Individual piece of evidence from any source
- AggregatedEvidence: Collection of evidence from multiple sources
- KnowledgePlan: LLM-driven planning output
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from brain_researcher.services.shared.brkg_evidence_models import EvidenceItem


class EvidenceConfidence(str, Enum):
    """Confidence level of aggregated evidence."""

    APPROXIMATE = "approximate"  # Fast phase results
    COMPLETE = "complete"  # Full phase with external sources


class PlanIntent(str, Enum):
    """What the knowledge planner recommends doing."""

    EXPLANATION = "explanation"  # Just explain, don't run pipeline
    DATASET_SELECTION = "dataset_selection"  # Help user pick datasets
    PIPELINE_RECOMMENDATION = "pipeline_recommendation"  # Recommend + run pipeline


@dataclass
class KnowledgeItem:
    """Individual knowledge item from any evidence source.

    This is a lightweight wrapper that can convert to/from EvidenceItem
    for compatibility with the existing evidence system.
    """

    # Identity
    id: str
    source_id: str  # e.g., "br_kg", "pubmed", "niclip"

    # Content
    title: str
    description: Optional[str] = None

    # Relevance
    score: float = 0.0  # 0-1 relevance score
    confidence: float = 1.0  # 0-1 confidence in the score

    # Metadata
    url: Optional[str] = None
    doi: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Timing
    retrieved_at: datetime = field(default_factory=datetime.utcnow)

    def to_evidence_item(self) -> "EvidenceItem":
        """Convert to the shared orchestrator-shaped EvidenceItem format."""
        from brain_researcher.services.shared.brkg_evidence_models import (
            EvidenceItem,
            EvidenceSource,
            EvidenceType,
            ValidationStatus,
        )

        # Map source_id to EvidenceSource
        source_map = {
            "br_kg": EvidenceSource.BR_KG,
            "pubmed": EvidenceSource.PUBMED if hasattr(EvidenceSource, "PUBMED") else EvidenceSource.EXTERNAL_API,
            "neurostore": EvidenceSource.NEUROSTORE if hasattr(EvidenceSource, "NEUROSTORE") else EvidenceSource.EXTERNAL_API,
            "niclip": EvidenceSource.NICLIP if hasattr(EvidenceSource, "NICLIP") else EvidenceSource.COMPUTED,
            "tool_registry": EvidenceSource.TOOL_REGISTRY if hasattr(EvidenceSource, "TOOL_REGISTRY") else EvidenceSource.AGENT,
            "dataset_catalog": EvidenceSource.DATASET_CATALOG if hasattr(EvidenceSource, "DATASET_CATALOG") else EvidenceSource.BR_KG,
        }

        # Map to EvidenceType based on source
        type_map = {
            "br_kg": EvidenceType.KG_NODE if hasattr(EvidenceType, "KG_NODE") else EvidenceType.DATASET,
            "pubmed": EvidenceType.LITERATURE if hasattr(EvidenceType, "LITERATURE") else EvidenceType.CITATION,
            "neurostore": EvidenceType.LITERATURE if hasattr(EvidenceType, "LITERATURE") else EvidenceType.CITATION,
            "niclip": EvidenceType.EMBEDDING_MATCH if hasattr(EvidenceType, "EMBEDDING_MATCH") else EvidenceType.RESULT,
            "tool_registry": EvidenceType.TOOL_MATCH if hasattr(EvidenceType, "TOOL_MATCH") else EvidenceType.METHOD,
            "dataset_catalog": EvidenceType.DATASET,
        }

        return EvidenceItem(
            id=self.id,
            type=type_map.get(self.source_id, EvidenceType.RESULT),
            source=source_map.get(self.source_id, EvidenceSource.EXTERNAL_API),
            title=self.title,
            description=self.description,
            value=str(round(self.score, 4)) if self.score else None,
            url=self.url,
            doi=self.doi,
            timestamp=self.retrieved_at,
            validation_status=ValidationStatus.VALID,
            metadata={
                **self.metadata,
                "knowledge_score": self.score,
                "knowledge_confidence": self.confidence,
            },
        )


@dataclass
class AggregatedEvidence:
    """Result of aggregating evidence from multiple sources.

    Supports progressive loading with approximate -> complete confidence.
    """

    query: str
    items: List[KnowledgeItem] = field(default_factory=list)
    confidence: EvidenceConfidence = EvidenceConfidence.APPROXIMATE

    # Source tracking
    sources_queried: List[str] = field(default_factory=list)
    sources_succeeded: List[str] = field(default_factory=list)
    sources_failed: List[str] = field(default_factory=list)

    # Timing
    aggregated_at: datetime = field(default_factory=datetime.utcnow)
    duration_ms: Optional[float] = None

    # Errors
    errors: List[str] = field(default_factory=list)

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def total_items(self) -> int:
        """Total number of evidence items."""
        return len(self.items)

    @property
    def success_rate(self) -> float:
        """Fraction of sources that succeeded."""
        if not self.sources_queried:
            return 0.0
        return len(self.sources_succeeded) / len(self.sources_queried)

    def items_by_source(self) -> Dict[str, List[KnowledgeItem]]:
        """Group items by their source."""
        result: Dict[str, List[KnowledgeItem]] = {}
        for item in self.items:
            result.setdefault(item.source_id, []).append(item)
        return result

    def to_evidence_items(self) -> List["EvidenceItem"]:
        """Convert all items to EvidenceItem format."""
        return [item.to_evidence_item() for item in self.items]


@dataclass
class KnowledgePlan:
    """Output of the Knowledge Planner.

    Tells the orchestrator what to do based on aggregated evidence.
    """

    # What to do
    intent: PlanIntent

    # Recommendations
    recommended_datasets: List[str] = field(default_factory=list)
    recommended_tools: List[str] = field(default_factory=list)

    # Reasoning
    justification: str = ""
    evidence_ids: List[str] = field(default_factory=list)  # IDs of supporting evidence

    # Confidence
    confidence: float = 0.0  # 0-1

    # Caching
    cache_key: Optional[str] = None
    cached_at: Optional[datetime] = None

    # Timing
    created_at: datetime = field(default_factory=datetime.utcnow)
    planning_duration_ms: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "intent": self.intent.value,
            "recommended_datasets": self.recommended_datasets,
            "recommended_tools": self.recommended_tools,
            "justification": self.justification,
            "evidence_ids": self.evidence_ids,
            "confidence": self.confidence,
            "cache_key": self.cache_key,
            "created_at": self.created_at.isoformat(),
        }


__all__ = [
    "AggregatedEvidence",
    "EvidenceConfidence",
    "KnowledgeItem",
    "KnowledgePlan",
    "PlanIntent",
]
