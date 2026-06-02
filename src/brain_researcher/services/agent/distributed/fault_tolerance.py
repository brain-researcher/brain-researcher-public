"""Fault Tolerance System

Implements failure detection, recovery mechanisms, and partition handling
for the distributed brain researcher agent system.
"""

import asyncio
import json
import logging
import random
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import redis.asyncio as redis

logger = logging.getLogger(__name__)


class FailureType(str, Enum):
    """Types of failures that can occur"""

    NODE_FAILURE = "node_failure"
    NETWORK_PARTITION = "network_partition"
    TASK_FAILURE = "task_failure"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    SERVICE_FAILURE = "service_failure"
    LEADERSHIP_FAILURE = "leadership_failure"


class RecoveryAction(str, Enum):
    """Recovery actions that can be taken"""

    RESTART_NODE = "restart_node"
    REASSIGN_TASKS = "reassign_tasks"
    ELECT_NEW_LEADER = "elect_new_leader"
    PARTITION_HEALING = "partition_healing"
    SCALE_UP = "scale_up"
    SCALE_DOWN = "scale_down"
    FAILOVER = "failover"
    CIRCUIT_BREAKER = "circuit_breaker"


class NodeState(str, Enum):
    """Possible node states"""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    SUSPECTED = "suspected"
    FAILED = "failed"
    RECOVERING = "recovering"
    QUARANTINED = "quarantined"


@dataclass
class FailureEvent:
    """Represents a detected failure event"""

    failure_id: str
    failure_type: FailureType
    affected_nodes: List[str]
    detected_at: datetime
    description: str
    severity: int  # 1-10, 10 being most severe
    metadata: Dict[str, Any] = field(default_factory=dict)
    resolved_at: Optional[datetime] = None
    recovery_actions: List[RecoveryAction] = field(default_factory=list)

    def to_dict(self) -> Dict:
        data = asdict(self)
        data["detected_at"] = self.detected_at.isoformat()
        if self.resolved_at:
            data["resolved_at"] = self.resolved_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict) -> "FailureEvent":
        if "detected_at" in data:
            data["detected_at"] = datetime.fromisoformat(data["detected_at"])
        if "resolved_at" in data and data["resolved_at"]:
            data["resolved_at"] = datetime.fromisoformat(data["resolved_at"])
        return cls(**data)


@dataclass
class RecoveryPlan:
    """Recovery plan for handling failures"""

    plan_id: str
    failure_event: FailureEvent
    recovery_actions: List[Tuple[RecoveryAction, Dict[str, Any]]]
    estimated_recovery_time: int  # seconds
    priority: int  # 1-10, 10 being highest priority
    created_at: datetime = field(default_factory=datetime.utcnow)
    executed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    success: bool = False

    def to_dict(self) -> Dict:
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        if self.executed_at:
            data["executed_at"] = self.executed_at.isoformat()
        if self.completed_at:
            data["completed_at"] = self.completed_at.isoformat()
        return data


class FailureDetector:
    """Detects various types of failures in the distributed system"""

    def __init__(self, redis_client: redis.Redis, node_id: str):
        self.redis = redis_client
        self.node_id = node_id

        # Detection parameters
        self.heartbeat_timeout = 90  # seconds
        self.failure_threshold = 3  # consecutive failures to declare node failed
        self.degradation_threshold = 80  # % utilization to declare degraded

        # State tracking
        self.node_states: Dict[str, NodeState] = {}
        self.failure_counts: Dict[str, int] = defaultdict(int)
        self.last_heartbeats: Dict[str, datetime] = {}

        # Detection history
        self.failure_history: deque = deque(maxlen=1000)

        # Monitoring
        self._detecting = False
        self._detection_task: Optional[asyncio.Task] = None

    async def start_detection(self, interval: int = 30):
        """Start failure detection"""
        self._detecting = True
        self._detection_task = asyncio.create_task(self._detection_loop(interval))
        logger.info("Failure detection started")

    async def stop_detection(self):
        """Stop failure detection"""
        self._detecting = False
        if self._detection_task:
            self._detection_task.cancel()
            try:
                await self._detection_task
            except asyncio.CancelledError:
                pass
        logger.info("Failure detection stopped")

    async def _detection_loop(self, interval: int):
        """Main failure detection loop"""
        while self._detecting:
            try:
                await self._detect_node_failures()
                await self._detect_network_partitions()
                await self._detect_resource_exhaustion()
                await self._detect_service_failures()
                await self._detect_leadership_failures()

                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Failure detection error: {e}")
                await asyncio.sleep(5)

    async def _detect_node_failures(self):
        """Detect node failures based on heartbeats"""
        try:
            current_time = datetime.utcnow()

            # Get all nodes and their heartbeats
            async for key in self.redis.scan_iter(match="heartbeat:*"):
                node_id = key.decode().split(":")[1]

                heartbeat_data = await self.redis.hgetall(key)
                if not heartbeat_data:
                    await self._handle_missing_heartbeat(node_id, current_time)
                    continue

                try:
                    timestamp_str = heartbeat_data.get(b"timestamp", b"").decode()
                    if timestamp_str:
                        last_heartbeat = datetime.fromisoformat(timestamp_str)
                        self.last_heartbeats[node_id] = last_heartbeat

                        # Check if heartbeat is stale
                        time_since_heartbeat = current_time - last_heartbeat
                        if (
                            time_since_heartbeat.total_seconds()
                            > self.heartbeat_timeout
                        ):
                            await self._handle_stale_heartbeat(
                                node_id, time_since_heartbeat.total_seconds()
                            )
                        else:
                            # Reset failure count for healthy nodes
                            if node_id in self.failure_counts:
                                self.failure_counts[node_id] = 0
                            self.node_states[node_id] = NodeState.HEALTHY

                except (ValueError, KeyError) as e:
                    logger.warning(f"Invalid heartbeat data for {node_id}: {e}")
                    await self._handle_invalid_heartbeat(node_id)

        except Exception as e:
            logger.error(f"Node failure detection error: {e}")

    async def _handle_missing_heartbeat(self, node_id: str, current_time: datetime):
        """Handle missing heartbeat data"""
        self.failure_counts[node_id] += 1

        if self.failure_counts[node_id] >= self.failure_threshold:
            if self.node_states.get(node_id) != NodeState.FAILED:
                await self._create_failure_event(
                    FailureType.NODE_FAILURE,
                    [node_id],
                    f"Node {node_id} missing heartbeat",
                    severity=8,
                    metadata={"missing_heartbeat_duration": "unknown"},
                )
                self.node_states[node_id] = NodeState.FAILED
        else:
            self.node_states[node_id] = NodeState.SUSPECTED

    async def _handle_stale_heartbeat(self, node_id: str, stale_seconds: float):
        """Handle stale heartbeat"""
        self.failure_counts[node_id] += 1

        if self.failure_counts[node_id] >= self.failure_threshold:
            if self.node_states.get(node_id) != NodeState.FAILED:
                await self._create_failure_event(
                    FailureType.NODE_FAILURE,
                    [node_id],
                    f"Node {node_id} heartbeat timeout",
                    severity=7,
                    metadata={"stale_seconds": stale_seconds},
                )
                self.node_states[node_id] = NodeState.FAILED
        else:
            self.node_states[node_id] = NodeState.SUSPECTED

    async def _handle_invalid_heartbeat(self, node_id: str):
        """Handle invalid heartbeat data"""
        self.failure_counts[node_id] += 1
        self.node_states[node_id] = NodeState.DEGRADED

    async def _detect_network_partitions(self):
        """Detect network partitions"""
        try:
            # Get all active nodes
            active_nodes = set()
            async for key in self.redis.scan_iter(match="node:*"):
                node_data = await self.redis.hgetall(key)
                if node_data and node_data.get(b"status") == b"active":
                    node_id = node_data.get(b"node_id", b"").decode()
                    if node_id:
                        active_nodes.add(node_id)

            # Check for sudden loss of many nodes (possible partition)
            healthy_nodes = set(
                node_id
                for node_id, state in self.node_states.items()
                if state in [NodeState.HEALTHY, NodeState.DEGRADED]
            )

            if active_nodes and healthy_nodes:
                partition_ratio = len(healthy_nodes) / len(active_nodes)

                if partition_ratio < 0.5:  # Less than half nodes are healthy
                    await self._create_failure_event(
                        FailureType.NETWORK_PARTITION,
                        list(active_nodes - healthy_nodes),
                        "Network partition suspected - many nodes unreachable",
                        severity=9,
                        metadata={
                            "healthy_nodes": len(healthy_nodes),
                            "total_nodes": len(active_nodes),
                            "partition_ratio": partition_ratio,
                        },
                    )

        except Exception as e:
            logger.error(f"Network partition detection error: {e}")

    async def _detect_resource_exhaustion(self):
        """Detect resource exhaustion on nodes"""
        try:
            # Check node metrics for resource exhaustion
            async for key in self.redis.scan_iter(match="node_metrics:*"):
                node_id = key.decode().split(":")[1]

                metrics_data = await self.redis.get(key)
                if not metrics_data:
                    continue

                try:
                    metrics = json.loads(metrics_data)

                    # Check CPU utilization
                    cpu_util = metrics.get("cpu_utilization", 0)
                    memory_util = metrics.get("memory_utilization", 0)

                    if cpu_util > 95 or memory_util > 95:
                        await self._create_failure_event(
                            FailureType.RESOURCE_EXHAUSTION,
                            [node_id],
                            f"Resource exhaustion on node {node_id}",
                            severity=6,
                            metadata={
                                "cpu_utilization": cpu_util,
                                "memory_utilization": memory_util,
                            },
                        )

                except json.JSONDecodeError:
                    continue

        except Exception as e:
            logger.error(f"Resource exhaustion detection error: {e}")

    async def _detect_service_failures(self):
        """Detect service-specific failures"""
        try:
            # Check for failed tasks
            failed_tasks = []

            async for key in self.redis.scan_iter(match="task_result:*"):
                result_data = await self.redis.get(key)
                if result_data:
                    try:
                        result = json.loads(result_data)
                        if result.get("status") == "failed":
                            failed_tasks.append(result)
                    except json.JSONDecodeError:
                        continue

            # If too many tasks are failing, it might indicate a service issue
            if len(failed_tasks) > 10:  # Threshold for service failure
                affected_nodes = list(
                    set(
                        task.get("node_id")
                        for task in failed_tasks
                        if task.get("node_id")
                    )
                )

                await self._create_failure_event(
                    FailureType.SERVICE_FAILURE,
                    affected_nodes,
                    f"High task failure rate detected - {len(failed_tasks)} failed tasks",
                    severity=7,
                    metadata={"failed_task_count": len(failed_tasks)},
                )

        except Exception as e:
            logger.error(f"Service failure detection error: {e}")

    async def _detect_leadership_failures(self):
        """Detect leadership failures"""
        try:
            leader_data = await self.redis.get("cluster:leader")

            if not leader_data:
                # No leader present
                await self._create_failure_event(
                    FailureType.LEADERSHIP_FAILURE,
                    [],
                    "No cluster leader detected",
                    severity=8,
                    metadata={"issue": "no_leader"},
                )
                return

            try:
                leader_info = json.loads(leader_data)
                leader_id = leader_info.get("node_id")

                if leader_id and leader_id in self.node_states:
                    leader_state = self.node_states[leader_id]

                    if leader_state in [NodeState.FAILED, NodeState.SUSPECTED]:
                        await self._create_failure_event(
                            FailureType.LEADERSHIP_FAILURE,
                            [leader_id],
                            f"Leader node {leader_id} is in {leader_state.value} state",
                            severity=9,
                            metadata={"leader_state": leader_state.value},
                        )

            except json.JSONDecodeError:
                logger.warning("Invalid leader data format")

        except Exception as e:
            logger.error(f"Leadership failure detection error: {e}")

    async def _create_failure_event(
        self,
        failure_type: FailureType,
        affected_nodes: List[str],
        description: str,
        severity: int,
        metadata: Dict = None,
    ):
        """Create and store a failure event"""
        failure_id = f"failure_{int(time.time())}_{random.randint(1000, 9999)}"

        event = FailureEvent(
            failure_id=failure_id,
            failure_type=failure_type,
            affected_nodes=affected_nodes,
            detected_at=datetime.utcnow(),
            description=description,
            severity=severity,
            metadata=metadata or {},
        )

        # Store in history
        self.failure_history.append(event)

        # Store in Redis
        await self.redis.setex(
            f"failure_event:{failure_id}",
            3600,  # 1 hour TTL
            json.dumps(event.to_dict()),
        )

        # Publish failure event
        await self.redis.publish(
            "cluster:failures",
            json.dumps({"event_type": "failure_detected", "failure": event.to_dict()}),
        )

        logger.warning(f"Failure detected: {failure_type.value} - {description}")

    def get_node_state(self, node_id: str) -> NodeState:
        """Get current state of a node"""
        return self.node_states.get(node_id, NodeState.HEALTHY)

    def get_failure_history(self, limit: int = 100) -> List[FailureEvent]:
        """Get recent failure history"""
        return list(self.failure_history)[-limit:]


class RecoveryManager:
    """Manages recovery actions for detected failures"""

    def __init__(self, redis_client: redis.Redis, coordinator):
        self.redis = redis_client
        self.coordinator = coordinator

        # Recovery action handlers
        self.recovery_handlers: Dict[RecoveryAction, Callable] = {
            RecoveryAction.RESTART_NODE: self._restart_node,
            RecoveryAction.REASSIGN_TASKS: self._reassign_tasks,
            RecoveryAction.ELECT_NEW_LEADER: self._elect_new_leader,
            RecoveryAction.PARTITION_HEALING: self._heal_partition,
            RecoveryAction.FAILOVER: self._failover,
            RecoveryAction.CIRCUIT_BREAKER: self._circuit_breaker,
        }

        # Recovery state
        self.active_recoveries: Dict[str, RecoveryPlan] = {}
        self.recovery_history: deque = deque(maxlen=1000)

    async def handle_failure(
        self, failure_event: FailureEvent
    ) -> Optional[RecoveryPlan]:
        """Create and execute recovery plan for failure"""
        try:
            # Generate recovery plan
            recovery_plan = await self._generate_recovery_plan(failure_event)

            if not recovery_plan:
                logger.warning(
                    f"No recovery plan generated for failure {failure_event.failure_id}"
                )
                return None

            # Store active recovery
            self.active_recoveries[recovery_plan.plan_id] = recovery_plan

            # Execute recovery plan
            await self._execute_recovery_plan(recovery_plan)

            return recovery_plan

        except Exception as e:
            logger.error(
                f"Recovery handling failed for {failure_event.failure_id}: {e}"
            )
            return None

    async def _generate_recovery_plan(
        self, failure_event: FailureEvent
    ) -> Optional[RecoveryPlan]:
        """Generate recovery plan based on failure type"""
        plan_id = f"recovery_{failure_event.failure_id}_{int(time.time())}"
        recovery_actions = []
        estimated_time = 0
        priority = failure_event.severity

        if failure_event.failure_type == FailureType.NODE_FAILURE:
            recovery_actions = [
                (
                    RecoveryAction.REASSIGN_TASKS,
                    {"nodes": failure_event.affected_nodes},
                ),
                (RecoveryAction.RESTART_NODE, {"nodes": failure_event.affected_nodes}),
            ]
            estimated_time = 180  # 3 minutes

        elif failure_event.failure_type == FailureType.LEADERSHIP_FAILURE:
            recovery_actions = [(RecoveryAction.ELECT_NEW_LEADER, {})]
            estimated_time = 60  # 1 minute

        elif failure_event.failure_type == FailureType.NETWORK_PARTITION:
            recovery_actions = [
                (
                    RecoveryAction.PARTITION_HEALING,
                    {"nodes": failure_event.affected_nodes},
                )
            ]
            estimated_time = 300  # 5 minutes

        elif failure_event.failure_type == FailureType.RESOURCE_EXHAUSTION:
            recovery_actions = [
                (
                    RecoveryAction.CIRCUIT_BREAKER,
                    {"nodes": failure_event.affected_nodes},
                ),
                (
                    RecoveryAction.REASSIGN_TASKS,
                    {"nodes": failure_event.affected_nodes},
                ),
            ]
            estimated_time = 120  # 2 minutes

        elif failure_event.failure_type == FailureType.SERVICE_FAILURE:
            recovery_actions = [
                (RecoveryAction.RESTART_NODE, {"nodes": failure_event.affected_nodes}),
                (
                    RecoveryAction.CIRCUIT_BREAKER,
                    {"nodes": failure_event.affected_nodes},
                ),
            ]
            estimated_time = 240  # 4 minutes

        else:
            logger.warning(
                f"No recovery plan for failure type: {failure_event.failure_type}"
            )
            return None

        return RecoveryPlan(
            plan_id=plan_id,
            failure_event=failure_event,
            recovery_actions=recovery_actions,
            estimated_recovery_time=estimated_time,
            priority=priority,
        )

    async def _execute_recovery_plan(self, recovery_plan: RecoveryPlan):
        """Execute recovery plan"""
        try:
            recovery_plan.executed_at = datetime.utcnow()

            logger.info(f"Executing recovery plan {recovery_plan.plan_id}")

            success = True

            for action, params in recovery_plan.recovery_actions:
                try:
                    if action in self.recovery_handlers:
                        await self.recovery_handlers[action](**params)
                        logger.info(f"Recovery action {action.value} completed")
                    else:
                        logger.warning(
                            f"No handler for recovery action: {action.value}"
                        )
                        success = False

                except Exception as e:
                    logger.error(f"Recovery action {action.value} failed: {e}")
                    success = False

            recovery_plan.completed_at = datetime.utcnow()
            recovery_plan.success = success

            # Move to history
            self.recovery_history.append(recovery_plan)
            if recovery_plan.plan_id in self.active_recoveries:
                del self.active_recoveries[recovery_plan.plan_id]

            # Mark failure as resolved if recovery successful
            if success:
                recovery_plan.failure_event.resolved_at = datetime.utcnow()

            logger.info(
                f"Recovery plan {recovery_plan.plan_id} completed - Success: {success}"
            )

        except Exception as e:
            logger.error(f"Recovery plan execution failed: {e}")
            recovery_plan.success = False
            recovery_plan.completed_at = datetime.utcnow()

    async def _restart_node(self, nodes: List[str]):
        """Restart failed nodes"""
        for node_id in nodes:
            try:
                # In a real implementation, this would trigger node restart
                # For now, we'll mark for restart and publish event
                await self.redis.publish(
                    f"node_control:{node_id}",
                    json.dumps(
                        {
                            "action": "restart",
                            "timestamp": datetime.utcnow().isoformat(),
                        }
                    ),
                )
                logger.info(f"Restart requested for node {node_id}")

            except Exception as e:
                logger.error(f"Failed to restart node {node_id}: {e}")

    async def _reassign_tasks(self, nodes: List[str]):
        """Reassign tasks from failed nodes"""
        for node_id in nodes:
            try:
                # Get tasks from failed node's queue
                tasks_data = await self.redis.lrange(f"task_queue:{node_id}", 0, -1)

                for task_json in tasks_data:
                    # Reassign to healthy nodes via load balancer
                    await self.redis.lpush("task_queue:unassigned", task_json)

                # Clear failed node's queue
                await self.redis.delete(f"task_queue:{node_id}")

                logger.info(f"Reassigned {len(tasks_data)} tasks from node {node_id}")

            except Exception as e:
                logger.error(f"Failed to reassign tasks from node {node_id}: {e}")

    async def _elect_new_leader(self):
        """Trigger new leader election"""
        try:
            if hasattr(self.coordinator, "elect_leader"):
                await self.coordinator.elect_leader()
                logger.info("New leader election triggered")
            else:
                logger.warning("Coordinator does not support leader election")

        except Exception as e:
            logger.error(f"Leader election failed: {e}")

    async def _heal_partition(self, nodes: List[str]):
        """Attempt to heal network partition"""
        try:
            # Publish partition healing event
            await self.redis.publish(
                "cluster:partition_healing",
                json.dumps(
                    {
                        "action": "heal_partition",
                        "affected_nodes": nodes,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                ),
            )

            logger.info(f"Partition healing initiated for nodes: {nodes}")

        except Exception as e:
            logger.error(f"Partition healing failed: {e}")

    async def _failover(self, nodes: List[str]):
        """Perform failover for affected nodes"""
        try:
            for node_id in nodes:
                # Mark node for failover
                await self.redis.hset(f"node:{node_id}", "status", "failed_over")

            # Trigger rebalancing
            await self.coordinator._trigger_rebalance()

            logger.info(f"Failover completed for nodes: {nodes}")

        except Exception as e:
            logger.error(f"Failover failed: {e}")

    async def _circuit_breaker(self, nodes: List[str]):
        """Activate circuit breaker for overloaded nodes"""
        try:
            for node_id in nodes:
                # Set circuit breaker flag
                await self.redis.setex(
                    f"circuit_breaker:{node_id}",
                    300,  # 5 minutes
                    json.dumps({"activated_at": datetime.utcnow().isoformat()}),
                )

            logger.info(f"Circuit breaker activated for nodes: {nodes}")

        except Exception as e:
            logger.error(f"Circuit breaker activation failed: {e}")


class FaultTolerance:
    """Main fault tolerance system"""

    def __init__(self, coordinator, redis_client: redis.Redis = None):
        self.coordinator = coordinator
        self.redis = redis_client or coordinator.redis

        # Components
        self.failure_detector = FailureDetector(self.redis, coordinator.node_id)
        self.recovery_manager = RecoveryManager(self.redis, coordinator)

        # Event subscription
        self._monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None

        logger.info("Fault tolerance system initialized")

    async def start(self):
        """Start fault tolerance system"""
        # Start failure detection
        await self.failure_detector.start_detection()

        # Start event monitoring
        self._monitoring = True
        self._monitor_task = asyncio.create_task(self._monitor_events())

        logger.info("Fault tolerance system started")

    async def stop(self):
        """Stop fault tolerance system"""
        # Stop failure detection
        await self.failure_detector.stop_detection()

        # Stop event monitoring
        self._monitoring = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        logger.info("Fault tolerance system stopped")

    async def _monitor_events(self):
        """Monitor failure events and trigger recovery"""
        try:
            pubsub = self.redis.pubsub()
            await pubsub.subscribe("cluster:failures")

            while self._monitoring:
                message = await pubsub.get_message(timeout=1.0)
                if message and message["type"] == "message":
                    try:
                        event_data = json.loads(message["data"])

                        if event_data.get("event_type") == "failure_detected":
                            failure_data = event_data.get("failure")
                            if failure_data:
                                failure_event = FailureEvent.from_dict(failure_data)
                                await self.recovery_manager.handle_failure(
                                    failure_event
                                )

                    except (json.JSONDecodeError, KeyError) as e:
                        logger.warning(f"Invalid failure event message: {e}")

            await pubsub.unsubscribe("cluster:failures")
            await pubsub.close()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Event monitoring error: {e}")

    async def handle_node_failure(self, node_id: str) -> bool:
        """Handle specific node failure"""
        try:
            # Create failure event
            failure_event = FailureEvent(
                failure_id=f"manual_node_failure_{int(time.time())}",
                failure_type=FailureType.NODE_FAILURE,
                affected_nodes=[node_id],
                detected_at=datetime.utcnow(),
                description=f"Manual handling of node {node_id} failure",
                severity=8,
            )

            # Trigger recovery
            recovery_plan = await self.recovery_manager.handle_failure(failure_event)

            return recovery_plan is not None and recovery_plan.success

        except Exception as e:
            logger.error(f"Node failure handling failed: {e}")
            return False

    async def handle_network_partition(self, affected_nodes: List[str]) -> bool:
        """Handle network partition"""
        try:
            failure_event = FailureEvent(
                failure_id=f"manual_partition_{int(time.time())}",
                failure_type=FailureType.NETWORK_PARTITION,
                affected_nodes=affected_nodes,
                detected_at=datetime.utcnow(),
                description=f"Manual handling of network partition affecting {len(affected_nodes)} nodes",
                severity=9,
            )

            recovery_plan = await self.recovery_manager.handle_failure(failure_event)

            return recovery_plan is not None and recovery_plan.success

        except Exception as e:
            logger.error(f"Network partition handling failed: {e}")
            return False

    def get_cluster_health(self) -> Dict:
        """Get overall cluster health status"""
        node_states = {}
        for node_id, state in self.failure_detector.node_states.items():
            node_states[node_id] = state.value

        healthy_nodes = sum(
            1
            for state in self.failure_detector.node_states.values()
            if state == NodeState.HEALTHY
        )
        total_nodes = len(self.failure_detector.node_states)

        health_ratio = healthy_nodes / total_nodes if total_nodes > 0 else 1.0

        if health_ratio >= 0.9:
            overall_health = "excellent"
        elif health_ratio >= 0.7:
            overall_health = "good"
        elif health_ratio >= 0.5:
            overall_health = "degraded"
        else:
            overall_health = "critical"

        return {
            "overall_health": overall_health,
            "health_ratio": health_ratio,
            "healthy_nodes": healthy_nodes,
            "total_nodes": total_nodes,
            "node_states": node_states,
            "active_recoveries": len(self.recovery_manager.active_recoveries),
            "recent_failures": len(
                self.failure_detector.get_failure_history(24)
            ),  # last 24 failures
        }
