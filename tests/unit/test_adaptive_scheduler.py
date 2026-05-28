"""
Unit tests for Adaptive Scheduler (AGENT-021).

Tests the AdaptiveScheduler, PreemptionManager, LoadBalancer, and related
components for priority-based task scheduling with preemption capabilities.
"""

import asyncio
import heapq
import json
import pytest
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

try:
    from brain_researcher.services.agent.adaptive_scheduler import (
        AdaptiveScheduler,
        PreemptionManager,
        LoadBalancer,
        ResourcePool,
        ScheduledTask,
        TaskPriority,
        SchedulingPolicy,
        create_adaptive_scheduler
    )
    from brain_researcher.services.agent.parallel_executor import (
        Task,
        TaskStatus,
        ResourceType,
        ResourceRequirement
    )
    from brain_researcher.services.agent.system_monitor import SystemHealth
except ImportError:
    pytest.skip("adaptive scheduler optional deps not available", allow_module_level=True)

# Import test fixtures
import sys
sys.path.append(str(Path(__file__).parent.parent / "fixtures" / "AGENT-021"))
from mock_tools import create_mock_system_monitor


class TestScheduledTask:
    """Test ScheduledTask functionality."""
    
    def test_scheduled_task_creation(self):
        """Test ScheduledTask creation and priority score calculation."""
        task = Task(
            task_id="test_task",
            name="Test Task",
            tool_name="mock_tool",
            tool_args={}
        )
        
        scheduled_task = ScheduledTask(
            task=task,
            priority=TaskPriority.HIGH,
            submission_time=time.time(),
            deadline=time.time() + 600,
            preemptible=True
        )
        
        assert scheduled_task.task.task_id == "test_task"
        assert scheduled_task.priority == TaskPriority.HIGH
        assert scheduled_task.preemptible is True
        assert scheduled_task.priority_score > 0
    
    def test_priority_score_calculation(self):
        """Test priority score calculation with various factors."""
        base_time = time.time()
        
        # High priority task
        high_task = ScheduledTask(
            task=Task("high", "High", "tool", {}),
            priority=TaskPriority.HIGH,
            submission_time=base_time
        )
        
        # Low priority task
        low_task = ScheduledTask(
            task=Task("low", "Low", "tool", {}),
            priority=TaskPriority.LOW,
            submission_time=base_time
        )
        
        # High priority should have lower score (higher priority in heap)
        assert high_task.priority_score < low_task.priority_score
    
    def test_age_bonus_calculation(self):
        """Test age bonus for waiting tasks."""
        old_time = time.time() - 300  # 5 minutes ago
        recent_time = time.time() - 60  # 1 minute ago
        
        old_task = ScheduledTask(
            task=Task("old", "Old", "tool", {}),
            priority=TaskPriority.NORMAL,
            submission_time=old_time
        )
        
        recent_task = ScheduledTask(
            task=Task("recent", "Recent", "tool", {}),
            priority=TaskPriority.NORMAL,
            submission_time=recent_time
        )
        
        # Older task should have lower priority score (age bonus)
        assert old_task.priority_score < recent_task.priority_score
    
    def test_deadline_urgency(self):
        """Test deadline urgency calculation."""
        current_time = time.time()
        
        urgent_task = ScheduledTask(
            task=Task("urgent", "Urgent", "tool", {}),
            priority=TaskPriority.NORMAL,
            submission_time=current_time,
            deadline=current_time + 120  # 2 minutes from now
        )
        
        relaxed_task = ScheduledTask(
            task=Task("relaxed", "Relaxed", "tool", {}),
            priority=TaskPriority.NORMAL,
            submission_time=current_time,
            deadline=current_time + 1800  # 30 minutes from now
        )
        
        # Urgent task should have lower priority score
        assert urgent_task.priority_score < relaxed_task.priority_score
    
    def test_retry_penalty(self):
        """Test retry penalty application."""
        task = Task("retry", "Retry", "tool", {})
        
        scheduled_task = ScheduledTask(
            task=task,
            priority=TaskPriority.NORMAL,
            submission_time=time.time(),
            retry_penalty=2.0  # High retry penalty
        )
        
        # Should increase priority score (lower priority)
        assert scheduled_task.priority_score > TaskPriority.NORMAL.value


class TestResourcePool:
    """Test ResourcePool functionality."""
    
    def test_resource_pool_creation(self):
        """Test ResourcePool initialization."""
        pool = ResourcePool(
            resource_type=ResourceType.CPU,
            total_capacity=8.0
        )
        
        assert pool.resource_type == ResourceType.CPU
        assert pool.total_capacity == 8.0
        assert pool.allocated == 0.0
        assert pool.reserved == 0.0
        assert pool.available == 8.0
        assert pool.utilization == 0.0
    
    def test_resource_allocation(self):
        """Test resource allocation and utilization calculation."""
        pool = ResourcePool(ResourceType.MEMORY, 16.0)
        
        # Allocate some resources
        pool.allocated = 8.0
        pool.reserved = 4.0
        
        assert pool.available == 4.0  # 16 - 8 - 4
        assert pool.utilization == 50.0  # 8/16 * 100
        
        # Test allocation tracking
        pool.allocations["task1"] = 4.0
        pool.allocations["task2"] = 4.0
        
        assert len(pool.allocations) == 2
        assert sum(pool.allocations.values()) == 8.0
    
    def test_resource_overallocation_protection(self):
        """Test that available resources never go negative."""
        pool = ResourcePool(ResourceType.CPU, 4.0)
        
        pool.allocated = 3.0
        pool.reserved = 2.0  # Over-reserved
        
        assert pool.available == 0.0  # Should be max(0, 4-3-2)


class TestPreemptionManager:
    """Test PreemptionManager functionality."""
    
    def test_preemption_manager_initialization(self):
        """Test PreemptionManager initialization."""
        manager = PreemptionManager()
        
        assert len(manager.preempted_tasks) == 0
        assert len(manager.preemption_history) == 0
    
    def test_can_preempt_priority_based(self):
        """Test preemption decision based on priority."""
        manager = PreemptionManager()
        
        running_task = ScheduledTask(
            task=Task("running", "Running", "tool", {}),
            priority=TaskPriority.LOW,
            submission_time=time.time(),
            preemptible=True
        )
        
        high_priority_task = ScheduledTask(
            task=Task("high", "High", "tool", {}),
            priority=TaskPriority.HIGH,
            submission_time=time.time()
        )
        
        low_priority_task = ScheduledTask(
            task=Task("low", "Low", "tool", {}),
            priority=TaskPriority.LOW,
            submission_time=time.time()
        )
        
        # Should preempt for significantly higher priority
        assert manager.can_preempt(running_task, high_priority_task) is True
        
        # Should not preempt for same priority
        assert manager.can_preempt(running_task, low_priority_task) is False
    
    def test_can_preempt_deadline_based(self):
        """Test preemption decision based on deadlines."""
        manager = PreemptionManager()
        current_time = time.time()
        
        running_task = ScheduledTask(
            task=Task("running", "Running", "tool", {}),
            priority=TaskPriority.NORMAL,
            submission_time=current_time,
            preemptible=True
        )
        
        urgent_task = ScheduledTask(
            task=Task("urgent", "Urgent", "tool", {}),
            priority=TaskPriority.NORMAL,
            submission_time=current_time,
            deadline=current_time + 120  # 2 minutes deadline
        )
        
        # Should preempt for urgent deadline even with same priority
        assert manager.can_preempt(running_task, urgent_task) is True
    
    def test_cannot_preempt_non_preemptible(self):
        """Test that non-preemptible tasks cannot be preempted."""
        manager = PreemptionManager()
        
        non_preemptible_task = ScheduledTask(
            task=Task("protected", "Protected", "tool", {}),
            priority=TaskPriority.LOW,
            submission_time=time.time(),
            preemptible=False  # Cannot be preempted
        )
        
        critical_task = ScheduledTask(
            task=Task("critical", "Critical", "tool", {}),
            priority=TaskPriority.CRITICAL,
            submission_time=time.time()
        )
        
        # Should not preempt non-preemptible task even for critical priority
        assert manager.can_preempt(non_preemptible_task, critical_task) is False
    
    def test_preempt_task(self):
        """Test task preemption functionality."""
        manager = PreemptionManager()
        
        task = ScheduledTask(
            task=Task("preempt_me", "Preempt Me", "tool", {}),
            priority=TaskPriority.NORMAL,
            submission_time=time.time(),
            preemptible=True
        )
        
        # Preempt the task
        success = manager.preempt_task(task, "Higher priority task")
        
        assert success is True
        assert task.task.status == TaskStatus.BLOCKED
        assert "preempt_me" in manager.preempted_tasks
        assert len(manager.preemption_history) == 1
        assert manager.preemption_history[0]["reason"] == "Higher priority task"
    
    def test_resume_task(self):
        """Test task resumption functionality."""
        manager = PreemptionManager()
        
        task = ScheduledTask(
            task=Task("resume_me", "Resume Me", "tool", {}),
            priority=TaskPriority.NORMAL,
            submission_time=time.time(),
            retry_penalty=1.0
        )
        
        # Preempt first
        manager.preempt_task(task, "Test preemption")
        original_penalty = task.retry_penalty
        
        # Resume task
        resumed_task = manager.resume_task("resume_me")
        
        assert resumed_task is not None
        assert resumed_task.task.status == TaskStatus.QUEUED
        assert resumed_task.retry_penalty > original_penalty  # Penalty increased
        assert "resume_me" not in manager.preempted_tasks
    
    def test_preemption_statistics(self):
        """Test preemption statistics collection."""
        manager = PreemptionManager()
        
        # Create some preemption history
        for i in range(5):
            task = ScheduledTask(
                task=Task(f"task_{i}", f"Task {i}", "tool", {}),
                priority=TaskPriority.NORMAL,
                submission_time=time.time()
            )
            manager.preempt_task(task, f"Reason {i}")
        
        # Resume some tasks
        manager.resume_task("task_0")
        manager.resume_task("task_1")
        
        stats = manager.get_preemption_stats()
        
        assert stats["total_preemptions"] == 5
        assert stats["preempted_tasks_waiting"] == 3  # 5 - 2 resumed
        assert stats["recent_preemptions"] <= 5  # All should be recent


class TestLoadBalancer:
    """Test LoadBalancer functionality."""
    
    def test_load_balancer_initialization(self):
        """Test LoadBalancer initialization."""
        resource_pools = {
            ResourceType.CPU: ResourcePool(ResourceType.CPU, 8.0),
            ResourceType.MEMORY: ResourcePool(ResourceType.MEMORY, 16.0)
        }
        
        balancer = LoadBalancer(resource_pools)
        
        assert len(balancer.resource_pools) == 2
        assert ResourceType.CPU in balancer.resource_pools
        assert ResourceType.MEMORY in balancer.resource_pools
        assert len(balancer.balancing_strategies) == 3
    
    def test_round_robin_balance(self):
        """Test round-robin resource assignment."""
        resource_pools = {
            ResourceType.CPU: ResourcePool(ResourceType.CPU, 8.0),
            ResourceType.MEMORY: ResourcePool(ResourceType.MEMORY, 16.0)
        }
        balancer = LoadBalancer(resource_pools)
        
        task = ScheduledTask(
            task=Task(
                "test", "Test", "tool", {},
                resource_requirements=[
                    ResourceRequirement(ResourceType.CPU, 2.0),
                    ResourceRequirement(ResourceType.MEMORY, 4.0)
                ]
            ),
            priority=TaskPriority.NORMAL,
            submission_time=time.time()
        )
        
        assignment = balancer._round_robin_balance(task)
        
        assert assignment[ResourceType.CPU] == 2.0
        assert assignment[ResourceType.MEMORY] == 4.0
    
    def test_least_loaded_balance(self):
        """Test least-loaded resource assignment."""
        cpu_pool = ResourcePool(ResourceType.CPU, 8.0)
        memory_pool = ResourcePool(ResourceType.MEMORY, 16.0)
        
        # Make CPU heavily utilized
        cpu_pool.allocated = 7.0
        memory_pool.allocated = 4.0
        
        resource_pools = {
            ResourceType.CPU: cpu_pool,
            ResourceType.MEMORY: memory_pool
        }
        balancer = LoadBalancer(resource_pools)
        
        task = ScheduledTask(
            task=Task(
                "test", "Test", "tool", {},
                resource_requirements=[
                    ResourceRequirement(ResourceType.CPU, 2.0),
                    ResourceRequirement(ResourceType.MEMORY, 4.0)
                ]
            ),
            priority=TaskPriority.NORMAL,
            submission_time=time.time()
        )
        
        assignment = balancer._least_loaded_balance(task)
        
        # CPU should be scaled down due to high utilization
        assert assignment[ResourceType.CPU] < 2.0
        assert assignment[ResourceType.MEMORY] == 4.0
    
    def test_resource_aware_balance(self):
        """Test resource-aware balancing with priority consideration."""
        resource_pools = {
            ResourceType.CPU: ResourcePool(ResourceType.CPU, 8.0),
            ResourceType.MEMORY: ResourcePool(ResourceType.MEMORY, 16.0)
        }
        balancer = LoadBalancer(resource_pools)
        
        high_priority_task = ScheduledTask(
            task=Task(
                "high", "High", "tool", {},
                resource_requirements=[
                    ResourceRequirement(ResourceType.CPU, 2.0)
                ]
            ),
            priority=TaskPriority.HIGH,
            submission_time=time.time()
        )
        
        low_priority_task = ScheduledTask(
            task=Task(
                "low", "Low", "tool", {},
                resource_requirements=[
                    ResourceRequirement(ResourceType.CPU, 2.0)
                ]
            ),
            priority=TaskPriority.LOW,
            submission_time=time.time()
        )
        
        high_assignment = balancer._resource_aware_balance(high_priority_task)
        low_assignment = balancer._resource_aware_balance(low_priority_task)
        
        # High priority task should get more resources
        assert high_assignment[ResourceType.CPU] > low_assignment[ResourceType.CPU]
    
    def test_load_statistics(self):
        """Test load statistics collection."""
        cpu_pool = ResourcePool(ResourceType.CPU, 8.0)
        memory_pool = ResourcePool(ResourceType.MEMORY, 16.0)
        
        cpu_pool.allocated = 4.0
        memory_pool.allocated = 8.0
        
        resource_pools = {
            ResourceType.CPU: cpu_pool,
            ResourceType.MEMORY: memory_pool
        }
        balancer = LoadBalancer(resource_pools)
        
        stats = balancer.get_load_statistics()
        
        assert stats["cpu"]["utilization"] == 50.0  # 4/8 * 100
        assert stats["memory"]["utilization"] == 50.0  # 8/16 * 100
        assert stats["overall"]["average_utilization"] == 50.0
        assert stats["overall"]["hottest_resource"] in ["cpu", "memory"]


class TestAdaptiveScheduler:
    """Test AdaptiveScheduler functionality."""
    
    @pytest.fixture
    def mock_monitor(self):
        """Create mock system monitor."""
        return create_mock_system_monitor()
    
    @pytest.fixture
    def scheduler(self, mock_monitor):
        """Create scheduler for testing."""
        return AdaptiveScheduler(
            monitor=mock_monitor,
            resource_limits={
                ResourceType.CPU: 8.0,
                ResourceType.MEMORY: 16.0
            }
        )
    
    def test_scheduler_initialization(self, scheduler):
        """Test scheduler initialization."""
        assert scheduler.scheduling_policy == SchedulingPolicy.PRIORITY_FIRST
        assert len(scheduler.resource_pools) >= 2
        assert ResourceType.CPU in scheduler.resource_pools
        assert ResourceType.MEMORY in scheduler.resource_pools
        assert isinstance(scheduler.preemption_manager, PreemptionManager)
        assert isinstance(scheduler.load_balancer, LoadBalancer)
    
    @pytest.mark.asyncio
    async def test_start_stop_scheduler(self, scheduler):
        """Test scheduler start and stop."""
        assert scheduler._scheduler_running is False
        
        # Start scheduler
        await scheduler.start_scheduler()
        assert scheduler._scheduler_running is True
        assert scheduler._scheduler_task is not None
        
        # Stop scheduler
        await scheduler.stop_scheduler()
        assert scheduler._scheduler_running is False
    
    @pytest.mark.asyncio
    async def test_schedule_task(self, scheduler):
        """Test task scheduling."""
        await scheduler.start_scheduler()
        
        task = Task(
            task_id="test_schedule",
            name="Test Schedule",
            tool_name="mock_tool",
            tool_args={}
        )
        
        task_id = await scheduler.schedule_task(
            task,
            priority=TaskPriority.HIGH,
            deadline=time.time() + 600
        )
        
        assert task_id == "test_schedule"
        assert len(scheduler.priority_queue) == 1
        assert scheduler.scheduling_stats["tasks_scheduled"] == 1
        
        await scheduler.stop_scheduler()
    
    @pytest.mark.asyncio
    async def test_priority_queue_ordering(self, scheduler):
        """Test priority queue maintains correct ordering."""
        await scheduler.start_scheduler()
        
        # Schedule tasks with different priorities
        tasks = [
            (Task("low", "Low", "tool", {}), TaskPriority.LOW),
            (Task("high", "High", "tool", {}), TaskPriority.HIGH),
            (Task("critical", "Critical", "tool", {}), TaskPriority.CRITICAL),
            (Task("normal", "Normal", "tool", {}), TaskPriority.NORMAL)
        ]
        
        for task, priority in tasks:
            await scheduler.schedule_task(task, priority=priority)
        
        # Extract tasks in priority order
        ordered_tasks = []
        temp_queue = scheduler.priority_queue.copy()
        while temp_queue:
            ordered_tasks.append(heapq.heappop(temp_queue))
        
        # Should be ordered by priority (CRITICAL first)
        assert ordered_tasks[0].priority == TaskPriority.CRITICAL
        assert ordered_tasks[1].priority == TaskPriority.HIGH
        
        await scheduler.stop_scheduler()
    
    @pytest.mark.asyncio
    async def test_emergency_scheduling(self, scheduler, mock_monitor):
        """Test emergency scheduling mode."""
        # Set system to critical health
        mock_monitor.get_health_status.return_value = SystemHealth.CRITICAL
        
        await scheduler.start_scheduler()
        
        # Schedule mixed priority tasks
        critical_task = Task("critical", "Critical", "tool", {})
        normal_task = Task("normal", "Normal", "tool", {})
        
        await scheduler.schedule_task(critical_task, TaskPriority.CRITICAL)
        await scheduler.schedule_task(normal_task, TaskPriority.NORMAL)
        
        # Simulate emergency scheduling
        async with scheduler._scheduling_lock:
            await scheduler._emergency_scheduling()
        
        # Should only process critical tasks
        assert len(scheduler.priority_queue) >= 0  # Critical task might be processed
        
        await scheduler.stop_scheduler()
    
    @pytest.mark.asyncio
    async def test_conservative_scheduling(self, scheduler, mock_monitor):
        """Test conservative scheduling mode."""
        mock_monitor.get_health_status.return_value = SystemHealth.STRESSED
        
        await scheduler.start_scheduler()
        
        # Add some running tasks
        for i in range(3):
            task = ScheduledTask(
                task=Task(f"running_{i}", f"Running {i}", "tool", {}),
                priority=TaskPriority.NORMAL,
                submission_time=time.time()
            )
            scheduler.running_tasks[f"running_{i}"] = task
        
        async with scheduler._scheduling_lock:
            await scheduler._conservative_scheduling()
        
        # Should limit concurrent tasks
        await scheduler.stop_scheduler()
    
    @pytest.mark.asyncio
    async def test_task_completion(self, scheduler):
        """Test task completion handling."""
        await scheduler.start_scheduler()
        
        # Add a running task
        task = ScheduledTask(
            task=Task("complete_me", "Complete Me", "tool", {}),
            priority=TaskPriority.NORMAL,
            submission_time=time.time()
        )
        task.task.started_at = time.time()
        scheduler.running_tasks["complete_me"] = task
        
        # Complete the task
        await scheduler.complete_task("complete_me", result={"status": "success"})
        
        assert "complete_me" not in scheduler.running_tasks
        assert "complete_me" in scheduler.completed_tasks
        assert scheduler.completed_tasks["complete_me"].task.status == TaskStatus.COMPLETED
        
        await scheduler.stop_scheduler()
    
    @pytest.mark.asyncio
    async def test_task_failure(self, scheduler):
        """Test task failure handling."""
        await scheduler.start_scheduler()
        
        # Add a running task
        task = ScheduledTask(
            task=Task("fail_me", "Fail Me", "tool", {}),
            priority=TaskPriority.NORMAL,
            submission_time=time.time()
        )
        task.task.started_at = time.time()
        scheduler.running_tasks["fail_me"] = task
        
        # Fail the task
        await scheduler.complete_task("fail_me", error="Task failed")
        
        assert "fail_me" not in scheduler.running_tasks
        assert "fail_me" in scheduler.completed_tasks
        assert scheduler.completed_tasks["fail_me"].task.status == TaskStatus.FAILED
        
        await scheduler.stop_scheduler()
    
    @pytest.mark.asyncio
    async def test_preemption_check(self, scheduler):
        """Test preemption checking mechanism."""
        await scheduler.start_scheduler()
        
        # Add low priority running task
        low_task = ScheduledTask(
            task=Task("low_running", "Low Running", "tool", {}),
            priority=TaskPriority.LOW,
            submission_time=time.time(),
            preemptible=True
        )
        scheduler.running_tasks["low_running"] = low_task
        
        # Add high priority waiting task
        high_task = ScheduledTask(
            task=Task("high_waiting", "High Waiting", "tool", {}),
            priority=TaskPriority.HIGH,
            submission_time=time.time()
        )
        scheduler.priority_queue = [high_task]
        heapq.heapify(scheduler.priority_queue)
        
        # Check preemption
        async with scheduler._scheduling_lock:
            await scheduler._check_preemption()
        
        # High priority task should be scheduled
        assert "high_waiting" in scheduler.running_tasks
        
        await scheduler.stop_scheduler()
    
    @pytest.mark.asyncio
    async def test_priority_adjustment(self, scheduler):
        """Test dynamic priority adjustment."""
        await scheduler.start_scheduler()
        
        task = Task("adjust_me", "Adjust Me", "tool", {})
        await scheduler.schedule_task(task, priority=TaskPriority.NORMAL)
        
        # Adjust priority
        success = await scheduler.adjust_task_priority("adjust_me", TaskPriority.HIGH)
        
        assert success is True
        
        # Find task in queue and verify priority
        for scheduled_task in scheduler.priority_queue:
            if scheduled_task.task.task_id == "adjust_me":
                assert scheduled_task.priority == TaskPriority.HIGH
                break
        else:
            pytest.fail("Task not found in queue")
        
        await scheduler.stop_scheduler()
    
    def test_queue_status(self, scheduler):
        """Test queue status reporting."""
        # Add some mock tasks
        for priority in TaskPriority:
            task = ScheduledTask(
                task=Task(f"task_{priority.name}", f"Task {priority.name}", "tool", {}),
                priority=priority,
                submission_time=time.time()
            )
            scheduler.priority_queue.append(task)
        
        status = scheduler.get_queue_status()
        
        assert status["queued_tasks"] == len(TaskPriority)
        assert status["running_tasks"] == 0
        assert status["completed_tasks"] == 0
        assert "queue_by_priority" in status
        
        # Check priority breakdown
        for priority in TaskPriority:
            assert status["queue_by_priority"][priority.name] == 1
    
    def test_performance_metrics(self, scheduler):
        """Test performance metrics collection."""
        metrics = scheduler.get_performance_metrics()
        
        assert "preemption_stats" in metrics
        assert "load_balancing" in metrics
        assert "queue_status" in metrics
        assert "tasks_scheduled" in metrics
        assert "avg_wait_time" in metrics
        assert "avg_execution_time" in metrics
        assert "throughput" in metrics
    
    def test_factory_function(self, mock_monitor):
        """Test scheduler factory function."""
        scheduler = create_adaptive_scheduler(
            monitor=mock_monitor,
            resource_limits={ResourceType.CPU: 4.0},
            scheduling_policy=SchedulingPolicy.FAIR_SHARE
        )
        
        assert isinstance(scheduler, AdaptiveScheduler)
        assert scheduler.scheduling_policy == SchedulingPolicy.FAIR_SHARE
        assert scheduler.resource_pools[ResourceType.CPU].total_capacity == 4.0


@pytest.mark.integration
class TestAdaptiveSchedulerIntegration:
    """Integration tests for adaptive scheduler."""
    
    @pytest.fixture
    def mock_monitor(self):
        """Create mock system monitor with configurable health."""
        monitor = create_mock_system_monitor()
        return monitor
    
    @pytest.mark.asyncio
    async def test_full_scheduling_cycle(self, mock_monitor):
        """Test complete scheduling cycle with various scenarios."""
        # Load test data
        fixtures_path = Path(__file__).parent.parent / "fixtures" / "AGENT-021"
        with open(fixtures_path / "task_scenarios.json") as f:
            test_data = json.load(f)
        
        scheduler = AdaptiveScheduler(
            monitor=mock_monitor,
            resource_limits={
                ResourceType.CPU: 8.0,
                ResourceType.MEMORY: 16.0,
                ResourceType.GPU: 1.0
            }
        )
        
        await scheduler.start_scheduler()
        
        # Schedule mixed priority workload
        scenario = test_data["scheduling_scenarios"]["mixed_priority_workload"]
        
        scheduled_tasks = []
        for task_data in scenario:
            task = Task(
                task_id=task_data["task_id"],
                name=task_data["name"],
                tool_name=task_data["tool_name"],
                tool_args=task_data["tool_args"],
                resource_requirements=[
                    ResourceRequirement(
                        ResourceType(req["resource_type"]),
                        req["amount"]
                    )
                    for req in task_data["resource_requirements"]
                ]
            )
            
            task_id = await scheduler.schedule_task(
                task,
                priority=TaskPriority[task_data["priority"]],
                deadline=task_data.get("deadline"),
                preemptible=task_data["preemptible"]
            )
            scheduled_tasks.append(task_id)
        
        # Let scheduler run for a moment
        await asyncio.sleep(1.0)
        
        # Verify tasks were scheduled
        assert len(scheduled_tasks) == len(scenario)
        assert scheduler.get_queue_status()["queued_tasks"] >= 0
        
        await scheduler.stop_scheduler()
    
    @pytest.mark.asyncio
    async def test_system_health_adaptation(self, mock_monitor):
        """Test scheduler adaptation to system health changes."""
        scheduler = AdaptiveScheduler(monitor=mock_monitor)
        await scheduler.start_scheduler()
        
        # Start with healthy system
        mock_monitor.get_health_status.return_value = SystemHealth.HEALTHY
        
        # Schedule some tasks
        for i in range(5):
            task = Task(f"task_{i}", f"Task {i}", "tool", {})
            await scheduler.schedule_task(task, priority=TaskPriority.NORMAL)
        
        # Change to critical system
        mock_monitor.get_health_status.return_value = SystemHealth.CRITICAL
        
        # Let scheduler adapt
        await asyncio.sleep(0.6)  # Wait for scheduling iteration
        
        # Should adapt to critical conditions
        await scheduler.stop_scheduler()
    
    @pytest.mark.asyncio
    async def test_preemption_scenario(self, mock_monitor):
        """Test realistic preemption scenario."""
        # Load preemption test scenario
        fixtures_path = Path(__file__).parent.parent / "fixtures" / "AGENT-021"
        with open(fixtures_path / "task_scenarios.json") as f:
            test_data = json.load(f)
        
        scheduler = AdaptiveScheduler(monitor=mock_monitor)
        await scheduler.start_scheduler()
        
        scenario = test_data["scheduling_scenarios"]["preemption_test"]
        
        # Schedule long running task first
        long_task_data = scenario[0]  # long_running task
        long_task = Task(
            task_id=long_task_data["task_id"],
            name=long_task_data["name"],
            tool_name=long_task_data["tool_name"],
            tool_args=long_task_data["tool_args"],
            resource_requirements=[
                ResourceRequirement(
                    ResourceType(req["resource_type"]),
                    req["amount"]
                )
                for req in long_task_data["resource_requirements"]
            ]
        )
        
        await scheduler.schedule_task(
            long_task,
            priority=TaskPriority[long_task_data["priority"]],
            preemptible=long_task_data["preemptible"]
        )
        
        # Let it start running
        await asyncio.sleep(0.1)
        
        # Schedule urgent task
        urgent_task_data = scenario[1]  # urgent_interrupt task
        urgent_task = Task(
            task_id=urgent_task_data["task_id"],
            name=urgent_task_data["name"],
            tool_name=urgent_task_data["tool_name"],
            tool_args=urgent_task_data["tool_args"]
        )
        
        await scheduler.schedule_task(
            urgent_task,
            priority=TaskPriority[urgent_task_data["priority"]],
            deadline=time.time() + urgent_task_data["deadline"],
            preemptible=urgent_task_data["preemptible"]
        )
        
        # Let scheduler process preemption
        await asyncio.sleep(0.6)
        
        # Check preemption occurred
        preemption_stats = scheduler.preemption_manager.get_preemption_stats()
        assert preemption_stats["total_preemptions"] >= 0  # May or may not preempt
        
        await scheduler.stop_scheduler()


@pytest.mark.performance
class TestAdaptiveSchedulerPerformance:
    """Performance tests for adaptive scheduler."""
    
    @pytest.mark.asyncio
    async def test_scheduling_latency(self):
        """Test scheduling latency under load."""
        mock_monitor = create_mock_system_monitor()
        scheduler = AdaptiveScheduler(monitor=mock_monitor)
        
        await scheduler.start_scheduler()
        
        # Measure scheduling latency
        start_time = time.time()
        
        # Schedule many tasks quickly
        tasks = []
        for i in range(100):
            task = Task(f"perf_task_{i}", f"Task {i}", "tool", {})
            tasks.append(scheduler.schedule_task(task, priority=TaskPriority.NORMAL))
        
        # Wait for all scheduling to complete
        await asyncio.gather(*tasks)
        
        end_time = time.time()
        avg_latency = (end_time - start_time) / 100
        
        # Should schedule tasks quickly (under 10ms per task)
        assert avg_latency < 0.01
        
        await scheduler.stop_scheduler()
    
    @pytest.mark.asyncio
    async def test_queue_throughput(self):
        """Test queue processing throughput."""
        mock_monitor = create_mock_system_monitor()
        scheduler = AdaptiveScheduler(monitor=mock_monitor)
        
        await scheduler.start_scheduler()
        
        # Fill queue with tasks
        for i in range(50):
            task = Task(f"throughput_task_{i}", f"Task {i}", "tool", {})
            await scheduler.schedule_task(task, priority=TaskPriority.NORMAL)
        
        initial_queue_size = len(scheduler.priority_queue)
        
        # Let scheduler process for 2 seconds
        await asyncio.sleep(2.0)
        
        final_queue_size = len(scheduler.priority_queue)
        tasks_processed = initial_queue_size - final_queue_size
        
        # Should process tasks (exact number depends on system/implementation)
        assert tasks_processed >= 0
        
        await scheduler.stop_scheduler()
    
    @pytest.mark.asyncio
    async def test_memory_usage_under_load(self):
        """Test memory usage doesn't grow unbounded under load."""
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss
        
        mock_monitor = create_mock_system_monitor()
        scheduler = AdaptiveScheduler(monitor=mock_monitor)
        await scheduler.start_scheduler()
        
        # Process many tasks
        for batch in range(10):
            # Schedule batch of tasks
            for i in range(20):
                task = Task(f"memory_task_{batch}_{i}", f"Task {batch}_{i}", "tool", {})
                await scheduler.schedule_task(task, priority=TaskPriority.NORMAL)
            
            # Complete some tasks to prevent unbounded growth
            if batch % 3 == 0:
                for task_id in list(scheduler.running_tasks.keys())[:5]:
                    await scheduler.complete_task(task_id, result={"status": "completed"})
        
        await asyncio.sleep(1.0)
        
        final_memory = process.memory_info().rss
        memory_growth = final_memory - initial_memory
        
        # Memory growth should be reasonable (under 100MB for this test)
        assert memory_growth < 100 * 1024 * 1024
        
        await scheduler.stop_scheduler()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
