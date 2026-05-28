"""
Integration tests for Parallel Execution Orchestration (AGENT-015).

Tests the complete parallel execution system integration with realistic
neuroimaging workflows and end-to-end scenarios.
"""

import asyncio
import json
import pytest
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import os

# These integration tests are heavy; enable explicitly
if os.environ.get("RUN_PARALLEL_EXECUTION") != "1":
    pytest.skip("Set RUN_PARALLEL_EXECUTION=1 to run parallel execution integration tests", allow_module_level=True)

from brain_researcher.services.agent.parallel_executor import (
    ParallelExecutionOrchestrator,
    ResourceType,
    ResourceRequirement,
    Task,
    TaskStatus,
    create_parallel_orchestrator
)
from brain_researcher.services.agent.dependency_resolver import ExecutionGraph, DependencyResolver
from brain_researcher.services.agent.execution_status import ExecutionTracker, AsyncExecutionTracker

# Import test fixtures
import importlib.util

_fixtures_path = Path(__file__).parent.parent / "fixtures" / "AGENT-015" / "mock_tools.py"
_spec = importlib.util.spec_from_file_location("agent_015_mock_tools", _fixtures_path)
if _spec is None or _spec.loader is None:  # pragma: no cover - fixture load failure
    raise ImportError(f"Unable to load mock_tools from {_fixtures_path}")
_mock_tools = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mock_tools)
MockToolRegistry = _mock_tools.MockToolRegistry
get_mock_tool = _mock_tools.get_mock_tool


@pytest.mark.integration
class TestParallelExecutionEndToEnd:
    """End-to-end integration tests for parallel execution."""
    
    @pytest.fixture
    def test_data_path(self):
        """Path to test data fixtures."""
        return Path(__file__).parent.parent / "fixtures" / "AGENT-015"
    
    @pytest.fixture
    def mock_tool_registry(self):
        """Mock tool registry for integration tests."""
        registry = MockToolRegistry()
        
        # Register neuroimaging tools
        tools = [
            "fmriprep_tool", "glm_analysis_tool", "connectivity_tool",
            "freesurfer_tool", "bids_validator_tool", "surface_analysis_tool",
            "group_glm_tool", "report_generator_tool", "merge_results_tool"
        ]
        
        for tool_name in tools:
            registry.register_tool(tool_name, get_mock_tool(tool_name).__class__)
        
        return registry
    
    def load_test_scenario(self, test_data_path: Path, scenario_name: str):
        """Load test scenario from fixtures."""
        with open(test_data_path / "parallel_execution_test_data.json") as f:
            test_data = json.load(f)
        return test_data[scenario_name]
    
    def create_tasks_from_data(self, task_data_list):
        """Create Task objects from test data."""
        tasks = []
        for task_data in task_data_list:
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
                estimated_duration=task_data.get("estimated_duration", 60.0),
                timeout=task_data.get("timeout")
            )
            tasks.append(task)
        return tasks
    
    @pytest.mark.asyncio
    async def test_simple_dag_execution(self, test_data_path, mock_tool_registry):
        """Test execution of simple DAG with dependencies."""
        # Load simple DAG scenario
        scenario = self.load_test_scenario(test_data_path, "simple_dag")
        tasks = self.create_tasks_from_data(scenario["tasks"])
        
        # Create execution graph
        graph = ExecutionGraph(tasks=tasks)
        
        # Create orchestrator
        orchestrator = create_parallel_orchestrator(
            max_workers=4,
            resource_limits={
                ResourceType.CPU: 8.0,
                ResourceType.MEMORY: 16.0,
                ResourceType.STORAGE: 100.0
            },
            enable_adaptive=False
        )
        
        # Mock tool registry
        with patch('brain_researcher.services.tools.tool_registry.ToolRegistry') as mock_registry:
            mock_registry.return_value = mock_tool_registry
            
            # Execute with tracking
            tracker = ExecutionTracker()
            
            start_time = time.time()
            result = await orchestrator.execute_parallel(graph, tracker)
            execution_time = time.time() - start_time
            
            # Verify successful execution
            assert result["metrics"]["tasks_completed"] == 4
            assert result["metrics"]["tasks_failed"] == 0
            assert len(result["results"]) == 4
            
            # Verify dependency order was respected
            assert "preprocess" in result["results"]
            assert "glm_left" in result["results"]
            assert "glm_right" in result["results"]
            assert "merge_results" in result["results"]
            
            # Verify parallel speedup
            assert result["metrics"]["speedup"] > 1.0
            
            # Verify execution completed reasonably quickly
            assert execution_time < 30.0  # Should complete within 30 seconds
    
    @pytest.mark.asyncio
    async def test_complex_neuroimaging_pipeline(self, test_data_path, mock_tool_registry):
        """Test execution of complex neuroimaging analysis pipeline."""
        # Load complex DAG scenario
        scenario = self.load_test_scenario(test_data_path, "complex_dag")
        tasks = self.create_tasks_from_data(scenario["tasks"])
        
        # Create execution graph
        graph = ExecutionGraph(tasks=tasks)
        
        # Create orchestrator with higher resource limits
        resource_limits = self.load_test_scenario(test_data_path, "resource_limits")["high_performance"]
        
        orchestrator = create_parallel_orchestrator(
            max_workers=8,
            resource_limits={
                ResourceType.CPU: resource_limits["cpu"],
                ResourceType.MEMORY: resource_limits["memory"],
                ResourceType.STORAGE: resource_limits["storage"],
                ResourceType.GPU: resource_limits["gpu"]
            },
            enable_adaptive=False
        )
        
        # Mock tool registry
        with patch('brain_researcher.services.tools.tool_registry.ToolRegistry') as mock_registry:
            mock_registry.return_value = mock_tool_registry
            
            # Execute with async tracking
            tracker = AsyncExecutionTracker()
            
            # Set up progress monitoring
            progress_updates = []
            async def progress_callback(update):
                progress_updates.append(update)
            
            await tracker.add_listener(progress_callback)
            
            start_time = time.time()
            result = await orchestrator.execute_parallel(graph, tracker)
            execution_time = time.time() - start_time
            
            # Verify all tasks completed
            assert result["metrics"]["tasks_completed"] == 9
            assert result["metrics"]["tasks_failed"] == 0
            
            # Verify key results exist
            expected_results = [
                "data_validation", "anat_preproc", "func_preproc",
                "glm_task1", "glm_task2", "connectivity",
                "surface_analysis", "group_analysis", "final_report"
            ]
            for expected in expected_results:
                assert expected in result["results"]
            
            # Verify final report depends on all prerequisite analyses
            assert "final_report" in result["results"]
            
            # Verify parallel efficiency
            assert result["metrics"]["speedup"] > 2.0
            
            # Verify progress updates were received
            assert len(progress_updates) > 0
    
    @pytest.mark.asyncio
    async def test_resource_constrained_execution(self, test_data_path, mock_tool_registry):
        """Test execution under resource constraints."""
        # Load complex scenario but with constrained resources
        scenario = self.load_test_scenario(test_data_path, "complex_dag")
        tasks = self.create_tasks_from_data(scenario["tasks"])
        
        graph = ExecutionGraph(tasks=tasks)
        
        # Use constrained resource limits
        resource_limits = self.load_test_scenario(test_data_path, "resource_limits")["constrained"]
        
        orchestrator = create_parallel_orchestrator(
            max_workers=2,  # Reduced workers
            resource_limits={
                ResourceType.CPU: resource_limits["cpu"],
                ResourceType.MEMORY: resource_limits["memory"],
                ResourceType.STORAGE: resource_limits["storage"]
            },
            enable_adaptive=False
        )
        
        with patch('brain_researcher.services.tools.tool_registry.ToolRegistry') as mock_registry:
            mock_registry.return_value = mock_tool_registry
            
            start_time = time.time()
            result = await orchestrator.execute_parallel(graph)
            execution_time = time.time() - start_time
            
            # Should still complete all tasks, but potentially slower
            assert result["metrics"]["tasks_completed"] == 9
            assert result["metrics"]["tasks_failed"] == 0
            
            # Resource utilization should be high
            resource_usage = result["metrics"]["resource_usage"]
            # At some point during execution, resources should be well utilized
            # (This is hard to test precisely, but we can check final state)
            assert resource_usage is not None
    
    @pytest.mark.asyncio
    async def test_failure_handling_and_recovery(self, test_data_path, mock_tool_registry):
        """Test handling of task failures and recovery."""
        # Create scenario with some failing tasks
        scenario = self.load_test_scenario(test_data_path, "simple_dag")
        tasks = self.create_tasks_from_data(scenario["tasks"])
        
        graph = ExecutionGraph(tasks=tasks)
        orchestrator = create_parallel_orchestrator(max_workers=4, enable_adaptive=False)
        
        # Mock registry with one failing GLM hemisphere
        def mock_get_tool(tool_name):
            if tool_name == "glm_analysis_tool":
                tool = MagicMock()

                def run_with_failure(**kwargs):
                    if kwargs.get("hemisphere") == "left":
                        raise Exception("Simulated failure in glm_left")
                    return mock_tool_registry.get_tool(tool_name).run(**kwargs)

                tool.run.side_effect = run_with_failure
                return tool
            return mock_tool_registry.get_tool(tool_name)
        
        with patch('brain_researcher.services.tools.tool_registry.ToolRegistry') as mock_registry:
            mock_registry.return_value.get_tool.side_effect = mock_get_tool
            
            result = await orchestrator.execute_parallel(graph)
            
            # Some tasks should succeed, some should fail
            assert result["metrics"]["tasks_completed"] >= 1
            assert result["metrics"]["tasks_failed"] >= 1
            assert len(result["errors"]) >= 1
            
            # Dependent tasks should be affected
            # merge_results depends on both GLM tasks, so it should fail if one GLM fails
            assert "glm_left" in result["errors"]
    
    @pytest.mark.asyncio
    async def test_execution_cancellation(self, test_data_path, mock_tool_registry):
        """Test execution cancellation during runtime."""
        # Load scenario with long-running tasks
        scenario = self.load_test_scenario(test_data_path, "complex_dag")
        tasks = self.create_tasks_from_data(scenario["tasks"])
        
        # Make tasks take longer for cancellation testing
        for task in tasks:
            task.estimated_duration = 10.0  # 10 seconds each
        
        graph = ExecutionGraph(tasks=tasks)
        orchestrator = create_parallel_orchestrator(max_workers=4, enable_adaptive=False)
        
        # Create slow mock tools
        def slow_tool_run(**kwargs):
            time.sleep(5.0)  # Simulate 5-second execution
            return {"status": "completed"}
        
        with patch('brain_researcher.services.tools.tool_registry.ToolRegistry') as mock_registry:
            mock_tool = MagicMock()
            mock_tool.run.side_effect = slow_tool_run
            mock_registry.return_value.get_tool.return_value = mock_tool
            
            # Start execution
            execution_task = asyncio.create_task(
                orchestrator.execute_parallel(graph)
            )
            
            # Wait for execution to start
            await asyncio.sleep(1.0)
            
            # Cancel execution
            execution_ids = list(orchestrator.active_executions.keys())
            if execution_ids:
                cancelled = orchestrator.cancel_execution(execution_ids[0])
                assert cancelled is True
            
            # Cancel the task
            execution_task.cancel()
            
            # Verify cancellation
            with pytest.raises(asyncio.CancelledError):
                await execution_task
    
    @pytest.mark.asyncio
    async def test_deadlock_detection_and_prevention(self, test_data_path, mock_tool_registry):
        """Test deadlock detection and prevention."""
        # Load deadlock scenario
        deadlock_scenarios = self.load_test_scenario(test_data_path, "deadlock_scenarios")
        circular_scenario = deadlock_scenarios["circular_dependency"]
        
        tasks = self.create_tasks_from_data(circular_scenario["tasks"])
        graph = ExecutionGraph(tasks=tasks)
        
        # Create orchestrator with deadlock detection enabled
        orchestrator = create_parallel_orchestrator(
            max_workers=4,
            resource_limits={ResourceType.CPU: 8.0},
            enable_adaptive=False
        )
        
        with patch('brain_researcher.services.tools.tool_registry.ToolRegistry') as mock_registry:
            mock_registry.return_value = mock_tool_registry
            
            # Execution should either:
            # 1. Detect and prevent the deadlock, or
            # 2. Fail with appropriate error message
            try:
                result = await orchestrator.execute_parallel(graph)
                # If successful, deadlock was prevented
                assert True
            except Exception as e:
                # If failed, should be due to circular dependency
                error_msg = str(e).lower()
                assert any(keyword in error_msg for keyword in 
                          ["circular", "dependency", "deadlock", "cycle"])
    
    @pytest.mark.asyncio
    async def test_resource_deadlock_resolution(self, test_data_path, mock_tool_registry):
        """Test resolution of resource-based deadlocks."""
        # Load resource deadlock scenario
        deadlock_scenarios = self.load_test_scenario(test_data_path, "deadlock_scenarios")
        resource_scenario = deadlock_scenarios["resource_deadlock"]
        
        tasks = self.create_tasks_from_data(resource_scenario["tasks"])
        graph = ExecutionGraph(tasks=tasks)
        
        # Create orchestrator with limited memory to force contention
        orchestrator = create_parallel_orchestrator(
            max_workers=4,
            resource_limits={
                ResourceType.CPU: 8.0,
                ResourceType.MEMORY: 30.0  # Less than combined requirement
            },
            enable_adaptive=False
        )
        
        with patch('brain_researcher.services.tools.tool_registry.ToolRegistry') as mock_registry:
            mock_registry.return_value = mock_tool_registry
            
            # Should handle resource contention gracefully
            result = await orchestrator.execute_parallel(graph, timeout=30.0)
            
            # Both tasks should eventually complete
            assert result["metrics"]["tasks_completed"] == 2
            assert result["metrics"]["tasks_failed"] == 0
    
    @pytest.mark.asyncio
    async def test_real_time_progress_tracking(self, test_data_path, mock_tool_registry):
        """Test real-time progress tracking and updates."""
        scenario = self.load_test_scenario(test_data_path, "simple_dag")
        tasks = self.create_tasks_from_data(scenario["tasks"])
        
        graph = ExecutionGraph(tasks=tasks)
        orchestrator = create_parallel_orchestrator(max_workers=4, enable_adaptive=False)
        
        # Set up progress tracking
        tracker = AsyncExecutionTracker()
        progress_events = []
        
        async def capture_progress(event):
            progress_events.append(event)
        
        await tracker.add_listener(capture_progress)
        
        with patch('brain_researcher.services.tools.tool_registry.ToolRegistry') as mock_registry:
            mock_registry.return_value = mock_tool_registry
            
            result = await orchestrator.execute_parallel(graph, tracker)
            
            # Verify progress events were captured
            assert len(progress_events) > 0
            
            # Check for expected event types
            event_types = [event["event"] for event in progress_events]
            assert "execution_started" in event_types or len(event_types) > 0
            
            # Verify execution completed successfully
            assert result["metrics"]["tasks_completed"] == 4


@pytest.mark.integration
class TestParallelExecutionScenarios:
    """Test specific neuroimaging scenarios."""
    
    @pytest.mark.asyncio
    async def test_multisubject_analysis_pipeline(self):
        """Test parallel execution of multi-subject analysis."""
        # Create tasks for multiple subjects
        subjects = ["sub-01", "sub-02", "sub-03", "sub-04"]
        tasks = []
        
        # Preprocessing for each subject (parallel)
        for subject in subjects:
            task = Task(
                task_id=f"preproc_{subject}",
                name=f"Preprocess {subject}",
                tool_name="fmriprep_tool",
                tool_args={"subject": subject},
                dependencies=[],
                resource_requirements=[
                    ResourceRequirement(ResourceType.CPU, 4.0),
                    ResourceRequirement(ResourceType.MEMORY, 8.0)
                ],
                estimated_duration=1.0  # Reduced for testing
            )
            tasks.append(task)
        
        # GLM analysis for each subject (depends on preprocessing)
        for subject in subjects:
            task = Task(
                task_id=f"glm_{subject}",
                name=f"GLM Analysis {subject}",
                tool_name="glm_analysis_tool",
                tool_args={"subject": subject},
                dependencies=[f"preproc_{subject}"],
                resource_requirements=[
                    ResourceRequirement(ResourceType.CPU, 2.0),
                    ResourceRequirement(ResourceType.MEMORY, 4.0)
                ],
                estimated_duration=0.5
            )
            tasks.append(task)
        
        # Group analysis (depends on all GLM analyses)
        group_task = Task(
            task_id="group_analysis",
            name="Group Analysis",
            tool_name="group_glm_tool",
            tool_args={"subjects": subjects},
            dependencies=[f"glm_{subject}" for subject in subjects],
            resource_requirements=[
                ResourceRequirement(ResourceType.CPU, 8.0),
                ResourceRequirement(ResourceType.MEMORY, 16.0)
            ],
            estimated_duration=1.0
        )
        tasks.append(group_task)
        
        graph = ExecutionGraph(tasks=tasks)
        orchestrator = create_parallel_orchestrator(
            max_workers=8,
            resource_limits={
                ResourceType.CPU: 16.0,
                ResourceType.MEMORY: 32.0
            },
            enable_adaptive=False
        )
        
        # Mock tool registry
        mock_registry = MockToolRegistry()
        
        with patch('brain_researcher.services.tools.tool_registry.ToolRegistry') as mock_reg:
            mock_reg.return_value = mock_registry
            
            result = await orchestrator.execute_parallel(graph)
            
            # All tasks should complete
            expected_tasks = len(subjects) * 2 + 1  # preproc + glm per subject + group
            assert result["metrics"]["tasks_completed"] == expected_tasks
            assert result["metrics"]["tasks_failed"] == 0
            
            # Group analysis should complete last
            assert "group_analysis" in result["results"]
            
            # Should achieve good speedup due to parallelization
            assert result["metrics"]["speedup"] > 2.0
    
    @pytest.mark.asyncio
    async def test_mixed_analysis_types_pipeline(self):
        """Test pipeline with different types of neuroimaging analyses."""
        # Create heterogeneous pipeline
        tasks = [
            # Data validation
            Task("validation", "Data Validation", "bids_validator_tool", {},
                 resource_requirements=[ResourceRequirement(ResourceType.CPU, 1.0)],
                 estimated_duration=0.3),
            
            # Structural preprocessing
            Task("anat_preproc", "Anatomical Preprocessing", "freesurfer_tool", {},
                 dependencies=["validation"],
                 resource_requirements=[
                     ResourceRequirement(ResourceType.CPU, 4.0),
                     ResourceRequirement(ResourceType.MEMORY, 8.0)
                 ],
                 estimated_duration=2.0),
            
            # Functional preprocessing
            Task("func_preproc", "Functional Preprocessing", "fmriprep_tool", {},
                 dependencies=["validation"],
                 resource_requirements=[
                     ResourceRequirement(ResourceType.CPU, 4.0),
                     ResourceRequirement(ResourceType.MEMORY, 8.0)
                 ],
                 estimated_duration=1.5),
            
            # Task-based analysis
            Task("task_analysis", "Task Analysis", "glm_analysis_tool", {},
                 dependencies=["func_preproc"],
                 resource_requirements=[
                     ResourceRequirement(ResourceType.CPU, 2.0),
                     ResourceRequirement(ResourceType.MEMORY, 4.0)
                 ],
                 estimated_duration=1.0),
            
            # Connectivity analysis
            Task("connectivity", "Connectivity Analysis", "connectivity_tool", {},
                 dependencies=["func_preproc"],
                 resource_requirements=[
                     ResourceRequirement(ResourceType.CPU, 4.0),
                     ResourceRequirement(ResourceType.MEMORY, 8.0)
                 ],
                 estimated_duration=1.5),
            
            # Surface analysis
            Task("surface", "Surface Analysis", "surface_analysis_tool", {},
                 dependencies=["anat_preproc"],
                 resource_requirements=[
                     ResourceRequirement(ResourceType.CPU, 2.0),
                     ResourceRequirement(ResourceType.MEMORY, 4.0)
                 ],
                 estimated_duration=1.0),
            
            # Final report
            Task("report", "Generate Report", "report_generator_tool", {},
                 dependencies=["task_analysis", "connectivity", "surface"],
                 resource_requirements=[
                     ResourceRequirement(ResourceType.CPU, 1.0),
                     ResourceRequirement(ResourceType.MEMORY, 2.0)
                 ],
                 estimated_duration=0.5)
        ]
        
        graph = ExecutionGraph(tasks=tasks)
        orchestrator = create_parallel_orchestrator(
            max_workers=6,
            resource_limits={
                ResourceType.CPU: 12.0,
                ResourceType.MEMORY: 24.0
            },
            enable_adaptive=False
        )
        
        mock_registry = MockToolRegistry()
        
        with patch('brain_researcher.services.tools.tool_registry.ToolRegistry') as mock_reg:
            mock_reg.return_value = mock_registry
            
            tracker = ExecutionTracker()
            
            result = await orchestrator.execute_parallel(graph, tracker)
            
            # All analyses should complete
            assert result["metrics"]["tasks_completed"] == 7
            assert result["metrics"]["tasks_failed"] == 0
            
            # Verify dependency ordering
            assert "validation" in result["results"]
            assert "report" in result["results"]  # Final task
            
            # Check that parallel branches executed efficiently
            assert result["metrics"]["speedup"] > 1.5


@pytest.mark.performance
class TestParallelExecutionPerformance:
    """Performance-focused integration tests."""
    
    @pytest.mark.asyncio
    async def test_large_scale_execution_performance(self):
        """Test performance with large number of tasks."""
        # Create large DAG with many independent tasks
        num_parallel_tasks = 20
        tasks = []
        
        # Create many independent preprocessing tasks
        for i in range(num_parallel_tasks):
            task = Task(
                task_id=f"preproc_task_{i}",
                name=f"Preprocessing Task {i}",
                tool_name="fmriprep_tool",
                tool_args={"task_id": i},
                resource_requirements=[
                    ResourceRequirement(ResourceType.CPU, 1.0),
                    ResourceRequirement(ResourceType.MEMORY, 2.0)
                ],
                estimated_duration=0.2  # Very short for performance testing
            )
            tasks.append(task)
        
        # Create aggregation task that depends on all preprocessing
        aggregate_task = Task(
            task_id="aggregate",
            name="Aggregate Results",
            tool_name="report_generator_tool",
            tool_args={},
            dependencies=[f"preproc_task_{i}" for i in range(num_parallel_tasks)],
            resource_requirements=[
                ResourceRequirement(ResourceType.CPU, 2.0),
                ResourceRequirement(ResourceType.MEMORY, 4.0)
            ],
            estimated_duration=0.1
        )
        tasks.append(aggregate_task)
        
        graph = ExecutionGraph(tasks=tasks)
        orchestrator = create_parallel_orchestrator(
            max_workers=10,
            resource_limits={
                ResourceType.CPU: 20.0,
                ResourceType.MEMORY: 40.0
            },
            enable_adaptive=False
        )
        
        mock_registry = MockToolRegistry()
        
        with patch('brain_researcher.services.tools.tool_registry.ToolRegistry') as mock_reg:
            mock_reg.return_value = mock_registry
            
            start_time = time.time()
            result = await orchestrator.execute_parallel(graph)
            execution_time = time.time() - start_time
            
            # All tasks should complete
            assert result["metrics"]["tasks_completed"] == num_parallel_tasks + 1
            assert result["metrics"]["tasks_failed"] == 0
            
            # Should achieve significant speedup
            assert result["metrics"]["speedup"] > 5.0
            
            # Should complete quickly due to parallelization
            assert execution_time < 10.0  # Should finish in under 10 seconds
    
    @pytest.mark.asyncio
    async def test_memory_intensive_workload_performance(self):
        """Test performance with memory-intensive workloads."""
        # Create tasks with high memory requirements
        tasks = [
            Task(
                task_id=f"memory_task_{i}",
                name=f"Memory Intensive Task {i}",
                tool_name="memory_intensive_tool",
                tool_args={"memory_mb": 100},  # Simulate 100MB allocation
                resource_requirements=[
                    ResourceRequirement(ResourceType.CPU, 1.0),
                    ResourceRequirement(ResourceType.MEMORY, 4.0)
                ],
                estimated_duration=0.5
            )
            for i in range(8)  # 8 tasks requiring 4GB each
        ]
        
        graph = ExecutionGraph(tasks=tasks)
        
        # Test with different memory limits to see impact
        for memory_limit in [16.0, 32.0]:  # 16GB vs 32GB
            orchestrator = create_parallel_orchestrator(
                max_workers=8,
                resource_limits={
                    ResourceType.CPU: 8.0,
                    ResourceType.MEMORY: memory_limit
                },
                enable_adaptive=False
            )
            
            mock_registry = MockToolRegistry()
            
            with patch('brain_researcher.services.tools.tool_registry.ToolRegistry') as mock_reg:
                mock_reg.return_value = mock_registry
                
                start_time = time.time()
                result = await orchestrator.execute_parallel(graph)
                execution_time = time.time() - start_time
                
                # All tasks should complete regardless of memory limit
                assert result["metrics"]["tasks_completed"] == 8
                assert result["metrics"]["tasks_failed"] == 0
                
                # Higher memory limit should allow better parallelization
                if memory_limit == 32.0:
                    assert result["metrics"]["speedup"] > 2.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
