"""Knowledge Planner for evidence-driven decision making.

This module implements the K+C component:
- Intent classification (explanation, dataset_selection, pipeline_recommendation)
- Evidence-based decision making
- Generation of KnowledgePlan with recommendations and citations

The planner uses LLM-based analysis of gathered evidence to determine
the best response strategy for neuroimaging questions.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from brain_researcher.services.agent.knowledge.evidence_models import (
    DecisionType,
    EvidenceBundle,
    EvidenceItem,
    EvidenceSourceType,
    KnowledgePlan,
)

logger = logging.getLogger(__name__)


# Intent classification prompt template
INTENT_CLASSIFICATION_PROMPT = """Analyze this neuroimaging question and classify the user's intent.

Question: {query}

Evidence Context (top {evidence_count} items):
{evidence_summary}

Classify the intent into ONE of these categories:
1. EXPLANATION - User wants to understand a concept, method, or brain region
2. DATASET_SELECTION - User wants to find datasets for analysis
3. PIPELINE_RECOMMENDATION - User wants tool/analysis recommendations

Respond with a JSON object:
{{
  "intent": "EXPLANATION" | "DATASET_SELECTION" | "PIPELINE_RECOMMENDATION",
  "reasoning": "Brief explanation of why this classification",
  "confidence": 0.0-1.0
}}

Only output the JSON, no other text."""


EXPLANATION_PROMPT = """Generate a concise, evidence-based explanation for this neuroimaging question.

Question: {query}

Evidence Bundle:
{evidence_summary}

Top Citations:
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

    The planner analyzes gathered evidence and uses LLM reasoning to:
    1. Classify user intent
    2. Generate appropriate plans based on intent
    3. Include citations and confidence scores
    """

    def __init__(
        self,
        model_hint: Optional[str] = None,
        max_citations: int = 10,
    ):
        """Initialize the knowledge planner.

        Args:
            model_hint: Optional model to use for LLM calls
            max_citations: Maximum citations to include in plans
        """
        self._model_hint = model_hint
        self._max_citations = max_citations
        self._router = None

    def _get_router(self):
        """Lazy-load the LLM router (shared singleton to avoid reload costs)."""
        if self._router is None:
            from brain_researcher.services.agent.knowledge.llm_utils import (
                get_llm_router,
            )

            self._router = get_llm_router()
        return self._router

    def _invoke_llm(self, prompt: str) -> str:
        """Invoke LLM with prompt.

        Args:
            prompt: The prompt to send

        Returns:
            LLM response text
        """
        router = self._get_router()
        result = router.route_chat(
            prompt=prompt,
            model_hint=self._model_hint,
            task_type="classification",
            strict_json=True,
        )
        return result.text

    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        """Parse JSON from LLM response, handling markdown code blocks.

        Args:
            text: Raw LLM response text

        Returns:
            Parsed JSON dictionary
        """
        # Strip markdown code fences if present
        text = text.strip()
        if text.startswith("```"):
            # Remove opening fence (with optional language)
            text = re.sub(r"^```\w*\n?", "", text)
            # Remove closing fence
            text = re.sub(r"\n?```$", "", text)

        # Try to parse JSON
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse LLM JSON response: %s", e)
            return {}

    def _format_evidence_summary(
        self, bundle: EvidenceBundle, max_items: int = 10
    ) -> str:
        """Format evidence bundle for prompt inclusion.

        Args:
            bundle: The evidence bundle
            max_items: Maximum items to include

        Returns:
            Formatted evidence summary string
        """
        lines = []
        for item in bundle.get_top_items(max_items):
            source_label = item.source_type.value.upper()
            lines.append(f"- [{source_label}] {item.label} (score: {item.relevance_score:.2f})")

            # Add metadata if available
            if item.metadata:
                meta_items = []
                for key in ["tasks", "modalities", "year", "description"]:
                    if key in item.metadata:
                        val = item.metadata[key]
                        if isinstance(val, list):
                            val = ", ".join(str(v) for v in val[:3])
                        meta_items.append(f"{key}={val}")
                if meta_items:
                    lines.append(f"    ({'; '.join(meta_items)})")

        return "\n".join(lines) if lines else "No evidence available."

    def _format_citations(self, bundle: EvidenceBundle) -> str:
        """Format citations for prompt inclusion.

        Args:
            bundle: The evidence bundle

        Returns:
            Formatted citations string
        """
        citations = bundle.format_citations(max_citations=self._max_citations)
        lines = []
        for cit in citations:
            url_part = f" - {cit['url']}" if cit.get("url") else ""
            lines.append(f"{cit['ref']} {cit['label']}{url_part}")
        return "\n".join(lines) if lines else "No citations available."

    def _format_dataset_evidence(self, bundle: EvidenceBundle) -> str:
        """Format dataset-specific evidence.

        Args:
            bundle: The evidence bundle

        Returns:
            Formatted dataset evidence string
        """
        dataset_items = bundle.get_items_by_source(EvidenceSourceType.DATASET_CATALOG)
        if not dataset_items:
            return "No datasets found in evidence."

        lines = []
        for item in dataset_items[:10]:
            meta = item.metadata or {}
            tasks = meta.get("tasks", [])
            modalities = meta.get("modalities", [])
            n_subjects = meta.get("n_subjects", "?")

            lines.append(f"- {item.source_id}: {item.label}")
            lines.append(f"    Tasks: {', '.join(tasks) if tasks else 'N/A'}")
            lines.append(f"    Modalities: {', '.join(modalities) if modalities else 'N/A'}")
            lines.append(f"    Subjects: {n_subjects}")

        return "\n".join(lines)

    def _format_tool_evidence(self, bundle: EvidenceBundle) -> str:
        """Format tool-specific evidence.

        Args:
            bundle: The evidence bundle

        Returns:
            Formatted tool evidence string
        """
        tool_items = bundle.get_items_by_source(EvidenceSourceType.TOOL_CATALOG)
        if not tool_items:
            return "No tools found in evidence."

        lines = []
        for item in tool_items[:10]:
            desc = item.metadata.get("description", "") if item.metadata else ""
            lines.append(f"- {item.source_id}: {desc[:100]}...")

        return "\n".join(lines)

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
            evidence_count=len(bundle.items),
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
            else:
                return DecisionType.EXPLANATION

        except Exception as e:
            logger.warning("Intent classification failed: %s; defaulting to EXPLANATION", e)
            return DecisionType.EXPLANATION

    async def _generate_explanation_plan(
        self, query: str, bundle: EvidenceBundle
    ) -> KnowledgePlan:
        """Generate an explanation plan.

        Args:
            query: The user's query
            bundle: Gathered evidence

        Returns:
            KnowledgePlan for explanation
        """
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
                citations=bundle.format_citations(self._max_citations),
                confidence=result.get("confidence", bundle.confidence),
                evidence_bundle=bundle,
                metadata={
                    "key_concepts": result.get("key_concepts", []),
                },
            )

        except Exception as e:
            logger.warning("Explanation generation failed: %s", e)
            return KnowledgePlan(
                decision_type=DecisionType.EXPLANATION,
                query=query,
                reasoning=f"Fallback plan due to error: {e}",
                explanation="Unable to generate explanation at this time.",
                citations=bundle.format_citations(self._max_citations),
                confidence=0.3,
                evidence_bundle=bundle,
            )

    async def _generate_dataset_plan(
        self, query: str, bundle: EvidenceBundle
    ) -> KnowledgePlan:
        """Generate a dataset selection plan.

        Args:
            query: The user's query
            bundle: Gathered evidence

        Returns:
            KnowledgePlan for dataset selection
        """
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
                citations=bundle.format_citations(self._max_citations),
                confidence=result.get("confidence", bundle.confidence),
                evidence_bundle=bundle,
            )

        except Exception as e:
            logger.warning("Dataset selection failed: %s", e)
            # Fallback: return top datasets from evidence
            dataset_items = bundle.get_items_by_source(EvidenceSourceType.DATASET_CATALOG)
            fallback_datasets = [item.source_id for item in dataset_items[:5]]

            return KnowledgePlan(
                decision_type=DecisionType.DATASET_SELECTION,
                query=query,
                reasoning=f"Fallback selection due to error: {e}",
                recommended_datasets=fallback_datasets,
                dataset_scores={ds: 0.5 for ds in fallback_datasets},
                citations=bundle.format_citations(self._max_citations),
                confidence=0.4,
                evidence_bundle=bundle,
            )

    async def _generate_pipeline_plan(
        self, query: str, bundle: EvidenceBundle
    ) -> KnowledgePlan:
        """Generate a pipeline recommendation plan.

        Args:
            query: The user's query
            bundle: Gathered evidence

        Returns:
            KnowledgePlan for pipeline recommendation
        """
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
                citations=bundle.format_citations(self._max_citations),
                confidence=result.get("confidence", bundle.confidence),
                evidence_bundle=bundle,
            )

        except Exception as e:
            logger.warning("Pipeline recommendation failed: %s", e)
            # Fallback: return top tools from evidence
            tool_items = bundle.get_items_by_source(EvidenceSourceType.TOOL_CATALOG)
            fallback_tools = [item.source_id for item in tool_items[:5]]

            return KnowledgePlan(
                decision_type=DecisionType.PIPELINE_RECOMMENDATION,
                query=query,
                reasoning=f"Fallback recommendation due to error: {e}",
                recommended_tools=fallback_tools,
                tool_sequence=fallback_tools,
                citations=bundle.format_citations(self._max_citations),
                confidence=0.4,
                evidence_bundle=bundle,
            )

    async def build_plan(
        self,
        query: str,
        bundle: EvidenceBundle,
        force_intent: Optional[DecisionType] = None,
    ) -> KnowledgePlan:
        """Build a knowledge plan based on query and evidence.

        This is the main entry point for planning.

        Args:
            query: The user's query
            bundle: Gathered evidence from EvidenceAggregator
            force_intent: Optional override for intent classification

        Returns:
            KnowledgePlan with recommendations
        """
        # Classify intent (or use override)
        intent = force_intent or await self.classify_intent(query, bundle)

        # Generate appropriate plan
        if intent == DecisionType.EXPLANATION:
            return await self._generate_explanation_plan(query, bundle)
        elif intent == DecisionType.DATASET_SELECTION:
            return await self._generate_dataset_plan(query, bundle)
        else:  # PIPELINE_RECOMMENDATION
            return await self._generate_pipeline_plan(query, bundle)


# Factory function
def create_knowledge_planner(
    model_hint: Optional[str] = None,
    max_citations: int = 10,
) -> KnowledgePlanner:
    """Create a knowledge planner instance.

    Args:
        model_hint: Optional model override
        max_citations: Maximum citations to include

    Returns:
        Configured KnowledgePlanner
    """
    return KnowledgePlanner(
        model_hint=model_hint,
        max_citations=max_citations,
    )


__all__ = [
    "KnowledgePlanner",
    "create_knowledge_planner",
]
