"""High-level agent tools for the Knowledge Layer (K+D).

This module provides the neuroassistant.* tools for evidence-driven decision making:
- neuroassistant.gather_evidence: Gather evidence from multiple sources
- neuroassistant.build_knowledge_plan: Build a knowledge plan with intent classification
- neuroassistant.recommend_datasets: Recommend datasets based on evidence
- neuroassistant.explain: Generate evidence-based explanations

These tools integrate with the ChatOrchestrator and provide the high-level
knowledge capabilities for neuroimaging questions.
"""

from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel, Field

from brain_researcher.services.agent.knowledge.evidence_models import (
    DecisionType,
    EvidenceBundle,
    EvidenceSourceType,
)
from brain_researcher.services.tools.tool_base import (
    NeuroToolWrapper,
    ToolResult,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input schemas for tools
# ---------------------------------------------------------------------------


class GatherEvidenceInput(BaseModel):
    """Input schema for gather_evidence tool."""

    query: str = Field(
        description="The neuroimaging question or topic to gather evidence for"
    )
    sources: list[str] | None = Field(
        default=None,
        description="Optional list of sources to search. Valid values: 'pubmed', 'neurostore', 'dataset_catalog', 'tool_catalog', 'kg_graph', 'niclip'. If not specified, searches all sources.",
    )
    limit: int = Field(
        default=10,
        description="Maximum number of results per source",
    )
    include_niclip: bool = Field(
        default=True,
        description="Whether to include NiCLIP scoring for cognitive concepts",
    )


class BuildKnowledgePlanInput(BaseModel):
    """Input schema for build_knowledge_plan tool."""

    query: str = Field(description="The neuroimaging question to build a plan for")
    force_intent: str | None = Field(
        default=None,
        description="Optional forced intent: 'explanation', 'dataset_selection', or 'pipeline_recommendation'",
    )


class RecommendDatasetsInput(BaseModel):
    """Input schema for recommend_datasets tool."""

    query: str = Field(
        description="Description of the research question or analysis goal"
    )
    max_datasets: int = Field(
        default=5,
        description="Maximum number of datasets to recommend",
    )
    required_modalities: list[str] | None = Field(
        default=None,
        description="Optional filter for required modalities (e.g., 'fMRI', 'MEG')",
    )
    required_tasks: list[str] | None = Field(
        default=None,
        description="Optional filter for required cognitive tasks",
    )


class ExplainInput(BaseModel):
    """Input schema for explain tool."""

    query: str = Field(
        description="The neuroimaging concept, method, or question to explain"
    )
    max_citations: int = Field(
        default=5,
        description="Maximum number of citations to include in the explanation",
    )
    include_related_concepts: bool = Field(
        default=True,
        description="Whether to include related cognitive concepts from NiCLIP",
    )


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _source_str_to_enum(source_str: str) -> EvidenceSourceType | None:
    """Convert source string to EvidenceSourceType enum."""
    mapping = {
        "pubmed": EvidenceSourceType.PUBMED,
        "neurostore": EvidenceSourceType.NEUROSTORE,
        "dataset_catalog": EvidenceSourceType.DATASET_CATALOG,
        "tool_catalog": EvidenceSourceType.TOOL_CATALOG,
        "kg_graph": EvidenceSourceType.KG_GRAPH,
        "niclip": EvidenceSourceType.NICLIP,
    }
    return mapping.get(source_str.lower())


def _run_async(coro):
    """Run an async coroutine from a sync context safely.

    Behaviors:
      * If no event loop is running, execute with asyncio.run.
      * If a loop is already running (typical inside notebooks/agents), spawn a
        short-lived thread that creates its own loop to avoid deadlocking the
        active loop thread.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No event loop running - safe to run directly
        return asyncio.run(coro)

    import threading

    result_box = {"value": None, "error": None}

    def runner():
        try:
            result_box["value"] = asyncio.run(coro)
        except Exception as exc:  # pragma: no cover - passthrough
            result_box["error"] = exc

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join(timeout=30.0)

    if t.is_alive():
        raise TimeoutError("Async operation timed out after 30 seconds")
    if result_box["error"]:
        raise result_box["error"]
    return result_box["value"]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


class GatherEvidenceTool(NeuroToolWrapper):
    """Tool for gathering evidence from multiple knowledge sources.

    This tool searches across:
    - PubMed literature (via Neo4j with EDirect fallback)
    - NeuroStore meta-analysis studies
    - Dataset catalog (OpenNeuro, etc.)
    - Tool catalog (analysis tools)
    - Knowledge graph nodes (concepts, regions)
    - NiCLIP cognitive concept embeddings

    Returns an evidence bundle with aggregated results and confidence score.
    """

    def get_tool_name(self) -> str:
        return "neuroassistant.gather_evidence"

    def get_tool_description(self) -> str:
        return (
            "Gather evidence from multiple neuroimaging knowledge sources including "
            "PubMed literature, NeuroStore studies, dataset catalogs, tool registries, "
            "and NiCLIP brain embeddings. Returns an evidence bundle with relevance-scored "
            "items and an overall confidence score."
        )

    def get_args_schema(self) -> type[BaseModel]:
        return GatherEvidenceInput

    def _run(
        self,
        query: str,
        sources: list[str] | None = None,
        limit: int = 10,
        include_niclip: bool = True,
    ) -> ToolResult:
        """Gather evidence for the query."""
        from brain_researcher.services.agent.knowledge.evidence_connector import (
            EvidenceAggregator,
        )
        from brain_researcher.services.agent.knowledge.niclip_scorer import (
            NiCLIPScorer,
        )

        try:
            # Convert source strings to enums
            source_types = None
            if sources:
                source_types = [
                    _source_str_to_enum(s)
                    for s in sources
                    if _source_str_to_enum(s) is not None
                ]
                if not source_types:
                    source_types = None  # Fall back to all sources

            # Gather evidence
            aggregator = EvidenceAggregator()

            async def _gather():
                return await aggregator.gather_evidence(
                    query=query,
                    sources=source_types,
                    limit=limit,
                )

            bundle = _run_async(_gather())

            # Enrich with NiCLIP if requested
            if include_niclip:
                try:
                    scorer = NiCLIPScorer()

                    async def _enrich():
                        return await scorer.enrich_bundle(bundle, limit=5)

                    bundle = _run_async(_enrich())
                except Exception as e:
                    logger.warning("NiCLIP enrichment failed: %s", e)

            # Format result
            return ToolResult(
                status="success",
                data={
                    "query": bundle.query,
                    "total_items": len(bundle.items),
                    "literature_count": bundle.total_literature_count,
                    "dataset_count": bundle.total_dataset_count,
                    "tool_count": bundle.total_tool_count,
                    "niclip_score": bundle.aggregate_niclip_score,
                    "confidence": bundle.confidence,
                    "top_items": [
                        {
                            "source": item.source_type.value,
                            "id": item.source_id,
                            "label": item.label,
                            "score": item.relevance_score,
                            "url": item.url,
                        }
                        for item in bundle.get_top_items(10)
                    ],
                    "citations": bundle.format_citations(max_citations=10),
                },
                metadata={
                    "sources_searched": (
                        [s.value for s in source_types] if source_types else "all"
                    ),
                },
            )

        except Exception as e:
            return ToolResult(
                status="error",
                error=f"Evidence gathering failed: {e}",
            )


class BuildKnowledgePlanTool(NeuroToolWrapper):
    """Tool for building evidence-based knowledge plans.

    This tool:
    1. Gathers evidence from multiple sources
    2. Classifies user intent (explanation, dataset selection, pipeline recommendation)
    3. Generates a plan with appropriate recommendations and citations

    The plan includes reasoning, confidence scores, and formatted citations.
    """

    def get_tool_name(self) -> str:
        return "neuroassistant.build_knowledge_plan"

    def get_tool_description(self) -> str:
        return (
            "Build a comprehensive knowledge plan for a neuroimaging question. "
            "Gathers evidence, classifies intent (explanation vs dataset selection vs "
            "pipeline recommendation), and generates a plan with recommendations, "
            "reasoning, and citations."
        )

    def get_args_schema(self) -> type[BaseModel]:
        return BuildKnowledgePlanInput

    def _run(
        self,
        query: str,
        force_intent: str | None = None,
    ) -> ToolResult:
        """Build a knowledge plan for the query."""
        from brain_researcher.services.agent.knowledge.evidence_connector import (
            EvidenceAggregator,
        )
        from brain_researcher.services.agent.knowledge.knowledge_planner import (
            KnowledgePlanner,
        )
        from brain_researcher.services.agent.knowledge.niclip_scorer import (
            NiCLIPScorer,
        )

        try:
            # Parse forced intent
            forced_decision_type = None
            if force_intent:
                intent_map = {
                    "explanation": DecisionType.EXPLANATION,
                    "dataset_selection": DecisionType.DATASET_SELECTION,
                    "pipeline_recommendation": DecisionType.PIPELINE_RECOMMENDATION,
                }
                forced_decision_type = intent_map.get(force_intent.lower())

            # Gather evidence
            aggregator = EvidenceAggregator()

            async def _gather():
                return await aggregator.gather_evidence(query=query, limit=15)

            bundle = _run_async(_gather())

            # Enrich with NiCLIP
            try:
                scorer = NiCLIPScorer()

                async def _enrich():
                    return await scorer.enrich_bundle(bundle, limit=5)

                bundle = _run_async(_enrich())
            except Exception as e:
                logger.warning("NiCLIP enrichment failed: %s", e)

            # Build plan
            planner = KnowledgePlanner()

            async def _plan():
                return await planner.build_plan(
                    query=query,
                    bundle=bundle,
                    force_intent=forced_decision_type,
                )

            plan = _run_async(_plan())

            # Format result
            result_data = {
                "decision_type": plan.decision_type.value,
                "query": plan.query,
                "reasoning": plan.reasoning,
                "confidence": plan.confidence,
                "citations": plan.citations,
            }

            # Add type-specific fields
            if plan.decision_type == DecisionType.EXPLANATION:
                result_data["explanation"] = plan.explanation
                result_data["key_concepts"] = plan.metadata.get("key_concepts", [])
            elif plan.decision_type == DecisionType.DATASET_SELECTION:
                result_data["recommended_datasets"] = plan.recommended_datasets
                result_data["dataset_scores"] = plan.dataset_scores
            else:  # PIPELINE_RECOMMENDATION
                result_data["recommended_tools"] = plan.recommended_tools
                result_data["tool_sequence"] = plan.tool_sequence

            return ToolResult(
                status="success",
                data=result_data,
                metadata={
                    "evidence_items": len(bundle.items),
                    "evidence_confidence": bundle.confidence,
                },
            )

        except Exception as e:
            return ToolResult(
                status="error",
                error=f"Knowledge plan building failed: {e}",
            )


class RecommendDatasetsTool(NeuroToolWrapper):
    """Tool for recommending neuroimaging datasets.

    This tool gathers evidence specifically focused on datasets
    and provides ranked recommendations based on:
    - Task/paradigm relevance
    - Modality match
    - Subject count
    - Data quality indicators
    """

    def get_tool_name(self) -> str:
        return "neuroassistant.recommend_datasets"

    def get_tool_description(self) -> str:
        return (
            "Recommend neuroimaging datasets for a research question. "
            "Searches dataset catalogs (OpenNeuro, etc.) and ranks datasets "
            "by relevance to the query, considering tasks, modalities, and sample sizes."
        )

    def get_args_schema(self) -> type[BaseModel]:
        return RecommendDatasetsInput

    def _run(
        self,
        query: str,
        max_datasets: int = 5,
        required_modalities: list[str] | None = None,
        required_tasks: list[str] | None = None,
    ) -> ToolResult:
        """Recommend datasets for the query."""
        from brain_researcher.services.agent.knowledge.evidence_connector import (
            EvidenceAggregator,
        )
        from brain_researcher.services.agent.knowledge.knowledge_planner import (
            KnowledgePlanner,
        )

        try:
            # Gather dataset evidence only
            aggregator = EvidenceAggregator()

            async def _gather():
                return await aggregator.gather_evidence(
                    query=query,
                    sources=[EvidenceSourceType.DATASET_CATALOG],
                    limit=max_datasets * 2,  # Gather more to allow filtering
                )

            bundle = _run_async(_gather())

            # Filter by required modalities/tasks if specified
            dataset_items = bundle.get_items_by_source(
                EvidenceSourceType.DATASET_CATALOG
            )

            if required_modalities or required_tasks:
                filtered_items = []
                for item in dataset_items:
                    meta = item.metadata or {}

                    # Check modalities
                    if required_modalities:
                        item_modalities = [
                            m.lower() for m in meta.get("modalities", [])
                        ]
                        if not any(
                            rm.lower() in item_modalities for rm in required_modalities
                        ):
                            continue

                    # Check tasks
                    if required_tasks:
                        item_tasks = [t.lower() for t in meta.get("tasks", [])]
                        if not any(rt.lower() in item_tasks for rt in required_tasks):
                            continue

                    filtered_items.append(item)

                dataset_items = filtered_items

            # Sort by relevance and limit
            dataset_items.sort(key=lambda x: x.relevance_score, reverse=True)
            top_datasets = dataset_items[:max_datasets]

            # Use planner for reasoning if we have datasets
            reasoning = "Selected based on relevance to query"
            if top_datasets:
                # Create a mini-bundle for planning
                plan_bundle = EvidenceBundle(query=query)
                for item in top_datasets:
                    plan_bundle.add_item(item)
                plan_bundle.compute_confidence()

                try:
                    planner = KnowledgePlanner()

                    async def _plan():
                        return await planner._generate_dataset_plan(query, plan_bundle)

                    plan = _run_async(_plan())
                    reasoning = plan.reasoning or reasoning
                except Exception:
                    pass  # Use default reasoning

            # Format result
            return ToolResult(
                status="success",
                data={
                    "query": query,
                    "total_found": len(dataset_items),
                    "recommended_count": len(top_datasets),
                    "reasoning": reasoning,
                    "datasets": [
                        {
                            "dataset_id": item.source_id,
                            "title": item.label,
                            "relevance_score": item.relevance_score,
                            "url": item.url,
                            "tasks": (
                                item.metadata.get("tasks", []) if item.metadata else []
                            ),
                            "modalities": (
                                item.metadata.get("modalities", [])
                                if item.metadata
                                else []
                            ),
                            "n_subjects": (
                                item.metadata.get("n_subjects")
                                if item.metadata
                                else None
                            ),
                        }
                        for item in top_datasets
                    ],
                },
                metadata={
                    "filters_applied": {
                        "modalities": required_modalities,
                        "tasks": required_tasks,
                    },
                },
            )

        except Exception as e:
            return ToolResult(
                status="error",
                error=f"Dataset recommendation failed: {e}",
            )


class ExplainTool(NeuroToolWrapper):
    """Tool for generating evidence-based explanations.

    This tool generates explanations for neuroimaging concepts,
    methods, and questions by:
    1. Gathering relevant evidence
    2. Synthesizing information from literature and knowledge graph
    3. Providing citations with links
    """

    def get_tool_name(self) -> str:
        return "neuroassistant.explain"

    def get_tool_description(self) -> str:
        return (
            "Generate an evidence-based explanation for a neuroimaging concept, "
            "method, or question. Gathers supporting evidence from literature "
            "and knowledge sources, then synthesizes a clear explanation with citations."
        )

    def get_args_schema(self) -> type[BaseModel]:
        return ExplainInput

    def _run(
        self,
        query: str,
        max_citations: int = 5,
        include_related_concepts: bool = True,
    ) -> ToolResult:
        """Generate an explanation for the query."""
        from brain_researcher.services.agent.knowledge.evidence_connector import (
            EvidenceAggregator,
        )
        from brain_researcher.services.agent.knowledge.knowledge_planner import (
            KnowledgePlanner,
        )
        from brain_researcher.services.agent.knowledge.niclip_scorer import (
            NiCLIPScorer,
        )

        try:
            # Gather evidence (focus on literature and KG)
            aggregator = EvidenceAggregator()

            async def _gather():
                return await aggregator.gather_evidence(
                    query=query,
                    sources=[
                        EvidenceSourceType.PUBMED,
                        EvidenceSourceType.NEUROSTORE,
                        EvidenceSourceType.KG_GRAPH,
                    ],
                    limit=15,
                )

            bundle = _run_async(_gather())

            # Add NiCLIP concepts if requested
            related_concepts = []
            if include_related_concepts:
                try:
                    scorer = NiCLIPScorer()

                    async def _enrich():
                        return await scorer.enrich_bundle(bundle, limit=5)

                    bundle = _run_async(_enrich())

                    # Extract concept names
                    niclip_items = bundle.get_items_by_source(EvidenceSourceType.NICLIP)
                    related_concepts = [item.label for item in niclip_items[:5]]
                except Exception as e:
                    logger.warning("NiCLIP concepts failed: %s", e)

            # Generate explanation via planner
            planner = KnowledgePlanner(max_citations=max_citations)

            async def _plan():
                return await planner._generate_explanation_plan(query, bundle)

            plan = _run_async(_plan())

            return ToolResult(
                status="success",
                data={
                    "query": query,
                    "explanation": plan.explanation,
                    "confidence": plan.confidence,
                    "citations": plan.citations[:max_citations],
                    "related_concepts": related_concepts,
                    "key_concepts": plan.metadata.get("key_concepts", []),
                },
                metadata={
                    "evidence_items": len(bundle.items),
                    "literature_count": bundle.total_literature_count,
                },
            )

        except Exception as e:
            return ToolResult(
                status="error",
                error=f"Explanation generation failed: {e}",
            )


# ---------------------------------------------------------------------------
# Tool registry helpers
# ---------------------------------------------------------------------------


def get_knowledge_tools() -> list[NeuroToolWrapper]:
    """Get all knowledge layer tools.

    Returns:
        List of tool wrapper instances
    """
    return [
        GatherEvidenceTool(),
        BuildKnowledgePlanTool(),
        RecommendDatasetsTool(),
        ExplainTool(),
    ]


def register_knowledge_tools(registry):
    """Register knowledge layer tools with a ToolRegistry.

    Args:
        registry: The ToolRegistry instance to register with
    """
    for tool in get_knowledge_tools():
        registry.register(tool)


__all__ = [
    # Tools
    "BuildKnowledgePlanTool",
    "ExplainTool",
    "GatherEvidenceTool",
    "RecommendDatasetsTool",
    # Input schemas
    "BuildKnowledgePlanInput",
    "ExplainInput",
    "GatherEvidenceInput",
    "RecommendDatasetsInput",
    # Helpers
    "get_knowledge_tools",
    "register_knowledge_tools",
]
