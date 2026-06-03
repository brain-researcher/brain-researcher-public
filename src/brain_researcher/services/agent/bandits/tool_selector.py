"""Bandit-based tool selector for neuroimaging agent."""

import numpy as np
import logging
from typing import Dict, List, Optional, Tuple, Any, Union
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import json

from .contextual_bandit import ContextualBandit, BanditAction, Context, BanditFeedback
from .thompson_sampling import ThompsonSampling
from .ucb_algorithm import LinUCB, UCBAlgorithm

logger = logging.getLogger(__name__)


class TaskType(Enum):
    PREPROCESSING = "preprocessing"
    GLM_ANALYSIS = "glm_analysis"
    CONTRAST_ANALYSIS = "contrast_analysis"
    STATISTICAL_TEST = "statistical_test"
    VISUALIZATION = "visualization"
    QUALITY_CHECK = "quality_check"
    DATA_EXPORT = "data_export"
    PARAMETER_OPTIMIZATION = "parameter_optimization"


@dataclass
class ToolDefinition:
    """Definition of a neuroimaging tool."""
    name: str
    description: str
    task_types: List[TaskType]
    parameters: Dict[str, Any]
    expected_execution_time: float
    resource_requirements: Dict[str, float]
    cost_estimate: float
    quality_score: float = 0.8
    reliability_score: float = 0.9


@dataclass
class TaskContext:
    """Context for tool selection."""
    task_type: TaskType
    data_size: float  # MB
    data_complexity: float  # 0-1 scale
    available_memory: float  # MB
    available_cpu_cores: int
    time_constraints: float  # seconds
    quality_requirements: float  # 0-1 scale
    user_expertise: float  # 0-1 scale
    previous_tools_used: List[str]
    session_history: List[Dict[str, Any]]
    user_preferences: Dict[str, Any]


class FeatureExtractor:
    """Extracts features from task context for bandit algorithms."""

    def __init__(self):
        self.feature_names = [
            "task_type_preprocessing",
            "task_type_glm_analysis",
            "task_type_contrast_analysis",
            "task_type_statistical_test",
            "task_type_visualization",
            "task_type_quality_check",
            "task_type_data_export",
            "task_type_parameter_optimization",
            "data_size_normalized",
            "data_complexity",
            "memory_ratio",
            "cpu_cores_normalized",
            "time_pressure",
            "quality_requirements",
            "user_expertise",
            "session_length",
            "recent_failures",
            "tool_diversity"
        ]

        self.feature_dim = len(self.feature_names)

    def extract_features(self, task_context: TaskContext) -> np.ndarray:
        """Extract feature vector from task context."""
        features = np.zeros(self.feature_dim)

        # Task type (one-hot encoding)
        task_type_features = {
            TaskType.PREPROCESSING: 0,
            TaskType.GLM_ANALYSIS: 1,
            TaskType.CONTRAST_ANALYSIS: 2,
            TaskType.STATISTICAL_TEST: 3,
            TaskType.VISUALIZATION: 4,
            TaskType.QUALITY_CHECK: 5,
            TaskType.DATA_EXPORT: 6,
            TaskType.PARAMETER_OPTIMIZATION: 7
        }

        if task_context.task_type in task_type_features:
            features[task_type_features[task_context.task_type]] = 1.0

        # Normalized data size (log scale, normalized to 0-1)
        features[8] = min(1.0, np.log(max(1, task_context.data_size)) / np.log(10000))  # 10GB max

        # Data complexity
        features[9] = task_context.data_complexity

        # Memory ratio (available / required)
        estimated_memory_need = task_context.data_size * 2  # Rough estimate
        features[10] = min(1.0, task_context.available_memory / max(1, estimated_memory_need))

        # CPU cores normalized
        features[11] = min(1.0, task_context.available_cpu_cores / 32)  # 32 cores max

        # Time pressure (inverse of available time)
        features[12] = max(0, 1.0 - task_context.time_constraints / 3600)  # 1 hour reference

        # Quality requirements
        features[13] = task_context.quality_requirements

        # User expertise
        features[14] = task_context.user_expertise

        # Session length (normalized)
        features[15] = min(1.0, len(task_context.session_history) / 20)

        # Recent failures rate
        if len(task_context.session_history) > 0:
            recent_failures = sum(
                1 for item in task_context.session_history[-10:]
                if not item.get("success", True)
            )
            features[16] = recent_failures / min(10, len(task_context.session_history))
        else:
            features[16] = 0.0

        # Tool diversity (unique tools used recently)
        if len(task_context.previous_tools_used) > 0:
            unique_tools = len(set(task_context.previous_tools_used[-10:]))
            features[17] = min(1.0, unique_tools / 10)
        else:
            features[17] = 0.0

        return features

    def get_feature_names(self) -> List[str]:
        """Get list of feature names."""
        return self.feature_names.copy()


class BanditToolSelector:
    """Tool selector using contextual bandits."""

    def __init__(
        self,
        tools: List[ToolDefinition],
        algorithm: str = "thompson_sampling",
        algorithm_params: Optional[Dict[str, Any]] = None
    ):
        self.tools = tools
        self.tool_name_to_id = {tool.name: i for i, tool in enumerate(tools)}

        # Create bandit actions
        bandit_actions = []
        for i, tool in enumerate(tools):
            action = BanditAction(
                id=i,
                name=tool.name,
                description=tool.description,
                parameters=tool.parameters,
                cost=tool.cost_estimate,
                expected_time=tool.expected_execution_time
            )
            bandit_actions.append(action)

        # Initialize feature extractor
        self.feature_extractor = FeatureExtractor()
        context_dim = self.feature_extractor.feature_dim

        # Initialize bandit algorithm
        algorithm_params = algorithm_params or {}

        if algorithm == "thompson_sampling":
            self.bandit = ThompsonSampling(
                n_arms=len(tools),
                context_dim=context_dim,
                actions=bandit_actions,
                **algorithm_params
            )
        elif algorithm == "linucb":
            self.bandit = LinUCB(
                n_arms=len(tools),
                context_dim=context_dim,
                actions=bandit_actions,
                **algorithm_params
            )
        elif algorithm == "ucb":
            self.bandit = UCBAlgorithm(
                n_arms=len(tools),
                context_dim=context_dim,
                actions=bandit_actions,
                **algorithm_params
            )
        else:
            raise ValueError(f"Unknown algorithm: {algorithm}")

        self.algorithm_name = algorithm

        # Performance tracking
        self.selection_history = []
        self.performance_by_task = {task_type: [] for task_type in TaskType}

        logger.info(f"Initialized BanditToolSelector with {len(tools)} tools using {algorithm}")

    def select_tool(
        self,
        task_context: TaskContext,
        available_tools: Optional[List[str]] = None,
        exploit: bool = False,
        return_ranking: bool = False
    ) -> Union[str, Tuple[str, List[Tuple[str, float]]]]:
        """Select best tool for given task context.

        Args:
            task_context: Current task context
            available_tools: List of available tool names (None = all tools)
            exploit: If True, select greedily without exploration
            return_ranking: If True, return tool ranking as well

        Returns:
            Selected tool name, optionally with ranking
        """
        # Extract features from context
        context_vector = self.feature_extractor.extract_features(task_context)
        context_obj = Context(
            features=context_vector,
            metadata={
                "task_type": task_context.task_type.value,
                "data_size": task_context.data_size,
                "time_constraints": task_context.time_constraints,
                "quality_requirements": task_context.quality_requirements
            },
            timestamp=datetime.utcnow()
        )

        # Filter available tools
        if available_tools:
            available_arm_ids = [
                self.tool_name_to_id[tool_name]
                for tool_name in available_tools
                if tool_name in self.tool_name_to_id
            ]
        else:
            # Check tool compatibility with task type
            available_arm_ids = []
            for i, tool in enumerate(self.tools):
                if (task_context.task_type in tool.task_types or
                    len(tool.task_types) == 0):  # Universal tools
                    available_arm_ids.append(i)

        if not available_arm_ids:
            raise ValueError("No compatible tools available for this task")

        # Select tool using bandit
        selected_arm_id, selection_info = self.bandit.select_arm(
            context_obj,
            available_arms=available_arm_ids,
            exploit=exploit
        )

        selected_tool = self.tools[selected_arm_id]

        # Store selection for tracking
        selection_record = {
            "timestamp": datetime.utcnow(),
            "task_context": task_context,
            "selected_tool": selected_tool.name,
            "available_tools": [self.tools[i].name for i in available_arm_ids],
            "selection_info": selection_info,
            "exploit": exploit
        }
        self.selection_history.append(selection_record)

        logger.debug(f"Selected tool '{selected_tool.name}' for {task_context.task_type.value} task")

        if return_ranking:
            # Generate tool ranking
            ranking = self._rank_tools(context_obj, available_arm_ids)
            return selected_tool.name, ranking

        return selected_tool.name

    def update_performance(
        self,
        task_context: TaskContext,
        tool_name: str,
        performance_metrics: Dict[str, Any],
        execution_time: float,
        success: bool
    ) -> None:
        """Update tool performance based on execution results.

        Args:
            task_context: Task context used for selection
            tool_name: Name of tool that was used
            performance_metrics: Dict with performance metrics
            execution_time: Actual execution time
            success: Whether execution was successful
        """
        if tool_name not in self.tool_name_to_id:
            logger.warning(f"Unknown tool: {tool_name}")
            return

        tool_id = self.tool_name_to_id[tool_name]

        # Calculate reward
        reward = self._calculate_reward(
            task_context, performance_metrics, execution_time, success
        )

        # Extract context features
        context_vector = self.feature_extractor.extract_features(task_context)
        context_obj = Context(
            features=context_vector,
            metadata={
                "task_type": task_context.task_type.value,
                "tool_name": tool_name
            },
            timestamp=datetime.utcnow()
        )

        # Create feedback object
        feedback = BanditFeedback(
            context=context_obj,
            action_id=tool_id,
            reward=reward,
            execution_time=execution_time,
            success=success,
            metadata=performance_metrics,
            timestamp=datetime.utcnow()
        )

        # Update bandit
        self.bandit.update(context_obj, tool_id, reward, feedback)

        # Track performance by task type
        self.performance_by_task[task_context.task_type].append({
            "tool": tool_name,
            "reward": reward,
            "success": success,
            "execution_time": execution_time,
            "timestamp": datetime.utcnow()
        })

        logger.debug(f"Updated performance for tool '{tool_name}' with reward {reward:.3f}")

    def get_tool_recommendations(
        self,
        task_context: TaskContext,
        top_k: int = 3
    ) -> List[Dict[str, Any]]:
        """Get top-k tool recommendations with explanations.

        Args:
            task_context: Task context
            top_k: Number of recommendations to return

        Returns:
            List of tool recommendations with metadata
        """
        context_vector = self.feature_extractor.extract_features(task_context)
        context_obj = Context(features=context_vector, metadata={}, timestamp=datetime.utcnow())

        # Get compatible tools
        compatible_tools = []
        for i, tool in enumerate(self.tools):
            if (task_context.task_type in tool.task_types or
                len(tool.task_types) == 0):
                compatible_tools.append(i)

        # Predict rewards for compatible tools
        if hasattr(self.bandit, 'predict_rewards'):
            predicted_rewards = self.bandit.predict_rewards(
                context_vector.reshape(1, -1),
                arms=compatible_tools
            )[0]
        else:
            # Fallback: use current estimates
            predicted_rewards = []
            for tool_id in compatible_tools:
                stats = self.bandit.get_arm_statistics(tool_id)
                predicted_rewards.append(stats["average_reward"])
            predicted_rewards = np.array(predicted_rewards)

        # Get uncertainty estimates if available
        uncertainties = None
        if hasattr(self.bandit, 'get_uncertainty_estimates'):
            try:
                uncertainties = self.bandit.get_uncertainty_estimates(
                    context_vector.reshape(1, -1),
                    arms=compatible_tools
                )[0]
            except:
                pass

        # Rank tools by predicted reward
        tool_rankings = list(zip(compatible_tools, predicted_rewards))
        tool_rankings.sort(key=lambda x: x[1], reverse=True)

        recommendations = []
        for i, (tool_id, predicted_reward) in enumerate(tool_rankings[:top_k]):
            tool = self.tools[tool_id]
            stats = self.bandit.get_arm_statistics(tool_id)

            # Generate explanation
            explanation = self._generate_explanation(
                tool, task_context, predicted_reward, stats
            )

            recommendation = {
                "rank": i + 1,
                "tool_name": tool.name,
                "description": tool.description,
                "predicted_reward": float(predicted_reward),
                "confidence": float(stats["confidence"]),
                "success_rate": float(stats["success_rate"]),
                "avg_execution_time": float(stats["avg_execution_time"]),
                "total_uses": int(stats["total_pulls"]),
                "explanation": explanation,
                "estimated_time": tool.expected_execution_time,
                "resource_requirements": tool.resource_requirements
            }

            if uncertainties is not None:
                uncertainty_idx = compatible_tools.index(tool_id)
                recommendation["uncertainty"] = float(uncertainties[uncertainty_idx])

            recommendations.append(recommendation)

        return recommendations

    def get_performance_summary(
        self,
        task_type: Optional[TaskType] = None,
        time_window_hours: int = 24
    ) -> Dict[str, Any]:
        """Get performance summary for tool selection.

        Args:
            task_type: Specific task type to analyze (None = all)
            time_window_hours: Time window for recent performance

        Returns:
            Performance summary dictionary
        """
        cutoff_time = datetime.utcnow() - timedelta(hours=time_window_hours)

        # Filter recent performance data
        recent_performance = []

        if task_type:
            task_performance = self.performance_by_task.get(task_type, [])
        else:
            task_performance = []
            for performances in self.performance_by_task.values():
                task_performance.extend(performances)

        for perf in task_performance:
            if perf["timestamp"] >= cutoff_time:
                recent_performance.append(perf)

        if not recent_performance:
            return {"message": "No recent performance data available"}

        # Calculate overall statistics
        total_selections = len(recent_performance)
        successful_selections = sum(1 for p in recent_performance if p["success"])
        success_rate = successful_selections / total_selections

        avg_reward = np.mean([p["reward"] for p in recent_performance])
        avg_execution_time = np.mean([p["execution_time"] for p in recent_performance])

        # Tool-specific statistics
        tool_stats = {}
        for perf in recent_performance:
            tool_name = perf["tool"]
            if tool_name not in tool_stats:
                tool_stats[tool_name] = {
                    "uses": 0,
                    "successes": 0,
                    "total_reward": 0.0,
                    "total_time": 0.0
                }

            tool_stats[tool_name]["uses"] += 1
            if perf["success"]:
                tool_stats[tool_name]["successes"] += 1
            tool_stats[tool_name]["total_reward"] += perf["reward"]
            tool_stats[tool_name]["total_time"] += perf["execution_time"]

        # Calculate derived statistics
        for tool_name, stats in tool_stats.items():
            stats["success_rate"] = stats["successes"] / stats["uses"]
            stats["avg_reward"] = stats["total_reward"] / stats["uses"]
            stats["avg_time"] = stats["total_time"] / stats["uses"]

        # Bandit algorithm statistics
        bandit_stats = self.bandit.get_overall_statistics()

        summary = {
            "time_window_hours": time_window_hours,
            "task_type": task_type.value if task_type else "all",
            "total_selections": total_selections,
            "success_rate": success_rate,
            "average_reward": avg_reward,
            "average_execution_time": avg_execution_time,
            "tool_statistics": tool_stats,
            "bandit_statistics": bandit_stats,
            "algorithm": self.algorithm_name,
            "total_tools": len(self.tools)
        }

        # Feature importance if available
        if hasattr(self.bandit, 'get_feature_importance'):
            importance = self.bandit.get_feature_importance()
            feature_names = self.feature_extractor.get_feature_names()

            feature_importance = {}
            for i, name in enumerate(feature_names):
                if f"feature_{i}" in importance:
                    feature_importance[name] = importance[f"feature_{i}"]

            summary["feature_importance"] = feature_importance

        return summary

    def save_state(self, filepath: str) -> None:
        """Save tool selector state."""
        # Save bandit state
        self.bandit.save_state(f"{filepath}_bandit.json")

        # Save tool selector specific state
        state = {
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "task_types": [tt.value for tt in tool.task_types],
                    "parameters": tool.parameters,
                    "expected_execution_time": tool.expected_execution_time,
                    "resource_requirements": tool.resource_requirements,
                    "cost_estimate": tool.cost_estimate,
                    "quality_score": tool.quality_score,
                    "reliability_score": tool.reliability_score
                }
                for tool in self.tools
            ],
            "algorithm_name": self.algorithm_name,
            "performance_by_task": {
                task_type.value: [
                    {
                        **perf,
                        "timestamp": perf["timestamp"].isoformat()
                    }
                    for perf in performances
                ]
                for task_type, performances in self.performance_by_task.items()
            }
        }

        with open(f"{filepath}_selector.json", 'w') as f:
            json.dump(state, f, indent=2)

        logger.info(f"Saved tool selector state to {filepath}")

    def load_state(self, filepath: str) -> None:
        """Load tool selector state."""
        # Load selector state
        with open(f"{filepath}_selector.json", 'r') as f:
            state = json.load(f)

        # Reconstruct tools
        self.tools = []
        for tool_data in state["tools"]:
            tool = ToolDefinition(
                name=tool_data["name"],
                description=tool_data["description"],
                task_types=[TaskType(tt) for tt in tool_data["task_types"]],
                parameters=tool_data["parameters"],
                expected_execution_time=tool_data["expected_execution_time"],
                resource_requirements=tool_data["resource_requirements"],
                cost_estimate=tool_data["cost_estimate"],
                quality_score=tool_data.get("quality_score", 0.8),
                reliability_score=tool_data.get("reliability_score", 0.9)
            )
            self.tools.append(tool)

        self.tool_name_to_id = {tool.name: i for i, tool in enumerate(self.tools)}
        self.algorithm_name = state["algorithm_name"]

        # Reconstruct performance history
        self.performance_by_task = {}
        for task_type_str, performances in state["performance_by_task"].items():
            task_type = TaskType(task_type_str)
            self.performance_by_task[task_type] = []

            for perf in performances:
                perf["timestamp"] = datetime.fromisoformat(perf["timestamp"])
                self.performance_by_task[task_type].append(perf)

        # Load bandit state
        self.bandit.load_state(f"{filepath}_bandit.json")

        logger.info(f"Loaded tool selector state from {filepath}")

    # Private methods

    def _calculate_reward(
        self,
        task_context: TaskContext,
        performance_metrics: Dict[str, Any],
        execution_time: float,
        success: bool
    ) -> float:
        """Calculate reward for tool performance."""
        if not success:
            return -1.0  # Failure penalty

        reward = 1.0  # Base success reward

        # Time efficiency bonus/penalty
        expected_time = performance_metrics.get("expected_time", 300)  # 5 min default
        time_ratio = execution_time / expected_time

        if time_ratio < 0.8:  # Faster than expected
            reward += 0.5 * (0.8 - time_ratio)
        elif time_ratio > 1.2:  # Slower than expected
            reward -= 0.3 * (time_ratio - 1.2)

        # Quality bonus
        quality_score = performance_metrics.get("quality_score", 0.7)
        if quality_score > task_context.quality_requirements:
            quality_bonus = (quality_score - task_context.quality_requirements) * 2.0
            reward += quality_bonus

        # Resource efficiency
        memory_used = performance_metrics.get("memory_used", 0)
        if memory_used > 0:
            memory_efficiency = min(1.0, task_context.available_memory / memory_used)
            reward += 0.2 * memory_efficiency

        # User satisfaction
        user_satisfaction = performance_metrics.get("user_satisfaction", 0.7)
        reward += (user_satisfaction - 0.5) * 1.5

        return reward

    def _rank_tools(
        self,
        context: Context,
        available_arm_ids: List[int]
    ) -> List[Tuple[str, float]]:
        """Rank available tools by expected performance."""
        rankings = []

        for arm_id in available_arm_ids:
            tool = self.tools[arm_id]

            # Get expected reward
            if hasattr(self.bandit, 'predict_rewards'):
                expected_reward = self.bandit.predict_rewards(
                    context.features.reshape(1, -1),
                    arms=[arm_id]
                )[0, 0]
            else:
                stats = self.bandit.get_arm_statistics(arm_id)
                expected_reward = stats["average_reward"]

            rankings.append((tool.name, float(expected_reward)))

        # Sort by expected reward (descending)
        rankings.sort(key=lambda x: x[1], reverse=True)

        return rankings

    def _generate_explanation(
        self,
        tool: ToolDefinition,
        task_context: TaskContext,
        predicted_reward: float,
        stats: Dict[str, Any]
    ) -> str:
        """Generate human-readable explanation for tool recommendation."""
        explanations = []

        # Success rate explanation
        if stats["success_rate"] > 0.8:
            explanations.append(f"high success rate ({stats['success_rate']:.1%})")
        elif stats["success_rate"] > 0.6:
            explanations.append(f"moderate success rate ({stats['success_rate']:.1%})")
        else:
            explanations.append(f"lower success rate ({stats['success_rate']:.1%})")

        # Experience explanation
        if stats["total_pulls"] > 50:
            explanations.append("well-tested")
        elif stats["total_pulls"] > 10:
            explanations.append("moderately tested")
        else:
            explanations.append("limited testing")

        # Performance explanation
        if predicted_reward > 0.5:
            explanations.append("expected high performance")
        elif predicted_reward > 0:
            explanations.append("expected adequate performance")
        else:
            explanations.append("uncertain performance")

        # Task compatibility
        if task_context.task_type in tool.task_types:
            explanations.append(f"optimized for {task_context.task_type.value}")

        # Resource fit
        memory_needed = task_context.data_size * 2
        if memory_needed <= task_context.available_memory:
            explanations.append("good resource fit")
        else:
            explanations.append("may require more memory")

        return "; ".join(explanations)