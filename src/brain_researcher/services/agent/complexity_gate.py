"""
Complexity Gate for Plan Memory System (MVP - Slice 1)

Hybrid complexity assessment that determines if a query needs full planning
or can be handled with direct tool execution. MVP uses heuristics only (no LLM).

This module is part of the Plan Memory system that enables:
- Fast routing for simple queries (single tool call)
- Full planning path for complex multi-step queries
- Historical lookup for known query patterns
"""

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from brain_researcher.services.agent.plan_memory import PlanMemory

logger = logging.getLogger(__name__)


@dataclass
class ComplexityResult:
    """Result of complexity assessment."""

    level: str  # "simple" or "complex"
    confidence: float  # 0.0 - 1.0
    reason: str  # Why this decision was made
    suggested_tool: str | None = None  # For simple queries, which tool to use


class ComplexityGate:
    """
    Hybrid complexity assessment: fast heuristics + plan memory lookup.

    MVP Implementation (Slice 1):
    - Pattern matching for simple queries
    - Keyword detection for complex queries
    - Plan memory lookup for historical patterns
    - NO LLM fallback (added in Slice 2)

    Decision Flow:
    1. Pattern Match → simple (direct tool)
    2. Complex Keywords → complex (full planning)
    3. Domain Patterns → complex (multi-step analysis)
    4. Plan Memory Lookup → use historical complexity
    5. Default → complex (safer fallback)
    """

    # ========== Stage 1: Fast Pattern Matching (<1ms) ==========

    # Queries matching these → SIMPLE (single tool call)
    SIMPLE_PATTERNS = [
        (r"^what is\s+(.+?)[\?.]?$", "kg_search", "definition query"),
        (r"^search\s+(?:for\s+)?(.+)$", "dataset_search", "simple search"),
        (r"^find\s+(.+)$", "dataset_search", "find query"),
        (r"^list\s+(?:all\s+)?(.+)$", "dataset_list", "list query"),
        (r"^show\s+(?:me\s+)?(.+)$", "dataset_search", "show query"),
        (r"^get\s+(.+)$", "dataset_search", "get query"),
        (r"^describe\s+(.+)$", "kg_search", "describe query"),
        (r"^explain\s+(.+)$", "kg_search", "explain query"),
        (r"^lookup\s+(.+)$", "kg_search", "lookup query"),
        (r"^fetch\s+(.+)$", "dataset_search", "fetch query"),
    ]

    # Queries containing these → COMPLEX (multi-step planning)
    COMPLEX_KEYWORDS = {
        # Sequential markers (high weight)
        "then": 0.8,
        "after that": 0.9,
        "first": 0.7,
        "finally": 0.8,
        "next": 0.6,
        "followed by": 0.9,
        "subsequently": 0.85,
        # Multi-step analysis
        "compare": 0.7,
        "analyze": 0.6,
        "across": 0.7,
        "between": 0.5,
        "correlate": 0.7,
        # Explicit orchestration
        "pipeline": 0.95,
        "workflow": 0.95,
        "batch": 0.8,
        "process all": 0.85,
        # Compound tasks
        "and also": 0.8,
        "as well as": 0.8,
        "in addition": 0.7,
        "multiple": 0.6,
        "several": 0.5,
        # Domain-specific complex operations
        "preprocess": 0.75,
        "run glm": 0.8,
        "contrast map": 0.7,
        "group analysis": 0.85,
        "second-level": 0.85,
        "meta-analysis": 0.9,
    }

    # Domain-specific patterns → COMPLEX
    COMPLEX_DOMAIN_PATTERNS = [
        r"run\s+(?:glm|fmri|preprocessing)",  # Neuroimaging analysis
        r"create\s+(?:a\s+)?(?:new\s+)?pipeline",  # Pipeline creation
        r"visualize\s+.+\s+and\s+",  # Compound visualization
        r"contrast\s+.+\s+(?:vs|versus|with)",  # Statistical contrast
        r"compare\s+.+\s+(?:to|with|and)\s+",  # Comparison analysis
        r"process\s+(?:all|multiple|each)",  # Batch processing
        r"(?:train|fit)\s+(?:a\s+)?model",  # Model training
        r"(?:cross|leave).*validation",  # Cross-validation
    ]

    # Historical step threshold for complexity
    HISTORICAL_STEP_THRESHOLD = 2  # If avg steps > 2, treat as complex

    def __init__(self, plan_memory: Optional["PlanMemory"] = None):
        """
        Initialize the complexity gate.

        Args:
            plan_memory: Optional PlanMemory instance for historical lookup
        """
        self.plan_memory = plan_memory

    def assess(self, query: str, context: dict | None = None) -> ComplexityResult:
        """
        Assess query complexity using hybrid heuristic approach.

        Args:
            query: User's natural language query
            context: Optional context (user_id, workspace_id, conversation history)

        Returns:
            ComplexityResult with level, confidence, reason, and optional suggested_tool
        """
        query_lower = query.lower().strip()
        context = context or {}

        # Stage 1a: Simple pattern matching
        for pattern, tool, reason in self.SIMPLE_PATTERNS:
            if re.match(pattern, query_lower, re.IGNORECASE):
                self._log_decision(
                    query, "simple", 0.9, f"pattern_match: {reason}", context
                )
                return ComplexityResult(
                    level="simple",
                    confidence=0.9,
                    reason=f"pattern_match: {reason}",
                    suggested_tool=tool,
                )

        # Stage 1b: Complex keyword detection
        keyword_scores = []
        for keyword, weight in self.COMPLEX_KEYWORDS.items():
            if keyword in query_lower:
                keyword_scores.append((keyword, weight))

        if keyword_scores:
            max_keyword, max_weight = max(keyword_scores, key=lambda x: x[1])
            if max_weight >= 0.7:
                self._log_decision(
                    query,
                    "complex",
                    max_weight,
                    f"keyword: '{max_keyword}' (weight={max_weight})",
                    context,
                )
                return ComplexityResult(
                    level="complex",
                    confidence=max_weight,
                    reason=f"keyword: '{max_keyword}' (weight={max_weight})",
                )

        # Stage 1c: Domain-specific complex patterns
        for pattern in self.COMPLEX_DOMAIN_PATTERNS:
            if re.search(pattern, query_lower, re.IGNORECASE):
                self._log_decision(
                    query, "complex", 0.85, f"domain_pattern: {pattern}", context
                )
                return ComplexityResult(
                    level="complex",
                    confidence=0.85,
                    reason=f"domain_pattern: {pattern}",
                )

        # Stage 2: Plan memory lookup (if available)
        if self.plan_memory:
            try:
                similar_plans = self.plan_memory.recall_similar(
                    query,
                    user_id=context.get("user_id", ""),
                    workspace_id=context.get("workspace_id", ""),
                    top_k=3,
                )

                if similar_plans:
                    # Calculate average step count from similar plans
                    avg_steps = sum(
                        p.get("step_count", 1) for p in similar_plans
                    ) / len(similar_plans)

                    if avg_steps > self.HISTORICAL_STEP_THRESHOLD:
                        self._log_decision(
                            query,
                            "complex",
                            0.8,
                            f"historical: avg_steps={avg_steps:.1f} from {len(similar_plans)} similar plans",
                            context,
                        )
                        return ComplexityResult(
                            level="complex",
                            confidence=0.8,
                            reason=f"historical: avg_steps={avg_steps:.1f} from {len(similar_plans)} similar plans",
                        )
                    else:
                        self._log_decision(
                            query,
                            "simple",
                            0.75,
                            f"historical: avg_steps={avg_steps:.1f}, single-step pattern",
                            context,
                        )
                        return ComplexityResult(
                            level="simple",
                            confidence=0.75,
                            reason=f"historical: avg_steps={avg_steps:.1f}, single-step pattern",
                            suggested_tool=similar_plans[0].get("primary_tool"),
                        )
            except Exception as e:
                logger.warning(f"Plan memory lookup failed: {e}")

        # Stage 3 (MVP): No LLM fallback - default to complex (safer)
        # LLM fallback will be added in Slice 2
        self._log_decision(
            query, "complex", 0.5, "default: no pattern match, no history", context
        )
        return ComplexityResult(
            level="complex",
            confidence=0.5,
            reason="default: no pattern match, no history",
        )

    def _log_decision(
        self, query: str, level: str, confidence: float, reason: str, context: dict
    ):
        """Log complexity decision for observability."""
        query_hash = hashlib.md5(query.encode()).hexdigest()[:8]
        logger.info(
            "complexity_decision",
            extra={
                "query_hash": query_hash,
                "level": level,
                "confidence": confidence,
                "reason": reason,
                "user_id": context.get("user_id"),
            },
        )


def create_complexity_gate(
    plan_memory: Optional["PlanMemory"] = None,
) -> ComplexityGate:
    """
    Factory function to create a ComplexityGate instance.

    Args:
        plan_memory: Optional PlanMemory for historical lookup

    Returns:
        Configured ComplexityGate instance
    """
    return ComplexityGate(plan_memory=plan_memory)
