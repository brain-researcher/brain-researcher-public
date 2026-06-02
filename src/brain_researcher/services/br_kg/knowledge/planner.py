"""Knowledge Planner for Track K+.

LLM-driven planning that uses aggregated evidence to decide:
- Intent: explanation, dataset_selection, or pipeline_recommendation
- Recommended datasets and tools
- Justification based on evidence
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from .models import AggregatedEvidence, KnowledgePlan, PlanIntent

if TYPE_CHECKING:
    from brain_researcher.services.shared.r2brkg_query_understanding_types import (
        QueryUnderstandingResult,
    )

logger = logging.getLogger(__name__)


@dataclass
class PlannerConfig:
    """Configuration for the KnowledgePlanner."""

    # LLM settings
    model_name: str = "gpt-4o-mini"  # Default to fast model
    temperature: float = 0.3
    max_tokens: int = 1024

    # Caching
    enable_cache: bool = True
    cache_ttl_seconds: int = 3600  # 1 hour

    # Heuristics
    use_heuristics_first: bool = True  # Try rules before LLM
    min_datasets_for_pipeline: int = 1


class PlanCache:
    """Simple in-memory cache for KnowledgePlans indexed by query pattern."""

    def __init__(self, ttl_seconds: int = 3600):
        self.ttl = ttl_seconds
        self._cache: dict[str, tuple[KnowledgePlan, float]] = {}

    def _normalize_query(self, query: str, entities: list[str]) -> str:
        """Normalize query to cache key.

        Replaces specific entity mentions with placeholders to match
        similar queries.
        """
        normalized = query.lower().strip()

        # Replace dataset IDs
        normalized = re.sub(r"ds0*\d+", "{dataset}", normalized)

        # Replace specific task names with placeholder
        for entity in entities:
            if entity.lower() in normalized:
                normalized = normalized.replace(entity.lower(), "{entity}")

        # Collapse whitespace
        normalized = re.sub(r"\s+", " ", normalized)

        return normalized

    def get_cache_key(self, query: str, entities: list[str]) -> str:
        """Generate cache key from query pattern."""
        normalized = self._normalize_query(query, entities)
        return hashlib.md5(normalized.encode()).hexdigest()[:16]

    def get(self, cache_key: str) -> KnowledgePlan | None:
        """Get cached plan if valid."""
        if cache_key not in self._cache:
            return None

        plan, timestamp = self._cache[cache_key]
        if time.time() - timestamp > self.ttl:
            del self._cache[cache_key]
            return None

        return plan

    def set(self, cache_key: str, plan: KnowledgePlan) -> None:
        """Cache a plan."""
        # Simple size limit
        if len(self._cache) > 1000:
            # Remove oldest
            oldest = min(self._cache.keys(), key=lambda k: self._cache[k][1])
            del self._cache[oldest]

        self._cache[cache_key] = (plan, time.time())


class KnowledgePlanner:
    """LLM-driven planner that uses evidence to decide intent and recommendations.

    Supports:
    - Heuristic-based fast path for common patterns
    - LLM-based planning for complex queries
    - Caching by normalized query pattern

    Usage:
        planner = KnowledgePlanner()
        plan = await planner.plan(
            query_understanding_result,
            aggregated_evidence,
        )
        print(plan.intent, plan.recommended_datasets)
    """

    def __init__(self, config: PlannerConfig | None = None):
        """Initialize the planner.

        Args:
            config: Optional configuration. Uses defaults if not provided.
        """
        self.config = config or PlannerConfig()
        self._cache = PlanCache(self.config.cache_ttl_seconds)
        self._router = None

    def _get_entities(self, qur: QueryUnderstandingResult | None) -> list[str]:
        """Extract entity strings from query understanding result."""
        if not qur:
            return []
        entities = []
        for ent in qur.entities or []:
            if isinstance(ent, dict):
                entities.append(ent.get("text", ""))
            elif hasattr(ent, "text"):
                entities.append(ent.text)
        return [e for e in entities if e]

    def _heuristic_plan(
        self,
        query: str,
        qur: QueryUnderstandingResult | None,
        evidence: AggregatedEvidence,
    ) -> KnowledgePlan | None:
        """Try to create a plan using heuristics before calling LLM.

        Returns None if heuristics can't confidently decide.
        """
        query_lower = query.lower()

        # Extract info from evidence
        dataset_items = [i for i in evidence.items if i.source_id == "dataset_catalog"]
        tool_items = [i for i in evidence.items if i.source_id == "tool_registry"]
        kg_items = [i for i in evidence.items if i.source_id == "br_kg"]

        # Heuristic 1: Explicit explanation request
        explanation_keywords = [
            "what is",
            "explain",
            "tell me about",
            "describe",
            "define",
        ]
        if any(kw in query_lower for kw in explanation_keywords):
            return KnowledgePlan(
                intent=PlanIntent.EXPLANATION,
                justification="Query explicitly asks for explanation",
                confidence=0.9,
                evidence_ids=[i.id for i in kg_items[:5]],
            )

        # Heuristic 2: Dataset search request
        dataset_keywords = [
            "find dataset",
            "search dataset",
            "which dataset",
            "looking for data",
        ]
        if any(kw in query_lower for kw in dataset_keywords):
            return KnowledgePlan(
                intent=PlanIntent.DATASET_SELECTION,
                recommended_datasets=[
                    d.metadata.get("dataset_id", d.id) for d in dataset_items[:5]
                ],
                justification="Query explicitly asks for datasets",
                confidence=0.9,
                evidence_ids=[d.id for d in dataset_items[:5]],
            )

        # Heuristic 3: Analysis request with available datasets
        analysis_keywords = [
            "analyze",
            "run",
            "process",
            "pipeline",
            "compute",
            "glm",
            "preprocess",
        ]
        has_analysis_intent = any(kw in query_lower for kw in analysis_keywords)

        if has_analysis_intent and dataset_items:
            # Check if we have resolved datasets from QUR
            resolved_datasets = []
            if qur and qur.resolved_datasets:
                resolved_datasets = [d.dataset_id for d in qur.resolved_datasets]
            elif dataset_items:
                resolved_datasets = [
                    d.metadata.get("dataset_id", d.id.replace("dataset:", ""))
                    for d in dataset_items[:3]
                ]

            if resolved_datasets:
                return KnowledgePlan(
                    intent=PlanIntent.PIPELINE_RECOMMENDATION,
                    recommended_datasets=resolved_datasets,
                    recommended_tools=[
                        t.metadata.get("tool_name", t.title) for t in tool_items[:5]
                    ],
                    justification="Analysis requested with available datasets",
                    confidence=0.8,
                    evidence_ids=[i.id for i in dataset_items[:3] + tool_items[:3]],
                )

        # Can't confidently decide with heuristics
        return None

    def _build_llm_prompt(
        self,
        query: str,
        qur: QueryUnderstandingResult | None,
        evidence: AggregatedEvidence,
    ) -> str:
        """Build the prompt for LLM-based planning."""
        # Group evidence by source
        evidence_by_source = evidence.items_by_source()

        prompt_parts = [
            "You are a neuroimaging research assistant helping decide how to respond to a user query.",
            "",
            "# User Query",
            query,
            "",
        ]

        # Add query understanding context
        if qur:
            prompt_parts.extend(
                [
                    "# Extracted Entities",
                ]
            )
            for ent in qur.entities[:10]:
                if isinstance(ent, dict):
                    prompt_parts.append(
                        f"- {ent.get('text', '')} ({ent.get('entity_type', '')})"
                    )
            prompt_parts.append("")

            if qur.resolved_datasets:
                prompt_parts.extend(
                    [
                        "# Resolved Datasets (available locally)",
                    ]
                )
                for ds in qur.resolved_datasets[:5]:
                    prompt_parts.append(f"- {ds.dataset_id}: {ds.name}")
                prompt_parts.append("")

        # Add evidence
        prompt_parts.extend(
            [
                "# Available Evidence",
            ]
        )

        for source_id, items in evidence_by_source.items():
            prompt_parts.append(f"\n## {source_id} ({len(items)} items)")
            for item in items[:5]:
                prompt_parts.append(
                    f"- [{item.id}] {item.title} (score: {item.score:.2f})"
                )

        prompt_parts.extend(
            [
                "",
                "# Your Task",
                "Decide how to respond to this query. Choose ONE of:",
                "1. explanation - Just explain/answer the question, don't run analysis",
                "2. dataset_selection - Help user select appropriate datasets",
                "3. pipeline_recommendation - Recommend and prepare to run analysis pipeline",
                "",
                "Respond with a JSON object containing:",
                "- intent: one of [explanation, dataset_selection, pipeline_recommendation]",
                "- recommended_datasets: list of dataset IDs (can be empty)",
                "- recommended_tools: list of tool names (can be empty)",
                "- justification: brief explanation of your decision",
                "- evidence_ids: list of evidence IDs that support your decision",
                "",
                "JSON:",
            ]
        )

        return "\n".join(prompt_parts)

    async def _call_llm(self, prompt: str) -> KnowledgePlan | None:
        """Call LLM to generate a plan."""
        try:
            # Lazy import router
            if self._router is None:
                from brain_researcher.services.llm_gateway.router import route_chat

                self._router = route_chat

            response = await self._router(
                messages=[{"role": "user", "content": prompt}],
                model=self.config.model_name,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )

            # Parse JSON from response
            text = response.text if hasattr(response, "text") else str(response)

            # Extract JSON from response (handle markdown code blocks)
            json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
            if json_match:
                text = json_match.group(1)
            else:
                # Try to find raw JSON
                json_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
                if json_match:
                    text = json_match.group(0)

            data = json.loads(text)

            # Map intent string to enum
            intent_str = data.get("intent", "explanation").lower()
            intent_map = {
                "explanation": PlanIntent.EXPLANATION,
                "dataset_selection": PlanIntent.DATASET_SELECTION,
                "pipeline_recommendation": PlanIntent.PIPELINE_RECOMMENDATION,
            }
            intent = intent_map.get(intent_str, PlanIntent.EXPLANATION)

            return KnowledgePlan(
                intent=intent,
                recommended_datasets=data.get("recommended_datasets", []),
                recommended_tools=data.get("recommended_tools", []),
                justification=data.get("justification", ""),
                evidence_ids=data.get("evidence_ids", []),
                confidence=0.85,  # LLM confidence
            )

        except Exception as e:
            logger.warning("LLM planning failed: %s", e)
            return None

    async def plan(
        self,
        qur: QueryUnderstandingResult | None,
        evidence: AggregatedEvidence,
    ) -> KnowledgePlan:
        """Generate a knowledge plan from evidence.

        Args:
            qur: Query understanding result (optional)
            evidence: Aggregated evidence from all sources

        Returns:
            KnowledgePlan with intent and recommendations
        """
        start_time = time.time()
        query = evidence.query

        # Check cache
        entities = self._get_entities(qur)
        cache_key = self._cache.get_cache_key(query, entities)

        if self.config.enable_cache:
            cached = self._cache.get(cache_key)
            if cached:
                cached.cache_key = cache_key
                cached.cached_at = datetime.utcnow()
                return cached

        # Try heuristics first
        plan = None
        if self.config.use_heuristics_first:
            plan = self._heuristic_plan(query, qur, evidence)
            if plan:
                plan.planning_duration_ms = (time.time() - start_time) * 1000
                plan.cache_key = cache_key
                self._cache.set(cache_key, plan)
                return plan

        # Fall back to LLM
        prompt = self._build_llm_prompt(query, qur, evidence)
        plan = await self._call_llm(prompt)

        if plan:
            plan.planning_duration_ms = (time.time() - start_time) * 1000
            plan.cache_key = cache_key
            self._cache.set(cache_key, plan)
            return plan

        # Fallback: default to explanation
        return KnowledgePlan(
            intent=PlanIntent.EXPLANATION,
            justification="Unable to determine intent, defaulting to explanation",
            confidence=0.5,
            planning_duration_ms=(time.time() - start_time) * 1000,
        )


__all__ = [
    "KnowledgePlanner",
    "PlanCache",
    "PlannerConfig",
]
