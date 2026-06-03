"""Knowledge Layer for evidence-driven decision making.

This package provides:
- K+A: Evidence connectors (PubMed, NeuroStore, Dataset catalog, Tool catalog)
- K+B: NiCLIP-based similarity scoring for datasets and brain regions
- K+C: Knowledge planner for intent classification and decision making
- K+D: High-level neuroassistant tools for the agent
"""

from brain_researcher.services.agent.knowledge.evidence_models import (
    DecisionType,
    EvidenceBundle,
    EvidenceItem,
    EvidenceSourceType,
    KnowledgePlan,
)
from brain_researcher.services.agent.knowledge.evidence_connector import (
    DatasetCatalogConnector,
    EvidenceAggregator,
    EvidenceConnector,
    KGNodeConnector,
    LiteratureConnector,
    NeuroStoreConnector,
    ToolCatalogConnector,
)
from brain_researcher.services.agent.knowledge.niclip_scorer import (
    NiCLIPConnector,
    NiCLIPScorer,
    ScoredConcept,
    create_niclip_scorer,
)
from brain_researcher.services.agent.knowledge.knowledge_planner import (
    KnowledgePlanner,
    create_knowledge_planner,
)
from brain_researcher.services.agent.knowledge.memory_store import KnowledgeMemoryStore
from brain_researcher.services.agent.knowledge.llm_utils import get_llm_router
from brain_researcher.services.agent.knowledge.tools import (
    BuildKnowledgePlanTool,
    ExplainTool,
    GatherEvidenceTool,
    RecommendDatasetsTool,
    get_knowledge_tools,
    register_knowledge_tools,
)

__all__ = [
    # Models
    "DecisionType",
    "EvidenceBundle",
    "EvidenceItem",
    "EvidenceSourceType",
    "KnowledgePlan",
    # Connectors
    "DatasetCatalogConnector",
    "EvidenceAggregator",
    "EvidenceConnector",
    "KGNodeConnector",
    "LiteratureConnector",
    "NeuroStoreConnector",
    "ToolCatalogConnector",
    # NiCLIP
    "NiCLIPConnector",
    "NiCLIPScorer",
    "ScoredConcept",
    "create_niclip_scorer",
    # Planner
    "KnowledgePlanner",
    "create_knowledge_planner",
    "KnowledgeMemoryStore",
    "get_llm_router",
    # Tools
    "BuildKnowledgePlanTool",
    "ExplainTool",
    "GatherEvidenceTool",
    "RecommendDatasetsTool",
    "get_knowledge_tools",
    "register_knowledge_tools",
]
