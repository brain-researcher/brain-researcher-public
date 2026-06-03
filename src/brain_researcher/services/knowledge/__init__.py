"""Knowledge Layer for Brain Researcher (Track K+).

This package provides a unified interface for querying and aggregating evidence
from multiple sources:
- Knowledge Graph (BR-KG via Neo4j)
- Literature (PubMed, NeuroStore)
- Datasets (catalog + OpenNeuro)
- Tools (ToolRegistry)
- Brain Foundation Model (NiCLIP embeddings)

The goal is to give the LLM agent a "knowledge oracle" that can gather evidence,
score relevance, and recommend next steps.
"""

from brain_researcher.services.knowledge.evidence.base import (
    EvidenceBundle,
    EvidenceQuery,
    EvidenceResult,
    EvidenceSource,
    EvidenceSourceType,
)
from brain_researcher.services.knowledge.planner import (
    DecisionType,
    EvidenceAggregator,
    KnowledgePlan,
    KnowledgePlanner,
    create_aggregator,
    create_planner,
)
from brain_researcher.services.knowledge.scoring.niclip_scorer import (
    NiCLIPConfig,
    NiCLIPEvidenceSource,
    NiCLIPScorer,
    ScoredConcept,
)

__all__ = [
    # Evidence types
    "EvidenceBundle",
    "EvidenceQuery",
    "EvidenceResult",
    "EvidenceSource",
    "EvidenceSourceType",
    # NiCLIP scoring
    "NiCLIPConfig",
    "NiCLIPEvidenceSource",
    "NiCLIPScorer",
    "ScoredConcept",
    # Planner
    "DecisionType",
    "EvidenceAggregator",
    "KnowledgePlan",
    "KnowledgePlanner",
    "create_aggregator",
    "create_planner",
]
