"""
Base state definitions for the BR-KG LangGraph system.

Following Biomni's minimal state pattern while adding neuroimaging-specific fields.
"""

from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class NeuroAgentState(TypedDict):
    """
    Minimal state for neuroscience agent workflows.

    Following Biomni's pattern of keeping state minimal and focused.
    """

    # Core workflow state
    messages: Annotated[list[BaseMessage], add_messages]
    current_phase: str  # planning, tool_selection, execution, synthesis, complete
    selected_tools: list[str]

    # Optional fields for tool execution
    tool_args: dict[str, dict[str, Any]] | None
    results: dict[str, Any] | None
    error: str | None


class ResearchState(NeuroAgentState):
    """
    Extended state for complex research workflows.

    Adds fields for cross-system coordination between fMRI and BR-KG.
    """

    # fMRI-specific state
    dataset_id: str | None
    analysis_type: str | None  # glm, encoding, connectivity, etc.
    analysis_results: dict[str, Any]
    coordinates: list[list[float]]  # Brain coordinates from activation

    # BR-KG-specific state
    concepts: list[str]
    concept_relationships: dict[str, list[str]]
    literature_findings: list[dict[str, Any]]

    # Integration state
    synthesis: dict[str, Any] | None
    confidence_scores: dict[str, float] | None


class MetaAnalysisState(NeuroAgentState):
    """
    State for meta-analysis workflows across multiple datasets.
    """

    # Meta-analysis specific
    dataset_ids: list[str]
    inclusion_criteria: dict[str, Any]
    included_studies: list[dict[str, Any]]
    excluded_studies: list[dict[str, Any]]

    # Results
    pooled_results: dict[str, Any] | None
    heterogeneity_stats: dict[str, float] | None
    forest_plot_data: dict[str, Any] | None


class InteractiveSessionState(NeuroAgentState):
    """
    State for interactive research sessions with memory.
    """

    session_id: str
    session_history: list[dict[str, Any]]  # Previous queries and results
    context_window: list[BaseMessage]  # Recent messages for context
    accumulated_findings: dict[str, Any]  # Growing knowledge base
