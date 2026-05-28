"""Knowledge Planner for evidence-driven decision making (K+C).

This module provides:
- EvidenceAggregator: Gathers evidence from multiple sources in parallel
- KnowledgePlanner: LLM-based planning with intent classification
- KnowledgePlan: Result type with recommendations and citations

The planner uses gathered evidence to make informed decisions about
how to respond to neuroimaging questions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Type

from brain_researcher.services.knowledge.evidence.base import (
    EvidenceBundle,
    EvidenceQuery,
    EvidenceResult,
    EvidenceSource,
    EvidenceSourceType,
)

logger = logging.getLogger(__name__)


class DecisionType(str, Enum):
    """Types of decisions the planner can make."""

    EXPLANATION = "explanation"
    DATASET_SELECTION = "dataset_selection"
    PIPELINE_RECOMMENDATION = "pipeline_recommendation"
    CONCEPT_LOOKUP = "concept_lookup"
    UNKNOWN = "unknown"


@dataclass
class KnowledgePlan:
    """Result of knowledge planning with recommendations and evidence."""

    decision_type: DecisionType
    query: str
    reasoning: str
    confidence: float

    # Decision-specific fields
    explanation: Optional[str] = None
    recommended_datasets: List[str] = field(default_factory=list)
    dataset_scores: Dict[str, float] = field(default_factory=dict)
    recommended_tools: List[str] = field(default_factory=list)
    tool_sequence: List[str] = field(default_factory=list)
    concepts: List[str] = field(default_factory=list)

    # Evidence and citations
    evidence_bundle: Optional[EvidenceBundle] = None
    citations: List[Dict[str, str]] = field(default_factory=list)

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "decision_type": self.decision_type.value,
            "query": self.query,
            "reasoning": self.reasoning,
            "confidence": self.confidence,
            "explanation": self.explanation,
            "recommended_datasets": self.recommended_datasets,
            "dataset_scores": self.dataset_scores,
            "recommended_tools": self.recommended_tools,
            "tool_sequence": self.tool_sequence,
            "concepts": self.concepts,
            "citations": self.citations,
            "metadata": self.metadata,
        }


class EvidenceAggregator:
    """Aggregates evidence from multiple sources in parallel.

    This class provides a unified interface for gathering evidence from:
    - Knowledge Graph (BR-KG)
    - Literature (PubMed)
    - Dataset Catalog
    - Tool Registry
    - NiCLIP (brain-text embeddings)
    """

    def __init__(
        self,
        sources: Optional[List[EvidenceSource]] = None,
        timeout: float = 30.0,
        limit_per_source: int = 10,
    ):
        """Initialize the aggregator.

        Args:
            sources: List of evidence sources to use (lazy-loaded)
            timeout: Timeout for all queries combined
            limit_per_source: Maximum results per source
        """
        self._sources = sources or []
        self._timeout = timeout
        self._limit_per_source = limit_per_source

    def _get_default_sources(self) -> List[EvidenceSource]:
        """Lazy-load default evidence sources."""
        sources = []

        # KG Source
        try:
            from brain_researcher.services.knowledge.evidence.kg_source import (
                KGEvidenceSource,
            )

            sources.append(KGEvidenceSource())
        except ImportError:
            logger.debug("KG source not available")

        # Dataset Source
        try:
            from brain_researcher.services.knowledge.evidence.dataset_source import (
                DatasetEvidenceSource,
            )

            sources.append(DatasetEvidenceSource())
        except ImportError:
            logger.debug("Dataset source not available")

        # Tool Source
        try:
            from brain_researcher.services.knowledge.evidence.tool_source import (
                ToolEvidenceSource,
            )

            sources.append(ToolEvidenceSource())
        except ImportError:
            logger.debug("Tool source not available")

        # Literature Source
        try:
            from brain_researcher.services.knowledge.evidence.literature_source import (
                LiteratureEvidenceSource,
            )

            sources.append(LiteratureEvidenceSource())
        except ImportError:
            logger.debug("Literature source not available")

        # NiCLIP Source
        try:
            from brain_researcher.services.knowledge.scoring.niclip_scorer import (
                NiCLIPEvidenceSource,
            )

            sources.append(NiCLIPEvidenceSource())
        except ImportError:
            logger.debug("NiCLIP source not available")

        return sources

    async def gather(
        self,
        query: str,
        source_types: Optional[List[EvidenceSourceType]] = None,
        limit: Optional[int] = None,
    ) -> EvidenceBundle:
        """Gather evidence from all sources in parallel.

        Args:
            query: The search query
            source_types: Specific source types to query (None = all)
            limit: Override for limit per source

        Returns:
            EvidenceBundle with aggregated results
        """
        start_time = time.time()

        # Get sources
        sources = self._sources or self._get_default_sources()

        # Filter by type if specified
        if source_types:
            sources = [s for s in sources if s.source_type in source_types]

        if not sources:
            logger.warning("No evidence sources available")
            return EvidenceBundle(
                metadata={"error": "No sources available", "query_time_ms": 0}
            )

        # Create query
        evidence_query = EvidenceQuery(
            text=query,
            limit=limit or self._limit_per_source,
        )

        async def _query_source(
            source: EvidenceSource,
        ) -> tuple[EvidenceSourceType, List[EvidenceResult], Optional[str]]:
            """Query a single source with error handling."""
            try:
                # Check health first
                if not await source.health_check():
                    return source.source_type, [], "Source unavailable"

                results = await source.query(evidence_query)
                return source.source_type, results, None
            except Exception as e:
                logger.warning(f"[{source.source_type.value}] Error: {e}")
                return source.source_type, [], str(e)

        # Query all sources in parallel with timeout
        tasks = [_query_source(s) for s in sources]

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(f"Evidence gathering timed out after {self._timeout}s")
            results = []

        # Aggregate into bundle
        bundle = EvidenceBundle(
            query_interpretation={"original_query": query},
            metadata={
                "sources_queried": [],
                "errors": {},
            },
        )

        seen_ids: set[str] = set()

        for result in results:
            if isinstance(result, Exception):
                logger.warning(f"Task failed: {result}")
                continue

            source_type, items, error = result
            bundle.metadata["sources_queried"].append(source_type.value)

            if error:
                bundle.metadata["errors"][source_type.value] = error
            else:
                for item in items:
                    # Deduplicate by ID
                    if item.id not in seen_ids:
                        seen_ids.add(item.id)
                        self._add_to_bundle(bundle, item)

        bundle.metadata["query_time_ms"] = (time.time() - start_time) * 1000

        logger.info(
            f"Evidence gathered: {bundle.total_count} items from "
            f"{len(bundle.metadata['sources_queried'])} sources in "
            f"{bundle.metadata['query_time_ms']:.1f}ms"
        )

        return bundle

    def _add_to_bundle(self, bundle: EvidenceBundle, item: EvidenceResult) -> None:
        """Add an evidence result to the appropriate bundle category."""
        if item.source == EvidenceSourceType.KNOWLEDGE_GRAPH:
            # Check if it's a brain region
            if item.payload.get("is_brain_region") or item.payload.get("node_type") == "BrainRegion":
                bundle.brain_regions.append(item)
            else:
                bundle.concepts.append(item)
        elif item.source == EvidenceSourceType.DATASET_CATALOG:
            bundle.datasets.append(item)
        elif item.source == EvidenceSourceType.TOOL_REGISTRY:
            bundle.tools.append(item)
        elif item.source == EvidenceSourceType.LITERATURE:
            bundle.papers.append(item)
        elif item.source == EvidenceSourceType.NICLIP:
            bundle.concepts.append(item)
        elif item.source == EvidenceSourceType.NEUROSTORE:
            bundle.papers.append(item)
        else:
            # Default to concepts
            bundle.concepts.append(item)


# Intent classification prompts
INTENT_CLASSIFICATION_PROMPT = """Analyze this neuroimaging question and classify the user's intent.

Question: {query}

Evidence Context (top {evidence_count} items):
{evidence_summary}

Classify the intent into ONE of these categories:
1. EXPLANATION - User wants to understand a concept, method, or brain region
2. DATASET_SELECTION - User wants to find datasets for analysis
3. PIPELINE_RECOMMENDATION - User wants tool/analysis recommendations
4. CONCEPT_LOOKUP - User wants to find specific concepts or brain regions

Respond with a JSON object:
{{
  "intent": "EXPLANATION" | "DATASET_SELECTION" | "PIPELINE_RECOMMENDATION" | "CONCEPT_LOOKUP",
  "reasoning": "Brief explanation of why this classification",
  "confidence": 0.0-1.0
}}

Only output the JSON, no other text."""


EXPLANATION_PROMPT = """Generate a concise, evidence-based explanation for this neuroimaging question.

Question: {query}

Evidence:
{evidence_summary}

Citations:
{citations}

Instructions:
- Provide a clear, accurate explanation drawing from the evidence
- Reference citations using [1], [2], etc. format
- Keep the explanation focused and technical but accessible
- If evidence is limited, acknowledge uncertainty

Respond with JSON:
{{
  "explanation": "Your explanation text with [1][2] citations...",
  "key_concepts": ["concept1", "concept2"],
  "confidence": 0.0-1.0
}}

Only output the JSON, no other text."""


DATASET_SELECTION_PROMPT = """Recommend datasets based on the evidence gathered.

Question: {query}

Available Datasets:
{dataset_evidence}

Instructions:
- Select the most relevant datasets for this research question
- Score each dataset on relevance (0.0-1.0)
- Consider task types, modalities, and subject counts
- Provide reasoning for selections

Respond with JSON:
{{
  "recommended_datasets": ["ds001", "ds002", ...],
  "dataset_scores": {{"ds001": 0.9, "ds002": 0.8}},
  "reasoning": "Why these datasets are recommended",
  "confidence": 0.0-1.0
}}

Only output the JSON, no other text."""


PIPELINE_RECOMMENDATION_PROMPT = """Recommend analysis tools and pipeline for this neuroimaging task.

Question: {query}

Available Tools:
{tool_evidence}

Evidence Context:
{evidence_summary}

Instructions:
- Recommend appropriate tools for the analysis
- Provide a logical sequence of tools/steps
- Consider the user's specific needs
- Reference relevant literature if available

Respond with JSON:
{{
  "recommended_tools": ["fmriprep", "nilearn", ...],
  "tool_sequence": ["step1_tool", "step2_tool", ...],
  "reasoning": "Explanation of the recommended pipeline",
  "confidence": 0.0-1.0
}}

Only output the JSON, no other text."""


class KnowledgePlanner:
    """LLM-based planner for knowledge-driven decisions.

    The planner:
    1. Gathers evidence from multiple sources
    2. Classifies user intent
    3. Generates appropriate plans based on intent
    4. Includes citations and confidence scores
    """

    def __init__(
        self,
        aggregator: Optional[EvidenceAggregator] = None,
        model_hint: Optional[str] = None,
        max_citations: int = 10,
    ):
        """Initialize the knowledge planner.

        Args:
            aggregator: Evidence aggregator (created if not provided)
            model_hint: Optional model to use for LLM calls
            max_citations: Maximum citations to include in plans
        """
        self._aggregator = aggregator or EvidenceAggregator()
        self._model_hint = model_hint
        self._max_citations = max_citations
        self._router = None

    def _get_router(self):
        """Lazy-load the LLM router."""
        if self._router is None:
            try:
                from brain_researcher.services.agent.router import LLMRouter

                self._router = LLMRouter()
            except ImportError:
                logger.warning("LLMRouter not available")
                self._router = None
        return self._router

    def _invoke_llm(self, prompt: str) -> str:
        """Invoke LLM with prompt.

        Args:
            prompt: The prompt to send

        Returns:
            LLM response text
        """
        router = self._get_router()
        if router is None:
            raise RuntimeError("LLM router not available")

        result = router.route_chat(
            prompt=prompt,
            model_hint=self._model_hint,
            task_type="classification",
            strict_json=True,
        )
        return result.text

    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        """Parse JSON from LLM response, handling markdown code blocks."""
        text = text.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)

        try:
            return json.loads(text.strip())
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse LLM JSON response: %s", e)
            return {}

    def _format_evidence_summary(
        self, bundle: EvidenceBundle, max_items: int = 10
    ) -> str:
        """Format evidence bundle for prompt inclusion."""
        lines = []

        # Combine all evidence
        all_items = (
            bundle.concepts[:5]
            + bundle.brain_regions[:3]
            + bundle.datasets[:3]
            + bundle.tools[:3]
            + bundle.papers[:3]
        )[:max_items]

        for item in all_items:
            source_label = item.source.value.upper()
            lines.append(
                f"- [{source_label}] {item.title} (score: {item.relevance_score:.2f})"
            )
            if item.summary:
                lines.append(f"    {item.summary[:100]}...")

        return "\n".join(lines) if lines else "No evidence available."

    def _format_citations(self, bundle: EvidenceBundle) -> str:
        """Format citations for prompt inclusion."""
        citations = []

        # Prioritize papers for citations
        items = bundle.papers + bundle.concepts + bundle.datasets
        for i, item in enumerate(items[: self._max_citations], 1):
            url_part = f" - {item.url}" if item.url else ""
            citations.append(f"[{i}] {item.title}{url_part}")

        return "\n".join(citations) if citations else "No citations available."

    def _format_dataset_evidence(self, bundle: EvidenceBundle) -> str:
        """Format dataset-specific evidence."""
        if not bundle.datasets:
            return "No datasets found in evidence."

        lines = []
        for item in bundle.datasets[:10]:
            payload = item.payload or {}
            tasks = payload.get("tasks", [])
            modalities = payload.get("modalities", [])
            n_subjects = payload.get("subjects_count", "?")

            lines.append(f"- {item.id}: {item.title}")
            lines.append(f"    Tasks: {', '.join(tasks) if tasks else 'N/A'}")
            lines.append(f"    Modalities: {', '.join(modalities) if modalities else 'N/A'}")
            lines.append(f"    Subjects: {n_subjects}")

        return "\n".join(lines)

    def _format_tool_evidence(self, bundle: EvidenceBundle) -> str:
        """Format tool-specific evidence."""
        if not bundle.tools:
            return "No tools found in evidence."

        lines = []
        for item in bundle.tools[:10]:
            desc = item.summary or item.title
            lines.append(f"- {item.id}: {desc[:100]}...")

        return "\n".join(lines)

    def _build_citations(self, bundle: EvidenceBundle) -> List[Dict[str, str]]:
        """Build citation list from bundle."""
        citations = []
        items = bundle.papers + bundle.concepts + bundle.datasets

        for i, item in enumerate(items[: self._max_citations], 1):
            citations.append({
                "ref": f"[{i}]",
                "id": item.id,
                "title": item.title,
                "source": item.source.value,
                "url": item.url or "",
            })

        return citations

    async def classify_intent(
        self, query: str, bundle: EvidenceBundle
    ) -> DecisionType:
        """Classify user intent based on query and evidence.

        Args:
            query: The user's query
            bundle: Gathered evidence

        Returns:
            The classified DecisionType
        """
        prompt = INTENT_CLASSIFICATION_PROMPT.format(
            query=query,
            evidence_count=bundle.total_count,
            evidence_summary=self._format_evidence_summary(bundle, max_items=5),
        )

        try:
            response = self._invoke_llm(prompt)
            result = self._parse_json_response(response)

            intent_str = result.get("intent", "EXPLANATION").upper()

            if "DATASET" in intent_str:
                return DecisionType.DATASET_SELECTION
            elif "PIPELINE" in intent_str or "TOOL" in intent_str:
                return DecisionType.PIPELINE_RECOMMENDATION
            elif "CONCEPT" in intent_str or "LOOKUP" in intent_str:
                return DecisionType.CONCEPT_LOOKUP
            else:
                return DecisionType.EXPLANATION

        except Exception as e:
            logger.warning("Intent classification failed: %s; defaulting to EXPLANATION", e)
            return DecisionType.EXPLANATION

    def _classify_intent_heuristic(self, query: str) -> DecisionType:
        """Fallback heuristic intent classification."""
        query_lower = query.lower()

        dataset_keywords = ["dataset", "data", "subjects", "openneuro", "find data"]
        if any(kw in query_lower for kw in dataset_keywords):
            return DecisionType.DATASET_SELECTION

        tool_keywords = ["tool", "pipeline", "analysis", "how to", "process", "analyze"]
        if any(kw in query_lower for kw in tool_keywords):
            return DecisionType.PIPELINE_RECOMMENDATION

        concept_keywords = ["what is", "define", "concept", "region", "area"]
        if any(kw in query_lower for kw in concept_keywords):
            return DecisionType.CONCEPT_LOOKUP

        return DecisionType.EXPLANATION

    async def _generate_explanation_plan(
        self, query: str, bundle: EvidenceBundle
    ) -> KnowledgePlan:
        """Generate an explanation plan."""
        prompt = EXPLANATION_PROMPT.format(
            query=query,
            evidence_summary=self._format_evidence_summary(bundle),
            citations=self._format_citations(bundle),
        )

        try:
            response = self._invoke_llm(prompt)
            result = self._parse_json_response(response)

            return KnowledgePlan(
                decision_type=DecisionType.EXPLANATION,
                query=query,
                reasoning="Generated explanation based on gathered evidence",
                explanation=result.get("explanation", "Unable to generate explanation."),
                citations=self._build_citations(bundle),
                confidence=result.get("confidence", 0.7),
                evidence_bundle=bundle,
                concepts=result.get("key_concepts", []),
            )

        except Exception as e:
            logger.warning("Explanation generation failed: %s", e)
            return KnowledgePlan(
                decision_type=DecisionType.EXPLANATION,
                query=query,
                reasoning=f"Fallback plan due to error: {e}",
                explanation="Unable to generate explanation at this time.",
                citations=self._build_citations(bundle),
                confidence=0.3,
                evidence_bundle=bundle,
            )

    async def _generate_dataset_plan(
        self, query: str, bundle: EvidenceBundle
    ) -> KnowledgePlan:
        """Generate a dataset selection plan."""
        prompt = DATASET_SELECTION_PROMPT.format(
            query=query,
            dataset_evidence=self._format_dataset_evidence(bundle),
        )

        try:
            response = self._invoke_llm(prompt)
            result = self._parse_json_response(response)

            return KnowledgePlan(
                decision_type=DecisionType.DATASET_SELECTION,
                query=query,
                reasoning=result.get("reasoning", "Selected based on evidence"),
                recommended_datasets=result.get("recommended_datasets", []),
                dataset_scores=result.get("dataset_scores", {}),
                citations=self._build_citations(bundle),
                confidence=result.get("confidence", 0.7),
                evidence_bundle=bundle,
            )

        except Exception as e:
            logger.warning("Dataset selection failed: %s", e)
            # Fallback: return top datasets from evidence
            fallback_datasets = [item.id for item in bundle.datasets[:5]]

            return KnowledgePlan(
                decision_type=DecisionType.DATASET_SELECTION,
                query=query,
                reasoning=f"Fallback selection due to error: {e}",
                recommended_datasets=fallback_datasets,
                dataset_scores={ds: 0.5 for ds in fallback_datasets},
                citations=self._build_citations(bundle),
                confidence=0.4,
                evidence_bundle=bundle,
            )

    async def _generate_pipeline_plan(
        self, query: str, bundle: EvidenceBundle
    ) -> KnowledgePlan:
        """Generate a pipeline recommendation plan."""
        prompt = PIPELINE_RECOMMENDATION_PROMPT.format(
            query=query,
            tool_evidence=self._format_tool_evidence(bundle),
            evidence_summary=self._format_evidence_summary(bundle, max_items=5),
        )

        try:
            response = self._invoke_llm(prompt)
            result = self._parse_json_response(response)

            return KnowledgePlan(
                decision_type=DecisionType.PIPELINE_RECOMMENDATION,
                query=query,
                reasoning=result.get("reasoning", "Recommended based on evidence"),
                recommended_tools=result.get("recommended_tools", []),
                tool_sequence=result.get("tool_sequence", []),
                citations=self._build_citations(bundle),
                confidence=result.get("confidence", 0.7),
                evidence_bundle=bundle,
            )

        except Exception as e:
            logger.warning("Pipeline recommendation failed: %s", e)
            # Fallback: return top tools from evidence
            fallback_tools = [item.id for item in bundle.tools[:5]]

            return KnowledgePlan(
                decision_type=DecisionType.PIPELINE_RECOMMENDATION,
                query=query,
                reasoning=f"Fallback recommendation due to error: {e}",
                recommended_tools=fallback_tools,
                tool_sequence=fallback_tools,
                citations=self._build_citations(bundle),
                confidence=0.4,
                evidence_bundle=bundle,
            )

    async def _generate_concept_plan(
        self, query: str, bundle: EvidenceBundle
    ) -> KnowledgePlan:
        """Generate a concept lookup plan."""
        # For concept lookup, we primarily return the found concepts
        concepts = [item.title for item in bundle.concepts[:10]]
        regions = [item.title for item in bundle.brain_regions[:5]]

        return KnowledgePlan(
            decision_type=DecisionType.CONCEPT_LOOKUP,
            query=query,
            reasoning="Found matching concepts and brain regions",
            concepts=concepts + regions,
            citations=self._build_citations(bundle),
            confidence=0.8 if concepts or regions else 0.3,
            evidence_bundle=bundle,
        )

    async def build_plan(
        self,
        query: str,
        bundle: Optional[EvidenceBundle] = None,
        force_intent: Optional[DecisionType] = None,
        use_llm: bool = True,
    ) -> KnowledgePlan:
        """Build a knowledge plan based on query and evidence.

        This is the main entry point for planning.

        Args:
            query: The user's query
            bundle: Pre-gathered evidence (gathered if not provided)
            force_intent: Optional override for intent classification
            use_llm: Whether to use LLM for planning (vs. heuristics)

        Returns:
            KnowledgePlan with recommendations
        """
        # Gather evidence if not provided
        if bundle is None:
            bundle = await self._aggregator.gather(query)

        # Classify intent
        if force_intent:
            intent = force_intent
        elif use_llm and self._get_router():
            intent = await self.classify_intent(query, bundle)
        else:
            intent = self._classify_intent_heuristic(query)

        # Generate appropriate plan
        if intent == DecisionType.EXPLANATION:
            return await self._generate_explanation_plan(query, bundle)
        elif intent == DecisionType.DATASET_SELECTION:
            return await self._generate_dataset_plan(query, bundle)
        elif intent == DecisionType.CONCEPT_LOOKUP:
            return await self._generate_concept_plan(query, bundle)
        else:  # PIPELINE_RECOMMENDATION
            return await self._generate_pipeline_plan(query, bundle)

    async def quick_gather(
        self,
        query: str,
        source_types: Optional[List[EvidenceSourceType]] = None,
    ) -> EvidenceBundle:
        """Quickly gather evidence without full planning.

        Convenience method for just getting evidence.

        Args:
            query: The search query
            source_types: Specific sources to query

        Returns:
            EvidenceBundle with results
        """
        return await self._aggregator.gather(query, source_types=source_types)


# Factory functions
def create_planner(
    model_hint: Optional[str] = None,
    max_citations: int = 10,
    timeout: float = 30.0,
) -> KnowledgePlanner:
    """Create a knowledge planner with sensible defaults.

    Args:
        model_hint: Optional model override for LLM
        max_citations: Maximum citations to include
        timeout: Timeout for evidence gathering

    Returns:
        Configured KnowledgePlanner
    """
    aggregator = EvidenceAggregator(timeout=timeout)
    return KnowledgePlanner(
        aggregator=aggregator,
        model_hint=model_hint,
        max_citations=max_citations,
    )


def create_aggregator(
    timeout: float = 30.0,
    limit_per_source: int = 10,
) -> EvidenceAggregator:
    """Create an evidence aggregator.

    Args:
        timeout: Timeout for all queries
        limit_per_source: Maximum results per source

    Returns:
        Configured EvidenceAggregator
    """
    return EvidenceAggregator(
        timeout=timeout,
        limit_per_source=limit_per_source,
    )


__all__ = [
    "DecisionType",
    "EvidenceAggregator",
    "KnowledgePlan",
    "KnowledgePlanner",
    "create_aggregator",
    "create_planner",
]
