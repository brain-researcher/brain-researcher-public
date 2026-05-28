"""Tests for Distributed Worker Node

Tests worker node functionality including task execution,
resource management, and communication with coordinator.
"""

import pytest
import asyncio
import json
import time
import psutil
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
from typing import Dict, List, Any

from brain_researcher.services.agent.distributed.worker_node import (
    WorkerNode, TaskExecutor, ResourceMonitor, TaskResult, TaskStatus,
    WorkerNodeConfig, TaskRequest
)
from brain_researcher.services.agent.distributed.coordinator import (
    ResourceCapacity, NodeStatus
)


class TestTaskRequest:
    """Test task request handling"""
    
    def test_task_request_creation(self):
        """Test task request creation with all fields"""
        task_request = TaskRequest(
            task_id="task_123",
            task_type="fmri_analysis",
            payload={"data": "test"},
            priority=5,
            timeout_seconds=300,
            resource_requirements={
                "cpu_cores": 2,
                "memory_gb": 4.0,
                "gpu_memory_gb": 1.0
            }
        )
        
        assert task_request.task_id == "task_123"
        assert task_request.task_type == "fmri_analysis"
        assert task_request.priority == 5
        assert task_request.timeout_seconds == 300
        assert task_request.resource_requirements["cpu_cores"] == 2
        
    def test_task_request_serialization(self):
        """Test task request to/from dict conversion"""
        original = TaskRequest(
            task_id="task_456",
            task_type="preprocessing",
            payload={"input": "data.nii"},
            priority=3
        )
        
        data = original.to_dict()
        reconstructed = TaskRequest.from_dict(data)
        
        assert reconstructed.task_id == original.task_id
        assert reconstructed.task_type == original.task_type
        assert reconstructed.payload == original.payload
        assert reconstructed.priority == original.priority


class TestTaskResult:
    """Test task result handling"""
    
    def test_task_result_creation(self):
        """Test task result creation with success"""
        result = TaskResult(
            task_id="task_123",
            status=TaskStatus.COMPLETED,
            result_data={"output": "analysis_results.json"},
            execution_time=45.6,
            resource_usage={
                "peak_memory_mb": 2048,
                "cpu_utilization": 85.5
            }
        )
        
        assert result.task_id == "task_123"
        assert result.status == TaskStatus.COMPLETED
        assert result.execution_time == 45.6
        assert result.resource_usage["peak_memory_mb"] == 2048
        
    def test_task_result_with_error(self):
        """Test task result creation with error"""
        result = TaskResult(
            task_id="task_456",
            status=TaskStatus.FAILED,
            error_message="Out of memory",
            error_traceback="Traceback...",
            execution_time=12.3
        )
        
        assert result.status == TaskStatus.FAILED
        assert result.error_message == "Out of memory"
        assert "Traceback" in result.error_traceback
        
    def test_task_result_serialization(self):
        """Test task result serialization"""
        original = TaskResult(
            task_id="task_789",
            status=TaskStatus.COMPLETED,
            result_data={"success": True},
            execution_time=30.0
        )
        
        data = original.to_dict()
        reconstructed = TaskResult.from_dict(data)
        
        assert reconstructed.task_id == original.task_id
        assert reconstructed.status == original.status
        assert reconstructed.result_data == original.result_data


class TestResourceMonitor:
    """Test resource monitoring functionality"""
    
    @pytest.fixture
    def resource_monitor(self):
        """Create resource monitor for testing"""
        return ResourceMonitor(monitoring_interval=0.1)
        
    @pytest.mark.asyncio
    async def test_resource_monitor_start_stop(self, resource_monitor):
        """Test starting and stopping resource monitor"""
        # Start monitoring
        await resource_monitor.start()
        assert resource_monitor._running is True
        assert resource_monitor._monitor_task is not None
        
        # Allow some monitoring cycles
        await asyncio.sleep(0.2)
        
        # Stop monitoring
        await resource_monitor.stop()
        assert resource_monitor._running is False
        
    @pytest.mark.asyncio
    async def test_get_current_usage(self, resource_monitor):
        """Test getting current resource usage"""
        usage = resource_monitor.get_current_usage()
        
        assert "cpu_percent" in usage
        assert "memory_percent" in usage
        assert "memory_available_gb" in usage
        assert "disk_usage_percent" in usage
        assert "network_io" in usage
        
        # Values should be reasonable
        assert 0 <= usage["cpu_percent"] <= 100
        assert 0 <= usage["memory_percent"] <= 100
        assert usage["memory_available_gb"] >= 0
        
    def test_get_capacity(self, resource_monitor):
        """Test getting system capacity"""
        capacity = resource_monitor.get_capacity()
        
        assert isinstance(capacity, ResourceCapacity)
        assert capacity.cpu_cores > 0
        assert capacity.memory_gb > 0
        
    @pytest.mark.asyncio
    async def test_resource_history_tracking(self, resource_monitor):
        """Test resource usage history tracking"""
        await resource_monitor.start()
        await asyncio.sleep(0.3)  # Allow multiple readings
        await resource_monitor.stop()
        
        history = resource_monitor.get_usage_history(limit=10)
        
        assert len(history) > 0
        assert all("timestamp" in entry for entry in history)
        assert all("cpu_percent" in entry for entry in history)
        
    def test_resource_alerts(self, resource_monitor):
        """Test resource usage alerts"""
        # Set thresholds
        resource_monitor.set_alert_thresholds(
            cpu_threshold=80.0,
            memory_threshold=90.0,
            disk_threshold=95.0
        )
        
        # Check alerts with high usage
        high_usage = {
            "cpu_percent": 85.0,
            "memory_percent": 95.0,
            "disk_usage_percent": 75.0
        }
        
        alerts = resource_monitor.check_alerts(high_usage)
        
        assert len(alerts) == 2  # CPU and memory alerts
        assert any("CPU usage" in alert for alert in alerts)
        assert any("Memory usage" in alert for alert in alerts)


class TestTaskExecutor:
    """Test task execution functionality"""
    
    @pytest.fixture
    def task_executor(self):
        """Create task executor for testing"""
        return TaskExecutor(max_concurrent_tasks=2)
        
    @pytest.mark.asyncio
    async def test_task_executor_initialization(self, task_executor):
        """Test task executor initialization"""
        assert task_executor.max_concurrent_tasks == 2
        assert len(task_executor.running_tasks) == 0
        assert len(task_executor.task_results) == 0
        
    @pytest.mark.asyncio
    async def test_simple_task_execution(self, task_executor):
        """Test executing a simple task"""
        async def simple_task(**kwargs):
            return {"result": kwargs.get("input", "default")}
            
        task_request = TaskRequest(
            task_id="simple_task",
            task_type="test",
            payload={"input": "test_data"},
            timeout_seconds=10
        )
        
        # Register task function
        task_executor.register_task_function("test", simple_task)
        
        # Execute task
        result = await task_executor.execute_task(task_request)
        
        assert result.status == TaskStatus.COMPLETED
        assert result.result_data["result"] == "test_data"
        assert result.execution_time > 0
        
    @pytest.mark.asyncio
    async def test_task_execution_with_error(self, task_executor):
        """Test task execution with error handling"""
        async def failing_task(**kwargs):
            raise ValueError("Task failed intentionally")
            
        task_request = TaskRequest(
            task_id="failing_task",
            task_type="fail",
            payload={},
            timeout_seconds=10
        )
        
        task_executor.register_task_function("fail", failing_task)
        
        result = await task_executor.execute_task(task_request)
        
        assert result.status == TaskStatus.FAILED
        assert "Task failed intentionally" in result.error_message
        assert result.error_traceback is not None
        
    @pytest.mark.asyncio
    async def test_task_timeout(self, task_executor):
        """Test task timeout handling"""
        async def slow_task(**kwargs):
            await asyncio.sleep(2.0)  # Longer than timeout
            return {"result": "completed"}
            
        task_request = TaskRequest(
            task_id="slow_task",
            task_type="slow",
            payload={},
            timeout_seconds=0.5  # Short timeout
        )
        
        task_executor.register_task_function("slow", slow_task)
        
        result = await task_executor.execute_task(task_request)
        
        assert result.status == TaskStatus.FAILED
        assert "timeout" in result.error_message.lower()
        
    @pytest.mark.asyncio
    async def test_concurrent_task_limit(self, task_executor):
        """Test concurrent task execution limits"""
        async def long_task(**kwargs):
            await asyncio.sleep(0.5)
            return {"result": "done"}
            
        task_executor.register_task_function("long", long_task)
        
        # Create multiple tasks
        tasks = [
            TaskRequest(f"task_{i}", "long", {}, timeout_seconds=10)
            for i in range(5)
        ]
        
        # Execute all tasks concurrently
        start_time = time.time()
        results = await asyncio.gather(*[
            task_executor.execute_task(task) 
            for task in tasks
        ])
        execution_time = time.time() - start_time
        
        # Should take longer due to concurrency limit
        expected_min_time = 0.5 * (len(tasks) // task_executor.max_concurrent_tasks + 
                                 (1 if len(tasks) % task_executor.max_concurrent_tasks else 0))
        
        assert execution_time >= expected_min_time * 0.9  # Allow some variance
        assert all(r.status == TaskStatus.COMPLETED for r in results)
        
    @pytest.mark.asyncio
    async def test_task_cancellation(self, task_executor):
        """Test task cancellation functionality"""
        async def cancellable_task(**kwargs):
            try:
                await asyncio.sleep(2.0)
                return {"result": "completed"}
            except asyncio.CancelledError:
                return {"result": "cancelled"}
                
        task_request = TaskRequest(
            task_id="cancel_test",
            task_type="cancellable",
            payload={},
            timeout_seconds=10
        )
        
        task_executor.register_task_function("cancellable", cancellable_task)
        
        # Start task execution
        task_future = asyncio.create_task(task_executor.execute_task(task_request))
        
        # Cancel after short delay
        await asyncio.sleep(0.1)
        success = await task_executor.cancel_task("cancel_test")
        
        assert success is True
        
        # Wait for result
        result = await task_future
        assert result.status == TaskStatus.CANCELLED


@pytest.mark.asyncio
class TestWorkerNode:
    """Test complete worker node functionality"""
    
    @pytest.fixture
    async def redis_mock(self):
        """Mock Redis client"""
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock(return_value=True)
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.hset = AsyncMock(return_value=1)
        mock_redis.publish = AsyncMock(return_value=1)
        return mock_redis
        
    @pytest.fixture
    def worker_config(self):
        """Create worker node configuration"""
        return WorkerNodeConfig(
            node_id="test_worker",
            coordinator_url="http://localhost:5000",
            max_concurrent_tasks=3,
            heartbeat_interval=1,
            resource_monitoring_interval=1
        )
        
    @pytest.fixture
    async def worker_node(self, worker_config, redis_mock):
        """Create worker node for testing"""
        node = WorkerNode(worker_config, redis_mock)
        return node
        
    async def test_worker_node_initialization(self, worker_node, worker_config):
        """Test worker node initialization"""
        assert worker_node.config == worker_config
        assert worker_node.status == NodeStatus.JOINING
        assert worker_node.task_executor is not None
        assert worker_node.resource_monitor is not None
        
    async def test_worker_node_startup(self, worker_node, redis_mock):
        """Test worker node startup process"""
        with patch('brain_researcher.services.agent.distributed.worker_node.aiohttp.ClientSession') as mock_session:
            mock_response = AsyncMock()
            mock_response.json = AsyncMock(return_value={"message": "registered"})
            mock_response.status = 200
            mock_session.return_value.__aenter__.return_value.post.return_value.__aenter__.return_value = mock_response
            
            await worker_node.start()
            
            assert worker_node.is_running is True
            assert worker_node.status == NodeStatus.ACTIVE
            
            # Clean up
            await worker_node.stop()
            
    async def test_task_assignment_handling(self, worker_node, redis_mock):
        """Test handling task assignments from coordinator"""
        # Register a test task function
        async def test_task(**kwargs):
            return {"processed": kwargs.get("data")}
            
        worker_node.task_executor.register_task_function("test_analysis", test_task)
        
        # Create task assignment
        task_request = TaskRequest(
            task_id="assigned_task",
            task_type="test_analysis",
            payload={"data": "brain_scan.nii"},
            timeout_seconds=30
        )
        
        # Handle task assignment
        result = await worker_node.handle_task_assignment(task_request)
        
        assert result.status == TaskStatus.COMPLETED
        assert result.result_data["processed"] == "brain_scan.nii"
        
    async def test_heartbeat_reporting(self, worker_node, redis_mock):
        """Test heartbeat reporting to coordinator"""
        await worker_node.start()
        
        # Wait for heartbeat
        await asyncio.sleep(1.1)
        
        # Verify heartbeat was sent to Redis
        redis_mock.setex.assert_called()
        
        # Check heartbeat data
        calls = redis_mock.setex.call_args_list
        assert len(calls) >= 1
        
        key = calls[0][0][0]
        heartbeat_data = json.loads(calls[0][0][2])
        
        assert f"heartbeat:{worker_node.config.node_id}" in key
        assert "timestamp" in heartbeat_data
        assert "status" in heartbeat_data
        assert "resource_usage" in heartbeat_data
        
        await worker_node.stop()
        
    async def test_resource_usage_reporting(self, worker_node, redis_mock):
        """Test resource usage reporting"""
        await worker_node.start()
        await asyncio.sleep(1.1)  # Allow resource monitoring
        
        usage = worker_node.get_current_resource_usage()
        
        assert "cpu_percent" in usage
        assert "memory_percent" in usage
        assert "active_tasks" in usage
        assert usage["node_id"] == worker_node.config.node_id
        
        await worker_node.stop()
        
    async def test_task_queue_management(self, worker_node):
        """Test task queue management"""
        # Add tasks to queue
        tasks = [
            TaskRequest(f"queued_task_{i}", "test", {"id": i}, timeout_seconds=10)
            for i in range(5)
        ]
        
        for task in tasks:
            await worker_node.queue_task(task)
            
        assert worker_node.get_queued_task_count() == 5
        
        # Process queue
        async def dummy_task(**kwargs):
            return {"id": kwargs.get("id")}
            
        worker_node.task_executor.register_task_function("test", dummy_task)
        
        results = []
        while not worker_node.is_queue_empty():
            task = await worker_node.dequeue_task()
            result = await worker_node.task_executor.execute_task(task)
            results.append(result)
            
        assert len(results) == 5
        assert all(r.status == TaskStatus.COMPLETED for r in results)
        
    async def test_graceful_shutdown(self, worker_node, redis_mock):
        """Test graceful shutdown handling"""
        # Start worker
        await worker_node.start()
        
        # Add a long-running task
        async def long_task(**kwargs):
            await asyncio.sleep(1.0)
            return {"completed": True}
            
        worker_node.task_executor.register_task_function("long", long_task)
        
        task = TaskRequest("long_task", "long", {}, timeout_seconds=30)
        task_future = asyncio.create_task(worker_node.handle_task_assignment(task))
        
        # Initiate graceful shutdown
        shutdown_task = asyncio.create_task(worker_node.graceful_shutdown(timeout=2.0))
        
        # Wait for both to complete
        shutdown_result, task_result = await asyncio.gather(
            shutdown_task, task_future, return_exceptions=True
        )
        
        assert worker_node.is_running is False
        assert worker_node.status in [NodeStatus.DRAINING, NodeStatus.FAILED]
        
    async def test_error_recovery(self, worker_node, redis_mock):
        """Test error recovery mechanisms"""
        # Simulate Redis connection failure
        redis_mock.setex.side_effect = Exception("Redis connection failed")
        
        await worker_node.start()
        
        # Wait for error handling
        await asyncio.sleep(2.0)
        
        # Node should handle the error gracefully
        assert worker_node.is_running is True  # Should still be running
        
        # Reset Redis mock
        redis_mock.setex.side_effect = None
        redis_mock.setex.return_value = True
        
        # Wait for recovery
        await asyncio.sleep(1.5)
        
        # Should recover and continue sending heartbeats
        redis_mock.setex.assert_called()
        
        await worker_node.stop()
        
    async def test_load_balancing_metrics(self, worker_node):
        """Test load balancing metrics calculation"""
        # Simulate some task execution
        worker_node.task_executor.running_tasks = {
            "task1": AsyncMock(),
            "task2": AsyncMock()
        }
        
        metrics = worker_node.get_load_balancing_metrics()
        
        assert metrics["node_id"] == worker_node.config.node_id
        assert metrics["active_tasks"] == 2
        assert metrics["max_concurrent_tasks"] == worker_node.config.max_concurrent_tasks
        assert "utilization_percent" in metrics
        assert "available_capacity" in metrics
        
    @pytest.mark.parametrize("task_type,expected_capability", [
        ("fmri_analysis", True),
        ("preprocessing", True),
        ("statistical_analysis", True),
        ("unsupported_task", False)
    ])
    async def test_task_capability_checking(self, worker_node, task_type, expected_capability):
        """Test checking task capabilities"""
        # Register some task functions
        worker_node.task_executor.register_task_function("fmri_analysis", lambda **k: {})
        worker_node.task_executor.register_task_function("preprocessing", lambda **k: {})
        worker_node.task_executor.register_task_function("statistical_analysis", lambda **k: {})
        
        can_handle = worker_node.can_handle_task_type(task_type)
        assert can_handle == expected_capability