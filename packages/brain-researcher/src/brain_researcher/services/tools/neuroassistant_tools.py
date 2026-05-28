"""Track K+ Neuroassistant agent tools.

High-level tools for knowledge-aware planning:
- gather_evidence: Aggregate evidence from all sources
- build_knowledge_plan: Create a plan from evidence
- recommend_datasets: Shortcut for dataset recommendations
- explain: Generate evidence-based explanations

All tools are tagged with ``neurokg``, ``assistant``, and ``planner``.

This module now delegates to the new Knowledge Layer (K+) implementation
in brain_researcher.services.agent.knowledge.tools for unified evidence-driven
decision making.
"""

from __future__ import annotations

from typing import List

from brain_researcher.services.tools.tool_base import NeuroToolWrapper

# Import the new Knowledge Layer tools (Track K+)
from brain_researcher.services.agent.knowledge.tools import (
    GatherEvidenceTool,
    BuildKnowledgePlanTool,
    RecommendDatasetsTool,
    ExplainTool,
    get_knowledge_tools,
)


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
        return get_knowledge_tools()


# Re-export tool classes for backward compatibility
__all__ = [
    "BuildKnowledgePlanTool",
    "ExplainTool",
    "GatherEvidenceTool",
    "NeuroassistantTools",
    "RecommendDatasetsTool",
    "get_knowledge_tools",
]
