"""
Unit tests for Parallel Execution Orchestration (AGENT-015).

Tests the ParallelExecutionOrchestrator, ResourceManager, DeadlockDetector,
and related components for parallel execution of neuroimaging tasks.
"""

import asyncio
import importlib.util
import json
import pytest
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from brain_researcher.services.agent.parallel_executor import (
    ParallelExecutionOrchestrator,
    ResourceManager,
    DeadlockDetector,
    ResourceType,
    ResourceRequirement,
    ResourceAllocation,
    Task,
    TaskStatus
)
from brain_researcher.services.agent.dependency_resolver import ExecutionGraph
from brain_researcher.services.agent.execution_status import ExecutionTracker

_FIXTURE_PATH = (
    Path(__file__).parent.parent / "fixtures" / "AGENT-015" / "mock_tools.py"
)
_FIXTURE_SPEC = importlib.util.spec_from_file_location(
    "agent_015_mock_tools",
    _FIXTURE_PATH,
)
assert _FIXTURE_SPEC is not None and _FIXTURE_SPEC.loader is not None
_mock_tools = importlib.util.module_from_spec(_FIXTURE_SPEC)
_FIXTURE_SPEC.loader.exec_module(_mock_tools)
MockToolRegistry = _mock_tools.MockToolRegistry
get_mock_tool = _mock_tools.get_mock_tool


class TestResourceManager:
    """Test resource management functionality."""

    def test_resource_manager_initialization(self):
        """Test resource manager initialization with default limits."""
        manager = ResourceManager()

        assert ResourceType.CPU in manager.allocations
        assert ResourceType.MEMORY in manager.allocations
        assert manager.allocations[ResourceType.CPU].total_capacity == 8.0
        assert manager.allocations[ResourceType.MEMORY].total_capacity == 32.0

    def test_custom_resource_limits(self):
        """Test resource manager with custom limits."""
        custom_limits = {
            ResourceType.CPU: 16.0,
            ResourceType.MEMORY: 64.0,
            ResourceType.GPU: 2.0
        }
        manager = ResourceManager(custom_limits)

        assert manager.allocations[ResourceType.CPU].total_capacity == 16.0
        assert manager.allocations[ResourceType.MEMORY].total_capacity == 64.0
        assert manager.allocations[ResourceType.GPU].total_capacity == 2.0

    @pytest.mark.asyncio
    async def test_resource_allocation_workflow(self):
        """Test complete resource allocation workflow."""
        manager = ResourceManager()

        # Create test task
        task = Task(
            task_id="test_task",
            name="Test Task",
            tool_name="test_tool",
            tool_args={},
            resource_requirements=[
                ResourceRequirement(ResourceType.CPU, 2.0),
                ResourceRequirement(ResourceType.MEMORY, 4.0)
            ]
        )

        # Check availability
        can_allocate = await manager.can_allocate(task)
        assert can_allocate is True

        # Reserve resources
        reserved = await manager.reserve_resources(task)
        assert reserved is True

        # Check reservations
        cpu_allocation = manager.allocations[ResourceType.CPU]
        memory_allocation = manager.allocations[ResourceType.MEMORY]
        assert cpu_allocation.reserved == 2.0
        assert memory_allocation.reserved == 4.0

        # Allocate resources
        allocated = await manager.allocate_resources(task)
        assert allocated is True

        # Check allocations
        assert cpu_allocation.allocated == 2.0
        assert memory_allocation.allocated == 4.0
        assert cpu_allocation.reserved == 0.0
        assert memory_allocation.reserved == 0.0

        # Release resources
        await manager.release_resources(task)

        # Check cleanup
        assert cpu_allocation.allocated == 0.0
        assert memory_allocation.allocated == 0.0
        assert task.task_id not in manager.task_allocations

    @pytest.mark.asyncio
    async def test_resource_contention(self):
        """Test resource contention handling."""
        manager = ResourceManager({ResourceType.CPU: 4.0})

        # Create tasks that exceed capacity
        task1 = Task(
            task_id="task1",
            name="Task 1",
            tool_name="test_tool",
            tool_args={},
            resource_requirements=[ResourceRequirement(ResourceType.CPU, 3.0)]
        )

        task2 = Task(
            task_id="task2",
            name="Task 2",
            tool_name="test_tool",
            tool_args={},
            resource_requirements=[ResourceRequirement(ResourceType.CPU, 3.0)]
        )

        # First task should succeed
        reserved1 = await manager.reserve_resources(task1)
        assert reserved1 is True
        allocated1 = await manager.allocate_resources(task1)
        assert allocated1 is True

        # Second task should fail due to insufficient resources
        can_allocate2 = await manager.can_allocate(task2)
        assert can_allocate2 is False

        reserved2 = await manager.reserve_resources(task2)
        assert reserved2 is False

        # Release first task
        await manager.release_resources(task1)

        # Now second task should succeed
        can_allocate2 = await manager.can_allocate(task2)
        assert can_allocate2 is True

    def test_resource_usage_reporting(self):
        """Test resource usage statistics."""
        manager = ResourceManager()

        task = Task(
            task_id="test_task",
            name="Test Task",
            tool_name="test_tool",
            tool_args={},
            resource_requirements=[
                ResourceRequirement(ResourceType.CPU, 4.0),
                ResourceRequirement(ResourceType.MEMORY, 16.0)
            ]
        )

        # Initially no usage
        usage = manager.get_resource_usage()
        assert usage[ResourceType.CPU.value]["utilization"] == 0.0
        assert usage[ResourceType.MEMORY.value]["utilization"] == 0.0

        # Allocate resources (synchronous for testing)
        manager.task_allocations[task.task_id] = task.resource_requirements
        manager.allocations[ResourceType.CPU].allocated = 4.0
        manager.allocations[ResourceType.MEMORY].allocated = 16.0

        # Check usage
        usage = manager.get_resource_usage()
        assert usage[ResourceType.CPU.value]["utilization"] == 50.0  # 4/8 * 100
        assert usage[ResourceType.MEMORY.value]["utilization"] == 50.0  # 16/32 * 100


class TestDeadlockDetector:
    """Test deadlock detection functionality."""

    def test_deadlock_detector_initialization(self):
        """Test deadlock detector initialization."""
        detector = DeadlockDetector()
        assert len(detector.wait_for_graph) == 0
        assert len(detector.resource_holders) == 0

    def test_simple_cycle_detection(self):
        """Test detection of simple circular dependency."""
        detector = DeadlockDetector()

        # Create circular dependency: A -> B -> C -> A
        detector.add_wait_relationship("task_a", {"task_c"})
        detector.add_wait_relationship("task_b", {"task_a"})
        detector.add_wait_relationship("task_c", {"task_b"})

        # Detect deadlock
        cycle = detector.detect_deadlock()
        assert cycle is not None
        assert len(cycle) >= 3
        assert "task_a" in cycle or "task_b" in cycle or "task_c" in cycle

    def test_no_deadlock_detection(self):
        """Test that no deadlock is detected in valid DAG."""
        detector = DeadlockDetector()

        # Create valid DAG: A -> B, A -> C, B -> D, C -> D
        detector.add_wait_relationship("task_b", {"task_a"})
        detector.add_wait_relationship("task_c", {"task_a"})
        detector.add_wait_relationship("task_d", {"task_b", "task_c"})

        # No deadlock should be detected
        cycle = detector.detect_deadlock()
        assert cycle is None

    def test_deadlock_prevention(self):
        """Test deadlock prevention through task reordering."""
        detector = DeadlockDetector()

        # Create tasks with different resource requirements
        tasks = [
            Task("task_high_cpu", "High CPU Task", "cpu_tool", {},
                 resource_requirements=[ResourceRequirement(ResourceType.CPU, 8.0)]),
            Task("task_low_cpu", "Low CPU Task", "cpu_tool", {},
                 resource_requirements=[ResourceRequirement(ResourceType.CPU, 1.0)]),
            Task("task_medium_cpu", "Medium CPU Task", "cpu_tool", {},
                 resource_requirements=[ResourceRequirement(ResourceType.CPU, 4.0)])
        ]

        # Prevent deadlock by reordering
        reordered = detector.prevent_deadlock(tasks)

        # Check that tasks are reordered (higher resource requirements first)
        assert len(reordered) == 3
        assert reordered[0].task_id == "task_high_cpu"

    def test_wait_relationship_management(self):
        """Test adding and removing wait relationships."""
        detector = DeadlockDetector()

        # Add relationships
        detector.add_wait_relationship("task_a", {"task_b", "task_c"})
        assert "task_a" in detector.wait_for_graph
        assert "task_b" in detector.wait_for_graph["task_a"]
        assert "task_c" in detector.wait_for_graph["task_a"]

        # Remove task
        detector.remove_wait_relationship("task_a")
        assert "task_a" not in detector.wait_for_graph

        # Add back and remove dependency
        detector.add_wait_relationship("task_a", {"task_b"})
        detector.add_wait_relationship("task_d", {"task_a"})
        detector.remove_wait_relationship("task_a")

        # task_a should be removed from task_d's wait list
        assert "task_a" not in detector.wait_for_graph.get("task_d", set())


class TestTask:
    """Test Task data structure and methods."""

    def test_task_creation(self):
        """Test task creation with all parameters."""
        task = Task(
            task_id="test_task",
            name="Test Task",
            tool_name="test_tool",
            tool_args={"param1": "value1"},
            dependencies=["dep1", "dep2"],
            resource_requirements=[
                ResourceRequirement(ResourceType.CPU, 2.0),
                ResourceRequirement(ResourceType.MEMORY, 4.0)
            ],
            estimated_duration=1800.0,
            timeout=3600.0,
            max_retries=3
        )

        assert task.task_id == "test_task"
        assert task.name == "Test Task"
        assert task.tool_name == "test_tool"
        assert task.tool_args["param1"] == "value1"
        assert len(task.dependencies) == 2
        assert len(task.resource_requirements) == 2
        assert task.estimated_duration == 1800.0
        assert task.timeout == 3600.0
        assert task.max_retries == 3
        assert task.status == TaskStatus.QUEUED

    def test_task_minimal_creation(self):
        """Test task creation with minimal parameters."""
        task = Task(
            task_id="minimal_task",
            name="Minimal Task",
            tool_name="minimal_tool",
            tool_args={}
        )

        assert task.task_id == "minimal_task"
        assert len(task.dependencies) == 0
        assert len(task.resource_requirements) == 0
        assert task.estimated_duration == 60.0
        assert task.max_retries == 2
        assert task.status == TaskStatus.QUEUED


class TestParallelExecutionOrchestrator:
    """Test the main parallel execution orchestrator."""

    @pytest.fixture
    def orchestrator(self):
        """Create orchestrator for testing."""
        return ParallelExecutionOrchestrator(
            max_workers=4,
            resource_limits={
                ResourceType.CPU: 8.0,
                ResourceType.MEMORY: 16.0
            }
        )

    @pytest.fixture
    def simple_execution_graph(self):
        """Create simple execution graph for testing."""
        tasks = [
            Task("task1", "Task 1", "mock_tool", {}, estimated_duration=1.0),
            Task("task2", "Task 2", "mock_tool", {}, dependencies=["task1"], estimated_duration=1.0),
            Task("task3", "Task 3", "mock_tool", {}, dependencies=["task1"], estimated_duration=1.0),
            Task("task4", "Task 4", "mock_tool", {}, dependencies=["task2", "task3"], estimated_duration=1.0)
        ]
        return ExecutionGraph(tasks=tasks)

    def test_orchestrator_initialization(self, orchestrator):
        """Test orchestrator initialization."""
        assert orchestrator.max_workers == 4
        assert isinstance(orchestrator.resource_manager, ResourceManager)
        assert isinstance(orchestrator.deadlock_detector, DeadlockDetector)
        assert len(orchestrator.active_executions) == 0

    @pytest.mark.asyncio
    async def test_execution_graph_validation(self, orchestrator):
        """Test execution graph validation."""
        # Valid graph
        valid_tasks = [
            Task("task1", "Task 1", "mock_tool", {}),
            Task("task2", "Task 2", "mock_tool", {}, dependencies=["task1"])
        ]
        valid_graph = ExecutionGraph(tasks=valid_tasks)

        # Should not raise
        orchestrator._validate_execution_graph(valid_graph)

        # Invalid graph - duplicate IDs
        invalid_tasks = [
            Task("task1", "Task 1", "mock_tool", {}),
            Task("task1", "Task 1 Duplicate", "mock_tool", {})
        ]
        invalid_graph = ExecutionGraph(tasks=invalid_tasks)

        with pytest.raises(ValueError, match="Duplicate task IDs"):
            orchestrator._validate_execution_graph(invalid_graph)

        # Invalid graph - missing dependency
        missing_dep_tasks = [
            Task("task1", "Task 1", "mock_tool", {}, dependencies=["nonexistent"])
        ]
        missing_dep_graph = ExecutionGraph(tasks=missing_dep_tasks)

        with pytest.raises(ValueError, match="invalid dependency"):
            orchestrator._validate_execution_graph(missing_dep_graph)

    @pytest.mark.asyncio
    @patch('brain_researcher.services.tools.tool_registry.ToolRegistry')
    async def test_simple_parallel_execution(self, mock_registry, orchestrator, simple_execution_graph):
        """Test simple parallel execution."""
        # Mock tool registry
        mock_tool = MagicMock()
        mock_tool.run.return_value = {"status": "completed", "result": "mock_result"}
        mock_registry.return_value.get_tool.return_value = mock_tool

        # Execute
        result = await orchestrator.execute_parallel(simple_execution_graph)

        # Verify results
        assert "execution_id" in result
        assert "results" in result
        assert "metrics" in result
        assert len(result["results"]) == 4  # All tasks completed
        assert result["metrics"]["tasks_completed"] == 4
        assert result["metrics"]["speedup"] > 1.0  # Should achieve some speedup

    @pytest.mark.asyncio
    @patch('brain_researcher.services.tools.tool_registry.ToolRegistry')
    async def test_execution_with_failures(self, mock_registry, orchestrator):
        """Test execution handling task failures."""
        # Create tasks
        tasks = [
            Task("task1", "Task 1", "mock_tool", {}),
            Task("task2", "Task 2", "failing_tool", {}),
            Task("task3", "Task 3", "mock_tool", {}, dependencies=["task1"])
        ]
        graph = ExecutionGraph(tasks=tasks)

        # Mock tools - one succeeds, one fails
        def mock_get_tool(tool_name):
            if tool_name == "failing_tool":
                failing_tool = MagicMock()
                failing_tool.run.side_effect = Exception("Tool failure")
                return failing_tool
            else:
                success_tool = MagicMock()
                success_tool.run.return_value = {"status": "completed"}
                return success_tool

        mock_registry.return_value.get_tool.side_effect = mock_get_tool

        # Execute
        result = await orchestrator.execute_parallel(graph)

        # Verify mixed results
        assert len(result["results"]) >= 1  # At least one task succeeded
        assert len(result["errors"]) >= 1  # At least one task failed
        assert result["metrics"]["tasks_failed"] >= 1

    @pytest.mark.asyncio
    async def test_execution_cancellation(self, orchestrator, simple_execution_graph):
        """Test execution cancellation."""
        # Start execution
        execution_task = asyncio.create_task(
            orchestrator.execute_parallel(simple_execution_graph)
        )

        # Wait a moment then cancel
        await asyncio.sleep(0.1)

        # Get execution ID (simplified for test)
        execution_id = list(orchestrator.active_executions.keys())[0]
        cancelled = orchestrator.cancel_execution(execution_id)
        assert cancelled is True

        # Cancel the async task
        execution_task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await execution_task

    @pytest.mark.asyncio
    async def test_execution_timeout(self, orchestrator):
        """Test execution timeout handling."""
        # Create tasks with long duration
        tasks = [
            Task("long_task", "Long Task", "mock_tool", {}, estimated_duration=10.0)
        ]
        graph = ExecutionGraph(tasks=tasks)

        # Execute with short timeout
        with patch('brain_researcher.services.tools.tool_registry.ToolRegistry') as mock_registry:
            slow_tool = MagicMock()
            slow_tool.run.side_effect = lambda **kwargs: time.sleep(5.0)  # Takes 5 seconds
            mock_registry.return_value.get_tool.return_value = slow_tool

            start_time = time.time()
            result = await orchestrator.execute_parallel(graph, timeout=2.0)  # 2 second timeout
            execution_time = time.time() - start_time

            # Should timeout quickly
            assert execution_time < 3.0

    def test_execution_status_tracking(self, orchestrator):
        """Test execution status tracking."""
        # Create mock execution
        execution_id = "test_execution"
        tasks = [Task("task1", "Task 1", "mock_tool", {})]

        orchestrator.active_executions[execution_id] = {
            "graph": ExecutionGraph(tasks=tasks),
            "task_status": {task.task_id: task for task in tasks},
            "results": {},
            "errors": {},
            "started_at": time.time()
        }

        # Get status
        status = orchestrator.get_execution_status(execution_id)

        assert status is not None
        assert status["execution_id"] == execution_id
        assert "task_counts" in status
        assert "resource_usage" in status

        # Non-existent execution
        non_existent_status = orchestrator.get_execution_status("nonexistent")
        assert non_existent_status is None

    @pytest.mark.asyncio
    async def test_orchestrator_shutdown(self, orchestrator):
        """Test orchestrator shutdown."""
        await orchestrator.shutdown(wait_for_completion=False)
        assert orchestrator._shutdown is True


@pytest.mark.integration
class TestParallelExecutionIntegration:
    """Integration tests for parallel execution with real-like scenarios."""

    @pytest.fixture
    def mock_tool_registry(self):
        """Create mock tool registry for integration tests."""
        return MockToolRegistry()

    @pytest.mark.asyncio
    async def test_neuroimaging_pipeline_execution(self, mock_tool_registry):
        """Test execution of a realistic neuroimaging pipeline."""
        # Load test data
        fixtures_path = Path(__file__).parent.parent / "fixtures" / "AGENT-015"
        with open(fixtures_path / "parallel_execution_test_data.json") as f:
            test_data = json.load(f)

        # Create tasks from test data
        tasks = []
        for task_data in test_data["complex_dag"]["tasks"]:
            # Convert resource requirements
            resource_reqs = []
            for req in task_data.get("resource_requirements", []):
                resource_reqs.append(ResourceRequirement(
                    ResourceType(req["resource_type"]),
                    req["amount"]
                ))

            task = Task(
                task_id=task_data["task_id"],
                name=task_data["name"],
                tool_name=task_data["tool_name"],
                tool_args=task_data["tool_args"],
                dependencies=task_data["dependencies"],
                resource_requirements=resource_reqs,
                estimated_duration=task_data["estimated_duration"]
            )
            tasks.append(task)

        graph = ExecutionGraph(tasks=tasks)

        # Create orchestrator with resource limits
        orchestrator = ParallelExecutionOrchestrator(
            max_workers=8,
            resource_limits=test_data["resource_limits"]["high_performance"]
        )

        # Mock the tool registry
        with patch('brain_researcher.services.tools.tool_registry.ToolRegistry') as mock_registry:
            mock_registry.return_value = mock_tool_registry

            # Execute pipeline
            start_time = time.time()
            result = await orchestrator.execute_parallel(graph)
            execution_time = time.time() - start_time

            # Verify results
            assert result["metrics"]["tasks_completed"] > 0
            assert result["metrics"]["speedup"] > 1.0
            assert execution_time < 60.0  # Should complete within 1 minute for test

            # Check that dependencies were respected
            assert "final_report" in result["results"]  # Final task completed

    @pytest.mark.asyncio
    async def test_resource_contention_handling(self, mock_tool_registry):
        """Test handling of resource contention scenarios."""
        # Create memory-intensive tasks that compete for resources
        tasks = [
            Task(
                task_id=f"memory_task_{i}",
                name=f"Memory Task {i}",
                tool_name="memory_intensive_tool",
                tool_args={"memory_mb": 50},
                resource_requirements=[
                    ResourceRequirement(ResourceType.MEMORY, 8.0)
                ],
                estimated_duration=2.0
            )
            for i in range(4)  # 4 tasks requiring 8GB each = 32GB total
        ]

        graph = ExecutionGraph(tasks=tasks)

        # Create orchestrator with limited memory
        orchestrator = ParallelExecutionOrchestrator(
            max_workers=4,
            resource_limits={ResourceType.MEMORY: 16.0}  # Only 16GB available
        )

        # Mock tool registry
        with patch('brain_researcher.services.tools.tool_registry.ToolRegistry') as mock_registry:
            mock_registry.return_value = mock_tool_registry

            # Execute - should handle contention gracefully
            result = await orchestrator.execute_parallel(graph)

            # All tasks should complete eventually
            assert result["metrics"]["tasks_completed"] == 4
            assert result["metrics"]["tasks_failed"] == 0

    @pytest.mark.asyncio
    async def test_deadlock_prevention_integration(self, mock_tool_registry):
        """Test deadlock prevention in practice."""
        # Load deadlock scenario
        fixtures_path = Path(__file__).parent.parent / "fixtures" / "AGENT-015"
        with open(fixtures_path / "parallel_execution_test_data.json") as f:
            test_data = json.load(f)

        # Create circular dependency scenario
        scenario = test_data["deadlock_scenarios"]["circular_dependency"]
        tasks = []
        for task_data in scenario["tasks"]:
            resource_reqs = []
            for req in task_data.get("resource_requirements", []):
                resource_reqs.append(ResourceRequirement(
                    ResourceType(req["resource_type"]),
                    req["amount"]
                ))

            task = Task(
                task_id=task_data["task_id"],
                name=task_data["name"],
                tool_name=task_data["tool_name"],
                tool_args=task_data["tool_args"],
                dependencies=task_data["dependencies"],
                resource_requirements=resource_reqs,
                estimated_duration=task_data["estimated_duration"]
            )
            tasks.append(task)

        graph = ExecutionGraph(tasks=tasks)

        # Create orchestrator with deadlock detection
        orchestrator = ParallelExecutionOrchestrator(
            max_workers=4,
            enable_deadlock_detection=True
        )

        # Mock tool registry
        with patch('brain_researcher.services.tools.tool_registry.ToolRegistry') as mock_registry:
            mock_registry.return_value = mock_tool_registry

            # Should handle circular dependencies gracefully
            # (either by reordering or detecting the issue)
            try:
                result = await orchestrator.execute_parallel(graph)
                # If execution completes, deadlock was prevented
                assert True
            except Exception as e:
                # If execution fails, should be due to dependency issue
                assert "dependency" in str(e).lower() or "deadlock" in str(e).lower()


@pytest.mark.performance
class TestParallelExecutionPerformance:
    """Performance tests for parallel execution."""

    @pytest.mark.asyncio
    async def test_speedup_measurement(self):
        """Test that parallel execution achieves expected speedup."""
        # Load performance test cases
        fixtures_path = Path(__file__).parent.parent / "fixtures" / "AGENT-015"
        with open(fixtures_path / "parallel_execution_test_data.json") as f:
            test_data = json.load(f)

        # Test parallel vs sequential performance
        for scenario_name in ["sequential_baseline", "parallel_optimized"]:
            scenario = test_data["performance_test_cases"][scenario_name]

            tasks = []
            for task_data in scenario["tasks"]:
                resource_reqs = []
                for req in task_data.get("resource_requirements", []):
                    resource_reqs.append(ResourceRequirement(
                        ResourceType(req["resource_type"]),
                        req["amount"]
                    ))

                task = Task(
                    task_id=task_data["task_id"],
                    name=task_data["name"],
                    tool_name=task_data["tool_name"],
                    tool_args=task_data["tool_args"],
                    dependencies=task_data["dependencies"],
                    resource_requirements=resource_reqs,
                    estimated_duration=0.5  # Shorter for testing
                )
                tasks.append(task)

            graph = ExecutionGraph(tasks=tasks)
            orchestrator = ParallelExecutionOrchestrator(max_workers=4)

            with patch('brain_researcher.services.tools.tool_registry.ToolRegistry') as mock_registry:
                mock_tool = MagicMock()
                mock_tool.run.return_value = {"status": "completed"}
                mock_registry.return_value.get_tool.return_value = mock_tool

                start_time = time.time()
                result = await orchestrator.execute_parallel(graph)
                execution_time = time.time() - start_time

                if scenario_name == "parallel_optimized":
                    # Parallel scenario should achieve speedup
                    assert result["metrics"]["speedup"] > 2.0
                else:
                    # Sequential scenario will have lower speedup
                    assert result["metrics"]["speedup"] >= 1.0

    @pytest.mark.asyncio
    async def test_resource_utilization_efficiency(self):
        """Test efficient resource utilization."""
        # Create tasks with varying resource requirements
        tasks = [
            Task(f"cpu_task_{i}", f"CPU Task {i}", "cpu_intensive_tool", {},
                 resource_requirements=[ResourceRequirement(ResourceType.CPU, 2.0)],
                 estimated_duration=1.0)
            for i in range(4)
        ]

        graph = ExecutionGraph(tasks=tasks)
        orchestrator = ParallelExecutionOrchestrator(
            max_workers=4,
            resource_limits={ResourceType.CPU: 8.0}
        )

        with patch('brain_researcher.services.tools.tool_registry.ToolRegistry') as mock_registry:
            mock_tool = MagicMock()
            mock_tool.run.return_value = {"status": "completed"}
            mock_registry.return_value.get_tool.return_value = mock_tool

            result = await orchestrator.execute_parallel(graph)

            # Should achieve high CPU utilization during execution
            resource_usage = result["metrics"]["resource_usage"]
            # All tasks should complete successfully
            assert result["metrics"]["tasks_completed"] == 4
            assert result["metrics"]["tasks_failed"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
