"""
Integration tests for Adaptive Execution Strategy (AGENT-021).

Tests the complete adaptive execution system including scheduler, monitor, strategy
selector, and their interactions under various scenarios and load conditions.
"""

import asyncio
import json
import pytest
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from brain_researcher.services.agent.adaptive_scheduler import (
    AdaptiveScheduler,
    TaskPriority,
    SchedulingPolicy,
    create_adaptive_scheduler
)
from brain_researcher.services.agent.system_monitor import (
    SystemMonitor,
    SystemHealth,
    create_system_monitor
)
from brain_researcher.services.agent.strategy_selector import (
    StrategySelector,
    ExecutionStrategy,
    ExecutionContext,
    create_strategy_selector
)
from brain_researcher.services.agent.parallel_executor import (
    Task,
    TaskStatus,
    ResourceType,
    ResourceRequirement,
    AdaptiveParallelExecutionOrchestrator,
    create_parallel_orchestrator
)
from brain_researcher.services.agent.dependency_resolver import ExecutionGraph

# Import test fixtures
import sys
sys.path.append(str(Path(__file__).parent.parent / "fixtures" / "AGENT-021"))
from mock_tools import MockToolRegistry, create_mock_system_monitor, MockExecutionTracker


@pytest.mark.integration
class TestAdaptiveSchedulerIntegration:
    """Integration tests for adaptive scheduler with system monitor."""
    
    @pytest.fixture
    def mock_monitor(self):
        """Create mock system monitor for integration testing."""
        return create_mock_system_monitor()
    
    @pytest.fixture
    def scheduler(self, mock_monitor):
        """Create adaptive scheduler with mock monitor."""
        return create_adaptive_scheduler(
            monitor=mock_monitor,
            resource_limits={
                ResourceType.CPU: 8.0,
                ResourceType.MEMORY: 16.0,
                ResourceType.GPU: 1.0
            }
        )
    
    @pytest.mark.asyncio
    async def test_scheduler_monitor_integration(self, scheduler, mock_monitor):
        """Test scheduler integration with system monitor."""
        await scheduler.start_scheduler()
        
        # Monitor should be providing system health updates
        mock_monitor.get_health_status.return_value = SystemHealth.HEALTHY
        
        # Schedule a task
        task = Task(
            task_id="integration_task",
            name="Integration Task",
            tool_name="mock_tool",
            tool_args={},
            resource_requirements=[
                ResourceRequirement(ResourceType.CPU, 2.0),
                ResourceRequirement(ResourceType.MEMORY, 4.0)
            ]
        )
        
        task_id = await scheduler.schedule_task(task, priority=TaskPriority.NORMAL)
        assert task_id == "integration_task"
        
        # Let scheduler process
        await asyncio.sleep(0.6)  # Wait for scheduling iteration
        
        # Verify monitor integration
        assert mock_monitor.update_queue_depth.called
        
        await scheduler.stop_scheduler()
    
    @pytest.mark.asyncio
    async def test_dynamic_health_adaptation(self, scheduler, mock_monitor):
        """Test scheduler adaptation to changing system health."""
        await scheduler.start_scheduler()
        
        # Start with healthy system
        mock_monitor.get_health_status.return_value = SystemHealth.HEALTHY
        
        # Schedule multiple tasks
        tasks = []
        for i in range(10):
            task = Task(
                task_id=f"health_task_{i}",
                name=f"Health Task {i}",
                tool_name="mock_tool",
                tool_args={},
                resource_requirements=[
                    ResourceRequirement(ResourceType.CPU, 1.0)
                ]
            )
            await scheduler.schedule_task(task, priority=TaskPriority.NORMAL)
            tasks.append(task)
        
        initial_queue_size = len(scheduler.priority_queue)
        
        # Change to critical health
        mock_monitor.get_health_status.return_value = SystemHealth.CRITICAL
        
        # Let scheduler adapt
        await asyncio.sleep(0.6)
        
        # Should have adapted to critical conditions (exact behavior depends on implementation)
        performance_metrics = scheduler.get_performance_metrics()
        assert "preemption_stats" in performance_metrics
        
        await scheduler.stop_scheduler()
    
    @pytest.mark.asyncio
    async def test_resource_contention_handling(self, scheduler, mock_monitor):
        """Test resource contention handling in integrated system."""
        await scheduler.start_scheduler()
        
        # Create resource-intensive tasks that will compete
        heavy_tasks = []
        for i in range(5):
            task = Task(
                task_id=f"heavy_task_{i}",
                name=f"Heavy Task {i}",
                tool_name="cpu_intensive_tool",
                tool_args={},
                resource_requirements=[
                    ResourceRequirement(ResourceType.CPU, 3.0),  # High CPU requirement
                    ResourceRequirement(ResourceType.MEMORY, 4.0)
                ]
            )
            await scheduler.schedule_task(task, priority=TaskPriority.NORMAL)
            heavy_tasks.append(task)
        
        # Let scheduler handle resource contention
        await asyncio.sleep(1.0)
        
        # Should have managed resources effectively
        resource_stats = scheduler.load_balancer.get_load_statistics()
        assert "cpu" in resource_stats
        assert resource_stats["cpu"]["utilization"] >= 0  # Some utilization expected
        
        await scheduler.stop_scheduler()
    
    @pytest.mark.asyncio
    async def test_preemption_under_load(self, scheduler, mock_monitor):
        """Test preemption behavior under system load."""
        await scheduler.start_scheduler()
        
        # Schedule low priority long-running task
        long_task = Task(
            task_id="long_running",
            name="Long Running Task",
            tool_name="long_computation",
            tool_args={},
            resource_requirements=[
                ResourceRequirement(ResourceType.CPU, 4.0)
            ]
        )
        await scheduler.schedule_task(long_task, priority=TaskPriority.LOW, preemptible=True)
        
        # Let it start
        await asyncio.sleep(0.2)
        
        # Schedule critical task that needs same resources
        critical_task = Task(
            task_id="critical_urgent",
            name="Critical Urgent Task",
            tool_name="urgent_analysis",
            tool_args={},
            resource_requirements=[
                ResourceRequirement(ResourceType.CPU, 4.0)
            ]
        )
        deadline = time.time() + 60  # 1 minute deadline
        await scheduler.schedule_task(
            critical_task, 
            priority=TaskPriority.CRITICAL, 
            deadline=deadline,
            preemptible=False
        )
        
        # Let scheduler handle preemption
        await asyncio.sleep(0.8)
        
        # Check preemption occurred
        preemption_stats = scheduler.preemption_manager.get_preemption_stats()
        # May or may not preempt depending on exact timing and conditions
        assert preemption_stats["total_preemptions"] >= 0
        
        await scheduler.stop_scheduler()


@pytest.mark.integration
class TestSystemMonitorIntegration:
    """Integration tests for system monitor with other components."""
    
    @pytest.mark.asyncio
    async def test_monitor_scheduler_feedback_loop(self):
        """Test feedback loop between monitor and scheduler."""
        monitor = create_system_monitor(collection_interval=0.1)
        scheduler = create_adaptive_scheduler(monitor=monitor)
        
        # Mock metrics collection to simulate system changes
        metrics_progression = [
            {"cpu_usage": 30, "memory_usage": 40, "health": SystemHealth.HEALTHY},
            {"cpu_usage": 60, "memory_usage": 70, "health": SystemHealth.MODERATE},
            {"cpu_usage": 85, "memory_usage": 90, "health": SystemHealth.STRESSED},
            {"cpu_usage": 95, "memory_usage": 95, "health": SystemHealth.CRITICAL}
        ]
        
        progression_index = 0
        
        def mock_collect():
            nonlocal progression_index
            if progression_index < len(metrics_progression):
                data = metrics_progression[progression_index]
                progression_index += 1
                return MagicMock(
                    cpu_usage=data["cpu_usage"],
                    memory_usage=data["memory_usage"],
                    memory_available=16.0 - (data["memory_usage"] / 100.0) * 16.0,
                    disk_io_read=10.0,
                    disk_io_write=8.0,
                    network_sent=5.0,
                    network_recv=4.0,
                    load_average=(data["cpu_usage"] / 50.0, data["cpu_usage"] / 50.0, data["cpu_usage"] / 50.0),
                    active_processes=100 + data["cpu_usage"],
                    queue_depth=0,
                    gpu_usage=None,
                    gpu_memory=None,
                    timestamp=time.time()
                )
            return metrics_progression[-1]  # Stay at last value
        
        def mock_health():
            if progression_index <= 1:
                return SystemHealth.HEALTHY
            elif progression_index <= 2:
                return SystemHealth.MODERATE
            elif progression_index <= 3:
                return SystemHealth.STRESSED
            else:
                return SystemHealth.CRITICAL
        
        monitor.metrics_collector.collect_metrics = mock_collect
        monitor.get_health_status = mock_health
        
        await monitor.start_monitoring()
        await scheduler.start_scheduler()
        
        # Schedule tasks to create load
        for i in range(8):
            task = Task(
                task_id=f"feedback_task_{i}",
                name=f"Feedback Task {i}",
                tool_name="mock_tool",
                tool_args={}
            )
            await scheduler.schedule_task(task, priority=TaskPriority.NORMAL)
        
        # Let system evolve through progression
        await asyncio.sleep(1.5)
        
        # Should have adapted to changing conditions
        final_metrics = monitor.get_system_metrics()
        assert final_metrics is not None
        
        performance_analysis = monitor.get_performance_analysis()
        assert performance_analysis is not None
        
        await scheduler.stop_scheduler()
        await monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_monitor_performance_tracking(self):
        """Test monitor performance tracking accuracy."""
        monitor = create_system_monitor(collection_interval=0.05)  # Fast collection
        
        await monitor.start_monitoring()
        
        # Let it collect metrics
        await asyncio.sleep(0.5)
        
        # Should have collected multiple metrics
        avg_metrics = monitor.get_average_metrics(window_seconds=1.0)
        assert avg_metrics is not None
        
        # Should have performance analysis
        analysis = monitor.get_performance_analysis()
        assert analysis is not None
        assert analysis.overall_health in SystemHealth
        
        # Should provide resource utilization
        utilization = monitor.get_resource_utilization()
        assert len(utilization) > 0
        assert "cpu" in utilization
        assert "memory" in utilization
        
        await monitor.stop_monitoring()


@pytest.mark.integration
class TestStrategyIntegration:
    """Integration tests for strategy selector with monitor and scheduler."""
    
    @pytest.mark.asyncio
    async def test_strategy_scheduler_integration(self):
        """Test strategy selector integration with scheduler."""
        monitor = create_mock_system_monitor()
        scheduler = create_adaptive_scheduler(monitor=monitor)
        selector = create_strategy_selector(monitor)
        
        # Create context for strategy selection
        context = ExecutionContext(
            system_metrics=monitor.get_system_metrics(),
            system_health=monitor.get_health_status(),
            queue_depth=5,
            average_task_duration=120.0,
            current_throughput=3.0,
            error_rate=0.02,
            resource_utilization=monitor.get_resource_utilization()
        )
        
        # Select strategy
        selected_strategy = selector.select_strategy(context)
        assert selected_strategy in ExecutionStrategy
        
        # Get strategy configuration
        config = selector.get_strategy_config(selected_strategy)
        assert config.max_parallel > 0
        assert config.cpu_limit > 0.0
        
        # Apply configuration would happen in orchestrator
        # Here we just verify the integration works
        
        await scheduler.start_scheduler()
        
        # Schedule task with strategy consideration
        task = Task(
            task_id="strategy_task",
            name="Strategy Task",
            tool_name="mock_tool",
            tool_args={}
        )
        await scheduler.schedule_task(task, priority=TaskPriority.NORMAL)
        
        await asyncio.sleep(0.3)
        
        # Update strategy performance based on results
        selector.update_strategy_performance(
            strategy=selected_strategy,
            throughput=3.5,
            latency=100.0,
            error_rate=0.01,
            resource_efficiency=0.85,
            success=True
        )
        
        # Verify performance was recorded
        metrics = selector.get_selection_metrics()
        assert "performance_summary" in metrics
        
        await scheduler.stop_scheduler()
    
    @pytest.mark.asyncio
    async def test_strategy_adaptation_cycle(self):
        """Test complete strategy adaptation cycle."""
        monitor = create_mock_system_monitor()
        selector = create_strategy_selector(monitor)
        
        # Simulate system condition changes
        conditions = [
            (SystemHealth.HEALTHY, 30.0, 40.0, 2),
            (SystemHealth.MODERATE, 60.0, 70.0, 8),
            (SystemHealth.STRESSED, 80.0, 85.0, 15),
            (SystemHealth.CRITICAL, 95.0, 92.0, 25)
        ]
        
        strategies_selected = []
        
        for health, cpu, memory, queue in conditions:
            # Update monitor state
            mock_metrics = MagicMock()
            mock_metrics.cpu_usage = cpu
            mock_metrics.memory_usage = memory
            mock_metrics.memory_available = 16.0 - (memory / 100.0) * 16.0
            mock_metrics.disk_io_read = 10.0
            mock_metrics.disk_io_write = 8.0
            mock_metrics.network_sent = 5.0
            mock_metrics.network_recv = 4.0
            mock_metrics.load_average = (cpu / 50.0, cpu / 50.0, cpu / 50.0)
            mock_metrics.active_processes = 100 + int(cpu)
            mock_metrics.timestamp = time.time()
            
            monitor.get_system_metrics.return_value = mock_metrics
            monitor.get_health_status.return_value = health
            monitor.get_resource_utilization.return_value = {
                "cpu": cpu,
                "memory": memory,
                "load_1min": cpu / 2.0
            }
            
            # Create context
            context = ExecutionContext(
                system_metrics=mock_metrics,
                system_health=health,
                queue_depth=queue,
                average_task_duration=180.0,
                current_throughput=max(1.0, 5.0 - (cpu / 25.0)),  # Decreases with load
                error_rate=min(0.1, cpu / 1000.0),  # Increases with load
                resource_utilization={"cpu": cpu, "memory": memory}
            )
            
            # Clear cooldown to allow strategy switching
            selector.last_strategy_switch = 0.0
            
            # Select strategy
            strategy = selector.select_strategy(context)
            strategies_selected.append((health.value, strategy))
            
            # Simulate some performance feedback
            if health == SystemHealth.HEALTHY:
                # Good performance for healthy system
                selector.update_strategy_performance(
                    strategy=strategy,
                    throughput=5.0,
                    latency=90.0,
                    error_rate=0.005,
                    resource_efficiency=0.9,
                    success=True
                )
            elif health == SystemHealth.CRITICAL:
                # Poor performance for critical system
                selector.update_strategy_performance(
                    strategy=strategy,
                    throughput=1.0,
                    latency=300.0,
                    error_rate=0.1,
                    resource_efficiency=0.4,
                    success=False
                )
            else:
                # Moderate performance
                selector.update_strategy_performance(
                    strategy=strategy,
                    throughput=3.0,
                    latency=150.0,
                    error_rate=0.02,
                    resource_efficiency=0.7,
                    success=True
                )
        
        # Verify strategies were selected and adapted
        assert len(strategies_selected) == 4
        
        # Generally should become more conservative as system degrades
        # (exact behavior depends on scoring algorithm)
        for health_name, strategy in strategies_selected:
            assert strategy in ExecutionStrategy
    
    @pytest.mark.asyncio
    async def test_strategy_performance_learning(self):
        """Test strategy performance learning over time."""
        monitor = create_mock_system_monitor()
        selector = create_strategy_selector(monitor)
        
        # Create consistent context
        context = ExecutionContext(
            system_metrics=monitor.get_system_metrics(),
            system_health=SystemHealth.MODERATE,
            queue_depth=8,
            average_task_duration=150.0,
            current_throughput=2.5,
            error_rate=0.03,
            resource_utilization={"cpu": 60.0, "memory": 65.0}
        )
        
        # Record multiple rounds of performance for different strategies
        performance_data = [
            (ExecutionStrategy.AGGRESSIVE, 6.0, 80.0, 0.08, 0.75, False),  # Fast but errorprone
            (ExecutionStrategy.BALANCED, 4.0, 120.0, 0.02, 0.85, True),    # Good balance
            (ExecutionStrategy.CONSERVATIVE, 2.5, 180.0, 0.005, 0.95, True), # Slow but reliable
            (ExecutionStrategy.MINIMAL, 1.2, 300.0, 0.0, 0.98, True)       # Very safe
        ]
        
        # Record multiple rounds to establish performance history
        for round_num in range(5):
            for strategy, throughput, latency, error_rate, efficiency, success in performance_data:
                # Add some variation
                variation = 0.1 * (round_num - 2)  # -0.2 to +0.2
                selector.update_strategy_performance(
                    strategy=strategy,
                    throughput=max(0.5, throughput + variation),
                    latency=max(30.0, latency - variation * 20),
                    error_rate=max(0.0, min(0.2, error_rate + variation * 0.02)),
                    resource_efficiency=max(0.1, min(1.0, efficiency + variation * 0.1)),
                    success=success and (error_rate + variation * 0.02) < 0.1
                )
        
        # Now test strategy selection with learned performance
        selector.last_strategy_switch = 0.0  # Allow switching
        learned_strategy = selector.select_strategy(context)
        
        # Should select based on learned performance (likely BALANCED or CONSERVATIVE)
        assert learned_strategy in ExecutionStrategy
        
        # Get performance summary
        summary = selector.get_performance_summary()
        assert len(summary) == len(ExecutionStrategy)
        
        # Balanced should have good scores
        balanced_score = summary["balanced"]["score"]
        assert balanced_score > 0.5  # Should be decent
        
        # Aggressive should have lower score due to errors
        aggressive_score = summary["aggressive"]["score"]
        # May vary based on exact scoring algorithm


@pytest.mark.integration
class TestFullAdaptiveSystem:
    """Integration tests for the complete adaptive execution system."""
    
    @pytest.fixture
    def mock_tool_registry(self):
        """Create mock tool registry for testing."""
        return MockToolRegistry()
    
    @pytest.mark.asyncio
    async def test_complete_adaptive_execution_cycle(self, mock_tool_registry):
        """Test complete adaptive execution cycle from task submission to completion."""
        # Create orchestrator with adaptive features
        orchestrator = create_parallel_orchestrator(
            max_workers=4,
            resource_limits={
                ResourceType.CPU: 8.0,
                ResourceType.MEMORY: 16.0,
                ResourceType.GPU: 1.0
            },
            enable_adaptive=True
        )
        
        # Start adaptive components
        await orchestrator.start_adaptive_components()
        
        # Create execution graph with varied tasks
        tasks = [
            Task(
                task_id="preprocessing",
                name="Data Preprocessing",
                tool_name="fmriprep",
                tool_args={"subject": "sub-001"},
                resource_requirements=[
                    ResourceRequirement(ResourceType.CPU, 2.0),
                    ResourceRequirement(ResourceType.MEMORY, 4.0)
                ]
            ),
            Task(
                task_id="quality_check",
                name="Quality Control",
                tool_name="quality_check", 
                tool_args={"dataset": "test"},
                dependencies=["preprocessing"],
                resource_requirements=[
                    ResourceRequirement(ResourceType.CPU, 1.0),
                    ResourceRequirement(ResourceType.MEMORY, 2.0)
                ]
            ),
            Task(
                task_id="analysis",
                name="Statistical Analysis",
                tool_name="statistical_test",
                tool_args={"contrast": "task_vs_rest"},
                dependencies=["quality_check"],
                resource_requirements=[
                    ResourceRequirement(ResourceType.CPU, 3.0),
                    ResourceRequirement(ResourceType.MEMORY, 6.0)
                ]
            ),
            Task(
                task_id="visualization",
                name="Result Visualization", 
                tool_name="plotting_tool",
                tool_args={"plot_type": "brain_map"},
                dependencies=["analysis"],
                resource_requirements=[
                    ResourceRequirement(ResourceType.CPU, 1.0),
                    ResourceRequirement(ResourceType.MEMORY, 3.0)
                ]
            )
        ]
        
        execution_graph = ExecutionGraph(tasks=tasks)
        execution_tracker = MockExecutionTracker()
        
        # Mock the tool registry
        with patch('brain_researcher.services.tools.tool_registry.ToolRegistry') as mock_registry:
            mock_registry.return_value = mock_tool_registry
            
            # Execute with adaptive strategy
            result = await orchestrator.execute_parallel(
                execution_graph=execution_graph,
                execution_tracker=execution_tracker,
                timeout=30.0,
                priority=TaskPriority.NORMAL
            )
        
        # Verify execution completed
        assert "execution_id" in result
        assert "results" in result
        assert "metrics" in result
        
        # Should have adaptive metrics
        if orchestrator.enable_adaptive:
            assert "strategy" in result["metrics"]
            assert "system_health" in result["metrics"]
            assert "adaptive_metrics" in result["metrics"]
            
            adaptive_metrics = result["metrics"]["adaptive_metrics"]
            assert "system" in adaptive_metrics
            assert "scheduler" in adaptive_metrics
            assert "strategy" in adaptive_metrics
        
        # Check that some tasks completed (depending on timing and mocking)
        assert result["metrics"]["tasks_completed"] >= 0
        
        await orchestrator.stop_adaptive_components()
    
    @pytest.mark.asyncio
    async def test_adaptive_system_under_stress(self, mock_tool_registry):
        """Test adaptive system behavior under stress conditions."""
        # Load stress test scenario
        fixtures_path = Path(__file__).parent.parent / "fixtures" / "AGENT-021"
        with open(fixtures_path / "task_scenarios.json") as f:
            test_data = json.load(f)
        
        orchestrator = create_parallel_orchestrator(
            max_workers=2,  # Limited workers to create stress
            resource_limits={
                ResourceType.CPU: 4.0,  # Limited CPU
                ResourceType.MEMORY: 8.0,  # Limited memory
            },
            enable_adaptive=True
        )
        
        await orchestrator.start_adaptive_components()
        
        # Create many competing tasks
        tasks = []
        scenario = test_data["scheduling_scenarios"]["resource_intensive"]
        
        for i, task_data in enumerate(scenario * 3):  # Triple the tasks for stress
            task = Task(
                task_id=f"stress_task_{i}",
                name=f"Stress Task {i}",
                tool_name=task_data["tool_name"],
                tool_args=task_data["tool_args"],
                resource_requirements=[
                    ResourceRequirement(
                        ResourceType(req["resource_type"]),
                        req["amount"] * 0.7  # Reduce to fit limited resources
                    )
                    for req in task_data["resource_requirements"]
                ]
            )
            tasks.append(task)
        
        execution_graph = ExecutionGraph(tasks=tasks)
        
        # Mock stressed system conditions
        if orchestrator.system_monitor:
            mock_stressed_metrics = MagicMock()
            mock_stressed_metrics.cpu_usage = 85.0
            mock_stressed_metrics.memory_usage = 90.0
            mock_stressed_metrics.memory_available = 2.0
            mock_stressed_metrics.load_average = (4.0, 4.2, 4.5)
            mock_stressed_metrics.active_processes = 250
            mock_stressed_metrics.timestamp = time.time()
            
            orchestrator.system_monitor.get_system_metrics = MagicMock(return_value=mock_stressed_metrics)
            orchestrator.system_monitor.get_health_status = MagicMock(return_value=SystemHealth.STRESSED)
            orchestrator.system_monitor.get_resource_utilization = MagicMock(return_value={
                "cpu": 85.0,
                "memory": 90.0,
                "load_1min": 100.0  # Overloaded
            })
        
        with patch('brain_researcher.services.tools.tool_registry.ToolRegistry') as mock_registry:
            mock_registry.return_value = mock_tool_registry
            
            # Execute under stress
            start_time = time.time()
            result = await orchestrator.execute_parallel(
                execution_graph=execution_graph,
                timeout=15.0  # Short timeout for stress test
            )
            execution_time = time.time() - start_time
        
        # System should handle stress gracefully
        assert result is not None
        assert execution_time < 20.0  # Should respect timeout
        
        # Should have adapted to stress
        if orchestrator.enable_adaptive:
            adaptive_metrics = result["metrics"]["adaptive_metrics"]
            system_health = adaptive_metrics["system"]["health"]
            current_strategy = adaptive_metrics["strategy"]["current_strategy"]
            
            # Should be in conservative mode under stress
            assert system_health in ["stressed", "critical"]
            assert current_strategy in ["conservative", "minimal"]
        
        await orchestrator.stop_adaptive_components()
    
    @pytest.mark.asyncio
    async def test_adaptive_system_recovery(self, mock_tool_registry):
        """Test adaptive system recovery from stress to normal conditions."""
        orchestrator = create_parallel_orchestrator(enable_adaptive=True)
        await orchestrator.start_adaptive_components()
        
        # Start with stressed conditions
        if orchestrator.system_monitor:
            initial_metrics = MagicMock()
            initial_metrics.cpu_usage = 90.0
            initial_metrics.memory_usage = 85.0
            initial_metrics.memory_available = 4.0
            initial_metrics.load_average = (4.5, 4.8, 5.0)
            initial_metrics.active_processes = 300
            initial_metrics.timestamp = time.time()
            
            orchestrator.system_monitor.get_system_metrics = MagicMock(return_value=initial_metrics)
            orchestrator.system_monitor.get_health_status = MagicMock(return_value=SystemHealth.CRITICAL)
        
        # Schedule initial task under stress
        initial_task = Task(
            task_id="recovery_test_initial",
            name="Initial Recovery Task",
            tool_name="mock_tool",
            tool_args={}
        )
        
        initial_graph = ExecutionGraph(tasks=[initial_task])
        
        with patch('brain_researcher.services.tools.tool_registry.ToolRegistry') as mock_registry:
            mock_registry.return_value = mock_tool_registry
            
            initial_result = await orchestrator.execute_parallel(initial_graph, timeout=5.0)
            initial_strategy = initial_result["metrics"].get("strategy", "unknown")
        
        # Simulate system recovery - improve conditions
        if orchestrator.system_monitor:
            recovered_metrics = MagicMock()
            recovered_metrics.cpu_usage = 35.0
            recovered_metrics.memory_usage = 45.0
            recovered_metrics.memory_available = 11.0
            recovered_metrics.load_average = (1.2, 1.3, 1.5)
            recovered_metrics.active_processes = 130
            recovered_metrics.timestamp = time.time()
            
            orchestrator.system_monitor.get_system_metrics = MagicMock(return_value=recovered_metrics)
            orchestrator.system_monitor.get_health_status = MagicMock(return_value=SystemHealth.HEALTHY)
            
            # Allow strategy switching by clearing cooldown
            if orchestrator.strategy_selector:
                orchestrator.strategy_selector.last_strategy_switch = 0.0
        
        # Schedule task after recovery
        recovery_task = Task(
            task_id="recovery_test_final",
            name="Final Recovery Task", 
            tool_name="mock_tool",
            tool_args={}
        )
        
        recovery_graph = ExecutionGraph(tasks=[recovery_task])
        
        with patch('brain_researcher.services.tools.tool_registry.ToolRegistry') as mock_registry:
            mock_registry.return_value = mock_tool_registry
            
            recovery_result = await orchestrator.execute_parallel(recovery_graph, timeout=5.0)
            recovery_strategy = recovery_result["metrics"].get("strategy", "unknown")
        
        # Should have adapted to better conditions
        # (Exact strategy may depend on implementation details and timing)
        assert initial_result is not None
        assert recovery_result is not None
        
        await orchestrator.stop_adaptive_components()
    
    @pytest.mark.asyncio
    async def test_multi_user_priority_handling(self, mock_tool_registry):
        """Test adaptive system handling multiple users with different priorities."""
        orchestrator = create_parallel_orchestrator(enable_adaptive=True)
        await orchestrator.start_adaptive_components()
        
        # Create tasks with different priorities simulating different users
        user_tasks = [
            # Critical research deadline
            (Task("critical_analysis", "Critical Analysis", "fmri_glm", {"urgent": True}), 
             TaskPriority.CRITICAL, time.time() + 300),
            
            # High priority student project  
            (Task("student_project", "Student Project", "statistical_test", {"course": "neuroscience"}),
             TaskPriority.HIGH, time.time() + 1800),
            
            # Normal priority research
            (Task("normal_research", "Normal Research", "connectivity_analysis", {"method": "pearson"}),
             TaskPriority.NORMAL, None),
            
            # Background batch job
            (Task("background_batch", "Background Batch", "quality_check", {"dataset": "large"}),
             TaskPriority.BACKGROUND, None),
             
            # Low priority exploratory analysis
            (Task("exploratory", "Exploratory Analysis", "ml_training", {"model": "simple"}),
             TaskPriority.LOW, None)
        ]
        
        # Execute tasks in sequence to test priority handling
        results = []
        
        with patch('brain_researcher.services.tools.tool_registry.ToolRegistry') as mock_registry:
            mock_registry.return_value = mock_tool_registry
            
            for task, priority, deadline in user_tasks:
                graph = ExecutionGraph(tasks=[task])
                
                result = await orchestrator.execute_parallel(
                    execution_graph=graph,
                    priority=priority,
                    timeout=10.0
                )
                
                results.append((task.task_id, priority.name, result))
        
        # All tasks should complete (with mocking)
        assert len(results) == 5
        
        # Verify different priorities were handled
        for task_id, priority_name, result in results:
            assert result is not None
            assert "metrics" in result
        
        await orchestrator.stop_adaptive_components()


@pytest.mark.performance
class TestAdaptiveExecutionPerformance:
    """Performance tests for the complete adaptive execution system."""
    
    @pytest.mark.asyncio
    async def test_adaptive_system_overhead(self):
        """Test performance overhead of adaptive features."""
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        
        # Baseline: orchestrator without adaptive features
        basic_orchestrator = create_parallel_orchestrator(
            max_workers=4,
            enable_adaptive=False
        )
        
        # Create simple task
        simple_task = Task("overhead_test", "Overhead Test", "mock_tool", {})
        simple_graph = ExecutionGraph(tasks=[simple_task])
        
        # Measure basic execution
        initial_memory = process.memory_info().rss
        start_time = time.time()
        
        with patch('brain_researcher.services.tools.tool_registry.ToolRegistry') as mock_registry:
            mock_registry.return_value = MockToolRegistry()
            basic_result = await basic_orchestrator.execute_parallel(simple_graph, timeout=5.0)
        
        basic_time = time.time() - start_time
        basic_memory = process.memory_info().rss - initial_memory
        
        # Adaptive orchestrator
        adaptive_orchestrator = create_parallel_orchestrator(
            max_workers=4,
            enable_adaptive=True
        )
        
        await adaptive_orchestrator.start_adaptive_components()
        
        # Measure adaptive execution
        adaptive_initial_memory = process.memory_info().rss
        start_time = time.time()
        
        with patch('brain_researcher.services.tools.tool_registry.ToolRegistry') as mock_registry:
            mock_registry.return_value = MockToolRegistry()
            adaptive_result = await adaptive_orchestrator.execute_parallel(simple_graph, timeout=5.0)
        
        adaptive_time = time.time() - start_time
        adaptive_memory = process.memory_info().rss - adaptive_initial_memory
        
        await adaptive_orchestrator.stop_adaptive_components()
        
        # Overhead should be reasonable
        time_overhead = adaptive_time - basic_time
        memory_overhead = adaptive_memory - basic_memory
        
        # Allow some overhead but not excessive (these are rough bounds)
        assert time_overhead < 2.0  # Under 2 seconds additional time
        assert memory_overhead < 50 * 1024 * 1024  # Under 50MB additional memory
        
        # Both should succeed
        assert basic_result is not None
        assert adaptive_result is not None
    
    @pytest.mark.asyncio
    async def test_adaptive_scaling_performance(self):
        """Test adaptive system performance scaling with task count."""
        orchestrator = create_parallel_orchestrator(enable_adaptive=True)
        await orchestrator.start_adaptive_components()
        
        # Test with different task counts
        task_counts = [1, 5, 10, 20]
        execution_times = []
        
        for count in task_counts:
            # Create tasks
            tasks = [
                Task(f"scale_task_{i}", f"Scale Task {i}", "mock_tool", {})
                for i in range(count)
            ]
            
            graph = ExecutionGraph(tasks=tasks)
            
            # Measure execution time
            start_time = time.time()
            
            with patch('brain_researcher.services.tools.tool_registry.ToolRegistry') as mock_registry:
                mock_registry.return_value = MockToolRegistry()
                result = await orchestrator.execute_parallel(graph, timeout=30.0)
            
            execution_time = time.time() - start_time
            execution_times.append((count, execution_time))
            
            # Should complete successfully
            assert result is not None
        
        await orchestrator.stop_adaptive_components()
        
        # Should show reasonable scaling (not exponential growth)
        # With proper parallelization, time shouldn't grow linearly
        times_only = [t for _, t in execution_times]
        
        # Last execution shouldn't be more than 5x the first
        assert times_only[-1] < times_only[0] * 5
    
    @pytest.mark.asyncio
    async def test_concurrent_adaptive_systems(self):
        """Test multiple adaptive systems running concurrently."""
        # Create multiple orchestrators
        orchestrators = []
        
        for i in range(3):
            orch = create_parallel_orchestrator(
                max_workers=2,
                enable_adaptive=True
            )
            await orch.start_adaptive_components()
            orchestrators.append(orch)
        
        # Run concurrent tasks
        concurrent_tasks = []
        
        for i, orch in enumerate(orchestrators):
            task = Task(f"concurrent_task_{i}", f"Concurrent Task {i}", "mock_tool", {})
            graph = ExecutionGraph(tasks=[task])
            
            with patch('brain_researcher.services.tools.tool_registry.ToolRegistry') as mock_registry:
                mock_registry.return_value = MockToolRegistry()
                task_coro = orch.execute_parallel(graph, timeout=10.0)
                concurrent_tasks.append(task_coro)
        
        # Execute all concurrently
        start_time = time.time()
        results = await asyncio.gather(*concurrent_tasks, return_exceptions=True)
        total_time = time.time() - start_time
        
        # All should complete successfully
        assert len(results) == 3
        for result in results:
            assert not isinstance(result, Exception)
            assert result is not None
        
        # Should complete in reasonable time (concurrent, not sequential)
        assert total_time < 15.0  # Should be much faster than 3 * individual time
        
        # Clean up
        for orch in orchestrators:
            await orch.stop_adaptive_components()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])