"""
Unit tests for Execution Provenance Tracking (AGENT-019).

Tests the ExecutionTracker and related components for tracking
execution status and provenance information.
"""

import asyncio
import json
import pytest
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from brain_researcher.services.agent.execution_status import (
    ExecutionTracker,
    AsyncExecutionTracker,
    ExecutionStep,
    ExecutionMetrics,
    ExecutionStatus,
    StepStatus
)


class TestExecutionStep:
    """Test execution step functionality."""
    
    def test_step_creation(self):
        """Test execution step creation."""
        step = ExecutionStep(
            name="Test Step",
            description="Test step description",
            estimated_duration=3600.0
        )
        
        assert step.name == "Test Step"
        assert step.description == "Test step description"
        assert step.status == StepStatus.WAITING
        assert step.progress == 0.0
        assert step.estimated_duration == 3600.0
        assert step.started_at is None
        assert step.completed_at is None
    
    def test_step_lifecycle(self):
        """Test step lifecycle methods."""
        step = ExecutionStep(name="Test Step")
        
        # Test start
        step.start()
        assert step.status == StepStatus.RUNNING
        assert step.started_at is not None
        
        # Test progress update
        step.update_progress(50.0)
        assert step.progress == 50.0
        
        # Test completion
        step.complete()
        assert step.status == StepStatus.COMPLETED
        assert step.progress == 100.0
        assert step.completed_at is not None
        assert step.actual_duration is not None
        assert step.actual_duration > 0
    
    def test_step_failure(self):
        """Test step failure handling."""
        step = ExecutionStep(name="Test Step")
        step.start()
        
        # Test failure
        step.complete(error="Test error")
        assert step.status == StepStatus.FAILED
        assert step.error == "Test error"
        assert step.completed_at is not None
    
    def test_step_skip(self):
        """Test step skip functionality."""
        step = ExecutionStep(name="Test Step")
        
        step.skip("Not needed")
        assert step.status == StepStatus.SKIPPED
        assert step.completed_at is not None
        assert step.metadata["skip_reason"] == "Not needed"
    
    def test_progress_bounds(self):
        """Test progress value bounds."""
        step = ExecutionStep(name="Test Step")
        
        # Test lower bound
        step.update_progress(-10.0)
        assert step.progress == 0.0
        
        # Test upper bound
        step.update_progress(120.0)
        assert step.progress == 100.0
        
        # Test normal range
        step.update_progress(75.0)
        assert step.progress == 75.0


class TestExecutionMetrics:
    """Test execution metrics functionality."""
    
    def test_metrics_initialization(self):
        """Test metrics initialization."""
        metrics = ExecutionMetrics()
        
        assert metrics.total_steps == 0
        assert metrics.completed_steps == 0
        assert metrics.failed_steps == 0
        assert metrics.skipped_steps == 0
        assert metrics.total_duration == 0.0
        assert metrics.average_step_duration == 0.0
        assert metrics.estimated_time_remaining == 0.0
    
    def test_metrics_update_from_steps(self):
        """Test metrics update from execution steps."""
        # Create test steps
        steps = [
            ExecutionStep(name="Step 1", estimated_duration=1800.0),
            ExecutionStep(name="Step 2", estimated_duration=3600.0),
            ExecutionStep(name="Step 3", estimated_duration=900.0),
        ]
        
        # Simulate step execution
        steps[0].start()
        steps[0].complete()
        steps[0].actual_duration = 1650.0  # Faster than estimated
        
        steps[1].start()
        steps[1].complete(error="Test error")
        steps[1].actual_duration = 1200.0  # Failed early
        
        steps[2].skip("Not needed")
        
        # Update metrics
        metrics = ExecutionMetrics()
        metrics.update_from_steps(steps)
        
        assert metrics.total_steps == 3
        assert metrics.completed_steps == 1
        assert metrics.failed_steps == 1
        assert metrics.skipped_steps == 1
        assert metrics.average_step_duration > 0  # Should use actual durations
    
    def test_metrics_with_no_actual_durations(self):
        """Test metrics with only estimated durations."""
        steps = [
            ExecutionStep(name="Step 1", estimated_duration=1800.0),
            ExecutionStep(name="Step 2", estimated_duration=3600.0),
        ]
        
        metrics = ExecutionMetrics()
        metrics.update_from_steps(steps)
        
        # Should use estimated durations
        assert metrics.average_step_duration == 2700.0  # (1800 + 3600) / 2
        assert metrics.estimated_time_remaining == 5400.0  # 2 pending * 2700


class TestExecutionTracker:
    """Test execution tracker functionality."""
    
    @pytest.fixture
    def tracker(self):
        """Create execution tracker for testing."""
        return ExecutionTracker()
    
    @pytest.fixture
    def test_data_path(self):
        """Path to test data fixtures."""
        return Path(__file__).parent.parent / "fixtures" / "AGENT-019"
    
    def test_tracker_initialization(self, tracker):
        """Test tracker initialization."""
        assert tracker.execution_id is not None
        assert tracker.status == ExecutionStatus.PENDING
        assert len(tracker.steps) == 0
        assert tracker.current_step_index is None
        assert tracker.overall_progress == 0.0
        assert tracker.created_at > 0
    
    def test_add_step(self, tracker):
        """Test adding steps to tracker."""
        step = tracker.add_step(
            name="Test Step",
            description="Test step description",
            estimated_duration=3600.0,
            metadata={"tool": "test_tool"}
        )
        
        assert isinstance(step, ExecutionStep)
        assert len(tracker.steps) == 1
        assert tracker.steps[0] == step
        assert step.name == "Test Step"
        assert step.metadata["tool"] == "test_tool"
    
    def test_execution_workflow(self, tracker):
        """Test complete execution workflow."""
        # Add steps
        tracker.add_step("Step 1", "First step", 1000.0)
        tracker.add_step("Step 2", "Second step", 2000.0)
        tracker.add_step("Step 3", "Third step", 1500.0)
        
        # Start execution
        tracker.start_execution()
        assert tracker.status == ExecutionStatus.RUNNING
        assert tracker.started_at is not None
        
        # Start first step
        step = tracker.start_step()
        assert step is not None
        assert step.name == "Step 1"
        assert tracker.current_step_index == 0
        assert step.status == StepStatus.RUNNING
        
        # Update progress
        tracker.update_step_progress(50.0, message="Halfway done")
        assert tracker.steps[0].progress == 50.0
        assert tracker.steps[0].metadata["progress_message"] == "Halfway done"
        
        # Complete first step
        tracker.complete_step(result="Step 1 result")
        assert tracker.steps[0].status == StepStatus.COMPLETED
        assert tracker.steps[0].metadata["result"] == "Step 1 result"
        
        # Should auto-start next step
        assert tracker.current_step_index == 1
        assert tracker.steps[1].status == StepStatus.RUNNING
        
        # Complete second step
        tracker.complete_step()
        assert tracker.steps[1].status == StepStatus.COMPLETED
        
        # Complete third step
        tracker.complete_step()
        assert tracker.steps[2].status == StepStatus.COMPLETED
        
        # Complete execution
        tracker.complete_execution(result="All done")
        assert tracker.status == ExecutionStatus.COMPLETED
        assert tracker.result == "All done"
        assert tracker.completed_at is not None
        assert tracker.overall_progress == 100.0
    
    def test_step_failure_handling(self, tracker):
        """Test step failure handling."""
        tracker.add_step("Test Step", "Will fail", 1000.0)
        tracker.start_execution()
        
        # Start and fail step
        step = tracker.start_step()
        tracker.complete_step(error="Test error")
        
        assert step.status == StepStatus.FAILED
        assert step.error == "Test error"
        assert tracker.status == ExecutionStatus.RUNNING  # Execution continues
    
    def test_execution_cancellation(self, tracker):
        """Test execution cancellation."""
        tracker.add_step("Step 1", "First step", 1000.0)
        tracker.add_step("Step 2", "Second step", 2000.0)
        
        tracker.start_execution()
        
        # Cancel execution
        tracker.cancel_execution("User requested")
        
        assert tracker.status == ExecutionStatus.CANCELLED
        assert tracker.metadata["cancellation_reason"] == "User requested"
        
        # Pending steps should be marked as skipped
        for step in tracker.steps:
            if step.status == StepStatus.WAITING:
                assert step.status == StepStatus.SKIPPED
    
    def test_execution_pause_resume(self, tracker):
        """Test execution pause and resume."""
        tracker.add_step("Test Step", "Will be paused", 1000.0)
        tracker.start_execution()
        
        # Pause execution
        tracker.pause_execution()
        assert tracker.status == ExecutionStatus.PAUSED
        assert "paused_at" in tracker.metadata
        
        # Resume execution
        tracker.resume_execution()
        assert tracker.status == ExecutionStatus.RUNNING
        assert "total_pause_duration" in tracker.metadata
    
    def test_execution_retry(self, tracker):
        """Test execution retry after failure."""
        tracker.add_step("Test Step", "Will fail then retry", 1000.0)
        tracker.start_execution()
        
        # Fail execution
        tracker.complete_execution(error="Test failure")
        assert tracker.status == ExecutionStatus.FAILED
        
        # Retry execution
        tracker.retry_execution()
        assert tracker.status == ExecutionStatus.RUNNING
        assert tracker.error is None
        
        # Failed steps should be reset
        for step in tracker.steps:
            if step.status == StepStatus.FAILED:
                assert step.status == StepStatus.WAITING
    
    def test_status_retrieval(self, tracker):
        """Test status retrieval."""
        tracker.add_step("Step 1", "First step", 1000.0)
        tracker.add_step("Step 2", "Second step", 2000.0)
        tracker.start_execution()
        
        status = tracker.get_status()
        
        assert status["execution_id"] == tracker.execution_id
        assert status["status"] == tracker.status
        assert status["overall_progress"] == tracker.overall_progress
        assert "steps" in status
        assert "metrics" in status
        assert "created_at" in status
        assert "eta" in status
    
    def test_progress_summary(self, tracker):
        """Test progress summary."""
        tracker.add_step("Step 1", "First step", 1000.0)
        tracker.add_step("Step 2", "Second step", 2000.0)
        tracker.start_execution()
        
        # Complete first step
        tracker.start_step()
        tracker.complete_step()
        
        summary = tracker.get_progress_summary()
        
        assert summary["execution_id"] == tracker.execution_id
        assert summary["status"] == tracker.status
        assert summary["steps_completed"] == "1/2"
        assert "eta" in summary
        assert "elapsed_time" in summary
    
    def test_overall_progress_calculation(self, tracker):
        """Test overall progress calculation."""
        tracker.add_step("Step 1", "First step", 1000.0)
        tracker.add_step("Step 2", "Second step", 2000.0)
        tracker.add_step("Step 3", "Third step", 1500.0)
        
        # No progress initially
        assert tracker.overall_progress == 0.0
        
        # Complete one step
        tracker.steps[0].status = StepStatus.COMPLETED
        tracker._calculate_overall_progress()
        assert tracker.overall_progress == pytest.approx(33.33, rel=1e-2)
        
        # Start another step with 50% progress
        tracker.steps[1].status = StepStatus.RUNNING
        tracker.steps[1].progress = 50.0
        tracker._calculate_overall_progress()
        assert tracker.overall_progress == pytest.approx(50.0, rel=1e-2)  # (1 + 0.5) / 3 * 100
        
        # Skip the last step
        tracker.steps[2].status = StepStatus.SKIPPED
        tracker._calculate_overall_progress()
        assert tracker.overall_progress == pytest.approx(83.33, rel=1e-2)  # (1 + 0.5 + 1) / 3 * 100
    
    def test_eta_calculation(self, tracker):
        """Test ETA calculation."""
        tracker.add_step("Step 1", "First step", 1000.0)
        tracker.add_step("Step 2", "Second step", 2000.0)
        
        # Complete one step to establish timing
        tracker.steps[0].status = StepStatus.COMPLETED
        tracker.steps[0].actual_duration = 800.0  # Faster than estimated
        
        tracker._update_metrics()
        
        eta = tracker._calculate_eta()
        assert eta is not None  # Should have an ETA with remaining work
    
    @patch('redis.from_url')
    def test_state_persistence(self, mock_redis, tracker):
        """Test state persistence to Redis."""
        # Mock Redis client
        mock_client = MagicMock()
        mock_redis.return_value = mock_client
        
        tracker.redis_client = mock_client
        tracker.add_step("Test Step", "Persistent step", 1000.0)
        
        # Trigger persistence
        tracker._persist_state()
        
        # Verify Redis interaction
        mock_client.setex.assert_called_once()
        call_args = mock_client.setex.call_args
        assert call_args[0][0] == f"execution:{tracker.execution_id}"
        assert call_args[0][1] == tracker.persistence_ttl


class TestAsyncExecutionTracker:
    """Test async execution tracker functionality."""
    
    @pytest.fixture
    def async_tracker(self):
        """Create async execution tracker for testing."""
        return AsyncExecutionTracker()
    
    @pytest.mark.asyncio
    async def test_async_listener_management(self, async_tracker):
        """Test async listener management."""
        updates = []
        
        async def test_listener(update):
            updates.append(update)
        
        # Add listener
        await async_tracker.add_listener(test_listener)
        assert test_listener in async_tracker.update_listeners
        
        # Remove listener
        await async_tracker.remove_listener(test_listener)
        assert test_listener not in async_tracker.update_listeners
    
    @pytest.mark.asyncio
    async def test_async_progress_updates(self, async_tracker):
        """Test async progress updates."""
        updates = []
        
        async def capture_updates(update):
            updates.append(update)
        
        await async_tracker.add_listener(capture_updates)
        async_tracker.add_step("Test Step", "Async test", 1000.0)
        
        # Start step asynchronously
        step = await async_tracker.start_step_async()
        assert len(updates) > 0
        assert updates[-1]["event"] == "step_started"
        
        # Update progress asynchronously
        await async_tracker.update_step_progress_async(50.0, message="Async progress")
        assert len(updates) > 1
        assert updates[-1]["event"] == "step_progress"
        
        # Complete step asynchronously
        await async_tracker.complete_step_async()
        assert len(updates) > 2
        assert updates[-1]["event"] == "step_completed"


class TestExecutionTrackerIntegration:
    """Integration tests for execution tracker."""
    
    @pytest.fixture
    def test_data_path(self):
        """Path to test data fixtures."""
        return Path(__file__).parent.parent / "fixtures" / "AGENT-019"
    
    def test_realistic_neuroimaging_workflow(self, test_data_path):
        """Test tracking of realistic neuroimaging workflow."""
        # Load test execution trace
        with open(test_data_path / "provenance_test_data.json") as f:
            test_data = json.load(f)
        
        trace = test_data["execution_traces"]["simple_preprocessing"]
        
        # Create tracker and recreate execution
        tracker = ExecutionTracker(execution_id=trace["execution_id"])
        
        # Add steps from trace
        for step_data in trace["steps"]:
            tracker.add_step(
                name=step_data["name"],
                description=f"Tool: {step_data['tool_name']}",
                estimated_duration=step_data["completed_at"] - step_data["started_at"],
                metadata=step_data.get("metadata", {})
            )
        
        # Simulate execution
        tracker.start_execution()
        
        for i, step_data in enumerate(trace["steps"]):
            step = tracker.start_step(i)
            
            # Simulate progress
            tracker.update_step_progress(25.0)
            tracker.update_step_progress(50.0)
            tracker.update_step_progress(75.0)
            
            # Complete step
            tracker.complete_step(
                step_index=i,
                result=step_data.get("outputs", {})
            )
        
        # Complete execution
        tracker.complete_execution(result="Workflow completed successfully")
        
        # Verify final state
        assert tracker.status == ExecutionStatus.COMPLETED
        assert tracker.overall_progress == 100.0
        assert len(tracker.steps) == len(trace["steps"])
        assert all(step.status == StepStatus.COMPLETED for step in tracker.steps)
    
    def test_provenance_data_capture(self, test_data_path):
        """Test capture of provenance data."""
        tracker = ExecutionTracker()
        
        # Add steps with detailed metadata
        tracker.add_step(
            name="fMRIPrep Preprocessing",
            description="Preprocessing with fMRIPrep",
            estimated_duration=7200.0,
            metadata={
                "tool": "fmriprep",
                "version": "21.0.2",
                "inputs": {
                    "bids_dir": "/data/bids",
                    "output_dir": "/outputs/fmriprep"
                },
                "parameters": {
                    "nthreads": 4,
                    "mem_mb": 8192,
                    "use_syn_sdc": True
                }
            }
        )
        
        tracker.start_execution()
        step = tracker.start_step()
        
        # Simulate tool execution with provenance tracking
        step.metadata.update({
            "execution_environment": {
                "container": "fmriprep:21.0.2",
                "host": "compute-node-01",
                "started_at": time.time()
            }
        })
        
        tracker.complete_step(result={
            "outputs": {
                "preprocessed_bold": "/outputs/sub-01_bold.nii.gz",
                "confounds": "/outputs/sub-01_confounds.tsv"
            },
            "provenance": {
                "input_checksums": {"bold.nii.gz": "sha256:abc123"},
                "output_checksums": {"preprocessed_bold.nii.gz": "sha256:def456"},
                "software_versions": {"fmriprep": "21.0.2", "fsl": "6.0.4"}
            }
        })
        
        tracker.complete_execution()
        
        # Verify provenance data is captured
        status = tracker.get_status()
        step_result = status["steps"][0]["metadata"]["result"]
        
        assert "provenance" in step_result
        assert "input_checksums" in step_result["provenance"]
        assert "software_versions" in step_result["provenance"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])