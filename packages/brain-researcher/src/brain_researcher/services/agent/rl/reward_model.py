"""Reward model for neuroimaging tasks and RL training."""

import numpy as np
import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import json

logger = logging.getLogger(__name__)


class TaskType(Enum):
    PREPROCESSING = "preprocessing"
    GLM_ANALYSIS = "glm_analysis"
    CONTRAST_ANALYSIS = "contrast_analysis"
    STATISTICAL_TEST = "statistical_test"
    VISUALIZATION = "visualization"
    QUALITY_CHECK = "quality_check"
    DATA_EXPORT = "data_export"
    OPTIMIZATION = "optimization"


class RewardComponent(Enum):
    SUCCESS = "success"
    EFFICIENCY = "efficiency"
    QUALITY = "quality"
    ROBUSTNESS = "robustness"
    USER_SATISFACTION = "user_satisfaction"
    COST = "cost"
    INTERPRETABILITY = "interpretability"


@dataclass
class TaskReward:
    task_type: TaskType
    base_reward: float
    time_penalty_rate: float  # penalty per second over expected time
    quality_bonus_rate: float  # bonus per quality point above threshold
    error_penalty: float  # penalty per error
    resource_penalty_rate: float  # penalty per resource unit over limit


@dataclass
class RewardMetrics:
    execution_time: float
    success: bool
    quality_score: float
    error_count: int
    resource_usage: Dict[str, float]
    user_feedback: Optional[Dict[str, Any]] = None
    intermediate_results: Optional[List[Dict]] = None


class NeuroimagingRewardModel:
    """Comprehensive reward model for neuroimaging analysis tasks."""
    
    def __init__(self):
        # Task-specific reward configurations
        self.task_rewards = self._initialize_task_rewards()
        
        # Global reward weights
        self.component_weights = {
            RewardComponent.SUCCESS: 1.0,
            RewardComponent.EFFICIENCY: 0.3,
            RewardComponent.QUALITY: 0.8,
            RewardComponent.ROBUSTNESS: 0.4,
            RewardComponent.USER_SATISFACTION: 0.6,
            RewardComponent.COST: -0.2,
            RewardComponent.INTERPRETABILITY: 0.3
        }
        
        # Baseline expectations (learned from historical data)
        self.baselines = {
            TaskType.PREPROCESSING: {
                "expected_time": 300,  # 5 minutes
                "quality_threshold": 0.8,
                "max_errors": 2,
                "resource_limit": {"memory_mb": 2000, "cpu_percent": 50}
            },
            TaskType.GLM_ANALYSIS: {
                "expected_time": 600,  # 10 minutes
                "quality_threshold": 0.85,
                "max_errors": 1,
                "resource_limit": {"memory_mb": 4000, "cpu_percent": 70}
            },
            TaskType.CONTRAST_ANALYSIS: {
                "expected_time": 120,  # 2 minutes
                "quality_threshold": 0.9,
                "max_errors": 0,
                "resource_limit": {"memory_mb": 1000, "cpu_percent": 30}
            },
            TaskType.STATISTICAL_TEST: {
                "expected_time": 60,   # 1 minute
                "quality_threshold": 0.95,
                "max_errors": 0,
                "resource_limit": {"memory_mb": 500, "cpu_percent": 20}
            },
            TaskType.VISUALIZATION: {
                "expected_time": 180,  # 3 minutes
                "quality_threshold": 0.7,
                "max_errors": 1,
                "resource_limit": {"memory_mb": 1500, "cpu_percent": 40}
            }
        }
        
        # Adaptive parameters
        self.adaptation_rate = 0.01
        self.reward_history = []
        self.performance_stats = {}
        
    def calculate_reward(
        self,
        task_type: str,
        metrics: RewardMetrics,
        context: Optional[Dict[str, Any]] = None
    ) -> Tuple[float, Dict[str, float]]:
        """Calculate comprehensive reward for a task execution."""
        try:
            task_type_enum = TaskType(task_type.lower())
        except ValueError:
            logger.warning(f"Unknown task type: {task_type}, using default")
            task_type_enum = TaskType.PREPROCESSING
        
        context = context or {}
        task_config = self.task_rewards[task_type_enum]
        baseline = self.baselines[task_type_enum]
        
        reward_components = {}
        
        # 1. Success/Failure Reward
        if metrics.success:
            reward_components[RewardComponent.SUCCESS.value] = task_config.base_reward
        else:
            reward_components[RewardComponent.SUCCESS.value] = -task_config.base_reward
        
        # 2. Efficiency Reward (time-based)
        expected_time = baseline["expected_time"]
        if metrics.execution_time <= expected_time:
            # Bonus for being faster than expected
            time_ratio = metrics.execution_time / expected_time
            efficiency_bonus = (1.0 - time_ratio) * task_config.base_reward * 0.5
            reward_components[RewardComponent.EFFICIENCY.value] = efficiency_bonus
        else:
            # Penalty for being slower
            excess_time = metrics.execution_time - expected_time
            time_penalty = excess_time * task_config.time_penalty_rate
            reward_components[RewardComponent.EFFICIENCY.value] = -time_penalty
        
        # 3. Quality Reward
        quality_threshold = baseline["quality_threshold"]
        if metrics.quality_score > quality_threshold:
            quality_bonus = (metrics.quality_score - quality_threshold) * task_config.quality_bonus_rate
            reward_components[RewardComponent.QUALITY.value] = quality_bonus
        else:
            # Penalty for low quality
            quality_penalty = (quality_threshold - metrics.quality_score) * task_config.quality_bonus_rate
            reward_components[RewardComponent.QUALITY.value] = -quality_penalty
        
        # 4. Robustness Reward (error-based)
        max_errors = baseline["max_errors"]
        if metrics.error_count <= max_errors:
            reward_components[RewardComponent.ROBUSTNESS.value] = 0.1 * task_config.base_reward
        else:
            excess_errors = metrics.error_count - max_errors
            error_penalty = excess_errors * task_config.error_penalty
            reward_components[RewardComponent.ROBUSTNESS.value] = -error_penalty
        
        # 5. Resource Efficiency
        resource_penalty = 0.0
        resource_limit = baseline["resource_limit"]
        
        for resource_type, usage in metrics.resource_usage.items():
            if resource_type in resource_limit:
                limit = resource_limit[resource_type]
                if usage > limit:
                    excess_ratio = (usage - limit) / limit
                    resource_penalty += excess_ratio * task_config.resource_penalty_rate
        
        reward_components[RewardComponent.COST.value] = -resource_penalty
        
        # 6. User Satisfaction
        if metrics.user_feedback:
            satisfaction = metrics.user_feedback.get("satisfaction_score", 0.5)
            # Scale from [0,1] to [-0.5, 0.5]
            satisfaction_reward = (satisfaction - 0.5) * task_config.base_reward
            reward_components[RewardComponent.USER_SATISFACTION.value] = satisfaction_reward
            
            # Additional feedback-based adjustments
            if metrics.user_feedback.get("helpful", False):
                reward_components[RewardComponent.INTERPRETABILITY.value] = 0.2 * task_config.base_reward
            
            if metrics.user_feedback.get("accurate", False):
                reward_components[RewardComponent.QUALITY.value] += 0.1 * task_config.base_reward
        else:
            reward_components[RewardComponent.USER_SATISFACTION.value] = 0.0
            reward_components[RewardComponent.INTERPRETABILITY.value] = 0.0
        
        # 7. Progressive rewards for multi-step tasks
        if metrics.intermediate_results:
            progress_reward = self._calculate_progress_reward(
                metrics.intermediate_results, task_type_enum
            )
            reward_components["progress"] = progress_reward
        
        # Apply component weights and calculate total
        total_reward = 0.0
        weighted_components = {}
        
        for component, value in reward_components.items():
            if component in [rc.value for rc in RewardComponent]:
                component_enum = RewardComponent(component)
                weight = self.component_weights[component_enum]
                weighted_value = value * weight
                weighted_components[component] = weighted_value
                total_reward += weighted_value
            else:
                # Non-standard components (like progress)
                weighted_components[component] = value
                total_reward += value
        
        # Context-based adjustments
        total_reward = self._apply_context_adjustments(total_reward, context, task_type_enum)
        
        # Store for adaptation
        self._record_reward(task_type_enum, total_reward, metrics)
        
        return total_reward, weighted_components
    
    def update_baselines(self, recent_performance: List[Dict[str, Any]]) -> None:
        """Update baseline expectations based on recent performance data."""
        if not recent_performance:
            return
        
        # Group by task type
        task_performance = {}
        for perf in recent_performance:
            task_type = perf.get("task_type")
            if task_type:
                try:
                    task_type_enum = TaskType(task_type.lower())
                    if task_type_enum not in task_performance:
                        task_performance[task_type_enum] = []
                    task_performance[task_type_enum].append(perf)
                except ValueError:
                    continue
        
        # Update baselines for each task type
        for task_type, performances in task_performance.items():
            if len(performances) < 5:  # Need minimum data
                continue
            
            # Update expected time (75th percentile)
            times = [p.get("execution_time", 0) for p in performances if p.get("execution_time")]
            if times:
                self.baselines[task_type]["expected_time"] = np.percentile(times, 75)
            
            # Update quality threshold (25th percentile)
            qualities = [p.get("quality_score", 0) for p in performances if p.get("quality_score")]
            if qualities:
                self.baselines[task_type]["quality_threshold"] = np.percentile(qualities, 25)
            
            # Update resource limits (90th percentile)
            memory_usage = [p.get("memory_usage", 0) for p in performances if p.get("memory_usage")]
            if memory_usage:
                self.baselines[task_type]["resource_limit"]["memory_mb"] = np.percentile(memory_usage, 90)
            
        logger.info(f"Updated baselines for {len(task_performance)} task types")
    
    def get_expected_reward(
        self,
        task_type: str,
        estimated_metrics: Dict[str, float],
        context: Optional[Dict[str, Any]] = None
    ) -> float:
        """Get expected reward for a task given estimated performance."""
        try:
            task_type_enum = TaskType(task_type.lower())
        except ValueError:
            task_type_enum = TaskType.PREPROCESSING
        
        # Create synthetic metrics
        metrics = RewardMetrics(
            execution_time=estimated_metrics.get("execution_time", 0),
            success=estimated_metrics.get("success_probability", 0.8) > 0.5,
            quality_score=estimated_metrics.get("quality_score", 0.7),
            error_count=int(estimated_metrics.get("error_count", 0)),
            resource_usage=estimated_metrics.get("resource_usage", {}),
            user_feedback={"satisfaction_score": estimated_metrics.get("satisfaction", 0.7)}
        )
        
        expected_reward, _ = self.calculate_reward(task_type, metrics, context)
        return expected_reward
    
    def optimize_task_parameters(
        self,
        task_type: str,
        parameter_ranges: Dict[str, Tuple[float, float]],
        num_samples: int = 100
    ) -> Tuple[Dict[str, float], float]:
        """Find optimal parameters for maximizing expected reward."""
        try:
            task_type_enum = TaskType(task_type.lower())
        except ValueError:
            task_type_enum = TaskType.PREPROCESSING
        
        best_params = {}
        best_reward = float('-inf')
        
        for _ in range(num_samples):
            # Sample random parameters
            params = {}
            for param_name, (min_val, max_val) in parameter_ranges.items():
                params[param_name] = np.random.uniform(min_val, max_val)
            
            # Estimate metrics based on parameters
            estimated_metrics = self._estimate_metrics_from_params(params, task_type_enum)
            
            # Calculate expected reward
            expected_reward = self.get_expected_reward(task_type, estimated_metrics)
            
            if expected_reward > best_reward:
                best_reward = expected_reward
                best_params = params.copy()
        
        return best_params, best_reward
    
    def get_reward_sensitivity(
        self,
        task_type: str,
        base_metrics: Dict[str, float],
        perturbation_size: float = 0.1
    ) -> Dict[str, float]:
        """Analyze sensitivity of reward to different metrics."""
        base_reward = self.get_expected_reward(task_type, base_metrics)
        
        sensitivities = {}
        
        for metric_name, base_value in base_metrics.items():
            if isinstance(base_value, (int, float)):
                # Perturb metric
                perturbed_metrics = base_metrics.copy()
                perturbed_metrics[metric_name] = base_value * (1 + perturbation_size)
                
                perturbed_reward = self.get_expected_reward(task_type, perturbed_metrics)
                
                # Calculate sensitivity (derivative approximation)
                sensitivity = (perturbed_reward - base_reward) / (base_value * perturbation_size)
                sensitivities[metric_name] = sensitivity
        
        return sensitivities
    
    def get_performance_summary(self, task_type: Optional[str] = None) -> Dict[str, Any]:
        """Get performance summary for model analysis."""
        if task_type:
            try:
                task_filter = TaskType(task_type.lower())
                filtered_history = [r for r in self.reward_history if r["task_type"] == task_filter]
            except ValueError:
                filtered_history = self.reward_history
        else:
            filtered_history = self.reward_history
        
        if not filtered_history:
            return {"message": "No reward history available"}
        
        rewards = [r["reward"] for r in filtered_history]
        
        summary = {
            "total_episodes": len(filtered_history),
            "average_reward": float(np.mean(rewards)),
            "reward_std": float(np.std(rewards)),
            "min_reward": float(np.min(rewards)),
            "max_reward": float(np.max(rewards)),
            "recent_performance": float(np.mean(rewards[-20:])) if len(rewards) >= 20 else float(np.mean(rewards)),
            "improvement_trend": self._calculate_trend(rewards),
        }
        
        # Task-specific statistics
        if not task_type:
            task_stats = {}
            for task in TaskType:
                task_rewards = [r["reward"] for r in filtered_history if r["task_type"] == task]
                if task_rewards:
                    task_stats[task.value] = {
                        "count": len(task_rewards),
                        "average": float(np.mean(task_rewards)),
                        "success_rate": sum(1 for r in filtered_history 
                                          if r["task_type"] == task and r.get("success", False)) / len(task_rewards)
                    }
            
            summary["task_statistics"] = task_stats
        
        return summary
    
    # Private Methods
    
    def _initialize_task_rewards(self) -> Dict[TaskType, TaskReward]:
        """Initialize task-specific reward configurations."""
        return {
            TaskType.PREPROCESSING: TaskReward(
                task_type=TaskType.PREPROCESSING,
                base_reward=2.0,
                time_penalty_rate=0.01,
                quality_bonus_rate=1.5,
                error_penalty=0.5,
                resource_penalty_rate=0.1
            ),
            TaskType.GLM_ANALYSIS: TaskReward(
                task_type=TaskType.GLM_ANALYSIS,
                base_reward=5.0,
                time_penalty_rate=0.008,
                quality_bonus_rate=3.0,
                error_penalty=1.0,
                resource_penalty_rate=0.15
            ),
            TaskType.CONTRAST_ANALYSIS: TaskReward(
                task_type=TaskType.CONTRAST_ANALYSIS,
                base_reward=3.0,
                time_penalty_rate=0.02,
                quality_bonus_rate=2.0,
                error_penalty=1.5,
                resource_penalty_rate=0.05
            ),
            TaskType.STATISTICAL_TEST: TaskReward(
                task_type=TaskType.STATISTICAL_TEST,
                base_reward=1.5,
                time_penalty_rate=0.05,
                quality_bonus_rate=2.5,
                error_penalty=2.0,
                resource_penalty_rate=0.02
            ),
            TaskType.VISUALIZATION: TaskReward(
                task_type=TaskType.VISUALIZATION,
                base_reward=1.0,
                time_penalty_rate=0.015,
                quality_bonus_rate=1.0,
                error_penalty=0.3,
                resource_penalty_rate=0.08
            ),
            TaskType.QUALITY_CHECK: TaskReward(
                task_type=TaskType.QUALITY_CHECK,
                base_reward=1.0,
                time_penalty_rate=0.03,
                quality_bonus_rate=2.0,
                error_penalty=0.8,
                resource_penalty_rate=0.03
            ),
            TaskType.DATA_EXPORT: TaskReward(
                task_type=TaskType.DATA_EXPORT,
                base_reward=0.5,
                time_penalty_rate=0.02,
                quality_bonus_rate=0.5,
                error_penalty=1.0,
                resource_penalty_rate=0.05
            ),
            TaskType.OPTIMIZATION: TaskReward(
                task_type=TaskType.OPTIMIZATION,
                base_reward=4.0,
                time_penalty_rate=0.005,
                quality_bonus_rate=4.0,
                error_penalty=0.5,
                resource_penalty_rate=0.2
            )
        }
    
    def _calculate_progress_reward(
        self,
        intermediate_results: List[Dict],
        task_type: TaskType
    ) -> float:
        """Calculate reward based on intermediate progress."""
        if not intermediate_results:
            return 0.0
        
        progress_scores = []
        for result in intermediate_results:
            score = result.get("progress_score", 0.0)
            quality = result.get("intermediate_quality", 0.0)
            progress_scores.append(score * quality)
        
        # Reward consistent progress
        if len(progress_scores) > 1:
            # Penalize large variations in progress
            progress_std = np.std(progress_scores)
            consistency_bonus = max(0, 0.2 - progress_std)
        else:
            consistency_bonus = 0.0
        
        avg_progress = np.mean(progress_scores)
        base_progress_reward = self.task_rewards[task_type].base_reward * 0.3
        
        return (avg_progress * base_progress_reward) + consistency_bonus
    
    def _apply_context_adjustments(
        self,
        base_reward: float,
        context: Dict[str, Any],
        task_type: TaskType
    ) -> float:
        """Apply context-specific reward adjustments."""
        adjusted_reward = base_reward
        
        # User experience level adjustment
        user_level = context.get("user_experience_level", "intermediate")
        if user_level == "beginner":
            # More forgiving for beginners
            adjusted_reward = adjusted_reward * 1.2 if adjusted_reward > 0 else adjusted_reward * 0.8
        elif user_level == "expert":
            # Higher standards for experts
            adjusted_reward = adjusted_reward * 0.9 if adjusted_reward > 0 else adjusted_reward * 1.2
        
        # Urgency adjustment
        urgency = context.get("urgency", "normal")
        if urgency == "high":
            # Penalize more for slow execution under high urgency
            time_adjustment = context.get("time_efficiency_ratio", 1.0)
            if time_adjustment > 1.0:  # Slow execution
                adjusted_reward *= 0.7
        
        # Dataset complexity adjustment
        complexity = context.get("dataset_complexity", "medium")
        complexity_multipliers = {"low": 0.8, "medium": 1.0, "high": 1.3}
        adjusted_reward *= complexity_multipliers.get(complexity, 1.0)
        
        # Historical performance adjustment
        if task_type in self.performance_stats:
            recent_performance = self.performance_stats[task_type].get("recent_average", 0)
            if recent_performance > 0:
                # Relative to recent performance
                performance_ratio = base_reward / recent_performance
                if performance_ratio > 1.5:  # Exceptionally good
                    adjusted_reward *= 1.1
                elif performance_ratio < 0.5:  # Exceptionally poor
                    adjusted_reward *= 0.9
        
        return adjusted_reward
    
    def _estimate_metrics_from_params(
        self,
        params: Dict[str, float],
        task_type: TaskType
    ) -> Dict[str, float]:
        """Estimate task metrics based on parameters (simplified model)."""
        baseline = self.baselines[task_type]
        
        # Simple linear model for estimation (would be replaced with learned model)
        estimated_time = baseline["expected_time"] * params.get("time_multiplier", 1.0)
        estimated_quality = baseline["quality_threshold"] * params.get("quality_multiplier", 1.0)
        estimated_errors = max(0, int(baseline["max_errors"] * params.get("error_multiplier", 1.0)))
        
        estimated_memory = baseline["resource_limit"]["memory_mb"] * params.get("memory_multiplier", 1.0)
        
        return {
            "execution_time": estimated_time,
            "success_probability": 0.95 - (estimated_errors * 0.1),  # Simple model
            "quality_score": min(1.0, estimated_quality),
            "error_count": estimated_errors,
            "resource_usage": {"memory_mb": estimated_memory},
            "satisfaction": 0.8 - (estimated_errors * 0.1) + (max(0, estimated_quality - 0.7) * 0.5)
        }
    
    def _record_reward(self, task_type: TaskType, reward: float, metrics: RewardMetrics) -> None:
        """Record reward for historical analysis."""
        record = {
            "timestamp": datetime.utcnow().isoformat(),
            "task_type": task_type,
            "reward": reward,
            "success": metrics.success,
            "execution_time": metrics.execution_time,
            "quality_score": metrics.quality_score,
            "error_count": metrics.error_count
        }
        
        self.reward_history.append(record)
        
        # Keep only last 1000 records
        if len(self.reward_history) > 1000:
            self.reward_history = self.reward_history[-1000:]
        
        # Update performance stats
        if task_type not in self.performance_stats:
            self.performance_stats[task_type] = {"rewards": [], "recent_average": 0}
        
        self.performance_stats[task_type]["rewards"].append(reward)
        
        # Keep last 50 rewards for recent average
        if len(self.performance_stats[task_type]["rewards"]) > 50:
            self.performance_stats[task_type]["rewards"] = self.performance_stats[task_type]["rewards"][-50:]
        
        self.performance_stats[task_type]["recent_average"] = np.mean(
            self.performance_stats[task_type]["rewards"]
        )
    
    def _calculate_trend(self, rewards: List[float]) -> str:
        """Calculate performance trend."""
        if len(rewards) < 10:
            return "insufficient_data"
        
        recent = rewards[-10:]
        earlier = rewards[-20:-10] if len(rewards) >= 20 else rewards[:-10]
        
        recent_avg = np.mean(recent)
        earlier_avg = np.mean(earlier)
        
        if recent_avg > earlier_avg * 1.05:
            return "improving"
        elif recent_avg < earlier_avg * 0.95:
            return "declining"
        else:
            return "stable"