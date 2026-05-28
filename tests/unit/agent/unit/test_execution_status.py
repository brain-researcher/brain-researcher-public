"""
Unit tests for execution status tracking system.
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fakeredis import FakeRedis

from brain_researcher.services.agent.execution_status import (
    AsyncExecutionTracker,
    ExecutionMetrics,
    ExecutionStatus,
    ExecutionStep,
    ExecutionTracker,
    StepStatus,
)


class TestExecutionStep:
    """Test ExecutionStep functionality."""
    
    def test_step_creation(self):
        """Test creating an execution step."""
        step = ExecutionStep(
            name="Test Step",
            description="A test step",
            estimated_duration=10.0
        )
        
        assert step.name == "Test Step"
        assert step.description == "A test step"
        assert step.status == StepStatus.WAITING
        assert step.progress == 0.0
        assert step.estimated_duration == 10.0
        
    def test_step_start(self):
        """Test starting a step."""
        step = ExecutionStep(name="Test")
        step.start()
        
        assert step.status == StepStatus.RUNNING
        assert step.started_at is not None
        
    def test_step_complete_success(self):
        """Test completing a step successfully."""
        step = ExecutionStep(name="Test")
        step.start()
        time.sleep(0.01)  # Ensure some duration
        step.complete()
        
        assert step.status == StepStatus.COMPLETED
        assert step.progress == 100.0
        assert step.completed_at is not None
        assert step.actual_duration is not None
        assert step.actual_duration > 0
        
    def test_step_complete_with_error(self):
        """Test completing a step with error."""
        step = ExecutionStep(name="Test")
        step.start()
        step.complete(error="Test error")
        
        assert step.status == StepStatus.FAILED
        assert step.error == "Test error"
        assert step.completed_at is not None
        
    def test_step_skip(self):
        """Test skipping a step."""
        step = ExecutionStep(name="Test")
        step.skip("Not needed")
        
        assert step.status == StepStatus.SKIPPED
        assert step.completed_at is not None
        assert step.metadata["skip_reason"] == "Not needed"
        
    def test_step_progress_update(self):
        """Test updating step progress."""
        step = ExecutionStep(name="Test")
        
        step.update_progress(50.0)
        assert step.progress == 50.0
        
        step.update_progress(150.0)  # Test clamping
        assert step.progress == 100.0
        
        step.update_progress(-10.0)  # Test clamping
        assert step.progress == 0.0


class TestExecutionMetrics:
    """Test ExecutionMetrics functionality."""
    
    def test_metrics_update_from_steps(self):
        """Test updating metrics from steps."""
        steps = [
            ExecutionStep(name="Step1"),
            ExecutionStep(name="Step2"),
            ExecutionStep(name="Step3"),
        ]
        
        # Complete first step
        steps[0].start()
        steps[0].actual_duration = 5.0
        steps[0].status = StepStatus.COMPLETED
        
        # Skip second step
        steps[1].status = StepStatus.SKIPPED
        
        # Third step waiting
        
        metrics = ExecutionMetrics()
        metrics.update_from_steps(steps)
        
        assert metrics.total_steps == 3
        assert metrics.completed_steps == 1
        assert metrics.skipped_steps == 1
        assert metrics.failed_steps == 0
        assert metrics.average_step_duration == 5.0
        assert metrics.estimated_time_remaining == 5.0  # 1 pending * 5.0 average


class TestExecutionTracker:
    """Test ExecutionTracker functionality."""
    
    @pytest.fixture
    def tracker(self):
        """Create a tracker instance."""
        return ExecutionTracker(redis_client=FakeRedis())
        
    def test_tracker_creation(self, tracker):
        """Test creating a tracker."""
        assert tracker.execution_id is not None
        assert tracker.status == ExecutionStatus.PENDING
        assert len(tracker.steps) == 0
        assert tracker.overall_progress == 0.0
        
    def test_add_step(self, tracker):
        """Test adding steps to tracker."""
        step1 = tracker.add_step("Step 1", "First step", estimated_duration=10.0)
        step2 = tracker.add_step("Step 2", "Second step", estimated_duration=20.0)
        
        assert len(tracker.steps) == 2
        assert tracker.steps[0].name == "Step 1"
        assert tracker.steps[1].name == "Step 2"
        
    def test_start_execution(self, tracker):
        """Test starting execution."""
        tracker.start_execution()
        
        assert tracker.status == ExecutionStatus.RUNNING
        assert tracker.started_at is not None
        
    def test_start_step(self, tracker):
        """Test starting a step."""
        tracker.add_step("Step 1")
        tracker.add_step("Step 2")
        
        # Start first step
        step = tracker.start_step()
        assert step is not None
        assert step.status == StepStatus.RUNNING
        assert tracker.current_step_index == 0
        
        # Complete first step
        tracker.complete_step()
        
        # Should auto-start next step
        assert tracker.current_step_index == 1
        assert tracker.steps[1].status == StepStatus.RUNNING
        
    def test_update_step_progress(self, tracker):
        """Test updating step progress."""
        tracker.add_step("Step 1")
        tracker.start_step()
        
        tracker.update_step_progress(50.0, message="Halfway there")
        
        step = tracker.steps[0]
        assert step.progress == 50.0
        assert step.metadata["progress_message"] == "Halfway there"
        
    def test_complete_step_success(self, tracker):
        """Test completing a step successfully."""
        tracker.add_step("Step 1")
        tracker.start_execution()
        tracker.start_step()
        
        tracker.complete_step(result={"output": "test"})
        
        step = tracker.steps[0]
        assert step.status == StepStatus.COMPLETED
        assert step.metadata["result"] == {"output": "test"}
        
    def test_complete_step_with_error(self, tracker):
        """Test completing a step with error."""
        tracker.add_step("Step 1")
        tracker.start_step()
        
        tracker.complete_step(error="Test error")
        
        step = tracker.steps[0]
        assert step.status == StepStatus.FAILED
        assert step.error == "Test error"
        
    def test_skip_step(self, tracker):
        """Test skipping a step."""
        tracker.add_step("Step 1")
        tracker.add_step("Step 2")
        
        tracker.skip_step(1, "Not needed")
        
        assert tracker.steps[1].status == StepStatus.SKIPPED
        assert tracker.steps[1].metadata["skip_reason"] == "Not needed"
        
    def test_complete_execution_success(self, tracker):
        """Test completing execution successfully."""
        tracker.add_step("Step 1")
        tracker.start_execution()
        tracker.start_step()
        tracker.complete_step()
        
        tracker.complete_execution(result={"final": "output"})
        
        assert tracker.status == ExecutionStatus.COMPLETED
        assert tracker.overall_progress == 100.0
        assert tracker.completed_at is not None
        assert tracker.result == {"final": "output"}
        
    def test_complete_execution_with_error(self, tracker):
        """Test completing execution with error."""
        tracker.start_execution()
        tracker.complete_execution(error="Fatal error")
        
        assert tracker.status == ExecutionStatus.FAILED
        assert tracker.error == "Fatal error"
        assert tracker.completed_at is not None
        
    def test_cancel_execution(self, tracker):
        """Test cancelling execution."""
        tracker.add_step("Step 1")
        tracker.add_step("Step 2")
        tracker.start_execution()
        tracker.start_step()
        
        tracker.cancel_execution("User cancelled")
        
        assert tracker.status == ExecutionStatus.CANCELLED
        assert tracker.metadata["cancellation_reason"] == "User cancelled"
        assert tracker.steps[1].status == StepStatus.SKIPPED
        
    def test_pause_and_resume(self, tracker):
        """Test pausing and resuming execution."""
        tracker.start_execution()
        
        tracker.pause_execution()
        assert tracker.status == ExecutionStatus.PAUSED
        assert "paused_at" in tracker.metadata
        
        time.sleep(0.01)
        tracker.resume_execution()
        assert tracker.status == ExecutionStatus.RUNNING
        assert "total_pause_duration" in tracker.metadata
        
    def test_retry_execution(self, tracker):
        """Test retrying failed execution."""
        tracker.add_step("Step 1")
        tracker.start_execution()
        tracker.start_step()
        tracker.complete_step(error="Error")
        tracker.complete_execution(error="Failed")
        
        assert tracker.status == ExecutionStatus.FAILED
        
        tracker.retry_execution()
        
        assert tracker.status == ExecutionStatus.RUNNING
        assert tracker.error is None
        assert tracker.steps[0].status == StepStatus.WAITING
        assert tracker.steps[0].error is None
        
    def test_get_status(self, tracker):
        """Test getting execution status."""
        tracker.add_step("Step 1")
        tracker.start_execution()
        
        status = tracker.get_status()
        
        assert status["execution_id"] == tracker.execution_id
        assert status["status"] == ExecutionStatus.RUNNING
        assert status["overall_progress"] == 0.0
        assert len(status["steps"]) == 1
        assert "metrics" in status
        assert "eta" in status
        
    def test_get_progress_summary(self, tracker):
        """Test getting progress summary."""
        tracker.add_step("Step 1")
        tracker.add_step("Step 2")
        tracker.start_execution()
        tracker.start_step()
        tracker.complete_step()
        
        summary = tracker.get_progress_summary()
        
        assert summary["execution_id"] == tracker.execution_id
        assert summary["steps_completed"] == "1/2"
        assert "elapsed_time" in summary
        assert "eta" in summary
        
    def test_overall_progress_calculation(self, tracker):
        """Test overall progress calculation."""
        tracker.add_step("Step 1")
        tracker.add_step("Step 2")
        tracker.add_step("Step 3")
        
        # Complete first step
        tracker.start_step(0)
        tracker.complete_step(0)
        tracker._calculate_overall_progress()
        assert tracker.overall_progress == pytest.approx(33.33, rel=0.1)
        
        # Half complete second step
        tracker.start_step(1)
        tracker.update_step_progress(50.0, 1)
        tracker._calculate_overall_progress()
        assert tracker.overall_progress == pytest.approx(50.0, rel=0.1)
        
        # Skip third step
        tracker.skip_step(2)
        tracker._calculate_overall_progress()
        assert tracker.overall_progress == pytest.approx(83.33, rel=0.1)
        
    def test_eta_calculation(self, tracker):
        """Test ETA calculation."""
        tracker.add_step("Step 1", estimated_duration=10.0)
        tracker.add_step("Step 2", estimated_duration=20.0)
        
        # Complete first step
        tracker.start_step(0)
        tracker.steps[0].actual_duration = 15.0  # Took longer than estimated
        tracker.complete_step(0)
        
        # Update metrics
        tracker._update_metrics()
        
        # Should estimate remaining time based on actual duration
        assert tracker.metrics.estimated_time_remaining == 15.0
        
        eta = tracker._calculate_eta()
        assert eta is not None
        assert "minute" in eta.lower() or ":" in eta
        
    def test_persistence(self, tracker):
        """Test state persistence and restoration."""
        # Add steps and make progress
        tracker.add_step("Step 1")
        tracker.add_step("Step 2")
        tracker.start_execution()
        tracker.start_step()
        tracker.complete_step()
        
        # Get state
        state = tracker.get_status()
        
        # Create new tracker with same ID
        new_tracker = ExecutionTracker(
            execution_id=tracker.execution_id,
            redis_client=tracker.redis_client
        )
        
        # Should restore state
        assert new_tracker.status == tracker.status
        assert len(new_tracker.steps) == len(tracker.steps)
        assert new_tracker.steps[0].status == StepStatus.COMPLETED
        
    def test_update_callback(self):
        """Test update callback functionality."""
        updates = []
        
        def callback(update):
            updates.append(update)
            
        tracker = ExecutionTracker(update_callback=callback)
        
        tracker.add_step("Step 1")
        tracker.start_execution()
        
        # Should have received updates
        assert len(updates) > 0
        assert any(u["event"] == "execution_started" for u in updates)


class TestAsyncExecutionTracker:
    """Test AsyncExecutionTracker functionality."""
    
    @pytest.fixture
    def tracker(self):
        """Create an async tracker instance."""
        return AsyncExecutionTracker(redis_client=FakeRedis())
        
    @pytest.mark.asyncio
    async def test_async_listener(self, tracker):
        """Test async listener functionality."""
        updates = []
        
        async def listener(update):
            updates.append(update)
            
        await tracker.add_listener(listener)
        
        # Trigger updates
        await tracker.start_step_async()
        await tracker.update_step_progress_async(50.0)
        await tracker.complete_step_async()
        
        # Allow async operations to complete
        await asyncio.sleep(0.01)
        
        # Should have received updates
        assert len(updates) > 0
        
    @pytest.mark.asyncio
    async def test_remove_listener(self, tracker):
        """Test removing a listener."""
        updates = []
        
        async def listener(update):
            updates.append(update)
            
        await tracker.add_listener(listener)
        await tracker.remove_listener(listener)
        
        # Trigger update
        await tracker.start_step_async()
        
        # Should not receive update
        await asyncio.sleep(0.01)
        assert len(updates) == 0
        
    @pytest.mark.asyncio
    async def test_async_methods(self, tracker):
        """Test async versions of methods."""
        tracker.add_step("Step 1")
        
        # Test async start
        step = await tracker.start_step_async()
        assert step is not None
        assert step.status == StepStatus.RUNNING
        
        # Test async progress update
        await tracker.update_step_progress_async(75.0, message="Almost done")
        assert tracker.steps[0].progress == 75.0
        
        # Test async complete
        await tracker.complete_step_async(result={"done": True})
        assert tracker.steps[0].status == StepStatus.COMPLETED


class TestIntegration:
    """Integration tests for execution tracking."""
    
    @pytest.mark.asyncio
    async def test_full_execution_flow(self):
        """Test complete execution flow."""
        tracker = AsyncExecutionTracker()
        
        # Add execution plan
        tracker.add_step("Load Data", estimated_duration=5.0)
        tracker.add_step("Preprocess", estimated_duration=10.0)
        tracker.add_step("Analyze", estimated_duration=20.0)
        tracker.add_step("Generate Report", estimated_duration=5.0)
        
        # Start execution
        tracker.start_execution()
        
        # Execute steps
        for i in range(4):
            await tracker.start_step_async()
            
            # Simulate progress
            for progress in [25, 50, 75, 100]:
                await tracker.update_step_progress_async(progress)
                await asyncio.sleep(0.001)
                
            await tracker.complete_step_async(result=f"Step {i+1} result")
            
        # Complete execution
        tracker.complete_execution(result="All done")
        
        # Verify final state
        assert tracker.status == ExecutionStatus.COMPLETED
        assert tracker.overall_progress == 100.0
        assert all(s.status == StepStatus.COMPLETED for s in tracker.steps)
        assert tracker.metrics.completed_steps == 4
        
    @pytest.mark.asyncio
    async def test_execution_with_errors(self):
        """Test execution with error handling."""
        tracker = AsyncExecutionTracker()
        
        tracker.add_step("Step 1")
        tracker.add_step("Step 2")
        tracker.add_step("Step 3")
        
        tracker.start_execution()
        
        # First step succeeds
        await tracker.start_step_async()
        await tracker.complete_step_async()
        
        # Second step fails
        await tracker.start_step_async()
        await tracker.complete_step_async(error="Network error")
        
        # Third step skipped
        tracker.skip_step(2, "Skipped due to previous error")
        
        # Complete with error
        tracker.complete_execution(error="Execution failed")
        
        # Verify state
        assert tracker.status == ExecutionStatus.FAILED
        assert tracker.metrics.completed_steps == 1
        assert tracker.metrics.failed_steps == 1
        assert tracker.metrics.skipped_steps == 1
        
    def test_concurrent_executions(self):
        """Test multiple concurrent executions."""
        trackers = []
        
        for i in range(5):
            tracker = ExecutionTracker(execution_id=f"exec_{i}")
            tracker.add_step(f"Step for execution {i}")
            tracker.start_execution()
            trackers.append(tracker)
            
        # Each should have unique ID
        ids = [t.execution_id for t in trackers]
        assert len(set(ids)) == 5
        
        # Each should track independently
        for i, tracker in enumerate(trackers):
            tracker.start_step()
            tracker.update_step_progress(i * 20)
            
        # Verify independent progress
        for i, tracker in enumerate(trackers):
            assert tracker.steps[0].progress == i * 20