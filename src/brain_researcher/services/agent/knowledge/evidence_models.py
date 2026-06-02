"""Data models for the Knowledge Layer.

These models define the core data structures for evidence gathering, aggregation,
and knowledge planning in the BR-KG system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class EvidenceSourceType(str, Enum):
    """Types of evidence sources available in the Knowledge Layer."""

    PUBMED = "pubmed"
    NEUROSTORE = "neurostore"
    DATASET_CATALOG = "dataset_catalog"
    TOOL_CATALOG = "tool_catalog"
    KG_GRAPH = "kg_graph"
    NICLIP = "niclip"


class DecisionType(str, Enum):
    """Types of decisions the Knowledge Planner can make."""

    EXPLANATION = "explanation"
    DATASET_SELECTION = "dataset_selection"
    PIPELINE_RECOMMENDATION = "pipeline_recommendation"


@dataclass
class EvidenceItem:
    """A single piece of evidence from any source.

    Attributes:
        source_type: The type of evidence source (pubmed, dataset_catalog, etc.)
        source_id: Unique identifier within the source (PMID, dataset_id, tool_id)
        label: Human-readable label/title
        relevance_score: Relevance score [0.0, 1.0]
        url: Optional URL for the evidence (PubMed link, dataset page, etc.)
        metadata: Additional source-specific metadata
    """

    source_type: EvidenceSourceType
    source_id: str
    label: str
    relevance_score: float = 1.0
    url: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate and normalize fields."""
        if not 0.0 <= self.relevance_score <= 1.0:
            self.relevance_score = max(0.0, min(1.0, self.relevance_score))

    def to_citation(self, index: int) -> str:
        """Format this evidence item as a citation reference.

        Args:
            index: The citation number (1-based)

        Returns:
            Formatted citation string with link if available
        """
        if self.url:
            return f"[{index}]({self.url})"
        return f"[{index}]"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "source_type": self.source_type.value,
            "source_id": self.source_id,
            "label": self.label,
            "relevance_score": self.relevance_score,
            "url": self.url,
            "metadata": self.metadata,
        }


@dataclass
class EvidenceBundle:
    """Aggregated evidence for a query from multiple sources.

    Attributes:
        query: The original query string
        items: List of evidence items from all sources
        total_literature_count: Count of literature/paper items
        total_dataset_count: Count of dataset items
        total_tool_count: Count of tool items
        aggregate_niclip_score: Average NiCLIP similarity score
        confidence: Overall confidence in the evidence [0.0, 1.0]
        metadata: Additional metadata about the bundle
    """

    query: str
    items: List[EvidenceItem] = field(default_factory=list)
    total_literature_count: int = 0
    total_dataset_count: int = 0
    total_tool_count: int = 0
    aggregate_niclip_score: float = 0.0
    confidence: float = 0.5
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_item(self, item: EvidenceItem) -> None:
        """Add an evidence item and update aggregates.

        Args:
            item: The evidence item to add
        """
        self.items.append(item)

        # Update type counts
        if item.source_type == EvidenceSourceType.PUBMED:
            self.total_literature_count += 1
        elif item.source_type == EvidenceSourceType.NEUROSTORE:
            self.total_literature_count += 1
        elif item.source_type == EvidenceSourceType.DATASET_CATALOG:
            self.total_dataset_count += 1
        elif item.source_type == EvidenceSourceType.TOOL_CATALOG:
            self.total_tool_count += 1

    def get_items_by_source(
        self, source_type: EvidenceSourceType
    ) -> List[EvidenceItem]:
        """Get all items from a specific source type.

        Args:
            source_type: The source type to filter by

        Returns:
            List of evidence items from that source
        """
        return [item for item in self.items if item.source_type == source_type]

    def get_top_items(self, n: int = 10) -> List[EvidenceItem]:
        """Get the top N items by relevance score.

        Args:
            n: Maximum number of items to return

        Returns:
            Top N items sorted by relevance
        """
        sorted_items = sorted(self.items, key=lambda x: x.relevance_score, reverse=True)
        return sorted_items[:n]

    def compute_confidence(self) -> float:
        """Compute overall confidence from evidence.

        Uses a weighted formula based on:
        - Literature count (log scale)
        - Dataset availability
        - Tool relevance
        - NiCLIP score

        Returns:
            Confidence score [0.0, 1.0]
        """
        import math

        # Base confidence from evidence counts
        lit_score = (
            min(1.0, self.total_literature_count / 10.0)
            if self.total_literature_count > 0
            else 0.0
        )
        dataset_score = (
            min(1.0, self.total_dataset_count / 5.0)
            if self.total_dataset_count > 0
            else 0.0
        )
        tool_score = (
            min(1.0, self.total_tool_count / 3.0) if self.total_tool_count > 0 else 0.0
        )

        # Weighted combination
        raw_score = (
            0.35 * lit_score
            + 0.30 * dataset_score
            + 0.15 * tool_score
            + 0.20 * max(0, self.aggregate_niclip_score)
        )

        # Logistic transformation for smoother scoring
        intercept = -1.0
        score_logit = intercept + raw_score * 3.0
        confidence = 1.0 / (1.0 + math.exp(-score_logit))

        # Clamp to [0.05, 0.95]
        self.confidence = max(0.05, min(0.95, confidence))
        return self.confidence

    def format_citations(self, max_citations: int = 10) -> List[Dict[str, str]]:
        """Format evidence items as citations with links.

        Args:
            max_citations: Maximum number of citations to include

        Returns:
            List of citation dictionaries with 'ref', 'label', and 'url' keys
        """
        citations = []
        for i, item in enumerate(self.get_top_items(max_citations), start=1):
            citations.append(
                {
                    "ref": f"[{i}]",
                    "label": item.label,
                    "url": item.url or "",
                    "source": item.source_type.value,
                }
            )
        return citations

    def summary(self) -> Dict[str, Any]:
        """Return a summary of the evidence bundle.

        Returns:
            Dictionary with summary statistics
        """
        return {
            "query": self.query,
            "total_items": len(self.items),
            "literature_count": self.total_literature_count,
            "dataset_count": self.total_dataset_count,
            "tool_count": self.total_tool_count,
            "niclip_score": self.aggregate_niclip_score,
            "confidence": self.confidence,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "query": self.query,
            "items": [item.to_dict() for item in self.items],
            "total_literature_count": self.total_literature_count,
            "total_dataset_count": self.total_dataset_count,
            "total_tool_count": self.total_tool_count,
            "aggregate_niclip_score": self.aggregate_niclip_score,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }


@dataclass
class KnowledgePlan:
    """Result of the Knowledge Planner's decision making.

    Attributes:
        decision_type: The type of decision (explanation, dataset_selection, pipeline_recommendation)
        query: The original query
        reasoning: Explanation of why this decision was made
        recommended_datasets: List of recommended dataset IDs
        dataset_scores: Mapping of dataset_id to relevance score
        recommended_tools: List of recommended tool/family IDs
        tool_sequence: Ordered list of tools for pipeline recommendation
        explanation: Generated explanation text (for explanation decision type)
        citations: Formatted citations from evidence
        confidence: Confidence in this plan [0.0, 1.0]
        evidence_bundle: Optional reference to the evidence used
        metadata: Additional metadata
    """

    decision_type: DecisionType
    query: str
    reasoning: str = ""
    recommended_datasets: List[str] = field(default_factory=list)
    dataset_scores: Dict[str, float] = field(default_factory=dict)
    recommended_tools: List[str] = field(default_factory=list)
    tool_sequence: List[str] = field(default_factory=list)
    explanation: Optional[str] = None
    citations: List[Dict[str, str]] = field(default_factory=list)
    confidence: float = 0.5
    evidence_bundle: Optional[EvidenceBundle] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate and normalize fields."""
        if not 0.0 <= self.confidence <= 1.0:
            self.confidence = max(0.0, min(1.0, self.confidence))

    def is_explanation(self) -> bool:
        """Check if this plan is for explanation."""
        return self.decision_type == DecisionType.EXPLANATION

    def is_dataset_selection(self) -> bool:
        """Check if this plan is for dataset selection."""
        return self.decision_type == DecisionType.DATASET_SELECTION

    def is_pipeline_recommendation(self) -> bool:
        """Check if this plan is for pipeline recommendation."""
        return self.decision_type == DecisionType.PIPELINE_RECOMMENDATION

    def get_top_datasets(self, n: int = 5) -> List[str]:
        """Get top N recommended datasets by score.

        Args:
            n: Maximum number of datasets to return

        Returns:
            List of dataset IDs sorted by score
        """
        if self.dataset_scores:
            sorted_datasets = sorted(
                self.dataset_scores.items(), key=lambda x: x[1], reverse=True
            )
            return [ds_id for ds_id, _ in sorted_datasets[:n]]
        return self.recommended_datasets[:n]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "decision_type": self.decision_type.value,
            "query": self.query,
            "reasoning": self.reasoning,
            "recommended_datasets": self.recommended_datasets,
            "dataset_scores": self.dataset_scores,
            "recommended_tools": self.recommended_tools,
            "tool_sequence": self.tool_sequence,
            "explanation": self.explanation,
            "citations": self.citations,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }


__all__ = [
    "DecisionType",
    "EvidenceBundle",
    "EvidenceItem",
    "EvidenceSourceType",
    "KnowledgePlan",
]
