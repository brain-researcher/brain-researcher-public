"""Agent tools for the Knowledge Layer (K+D).

This module provides 8 tools for evidence-driven decision making:

Low-level tools (direct source access):
- knowledge.query_kg: Query knowledge graph for concepts and brain regions
- knowledge.search_datasets: Search dataset catalog
- knowledge.search_tools: Search tool registry
- knowledge.search_literature: Search PubMed/literature
- knowledge.query_niclip: Query NiCLIP cognitive concepts

High-level tools (orchestrated access):
- knowledge.gather_evidence: Aggregate evidence from multiple sources
- knowledge.build_plan: Build knowledge plan with intent classification
- knowledge.explain: Generate evidence-based explanations

These tools integrate with the Knowledge Layer's evidence sources and planner.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field

from brain_researcher.services.knowledge.evidence.base import (
    EvidenceBundle,
    EvidenceQuery,
    EvidenceResult,
    EvidenceSourceType,
)
from brain_researcher.services.knowledge.planner import (
    DecisionType,
    EvidenceAggregator,
    KnowledgePlan,
    KnowledgePlanner,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------


class QueryKGInput(BaseModel):
    """Input for knowledge graph query."""

    query: str = Field(description="Search text for KG concepts and brain regions")
    node_types: Optional[List[str]] = Field(
        default=None,
        description="Filter by node types: 'Concept', 'BrainRegion', etc.",
    )
    limit: int = Field(default=10, description="Maximum results to return")


class SearchDatasetsInput(BaseModel):
    """Input for dataset search."""

    query: str = Field(description="Search text for datasets")
    modality: Optional[str] = Field(
        default=None,
        description="Filter by modality: 'fmri', 'eeg', 'meg', etc.",
    )
    min_subjects: Optional[int] = Field(
        default=None,
        description="Minimum number of subjects required",
    )
    limit: int = Field(default=10, description="Maximum results to return")


class SearchToolsInput(BaseModel):
    """Input for tool search."""

    query: str = Field(description="Search text for analysis tools")
    limit: int = Field(default=10, description="Maximum results to return")


class SearchLiteratureInput(BaseModel):
    """Input for literature search."""

    query: str = Field(description="Search text for literature")
    year_min: Optional[int] = Field(
        default=None,
        description="Minimum publication year",
    )
    year_max: Optional[int] = Field(
        default=None,
        description="Maximum publication year",
    )
    limit: int = Field(default=10, description="Maximum results to return")


class QueryNiCLIPInput(BaseModel):
    """Input for NiCLIP cognitive concept query."""

    query: str = Field(description="Search text for cognitive concepts")
    vocabulary_type: str = Field(
        default="cogatlas_task-names",
        description="Vocabulary to search: 'cogatlas_task-names' or 'cogatlasred_task-names'",
    )
    limit: int = Field(default=10, description="Maximum results to return")


class GatherEvidenceInput(BaseModel):
    """Input for evidence gathering."""

    query: str = Field(description="The query to gather evidence for")
    source_types: Optional[List[str]] = Field(
        default=None,
        description="Sources to query: 'kg', 'pubmed', 'datasets', 'tools', 'niclip'",
    )
    limit_per_source: int = Field(
        default=10,
        description="Maximum results per source",
    )


class BuildPlanInput(BaseModel):
    """Input for knowledge plan building."""

    query: str = Field(description="The neuroimaging question")
    force_intent: Optional[str] = Field(
        default=None,
        description="Force intent: 'explanation', 'dataset_selection', 'pipeline_recommendation', 'concept_lookup'",
    )
    use_llm: bool = Field(
        default=True,
        description="Use LLM for intent classification (vs. heuristics)",
    )


class ExplainInput(BaseModel):
    """Input for explanation generation."""

    query: str = Field(description="The concept/question to explain")
    max_citations: int = Field(
        default=10,
        description="Maximum citations to include",
    )
    include_niclip: bool = Field(
        default=True,
        description="Include NiCLIP cognitive concepts",
    )


# ---------------------------------------------------------------------------
# Tool result type
# ---------------------------------------------------------------------------


class ToolResult(BaseModel):
    """Standard result type for knowledge tools."""

    status: str = Field(description="'success' or 'error'")
    data: Optional[Dict[str, Any]] = Field(default=None)
    error: Optional[str] = Field(default=None)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _run_async(coro):
    """Run async coroutine from sync context."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import threading

    result_box = {"value": None, "error": None}

    def runner():
        try:
            result_box["value"] = asyncio.run(coro)
        except Exception as e:
            result_box["error"] = e

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join()

    if result_box["error"]:
        raise result_box["error"]
    return result_box["value"]


def _format_results(results: List[EvidenceResult]) -> List[Dict[str, Any]]:
    """Format evidence results for tool output."""
    return [
        {
            "id": r.id,
            "title": r.title,
            "source": r.source.value,
            "relevance_score": r.relevance_score,
            "confidence": r.confidence,
            "url": r.url,
            "summary": r.summary,
            "payload": r.payload,
        }
        for r in results
    ]


def _parse_source_types(source_strs: Optional[List[str]]) -> Optional[List[EvidenceSourceType]]:
    """Parse source type strings to enums."""
    if not source_strs:
        return None

    mapping = {
        "kg": EvidenceSourceType.KNOWLEDGE_GRAPH,
        "pubmed": EvidenceSourceType.LITERATURE,
        "literature": EvidenceSourceType.LITERATURE,
        "datasets": EvidenceSourceType.DATASET_CATALOG,
        "tools": EvidenceSourceType.TOOL_REGISTRY,
        "niclip": EvidenceSourceType.NICLIP,
        "neurostore": EvidenceSourceType.NEUROSTORE,
    }

    result = []
    for s in source_strs:
        if s.lower() in mapping:
            result.append(mapping[s.lower()])

    return result if result else None


def _parse_decision_type(intent_str: Optional[str]) -> Optional[DecisionType]:
    """Parse intent string to DecisionType."""
    if not intent_str:
        return None

    mapping = {
        "explanation": DecisionType.EXPLANATION,
        "dataset_selection": DecisionType.DATASET_SELECTION,
        "pipeline_recommendation": DecisionType.PIPELINE_RECOMMENDATION,
        "concept_lookup": DecisionType.CONCEPT_LOOKUP,
    }

    return mapping.get(intent_str.lower())


# ---------------------------------------------------------------------------
# Low-level tool implementations
# ---------------------------------------------------------------------------


def query_kg(
    query: str,
    node_types: Optional[List[str]] = None,
    limit: int = 10,
) -> ToolResult:
    """Query knowledge graph for concepts and brain regions.

    Args:
        query: Search text
        node_types: Optional filter for node types
        limit: Maximum results

    Returns:
        ToolResult with matching KG nodes
    """
    try:
        from brain_researcher.services.knowledge.evidence.kg_source import (
            KGEvidenceSource,
        )

        source = KGEvidenceSource()
        evidence_query = EvidenceQuery(
            text=query,
            node_types=node_types,
            limit=limit,
        )
        results = source.query_sync(evidence_query)

        return ToolResult(
            status="success",
            data={
                "query": query,
                "total": len(results),
                "concepts": _format_results(
                    [r for r in results if not r.payload.get("is_brain_region")]
                ),
                "brain_regions": _format_results(
                    [r for r in results if r.payload.get("is_brain_region")]
                ),
            },
            metadata={"node_types_filter": node_types},
        )

    except Exception as e:
        return ToolResult(status="error", error=f"KG query failed: {e}")


def search_datasets(
    query: str,
    modality: Optional[str] = None,
    min_subjects: Optional[int] = None,
    limit: int = 10,
) -> ToolResult:
    """Search dataset catalog.

    Args:
        query: Search text
        modality: Optional modality filter
        min_subjects: Optional minimum subjects filter
        limit: Maximum results

    Returns:
        ToolResult with matching datasets
    """
    try:
        from brain_researcher.services.knowledge.evidence.dataset_source import (
            DatasetEvidenceSource,
        )

        source = DatasetEvidenceSource()
        evidence_query = EvidenceQuery(
            text=query,
            modality=modality,
            min_subjects=min_subjects,
            limit=limit,
        )
        results = source.query_sync(evidence_query)

        return ToolResult(
            status="success",
            data={
                "query": query,
                "total": len(results),
                "datasets": _format_results(results),
            },
            metadata={
                "modality_filter": modality,
                "min_subjects_filter": min_subjects,
            },
        )

    except Exception as e:
        return ToolResult(status="error", error=f"Dataset search failed: {e}")


def search_tools(
    query: str,
    limit: int = 10,
) -> ToolResult:
    """Search tool registry.

    Args:
        query: Search text
        limit: Maximum results

    Returns:
        ToolResult with matching tools
    """
    try:
        from brain_researcher.services.knowledge.evidence.tool_source import (
            ToolEvidenceSource,
        )

        source = ToolEvidenceSource()
        evidence_query = EvidenceQuery(text=query, limit=limit)
        results = source.query_sync(evidence_query)

        return ToolResult(
            status="success",
            data={
                "query": query,
                "total": len(results),
                "tools": _format_results(results),
            },
        )

    except Exception as e:
        return ToolResult(status="error", error=f"Tool search failed: {e}")


def search_literature(
    query: str,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    limit: int = 10,
) -> ToolResult:
    """Search PubMed/literature.

    Args:
        query: Search text
        year_min: Optional minimum year filter
        year_max: Optional maximum year filter
        limit: Maximum results

    Returns:
        ToolResult with matching publications
    """
    try:
        from brain_researcher.services.knowledge.evidence.literature_source import (
            LiteratureEvidenceSource,
        )

        source = LiteratureEvidenceSource()
        evidence_query = EvidenceQuery(
            text=query,
            year_min=year_min,
            year_max=year_max,
            limit=limit,
        )

        async def _query():
            return await source.query(evidence_query)

        results = _run_async(_query())

        return ToolResult(
            status="success",
            data={
                "query": query,
                "total": len(results),
                "papers": _format_results(results),
            },
            metadata={
                "year_min_filter": year_min,
                "year_max_filter": year_max,
            },
        )

    except Exception as e:
        return ToolResult(status="error", error=f"Literature search failed: {e}")


def query_niclip(
    query: str,
    vocabulary_type: str = "cogatlas_task-names",
    limit: int = 10,
) -> ToolResult:
    """Query NiCLIP cognitive concepts.

    Args:
        query: Search text
        vocabulary_type: Which vocabulary to search
        limit: Maximum results

    Returns:
        ToolResult with matching cognitive concepts
    """
    try:
        from brain_researcher.services.knowledge.scoring.niclip_scorer import (
            NiCLIPEvidenceSource,
        )

        source = NiCLIPEvidenceSource(
            vocabulary_type=vocabulary_type,
            top_k=limit,
        )
        evidence_query = EvidenceQuery(text=query, limit=limit)
        results = source.query_sync(evidence_query)

        return ToolResult(
            status="success",
            data={
                "query": query,
                "vocabulary_type": vocabulary_type,
                "total": len(results),
                "concepts": _format_results(results),
            },
        )

    except Exception as e:
        return ToolResult(status="error", error=f"NiCLIP query failed: {e}")


# ---------------------------------------------------------------------------
# High-level tool implementations
# ---------------------------------------------------------------------------


def gather_evidence(
    query: str,
    source_types: Optional[List[str]] = None,
    limit_per_source: int = 10,
) -> ToolResult:
    """Gather evidence from multiple sources.

    Args:
        query: The query to gather evidence for
        source_types: Optional list of sources to query
        limit_per_source: Maximum results per source

    Returns:
        ToolResult with aggregated evidence bundle
    """
    try:
        aggregator = EvidenceAggregator(
            timeout=30.0,
            limit_per_source=limit_per_source,
        )

        source_type_enums = _parse_source_types(source_types)

        async def _gather():
            return await aggregator.gather(query, source_types=source_type_enums)

        bundle = _run_async(_gather())

        return ToolResult(
            status="success",
            data={
                "query": query,
                "total_count": bundle.total_count,
                "concepts_count": len(bundle.concepts),
                "brain_regions_count": len(bundle.brain_regions),
                "datasets_count": len(bundle.datasets),
                "tools_count": len(bundle.tools),
                "papers_count": len(bundle.papers),
                "concepts": _format_results(bundle.concepts[:5]),
                "brain_regions": _format_results(bundle.brain_regions[:3]),
                "datasets": _format_results(bundle.datasets[:5]),
                "tools": _format_results(bundle.tools[:5]),
                "papers": _format_results(bundle.papers[:5]),
            },
            metadata={
                "sources_queried": bundle.metadata.get("sources_queried", []),
                "query_time_ms": bundle.metadata.get("query_time_ms", 0),
                "errors": bundle.metadata.get("errors", {}),
            },
        )

    except Exception as e:
        return ToolResult(status="error", error=f"Evidence gathering failed: {e}")


def build_plan(
    query: str,
    force_intent: Optional[str] = None,
    use_llm: bool = True,
) -> ToolResult:
    """Build a knowledge plan with intent classification.

    Args:
        query: The neuroimaging question
        force_intent: Optional forced intent
        use_llm: Whether to use LLM for intent classification

    Returns:
        ToolResult with knowledge plan
    """
    try:
        planner = KnowledgePlanner()
        intent = _parse_decision_type(force_intent)

        async def _build():
            return await planner.build_plan(
                query=query,
                force_intent=intent,
                use_llm=use_llm,
            )

        plan = _run_async(_build())

        result_data = {
            "query": plan.query,
            "decision_type": plan.decision_type.value,
            "reasoning": plan.reasoning,
            "confidence": plan.confidence,
            "citations": plan.citations,
        }

        # Add type-specific fields
        if plan.decision_type == DecisionType.EXPLANATION:
            result_data["explanation"] = plan.explanation
            result_data["concepts"] = plan.concepts
        elif plan.decision_type == DecisionType.DATASET_SELECTION:
            result_data["recommended_datasets"] = plan.recommended_datasets
            result_data["dataset_scores"] = plan.dataset_scores
        elif plan.decision_type == DecisionType.PIPELINE_RECOMMENDATION:
            result_data["recommended_tools"] = plan.recommended_tools
            result_data["tool_sequence"] = plan.tool_sequence
        elif plan.decision_type == DecisionType.CONCEPT_LOOKUP:
            result_data["concepts"] = plan.concepts

        return ToolResult(
            status="success",
            data=result_data,
            metadata=plan.metadata,
        )

    except Exception as e:
        return ToolResult(status="error", error=f"Plan building failed: {e}")


def explain(
    query: str,
    max_citations: int = 10,
    include_niclip: bool = True,
) -> ToolResult:
    """Generate an evidence-based explanation.

    Args:
        query: The concept/question to explain
        max_citations: Maximum citations to include
        include_niclip: Whether to include NiCLIP concepts

    Returns:
        ToolResult with explanation and citations
    """
    try:
        aggregator = EvidenceAggregator(timeout=30.0)
        planner = KnowledgePlanner(max_citations=max_citations)

        # Sources for explanations
        source_types = [
            EvidenceSourceType.KNOWLEDGE_GRAPH,
            EvidenceSourceType.LITERATURE,
        ]
        if include_niclip:
            source_types.append(EvidenceSourceType.NICLIP)

        async def _explain():
            bundle = await aggregator.gather(query, source_types=source_types)
            return await planner._generate_explanation_plan(query, bundle)

        plan = _run_async(_explain())

        # Get NiCLIP concepts if included
        niclip_concepts = []
        if include_niclip and plan.evidence_bundle:
            niclip_results = [
                r
                for r in plan.evidence_bundle.concepts
                if r.source == EvidenceSourceType.NICLIP
            ]
            niclip_concepts = [r.title for r in niclip_results[:5]]

        return ToolResult(
            status="success",
            data={
                "query": query,
                "explanation": plan.explanation,
                "confidence": plan.confidence,
                "citations": plan.citations,
                "concepts": plan.concepts,
                "niclip_concepts": niclip_concepts,
            },
            metadata={
                "evidence_count": plan.evidence_bundle.total_count
                if plan.evidence_bundle
                else 0,
            },
        )

    except Exception as e:
        return ToolResult(status="error", error=f"Explanation failed: {e}")


# ---------------------------------------------------------------------------
# Tool metadata for registration
# ---------------------------------------------------------------------------


TOOL_DEFINITIONS = [
    # Low-level tools
    {
        "name": "knowledge.query_kg",
        "description": "Query knowledge graph for concepts and brain regions",
        "function": query_kg,
        "input_schema": QueryKGInput,
        "tags": ["knowledge", "kg", "concepts"],
    },
    {
        "name": "knowledge.search_datasets",
        "description": "Search dataset catalog for neuroimaging datasets",
        "function": search_datasets,
        "input_schema": SearchDatasetsInput,
        "tags": ["knowledge", "datasets"],
    },
    {
        "name": "knowledge.search_tools",
        "description": "Search tool registry for analysis tools",
        "function": search_tools,
        "input_schema": SearchToolsInput,
        "tags": ["knowledge", "tools"],
    },
    {
        "name": "knowledge.search_literature",
        "description": "Search PubMed/literature for publications",
        "function": search_literature,
        "input_schema": SearchLiteratureInput,
        "tags": ["knowledge", "literature", "pubmed"],
    },
    {
        "name": "knowledge.query_niclip",
        "description": "Query NiCLIP for cognitive concepts",
        "function": query_niclip,
        "input_schema": QueryNiCLIPInput,
        "tags": ["knowledge", "niclip", "concepts"],
    },
    # High-level tools
    {
        "name": "knowledge.gather_evidence",
        "description": "Gather evidence from multiple knowledge sources",
        "function": gather_evidence,
        "input_schema": GatherEvidenceInput,
        "tags": ["knowledge", "evidence", "aggregation"],
    },
    {
        "name": "knowledge.build_plan",
        "description": "Build a knowledge plan with intent classification",
        "function": build_plan,
        "input_schema": BuildPlanInput,
        "tags": ["knowledge", "planning"],
    },
    {
        "name": "knowledge.explain",
        "description": "Generate an evidence-based explanation",
        "function": explain,
        "input_schema": ExplainInput,
        "tags": ["knowledge", "explanation"],
    },
]


def get_tool_definitions() -> List[Dict[str, Any]]:
    """Get all tool definitions for registration.

    Returns:
        List of tool definition dictionaries
    """
    return TOOL_DEFINITIONS.copy()


def get_tool_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Get a tool definition by name.

    Args:
        name: Tool name (e.g., 'knowledge.query_kg')

    Returns:
        Tool definition dict or None
    """
    for tool in TOOL_DEFINITIONS:
        if tool["name"] == name:
            return tool
    return None


__all__ = [
    # Low-level tools
    "query_kg",
    "search_datasets",
    "search_tools",
    "search_literature",
    "query_niclip",
    # High-level tools
    "gather_evidence",
    "build_plan",
    "explain",
    # Input schemas
    "QueryKGInput",
    "SearchDatasetsInput",
    "SearchToolsInput",
    "SearchLiteratureInput",
    "QueryNiCLIPInput",
    "GatherEvidenceInput",
    "BuildPlanInput",
    "ExplainInput",
    # Result type
    "ToolResult",
    # Registration helpers
    "TOOL_DEFINITIONS",
    "get_tool_definitions",
    "get_tool_by_name",
]
