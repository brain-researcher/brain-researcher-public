"""Track K+ Neuroassistant agent tools.

High-level tools for knowledge-aware planning:
- gather_evidence: Aggregate evidence from all sources
- build_knowledge_plan: Create a plan from evidence
- recommend_datasets: Shortcut for dataset recommendations
- explain: Generate evidence-based explanations

All tools are tagged with ``br_kg``, ``assistant``, and ``planner``.

This module now delegates to the Knowledge Layer (K+) implementation in
``brain_researcher.services.agent.knowledge.tools`` for unified evidence-driven
decision making. The implementation is resolved lazily to preserve the public
tool factory without introducing a static ``tools -> agent`` import back-edge.
"""

from __future__ import annotations

import importlib
from typing import Any, List

from brain_researcher.services.tools.tool_base import NeuroToolWrapper

_KNOWLEDGE_TOOLS_MODULE = "brain_researcher.services.agent.knowledge.tools"
_LAZY_EXPORTS = (
    "BuildKnowledgePlanTool",
    "ExplainTool",
    "GatherEvidenceTool",
    "RecommendDatasetsTool",
    "get_knowledge_tools",
)


def __getattr__(name: str) -> Any:
    if name in _LAZY_EXPORTS:
        module = importlib.import_module(_KNOWLEDGE_TOOLS_MODULE)
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted([*globals().keys(), *_LAZY_EXPORTS])


class NeuroassistantTools:
    """Factory for all Neuroassistant tools.

    Delegates to the Knowledge Layer (K+) implementation which provides:
    - Evidence aggregation from PubMed, NeuroStore, Dataset Catalog, Tool Catalog, KG
    - NiCLIP-based similarity scoring for brain regions and cognitive concepts
    - LLM-based intent classification (explanation, dataset_selection, pipeline_recommendation)
    - Citation formatting with links
    """

    def get_all_tools(self) -> List[NeuroToolWrapper]:
        """Get all Knowledge Layer tools.

        Returns:
            List of neuroassistant.* tools:
            - neuroassistant.gather_evidence
            - neuroassistant.build_knowledge_plan
            - neuroassistant.recommend_datasets
            - neuroassistant.explain
        """
        module = importlib.import_module(_KNOWLEDGE_TOOLS_MODULE)
        return module.get_knowledge_tools()


# Re-export tool classes for backward compatibility
__all__ = [
    "BuildKnowledgePlanTool",
    "ExplainTool",
    "GatherEvidenceTool",
    "NeuroassistantTools",
    "RecommendDatasetsTool",
    "get_knowledge_tools",
]
