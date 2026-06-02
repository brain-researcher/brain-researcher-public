"""
Strategy Selector for Dynamic Execution Strategy Selection (AGENT-021)

This module implements dynamic strategy selection based on system conditions,
workload characteristics, and performance feedback.
"""

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from brain_researcher.services.agent.adaptive_scheduler import (
    SchedulingPolicy,
    TaskPriority,
)
from brain_researcher.services.agent.system_monitor import (
    SystemHealth,
    SystemMetrics,
    SystemMonitor,
)

logger = logging.getLogger(__name__)


class ExecutionStrategy(str, Enum):
    """Execution strategy types."""

    AGGRESSIVE = "aggressive"
    BALANCED = "balanced"
    CONSERVATIVE = "conservative"
    MINIMAL = "minimal"


@dataclass
class ResourceLimits:
    """Resource limits for execution strategies."""

    max_parallel: int
    cpu_limit: float  # Percentage
    memory_limit: float  # Percentage
    io_limit: float  # MB/s
    preemption_enabled: bool
    timeout_multiplier: float


@dataclass
class ExecutionContext:
    """Context information for strategy selection."""

    system_metrics: SystemMetrics
    system_health: SystemHealth
    queue_depth: int
    average_task_duration: float
    current_throughput: float
    error_rate: float
    resource_utilization: Dict[str, float]
    time_constraints: Optional[float] = None  # Deadline pressure
    workload_type: str = "mixed"  # compute, io, memory, mixed
    user_priority: TaskPriority = TaskPriority.NORMAL


@dataclass
class StrategyPerformance:
    """Performance metrics for a strategy."""

    strategy: ExecutionStrategy
    throughput: float
    avg_latency: float
    error_rate: float
    resource_efficiency: float
    last_used: float
    success_count: int
    failure_count: int

    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0


class WorkloadAnalyzer:
    """Analyzes workload characteristics to inform strategy selection."""

    def __init__(self):
        """Initialize workload analyzer."""
        self.task_history: List[Dict[str, Any]] = []
        self.workload_patterns = {
            "compute_intensive": {
                "cpu_weight": 0.7,
                "memory_weight": 0.2,
                "io_weight": 0.1,
            },
            "memory_intensive": {
                "cpu_weight": 0.2,
                "memory_weight": 0.7,
                "io_weight": 0.1,
            },
            "io_intensive": {"cpu_weight": 0.1, "memory_weight": 0.2, "io_weight": 0.7},
            "mixed": {"cpu_weight": 0.33, "memory_weight": 0.33, "io_weight": 0.34},
        }

    def analyze_workload_type(self, recent_tasks: List[Dict[str, Any]]) -> str:
        """Analyze workload type based on recent tasks."""
        if not recent_tasks:
            return "mixed"

        # Analyze resource usage patterns
        cpu_heavy_tasks = sum(
            1 for task in recent_tasks if task.get("cpu_usage", 0) > 70
        )
        memory_heavy_tasks = sum(
            1 for task in recent_tasks if task.get("memory_usage", 0) > 70
        )
        io_heavy_tasks = sum(1 for task in recent_tasks if task.get("io_usage", 0) > 50)

        total_tasks = len(recent_tasks)

        if cpu_heavy_tasks / total_tasks > 0.6:
            return "compute_intensive"
        elif memory_heavy_tasks / total_tasks > 0.6:
            return "memory_intensive"
        elif io_heavy_tasks / total_tasks > 0.6:
            return "io_intensive"
        else:
            return "mixed"

    def predict_resource_requirements(self, workload_type: str) -> Dict[str, float]:
        """Predict resource requirements for workload type."""
        pattern = self.workload_patterns.get(
            workload_type, self.workload_patterns["mixed"]
        )

        return {
            "cpu_intensity": pattern["cpu_weight"],
            "memory_intensity": pattern["memory_weight"],
            "io_intensity": pattern["io_weight"],
        }

    def calculate_workload_complexity(self, context: ExecutionContext) -> float:
        """Calculate workload complexity score (0-1)."""
        complexity = 0.0

        # Queue depth factor
        queue_factor = min(context.queue_depth / 20.0, 1.0)  # Normalize to 20 tasks
        complexity += queue_factor * 0.3

        # Resource utilization factor
        avg_utilization = sum(context.resource_utilization.values()) / len(
            context.resource_utilization
        )
        complexity += (avg_utilization / 100.0) * 0.3

        # Task duration factor
        duration_factor = min(
            context.average_task_duration / 300.0, 1.0
        )  # Normalize to 5 minutes
        complexity += duration_factor * 0.2

        # Error rate factor
        complexity += context.error_rate * 0.2

        return min(complexity, 1.0)


class PerformanceTracker:
    """Tracks strategy performance over time."""

    def __init__(self, history_size: int = 100):
        """Initialize performance tracker."""
        self.history_size = history_size
        self.strategy_metrics: Dict[ExecutionStrategy, StrategyPerformance] = {}
        self.performance_history: List[Dict[str, Any]] = []

        # Initialize strategy metrics
        for strategy in ExecutionStrategy:
            self.strategy_metrics[strategy] = StrategyPerformance(
                strategy=strategy,
                throughput=0.0,
                avg_latency=0.0,
                error_rate=0.0,
                resource_efficiency=0.0,
                last_used=0.0,
                success_count=0,
                failure_count=0,
            )

    def record_strategy_performance(
        self,
        strategy: ExecutionStrategy,
        throughput: float,
        latency: float,
        error_rate: float,
        resource_efficiency: float,
        success: bool,
    ):
        """Record performance data for a strategy."""
        metrics = self.strategy_metrics[strategy]

        # Update running averages (exponential moving average)
        alpha = 0.1  # Smoothing factor
        metrics.throughput = metrics.throughput * (1 - alpha) + throughput * alpha
        metrics.avg_latency = metrics.avg_latency * (1 - alpha) + latency * alpha
        metrics.error_rate = metrics.error_rate * (1 - alpha) + error_rate * alpha
        metrics.resource_efficiency = (
            metrics.resource_efficiency * (1 - alpha) + resource_efficiency * alpha
        )
        metrics.last_used = time.time()

        if success:
            metrics.success_count += 1
        else:
            metrics.failure_count += 1

        # Record in history
        self.performance_history.append(
            {
                "strategy": strategy.value,
                "timestamp": time.time(),
                "throughput": throughput,
                "latency": latency,
                "error_rate": error_rate,
                "resource_efficiency": resource_efficiency,
                "success": success,
            }
        )

        # Trim history
        if len(self.performance_history) > self.history_size:
            self.performance_history.pop(0)

    def get_strategy_score(self, strategy: ExecutionStrategy) -> float:
        """Calculate composite score for a strategy."""
        metrics = self.strategy_metrics[strategy]

        if metrics.success_count + metrics.failure_count == 0:
            return 0.5  # Neutral score for untested strategies

        # Weighted composite score
        throughput_score = min(
            metrics.throughput / 10.0, 1.0
        )  # Normalize to 10 tasks/min
        latency_score = max(
            0, 1.0 - (metrics.avg_latency / 300.0)
        )  # Penalty for >5min latency
        success_score = metrics.success_rate
        efficiency_score = metrics.resource_efficiency

        # Recent usage bonus (prefer recently successful strategies)
        recency_bonus = 0.0
        if metrics.last_used > 0:
            time_since_used = time.time() - metrics.last_used
            if time_since_used < 3600:  # Last hour
                recency_bonus = 0.1 * (1 - time_since_used / 3600.0)

        composite_score = (
            throughput_score * 0.3
            + latency_score * 0.2
            + success_score * 0.3
            + efficiency_score * 0.2
            + recency_bonus
        )

        return min(composite_score, 1.0)

    def get_best_strategy(self) -> ExecutionStrategy:
        """Get the best performing strategy."""
        scores = {
            strategy: self.get_strategy_score(strategy)
            for strategy in ExecutionStrategy
        }
        return max(scores.items(), key=lambda x: x[1])[0]

    def get_performance_summary(self) -> Dict[str, Any]:
        """Get performance summary for all strategies."""
        summary = {}
        for strategy, metrics in self.strategy_metrics.items():
            summary[strategy.value] = {
                "score": self.get_strategy_score(strategy),
                "throughput": metrics.throughput,
                "avg_latency": metrics.avg_latency,
                "success_rate": metrics.success_rate,
                "resource_efficiency": metrics.resource_efficiency,
                "usage_count": metrics.success_count + metrics.failure_count,
            }
        return summary


class StrategySelector:
    """
    Selects optimal execution strategy based on current conditions.

    Considers:
    - System load and health
    - Queue depth and urgency
    - Workload characteristics
    - Historical performance
    - Resource availability
    """

    def __init__(self, monitor: SystemMonitor):
        """Initialize strategy selector."""
        self.monitor = monitor
        self.workload_analyzer = WorkloadAnalyzer()
        self.performance_tracker = PerformanceTracker()

        # Strategy configurations
        self.strategy_configs = {
            ExecutionStrategy.AGGRESSIVE: ResourceLimits(
                max_parallel=8,
                cpu_limit=95.0,
                memory_limit=90.0,
                io_limit=200.0,
                preemption_enabled=True,
                timeout_multiplier=0.8,
            ),
            ExecutionStrategy.BALANCED: ResourceLimits(
                max_parallel=4,
                cpu_limit=80.0,
                memory_limit=80.0,
                io_limit=150.0,
                preemption_enabled=True,
                timeout_multiplier=1.0,
            ),
            ExecutionStrategy.CONSERVATIVE: ResourceLimits(
                max_parallel=2,
                cpu_limit=60.0,
                memory_limit=70.0,
                io_limit=100.0,
                preemption_enabled=False,
                timeout_multiplier=1.5,
            ),
            ExecutionStrategy.MINIMAL: ResourceLimits(
                max_parallel=1,
                cpu_limit=40.0,
                memory_limit=50.0,
                io_limit=50.0,
                preemption_enabled=False,
                timeout_multiplier=2.0,
            ),
        }

        # Current strategy state
        self.current_strategy = ExecutionStrategy.BALANCED
        self.strategy_switch_cooldown = 30.0  # Seconds before allowing strategy switch
        self.last_strategy_switch = 0.0

        logger.info("Strategy selector initialized")

    def select_strategy(self, context: ExecutionContext) -> ExecutionStrategy:
        """
        Select optimal execution strategy based on context.

        Args:
            context: Current execution context

        Returns:
            Selected execution strategy
        """
        # Rule-based strategy selection with performance feedback
        candidate_strategies = self._get_candidate_strategies(context)

        # Score each candidate
        strategy_scores = {}
        for strategy in candidate_strategies:
            score = self._calculate_strategy_score(strategy, context)
            strategy_scores[strategy] = score

        # Select best strategy
        best_strategy = max(strategy_scores.items(), key=lambda x: x[1])[0]

        # Apply switching logic
        selected_strategy = self._apply_switching_logic(best_strategy, context)

        logger.info(
            f"Selected strategy: {selected_strategy.value} "
            f"(scores: {[(s.value, f'{score:.2f}') for s, score in strategy_scores.items()]})"
        )

        return selected_strategy

    def _get_candidate_strategies(
        self, context: ExecutionContext
    ) -> List[ExecutionStrategy]:
        """Get candidate strategies based on system health."""
        if context.system_health == SystemHealth.CRITICAL:
            return [ExecutionStrategy.MINIMAL, ExecutionStrategy.CONSERVATIVE]
        elif context.system_health == SystemHealth.STRESSED:
            return [ExecutionStrategy.CONSERVATIVE, ExecutionStrategy.BALANCED]
        elif context.system_health == SystemHealth.MODERATE:
            return [ExecutionStrategy.BALANCED, ExecutionStrategy.AGGRESSIVE]
        else:  # HEALTHY
            return list(ExecutionStrategy)

    def _calculate_strategy_score(
        self, strategy: ExecutionStrategy, context: ExecutionContext
    ) -> float:
        """Calculate score for a strategy given current context."""
        config = self.strategy_configs[strategy]

        # Base score from historical performance
        base_score = self.performance_tracker.get_strategy_score(strategy)

        # System compatibility score
        system_score = self._calculate_system_compatibility(strategy, context)

        # Workload compatibility score
        workload_score = self._calculate_workload_compatibility(strategy, context)

        # Urgency score
        urgency_score = self._calculate_urgency_compatibility(strategy, context)

        # Combine scores
        final_score = (
            base_score * 0.4
            + system_score * 0.3
            + workload_score * 0.2
            + urgency_score * 0.1
        )

        return final_score

    def _calculate_system_compatibility(
        self, strategy: ExecutionStrategy, context: ExecutionContext
    ) -> float:
        """Calculate how well strategy fits current system state."""
        config = self.strategy_configs[strategy]

        # Resource availability score
        cpu_available = 100 - context.system_metrics.cpu_usage
        memory_available = 100 - context.system_metrics.memory_usage

        cpu_fit = (
            1.0
            if cpu_available >= (100 - config.cpu_limit)
            else cpu_available / (100 - config.cpu_limit)
        )
        memory_fit = (
            1.0
            if memory_available >= (100 - config.memory_limit)
            else memory_available / (100 - config.memory_limit)
        )

        resource_score = (cpu_fit + memory_fit) / 2.0

        # Health compatibility
        health_scores = {
            SystemHealth.HEALTHY: {
                ExecutionStrategy.AGGRESSIVE: 1.0,
                ExecutionStrategy.BALANCED: 0.8,
                ExecutionStrategy.CONSERVATIVE: 0.6,
                ExecutionStrategy.MINIMAL: 0.3,
            },
            SystemHealth.MODERATE: {
                ExecutionStrategy.AGGRESSIVE: 0.7,
                ExecutionStrategy.BALANCED: 1.0,
                ExecutionStrategy.CONSERVATIVE: 0.8,
                ExecutionStrategy.MINIMAL: 0.5,
            },
            SystemHealth.STRESSED: {
                ExecutionStrategy.AGGRESSIVE: 0.3,
                ExecutionStrategy.BALANCED: 0.6,
                ExecutionStrategy.CONSERVATIVE: 1.0,
                ExecutionStrategy.MINIMAL: 0.8,
            },
            SystemHealth.CRITICAL: {
                ExecutionStrategy.AGGRESSIVE: 0.1,
                ExecutionStrategy.BALANCED: 0.3,
                ExecutionStrategy.CONSERVATIVE: 0.7,
                ExecutionStrategy.MINIMAL: 1.0,
            },
        }

        health_score = health_scores[context.system_health][strategy]

        return (resource_score + health_score) / 2.0

    def _calculate_workload_compatibility(
        self, strategy: ExecutionStrategy, context: ExecutionContext
    ) -> float:
        """Calculate how well strategy handles current workload."""
        config = self.strategy_configs[strategy]

        # Queue pressure compatibility
        queue_pressure = min(context.queue_depth / 10.0, 1.0)  # Normalize to 10 tasks

        if queue_pressure > 0.8:  # High queue pressure
            pressure_scores = {
                ExecutionStrategy.AGGRESSIVE: 1.0,
                ExecutionStrategy.BALANCED: 0.8,
                ExecutionStrategy.CONSERVATIVE: 0.5,
                ExecutionStrategy.MINIMAL: 0.2,
            }
        elif queue_pressure > 0.5:  # Medium queue pressure
            pressure_scores = {
                ExecutionStrategy.AGGRESSIVE: 0.9,
                ExecutionStrategy.BALANCED: 1.0,
                ExecutionStrategy.CONSERVATIVE: 0.7,
                ExecutionStrategy.MINIMAL: 0.4,
            }
        else:  # Low queue pressure
            pressure_scores = {
                ExecutionStrategy.AGGRESSIVE: 0.7,
                ExecutionStrategy.BALANCED: 0.9,
                ExecutionStrategy.CONSERVATIVE: 1.0,
                ExecutionStrategy.MINIMAL: 0.8,
            }

        # Parallelism compatibility
        optimal_parallel = min(context.queue_depth, 8)
        parallel_fit = 1.0 - abs(config.max_parallel - optimal_parallel) / 8.0

        return (pressure_scores[strategy] + parallel_fit) / 2.0

    def _calculate_urgency_compatibility(
        self, strategy: ExecutionStrategy, context: ExecutionContext
    ) -> float:
        """Calculate urgency compatibility score."""
        # Time constraints
        if context.time_constraints:
            time_pressure = max(
                0, 1.0 - context.time_constraints / 3600.0
            )  # Normalize to 1 hour
        else:
            time_pressure = 0.0

        # Priority urgency
        priority_urgency = (5 - context.user_priority.value) / 4.0  # Normalize priority

        # Error rate tolerance
        error_tolerance = 1.0 - context.error_rate

        urgency_factor = (time_pressure + priority_urgency) / 2.0

        # Strategy urgency handling
        urgency_scores = {
            ExecutionStrategy.AGGRESSIVE: urgency_factor * error_tolerance,
            ExecutionStrategy.BALANCED: 0.7 + urgency_factor * 0.3,
            ExecutionStrategy.CONSERVATIVE: 0.8 + urgency_factor * 0.2,
            ExecutionStrategy.MINIMAL: 0.9 + urgency_factor * 0.1,
        }

        return urgency_scores[strategy]

    def _apply_switching_logic(
        self, best_strategy: ExecutionStrategy, context: ExecutionContext
    ) -> ExecutionStrategy:
        """Apply strategy switching logic with hysteresis."""
        current_time = time.time()

        # Check cooldown
        if current_time - self.last_strategy_switch < self.strategy_switch_cooldown:
            return self.current_strategy

        # Check if switch is significant enough
        if best_strategy == self.current_strategy:
            return self.current_strategy

        # Calculate switch threshold based on system stability
        if context.system_health in [SystemHealth.CRITICAL, SystemHealth.STRESSED]:
            # More aggressive switching under stress
            switch_threshold = 0.1
        else:
            # Conservative switching under normal conditions
            switch_threshold = 0.2

        current_score = self._calculate_strategy_score(self.current_strategy, context)
        best_score = self._calculate_strategy_score(best_strategy, context)

        if best_score - current_score > switch_threshold:
            self.last_strategy_switch = current_time
            self.current_strategy = best_strategy
            logger.info(f"Strategy switched to {best_strategy.value}")

        return self.current_strategy

    def get_strategy_config(self, strategy: ExecutionStrategy) -> ResourceLimits:
        """Get configuration for a strategy."""
        return self.strategy_configs[strategy]

    def update_strategy_performance(
        self,
        strategy: ExecutionStrategy,
        throughput: float,
        latency: float,
        error_rate: float,
        resource_efficiency: float,
        success: bool,
    ):
        """Update performance tracking for a strategy."""
        self.performance_tracker.record_strategy_performance(
            strategy, throughput, latency, error_rate, resource_efficiency, success
        )

    def get_current_strategy(self) -> ExecutionStrategy:
        """Get current active strategy."""
        return self.current_strategy

    def force_strategy(self, strategy: ExecutionStrategy):
        """Force a specific strategy (for testing/debugging)."""
        self.current_strategy = strategy
        self.last_strategy_switch = time.time()
        logger.info(f"Forced strategy to {strategy.value}")

    def get_strategy_recommendations(self, context: ExecutionContext) -> Dict[str, Any]:
        """Get strategy recommendations with explanations."""
        recommendations = {}

        for strategy in ExecutionStrategy:
            score = self._calculate_strategy_score(strategy, context)
            config = self.strategy_configs[strategy]

            # Generate explanation
            explanation = []
            if context.system_health == SystemHealth.CRITICAL:
                if strategy in [
                    ExecutionStrategy.MINIMAL,
                    ExecutionStrategy.CONSERVATIVE,
                ]:
                    explanation.append("Good for critical system state")
                else:
                    explanation.append("May overwhelm critical system")

            if context.queue_depth > 10:
                if strategy in [
                    ExecutionStrategy.AGGRESSIVE,
                    ExecutionStrategy.BALANCED,
                ]:
                    explanation.append("Handles high queue depth well")
                else:
                    explanation.append("May not clear queue quickly")

            if context.error_rate > 0.1:
                if strategy in [
                    ExecutionStrategy.CONSERVATIVE,
                    ExecutionStrategy.MINIMAL,
                ]:
                    explanation.append("Conservative approach for high error rate")
                else:
                    explanation.append("May increase errors further")

            recommendations[strategy.value] = {
                "score": score,
                "config": {
                    "max_parallel": config.max_parallel,
                    "cpu_limit": config.cpu_limit,
                    "memory_limit": config.memory_limit,
                    "preemption_enabled": config.preemption_enabled,
                },
                "explanation": (
                    "; ".join(explanation) if explanation else "Standard operation"
                ),
            }

        return recommendations

    def get_selection_metrics(self) -> Dict[str, Any]:
        """Get strategy selection metrics."""
        return {
            "current_strategy": self.current_strategy.value,
            "last_switch": self.last_strategy_switch,
            "performance_summary": self.performance_tracker.get_performance_summary(),
            "switch_cooldown_remaining": max(
                0,
                self.strategy_switch_cooldown
                - (time.time() - self.last_strategy_switch),
            ),
        }


# Factory function
def create_strategy_selector(monitor: SystemMonitor) -> StrategySelector:
    """
    Create a strategy selector instance.

    Args:
        monitor: System monitor for real-time metrics

    Returns:
        Configured StrategySelector instance
    """
    return StrategySelector(monitor)
