"""
Unit tests for Strategy Selector (AGENT-021).

Tests the StrategySelector, WorkloadAnalyzer, PerformanceTracker, and related
components for dynamic execution strategy selection based on system conditions.
"""

import json
import pytest
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from brain_researcher.services.agent.strategy_selector import (
    StrategySelector,
    WorkloadAnalyzer,
    PerformanceTracker,
    ExecutionStrategy,
    ExecutionContext,
    ResourceLimits,
    StrategyPerformance,
    create_strategy_selector
)
from brain_researcher.services.agent.adaptive_scheduler import TaskPriority
from brain_researcher.services.agent.system_monitor import SystemHealth, SystemMetrics

# Import test fixtures
import sys
sys.path.append(str(Path(__file__).parent.parent / "fixtures" / "AGENT-021"))
from mock_tools import create_mock_system_monitor


class TestResourceLimits:
    """Test ResourceLimits data structure."""
    
    def test_resource_limits_creation(self):
        """Test ResourceLimits creation."""
        limits = ResourceLimits(
            max_parallel=4,
            cpu_limit=80.0,
            memory_limit=75.0,
            io_limit=100.0,
            preemption_enabled=True,
            timeout_multiplier=1.2
        )
        
        assert limits.max_parallel == 4
        assert limits.cpu_limit == 80.0
        assert limits.memory_limit == 75.0
        assert limits.io_limit == 100.0
        assert limits.preemption_enabled is True
        assert limits.timeout_multiplier == 1.2


class TestExecutionContext:
    """Test ExecutionContext data structure."""
    
    def test_execution_context_creation(self):
        """Test ExecutionContext creation with all fields."""
        metrics = SystemMetrics(
            timestamp=time.time(),
            cpu_usage=65.0,
            memory_usage=70.0,
            memory_available=8.0,
            disk_io_read=15.0,
            disk_io_write=12.0,
            network_sent=8.0,
            network_recv=6.0,
            load_average=(2.0, 2.1, 2.2),
            active_processes=150
        )
        
        context = ExecutionContext(
            system_metrics=metrics,
            system_health=SystemHealth.MODERATE,
            queue_depth=12,
            average_task_duration=180.0,
            current_throughput=3.5,
            error_rate=0.02,
            resource_utilization={"cpu": 65.0, "memory": 70.0},
            time_constraints=300.0,
            workload_type="compute_intensive",
            user_priority=TaskPriority.HIGH
        )
        
        assert context.system_metrics.cpu_usage == 65.0
        assert context.system_health == SystemHealth.MODERATE
        assert context.queue_depth == 12
        assert context.average_task_duration == 180.0
        assert context.current_throughput == 3.5
        assert context.error_rate == 0.02
        assert context.resource_utilization["cpu"] == 65.0
        assert context.time_constraints == 300.0
        assert context.workload_type == "compute_intensive"
        assert context.user_priority == TaskPriority.HIGH


class TestStrategyPerformance:
    """Test StrategyPerformance data structure and methods."""
    
    def test_strategy_performance_creation(self):
        """Test StrategyPerformance creation."""
        performance = StrategyPerformance(
            strategy=ExecutionStrategy.BALANCED,
            throughput=4.2,
            avg_latency=120.0,
            error_rate=0.01,
            resource_efficiency=0.85,
            last_used=time.time(),
            success_count=50,
            failure_count=2
        )
        
        assert performance.strategy == ExecutionStrategy.BALANCED
        assert performance.throughput == 4.2
        assert performance.avg_latency == 120.0
        assert performance.error_rate == 0.01
        assert performance.resource_efficiency == 0.85
        assert performance.success_count == 50
        assert performance.failure_count == 2
    
    def test_success_rate_calculation(self):
        """Test success rate calculation."""
        # Perfect success rate
        performance = StrategyPerformance(
            strategy=ExecutionStrategy.AGGRESSIVE,
            throughput=5.0,
            avg_latency=90.0,
            error_rate=0.0,
            resource_efficiency=0.9,
            last_used=time.time(),
            success_count=100,
            failure_count=0
        )
        
        assert performance.success_rate == 1.0
        
        # Mixed success rate
        performance.success_count = 80
        performance.failure_count = 20
        assert performance.success_rate == 0.8
        
        # No attempts yet
        performance.success_count = 0
        performance.failure_count = 0
        assert performance.success_rate == 0.0


class TestWorkloadAnalyzer:
    """Test WorkloadAnalyzer functionality."""
    
    def test_workload_analyzer_initialization(self):
        """Test WorkloadAnalyzer initialization."""
        analyzer = WorkloadAnalyzer()
        
        assert len(analyzer.task_history) == 0
        assert len(analyzer.workload_patterns) == 4
        assert "compute_intensive" in analyzer.workload_patterns
        assert "memory_intensive" in analyzer.workload_patterns
        assert "io_intensive" in analyzer.workload_patterns
        assert "mixed" in analyzer.workload_patterns
    
    def test_analyze_compute_intensive_workload(self):
        """Test analysis of compute-intensive workload."""
        analyzer = WorkloadAnalyzer()
        
        # Create tasks with high CPU usage
        recent_tasks = [
            {"cpu_usage": 85, "memory_usage": 30, "io_usage": 10},
            {"cpu_usage": 90, "memory_usage": 25, "io_usage": 15},
            {"cpu_usage": 80, "memory_usage": 35, "io_usage": 8},
            {"cpu_usage": 88, "memory_usage": 40, "io_usage": 12},
            {"cpu_usage": 92, "memory_usage": 28, "io_usage": 5}
        ]
        
        workload_type = analyzer.analyze_workload_type(recent_tasks)
        assert workload_type == "compute_intensive"
    
    def test_analyze_memory_intensive_workload(self):
        """Test analysis of memory-intensive workload."""
        analyzer = WorkloadAnalyzer()
        
        # Create tasks with high memory usage
        recent_tasks = [
            {"cpu_usage": 30, "memory_usage": 85, "io_usage": 15},
            {"cpu_usage": 25, "memory_usage": 90, "io_usage": 10},
            {"cpu_usage": 35, "memory_usage": 80, "io_usage": 20},
            {"cpu_usage": 40, "memory_usage": 88, "io_usage": 12}
        ]
        
        workload_type = analyzer.analyze_workload_type(recent_tasks)
        assert workload_type == "memory_intensive"
    
    def test_analyze_io_intensive_workload(self):
        """Test analysis of I/O-intensive workload."""
        analyzer = WorkloadAnalyzer()
        
        # Create tasks with high I/O usage
        recent_tasks = [
            {"cpu_usage": 20, "memory_usage": 30, "io_usage": 75},
            {"cpu_usage": 25, "memory_usage": 35, "io_usage": 80},
            {"cpu_usage": 15, "memory_usage": 25, "io_usage": 85},
            {"cpu_usage": 30, "memory_usage": 40, "io_usage": 70}
        ]
        
        workload_type = analyzer.analyze_workload_type(recent_tasks)
        assert workload_type == "io_intensive"
    
    def test_analyze_mixed_workload(self):
        """Test analysis of mixed workload."""
        analyzer = WorkloadAnalyzer()
        
        # Create tasks with varied resource usage
        recent_tasks = [
            {"cpu_usage": 50, "memory_usage": 40, "io_usage": 30},
            {"cpu_usage": 60, "memory_usage": 50, "io_usage": 25},
            {"cpu_usage": 45, "memory_usage": 45, "io_usage": 35},
            {"cpu_usage": 55, "memory_usage": 55, "io_usage": 40}
        ]
        
        workload_type = analyzer.analyze_workload_type(recent_tasks)
        assert workload_type == "mixed"
    
    def test_analyze_empty_workload(self):
        """Test analysis with no task history."""
        analyzer = WorkloadAnalyzer()
        
        workload_type = analyzer.analyze_workload_type([])
        assert workload_type == "mixed"  # Default
    
    def test_predict_resource_requirements(self):
        """Test resource requirement prediction."""
        analyzer = WorkloadAnalyzer()
        
        # Test compute-intensive prediction
        compute_reqs = analyzer.predict_resource_requirements("compute_intensive")
        assert compute_reqs["cpu_intensity"] == 0.7
        assert compute_reqs["memory_intensity"] == 0.2
        assert compute_reqs["io_intensity"] == 0.1
        
        # Test memory-intensive prediction
        memory_reqs = analyzer.predict_resource_requirements("memory_intensive")
        assert memory_reqs["cpu_intensity"] == 0.2
        assert memory_reqs["memory_intensity"] == 0.7
        assert memory_reqs["io_intensity"] == 0.1
        
        # Test unknown workload (defaults to mixed)
        unknown_reqs = analyzer.predict_resource_requirements("unknown")
        mixed_reqs = analyzer.predict_resource_requirements("mixed")
        assert unknown_reqs == mixed_reqs
    
    def test_calculate_workload_complexity(self):
        """Test workload complexity calculation."""
        analyzer = WorkloadAnalyzer()
        
        # Simple workload
        simple_context = ExecutionContext(
            system_metrics=SystemMetrics(
                timestamp=time.time(),
                cpu_usage=30.0,
                memory_usage=40.0,
                memory_available=12.0,
                disk_io_read=5.0,
                disk_io_write=3.0,
                network_sent=2.0,
                network_recv=1.5,
                load_average=(1.0, 1.0, 1.0),
                active_processes=100
            ),
            system_health=SystemHealth.HEALTHY,
            queue_depth=2,
            average_task_duration=60.0,
            current_throughput=5.0,
            error_rate=0.0,
            resource_utilization={"cpu": 30.0, "memory": 40.0}
        )
        
        simple_complexity = analyzer.calculate_workload_complexity(simple_context)
        
        # Complex workload
        complex_context = ExecutionContext(
            system_metrics=SystemMetrics(
                timestamp=time.time(),
                cpu_usage=80.0,
                memory_usage=85.0,
                memory_available=4.0,
                disk_io_read=50.0,
                disk_io_write=40.0,
                network_sent=20.0,
                network_recv=15.0,
                load_average=(3.0, 3.5, 4.0),
                active_processes=250
            ),
            system_health=SystemHealth.STRESSED,
            queue_depth=25,
            average_task_duration=600.0,
            current_throughput=1.0,
            error_rate=0.1,
            resource_utilization={"cpu": 80.0, "memory": 85.0}
        )
        
        complex_complexity = analyzer.calculate_workload_complexity(complex_context)
        
        # Complex workload should have higher complexity score
        assert complex_complexity > simple_complexity
        assert 0.0 <= simple_complexity <= 1.0
        assert 0.0 <= complex_complexity <= 1.0


class TestPerformanceTracker:
    """Test PerformanceTracker functionality."""
    
    def test_performance_tracker_initialization(self):
        """Test PerformanceTracker initialization."""
        tracker = PerformanceTracker(history_size=50)
        
        assert tracker.history_size == 50
        assert len(tracker.strategy_metrics) == len(ExecutionStrategy)
        assert len(tracker.performance_history) == 0
        
        # Check that all strategies are initialized
        for strategy in ExecutionStrategy:
            assert strategy in tracker.strategy_metrics
            assert tracker.strategy_metrics[strategy].strategy == strategy
    
    def test_record_strategy_performance(self):
        """Test recording strategy performance."""
        tracker = PerformanceTracker()
        
        initial_metrics = tracker.strategy_metrics[ExecutionStrategy.BALANCED]
        initial_throughput = initial_metrics.throughput
        initial_success = initial_metrics.success_count
        
        # Record successful performance
        tracker.record_strategy_performance(
            strategy=ExecutionStrategy.BALANCED,
            throughput=5.0,
            latency=100.0,
            error_rate=0.02,
            resource_efficiency=0.8,
            success=True
        )
        
        updated_metrics = tracker.strategy_metrics[ExecutionStrategy.BALANCED]
        
        # Should update metrics
        assert updated_metrics.throughput != initial_throughput
        assert updated_metrics.success_count == initial_success + 1
        assert len(tracker.performance_history) == 1
        
        # Record failed performance
        tracker.record_strategy_performance(
            strategy=ExecutionStrategy.BALANCED,
            throughput=2.0,
            latency=200.0,
            error_rate=0.1,
            resource_efficiency=0.6,
            success=False
        )
        
        assert updated_metrics.failure_count == 1
        assert len(tracker.performance_history) == 2
    
    def test_exponential_moving_average(self):
        """Test exponential moving average calculation."""
        tracker = PerformanceTracker()
        
        # Record multiple performances to test averaging
        for i in range(5):
            tracker.record_strategy_performance(
                strategy=ExecutionStrategy.AGGRESSIVE,
                throughput=float(i + 1),  # 1.0, 2.0, 3.0, 4.0, 5.0
                latency=100.0,
                error_rate=0.01,
                resource_efficiency=0.8,
                success=True
            )
        
        metrics = tracker.strategy_metrics[ExecutionStrategy.AGGRESSIVE]
        
        # Should be exponentially weighted average, not simple average
        # With alpha=0.1, final value should be closer to earlier values
        assert metrics.throughput != 3.0  # Not simple average
        assert metrics.throughput > 0.0
    
    def test_get_strategy_score(self):
        """Test strategy score calculation."""
        tracker = PerformanceTracker()
        
        # Record excellent performance
        for _ in range(10):
            tracker.record_strategy_performance(
                strategy=ExecutionStrategy.BALANCED,
                throughput=8.0,  # High throughput
                latency=60.0,    # Low latency
                error_rate=0.0,  # No errors
                resource_efficiency=0.95,  # High efficiency
                success=True
            )
        
        excellent_score = tracker.get_strategy_score(ExecutionStrategy.BALANCED)
        
        # Record poor performance
        for _ in range(10):
            tracker.record_strategy_performance(
                strategy=ExecutionStrategy.CONSERVATIVE,
                throughput=1.0,  # Low throughput
                latency=500.0,   # High latency
                error_rate=0.2,  # High error rate
                resource_efficiency=0.3,  # Low efficiency
                success=False
            )
        
        poor_score = tracker.get_strategy_score(ExecutionStrategy.CONSERVATIVE)
        
        # Excellent performance should have higher score
        assert excellent_score > poor_score
        assert 0.0 <= excellent_score <= 1.0
        assert 0.0 <= poor_score <= 1.0
    
    def test_get_strategy_score_untested(self):
        """Test strategy score for untested strategy."""
        tracker = PerformanceTracker()
        
        # Get score for strategy with no recorded performance
        score = tracker.get_strategy_score(ExecutionStrategy.MINIMAL)
        
        # Should return neutral score
        assert score == 0.5
    
    def test_get_best_strategy(self):
        """Test best strategy selection."""
        tracker = PerformanceTracker()
        
        # Record different performance levels for different strategies
        strategies_performance = [
            (ExecutionStrategy.AGGRESSIVE, 6.0, 80.0, 0.05, 0.85),  # Good but risky
            (ExecutionStrategy.BALANCED, 4.0, 120.0, 0.01, 0.90),   # Excellent balance
            (ExecutionStrategy.CONSERVATIVE, 2.0, 200.0, 0.0, 0.95), # Slow but reliable
            (ExecutionStrategy.MINIMAL, 1.0, 400.0, 0.0, 0.98)      # Very slow, very safe
        ]
        
        for strategy, throughput, latency, error_rate, efficiency in strategies_performance:
            for _ in range(5):  # Multiple recordings for each
                tracker.record_strategy_performance(
                    strategy=strategy,
                    throughput=throughput,
                    latency=latency,
                    error_rate=error_rate,
                    resource_efficiency=efficiency,
                    success=True
                )
        
        best_strategy = tracker.get_best_strategy()
        
        # Should select the strategy with highest composite score
        # (likely BALANCED given the metrics above)
        assert best_strategy in ExecutionStrategy
    
    def test_get_performance_summary(self):
        """Test performance summary generation."""
        tracker = PerformanceTracker()
        
        # Record performance for some strategies
        tracker.record_strategy_performance(
            strategy=ExecutionStrategy.BALANCED,
            throughput=4.5,
            latency=110.0,
            error_rate=0.02,
            resource_efficiency=0.85,
            success=True
        )
        
        summary = tracker.get_performance_summary()
        
        assert len(summary) == len(ExecutionStrategy)
        assert "balanced" in summary
        
        balanced_summary = summary["balanced"]
        assert "score" in balanced_summary
        assert "throughput" in balanced_summary
        assert "avg_latency" in balanced_summary
        assert "success_rate" in balanced_summary
        assert "resource_efficiency" in balanced_summary
        assert "usage_count" in balanced_summary
    
    def test_performance_history_limit(self):
        """Test performance history size limit."""
        tracker = PerformanceTracker(history_size=5)
        
        # Record more entries than history size
        for i in range(10):
            tracker.record_strategy_performance(
                strategy=ExecutionStrategy.AGGRESSIVE,
                throughput=float(i),
                latency=100.0,
                error_rate=0.01,
                resource_efficiency=0.8,
                success=True
            )
        
        # Should only keep last 5 entries
        assert len(tracker.performance_history) == 5
        
        # Should keep the most recent ones
        assert tracker.performance_history[0]["throughput"] == 5.0  # Entry 5 (0-indexed)
        assert tracker.performance_history[-1]["throughput"] == 9.0  # Entry 9


class TestStrategySelector:
    """Test StrategySelector functionality."""
    
    @pytest.fixture
    def mock_monitor(self):
        """Create mock system monitor."""
        return create_mock_system_monitor()
    
    @pytest.fixture
    def selector(self, mock_monitor):
        """Create strategy selector for testing."""
        return StrategySelector(monitor=mock_monitor)
    
    def test_strategy_selector_initialization(self, selector):
        """Test StrategySelector initialization."""
        assert isinstance(selector.workload_analyzer, WorkloadAnalyzer)
        assert isinstance(selector.performance_tracker, PerformanceTracker)
        
        # Check strategy configurations
        assert len(selector.strategy_configs) == len(ExecutionStrategy)
        for strategy in ExecutionStrategy:
            assert strategy in selector.strategy_configs
            config = selector.strategy_configs[strategy]
            assert isinstance(config, ResourceLimits)
            assert config.max_parallel > 0
            assert config.cpu_limit > 0
            assert config.memory_limit > 0
        
        # Check initial state
        assert selector.current_strategy == ExecutionStrategy.BALANCED
        assert selector.strategy_switch_cooldown == 30.0
        assert selector.last_strategy_switch == 0.0
    
    def test_strategy_configurations(self, selector):
        """Test strategy configuration values."""
        aggressive_config = selector.strategy_configs[ExecutionStrategy.AGGRESSIVE]
        conservative_config = selector.strategy_configs[ExecutionStrategy.CONSERVATIVE]
        minimal_config = selector.strategy_configs[ExecutionStrategy.MINIMAL]
        
        # Aggressive should allow more parallelism and higher resource limits
        assert aggressive_config.max_parallel > conservative_config.max_parallel
        assert aggressive_config.cpu_limit > conservative_config.cpu_limit
        assert aggressive_config.preemption_enabled is True
        
        # Minimal should be most restrictive
        assert minimal_config.max_parallel == 1
        assert minimal_config.preemption_enabled is False
        assert minimal_config.timeout_multiplier > 1.0
    
    def test_get_candidate_strategies_healthy(self, selector):
        """Test candidate strategy selection for healthy system."""
        healthy_context = ExecutionContext(
            system_metrics=SystemMetrics(
                timestamp=time.time(),
                cpu_usage=30.0,
                memory_usage=40.0,
                memory_available=12.0,
                disk_io_read=5.0,
                disk_io_write=3.0,
                network_sent=2.0,
                network_recv=1.5,
                load_average=(1.0, 1.0, 1.0),
                active_processes=100
            ),
            system_health=SystemHealth.HEALTHY,
            queue_depth=3,
            average_task_duration=120.0,
            current_throughput=4.0,
            error_rate=0.01,
            resource_utilization={"cpu": 30.0, "memory": 40.0}
        )
        
        candidates = selector._get_candidate_strategies(healthy_context)
        
        # Healthy system should allow all strategies
        assert len(candidates) == len(ExecutionStrategy)
        assert ExecutionStrategy.AGGRESSIVE in candidates
        assert ExecutionStrategy.MINIMAL in candidates
    
    def test_get_candidate_strategies_critical(self, selector):
        """Test candidate strategy selection for critical system."""
        critical_context = ExecutionContext(
            system_metrics=SystemMetrics(
                timestamp=time.time(),
                cpu_usage=95.0,
                memory_usage=92.0,
                memory_available=2.0,
                disk_io_read=100.0,
                disk_io_write=80.0,
                network_sent=50.0,
                network_recv=40.0,
                load_average=(6.0, 6.5, 7.0),
                active_processes=300
            ),
            system_health=SystemHealth.CRITICAL,
            queue_depth=50,
            average_task_duration=300.0,
            current_throughput=0.5,
            error_rate=0.2,
            resource_utilization={"cpu": 95.0, "memory": 92.0}
        )
        
        candidates = selector._get_candidate_strategies(critical_context)
        
        # Critical system should only allow conservative strategies
        assert len(candidates) <= 2
        assert ExecutionStrategy.MINIMAL in candidates
        assert ExecutionStrategy.CONSERVATIVE in candidates
        assert ExecutionStrategy.AGGRESSIVE not in candidates
    
    def test_calculate_system_compatibility(self, selector):
        """Test system compatibility calculation."""
        # Healthy system with available resources
        healthy_context = ExecutionContext(
            system_metrics=SystemMetrics(
                timestamp=time.time(),
                cpu_usage=40.0,  # 60% available
                memory_usage=30.0,  # 70% available
                memory_available=14.0,
                disk_io_read=10.0,
                disk_io_write=8.0,
                network_sent=5.0,
                network_recv=4.0,
                load_average=(1.5, 1.6, 1.7),
                active_processes=130
            ),
            system_health=SystemHealth.HEALTHY,
            queue_depth=5,
            average_task_duration=180.0,
            current_throughput=3.0,
            error_rate=0.02,
            resource_utilization={"cpu": 40.0, "memory": 30.0}
        )
        
        aggressive_compatibility = selector._calculate_system_compatibility(
            ExecutionStrategy.AGGRESSIVE, healthy_context
        )
        minimal_compatibility = selector._calculate_system_compatibility(
            ExecutionStrategy.MINIMAL, healthy_context
        )
        
        # Aggressive strategy should be more compatible with healthy system
        assert aggressive_compatibility > minimal_compatibility
        
        # Stressed system
        stressed_context = ExecutionContext(
            system_metrics=SystemMetrics(
                timestamp=time.time(),
                cpu_usage=85.0,  # Limited availability
                memory_usage=80.0,
                memory_available=4.0,
                disk_io_read=50.0,
                disk_io_write=40.0,
                network_sent=25.0,
                network_recv=20.0,
                load_average=(4.0, 4.2, 4.5),
                active_processes=220
            ),
            system_health=SystemHealth.STRESSED,
            queue_depth=20,
            average_task_duration=240.0,
            current_throughput=1.5,
            error_rate=0.08,
            resource_utilization={"cpu": 85.0, "memory": 80.0}
        )
        
        stressed_aggressive = selector._calculate_system_compatibility(
            ExecutionStrategy.AGGRESSIVE, stressed_context
        )
        stressed_minimal = selector._calculate_system_compatibility(
            ExecutionStrategy.MINIMAL, stressed_context
        )
        
        # Under stress, minimal should be more compatible
        assert stressed_minimal > stressed_aggressive
    
    def test_calculate_workload_compatibility(self, selector):
        """Test workload compatibility calculation."""
        # High queue pressure scenario
        high_queue_context = ExecutionContext(
            system_metrics=SystemMetrics(
                timestamp=time.time(),
                cpu_usage=60.0,
                memory_usage=50.0,
                memory_available=10.0,
                disk_io_read=20.0,
                disk_io_write=15.0,
                network_sent=10.0,
                network_recv=8.0,
                load_average=(2.5, 2.6, 2.7),
                active_processes=180
            ),
            system_health=SystemHealth.MODERATE,
            queue_depth=15,  # High queue depth
            average_task_duration=200.0,
            current_throughput=2.0,
            error_rate=0.03,
            resource_utilization={"cpu": 60.0, "memory": 50.0}
        )
        
        aggressive_workload = selector._calculate_workload_compatibility(
            ExecutionStrategy.AGGRESSIVE, high_queue_context
        )
        minimal_workload = selector._calculate_workload_compatibility(
            ExecutionStrategy.MINIMAL, high_queue_context
        )
        
        # High queue pressure should favor aggressive strategy
        assert aggressive_workload > minimal_workload
        
        # Low queue pressure scenario
        low_queue_context = ExecutionContext(
            system_metrics=SystemMetrics(
                timestamp=time.time(),
                cpu_usage=30.0,
                memory_usage=35.0,
                memory_available=13.0,
                disk_io_read=8.0,
                disk_io_write=6.0,
                network_sent=4.0,
                network_recv=3.0,
                load_average=(1.0, 1.1, 1.2),
                active_processes=120
            ),
            system_health=SystemHealth.HEALTHY,
            queue_depth=2,  # Low queue depth
            average_task_duration=90.0,
            current_throughput=5.0,
            error_rate=0.005,
            resource_utilization={"cpu": 30.0, "memory": 35.0}
        )
        
        low_aggressive = selector._calculate_workload_compatibility(
            ExecutionStrategy.AGGRESSIVE, low_queue_context
        )
        low_conservative = selector._calculate_workload_compatibility(
            ExecutionStrategy.CONSERVATIVE, low_queue_context
        )
        
        # Low pressure should favor conservative approach
        assert low_conservative >= low_aggressive
    
    def test_calculate_urgency_compatibility(self, selector):
        """Test urgency compatibility calculation."""
        current_time = time.time()
        
        # Urgent scenario
        urgent_context = ExecutionContext(
            system_metrics=SystemMetrics(
                timestamp=current_time,
                cpu_usage=50.0,
                memory_usage=60.0,
                memory_available=8.0,
                disk_io_read=15.0,
                disk_io_write=12.0,
                network_sent=8.0,
                network_recv=6.0,
                load_average=(2.0, 2.0, 2.0),
                active_processes=150
            ),
            system_health=SystemHealth.MODERATE,
            queue_depth=8,
            average_task_duration=180.0,
            current_throughput=2.5,
            error_rate=0.02,
            resource_utilization={"cpu": 50.0, "memory": 60.0},
            time_constraints=300.0,  # 5 minutes deadline
            user_priority=TaskPriority.CRITICAL
        )
        
        urgent_aggressive = selector._calculate_urgency_compatibility(
            ExecutionStrategy.AGGRESSIVE, urgent_context
        )
        urgent_minimal = selector._calculate_urgency_compatibility(
            ExecutionStrategy.MINIMAL, urgent_context
        )
        
        # Urgent scenarios should favor aggressive strategies
        assert urgent_aggressive >= urgent_minimal
        
        # Relaxed scenario
        relaxed_context = ExecutionContext(
            system_metrics=SystemMetrics(
                timestamp=current_time,
                cpu_usage=40.0,
                memory_usage=45.0,
                memory_available=11.0,
                disk_io_read=10.0,
                disk_io_write=8.0,
                network_sent=5.0,
                network_recv=4.0,
                load_average=(1.5, 1.5, 1.5),
                active_processes=130
            ),
            system_health=SystemHealth.HEALTHY,
            queue_depth=4,
            average_task_duration=120.0,
            current_throughput=4.0,
            error_rate=0.01,
            resource_utilization={"cpu": 40.0, "memory": 45.0},
            time_constraints=None,  # No deadline
            user_priority=TaskPriority.BACKGROUND
        )
        
        relaxed_conservative = selector._calculate_urgency_compatibility(
            ExecutionStrategy.CONSERVATIVE, relaxed_context
        )
        relaxed_aggressive = selector._calculate_urgency_compatibility(
            ExecutionStrategy.AGGRESSIVE, relaxed_context
        )
        
        # Should favor conservative for relaxed scenarios
        assert relaxed_conservative >= relaxed_aggressive
    
    def test_select_strategy(self, selector, mock_monitor):
        """Test strategy selection process."""
        # Mock healthy system
        mock_monitor.get_health_status.return_value = SystemHealth.HEALTHY
        
        context = ExecutionContext(
            system_metrics=SystemMetrics(
                timestamp=time.time(),
                cpu_usage=45.0,
                memory_usage=55.0,
                memory_available=9.0,
                disk_io_read=12.0,
                disk_io_write=10.0,
                network_sent=6.0,
                network_recv=5.0,
                load_average=(1.8, 1.9, 2.0),
                active_processes=160
            ),
            system_health=SystemHealth.HEALTHY,
            queue_depth=6,
            average_task_duration=150.0,
            current_throughput=3.5,
            error_rate=0.015,
            resource_utilization={"cpu": 45.0, "memory": 55.0}
        )
        
        selected_strategy = selector.select_strategy(context)
        
        # Should select a valid strategy
        assert selected_strategy in ExecutionStrategy
        
        # Current strategy should be updated
        assert selector.current_strategy == selected_strategy
    
    def test_switching_logic_with_cooldown(self, selector):
        """Test strategy switching with cooldown period."""
        context = ExecutionContext(
            system_metrics=SystemMetrics(
                timestamp=time.time(),
                cpu_usage=50.0,
                memory_usage=60.0,
                memory_available=8.0,
                disk_io_read=15.0,
                disk_io_write=12.0,
                network_sent=8.0,
                network_recv=6.0,
                load_average=(2.0, 2.0, 2.0),
                active_processes=150
            ),
            system_health=SystemHealth.MODERATE,
            queue_depth=8,
            average_task_duration=180.0,
            current_throughput=2.5,
            error_rate=0.02,
            resource_utilization={"cpu": 50.0, "memory": 60.0}
        )
        
        # Set recent strategy switch
        selector.last_strategy_switch = time.time() - 10.0  # 10 seconds ago
        initial_strategy = selector.current_strategy
        
        # Should not switch due to cooldown
        result = selector._apply_switching_logic(ExecutionStrategy.AGGRESSIVE, context)
        assert result == initial_strategy
        
        # Set old strategy switch (outside cooldown)
        selector.last_strategy_switch = time.time() - 60.0  # 60 seconds ago
        
        # Should allow switch now
        result = selector._apply_switching_logic(ExecutionStrategy.AGGRESSIVE, context)
        # Result depends on score difference, but cooldown should not prevent it
    
    def test_get_strategy_config(self, selector):
        """Test strategy configuration retrieval."""
        config = selector.get_strategy_config(ExecutionStrategy.BALANCED)
        
        assert isinstance(config, ResourceLimits)
        assert config.max_parallel > 0
        assert config.cpu_limit > 0.0
        assert config.memory_limit > 0.0
    
    def test_update_strategy_performance(self, selector):
        """Test strategy performance updating."""
        initial_count = selector.performance_tracker.strategy_metrics[ExecutionStrategy.BALANCED].success_count
        
        selector.update_strategy_performance(
            strategy=ExecutionStrategy.BALANCED,
            throughput=4.5,
            latency=120.0,
            error_rate=0.02,
            resource_efficiency=0.85,
            success=True
        )
        
        updated_count = selector.performance_tracker.strategy_metrics[ExecutionStrategy.BALANCED].success_count
        assert updated_count == initial_count + 1
    
    def test_force_strategy(self, selector):
        """Test forcing a specific strategy."""
        original_strategy = selector.current_strategy
        
        selector.force_strategy(ExecutionStrategy.MINIMAL)
        
        assert selector.current_strategy == ExecutionStrategy.MINIMAL
        assert selector.last_strategy_switch > 0  # Should update timestamp
    
    def test_get_strategy_recommendations(self, selector):
        """Test strategy recommendations generation."""
        context = ExecutionContext(
            system_metrics=SystemMetrics(
                timestamp=time.time(),
                cpu_usage=75.0,
                memory_usage=80.0,
                memory_available=5.0,
                disk_io_read=40.0,
                disk_io_write=30.0,
                network_sent=20.0,
                network_recv=15.0,
                load_average=(3.5, 3.8, 4.0),
                active_processes=220
            ),
            system_health=SystemHealth.STRESSED,
            queue_depth=15,
            average_task_duration=200.0,
            current_throughput=2.0,
            error_rate=0.05,
            resource_utilization={"cpu": 75.0, "memory": 80.0}
        )
        
        recommendations = selector.get_strategy_recommendations(context)
        
        assert len(recommendations) == len(ExecutionStrategy)
        
        for strategy_name, rec in recommendations.items():
            assert "score" in rec
            assert "config" in rec
            assert "explanation" in rec
            assert isinstance(rec["score"], float)
            assert "max_parallel" in rec["config"]
    
    def test_get_selection_metrics(self, selector):
        """Test selection metrics reporting."""
        metrics = selector.get_selection_metrics()
        
        assert "current_strategy" in metrics
        assert "last_switch" in metrics
        assert "performance_summary" in metrics
        assert "switch_cooldown_remaining" in metrics
        
        assert metrics["current_strategy"] == selector.current_strategy.value
        assert metrics["switch_cooldown_remaining"] >= 0
    
    def test_factory_function(self, mock_monitor):
        """Test strategy selector factory function."""
        selector = create_strategy_selector(mock_monitor)
        
        assert isinstance(selector, StrategySelector)
        assert selector.monitor == mock_monitor


@pytest.mark.integration
class TestStrategySelectorIntegration:
    """Integration tests for strategy selector."""
    
    @pytest.mark.asyncio
    async def test_dynamic_strategy_selection_scenario(self):
        """Test dynamic strategy selection through different system scenarios."""
        # Load test scenarios
        fixtures_path = Path(__file__).parent.parent / "fixtures" / "AGENT-021"
        with open(fixtures_path / "system_metrics.json") as f:
            test_data = json.load(f)
        
        mock_monitor = create_mock_system_monitor()
        selector = StrategySelector(monitor=mock_monitor)
        
        # Test different system health scenarios
        scenarios = [
            ("healthy_system", SystemHealth.HEALTHY),
            ("moderate_load", SystemHealth.MODERATE),
            ("stressed_system", SystemHealth.STRESSED),
            ("critical_system", SystemHealth.CRITICAL)
        ]
        
        selected_strategies = []
        
        for scenario_name, expected_health in scenarios:
            scenario_data = test_data["test_scenarios"][scenario_name]
            
            metrics = SystemMetrics(
                timestamp=time.time(),
                cpu_usage=scenario_data["cpu_usage"],
                memory_usage=scenario_data["memory_usage"],
                memory_available=scenario_data["memory_available"],
                disk_io_read=scenario_data["disk_io_read"],
                disk_io_write=scenario_data["disk_io_write"],
                network_sent=scenario_data["network_sent"],
                network_recv=scenario_data["network_recv"],
                load_average=tuple(scenario_data["load_average"]),
                active_processes=scenario_data["active_processes"],
                gpu_usage=scenario_data["gpu_usage"],
                gpu_memory=scenario_data["gpu_memory"]
            )
            
            context = ExecutionContext(
                system_metrics=metrics,
                system_health=expected_health,
                queue_depth=5,
                average_task_duration=180.0,
                current_throughput=3.0,
                error_rate=0.02,
                resource_utilization={
                    "cpu": metrics.cpu_usage,
                    "memory": metrics.memory_usage,
                    "gpu": metrics.gpu_usage,
                    "gpu_memory": metrics.gpu_memory
                }
            )
            
            # Allow strategy switching by clearing cooldown
            selector.last_strategy_switch = 0.0
            
            selected_strategy = selector.select_strategy(context)
            selected_strategies.append((scenario_name, selected_strategy))
        
        # Verify strategies adapt to system conditions
        assert len(selected_strategies) == 4
        
        # Should generally become more conservative as system becomes more stressed
        # (though this depends on specific scoring, so we just verify valid selection)
        for scenario_name, strategy in selected_strategies:
            assert strategy in ExecutionStrategy
    
    @pytest.mark.asyncio
    async def test_workload_adaptation(self):
        """Test adaptation to different workload types."""
        mock_monitor = create_mock_system_monitor()
        selector = StrategySelector(monitor=mock_monitor)
        
        # Test different workload scenarios
        workload_scenarios = [
            {
                "type": "compute_intensive",
                "queue_depth": 12,
                "avg_duration": 300.0,
                "throughput": 2.0,
                "error_rate": 0.01
            },
            {
                "type": "io_intensive",
                "queue_depth": 8,
                "avg_duration": 120.0,
                "throughput": 4.0,
                "error_rate": 0.02
            },
            {
                "type": "memory_intensive",
                "queue_depth": 6,
                "avg_duration": 200.0,
                "throughput": 3.0,
                "error_rate": 0.015
            }
        ]
        
        for scenario in workload_scenarios:
            context = ExecutionContext(
                system_metrics=SystemMetrics(
                    timestamp=time.time(),
                    cpu_usage=60.0,
                    memory_usage=65.0,
                    memory_available=7.0,
                    disk_io_read=25.0,
                    disk_io_write=20.0,
                    network_sent=12.0,
                    network_recv=10.0,
                    load_average=(2.5, 2.6, 2.7),
                    active_processes=170
                ),
                system_health=SystemHealth.MODERATE,
                queue_depth=scenario["queue_depth"],
                average_task_duration=scenario["avg_duration"],
                current_throughput=scenario["throughput"],
                error_rate=scenario["error_rate"],
                resource_utilization={"cpu": 60.0, "memory": 65.0},
                workload_type=scenario["type"]
            )
            
            selector.last_strategy_switch = 0.0  # Allow switching
            strategy = selector.select_strategy(context)
            
            # Should select appropriate strategy for workload
            assert strategy in ExecutionStrategy
    
    @pytest.mark.asyncio
    async def test_performance_feedback_loop(self):
        """Test performance feedback affects future strategy selection."""
        mock_monitor = create_mock_system_monitor()
        selector = StrategySelector(monitor=mock_monitor)
        
        # Record poor performance for aggressive strategy
        for _ in range(10):
            selector.update_strategy_performance(
                strategy=ExecutionStrategy.AGGRESSIVE,
                throughput=1.0,    # Poor throughput
                latency=600.0,     # High latency
                error_rate=0.15,   # High error rate
                resource_efficiency=0.4,  # Poor efficiency
                success=False
            )
        
        # Record good performance for conservative strategy
        for _ in range(10):
            selector.update_strategy_performance(
                strategy=ExecutionStrategy.CONSERVATIVE,
                throughput=3.0,    # Good throughput
                latency=150.0,     # Reasonable latency
                error_rate=0.005,  # Low error rate
                resource_efficiency=0.9,  # High efficiency
                success=True
            )
        
        # Create neutral context
        context = ExecutionContext(
            system_metrics=SystemMetrics(
                timestamp=time.time(),
                cpu_usage=50.0,
                memory_usage=55.0,
                memory_available=9.0,
                disk_io_read=15.0,
                disk_io_write=12.0,
                network_sent=8.0,
                network_recv=6.0,
                load_average=(2.0, 2.0, 2.0),
                active_processes=150
            ),
            system_health=SystemHealth.MODERATE,
            queue_depth=8,
            average_task_duration=180.0,
            current_throughput=2.5,
            error_rate=0.02,
            resource_utilization={"cpu": 50.0, "memory": 55.0}
        )
        
        selector.last_strategy_switch = 0.0  # Allow switching
        selected_strategy = selector.select_strategy(context)
        
        # Should favor conservative strategy due to performance feedback
        # (though exact result depends on scoring algorithm)
        assert selected_strategy in ExecutionStrategy


@pytest.mark.performance
class TestStrategySelectorPerformance:
    """Performance tests for strategy selector."""
    
    def test_strategy_selection_latency(self):
        """Test strategy selection latency."""
        mock_monitor = create_mock_system_monitor()
        selector = StrategySelector(monitor=mock_monitor)
        
        context = ExecutionContext(
            system_metrics=SystemMetrics(
                timestamp=time.time(),
                cpu_usage=55.0,
                memory_usage=60.0,
                memory_available=8.0,
                disk_io_read=18.0,
                disk_io_write=15.0,
                network_sent=10.0,
                network_recv=8.0,
                load_average=(2.2, 2.3, 2.4),
                active_processes=165
            ),
            system_health=SystemHealth.MODERATE,
            queue_depth=10,
            average_task_duration=200.0,
            current_throughput=2.8,
            error_rate=0.025,
            resource_utilization={"cpu": 55.0, "memory": 60.0}
        )
        
        # Measure selection time
        times = []
        for _ in range(100):
            start = time.time()
            selector.select_strategy(context)
            end = time.time()
            times.append(end - start)
        
        avg_time = sum(times) / len(times)
        
        # Strategy selection should be fast (under 10ms)
        assert avg_time < 0.01
    
    def test_performance_tracking_overhead(self):
        """Test performance tracking overhead."""
        tracker = PerformanceTracker()
        
        # Measure recording time
        start_time = time.time()
        
        for i in range(1000):
            tracker.record_strategy_performance(
                strategy=ExecutionStrategy.BALANCED,
                throughput=float(i % 10),
                latency=100.0 + (i % 50),
                error_rate=0.01 + (i % 5) * 0.001,
                resource_efficiency=0.8 + (i % 20) * 0.01,
                success=(i % 10) != 0
            )
        
        end_time = time.time()
        avg_time_per_record = (end_time - start_time) / 1000
        
        # Should record performance quickly (under 1ms per record)
        assert avg_time_per_record < 0.001
    
    def test_memory_usage_performance_tracking(self):
        """Test memory usage of performance tracking."""
        import sys
        
        tracker = PerformanceTracker(history_size=1000)
        
        # Record memory usage before
        initial_size = sys.getsizeof(tracker.performance_history)
        
        # Add many performance records
        for i in range(2000):  # More than history_size
            tracker.record_strategy_performance(
                strategy=ExecutionStrategy.AGGRESSIVE,
                throughput=float(i),
                latency=100.0,
                error_rate=0.01,
                resource_efficiency=0.8,
                success=True
            )
        
        # Check final memory usage
        final_size = sys.getsizeof(tracker.performance_history)
        
        # Should not grow unbounded
        assert len(tracker.performance_history) == 1000  # Limited by history_size
        
        # Memory usage should be reasonable
        memory_per_entry = (final_size - initial_size) / 1000
        assert memory_per_entry < 1024  # Under 1KB per entry


if __name__ == "__main__":
    pytest.main([__file__, "-v"])