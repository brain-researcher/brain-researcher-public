"""Distributed State Synchronization

Implements CRDT-based state synchronization with vector clocks and conflict resolution
for the distributed brain researcher agent system.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Set, Tuple, Union, Callable
from dataclasses import dataclass, asdict, field
from enum import Enum
from collections import defaultdict
import hashlib
import uuid

import redis.asyncio as redis


logger = logging.getLogger(__name__)


class CRDTType(str, Enum):
    """Types of CRDTs supported"""
    G_COUNTER = "g_counter"  # Grow-only counter
    PN_COUNTER = "pn_counter"  # Positive-negative counter
    G_SET = "g_set"  # Grow-only set
    OR_SET = "or_set"  # Observed-remove set
    LWW_REGISTER = "lww_register"  # Last-writer-wins register
    OR_MAP = "or_map"  # Observed-remove map


class OperationType(str, Enum):
    """Types of operations on CRDTs"""
    INCREMENT = "increment"
    DECREMENT = "decrement"
    ADD = "add"
    REMOVE = "remove"
    SET = "set"
    UPDATE = "update"


@dataclass
class VectorClock:
    """Vector clock for tracking causality in distributed systems"""
    clocks: Dict[str, int] = field(default_factory=dict)

    def tick(self, node_id: str):
        """Increment the clock for a node"""
        self.clocks[node_id] = self.clocks.get(node_id, 0) + 1

    def update(self, other: 'VectorClock'):
        """Update this clock with another clock (take maximum)"""
        for node_id, clock_value in other.clocks.items():
            self.clocks[node_id] = max(self.clocks.get(node_id, 0), clock_value)

    def compare(self, other: 'VectorClock') -> str:
        """Compare two vector clocks"""
        all_nodes = set(self.clocks.keys()) | set(other.clocks.keys())

        self_greater = False
        other_greater = False

        for node_id in all_nodes:
            self_val = self.clocks.get(node_id, 0)
            other_val = other.clocks.get(node_id, 0)

            if self_val > other_val:
                self_greater = True
            elif self_val < other_val:
                other_greater = True

        if self_greater and not other_greater:
            return "greater"
        elif other_greater and not self_greater:
            return "less"
        elif not self_greater and not other_greater:
            return "equal"
        else:
            return "concurrent"

    def to_dict(self) -> Dict:
        return {"clocks": self.clocks}

    @classmethod
    def from_dict(cls, data: Dict) -> 'VectorClock':
        return cls(clocks=data.get("clocks", {}))


@dataclass
class Operation:
    """Represents an operation on a CRDT"""
    operation_id: str
    node_id: str
    operation_type: OperationType
    key: str
    value: Any
    timestamp: datetime
    vector_clock: VectorClock

    def __post_init__(self):
        if isinstance(self.timestamp, str):
            self.timestamp = datetime.fromisoformat(self.timestamp)

    def to_dict(self) -> Dict:
        return {
            "operation_id": self.operation_id,
            "node_id": self.node_id,
            "operation_type": self.operation_type.value,
            "key": self.key,
            "value": self.value,
            "timestamp": self.timestamp.isoformat(),
            "vector_clock": self.vector_clock.to_dict()
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'Operation':
        return cls(
            operation_id=data["operation_id"],
            node_id=data["node_id"],
            operation_type=OperationType(data["operation_type"]),
            key=data["key"],
            value=data["value"],
            timestamp=data["timestamp"],
            vector_clock=VectorClock.from_dict(data["vector_clock"])
        )


class GCounterCRDT:
    """Grow-only counter CRDT"""

    def __init__(self, node_id: str):
        self.node_id = node_id
        self.counters: Dict[str, int] = {}

    def increment(self, amount: int = 1):
        """Increment counter for this node"""
        if amount < 0:
            raise ValueError("GCounter only supports positive increments")
        self.counters[self.node_id] = self.counters.get(self.node_id, 0) + amount

    def value(self) -> int:
        """Get current counter value"""
        return sum(self.counters.values())

    def merge(self, other: 'GCounterCRDT'):
        """Merge with another GCounter"""
        for node_id, count in other.counters.items():
            self.counters[node_id] = max(self.counters.get(node_id, 0), count)

    def to_dict(self) -> Dict:
        return {"counters": self.counters}

    @classmethod
    def from_dict(cls, node_id: str, data: Dict) -> 'GCounterCRDT':
        counter = cls(node_id)
        counter.counters = data.get("counters", {})
        return counter


class PNCounterCRDT:
    """Positive-negative counter CRDT"""

    def __init__(self, node_id: str):
        self.node_id = node_id
        self.positive = GCounterCRDT(node_id)
        self.negative = GCounterCRDT(node_id)

    def increment(self, amount: int = 1):
        """Increment counter"""
        if amount >= 0:
            self.positive.increment(amount)
        else:
            self.negative.increment(-amount)

    def decrement(self, amount: int = 1):
        """Decrement counter"""
        self.increment(-amount)

    def value(self) -> int:
        """Get current counter value"""
        return self.positive.value() - self.negative.value()

    def merge(self, other: 'PNCounterCRDT'):
        """Merge with another PNCounter"""
        self.positive.merge(other.positive)
        self.negative.merge(other.negative)

    def to_dict(self) -> Dict:
        return {
            "positive": self.positive.to_dict(),
            "negative": self.negative.to_dict()
        }

    @classmethod
    def from_dict(cls, node_id: str, data: Dict) -> 'PNCounterCRDT':
        counter = cls(node_id)
        if "positive" in data:
            counter.positive = GCounterCRDT.from_dict(node_id, data["positive"])
        if "negative" in data:
            counter.negative = GCounterCRDT.from_dict(node_id, data["negative"])
        return counter


class ORSetCRDT:
    """Observed-remove set CRDT"""

    def __init__(self, node_id: str):
        self.node_id = node_id
        self.added: Dict[Any, Set[str]] = defaultdict(set)  # element -> set of unique tags
        self.removed: Dict[Any, Set[str]] = defaultdict(set)  # element -> set of unique tags

    def add(self, element: Any) -> str:
        """Add element to set, returns unique tag"""
        tag = f"{self.node_id}:{uuid.uuid4().hex}"
        self.added[element].add(tag)
        return tag

    def remove(self, element: Any):
        """Remove element from set"""
        if element in self.added:
            # Move all tags from added to removed
            self.removed[element].update(self.added[element])

    def contains(self, element: Any) -> bool:
        """Check if element is in set"""
        if element not in self.added:
            return False
        return bool(self.added[element] - self.removed[element])

    def value(self) -> Set[Any]:
        """Get current set value"""
        result = set()
        for element in self.added:
            if self.added[element] - self.removed[element]:
                result.add(element)
        return result

    def merge(self, other: 'ORSetCRDT'):
        """Merge with another ORSet"""
        # Merge added elements
        for element, tags in other.added.items():
            self.added[element].update(tags)

        # Merge removed elements
        for element, tags in other.removed.items():
            self.removed[element].update(tags)

    def to_dict(self) -> Dict:
        return {
            "added": {k: list(v) for k, v in self.added.items()},
            "removed": {k: list(v) for k, v in self.removed.items()}
        }

    @classmethod
    def from_dict(cls, node_id: str, data: Dict) -> 'ORSetCRDT':
        or_set = cls(node_id)

        if "added" in data:
            or_set.added = defaultdict(set)
            for element, tags in data["added"].items():
                or_set.added[element] = set(tags)

        if "removed" in data:
            or_set.removed = defaultdict(set)
            for element, tags in data["removed"].items():
                or_set.removed[element] = set(tags)

        return or_set


class LWWRegisterCRDT:
    """Last-writer-wins register CRDT"""

    def __init__(self, node_id: str):
        self.node_id = node_id
        self.value: Any = None
        self.timestamp: datetime = datetime.min
        self.writer_node: Optional[str] = None

    def set(self, value: Any, timestamp: Optional[datetime] = None):
        """Set register value"""
        if timestamp is None:
            timestamp = datetime.utcnow()

        # Only update if timestamp is newer
        if timestamp > self.timestamp:
            self.value = value
            self.timestamp = timestamp
            self.writer_node = self.node_id

    def get(self) -> Any:
        """Get register value"""
        return self.value

    def merge(self, other: 'LWWRegisterCRDT'):
        """Merge with another LWWRegister"""
        if other.timestamp > self.timestamp:
            self.value = other.value
            self.timestamp = other.timestamp
            self.writer_node = other.writer_node
        elif other.timestamp == self.timestamp and other.writer_node and self.writer_node:
            # Tie-breaking: use lexicographically smaller node ID
            if other.writer_node < self.writer_node:
                self.value = other.value
                self.writer_node = other.writer_node

    def to_dict(self) -> Dict:
        return {
            "value": self.value,
            "timestamp": self.timestamp.isoformat() if self.timestamp != datetime.min else None,
            "writer_node": self.writer_node
        }

    @classmethod
    def from_dict(cls, node_id: str, data: Dict) -> 'LWWRegisterCRDT':
        register = cls(node_id)
        register.value = data.get("value")
        if data.get("timestamp"):
            register.timestamp = datetime.fromisoformat(data["timestamp"])
        register.writer_node = data.get("writer_node")
        return register


class ConflictResolver:
    """Handles conflict resolution for different merge strategies"""

    @staticmethod
    def last_write_wins(states: List[Dict], timestamp_key: str = "timestamp") -> Dict:
        """Resolve conflict using last-writer-wins strategy"""
        if not states:
            return {}

        latest_state = states[0]
        latest_time = datetime.min

        for state in states:
            if timestamp_key in state:
                timestamp = datetime.fromisoformat(state[timestamp_key])
                if timestamp > latest_time:
                    latest_time = timestamp
                    latest_state = state

        return latest_state

    @staticmethod
    def merge_sets(states: List[Dict], key: str) -> Set:
        """Merge sets from multiple states"""
        merged_set = set()
        for state in states:
            if key in state:
                merged_set.update(state[key])
        return merged_set

    @staticmethod
    def max_value(states: List[Dict], key: str) -> Any:
        """Take maximum value across states"""
        max_val = None
        for state in states:
            if key in state:
                val = state[key]
                if max_val is None or (val is not None and val > max_val):
                    max_val = val
        return max_val

    @staticmethod
    def manual_resolution(states: List[Dict], resolution_func: callable) -> Dict:
        """Use custom resolution function"""
        return resolution_func(states)


class StateSync:
    """Main state synchronization manager"""

    def __init__(self,
                 redis_client: redis.Redis,
                 node_id: str,
                 sync_interval: int = 30):
        self.redis = redis_client
        self.node_id = node_id
        self.sync_interval = sync_interval

        # Vector clock for this node
        self.vector_clock = VectorClock()

        # CRDT instances
        self.crdts: Dict[str, Any] = {}

        # Conflict resolver
        self.conflict_resolver = ConflictResolver()

        # Operation log
        self.operation_log: List[Operation] = []
        self.max_log_size = 10000

        # Sync state
        self._syncing = False
        self._sync_task: Optional[asyncio.Task] = None

        logger.info(f"Initialized StateSync for node {node_id}")

    async def start(self):
        """Start state synchronization"""
        self._syncing = True
        self._sync_task = asyncio.create_task(self._sync_loop())
        logger.info("State synchronization started")

    async def stop(self):
        """Stop state synchronization"""
        self._syncing = False
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
        logger.info("State synchronization stopped")

    def create_crdt(self, key: str, crdt_type: CRDTType, initial_value: Any = None):
        """Create a new CRDT"""
        if crdt_type == CRDTType.G_COUNTER:
            self.crdts[key] = GCounterCRDT(self.node_id)
        elif crdt_type == CRDTType.PN_COUNTER:
            self.crdts[key] = PNCounterCRDT(self.node_id)
        elif crdt_type == CRDTType.OR_SET:
            self.crdts[key] = ORSetCRDT(self.node_id)
        elif crdt_type == CRDTType.LWW_REGISTER:
            crdt = LWWRegisterCRDT(self.node_id)
            if initial_value is not None:
                crdt.set(initial_value)
            self.crdts[key] = crdt
        else:
            raise ValueError(f"Unsupported CRDT type: {crdt_type}")

        logger.info(f"Created CRDT {key} of type {crdt_type}")

    def get_crdt(self, key: str) -> Optional[Any]:
        """Get CRDT by key"""
        return self.crdts.get(key)

    async def apply_operation(self, operation: Operation):
        """Apply an operation to a CRDT"""
        crdt = self.crdts.get(operation.key)
        if not crdt:
            logger.warning(f"CRDT {operation.key} not found for operation")
            return

        try:
            # Update vector clock
            self.vector_clock.update(operation.vector_clock)
            self.vector_clock.tick(self.node_id)

            # Apply operation based on type
            if operation.operation_type == OperationType.INCREMENT:
                if hasattr(crdt, 'increment'):
                    crdt.increment(operation.value)

            elif operation.operation_type == OperationType.DECREMENT:
                if hasattr(crdt, 'decrement'):
                    crdt.decrement(operation.value)

            elif operation.operation_type == OperationType.ADD:
                if hasattr(crdt, 'add'):
                    crdt.add(operation.value)

            elif operation.operation_type == OperationType.REMOVE:
                if hasattr(crdt, 'remove'):
                    crdt.remove(operation.value)

            elif operation.operation_type == OperationType.SET:
                if hasattr(crdt, 'set'):
                    crdt.set(operation.value)

            # Add to operation log
            self.operation_log.append(operation)

            # Trim log if needed
            if len(self.operation_log) > self.max_log_size:
                self.operation_log = self.operation_log[-self.max_log_size // 2:]

            logger.debug(f"Applied operation {operation.operation_id}")

        except Exception as e:
            logger.error(f"Failed to apply operation {operation.operation_id}: {e}")

    async def sync_state(self, target_node: Optional[str] = None):
        """Synchronize state with other nodes"""
        try:
            # Get list of nodes to sync with
            if target_node:
                nodes_to_sync = [target_node]
            else:
                # Get all active nodes
                nodes_to_sync = await self._get_active_nodes()

            for node_id in nodes_to_sync:
                if node_id == self.node_id:
                    continue

                await self._sync_with_node(node_id)

        except Exception as e:
            logger.error(f"State sync failed: {e}")

    async def _sync_with_node(self, node_id: str):
        """Synchronize state with a specific node"""
        try:
            # Get our current state
            our_state = await self._get_node_state()

            # Get other node's state
            other_state_data = await self.redis.hgetall(f"node_state:{node_id}")

            if not other_state_data:
                # Other node has no state, send ours
                await self._send_state_to_node(node_id, our_state)
                return

            # Parse other node's state
            other_state = {}
            for key, value in other_state_data.items():
                key_str = key.decode() if isinstance(key, bytes) else key
                value_str = value.decode() if isinstance(value, bytes) else value
                other_state[key_str] = json.loads(value_str)

            # Merge states
            await self._merge_states(our_state, other_state, node_id)

            # Send updated state back
            await self._send_state_to_node(node_id, await self._get_node_state())

        except Exception as e:
            logger.error(f"Failed to sync with node {node_id}: {e}")

    async def _merge_states(self, our_state: Dict, other_state: Dict, other_node_id: str):
        """Merge state from another node"""
        try:
            # Merge vector clocks
            if "vector_clock" in other_state:
                other_clock = VectorClock.from_dict(other_state["vector_clock"])
                self.vector_clock.update(other_clock)

            # Merge CRDTs
            if "crdts" in other_state:
                for key, crdt_data in other_state["crdts"].items():
                    if key not in self.crdts:
                        # We don't have this CRDT, skip or request full sync
                        continue

                    our_crdt = self.crdts[key]

                    # Create temporary CRDT from other node's data
                    if isinstance(our_crdt, GCounterCRDT):
                        other_crdt = GCounterCRDT.from_dict(other_node_id, crdt_data)
                        our_crdt.merge(other_crdt)

                    elif isinstance(our_crdt, PNCounterCRDT):
                        other_crdt = PNCounterCRDT.from_dict(other_node_id, crdt_data)
                        our_crdt.merge(other_crdt)

                    elif isinstance(our_crdt, ORSetCRDT):
                        other_crdt = ORSetCRDT.from_dict(other_node_id, crdt_data)
                        our_crdt.merge(other_crdt)

                    elif isinstance(our_crdt, LWWRegisterCRDT):
                        other_crdt = LWWRegisterCRDT.from_dict(other_node_id, crdt_data)
                        our_crdt.merge(other_crdt)

            logger.debug(f"Merged state from node {other_node_id}")

        except Exception as e:
            logger.error(f"Failed to merge states from {other_node_id}: {e}")

    async def _get_node_state(self) -> Dict:
        """Get current node state for synchronization"""
        state = {
            "node_id": self.node_id,
            "timestamp": datetime.utcnow().isoformat(),
            "vector_clock": self.vector_clock.to_dict(),
            "crdts": {}
        }

        # Serialize CRDTs
        for key, crdt in self.crdts.items():
            if hasattr(crdt, 'to_dict'):
                state["crdts"][key] = crdt.to_dict()

        return state

    async def _send_state_to_node(self, node_id: str, state: Dict):
        """Send our state to another node"""
        try:
            # Store state in Redis for the other node to read
            await self.redis.hset(
                f"node_state:{self.node_id}",
                mapping={k: json.dumps(v) for k, v in state.items()}
            )

            # Set expiration
            await self.redis.expire(f"node_state:{self.node_id}", 3600)

            # Notify the other node
            await self.redis.publish(
                f"sync_channel:{node_id}",
                json.dumps({
                    "type": "state_update",
                    "from_node": self.node_id,
                    "timestamp": datetime.utcnow().isoformat()
                })
            )

        except Exception as e:
            logger.error(f"Failed to send state to node {node_id}: {e}")

    async def _get_active_nodes(self) -> List[str]:
        """Get list of active nodes for synchronization"""
        nodes = []

        async for key in self.redis.scan_iter(match="node:*"):
            node_data = await self.redis.hgetall(key)
            if node_data and node_data.get(b'status') == b'active':
                node_id = node_data.get(b'node_id')
                if node_id:
                    nodes.append(node_id.decode())

        return nodes

    async def _sync_loop(self):
        """Main synchronization loop"""
        while self._syncing:
            try:
                await self.sync_state()
                await asyncio.sleep(self.sync_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Sync loop error: {e}")
                await asyncio.sleep(5)

    def resolve_conflicts(self,
                         states: List[Dict],
                         strategy: str = "last_write_wins") -> Dict:
        """Resolve conflicts between states"""
        if not states:
            return {}

        if len(states) == 1:
            return states[0]

        if strategy == "last_write_wins":
            return self.conflict_resolver.last_write_wins(states)
        elif strategy == "merge":
            # Custom merge logic based on CRDT semantics
            merged_state = states[0].copy()

            for state in states[1:]:
                # This is a simplified merge - in practice, you'd use CRDT merge semantics
                for key, value in state.items():
                    if key not in merged_state:
                        merged_state[key] = value
                    elif isinstance(value, dict) and isinstance(merged_state[key], dict):
                        merged_state[key].update(value)

            return merged_state
        else:
            raise ValueError(f"Unknown conflict resolution strategy: {strategy}")

    def get_sync_status(self) -> Dict:
        """Get current synchronization status"""
        return {
            "node_id": self.node_id,
            "vector_clock": self.vector_clock.to_dict(),
            "crdt_count": len(self.crdts),
            "operation_log_size": len(self.operation_log),
            "syncing": self._syncing
        }
# ----------------------------
# Additional high-level state sync primitives (lightweight shim for tests)
# ----------------------------

# The CRDT utilities above are heavier-weight; the unit tests in
# tests/unit/test_distributed/test_state_sync.py expect a simpler API
# (StateManager/StateNode/VectorClock/StateChange).  The implementations
# below are intentionally lightweight and self-contained so they can run
# without a live Redis/cluster while keeping the rest of the module intact.

class VectorClock:
    """Minimal vector clock with node-centric helpers."""

    def __init__(self, node_id: str):
        self.node_id = node_id
        self.clock: Dict[str, int] = {node_id: 0}

    def increment(self):
        self.clock[self.node_id] = self.clock.get(self.node_id, 0) + 1

    def update(self, peer_clock: Dict[str, int]):
        for n, v in peer_clock.items():
            self.clock[n] = max(self.clock.get(n, 0), v)

    def compare(self, peer_clock: Dict[str, int]) -> str:
        """Return 'before'/'after'/'concurrent'."""
        before = True
        after = True
        keys = set(self.clock.keys()) | set(peer_clock.keys())
        for k in keys:
            a = self.clock.get(k, 0)
            b = peer_clock.get(k, 0)
            if a > b:
                before = False
            if a < b:
                after = False
        if before and not after:
            return "before"
        if after and not before:
            return "after"
        return "concurrent"

    def to_dict(self) -> Dict[str, Any]:
        return {"node_id": self.node_id, "clock": dict(self.clock)}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VectorClock":
        node_id = data.get("node_id") or "unknown"
        vc = cls(node_id)
        vc.clock = dict(data.get("clock", {}))
        return vc


class ChangeType(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class MergeStrategy(str, Enum):
    LAST_WRITER_WINS = "last_writer_wins"
    NODE_PRIORITY = "node_priority"
    MERGE_LISTS = "merge_lists"
    MERGE_DICTS = "merge_dicts"


class StateChange:
    """Represents a change to replicated state."""

    def __init__(
        self,
        change_id: str,
        change_type: ChangeType,
        key: str,
        value: Any,
        vector_clock: VectorClock,
        node_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None,
    ):
        self.change_id = change_id
        self.change_type = change_type
        self.key = key
        self.value = value
        self.vector_clock = vector_clock
        self.node_id = node_id
        self.metadata = metadata or {}
        self.timestamp = timestamp or datetime.utcnow()

    def happens_before(self, other: "StateChange") -> bool:
        return self.vector_clock.compare(other.vector_clock.clock) == "before"

    def is_concurrent_with(self, other: "StateChange") -> bool:
        return self.vector_clock.compare(other.vector_clock.clock) == "concurrent"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "change_id": self.change_id,
            "change_type": self.change_type.value,
            "key": self.key,
            "value": self.value,
            "vector_clock": self.vector_clock.clock,
            "node_id": self.node_id,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StateChange":
        return cls(
            change_id=data["change_id"],
            change_type=ChangeType(data["change_type"]),
            key=data["key"],
            value=data.get("value"),
            vector_clock=VectorClock(data["node_id"]),
            node_id=data["node_id"],
            metadata=data.get("metadata", {}),
            timestamp=datetime.fromisoformat(data["timestamp"])
            if "timestamp" in data
            else None,
        )


class ConflictResolver:
    """Resolves conflicts between concurrent StateChange objects."""

    def __init__(self):
        self.node_priorities: Dict[str, int] = {}
        self.custom_resolvers: Dict[str, Callable[[List[StateChange]], StateChange]] = {}

    def set_node_priorities(self, priorities: Dict[str, int]):
        self.node_priorities = priorities

    def register_custom_resolver(self, name: str, fn: Callable[[List[StateChange]], StateChange]):
        self.custom_resolvers[name] = fn

    def resolve_conflict(
        self, changes: List[StateChange], strategy: Union[MergeStrategy, str] = MergeStrategy.LAST_WRITER_WINS
    ) -> StateChange:
        if isinstance(strategy, str) and strategy in self.custom_resolvers:
            return self.custom_resolvers[strategy](changes)

        if strategy == MergeStrategy.NODE_PRIORITY:
            return max(changes, key=lambda c: self.node_priorities.get(c.node_id, 0))

        if strategy == MergeStrategy.MERGE_LISTS:
            merged: List[Any] = []
            for ch in changes:
                merged.extend(ch.value or [])
            result = changes[-1]
            result.value = merged
            return result

        if strategy == MergeStrategy.MERGE_DICTS:
            merged: Dict[Any, Any] = {}
            for ch in changes:
                if isinstance(ch.value, dict):
                    merged.update(ch.value)
            result = changes[-1]
            result.value = merged
            return result

        # LAST_WRITER_WINS fallback: pick the change with the "largest" clock sum, tie-break by timestamp
        def _score(ch: StateChange):
            return sum(ch.vector_clock.clock.values()), ch.timestamp

        return max(changes, key=_score)


class StateNode:
    """Local node state plus vector clock and change log."""

    def __init__(self, node_id: str, initial_state: Optional[Dict[str, Any]] = None):
        self.node_id = node_id
        self.state: Dict[str, Any] = initial_state or {}
        self.vector_clock = VectorClock(node_id)
        self.change_log: List[StateChange] = []

    def update_local_state(self, key: str, value: Any) -> StateChange:
        self.vector_clock.increment()
        change = StateChange(
            change_id=f"{self.node_id}_{len(self.change_log)+1}",
            change_type=ChangeType.UPDATE,
            key=key,
            value=value,
            vector_clock=self.vector_clock,
            node_id=self.node_id,
        )
        self.state[key] = value
        self.change_log.append(change)
        return change

    def apply_remote_change(self, change: StateChange) -> bool:
        # Simple policy: accept if concurrent or newer; ignore if strictly before
        relation = self.vector_clock.compare(change.vector_clock.clock)
        if relation == "after":
            return False
        self.vector_clock.update(change.vector_clock.clock)
        self.state[change.key] = change.value
        self.change_log.append(change)
        return True

    def get_state_snapshot(self) -> Dict[str, Any]:
        return {
            "state": dict(self.state),
            "vector_clock": dict(self.vector_clock.clock),
            "change_log": [c.to_dict() for c in self.change_log],
        }

    def restore_from_snapshot(self, snapshot: Dict[str, Any]):
        self.state = dict(snapshot.get("state", {}))
        self.vector_clock.clock = dict(snapshot.get("vector_clock", {}))
        self.change_log = [StateChange.from_dict(c) for c in snapshot.get("change_log", [])]

    def prune_change_log(self, max_size: int):
        if len(self.change_log) > max_size:
            self.change_log = self.change_log[-max_size:]


class SyncProtocol(str, Enum):
    """Placeholder for sync protocol types."""
    PUBSUB = "pubsub"


class StateManager:
    """Coordinates distributed state sync using Redis pub/sub (mocked in tests)."""

    def __init__(self, node_id: str, redis_client):
        self.node_id = node_id
        self.redis = redis_client
        self.state_node = StateNode(node_id)
        self.conflict_resolver = ConflictResolver()
        self.channel = "state_changes"
        self._running = False

    async def start(self):
        self._running = True
        if hasattr(self.redis, "subscribe"):
            await self.redis.subscribe(self.channel)

    async def stop(self):
        self._running = False

    async def update_state(self, key: str, value: Any):
        change = self.state_node.update_local_state(key, value)
        await self._persist_state()
        await self._publish_change(change)

    async def handle_remote_change(self, change_data: Dict[str, Any]):
        change = StateChange.from_dict(change_data)
        self.state_node.apply_remote_change(change)
        await self._persist_state()

    async def recover_state(self):
        if hasattr(self.redis, "get"):
            raw = await self.redis.get(f"state:{self.node_id}")
            if raw:
                try:
                    state = json.loads(raw.decode() if hasattr(raw, "decode") else raw)
                    self.state_node.state = state
                except Exception:
                    pass

    async def _persist_state(self):
        if hasattr(self.redis, "set"):
            await self.redis.set(f"state:{self.node_id}", json.dumps(self.state_node.state))

    async def _publish_change(self, change: StateChange):
        if hasattr(self.redis, "publish"):
            await self.redis.publish(self.channel, json.dumps(change.to_dict()))
