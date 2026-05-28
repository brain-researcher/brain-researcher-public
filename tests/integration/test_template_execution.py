"""
Integration tests for AGENT-018: Workflow Templates - Template Execution

Tests the complete workflow template execution pipeline including:
- Real template execution scenarios
- Template orchestration with multiple services
- Error handling and recovery
- Performance under realistic conditions
- Template execution with external dependencies

Author: Reviewer Subagent
Date: 2025-01-XX
"""

import pytest
import asyncio
import json
import yaml
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from typing import Dict, Any, List, Optional
import concurrent.futures

from brain_researcher.services.agent.workflow_templates import (
    WorkflowTemplateEngine,
    WorkflowExecutor,
    ExecutionContext,
    ExecutionResult,
    TemplateValidationError,
    ExecutionError,
    WorkflowTemplate,
    ExecutionStep
)


@pytest.fixture
def sample_templates():
    """Load comprehensive template fixtures."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "AGENT-018" / "test_templates.yaml"
    with open(fixture_path, 'r') as f:
        return yaml.safe_load(f)


@pytest.fixture
def template_engine(sample_templates):
    """Create template engine with sample templates."""
    with tempfile.TemporaryDirectory() as temp_dir:
        template_file = Path(temp_dir) / "templates.yaml"
        with open(template_file, 'w') as f:
            yaml.dump(sample_templates, f)
        
        engine = WorkflowTemplateEngine(template_dir=temp_dir)
        return engine


@pytest.fixture
def mock_tool_registry():
    """Create mock tool registry for testing."""
    registry = Mock()
    
    # Mock neuroimaging tools
    registry.get_tool.side_effect = lambda name: {
        "load_nifti": Mock(return_value={"status": "success", "data": "mock_nifti_data"}),
        "preprocess_fmri": Mock(return_value={"status": "success", "preprocessed_data": "mock_preprocessed"}),
        "compute_glm": Mock(return_value={"status": "success", "glm_results": "mock_glm"}),
        "extract_timeseries": Mock(return_value={"status": "success", "timeseries": "mock_timeseries"}),
        "compute_connectivity": Mock(return_value={"status": "success", "connectivity_matrix": "mock_connectivity"}),
        "group_analysis": Mock(return_value={"status": "success", "group_stats": "mock_group_results"}),
        "save_results": Mock(return_value={"status": "success", "output_path": "/mock/output/path"})
    }.get(name, Mock(return_value={"status": "error", "message": f"Unknown tool: {name}"}))
    
    return registry


@pytest.fixture
def workflow_executor(template_engine, mock_tool_registry):
    """Create workflow executor with mocked dependencies."""
    executor = WorkflowExecutor(
        template_engine=template_engine,
        tool_registry=mock_tool_registry,
        max_parallel_steps=4,
        step_timeout=30.0
    )
    return executor


class TestBasicTemplateExecution:
    """Test basic template execution functionality."""
    
    @pytest.mark.asyncio
    async def test_simple_template_execution(self, workflow_executor):
        """Test execution of simple fMRI analysis template."""
        params = {
            "input_data": "/test/data/sub-01_task-rest_bold.nii.gz",
            "tr": 2.0,
            "high_pass_cutoff": 0.01
        }
        
        result = await workflow_executor.execute_template("fmri_analysis", params)
        
        assert result.status == "success"
        assert result.template_name == "fmri_analysis"
        assert len(result.step_results) > 0
        
        # Verify all steps completed successfully
        for step_result in result.step_results:
            assert step_result.status in ["success", "skipped"]
    
    @pytest.mark.asyncio
    async def test_template_with_inheritance_execution(self, workflow_executor):
        """Test execution of template with inheritance."""
        params = {
            "input_data": "/test/data/sub-01_task-rest_bold.nii.gz",
            "tr": 2.0,
            "high_pass_cutoff": 0.01,
            "connectivity_method": "correlation"
        }
        
        result = await workflow_executor.execute_template("connectivity_analysis", params)
        
        assert result.status == "success"
        assert result.template_name == "connectivity_analysis"
        
        # Should have executed both base and derived steps
        step_names = [step.step_name for step in result.step_results]
        assert "load_data" in step_names  # From base template
        assert "compute_connectivity" in step_names  # From derived template
    
    @pytest.mark.asyncio
    async def test_template_execution_with_conditions(self, workflow_executor):
        """Test template execution with conditional steps."""
        # Test with motion correction enabled
        params_with_mc = {
            "input_data": "/test/data/sub-01_task-rest_bold.nii.gz",
            "tr": 2.0,
            "high_pass_cutoff": 0.01,
            "motion_correction": True
        }
        
        result = await workflow_executor.execute_template("fmri_analysis", params_with_mc)
        
        step_names = [step.step_name for step in result.step_results]
        assert "motion_correction" in step_names
        
        # Test with motion correction disabled
        params_no_mc = {
            "input_data": "/test/data/sub-01_task-rest_bold.nii.gz",
            "tr": 2.0,
            "high_pass_cutoff": 0.01,
            "motion_correction": False
        }
        
        result = await workflow_executor.execute_template("fmri_analysis", params_no_mc)
        
        step_names = [step.step_name for step in result.step_results]
        assert "motion_correction" not in step_names
    
    @pytest.mark.asyncio
    async def test_template_execution_order(self, workflow_executor):
        """Test that template steps execute in correct dependency order."""
        params = {
            "input_data": "/test/data/sub-01_task-rest_bold.nii.gz",
            "tr": 2.0,
            "high_pass_cutoff": 0.01
        }
        
        result = await workflow_executor.execute_template("fmri_analysis", params)
        
        # Extract execution timestamps
        step_times = {step.step_name: step.start_time for step in result.step_results}
        
        # Verify logical execution order
        assert step_times["load_data"] < step_times["preprocessing"]
        assert step_times["preprocessing"] < step_times["save_results"]


class TestParallelTemplateExecution:
    """Test parallel execution of template steps."""
    
    @pytest.mark.asyncio
    async def test_parallel_step_execution(self, workflow_executor):
        """Test execution of steps that can run in parallel."""
        params = {
            "input_data": ["/test/sub-01_bold.nii.gz", "/test/sub-02_bold.nii.gz", "/test/sub-03_bold.nii.gz"],
            "group_mask": "/test/group_mask.nii.gz",
            "tr": 2.0,
            "high_pass_cutoff": 0.01
        }
        
        start_time = time.time()
        result = await workflow_executor.execute_template("group_analysis", params)
        total_time = time.time() - start_time
        
        assert result.status == "success"
        
        # Find parallel steps
        parallel_steps = [step for step in result.step_results 
                         if step.step_name.startswith("subject_analysis")]
        
        # Should have processed multiple subjects
        assert len(parallel_steps) >= 2
        
        # Parallel execution should be faster than sequential
        # (This is a rough heuristic - in practice would depend on actual timing)
        expected_sequential_time = len(parallel_steps) * 1.0  # Assume 1s per step
        assert total_time < expected_sequential_time * 0.8  # 20% speedup at least
    
    @pytest.mark.asyncio
    async def test_parallel_execution_limits(self, workflow_executor):
        """Test that parallel execution respects concurrency limits."""
        # Create template with many parallel steps
        params = {
            "input_data": [f"/test/sub-{i:02d}_bold.nii.gz" for i in range(1, 11)],  # 10 subjects
            "group_mask": "/test/group_mask.nii.gz",
            "tr": 2.0
        }
        
        # Mock tool to track concurrent executions
        concurrent_count = {"current": 0, "max_seen": 0}
        
        async def mock_subject_analysis(*args, **kwargs):
            concurrent_count["current"] += 1
            concurrent_count["max_seen"] = max(concurrent_count["max_seen"], concurrent_count["current"])
            
            await asyncio.sleep(0.1)  # Simulate processing time
            
            concurrent_count["current"] -= 1
            return {"status": "success", "subject_results": "mock_results"}
        
        with patch.object(workflow_executor.tool_registry, 'get_tool') as mock_get_tool:
            mock_get_tool.return_value = mock_subject_analysis
            
            result = await workflow_executor.execute_template("group_analysis", params)
        
        # Should not exceed max_parallel_steps limit
        assert concurrent_count["max_seen"] <= workflow_executor.max_parallel_steps
        assert result.status == "success"
    
    @pytest.mark.asyncio
    async def test_mixed_parallel_sequential_execution(self, workflow_executor):
        """Test execution mixing parallel and sequential steps."""
        params = {
            "input_data": ["/test/sub-01_bold.nii.gz", "/test/sub-02_bold.nii.gz"],
            "connectivity_method": "correlation",
            "group_mask": "/test/group_mask.nii.gz"
        }
        
        result = await workflow_executor.execute_template("group_analysis", params)
        
        assert result.status == "success"
        
        # Verify execution timeline
        step_times = [(step.step_name, step.start_time, step.end_time) for step in result.step_results]
        
        # Group preparation should complete before subject analyses start
        prep_steps = [s for s in step_times if "preparation" in s[0]]
        subject_steps = [s for s in step_times if "subject_analysis" in s[0]]
        group_stats_steps = [s for s in step_times if "group_statistics" in s[0]]
        
        if prep_steps and subject_steps and group_stats_steps:
            latest_prep_end = max(s[2] for s in prep_steps)
            earliest_subject_start = min(s[1] for s in subject_steps)
            latest_subject_end = max(s[2] for s in subject_steps)
            earliest_stats_start = min(s[1] for s in group_stats_steps)
            
            assert latest_prep_end <= earliest_subject_start
            assert latest_subject_end <= earliest_stats_start


class TestTemplateExecutionErrorHandling:
    """Test error handling during template execution."""
    
    @pytest.mark.asyncio
    async def test_step_failure_handling(self, workflow_executor):
        """Test handling of individual step failures."""
        # Mock a failing tool
        failing_tool = Mock(side_effect=Exception("Tool execution failed"))
        
        with patch.object(workflow_executor.tool_registry, 'get_tool', return_value=failing_tool):
            params = {
                "input_data": "/test/data/sub-01_task-rest_bold.nii.gz",
                "tr": 2.0,
                "high_pass_cutoff": 0.01
            }
            
            result = await workflow_executor.execute_template("fmri_analysis", params)
            
            assert result.status == "failed"
            assert result.error_message is not None
            
            # Should have attempted to execute steps until failure
            assert len(result.step_results) > 0
            
            # At least one step should have failed
            failed_steps = [step for step in result.step_results if step.status == "failed"]
            assert len(failed_steps) > 0
    
    @pytest.mark.asyncio
    async def test_step_timeout_handling(self, workflow_executor):
        """Test handling of step timeouts."""
        # Mock a slow tool that times out
        async def slow_tool(*args, **kwargs):
            await asyncio.sleep(workflow_executor.step_timeout + 1)
            return {"status": "success"}
        
        with patch.object(workflow_executor.tool_registry, 'get_tool', return_value=slow_tool):
            params = {
                "input_data": "/test/data/sub-01_task-rest_bold.nii.gz", 
                "tr": 2.0,
                "high_pass_cutoff": 0.01
            }
            
            result = await workflow_executor.execute_template("fmri_analysis", params)
            
            assert result.status == "failed"
            
            # Should have timed out steps
            timeout_steps = [step for step in result.step_results if "timeout" in step.error_message.lower()]
            assert len(timeout_steps) > 0
    
    @pytest.mark.asyncio
    async def test_partial_failure_recovery(self, workflow_executor):
        """Test recovery from partial failures in parallel execution."""
        # Configure some subjects to fail, others to succeed
        success_subjects = ["/test/sub-01_bold.nii.gz", "/test/sub-03_bold.nii.gz"]
        failure_subjects = ["/test/sub-02_bold.nii.gz", "/test/sub-04_bold.nii.gz"]
        
        def mock_subject_tool(input_data=None, **kwargs):
            if input_data in failure_subjects:
                raise Exception(f"Processing failed for {input_data}")
            return {"status": "success", "subject_results": "mock_results"}
        
        with patch.object(workflow_executor.tool_registry, 'get_tool', return_value=mock_subject_tool):
            params = {
                "input_data": success_subjects + failure_subjects,
                "group_mask": "/test/group_mask.nii.gz"
            }
            
            result = await workflow_executor.execute_template("group_analysis", params)
            
            # Overall status depends on configuration - might be partial success
            assert result.status in ["partial_success", "failed"]
            
            # Should have both successful and failed steps
            success_steps = [step for step in result.step_results if step.status == "success"]
            failed_steps = [step for step in result.step_results if step.status == "failed"]
            
            assert len(success_steps) > 0
            assert len(failed_steps) > 0
    
    @pytest.mark.asyncio
    async def test_dependency_failure_propagation(self, workflow_executor):
        """Test that dependency failures properly propagate."""
        # Mock load_data to fail
        def mock_tool_selector(tool_name):
            if tool_name == "load_data":
                return Mock(side_effect=Exception("Data loading failed"))
            return Mock(return_value={"status": "success", "data": "mock_data"})
        
        with patch.object(workflow_executor.tool_registry, 'get_tool', side_effect=mock_tool_selector):
            params = {
                "input_data": "/test/data/sub-01_task-rest_bold.nii.gz",
                "tr": 2.0,
                "high_pass_cutoff": 0.01
            }
            
            result = await workflow_executor.execute_template("fmri_analysis", params)
            
            assert result.status == "failed"
            
            # Steps dependent on load_data should be skipped or failed
            load_step = next(step for step in result.step_results if step.step_name == "load_data")
            assert load_step.status == "failed"
            
            # Subsequent dependent steps should be skipped
            dependent_steps = [step for step in result.step_results 
                             if step.step_name in ["preprocessing", "save_results"]]
            
            for step in dependent_steps:
                assert step.status in ["skipped", "failed"]


class TestTemplateExecutionContext:
    """Test execution context management."""
    
    @pytest.mark.asyncio
    async def test_execution_context_data_flow(self, workflow_executor):
        """Test data flow between steps through execution context."""
        # Mock tools that pass data between steps
        def mock_tool_with_context(tool_name):
            if tool_name == "load_data":
                return Mock(return_value={"status": "success", "nifti_data": "loaded_data_object"})
            elif tool_name == "preprocess_fmri":
                def preprocess(nifti_data=None, **kwargs):
                    assert nifti_data == "loaded_data_object"  # Should receive output from load_data
                    return {"status": "success", "preprocessed_data": "processed_data_object"}
                return preprocess
            elif tool_name == "save_results":
                def save(preprocessed_data=None, **kwargs):
                    assert preprocessed_data == "processed_data_object"  # Should receive output from preprocess
                    return {"status": "success", "output_path": "/test/output.nii.gz"}
                return save
            else:
                return Mock(return_value={"status": "success"})
        
        with patch.object(workflow_executor.tool_registry, 'get_tool', side_effect=mock_tool_with_context):
            params = {
                "input_data": "/test/data/sub-01_task-rest_bold.nii.gz",
                "tr": 2.0,
                "high_pass_cutoff": 0.01
            }
            
            result = await workflow_executor.execute_template("fmri_analysis", params)
            
            assert result.status == "success"
            
            # Verify context data was passed correctly
            assert result.execution_context["nifti_data"] == "loaded_data_object"
            assert result.execution_context["preprocessed_data"] == "processed_data_object"
    
    @pytest.mark.asyncio
    async def test_execution_context_isolation(self, workflow_executor):
        """Test that execution contexts are isolated between parallel executions."""
        executed_contexts = []
        
        async def context_recording_tool(input_data=None, **kwargs):
            # Record the context for this execution
            context_copy = dict(kwargs)
            context_copy["input_data"] = input_data
            executed_contexts.append(context_copy)
            return {"status": "success", "subject_id": input_data}
        
        with patch.object(workflow_executor.tool_registry, 'get_tool', return_value=context_recording_tool):
            params = {
                "input_data": ["/test/sub-01_bold.nii.gz", "/test/sub-02_bold.nii.gz", "/test/sub-03_bold.nii.gz"],
                "group_mask": "/test/group_mask.nii.gz"
            }
            
            result = await workflow_executor.execute_template("group_analysis", params)
            
            assert result.status == "success"
            
            # Each parallel execution should have had its own context
            assert len(executed_contexts) >= 3
            
            # Contexts should have different input_data values
            input_data_values = [ctx["input_data"] for ctx in executed_contexts]
            assert len(set(input_data_values)) >= 3  # At least 3 unique values
    
    @pytest.mark.asyncio
    async def test_execution_context_persistence(self, workflow_executor):
        """Test that execution context persists across step executions."""
        context_values = []
        
        def context_tracking_tool(tool_name):
            def tool_func(**kwargs):
                # Track context values seen by this tool
                context_snapshot = {k: v for k, v in kwargs.items() if not k.startswith('_')}
                context_values.append((tool_name, context_snapshot))
                
                # Add new value to context
                return {"status": "success", f"{tool_name}_output": f"data_from_{tool_name}"}
            return tool_func
        
        with patch.object(workflow_executor.tool_registry, 'get_tool', side_effect=context_tracking_tool):
            params = {
                "input_data": "/test/data/sub-01_task-rest_bold.nii.gz",
                "tr": 2.0,
                "high_pass_cutoff": 0.01
            }
            
            result = await workflow_executor.execute_template("fmri_analysis", params)
            
            assert result.status == "success"
            
            # Later tools should see outputs from earlier tools
            load_context = next((ctx for tool, ctx in context_values if tool == "load_data"), None)
            preprocess_context = next((ctx for tool, ctx in context_values if tool == "preprocess_fmri"), None)
            
            if load_context and preprocess_context:
                # Preprocess should see load_data output
                assert "load_data_output" in preprocess_context


class TestTemplateExecutionPerformance:
    """Test template execution performance characteristics."""
    
    @pytest.mark.asyncio
    async def test_execution_performance_single_template(self, workflow_executor):
        """Test performance of single template execution."""
        params = {
            "input_data": "/test/data/sub-01_task-rest_bold.nii.gz",
            "tr": 2.0,
            "high_pass_cutoff": 0.01
        }
        
        # Execute template multiple times and measure performance
        execution_times = []
        
        for _ in range(10):
            start_time = time.time()
            result = await workflow_executor.execute_template("fmri_analysis", params)
            execution_time = time.time() - start_time
            execution_times.append(execution_time)
            
            assert result.status == "success"
        
        # Performance should be consistent
        avg_time = sum(execution_times) / len(execution_times)
        max_time = max(execution_times)
        min_time = min(execution_times)
        
        # Variation should be reasonable (less than 100% difference)
        assert (max_time - min_time) / avg_time < 1.0
        
        # Average execution time should be reasonable (< 1 second for mocked tools)
        assert avg_time < 1.0
    
    @pytest.mark.asyncio
    async def test_concurrent_template_execution(self, workflow_executor):
        """Test concurrent execution of multiple templates."""
        params_list = [
            {
                "input_data": f"/test/data/sub-{i:02d}_task-rest_bold.nii.gz",
                "tr": 2.0,
                "high_pass_cutoff": 0.01
            }
            for i in range(1, 6)  # 5 concurrent executions
        ]
        
        start_time = time.time()
        
        # Execute templates concurrently
        tasks = [
            workflow_executor.execute_template("fmri_analysis", params)
            for params in params_list
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        total_time = time.time() - start_time
        
        # All should succeed (or be exceptions we handle)
        successful_results = [r for r in results if not isinstance(r, Exception)]
        assert len(successful_results) == len(params_list)
        
        for result in successful_results:
            assert result.status == "success"
        
        # Concurrent execution should be faster than sequential
        # (This is a rough estimate based on mocked tools)
        estimated_sequential_time = len(params_list) * 0.1  # Assume 100ms per execution
        assert total_time < estimated_sequential_time * 1.5  # Allow 50% overhead
    
    @pytest.mark.asyncio
    async def test_resource_usage_monitoring(self, workflow_executor):
        """Test monitoring of resource usage during execution."""
        params = {
            "input_data": [f"/test/sub-{i:02d}_bold.nii.gz" for i in range(1, 21)],  # 20 subjects
            "group_mask": "/test/group_mask.nii.gz"
        }
        
        # Enable resource monitoring
        workflow_executor.enable_resource_monitoring = True
        
        result = await workflow_executor.execute_template("group_analysis", params)
        
        assert result.status == "success"
        
        # Should have resource usage data
        assert hasattr(result, 'resource_usage')
        assert result.resource_usage is not None
        
        # Should track memory and CPU usage
        assert 'peak_memory_mb' in result.resource_usage
        assert 'avg_cpu_percent' in result.resource_usage
        assert 'execution_duration_seconds' in result.resource_usage
        
        # Values should be reasonable
        assert result.resource_usage['peak_memory_mb'] > 0
        assert 0 <= result.resource_usage['avg_cpu_percent'] <= 100


class TestRealWorldScenarios:
    """Test realistic template execution scenarios."""
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_large_group_analysis_execution(self, workflow_executor):
        """Test execution of large group analysis template."""
        # Simulate large group study with many subjects
        params = {
            "input_data": [f"/test/derivatives/sub-{i:03d}/func/sub-{i:03d}_task-rest_space-MNI152NLin2009cAsym_desc-preproc_bold.nii.gz" 
                          for i in range(1, 51)],  # 50 subjects
            "group_mask": "/test/templates/MNI152NLin2009cAsym_res-2_desc-brain_mask.nii.gz",
            "confounds": [f"/test/derivatives/sub-{i:03d}/func/sub-{i:03d}_task-rest_desc-confounds_timeseries.tsv"
                         for i in range(1, 51)],
            "tr": 2.0,
            "high_pass_cutoff": 0.01,
            "smoothing_fwhm": 6.0
        }
        
        start_time = time.time()
        result = await workflow_executor.execute_template("group_analysis", params)
        execution_time = time.time() - start_time
        
        assert result.status in ["success", "partial_success"]
        
        # Should have processed all or most subjects
        subject_steps = [step for step in result.step_results if "subject_analysis" in step.step_name]
        assert len(subject_steps) >= 45  # Allow for some failures
        
        # Execution time should be reasonable for 50 subjects
        assert execution_time < 60  # Less than 1 minute with mocked tools
        
        # Should have group-level results
        group_steps = [step for step in result.step_results if "group_statistics" in step.step_name]
        assert len(group_steps) > 0
    
    @pytest.mark.asyncio
    async def test_multi_task_connectivity_analysis(self, workflow_executor):
        """Test execution of multi-task connectivity analysis."""
        params = {
            "input_data": {
                "rest": [f"/test/sub-{i:02d}_task-rest_bold.nii.gz" for i in range(1, 11)],
                "task": [f"/test/sub-{i:02d}_task-nback_bold.nii.gz" for i in range(1, 11)]
            },
            "connectivity_method": "correlation",
            "atlas": "/test/atlases/schaefer400_2mm.nii.gz",
            "tr": 2.0
        }
        
        result = await workflow_executor.execute_template("multi_task_connectivity", params)
        
        assert result.status == "success"
        
        # Should have connectivity analyses for both tasks
        rest_steps = [step for step in result.step_results if "rest" in step.step_name]
        task_steps = [step for step in result.step_results if "task" in step.step_name]
        
        assert len(rest_steps) >= 10  # One per subject
        assert len(task_steps) >= 10  # One per subject
        
        # Should have comparison analysis
        comparison_steps = [step for step in result.step_results if "comparison" in step.step_name]
        assert len(comparison_steps) > 0
    
    @pytest.mark.asyncio
    async def test_longitudinal_analysis_execution(self, workflow_executor):
        """Test execution of longitudinal analysis template."""
        params = {
            "baseline_data": [f"/test/timepoint1/sub-{i:02d}_task-rest_bold.nii.gz" for i in range(1, 21)],
            "followup_data": [f"/test/timepoint2/sub-{i:02d}_task-rest_bold.nii.gz" for i in range(1, 21)],
            "demographics": "/test/participants.tsv",
            "time_between_scans": "12_months",
            "tr": 2.0
        }
        
        result = await workflow_executor.execute_template("longitudinal_analysis", params)
        
        assert result.status == "success"
        
        # Should have within-subject analyses
        within_subject_steps = [step for step in result.step_results if "within_subject" in step.step_name]
        assert len(within_subject_steps) >= 20  # One per subject
        
        # Should have group-level change analysis
        change_steps = [step for step in result.step_results if "change_analysis" in step.step_name]
        assert len(change_steps) > 0
    
    @pytest.mark.asyncio
    async def test_error_recovery_in_complex_workflow(self, workflow_executor):
        """Test error recovery in complex multi-step workflow."""
        # Simulate scenario where some subjects fail at different stages
        failure_config = {
            "load_failures": ["/test/sub-03_bold.nii.gz", "/test/sub-07_bold.nii.gz"],
            "preprocess_failures": ["/test/sub-05_bold.nii.gz"],
            "analysis_failures": ["/test/sub-11_bold.nii.gz"]
        }
        
        def selective_failure_tool(tool_name):
            def tool_func(input_data=None, **kwargs):
                if (tool_name == "load_data" and input_data in failure_config["load_failures"]) or \
                   (tool_name == "preprocess_fmri" and input_data in failure_config["preprocess_failures"]) or \
                   (tool_name == "compute_glm" and input_data in failure_config["analysis_failures"]):
                    raise Exception(f"{tool_name} failed for {input_data}")
                
                return {"status": "success", f"{tool_name}_output": f"result_for_{input_data}"}
            
            return tool_func
        
        with patch.object(workflow_executor.tool_registry, 'get_tool', side_effect=selective_failure_tool):
            params = {
                "input_data": [f"/test/sub-{i:02d}_bold.nii.gz" for i in range(1, 16)],  # 15 subjects
                "group_mask": "/test/group_mask.nii.gz"
            }
            
            result = await workflow_executor.execute_template("group_analysis", params)
            
            # Should have partial success - some subjects processed successfully
            assert result.status in ["partial_success", "success"]
            
            # Count successful vs failed subjects
            successful_subjects = 0
            failed_subjects = 0
            
            for step in result.step_results:
                if "subject_analysis" in step.step_name:
                    if step.status == "success":
                        successful_subjects += 1
                    else:
                        failed_subjects += 1
            
            # Should have both successes and failures
            assert successful_subjects > 0
            assert failed_subjects > 0
            
            # Group analysis should still proceed with available data
            group_steps = [step for step in result.step_results if "group_statistics" in step.step_name]
            assert len(group_steps) > 0


class TestTemplateExecutionMetrics:
    """Test collection of execution metrics."""
    
    @pytest.mark.asyncio
    async def test_execution_timing_metrics(self, workflow_executor):
        """Test collection of detailed execution timing metrics."""
        params = {
            "input_data": "/test/data/sub-01_task-rest_bold.nii.gz",
            "tr": 2.0,
            "high_pass_cutoff": 0.01
        }
        
        result = await workflow_executor.execute_template("fmri_analysis", params)
        
        assert result.status == "success"
        
        # Should have timing data for each step
        for step_result in result.step_results:
            assert hasattr(step_result, 'start_time')
            assert hasattr(step_result, 'end_time') 
            assert hasattr(step_result, 'duration')
            
            assert step_result.start_time > 0
            assert step_result.end_time >= step_result.start_time
            assert step_result.duration > 0
        
        # Should have overall execution metrics
        assert hasattr(result, 'total_duration')
        assert hasattr(result, 'step_count')
        assert hasattr(result, 'parallel_step_count')
        
        assert result.total_duration > 0
        assert result.step_count == len(result.step_results)
    
    @pytest.mark.asyncio
    async def test_execution_success_rate_metrics(self, workflow_executor):
        """Test tracking of execution success rates."""
        # Configure partial failures
        def partially_failing_tool(tool_name):
            def tool_func(**kwargs):
                # Fail 20% of the time
                import random
                if random.random() < 0.2:
                    raise Exception(f"Random failure in {tool_name}")
                return {"status": "success", "data": "mock_result"}
            return tool_func
        
        with patch.object(workflow_executor.tool_registry, 'get_tool', side_effect=partially_failing_tool):
            params = {
                "input_data": [f"/test/sub-{i:02d}_bold.nii.gz" for i in range(1, 21)],  # 20 subjects
                "group_mask": "/test/group_mask.nii.gz"
            }
            
            result = await workflow_executor.execute_template("group_analysis", params)
            
            # Should collect success rate metrics
            assert hasattr(result, 'success_rate')
            assert hasattr(result, 'failure_count')
            assert hasattr(result, 'success_count')
            
            assert 0 <= result.success_rate <= 1.0
            assert result.success_count + result.failure_count <= result.step_count
    
    @pytest.mark.asyncio
    async def test_execution_resource_metrics(self, workflow_executor):
        """Test collection of resource usage metrics."""
        # Enable detailed resource monitoring
        workflow_executor.collect_resource_metrics = True
        
        params = {
            "input_data": [f"/test/sub-{i:02d}_bold.nii.gz" for i in range(1, 11)],
            "group_mask": "/test/group_mask.nii.gz"
        }
        
        result = await workflow_executor.execute_template("group_analysis", params)
        
        assert result.status in ["success", "partial_success"]
        
        # Should have resource metrics
        assert hasattr(result, 'resource_metrics')
        assert result.resource_metrics is not None
        
        metrics = result.resource_metrics
        
        # Should track various resource dimensions
        expected_metrics = [
            'peak_memory_usage_mb',
            'avg_memory_usage_mb', 
            'peak_cpu_percent',
            'avg_cpu_percent',
            'disk_io_read_mb',
            'disk_io_write_mb',
            'network_io_mb'
        ]
        
        for metric in expected_metrics:
            assert metric in metrics
            assert isinstance(metrics[metric], (int, float))
            assert metrics[metric] >= 0


if __name__ == "__main__":
    pytest.main([__file__])