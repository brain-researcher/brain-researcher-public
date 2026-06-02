"""Distributed Worker Node

Manages task processing, work stealing, and parallel execution
for distributed brain researcher agent nodes.
"""

import asyncio
import json
import logging
import queue
import threading
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

import psutil
import redis.asyncio as redis
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Task:
    """Represents a task to be executed"""

    task_id: str
    task_type: str
    payload: Dict[str, Any]
    priority: TaskPriority = TaskPriority.MEDIUM
    created_at: Optional[datetime] = None
    assigned_node: Optional[str] = None
    timeout_seconds: int = 300
    retry_count: int = 0
    max_retries: int = 3
    dependencies: List[str] = None
    estimated_duration: Optional[float] = None
    resource_requirements: Optional[Dict] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()
        if self.dependencies is None:
            self.dependencies = []

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization"""
        data = asdict(self)
        if self.created_at:
            data["created_at"] = self.created_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict) -> "Task":
        """Create from dictionary"""
        if "created_at" in data and data["created_at"]:
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        return cls(**data)


@dataclass
class TaskResult:
    """Result of task execution"""

    task_id: str
    status: TaskStatus
    result: Optional[Any] = None
    error: Optional[str] = None
    execution_time: Optional[float] = None
    memory_used: Optional[float] = None
    node_id: Optional[str] = None
    completed_at: Optional[datetime] = None
    result_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    error_traceback: Optional[str] = None
    resource_usage: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.completed_at is None and self.status in [
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
        ]:
            self.completed_at = datetime.utcnow()
        # Keep aliases in sync for tests
        if self.result_data is None and self.result is not None:
            self.result_data = (
                self.result
                if isinstance(self.result, dict)
                else {"result": self.result}
            )
        if self.error_message is None and self.error is not None:
            self.error_message = self.error

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization"""
        data = asdict(self)
        if self.completed_at:
            data["completed_at"] = self.completed_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskResult":
        completed_at = data.get("completed_at")
        if completed_at:
            data["completed_at"] = datetime.fromisoformat(completed_at)
        return cls(**data)


# Lightweight task request/execution helpers used by unit tests
@dataclass
class TaskRequest:
    task_id: str
    task_type: str
    payload: Dict[str, Any]
    priority: TaskPriority = TaskPriority.MEDIUM
    timeout_seconds: int = 300
    resource_requirements: Dict[str, Any] = None

    def __post_init__(self):
        if self.resource_requirements is None:
            self.resource_requirements = {}

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["priority"] = (
            int(self.priority)
            if isinstance(self.priority, TaskPriority)
            else self.priority
        )
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskRequest":
        return cls(
            task_id=data["task_id"],
            task_type=data["task_type"],
            payload=data.get("payload", {}),
            priority=data.get("priority", TaskPriority.MEDIUM),
            timeout_seconds=data.get("timeout_seconds", 300),
            resource_requirements=data.get("resource_requirements", {}),
        )


@dataclass
class TaskExecutionResult:
    task_id: str
    status: TaskStatus
    result_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    error_traceback: Optional[str] = None
    execution_time: float = 0.0


class TaskExecutor:
    """Simplified async task executor (test-oriented)."""

    def __init__(self, max_concurrent_tasks: int = 4):
        self.max_concurrent_tasks = max_concurrent_tasks
        self.running_tasks: Set[str] = set()
        self.task_results: Dict[str, TaskExecutionResult] = {}
        self.task_functions: Dict[str, Callable[..., Any]] = {}

    def register_task_function(self, task_type: str, fn: Callable[..., Any]):
        self.task_functions[task_type] = fn

    async def execute_task(self, task_request: TaskRequest) -> TaskExecutionResult:
        start = time.time()
        try:
            fn = self.task_functions[task_request.task_type]
        except KeyError:
            return TaskExecutionResult(
                task_id=task_request.task_id,
                status=TaskStatus.FAILED,
                error_message="Unknown task type",
                execution_time=0.0,
            )

        try:
            self.running_tasks.add(task_request.task_id)
            result = await fn(**task_request.payload)
            exec_time = time.time() - start
            res = TaskExecutionResult(
                task_id=task_request.task_id,
                status=TaskStatus.COMPLETED,
                result_data=result if isinstance(result, dict) else {"result": result},
                execution_time=exec_time,
            )
        except Exception as e:
            exec_time = time.time() - start
            res = TaskExecutionResult(
                task_id=task_request.task_id,
                status=TaskStatus.FAILED,
                error_message=str(e),
                error_traceback=traceback.format_exc(),
                execution_time=exec_time,
            )
        finally:
            self.running_tasks.discard(task_request.task_id)
            self.task_results[task_request.task_id] = res
        return res


@dataclass
class WorkerNodeConfig:
    node_id: str
    coordinator_url: str
    max_concurrent_tasks: int = 4
    heartbeat_interval: float = 5.0
    resource_monitoring_interval: float = 5.0


class ResourceMonitor:
    """Minimal resource monitor providing alert thresholds."""

    def __init__(self, monitoring_interval: float = 1.0):
        self.monitoring_interval = monitoring_interval
        self.cpu_threshold = 90.0
        self.memory_threshold = 90.0
        self.disk_threshold = 95.0
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
        self.usage_history: List[Dict[str, float]] = []

    async def start(self):
        self._running = True
        self._monitor_task = asyncio.create_task(self._loop())

    async def stop(self):
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

    async def _loop(self):
        while self._running:
            usage = self.get_resource_usage()
            self.usage_history.append(usage)
            await asyncio.sleep(self.monitoring_interval)

    def set_alert_thresholds(
        self, cpu_threshold: float, memory_threshold: float, disk_threshold: float
    ):
        self.cpu_threshold = cpu_threshold
        self.memory_threshold = memory_threshold
        self.disk_threshold = disk_threshold

    def get_resource_usage(self) -> Dict[str, float]:
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return {
            "cpu_percent": psutil.cpu_percent(),
            "memory_percent": memory.percent,
            "disk_usage_percent": disk.percent,
        }

    def check_alerts(self, usage: Dict[str, float]) -> List[str]:
        alerts = []
        if usage.get("cpu_percent", 0) > self.cpu_threshold:
            alerts.append(f"CPU usage high: {usage['cpu_percent']:.1f}%")
        if usage.get("memory_percent", 0) > self.memory_threshold:
            alerts.append(f"Memory usage high: {usage['memory_percent']:.1f}%")
        if usage.get("disk_usage_percent", 0) > self.disk_threshold:
            alerts.append(f"Disk usage high: {usage['disk_usage_percent']:.1f}%")
        return alerts


class WorkQueue:
    """Thread-safe work queue for task management"""

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self._high_priority = queue.PriorityQueue()
        self._medium_priority = queue.Queue()
        self._low_priority = queue.Queue()
        self._lock = threading.Lock()
        self._current_size = 0

    def put(self, task: Task) -> bool:
        """Add task to queue based on priority"""
        with self._lock:
            if self._current_size >= self.max_size:
                return False

            priority_value = self._get_priority_value(task.priority)

            try:
                if task.priority == TaskPriority.CRITICAL:
                    self._high_priority.put((0, task), timeout=1)
                elif task.priority == TaskPriority.HIGH:
                    self._high_priority.put((1, task), timeout=1)
                elif task.priority == TaskPriority.MEDIUM:
                    self._medium_priority.put(task, timeout=1)
                else:  # LOW
                    self._low_priority.put(task, timeout=1)

                self._current_size += 1
                return True

            except queue.Full:
                return False

    def get(self, timeout: Optional[float] = None) -> Optional[Task]:
        """Get next task from queue (priority order)"""
        with self._lock:
            # Try high priority first
            try:
                _, task = self._high_priority.get_nowait()
                self._current_size -= 1
                return task
            except queue.Empty:
                pass

            # Try medium priority
            try:
                task = self._medium_priority.get_nowait()
                self._current_size -= 1
                return task
            except queue.Empty:
                pass

            # Try low priority
            try:
                task = self._low_priority.get_nowait()
                self._current_size -= 1
                return task
            except queue.Empty:
                pass

            return None

    def size(self) -> int:
        """Get current queue size"""
        return self._current_size

    def is_full(self) -> bool:
        """Check if queue is full"""
        return self._current_size >= self.max_size

    def _get_priority_value(self, priority: TaskPriority) -> int:
        """Convert priority to numeric value"""
        priority_map = {
            TaskPriority.CRITICAL: 0,
            TaskPriority.HIGH: 1,
            TaskPriority.MEDIUM: 2,
            TaskPriority.LOW: 3,
        }
        return priority_map.get(priority, 2)


class ParallelExecutor:
    """Manages parallel task execution with resource limits"""

    def __init__(
        self, max_threads: int = 4, max_processes: int = 2, memory_limit_gb: float = 4.0
    ):
        self.max_threads = max_threads
        self.max_processes = max_processes
        self.memory_limit_gb = memory_limit_gb

        self.thread_pool = ThreadPoolExecutor(max_workers=max_threads)
        self.process_pool = ProcessPoolExecutor(max_workers=max_processes)

        self.running_tasks: Set[str] = set()
        self.task_futures: Dict[str, asyncio.Future] = {}

        # Resource monitoring
        self.current_memory_usage = 0.0
        self.current_cpu_usage = 0.0

    async def execute_task(self, task: Task, executor_func: Callable) -> TaskResult:
        """Execute a task using appropriate executor"""
        if task.task_id in self.running_tasks:
            raise ValueError(f"Task {task.task_id} is already running")

        # Check resource requirements
        if not self._can_execute_task(task):
            raise RuntimeError("Insufficient resources to execute task")

        self.running_tasks.add(task.task_id)

        try:
            start_time = time.time()
            start_memory = self._get_memory_usage()

            # Choose execution method based on task type
            if task.resource_requirements and task.resource_requirements.get(
                "needs_process", False
            ):
                # CPU-intensive task - use process pool
                future = asyncio.create_task(
                    self._execute_in_process(task, executor_func)
                )
            else:
                # I/O or light CPU task - use thread pool
                future = asyncio.create_task(
                    self._execute_in_thread(task, executor_func)
                )

            self.task_futures[task.task_id] = future

            # Execute with timeout
            try:
                result = await asyncio.wait_for(future, timeout=task.timeout_seconds)

                execution_time = time.time() - start_time
                memory_used = self._get_memory_usage() - start_memory

                return TaskResult(
                    task_id=task.task_id,
                    status=TaskStatus.COMPLETED,
                    result=result,
                    execution_time=execution_time,
                    memory_used=memory_used,
                )

            except asyncio.TimeoutError:
                future.cancel()
                return TaskResult(
                    task_id=task.task_id,
                    status=TaskStatus.FAILED,
                    error=f"Task timed out after {task.timeout_seconds} seconds",
                )

        except Exception as e:
            logger.error(f"Task {task.task_id} execution failed: {e}")
            return TaskResult(
                task_id=task.task_id, status=TaskStatus.FAILED, error=str(e)
            )

        finally:
            self.running_tasks.discard(task.task_id)
            self.task_futures.pop(task.task_id, None)

    async def _execute_in_thread(self, task: Task, executor_func: Callable) -> Any:
        """Execute task in thread pool"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.thread_pool, executor_func, task)

    async def _execute_in_process(self, task: Task, executor_func: Callable) -> Any:
        """Execute task in process pool"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.process_pool, executor_func, task)

    def _can_execute_task(self, task: Task) -> bool:
        """Check if task can be executed given resource constraints"""
        # Check memory limit
        current_memory = self._get_memory_usage()
        required_memory = (
            task.resource_requirements.get("memory_gb", 0.5)
            if task.resource_requirements
            else 0.5
        )

        if current_memory + required_memory > self.memory_limit_gb:
            return False

        # Check if we have available slots
        if len(self.running_tasks) >= self.max_threads:
            return False

        return True

    def _get_memory_usage(self) -> float:
        """Get current memory usage in GB"""
        process = psutil.Process()
        return process.memory_info().rss / (1024**3)

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task"""
        if task_id in self.task_futures:
            future = self.task_futures[task_id]
            future.cancel()
            return True
        return False

    def get_resource_usage(self) -> Dict:
        """Get current resource usage"""
        return {
            "running_tasks": len(self.running_tasks),
            "memory_usage_gb": self._get_memory_usage(),
            "cpu_usage_percent": psutil.cpu_percent(),
            "available_slots": self.max_threads - len(self.running_tasks),
        }


class HealthMonitor:
    """Monitors node health and performance metrics"""

    def __init__(self):
        self.metrics_history: List[Dict] = []
        self.max_history_size = 1000
        self._monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None

    async def start_monitoring(self, interval: int = 30):
        """Start health monitoring"""
        self._monitoring = True
        self._monitor_task = asyncio.create_task(self._monitor_loop(interval))

    async def stop_monitoring(self):
        """Stop health monitoring"""
        self._monitoring = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

    async def _monitor_loop(self, interval: int):
        """Main monitoring loop"""
        while self._monitoring:
            try:
                metrics = self._collect_metrics()
                self.metrics_history.append(metrics)

                # Trim history if needed
                if len(self.metrics_history) > self.max_history_size:
                    self.metrics_history = self.metrics_history[
                        -self.max_history_size :
                    ]

                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health monitoring error: {e}")
                await asyncio.sleep(5)

    def _collect_metrics(self) -> Dict:
        """Collect current system metrics"""
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        network = psutil.net_io_counters()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "cpu_percent": psutil.cpu_percent(),
            "memory_percent": memory.percent,
            "memory_available_gb": memory.available / (1024**3),
            "disk_percent": disk.percent,
            "disk_free_gb": disk.free / (1024**3),
            "network_bytes_sent": network.bytes_sent,
            "network_bytes_recv": network.bytes_recv,
            "load_average": (
                psutil.getloadavg()[0] if hasattr(psutil, "getloadavg") else 0.0
            ),
        }

    def get_health_status(self) -> Dict:
        """Get current health status"""
        if not self.metrics_history:
            return {"status": "unknown", "metrics": {}}

        latest_metrics = self.metrics_history[-1]

        # Determine health status
        status = "healthy"
        warnings = []

        if latest_metrics["cpu_percent"] > 90:
            status = "warning"
            warnings.append("High CPU usage")

        if latest_metrics["memory_percent"] > 90:
            status = "warning"
            warnings.append("High memory usage")

        if latest_metrics["disk_percent"] > 90:
            status = "critical"
            warnings.append("Low disk space")

        return {"status": status, "warnings": warnings, "metrics": latest_metrics}


class WorkerNode:
    """Main worker node for distributed task processing (lite implementation for tests)."""

    def __init__(self, config_or_node_id, redis_client=None, **kwargs):
        # Support legacy signature (node_id, coordinator, ...) but prefer config-based.
        if isinstance(config_or_node_id, WorkerNodeConfig):
            self.config = config_or_node_id
            self.redis = redis_client
            self.node_id = self.config.node_id
            self.coordinator_url = self.config.coordinator_url
            self.task_executor = TaskExecutor(self.config.max_concurrent_tasks)
            self.resource_monitor = ResourceMonitor(
                self.config.resource_monitoring_interval
            )
            # simple queue for TaskRequest objects
            self._task_queue: asyncio.Queue[TaskRequest] = asyncio.Queue()
            self.status = NodeStatus.JOINING
            self.is_running = False
        else:
            # fallback to legacy init to avoid breaking existing code
            node_id = config_or_node_id
            coordinator = redis_client
            self.node_id = node_id
            self.coordinator = coordinator
            self.redis = coordinator.redis if coordinator else redis_client
            self.work_queue = WorkQueue()
            self.executor = ParallelExecutor(
                kwargs.get("max_threads", 4), kwargs.get("max_processes", 2)
            )
            self.health_monitor = HealthMonitor()
            self.task_executors: Dict[str, Callable] = {}
            self.work_steal_enabled = kwargs.get("work_steal_enabled", True)
            self.steal_threshold = 0.5
            self._running = False
            self._worker_task: Optional[asyncio.Task] = None
            self._steal_task: Optional[asyncio.Task] = None
            self.status = NodeStatus.JOINING
            self.is_running = False
            # Compatibility helpers
            self.task_executor = TaskExecutor()
            self.resource_monitor = ResourceMonitor()
            self.config = WorkerNodeConfig(
                node_id=node_id,
                coordinator_url="",
                max_concurrent_tasks=self.executor.max_threads,
            )
        logger.info(f"Initialized worker node {self.node_id}")

    async def start(self):
        """Start the worker node"""
        self._running = True

        # Start health monitoring
        await self.health_monitor.start_monitoring()

        # Start worker loop
        self._worker_task = asyncio.create_task(self._worker_loop())

        # Start work stealing if enabled
        if self.work_steal_enabled:
            self._steal_task = asyncio.create_task(self._work_steal_loop())

        logger.info("Worker node started")

    async def stop(self):
        """Stop the worker node"""
        self._running = False

        # Stop health monitoring
        await self.health_monitor.stop_monitoring()

        # Stop worker loop
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

        # Stop work stealing
        if self._steal_task:
            self._steal_task.cancel()
            try:
                await self._steal_task
            except asyncio.CancelledError:
                pass

        logger.info("Worker node stopped")

    def register_task_executor(self, task_type: str, executor_func: Callable):
        """Register a task executor function"""
        self.task_executors[task_type] = executor_func
        logger.info(f"Registered executor for task type: {task_type}")

    async def submit_task(self, task: Task) -> bool:
        """Submit a task for execution"""
        # Add to local queue
        if self.work_queue.put(task):
            # Also add to Redis for work stealing
            await self.redis.lpush(
                f"task_queue:{self.node_id}", json.dumps(task.to_dict())
            )

            logger.info(f"Submitted task {task.task_id}")
            return True
        else:
            logger.warning(f"Failed to submit task {task.task_id} - queue full")
            return False

    async def process_task(self, task: Task) -> TaskResult:
        """Process a single task"""
        logger.info(f"Processing task {task.task_id} of type {task.task_type}")

        # Check if we have an executor for this task type
        if task.task_type not in self.task_executors:
            return TaskResult(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                error=f"No executor registered for task type: {task.task_type}",
                node_id=self.node_id,
            )

        try:
            # Execute the task
            executor_func = self.task_executors[task.task_type]
            result = await self.executor.execute_task(task, executor_func)
            result.node_id = self.node_id

            # Store result in Redis
            await self.redis.setex(
                f"task_result:{task.task_id}",
                3600,  # 1 hour TTL
                json.dumps(result.to_dict()),
            )

            logger.info(f"Completed task {task.task_id}: {result.status}")
            return result

        except Exception as e:
            logger.error(f"Task {task.task_id} processing failed: {e}")
            result = TaskResult(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                error=str(e),
                node_id=self.node_id,
            )

            # Store error result
            await self.redis.setex(
                f"task_result:{task.task_id}", 3600, json.dumps(result.to_dict())
            )

            return result

    async def steal_work(self) -> Optional[Task]:
        """Attempt to steal work from other nodes"""
        if not self.work_steal_enabled:
            return None

        try:
            # Get list of other nodes
            cluster_status = await self.coordinator.get_cluster_status()
            other_nodes = [
                node["node_id"]
                for node in cluster_status["nodes"]
                if node["node_id"] != self.node_id and node["status"] == "active"
            ]

            # Try to steal from nodes with work
            for node_id in other_nodes:
                task_data = await self.redis.brpop(f"task_queue:{node_id}", timeout=1)

                if task_data:
                    _, task_json = task_data
                    task = Task.from_dict(json.loads(task_json))
                    task.assigned_node = self.node_id

                    logger.info(f"Stole task {task.task_id} from node {node_id}")
                    return task

            return None

        except Exception as e:
            logger.error(f"Work stealing error: {e}")
            return None

    async def _worker_loop(self):
        """Main worker processing loop"""
        while self._running:
            try:
                # Get task from local queue first
                task = self.work_queue.get()

                if task:
                    # Process the task
                    await self.process_task(task)
                else:
                    # No local work, try to steal
                    stolen_task = await self.steal_work()
                    if stolen_task:
                        await self.process_task(stolen_task)
                    else:
                        # No work available, wait a bit
                        await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker loop error: {e}")
                await asyncio.sleep(5)

    async def _work_steal_loop(self):
        """Work stealing coordination loop"""
        while self._running:
            try:
                # Check our current utilization
                resource_usage = self.executor.get_resource_usage()
                utilization = (
                    resource_usage["running_tasks"] / self.executor.max_threads
                )

                # If utilization is low, try to steal work
                if utilization < self.steal_threshold:
                    stolen_task = await self.steal_work()
                    if stolen_task:
                        # Add to local queue for processing
                        self.work_queue.put(stolen_task)

                await asyncio.sleep(10)  # Check every 10 seconds

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Work steal loop error: {e}")
                await asyncio.sleep(5)

    def get_node_metrics(self) -> Dict:
        """Get comprehensive node metrics"""
        health_status = self.health_monitor.get_health_status()
        resource_usage = self.executor.get_resource_usage()

        return {
            "node_id": self.node_id,
            "queue_size": self.work_queue.size(),
            "health": health_status,
            "resources": resource_usage,
            "registered_executors": list(self.task_executors.keys()),
            "work_steal_enabled": self.work_steal_enabled,
        }

    # --- Lightweight overrides for config-based usage used in unit tests ---
    async def start(self):
        if isinstance(self.config, WorkerNodeConfig):
            await self.resource_monitor.start()
            self.is_running = True
            self.status = NodeStatus.ACTIVE
            # record heartbeat once
            if self.redis and hasattr(self.redis, "hset"):
                await self.redis.hset(
                    f"heartbeat:{self.config.node_id}",
                    mapping={
                        "status": self.status.value,
                        "ts": datetime.utcnow().isoformat(),
                    },
                )
        else:
            return await super().start() if hasattr(super(), "start") else None

    async def stop(self):
        if isinstance(self.config, WorkerNodeConfig):
            await self.resource_monitor.stop()
            self.is_running = False
            self.status = NodeStatus.DRAINING
        else:
            return await super().stop() if hasattr(super(), "stop") else None

    async def handle_task_assignment(
        self, task_request: TaskRequest
    ) -> TaskExecutionResult:
        result = await self.task_executor.execute_task(task_request)
        return result

    def get_current_resource_usage(self) -> Dict[str, Any]:
        usage = self.resource_monitor.get_resource_usage()
        usage["node_id"] = self.node_id
        return usage

    async def queue_task(self, task_request: TaskRequest):
        await self._task_queue.put(task_request)

    async def dequeue_task(self) -> Optional[TaskRequest]:
        try:
            return self._task_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    def is_queue_empty(self) -> bool:
        return self._task_queue.empty()

    def get_queued_task_count(self) -> int:
        return self._task_queue.qsize()

    async def graceful_shutdown(self, timeout: float = 5.0):
        self.status = NodeStatus.DRAINING
        self.is_running = False
        await self.resource_monitor.stop()

    async def handle_processing_error(self, error: Exception, task_id: str):
        # Log error but keep running
        logger.error(f"Processing error for {task_id}: {error}")
        self.status = NodeStatus.ACTIVE
        self.is_running = True

    def get_load_balancing_metrics(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "running_tasks": len(self.task_executor.running_tasks),
            "max_concurrent_tasks": getattr(self.config, "max_concurrent_tasks", 0),
        }

    def can_handle_task_type(self, task_type: str) -> bool:
        return task_type in self.task_executor.task_functions
