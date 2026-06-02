"""
Enhanced Tool Registry with Advanced Parameter Inference and Confidence Scoring

This module implements sophisticated tool selection, parameter inference, and
execution monitoring capabilities for the Brain Researcher Agent system.
"""

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from uuid import uuid4

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from brain_researcher.services.shared.toolsagent_evidence_collection import (
    ConfidenceLevel,
    EvidenceCollector,
    EvidenceType,
)
from brain_researcher.services.shared.toolsagent_tool_metadata_bridge import (
    get_resource_hints,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper
from brain_researcher.services.tools.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


class ParameterInferenceStrategy(Enum):
    """Strategies for parameter inference."""

    SEMANTIC_MATCHING = "semantic_matching"
    CONTEXT_BASED = "context_based"
    HISTORICAL_PATTERNS = "historical_patterns"
    USER_PREFERENCES = "user_preferences"


class ConfidenceMetric(Enum):
    """Types of confidence metrics."""

    TOOL_MATCH_CONFIDENCE = "tool_match_confidence"
    PARAMETER_CONFIDENCE = "parameter_confidence"
    EXECUTION_CONFIDENCE = "execution_confidence"
    OUTPUT_QUALITY_CONFIDENCE = "output_quality_confidence"


@dataclass
class ParameterInference:
    """Result of parameter inference for a tool."""

    tool_name: str
    inferred_parameters: Dict[str, Any]
    confidence_scores: Dict[str, float]
    inference_strategy: ParameterInferenceStrategy
    reasoning: str
    fallback_parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolRecommendation:
    """Tool recommendation with confidence and reasoning."""

    tool: NeuroToolWrapper
    confidence_score: float
    match_reasons: List[str]
    parameter_suggestions: Dict[str, Any]
    estimated_execution_time: float
    resource_requirements: List[str]
    success_probability: float


@dataclass
class ExecutionMetrics:
    """Comprehensive execution metrics for monitoring."""

    execution_id: str
    tool_name: str
    start_time: float
    end_time: Optional[float] = None
    duration: Optional[float] = None
    success: Optional[bool] = None
    error_message: Optional[str] = None
    resource_usage: Dict[str, Any] = field(default_factory=dict)
    output_size: Optional[int] = None
    confidence_scores: Dict[ConfidenceMetric, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class ParameterInferenceEngine:
    """Advanced parameter inference engine with multiple strategies."""

    def __init__(self, use_ml_inference: bool = True):
        """Initialize parameter inference engine."""
        self.use_ml_inference = use_ml_inference
        self.parameter_history: Dict[str, List[Dict[str, Any]]] = {}
        self.user_preferences: Dict[str, Any] = {}
        self.context_patterns: Dict[str, Any] = {}

        # Initialize TF-IDF vectorizer for semantic matching
        if use_ml_inference:
            self.vectorizer = TfidfVectorizer(
                max_features=1000, stop_words="english", ngram_range=(1, 2)
            )
            self.fitted_vectorizer = False

        logger.info("Parameter inference engine initialized")

    def infer_parameters(
        self,
        tool: NeuroToolWrapper,
        query: str,
        context: Dict[str, Any] = None,
        user_preferences: Dict[str, Any] = None,
    ) -> ParameterInference:
        """
        Infer optimal parameters for a tool based on query and context.

        Args:
            tool: Tool to infer parameters for
            query: User query
            context: Execution context
            user_preferences: User-specific preferences

        Returns:
            Parameter inference result
        """
        context = context or {}
        user_preferences = user_preferences or {}

        # Get tool's parameter schema
        tool_schema = self._get_tool_parameter_schema(tool)

        # Apply different inference strategies
        strategies = [
            self._semantic_matching_inference,
            self._context_based_inference,
            self._historical_patterns_inference,
            self._user_preferences_inference,
        ]

        inference_results = []
        for strategy in strategies:
            try:
                result = strategy(tool, query, tool_schema, context, user_preferences)
                if result:
                    inference_results.append(result)
            except Exception as e:
                logger.warning(f"Parameter inference strategy failed: {e}")

        # Combine results from different strategies
        return self._combine_inference_results(tool, inference_results, query)

    def _get_tool_parameter_schema(self, tool: NeuroToolWrapper) -> Dict[str, Any]:
        """Extract parameter schema from tool."""
        try:
            # Get tool's structured schema
            langchain_tool = tool.as_langchain_tool()
            if hasattr(langchain_tool, "args_schema") and langchain_tool.args_schema:
                schema = langchain_tool.args_schema.schema()
                return schema.get("properties", {})

            # Fallback to tool description parsing
            return self._parse_tool_description_for_parameters(tool)

        except Exception as e:
            logger.warning(
                f"Failed to get parameter schema for {tool.get_tool_name()}: {e}"
            )
            return {}

    def _parse_tool_description_for_parameters(
        self, tool: NeuroToolWrapper
    ) -> Dict[str, Any]:
        """Parse tool description to extract parameter information."""
        description = tool.get_tool_description()
        parameters = {}

        # Simple heuristics for common neuroimaging parameters
        common_params = {
            "threshold": {"type": "number", "default": 0.05, "range": [0.001, 0.1]},
            "fwhm": {"type": "number", "default": 6.0, "range": [2.0, 12.0]},
            "tr": {"type": "number", "default": 2.0, "range": [0.5, 5.0]},
            "mask": {"type": "string", "pattern": ".*\\.nii(\\.gz)?$"},
            "output_dir": {"type": "string", "default": "/tmp/analysis"},
            "n_jobs": {"type": "integer", "default": 1, "range": [1, 8]},
            "memory": {"type": "string", "default": "8GB"},
        }

        # Extract parameters mentioned in description
        desc_lower = description.lower()
        for param, schema in common_params.items():
            if param in desc_lower or param.replace("_", " ") in desc_lower:
                parameters[param] = schema

        return parameters

    def _semantic_matching_inference(
        self, tool, query, tool_schema, context, user_prefs
    ) -> Optional[ParameterInference]:
        """Infer parameters using semantic matching."""
        if not self.use_ml_inference:
            return None

        inferred_params = {}
        confidence_scores = {}
        reasoning_parts = []

        # Analyze query for neuroimaging-specific terms
        query_lower = query.lower()

        # Statistical threshold inference
        if "significant" in query_lower or "threshold" in query_lower:
            if "threshold" in tool_schema:
                if "strict" in query_lower or "conservative" in query_lower:
                    inferred_params["threshold"] = 0.001
                    confidence_scores["threshold"] = 0.8
                    reasoning_parts.append("Conservative threshold for strict analysis")
                elif "liberal" in query_lower or "exploratory" in query_lower:
                    inferred_params["threshold"] = 0.1
                    confidence_scores["threshold"] = 0.7
                    reasoning_parts.append("Liberal threshold for exploratory analysis")
                else:
                    inferred_params["threshold"] = 0.05
                    confidence_scores["threshold"] = 0.9
                    reasoning_parts.append(
                        "Standard threshold for significance testing"
                    )

        # Smoothing inference
        if "smooth" in query_lower and "fwhm" in tool_schema:
            if "high resolution" in query_lower or "precise" in query_lower:
                inferred_params["fwhm"] = 4.0
                confidence_scores["fwhm"] = 0.7
                reasoning_parts.append("Small smoothing kernel for high resolution")
            else:
                inferred_params["fwhm"] = 6.0
                confidence_scores["fwhm"] = 0.8
                reasoning_parts.append("Standard smoothing kernel")

        # Parallelization inference based on computational requirements
        if "n_jobs" in tool_schema:
            tool_name = tool.get_tool_name().lower()
            if any(term in tool_name for term in ["fmriprep", "preprocessing", "glm"]):
                inferred_params["n_jobs"] = 4
                confidence_scores["n_jobs"] = 0.9
                reasoning_parts.append(
                    "Parallel processing for computationally intensive task"
                )
            else:
                inferred_params["n_jobs"] = 1
                confidence_scores["n_jobs"] = 0.6
                reasoning_parts.append("Single-threaded processing for simple task")

        if inferred_params:
            return ParameterInference(
                tool_name=tool.get_tool_name(),
                inferred_parameters=inferred_params,
                confidence_scores=confidence_scores,
                inference_strategy=ParameterInferenceStrategy.SEMANTIC_MATCHING,
                reasoning="; ".join(reasoning_parts),
            )

        return None

    def _context_based_inference(
        self, tool, query, tool_schema, context, user_prefs
    ) -> Optional[ParameterInference]:
        """Infer parameters based on execution context."""
        inferred_params = {}
        confidence_scores = {}
        reasoning_parts = []

        # Use previous execution results for context
        if "previous_results" in context:
            prev_results = context["previous_results"]

            # Adapt thresholds based on previous findings
            if "threshold" in tool_schema and isinstance(prev_results, dict):
                significant_findings = prev_results.get("significant_results", 0)
                if significant_findings == 0:
                    # No significant findings, suggest more liberal threshold
                    inferred_params["threshold"] = 0.1
                    confidence_scores["threshold"] = 0.6
                    reasoning_parts.append(
                        "Liberal threshold due to no previous significant findings"
                    )
                elif significant_findings > 1000:
                    # Too many findings, suggest stricter threshold
                    inferred_params["threshold"] = 0.001
                    confidence_scores["threshold"] = 0.7
                    reasoning_parts.append(
                        "Conservative threshold due to many findings"
                    )

        # Use dataset characteristics if available
        if "dataset_info" in context:
            dataset = context["dataset_info"]

            # Infer TR from dataset
            if "tr" in tool_schema and "repetition_time" in dataset:
                inferred_params["tr"] = dataset["repetition_time"]
                confidence_scores["tr"] = 0.95
                reasoning_parts.append("TR from dataset metadata")

            # Infer number of subjects for group analysis
            if "n_subjects" in tool_schema and "num_subjects" in dataset:
                inferred_params["n_subjects"] = dataset["num_subjects"]
                confidence_scores["n_subjects"] = 0.9
                reasoning_parts.append("Subject count from dataset")

        if inferred_params:
            return ParameterInference(
                tool_name=tool.get_tool_name(),
                inferred_parameters=inferred_params,
                confidence_scores=confidence_scores,
                inference_strategy=ParameterInferenceStrategy.CONTEXT_BASED,
                reasoning="; ".join(reasoning_parts),
            )

        return None

    def _historical_patterns_inference(
        self, tool, query, tool_schema, context, user_prefs
    ) -> Optional[ParameterInference]:
        """Infer parameters based on historical usage patterns."""
        tool_name = tool.get_tool_name()

        if tool_name not in self.parameter_history:
            return None

        history = self.parameter_history[tool_name]
        if not history:
            return None

        # Analyze most common parameter values
        inferred_params = {}
        confidence_scores = {}
        reasoning_parts = []

        for param_name in tool_schema:
            param_values = [h.get(param_name) for h in history if param_name in h]
            if param_values:
                # Use most common value or median for numerical parameters
                if all(isinstance(v, (int, float)) for v in param_values):
                    inferred_params[param_name] = np.median(param_values)
                    confidence_scores[param_name] = min(0.8, len(param_values) / 10)
                    reasoning_parts.append(
                        f"Median {param_name} from {len(param_values)} historical uses"
                    )
                else:
                    # Use most common non-numerical value
                    from collections import Counter

                    most_common = Counter(param_values).most_common(1)[0][0]
                    inferred_params[param_name] = most_common
                    confidence_scores[param_name] = 0.7
                    reasoning_parts.append(f"Most common {param_name} from history")

        if inferred_params:
            return ParameterInference(
                tool_name=tool_name,
                inferred_parameters=inferred_params,
                confidence_scores=confidence_scores,
                inference_strategy=ParameterInferenceStrategy.HISTORICAL_PATTERNS,
                reasoning="; ".join(reasoning_parts),
            )

        return None

    def _user_preferences_inference(
        self, tool, query, tool_schema, context, user_prefs
    ) -> Optional[ParameterInference]:
        """Infer parameters based on user preferences."""
        if not user_prefs:
            return None

        inferred_params = {}
        confidence_scores = {}
        reasoning_parts = []

        # Apply user-specific defaults
        for param_name in tool_schema:
            if param_name in user_prefs:
                inferred_params[param_name] = user_prefs[param_name]
                confidence_scores[param_name] = 0.9
                reasoning_parts.append(f"User preference for {param_name}")

        # Apply tool-specific user preferences
        tool_name = tool.get_tool_name()
        if tool_name in user_prefs:
            tool_prefs = user_prefs[tool_name]
            for param_name, value in tool_prefs.items():
                if param_name in tool_schema:
                    inferred_params[param_name] = value
                    confidence_scores[param_name] = 0.95
                    reasoning_parts.append(
                        f"Tool-specific user preference for {param_name}"
                    )

        if inferred_params:
            return ParameterInference(
                tool_name=tool.get_tool_name(),
                inferred_parameters=inferred_params,
                confidence_scores=confidence_scores,
                inference_strategy=ParameterInferenceStrategy.USER_PREFERENCES,
                reasoning="; ".join(reasoning_parts),
            )

        return None

    def _combine_inference_results(
        self, tool, results: List[ParameterInference], query: str
    ) -> ParameterInference:
        """Combine results from multiple inference strategies."""
        if not results:
            return ParameterInference(
                tool_name=tool.get_tool_name(),
                inferred_parameters={},
                confidence_scores={},
                inference_strategy=ParameterInferenceStrategy.SEMANTIC_MATCHING,
                reasoning="No parameters could be inferred",
            )

        # Merge parameters with weighted confidence scores
        combined_params = {}
        combined_confidence = {}
        combined_reasoning = []

        strategy_weights = {
            ParameterInferenceStrategy.USER_PREFERENCES: 1.0,
            ParameterInferenceStrategy.CONTEXT_BASED: 0.9,
            ParameterInferenceStrategy.HISTORICAL_PATTERNS: 0.7,
            ParameterInferenceStrategy.SEMANTIC_MATCHING: 0.6,
        }

        # Collect all parameters across strategies
        all_params = set()
        for result in results:
            all_params.update(result.inferred_parameters.keys())

        # For each parameter, use the highest confidence inference
        for param in all_params:
            best_confidence = 0
            best_value = None
            best_strategy = None

            for result in results:
                if param in result.inferred_parameters:
                    weighted_confidence = result.confidence_scores.get(
                        param, 0.5
                    ) * strategy_weights.get(result.inference_strategy, 0.5)

                    if weighted_confidence > best_confidence:
                        best_confidence = weighted_confidence
                        best_value = result.inferred_parameters[param]
                        best_strategy = result.inference_strategy

            if best_value is not None:
                combined_params[param] = best_value
                combined_confidence[param] = best_confidence
                combined_reasoning.append(f"{param} from {best_strategy.value}")

        # Create fallback parameters for critical missing parameters
        fallback_params = self._create_fallback_parameters(tool, combined_params)

        return ParameterInference(
            tool_name=tool.get_tool_name(),
            inferred_parameters=combined_params,
            confidence_scores=combined_confidence,
            inference_strategy=ParameterInferenceStrategy.SEMANTIC_MATCHING,
            reasoning=(
                "; ".join(combined_reasoning)
                if combined_reasoning
                else "Combined inference"
            ),
            fallback_parameters=fallback_params,
        )

    def _create_fallback_parameters(
        self, tool, inferred_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create fallback parameters for critical missing parameters."""
        fallback = {}

        # Common neuroimaging defaults
        defaults = {
            "threshold": 0.05,
            "fwhm": 6.0,
            "tr": 2.0,
            "n_jobs": 1,
            "output_dir": "/tmp/analysis",
            "mask": None,
            "memory": "4GB",
        }

        tool_schema = self._get_tool_parameter_schema(tool)

        for param, default_value in defaults.items():
            if param in tool_schema and param not in inferred_params:
                fallback[param] = default_value

        return fallback

    def record_execution(
        self, tool_name: str, parameters: Dict[str, Any], success: bool
    ):
        """Record successful parameter usage for future inference."""
        if tool_name not in self.parameter_history:
            self.parameter_history[tool_name] = []

        # Only record successful executions
        if success:
            self.parameter_history[tool_name].append(parameters.copy())

            # Keep only recent history (last 100 executions)
            if len(self.parameter_history[tool_name]) > 100:
                self.parameter_history[tool_name] = self.parameter_history[tool_name][
                    -100:
                ]

    def update_user_preferences(self, preferences: Dict[str, Any]):
        """Update user preferences for parameter inference."""
        self.user_preferences.update(preferences)
        logger.info(f"Updated user preferences: {list(preferences.keys())}")


class ToolRecommendationEngine:
    """Advanced tool recommendation system with context awareness."""

    def __init__(self, tool_registry: ToolRegistry):
        """Initialize tool recommendation engine."""
        self.tool_registry = tool_registry
        self.usage_statistics: Dict[str, Dict[str, Any]] = {}
        self.context_patterns: Dict[str, List[str]] = {}
        self.success_rates: Dict[str, float] = {}

        logger.info("Tool recommendation engine initialized")

    def recommend_tools(
        self,
        query: str,
        context: Dict[str, Any] = None,
        max_recommendations: int = 5,
        min_confidence: float = 0.3,
    ) -> List[ToolRecommendation]:
        """
        Recommend tools based on query and context with confidence scoring.

        Args:
            query: User query
            context: Execution context
            max_recommendations: Maximum number of recommendations
            min_confidence: Minimum confidence threshold

        Returns:
            List of tool recommendations sorted by confidence
        """
        context = context or {}

        # Get all available tools
        all_tools = self.tool_registry.get_all_tools()

        recommendations = []
        for tool in all_tools:
            try:
                recommendation = self._evaluate_tool_for_query(tool, query, context)
                if recommendation and recommendation.confidence_score >= min_confidence:
                    recommendations.append(recommendation)
            except Exception as e:
                logger.warning(f"Failed to evaluate tool {tool.get_tool_name()}: {e}")

        # Sort by confidence score (descending)
        recommendations.sort(key=lambda x: x.confidence_score, reverse=True)

        # Return top recommendations
        return recommendations[:max_recommendations]

    def _evaluate_tool_for_query(
        self, tool: NeuroToolWrapper, query: str, context: Dict[str, Any]
    ) -> Optional[ToolRecommendation]:
        """Evaluate how well a tool matches the query and context."""
        tool_name = tool.get_tool_name()
        tool_description = tool.get_tool_description()

        # Calculate different confidence components
        semantic_confidence = self._calculate_semantic_confidence(
            query, tool_description
        )
        context_confidence = self._calculate_context_confidence(tool_name, context)
        historical_confidence = self._calculate_historical_confidence(tool_name, query)
        success_confidence = self.success_rates.get(tool_name, 0.5)

        # Weighted combination of confidence scores
        overall_confidence = (
            0.4 * semantic_confidence
            + 0.3 * context_confidence
            + 0.2 * historical_confidence
            + 0.1 * success_confidence
        )

        # Skip tools with very low confidence
        if overall_confidence < 0.1:
            return None

        # Generate match reasons
        match_reasons = []
        if semantic_confidence > 0.5:
            match_reasons.append("Strong semantic match with query")
        if context_confidence > 0.5:
            match_reasons.append("Suitable for current context")
        if historical_confidence > 0.5:
            match_reasons.append("Frequently used for similar queries")
        if success_confidence > 0.7:
            match_reasons.append("High historical success rate")

        # Estimate execution time and resource requirements
        estimated_time = self._estimate_execution_time(tool_name, context)
        resource_requirements = self._estimate_resource_requirements(tool_name)

        return ToolRecommendation(
            tool=tool,
            confidence_score=overall_confidence,
            match_reasons=match_reasons,
            parameter_suggestions={},  # Will be filled by parameter inference
            estimated_execution_time=estimated_time,
            resource_requirements=resource_requirements,
            success_probability=success_confidence,
        )

    def _calculate_semantic_confidence(
        self, query: str, tool_description: str
    ) -> float:
        """Calculate semantic similarity between query and tool description."""
        # Simple keyword-based matching (can be enhanced with embeddings)
        query_words = set(query.lower().split())
        desc_words = set(tool_description.lower().split())

        # Calculate Jaccard similarity
        intersection = len(query_words & desc_words)
        union = len(query_words | desc_words)

        if union == 0:
            return 0.0

        base_confidence = intersection / union

        # Boost confidence for exact matches of important terms
        important_terms = {
            "glm",
            "analysis",
            "fmri",
            "connectivity",
            "preprocessing",
            "statistical",
            "coordinate",
            "brain",
            "activation",
            "network",
        }

        query_important = query_words & important_terms
        desc_important = desc_words & important_terms

        if query_important & desc_important:
            base_confidence *= 1.5

        return min(1.0, base_confidence)

    def _calculate_context_confidence(
        self, tool_name: str, context: Dict[str, Any]
    ) -> float:
        """Calculate how well the tool fits the current context."""
        confidence = 0.5  # Base confidence

        # Check if tool is suitable for the data type
        if "data_type" in context:
            data_type = context["data_type"].lower()
            tool_name_lower = tool_name.lower()

            if data_type == "fmri" and "fmri" in tool_name_lower:
                confidence += 0.3
            elif data_type == "dwi" and (
                "dwi" in tool_name_lower or "diffusion" in tool_name_lower
            ):
                confidence += 0.3
            elif data_type == "anat" and (
                "anat" in tool_name_lower or "structural" in tool_name_lower
            ):
                confidence += 0.3

        # Check if tool is appropriate for the analysis stage
        if "analysis_stage" in context:
            stage = context["analysis_stage"].lower()
            tool_name_lower = tool_name.lower()

            if stage == "preprocessing" and "prep" in tool_name_lower:
                confidence += 0.2
            elif stage == "analysis" and any(
                term in tool_name_lower for term in ["glm", "analysis", "statistical"]
            ):
                confidence += 0.2
            elif (
                stage == "visualization"
                and "plot" in tool_name_lower
                or "viz" in tool_name_lower
            ):
                confidence += 0.2

        return min(1.0, confidence)

    def _calculate_historical_confidence(self, tool_name: str, query: str) -> float:
        """Calculate confidence based on historical usage patterns."""
        if tool_name not in self.usage_statistics:
            return 0.5

        stats = self.usage_statistics[tool_name]
        total_uses = stats.get("total_uses", 0)

        if total_uses == 0:
            return 0.5

        # Higher confidence for frequently used tools
        usage_confidence = min(1.0, total_uses / 100)

        # Check for similar queries in history
        similar_queries = stats.get("similar_queries", [])
        query_similarity = max(
            [
                self._calculate_query_similarity(query, hist_query)
                for hist_query in similar_queries
            ],
            default=0.0,
        )

        return (usage_confidence + query_similarity) / 2

    def _calculate_query_similarity(self, query1: str, query2: str) -> float:
        """Calculate similarity between two queries."""
        words1 = set(query1.lower().split())
        words2 = set(query2.lower().split())

        intersection = len(words1 & words2)
        union = len(words1 | words2)

        if union == 0:
            return 0.0

        return intersection / union

    def _estimate_execution_time(
        self, tool_name: str, context: Dict[str, Any]
    ) -> float:
        """Estimate execution time based on tool and context."""
        # Base estimates for different tool types
        time_estimates = {
            "fmriprep": 3600,  # 1 hour
            "glm": 300,  # 5 minutes
            "connectivity": 600,  # 10 minutes
            "preprocessing": 1800,  # 30 minutes
            "visualization": 60,  # 1 minute
        }

        tool_name_lower = tool_name.lower()

        for tool_type, base_time in time_estimates.items():
            if tool_type in tool_name_lower:
                # Adjust based on context
                if "num_subjects" in context:
                    # Scale with number of subjects
                    multiplier = max(1, context["num_subjects"] / 10)
                    return base_time * multiplier
                return base_time

        # Default estimate
        return 180  # 3 minutes

    def _estimate_resource_requirements(self, tool_name: str) -> List[str]:
        """Estimate resource requirements for the tool."""
        hints = get_resource_hints(tool_name)
        if hints:
            labels: List[str] = []
            cpu = hints.get("cpu")
            if cpu is not None:
                labels.append(f"CPU: {cpu}")
            mem = hints.get("mem_gb")
            if mem is not None:
                labels.append(f"Memory: {mem} GB")
            gpu = hints.get("gpu")
            if gpu:
                labels.append(f"GPU: {gpu}")
            return labels or ["Unknown"]

        requirements = []
        tool_name_lower = tool_name.lower()

        if "fmriprep" in tool_name_lower or "preprocessing" in tool_name_lower:
            requirements.extend(["High CPU", "High Memory", "Large Storage"])
        elif "glm" in tool_name_lower or "analysis" in tool_name_lower:
            requirements.extend(["Medium CPU", "Medium Memory"])
        elif "connectivity" in tool_name_lower:
            requirements.extend(["Medium CPU", "Medium Memory"])
        else:
            requirements.extend(["Low CPU", "Low Memory"])

        return requirements

    def record_tool_usage(
        self, tool_name: str, query: str, success: bool, execution_time: float
    ):
        """Record tool usage for improving recommendations."""
        if tool_name not in self.usage_statistics:
            self.usage_statistics[tool_name] = {
                "total_uses": 0,
                "successful_uses": 0,
                "similar_queries": [],
            }

        stats = self.usage_statistics[tool_name]
        stats["total_uses"] += 1

        if success:
            stats["successful_uses"] += 1

        # Update success rate
        self.success_rates[tool_name] = stats["successful_uses"] / stats["total_uses"]

        # Store similar queries (keep only recent ones)
        stats["similar_queries"].append(query)
        if len(stats["similar_queries"]) > 50:
            stats["similar_queries"] = stats["similar_queries"][-50:]


class ExecutionMonitor:
    """Comprehensive execution monitoring with real-time metrics."""

    def __init__(self):
        """Initialize execution monitor."""
        self.active_executions: Dict[str, ExecutionMetrics] = {}
        self.completed_executions: List[ExecutionMetrics] = []
        self.performance_metrics: Dict[str, Any] = {}

        logger.info("Execution monitor initialized")

    def start_execution(
        self, tool_name: str, parameters: Dict[str, Any], context: Dict[str, Any] = None
    ) -> str:
        """Start monitoring a tool execution."""
        execution_id = f"exec_{uuid4().hex[:8]}"

        metrics = ExecutionMetrics(
            execution_id=execution_id,
            tool_name=tool_name,
            start_time=time.time(),
            metadata={"parameters": parameters, "context": context or {}},
        )

        self.active_executions[execution_id] = metrics
        logger.info(f"Started monitoring execution {execution_id} for tool {tool_name}")

        return execution_id

    def end_execution(
        self,
        execution_id: str,
        success: bool,
        result: Any = None,
        error_message: str = None,
    ):
        """End monitoring of a tool execution."""
        if execution_id not in self.active_executions:
            logger.warning(f"Execution {execution_id} not found in active executions")
            return

        metrics = self.active_executions[execution_id]
        metrics.end_time = time.time()
        metrics.duration = metrics.end_time - metrics.start_time
        metrics.success = success
        metrics.error_message = error_message

        if result is not None:
            metrics.output_size = self._estimate_output_size(result)

        # Calculate confidence scores
        metrics.confidence_scores = self._calculate_execution_confidence(
            metrics, result
        )

        # Move to completed executions
        self.completed_executions.append(metrics)
        del self.active_executions[execution_id]

        logger.info(
            f"Completed monitoring execution {execution_id}: "
            f"success={success}, duration={metrics.duration:.2f}s"
        )

    def get_execution_status(self, execution_id: str) -> Optional[ExecutionMetrics]:
        """Get current status of an execution."""
        return self.active_executions.get(execution_id)

    def get_active_executions(self) -> List[ExecutionMetrics]:
        """Get all active executions."""
        return list(self.active_executions.values())

    def get_performance_summary(self) -> Dict[str, Any]:
        """Get performance summary across all executions."""
        if not self.completed_executions:
            return {"message": "No completed executions"}

        # Calculate aggregate statistics
        total_executions = len(self.completed_executions)
        successful_executions = sum(1 for e in self.completed_executions if e.success)
        average_duration = np.mean(
            [e.duration for e in self.completed_executions if e.duration]
        )

        # Tool-specific statistics
        tool_stats = {}
        for execution in self.completed_executions:
            tool = execution.tool_name
            if tool not in tool_stats:
                tool_stats[tool] = {"count": 0, "successes": 0, "avg_duration": 0}

            tool_stats[tool]["count"] += 1
            if execution.success:
                tool_stats[tool]["successes"] += 1

        # Calculate success rates and average durations
        for tool, stats in tool_stats.items():
            stats["success_rate"] = stats["successes"] / stats["count"]
            tool_executions = [
                e for e in self.completed_executions if e.tool_name == tool
            ]
            durations = [e.duration for e in tool_executions if e.duration]
            stats["avg_duration"] = np.mean(durations) if durations else 0

        return {
            "total_executions": total_executions,
            "successful_executions": successful_executions,
            "overall_success_rate": successful_executions / total_executions,
            "average_duration": average_duration,
            "tool_statistics": tool_stats,
            "active_executions": len(self.active_executions),
        }

    def _estimate_output_size(self, result: Any) -> int:
        """Estimate the size of the output result."""
        try:
            if isinstance(result, str):
                return len(result)
            elif isinstance(result, dict):
                return len(json.dumps(result, default=str))
            elif hasattr(result, "__len__"):
                return len(result)
            else:
                return len(str(result))
        except:
            return 0

    def _calculate_execution_confidence(
        self, metrics: ExecutionMetrics, result: Any
    ) -> Dict[ConfidenceMetric, float]:
        """Calculate various confidence metrics for the execution."""
        confidence_scores = {}

        # Execution confidence based on success and duration
        if metrics.success:
            # Higher confidence for reasonable execution times
            if metrics.duration and metrics.duration < 300:  # Less than 5 minutes
                confidence_scores[ConfidenceMetric.EXECUTION_CONFIDENCE] = 0.9
            elif metrics.duration and metrics.duration < 1800:  # Less than 30 minutes
                confidence_scores[ConfidenceMetric.EXECUTION_CONFIDENCE] = 0.7
            else:
                confidence_scores[ConfidenceMetric.EXECUTION_CONFIDENCE] = 0.5
        else:
            confidence_scores[ConfidenceMetric.EXECUTION_CONFIDENCE] = 0.1

        # Output quality confidence
        if result is not None and metrics.success:
            if isinstance(result, dict) and result:
                confidence_scores[ConfidenceMetric.OUTPUT_QUALITY_CONFIDENCE] = 0.8
            elif result:
                confidence_scores[ConfidenceMetric.OUTPUT_QUALITY_CONFIDENCE] = 0.6
            else:
                confidence_scores[ConfidenceMetric.OUTPUT_QUALITY_CONFIDENCE] = 0.3
        else:
            confidence_scores[ConfidenceMetric.OUTPUT_QUALITY_CONFIDENCE] = 0.0

        return confidence_scores


class EnhancedToolRegistry(ToolRegistry):
    """Enhanced tool registry with advanced inference and monitoring capabilities."""

    def __init__(self, *args, **kwargs):
        """Initialize enhanced tool registry."""
        super().__init__(*args, **kwargs)

        # Initialize advanced components
        self.parameter_inference_engine = ParameterInferenceEngine()
        self.recommendation_engine = ToolRecommendationEngine(self)
        self.execution_monitor = ExecutionMonitor()
        self.evidence_collector = EvidenceCollector()

        logger.info("Enhanced tool registry initialized with advanced capabilities")

    def get_intelligent_recommendations(
        self,
        query: str,
        context: Dict[str, Any] = None,
        user_preferences: Dict[str, Any] = None,
        max_recommendations: int = 5,
    ) -> List[ToolRecommendation]:
        """
        Get intelligent tool recommendations with parameter inference.

        Args:
            query: User query
            context: Execution context
            user_preferences: User-specific preferences
            max_recommendations: Maximum number of recommendations

        Returns:
            List of tool recommendations with inferred parameters
        """
        # Get tool recommendations
        recommendations = self.recommendation_engine.recommend_tools(
            query=query, context=context, max_recommendations=max_recommendations
        )

        # Enhance recommendations with parameter inference
        for recommendation in recommendations:
            try:
                parameter_inference = self.parameter_inference_engine.infer_parameters(
                    tool=recommendation.tool,
                    query=query,
                    context=context,
                    user_preferences=user_preferences,
                )

                recommendation.parameter_suggestions = (
                    parameter_inference.inferred_parameters
                )

                # Add parameter confidence to overall confidence
                if parameter_inference.confidence_scores:
                    avg_param_confidence = np.mean(
                        list(parameter_inference.confidence_scores.values())
                    )
                    recommendation.confidence_score = (
                        recommendation.confidence_score * 0.7
                        + avg_param_confidence * 0.3
                    )

            except Exception as e:
                logger.warning(
                    f"Failed to infer parameters for {recommendation.tool.get_tool_name()}: {e}"
                )

        return recommendations

    async def execute_with_monitoring(
        self,
        tool: NeuroToolWrapper,
        parameters: Dict[str, Any],
        context: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        Execute a tool with comprehensive monitoring and evidence collection.

        Args:
            tool: Tool to execute
            parameters: Tool parameters
            context: Execution context

        Returns:
            Execution result with monitoring information
        """
        tool_name = tool.get_tool_name()

        # Start execution monitoring
        execution_id = self.execution_monitor.start_execution(
            tool_name=tool_name, parameters=parameters, context=context
        )

        # Start evidence collection chain
        evidence_chain = self.evidence_collector.start_chain(
            description=f"Tool execution: {tool_name}"
        )

        # Collect tool evidence
        self.evidence_collector.collect_tool_execution(
            tool_name=tool_name,
            parameters=parameters,
            execution_time=None,
            success=False,  # Will be updated
        )

        try:
            # Execute the tool
            start_time = time.time()
            result = tool.run(**parameters)
            execution_time = time.time() - start_time

            # End monitoring with success
            self.execution_monitor.end_execution(
                execution_id=execution_id, success=True, result=result
            )

            # Update evidence with success
            self.evidence_collector.collect(
                type=EvidenceType.RESULT,
                source=tool_name,
                content={
                    "result": result,
                    "execution_time": execution_time,
                    "parameters": parameters,
                },
                confidence=ConfidenceLevel.HIGH,
            )

            # Collect output artifact files (best-effort)
            try:
                data = result.get("data") if isinstance(result, dict) else None
                if isinstance(data, dict) and data.get("outputs"):
                    self.evidence_collector.collect_output_files(
                        tool_name, data["outputs"]
                    )
            except Exception as e:
                logger.warning(
                    f"Failed to collect output artifacts for {tool_name}: {e}"
                )

            # Record successful execution for future inference
            self.parameter_inference_engine.record_execution(
                tool_name, parameters, True
            )
            self.recommendation_engine.record_tool_usage(
                tool_name, "", True, execution_time
            )

            return {
                "status": "success",
                "result": result,
                "execution_id": execution_id,
                "execution_time": execution_time,
                "evidence_chain_id": evidence_chain.chain_id,
            }

        except Exception as e:
            # End monitoring with failure
            self.execution_monitor.end_execution(
                execution_id=execution_id, success=False, error_message=str(e)
            )

            # Collect error evidence
            self.evidence_collector.collect(
                type=EvidenceType.RESULT,
                source=tool_name,
                content={"error": str(e), "parameters": parameters},
                confidence=ConfidenceLevel.HIGH,
            )

            # Record failed execution
            self.parameter_inference_engine.record_execution(
                tool_name, parameters, False
            )
            self.recommendation_engine.record_tool_usage(tool_name, "", False, 0)

            return {
                "status": "error",
                "error": str(e),
                "execution_id": execution_id,
                "evidence_chain_id": evidence_chain.chain_id,
            }

        finally:
            # End evidence chain
            self.evidence_collector.end_chain()

    def get_registry_statistics(self) -> Dict[str, Any]:
        """Get comprehensive statistics about the registry."""
        base_stats = self.get_tool_info()

        # Add advanced statistics
        performance_summary = self.execution_monitor.get_performance_summary()

        return {
            **base_stats,
            "performance_summary": performance_summary,
            "parameter_inference_history": {
                tool: len(history)
                for tool, history in self.parameter_inference_engine.parameter_history.items()
            },
            "recommendation_statistics": {
                tool: stats["total_uses"]
                for tool, stats in self.recommendation_engine.usage_statistics.items()
            },
            "evidence_summary": self.evidence_collector.generate_report()["summary"],
        }
