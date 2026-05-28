"""Track K+ - Neuro Knowledge Layer.

This package provides unified knowledge aggregation from multiple sources:
- Knowledge Graph (Neo4j/BR-KG)
- Literature (PubMed, NeuroStore)
- Dataset catalog
- Tool registry
- NiCLIP brain embeddings

Usage:
    from brain_researcher.services.neurokg.knowledge import (
        KnowledgeAggregator,
        AggregatedEvidence,
        KnowledgePlan,
        gather_knowledge,
    )

    aggregator = KnowledgeAggregator()
    evidence = await aggregator.gather(query, query_understanding)

    # Or use the convenience function
    evidence = await gather_knowledge(query)
"""

from .models import (
    AggregatedEvidence,
    EvidenceConfidence,
    KnowledgeItem,
    KnowledgePlan,
    PlanIntent,
)
from .aggregator import (
    AggregatorConfig,
    KnowledgeAggregator,
    gather_knowledge,
)
from .planner import (
    KnowledgePlanner,
    PlanCache,
    PlannerConfig,
)

__all__ = [
    # Models
    "AggregatedEvidence",
    "EvidenceConfidence",
    "KnowledgeItem",
    "KnowledgePlan",
    "PlanIntent",
    # Aggregator
    "AggregatorConfig",
    "KnowledgeAggregator",
    "gather_knowledge",
    # Planner
    "KnowledgePlanner",
    "PlanCache",
    "PlannerConfig",
]
