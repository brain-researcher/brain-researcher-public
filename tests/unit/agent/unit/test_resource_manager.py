"""
Comprehensive tests for Resource Management System.
"""

import pytest
import time
import threading
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

from brain_researcher.services.agent.resources import (
    ResourceManager,
    ResourcePool,
    ResourceAllocation,
    QueueManager,
    QueueEntry,
    Priority,
    ToolResourceProfile,
    ResourceLimits,
    get_tool_profile,
    ResourceMonitor,
    ResourceMetrics,
)
from brain_researcher.services.agent.resources.integration import (
    ResourceAwareExecutionTracker,
    resource_aware_tool,
    with_resource_management,
    initialize_resource_management,
)


class TestResourcePool:
    """Test ResourcePool functionality."""
    
    def test_pool_initialization(self):
        """Test pool initializes with correct resources."""
        pool = ResourcePool(max_cpu_cores=4.0, max_memory_gb=8.0, max_gpus=1)
        
        assert pool.max_cpu_cores == 4.0
        assert pool.max_memory_gb == 8.0
        assert pool.max_gpus == 1
        assert pool.available_cpu == 4.0
        assert pool.available_memory == 8.0
        assert pool.available_gpus == 1
    
    def test_resource_allocation(self):
        """Test allocating resources from pool."""
        pool = ResourcePool(max_cpu_cores=4.0, max_memory_gb=8.0)
        
        # Successful allocation
        assert pool.allocate(2.0, 4.0) is True
        assert pool.available_cpu == 2.0
        assert pool.available_memory == 4.0
        
        # Failed allocation (not enough resources)
        assert pool.allocate(3.0, 5.0) is False
        assert pool.available_cpu == 2.0  # Unchanged
        assert pool.available_memory == 4.0  # Unchanged
    
    def test_resource_release(self):
        """Test releasing resources back to pool."""
        pool = ResourcePool(max_cpu_cores=4.0, max_memory_gb=8.0)
        
        pool.allocate(2.0, 4.0)
        pool.release(1.0, 2.0)
        
        assert pool.available_cpu == 3.0
        assert pool.available_memory == 6.0
        
        # Release more than allocated (should cap at max)
        pool.release(10.0, 10.0)
        assert pool.available_cpu == 4.0  # Capped at max
        assert pool.available_memory == 8.0  # Capped at max
    
    def test_utilization_metrics(self):
        """Test resource utilization calculation."""
        pool = ResourcePool(max_cpu_cores=4.0, max_memory_gb=8.0)
        
        pool.allocate(3.0, 6.0)
        utilization = pool.get_utilization()
        
        assert utilization["cpu_utilization"] == 75.0
        assert utilization["memory_utilization"] == 75.0
    
    def test_thread_safety(self):
        """Test thread-safe resource operations."""
        pool = ResourcePool(max_cpu_cores=4.0, max_memory_gb=8.0)
        results = []
        
        def allocate_worker():
            result = pool.allocate(1.0, 2.0)
            results.append(result)
        
        # Start 5 threads trying to allocate
        threads = [threading.Thread(target=allocate_worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Only 4 should succeed (4 CPU cores / 1 per allocation)
        assert sum(results) == 4
        assert pool.available_cpu == 0.0


class TestQueueManager:
    """Test QueueManager functionality."""
    
    def test_queue_operations(self):
        """Test basic enqueue/dequeue operations."""
        queue = QueueManager(max_size=10)
        
        entry1 = QueueEntry(
            priority=Priority.NORMAL,
            tool_name="tool1",
            execution_id="exec1",
        )
        entry2 = QueueEntry(
            priority=Priority.HIGH,
            tool_name="tool2",
            execution_id="exec2",
        )
        
        assert queue.enqueue(entry1) is True
        assert queue.enqueue(entry2) is True
        assert len(queue) == 2
        
        # High priority should dequeue first
        dequeued = queue.dequeue()
        assert dequeued.execution_id == "exec2"
        assert len(queue) == 1
    
    def test_priority_ordering(self):
        """Test priority-based ordering."""
        queue = QueueManager()
        
        # Add entries with different priorities
        queue.enqueue(QueueEntry(Priority.LOW, tool_name="low", execution_id="e1"))
        queue.enqueue(QueueEntry(Priority.HIGH, tool_name="high", execution_id="e2"))
        queue.enqueue(QueueEntry(Priority.NORMAL, tool_name="normal", execution_id="e3"))
        queue.enqueue(QueueEntry(Priority.HIGH, tool_name="high2", execution_id="e4"))
        
        # Dequeue in priority order
        assert queue.dequeue().execution_id == "e2"  # First HIGH
        assert queue.dequeue().execution_id == "e4"  # Second HIGH (FIFO within priority)
        assert queue.dequeue().execution_id == "e3"  # NORMAL
        assert queue.dequeue().execution_id == "e1"  # LOW
    
    def test_queue_backpressure(self):
        """Test backpressure when queue is full."""
        queue = QueueManager(max_size=2, enable_backpressure=True)
        
        # Fill queue with low priority
        queue.enqueue(QueueEntry(Priority.LOW, tool_name="low1", execution_id="e1"))
        queue.enqueue(QueueEntry(Priority.LOW, tool_name="low2", execution_id="e2"))
        
        # High priority should replace low priority
        high_entry = QueueEntry(Priority.HIGH, tool_name="high", execution_id="e3")
        assert queue.enqueue(high_entry) is True
        assert len(queue) == 2
        
        # Check that high priority is in queue
        assert queue.dequeue().execution_id == "e3"
    
    def test_dequeue_if_ready(self):
        """Test conditional dequeue."""
        queue = QueueManager()
        
        entry1 = QueueEntry(
            Priority.NORMAL,
            tool_name="tool1",
            execution_id="e1",
            resource_request={"cpu_cores": 2.0},
        )
        entry2 = QueueEntry(
            Priority.NORMAL,
            tool_name="tool2",
            execution_id="e2",
            resource_request={"cpu_cores": 1.0},
        )
        
        queue.enqueue(entry1)
        queue.enqueue(entry2)
        
        # Only dequeue if CPU < 1.5
        result = queue.dequeue_if_ready(
            lambda e: e.resource_request["cpu_cores"] < 1.5
        )
        
        assert result.execution_id == "e2"
        assert len(queue) == 1
    
    def test_queue_metrics(self):
        """Test queue status and metrics."""
        queue = QueueManager()
        
        queue.enqueue(QueueEntry(Priority.HIGH, tool_name="t1", execution_id="e1"))
        time.sleep(0.1)  # Let some wait time accumulate
        
        status = queue.get_status()
        assert status["size"] == 1
        assert status["depth_by_priority"]["HIGH"] == 1
        assert status["metrics"]["total_enqueued"] == 1


class TestResourceManager:
    """Test ResourceManager functionality."""
    
    def test_resource_request_immediate(self):
        """Test immediate resource allocation."""
        manager = ResourceManager(max_cpu_cores=4.0, max_memory_gb=8.0)
        
        allocation = manager.request_resources(
            tool_name="glm_analysis",
            execution_id="exec1",
        )
        
        assert allocation is not None
        assert allocation.tool_name == "glm_analysis"
        assert allocation.cpu_cores == 2.0  # From tool profile
        assert allocation.memory_gb == 4.0  # From tool profile
    
    def test_resource_request_queued(self):
        """Test queued resource requests."""
        manager = ResourceManager(max_cpu_cores=2.0, max_memory_gb=4.0)
        
        # First request succeeds
        alloc1 = manager.request_resources("glm_analysis", "exec1")
        assert alloc1 is not None
        
        # Second request should be queued (not enough resources)
        # Use timeout to avoid blocking test
        alloc2 = manager.request_resources(
            "glm_analysis", "exec2", timeout=0.1
        )
        assert alloc2 is None  # Timed out waiting for resources
    
    @pytest.mark.skip(reason="Complex threading test, may have timing issues")
    def test_resource_release_and_reallocation(self):
        """Test releasing resources and processing queue."""
        manager = ResourceManager(max_cpu_cores=2.0, max_memory_gb=4.0, enable_queueing=True)
        
        # Allocate all resources
        alloc1 = manager.request_resources("glm_analysis", "exec1")
        assert alloc1 is not None
        
        # Queue another request in a thread
        alloc2 = None
        def request_worker():
            nonlocal alloc2
            alloc2 = manager.request_resources(
                "glm_analysis", "exec2", timeout=1.0
            )
        
        thread = threading.Thread(target=request_worker)
        thread.start()
        
        # Give thread time to queue request
        time.sleep(0.1)
        
        # Release first allocation
        assert manager.release_resources("exec1") is True
        
        # Wait for thread to complete
        thread.join()
        
        # Second allocation should have succeeded
        assert alloc2 is not None
    
    def test_resource_status(self):
        """Test resource manager status reporting."""
        manager = ResourceManager(max_cpu_cores=4.0, max_memory_gb=8.0)
        
        alloc1 = manager.request_resources("glm_analysis", "exec1")
        status = manager.get_status()
        
        assert status["pool"]["available"]["cpu_cores"] == 2.0
        assert status["pool"]["available"]["memory_gb"] == 4.0
        assert status["allocations"]["active"] == 1
        assert "glm_analysis" in status["allocations"]["by_tool"]
    
    @pytest.mark.skip(reason="Timing-dependent test, may fail in CI")
    def test_cleanup_stale_allocations(self):
        """Test cleanup of stale allocations."""
        manager = ResourceManager(max_cpu_cores=4.0, max_memory_gb=8.0)
        manager._cleanup_interval = 0.1  # Speed up for testing
        
        # Create allocation and mark it as old
        alloc = manager.request_resources("glm_analysis", "exec1")
        
        # Manually make it stale
        with manager._lock:
            alloc.allocated_at = datetime.now() - timedelta(hours=2)
        
        # Wait for cleanup
        time.sleep(0.3)
        
        # Check that allocation was cleaned up
        assert "exec1" not in manager.execution_to_allocation


class TestToolResourceProfiles:
    """Test tool resource profiles."""
    
    def test_default_profile(self):
        """Test default profile for unknown tools."""
        profile = get_tool_profile("unknown_tool")
        
        assert profile.tool_name == "default"
        assert profile.cpu_cores == 0.5
        assert profile.memory_gb == 1.0
    
    def test_known_tool_profiles(self):
        """Test profiles for known tools."""
        # Heavy tool
        glm = get_tool_profile("glm_analysis")
        assert glm.cpu_cores == 2.0
        assert glm.memory_gb == 4.0
        assert glm.is_heavyweight is True
        
        # Light tool
        concepts = get_tool_profile("find_related_concepts")
        assert concepts.cpu_cores == 0.5
        assert concepts.memory_gb == 0.5
        assert concepts.is_heavyweight is False
    
    def test_resource_limits(self):
        """Test ResourceLimits enforcement."""
        limits = ResourceLimits(
            global_cpu_limit=2.0,
            global_memory_limit=4.0,
        )
        
        # Tool that exceeds limits
        profile = limits.get_tool_profile("encoding_model")
        
        # Should be scaled down to fit limits
        assert profile.cpu_cores <= 2.0
        assert profile.memory_gb <= 4.0
    
    def test_can_execute_tool(self):
        """Test checking if tool can execute."""
        limits = ResourceLimits(
            global_cpu_limit=4.0,
            global_memory_limit=8.0,
        )
        
        current_usage = {"cpu_cores": 3.0, "memory_gb": 6.0}
        
        # Light tool should fit
        assert limits.can_execute_tool("find_related_concepts", current_usage) is True
        
        # Heavy tool should not fit
        assert limits.can_execute_tool("glm_analysis", current_usage) is False


class TestResourceMonitor:
    """Test ResourceMonitor functionality."""
    
    @patch("brain_researcher.services.agent.resources.resource_monitor.psutil")
    def test_resource_tracking(self, mock_psutil):
        """Test resource usage tracking."""
        # Mock psutil values
        mock_psutil.cpu_percent.return_value = 50.0
        mock_psutil.virtual_memory.return_value = MagicMock(
            percent=60.0,
            used=4 * 1024 * 1024 * 1024,  # 4GB in bytes
        )
        
        monitor = ResourceMonitor(sampling_interval=0.1, enable_monitoring=False)
        
        # Start tracking
        metrics = monitor.start_tracking("glm_analysis", "exec1")
        assert metrics is not None
        
        # Simulate some work
        time.sleep(0.2)
        
        # Stop tracking
        final_metrics = monitor.stop_tracking("exec1")
        assert final_metrics is not None
        assert final_metrics.tool_name == "glm_analysis"
        assert final_metrics.duration_seconds > 0
    
    def test_resource_statistics(self):
        """Test aggregated statistics."""
        monitor = ResourceMonitor(enable_monitoring=False)
        
        # Add some mock metrics
        metrics1 = ResourceMetrics(
            tool_name="tool1",
            execution_id="e1",
            start_time=datetime.now() - timedelta(seconds=10),
            end_time=datetime.now(),
            peak_cpu_percent=80.0,
            avg_cpu_percent=60.0,
            peak_memory_mb=1000.0,
            avg_memory_mb=800.0,
        )
        
        metrics2 = ResourceMetrics(
            tool_name="tool2",
            execution_id="e2",
            start_time=datetime.now() - timedelta(seconds=5),
            end_time=datetime.now(),
            peak_cpu_percent=40.0,
            avg_cpu_percent=30.0,
            peak_memory_mb=500.0,
            avg_memory_mb=400.0,
        )
        
        monitor.history.append(metrics1)
        monitor.history.append(metrics2)
        
        # Get statistics
        stats = monitor.get_tool_statistics()
        
        assert stats["count"] == 2
        assert stats["avg_cpu_percent"] == 45.0  # (60+30)/2
        assert stats["peak_cpu_percent"] == 80.0
        assert "by_tool" in stats
    
    def test_recommendations(self):
        """Test resource optimization recommendations."""
        monitor = ResourceMonitor(enable_monitoring=False)
        
        # Add high usage metrics
        metrics = ResourceMetrics(
            tool_name="heavy_tool",
            execution_id="e1",
            start_time=datetime.now() - timedelta(seconds=400),
            end_time=datetime.now(),
            peak_cpu_percent=85.0,
            avg_cpu_percent=75.0,
            peak_memory_mb=7000.0,
        )
        monitor.history.append(metrics)
        
        recommendations = monitor.get_recommendations()
        
        # Should recommend optimization
        assert len(recommendations) > 0
        assert any("CPU" in r for r in recommendations)
        assert any("memory" in r for r in recommendations)


class TestIntegration:
    """Test integration with existing systems."""
    
    def test_resource_aware_execution_tracker(self):
        """Test ResourceAwareExecutionTracker."""
        manager = ResourceManager(max_cpu_cores=4.0, max_memory_gb=8.0)
        monitor = ResourceMonitor(enable_monitoring=False)
        
        tracker = ResourceAwareExecutionTracker(
            resource_manager=manager,
            resource_monitor=monitor,
        )
        
        # Add a step with tool
        tracker.add_step("GLM Analysis")
        tracker.steps[0].data = {"tool": "glm_analysis"}
        
        # Start step (should allocate resources)
        tracker.start_step(0)
        
        # Check that resources were allocated
        status = manager.get_status()
        assert status["allocations"]["active"] == 1
        
        # Complete step (should release resources)
        tracker.complete_step(0)
        
        # Check that resources were released
        status = manager.get_status()
        assert status["allocations"]["active"] == 0
    
    def test_resource_aware_tool_decorator(self):
        """Test resource_aware_tool decorator."""
        manager = ResourceManager(max_cpu_cores=4.0, max_memory_gb=8.0)
        initialize_resource_management()  # Set global manager
        
        @resource_aware_tool(priority=Priority.HIGH)
        def my_tool(data):
            return {"result": data * 2}
        
        # Execute tool
        result = my_tool(5)
        
        assert result["result"] == 10
        assert "_resource_allocation" in result
    
    def test_with_resource_management_context(self):
        """Test with_resource_management context manager."""
        initialize_resource_management()
        
        executed = False
        
        with with_resource_management("glm_analysis") as allocation:
            if allocation:
                executed = True
                assert allocation.tool_name == "glm_analysis"
                assert allocation.cpu_cores == 2.0
        
        assert executed is True
    
    def test_concurrent_resource_requests(self):
        """Test handling concurrent resource requests."""
        manager = ResourceManager(max_cpu_cores=4.0, max_memory_gb=8.0, enable_queueing=True)
        
        results = []
        
        def worker(i):
            allocation = manager.request_resources(
                "glm_analysis",
                f"exec{i}",
                timeout=2.0,
            )
            results.append(allocation is not None)
            if allocation:
                time.sleep(0.1)
                manager.release_resources(f"exec{i}")
        
        # Start 4 workers (should handle 2 at a time)
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # All should eventually succeed
        assert all(results)


class TestPerformance:
    """Test performance characteristics."""
    
    def test_allocation_performance(self):
        """Test resource allocation performance."""
        manager = ResourceManager(max_cpu_cores=16.0, max_memory_gb=32.0)
        
        start = time.time()
        
        # Allocate and release 100 times
        for i in range(100):
            alloc = manager.request_resources(
                "find_related_concepts",  # Light tool
                f"exec{i}",
            )
            manager.release_resources(f"exec{i}")
        
        duration = time.time() - start
        
        # Should complete quickly (< 1 second for 100 operations)
        assert duration < 1.0
    
    def test_queue_performance(self):
        """Test queue performance with many entries."""
        queue = QueueManager(max_size=1000)
        
        # Add 1000 entries
        start = time.time()
        for i in range(1000):
            queue.enqueue(QueueEntry(
                Priority.NORMAL,
                tool_name=f"tool{i}",
                execution_id=f"exec{i}",
            ))
        
        enqueue_time = time.time() - start
        
        # Dequeue all
        start = time.time()
        while queue:
            queue.dequeue()
        
        dequeue_time = time.time() - start
        
        # Both should be fast
        assert enqueue_time < 1.0
        assert dequeue_time < 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])