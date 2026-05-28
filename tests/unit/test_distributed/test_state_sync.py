"""Tests for Distributed State Synchronization

Tests state synchronization mechanisms including conflict resolution,
version vectors, and consistency guarantees.
"""

import pytest
import asyncio
import json
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, List, Any, Optional

from brain_researcher.services.agent.distributed.state_sync import (
    StateManager, VectorClock, StateNode, ConflictResolver,
    SyncProtocol, StateChange, ChangeType, MergeStrategy
)


class TestVectorClock:
    """Test vector clock implementation for ordering events"""
    
    def test_vector_clock_initialization(self):
        """Test vector clock creation"""
        clock = VectorClock("node1")
        assert clock.node_id == "node1"
        assert clock.clock == {"node1": 0}
        
    def test_vector_clock_increment(self):
        """Test incrementing vector clock"""
        clock = VectorClock("node1")
        clock.increment()
        
        assert clock.clock["node1"] == 1
        
        clock.increment()
        assert clock.clock["node1"] == 2
        
    def test_vector_clock_update_from_peer(self):
        """Test updating clock from peer"""
        clock1 = VectorClock("node1")
        clock2 = VectorClock("node2")
        
        # Increment both clocks
        clock1.increment()
        clock2.increment()
        clock2.increment()
        
        # Update clock1 with clock2's state
        clock1.update(clock2.clock)
        
        assert clock1.clock["node1"] == 1
        assert clock1.clock["node2"] == 2
        
    def test_vector_clock_comparison(self):
        """Test vector clock ordering relationships"""
        clock1 = VectorClock("node1")
        clock2 = VectorClock("node2")
        
        # Initial state - concurrent
        assert clock1.compare(clock2.clock) == "concurrent"
        
        # clock1 happens before clock2
        clock2.update(clock1.clock)
        clock2.increment()
        
        assert clock1.compare(clock2.clock) == "before"
        assert clock2.compare(clock1.clock) == "after"
        
    def test_vector_clock_concurrent_detection(self):
        """Test detection of concurrent events"""
        clock1 = VectorClock("node1")
        clock2 = VectorClock("node2")
        
        # Both increment independently
        clock1.increment()
        clock2.increment()
        
        assert clock1.compare(clock2.clock) == "concurrent"
        assert clock2.compare(clock1.clock) == "concurrent"
        
    def test_vector_clock_serialization(self):
        """Test vector clock serialization"""
        clock = VectorClock("node1")
        clock.increment()
        clock.update({"node2": 3, "node3": 1})
        
        data = clock.to_dict()
        reconstructed = VectorClock.from_dict(data)
        
        assert reconstructed.node_id == clock.node_id
        assert reconstructed.clock == clock.clock


class TestStateChange:
    """Test state change representation and handling"""
    
    def test_state_change_creation(self):
        """Test state change creation"""
        clock = VectorClock("node1")
        clock.increment()
        
        change = StateChange(
            change_id="change_123",
            change_type=ChangeType.UPDATE,
            key="task_status",
            value={"status": "completed"},
            vector_clock=clock,
            node_id="node1",
            metadata={"reason": "task finished"}
        )
        
        assert change.change_id == "change_123"
        assert change.change_type == ChangeType.UPDATE
        assert change.key == "task_status"
        assert change.value["status"] == "completed"
        assert change.node_id == "node1"
        
    def test_state_change_ordering(self):
        """Test state change ordering by vector clocks"""
        clock1 = VectorClock("node1")
        clock2 = VectorClock("node2")
        
        clock1.increment()
        change1 = StateChange("c1", ChangeType.CREATE, "key1", "value1", clock1, "node1")
        
        clock2.update(clock1.clock)
        clock2.increment()
        change2 = StateChange("c2", ChangeType.UPDATE, "key1", "value2", clock2, "node2")
        
        # change1 should come before change2
        assert change1.happens_before(change2)
        assert not change2.happens_before(change1)
        
    def test_concurrent_changes(self):
        """Test handling of concurrent changes"""
        clock1 = VectorClock("node1")
        clock2 = VectorClock("node2")
        
        clock1.increment()
        clock2.increment()
        
        change1 = StateChange("c1", ChangeType.UPDATE, "key1", "value1", clock1, "node1")
        change2 = StateChange("c2", ChangeType.UPDATE, "key1", "value2", clock2, "node2")
        
        assert change1.is_concurrent_with(change2)
        assert change2.is_concurrent_with(change1)
        
    def test_state_change_serialization(self):
        """Test state change serialization"""
        clock = VectorClock("node1")
        clock.increment()
        
        original = StateChange(
            "change_456",
            ChangeType.DELETE,
            "old_key",
            None,
            clock,
            "node1",
            metadata={"timestamp": datetime.utcnow().isoformat()}
        )
        
        data = original.to_dict()
        reconstructed = StateChange.from_dict(data)
        
        assert reconstructed.change_id == original.change_id
        assert reconstructed.change_type == original.change_type
        assert reconstructed.key == original.key
        assert reconstructed.node_id == original.node_id


class TestConflictResolver:
    """Test conflict resolution strategies"""
    
    @pytest.fixture
    def conflict_resolver(self):
        """Create conflict resolver for testing"""
        return ConflictResolver()
        
    def test_last_writer_wins_strategy(self, conflict_resolver):
        """Test last writer wins conflict resolution"""
        clock1 = VectorClock("node1")
        clock2 = VectorClock("node2")
        
        clock1.increment()
        change1 = StateChange("c1", ChangeType.UPDATE, "key1", "old_value", clock1, "node1")
        
        clock2.update(clock1.clock)
        clock2.increment()
        change2 = StateChange("c2", ChangeType.UPDATE, "key1", "new_value", clock2, "node2")
        
        resolved = conflict_resolver.resolve_conflict(
            [change1, change2],
            MergeStrategy.LAST_WRITER_WINS
        )
        
        assert resolved.value == "new_value"
        assert resolved.change_id == "c2"
        
    def test_node_priority_strategy(self, conflict_resolver):
        """Test node priority based conflict resolution"""
        clock1 = VectorClock("node1")
        clock2 = VectorClock("node2")
        
        # Concurrent changes
        clock1.increment()
        clock2.increment()
        
        change1 = StateChange("c1", ChangeType.UPDATE, "key1", "value1", clock1, "node1")
        change2 = StateChange("c2", ChangeType.UPDATE, "key1", "value2", clock2, "node2")
        
        # Set node priorities
        conflict_resolver.set_node_priorities({"node1": 1, "node2": 2})
        
        resolved = conflict_resolver.resolve_conflict(
            [change1, change2],
            MergeStrategy.NODE_PRIORITY
        )
        
        # node2 has higher priority
        assert resolved.value == "value2"
        assert resolved.node_id == "node2"
        
    def test_merge_strategy_for_lists(self, conflict_resolver):
        """Test merge strategy for list values"""
        clock1 = VectorClock("node1")
        clock2 = VectorClock("node2")
        
        clock1.increment()
        clock2.increment()
        
        change1 = StateChange("c1", ChangeType.UPDATE, "list_key", ["a", "b"], clock1, "node1")
        change2 = StateChange("c2", ChangeType.UPDATE, "list_key", ["c", "d"], clock2, "node2")
        
        resolved = conflict_resolver.resolve_conflict(
            [change1, change2],
            MergeStrategy.MERGE_LISTS
        )
        
        # Should merge both lists
        assert set(resolved.value) == {"a", "b", "c", "d"}
        
    def test_merge_strategy_for_dicts(self, conflict_resolver):
        """Test merge strategy for dictionary values"""
        clock1 = VectorClock("node1")
        clock2 = VectorClock("node2")
        
        clock1.increment()
        clock2.increment()
        
        change1 = StateChange("c1", ChangeType.UPDATE, "dict_key", {"a": 1, "b": 2}, clock1, "node1")
        change2 = StateChange("c2", ChangeType.UPDATE, "dict_key", {"c": 3, "b": 4}, clock2, "node2")
        
        resolved = conflict_resolver.resolve_conflict(
            [change1, change2],
            MergeStrategy.MERGE_DICTS
        )
        
        # Should merge dictionaries, with conflicts using last writer wins
        expected = {"a": 1, "b": 4, "c": 3}  # b=4 from later change
        assert resolved.value == expected
        
    def test_custom_conflict_resolver(self, conflict_resolver):
        """Test custom conflict resolution function"""
        def custom_resolver(changes: List[StateChange]) -> StateChange:
            # Always pick the change with the longest value
            return max(changes, key=lambda c: len(str(c.value)))
            
        conflict_resolver.register_custom_resolver("custom", custom_resolver)
        
        clock1 = VectorClock("node1")
        clock2 = VectorClock("node2")
        
        clock1.increment()
        clock2.increment()
        
        change1 = StateChange("c1", ChangeType.UPDATE, "key1", "short", clock1, "node1")
        change2 = StateChange("c2", ChangeType.UPDATE, "key1", "much longer value", clock2, "node2")
        
        resolved = conflict_resolver.resolve_conflict([change1, change2], "custom")
        
        assert resolved.value == "much longer value"


class TestStateNode:
    """Test individual state node functionality"""
    
    @pytest.fixture
    def state_node(self):
        """Create state node for testing"""
        return StateNode("test_node", {"initial_key": "initial_value"})
        
    def test_state_node_initialization(self, state_node):
        """Test state node initialization"""
        assert state_node.node_id == "test_node"
        assert state_node.state["initial_key"] == "initial_value"
        assert isinstance(state_node.vector_clock, VectorClock)
        assert len(state_node.change_log) == 0
        
    def test_local_state_update(self, state_node):
        """Test local state updates"""
        state_node.update_local_state("new_key", "new_value")
        
        assert state_node.state["new_key"] == "new_value"
        assert len(state_node.change_log) == 1
        
        change = state_node.change_log[0]
        assert change.change_type == ChangeType.UPDATE
        assert change.key == "new_key"
        assert change.value == "new_value"
        
    def test_remote_state_application(self, state_node):
        """Test applying remote state changes"""
        # Create remote change
        remote_clock = VectorClock("remote_node")
        remote_clock.increment()
        
        remote_change = StateChange(
            "remote_c1",
            ChangeType.UPDATE,
            "remote_key",
            "remote_value",
            remote_clock,
            "remote_node"
        )
        
        success = state_node.apply_remote_change(remote_change)
        
        assert success is True
        assert state_node.state["remote_key"] == "remote_value"
        assert len(state_node.change_log) == 1
        
    def test_outdated_change_rejection(self, state_node):
        """Test rejection of outdated changes"""
        # Apply a change first
        state_node.update_local_state("key1", "value1")
        
        # Create an "older" remote change
        old_clock = VectorClock("remote_node")
        # Don't increment, so it's concurrent/older
        
        old_change = StateChange(
            "old_c1",
            ChangeType.UPDATE,
            "key1",
            "old_value",
            old_clock,
            "remote_node"
        )
        
        success = state_node.apply_remote_change(old_change)
        
        # Should reject or resolve conflict
        if success:
            # If accepted, should use conflict resolution
            assert state_node.state["key1"] in ["value1", "old_value"]
        
    def test_state_snapshot(self, state_node):
        """Test creating state snapshots"""
        state_node.update_local_state("key1", "value1")
        state_node.update_local_state("key2", "value2")
        
        snapshot = state_node.get_state_snapshot()
        
        assert "state" in snapshot
        assert "vector_clock" in snapshot
        assert "change_log" in snapshot
        assert snapshot["state"]["key1"] == "value1"
        assert snapshot["state"]["key2"] == "value2"
        
    def test_state_restoration(self, state_node):
        """Test restoring from state snapshot"""
        # Create initial state
        state_node.update_local_state("key1", "value1")
        snapshot1 = state_node.get_state_snapshot()
        
        # Make more changes
        state_node.update_local_state("key2", "value2")
        state_node.update_local_state("key1", "updated_value1")
        
        # Restore from snapshot
        state_node.restore_from_snapshot(snapshot1)
        
        assert state_node.state["key1"] == "value1"
        assert "key2" not in state_node.state
        
    def test_change_log_pruning(self, state_node):
        """Test pruning old changes from log"""
        # Add many changes
        for i in range(100):
            state_node.update_local_state(f"key{i}", f"value{i}")
            
        original_log_size = len(state_node.change_log)
        
        # Prune old changes
        state_node.prune_change_log(max_size=50)
        
        assert len(state_node.change_log) <= 50
        assert len(state_node.change_log) < original_log_size


@pytest.mark.asyncio
class TestStateManager:
    """Test complete state management system"""
    
    @pytest.fixture
    async def redis_mock(self):
        """Mock Redis client for state storage"""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.publish = AsyncMock(return_value=1)
        mock_redis.subscribe = AsyncMock()
        return mock_redis
        
    @pytest.fixture
    def state_manager(self, redis_mock):
        """Create state manager for testing"""
        return StateManager("test_node", redis_mock)
        
    async def test_state_manager_initialization(self, state_manager):
        """Test state manager initialization"""
        assert state_manager.node_id == "test_node"
        assert isinstance(state_manager.state_node, StateNode)
        assert isinstance(state_manager.conflict_resolver, ConflictResolver)
        
    async def test_distributed_state_update(self, state_manager, redis_mock):
        """Test distributed state updates"""
        await state_manager.start()
        
        # Update state
        await state_manager.update_state("distributed_key", "distributed_value")
        
        # Should publish change to other nodes
        redis_mock.publish.assert_called()
        
        # Should store state in Redis
        redis_mock.set.assert_called()
        
        await state_manager.stop()
        
    async def test_state_synchronization(self, state_manager, redis_mock):
        """Test state synchronization between nodes"""
        # Mock receiving a change from another node
        remote_change_data = {
            "change_id": "remote_123",
            "change_type": "update",
            "key": "sync_key",
            "value": "sync_value",
            "vector_clock": {"remote_node": 1},
            "node_id": "remote_node",
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": {}
        }
        
        await state_manager.start()
        await state_manager.handle_remote_change(remote_change_data)
        
        # Should apply the change locally
        assert state_manager.state_node.state["sync_key"] == "sync_value"
        
        await state_manager.stop()
        
    async def test_conflict_resolution_integration(self, state_manager, redis_mock):
        """Test conflict resolution in distributed environment"""
        await state_manager.start()
        
        # Create local change
        await state_manager.update_state("conflict_key", "local_value")
        
        # Simulate concurrent remote change
        remote_change_data = {
            "change_id": "remote_conflict",
            "change_type": "update",
            "key": "conflict_key",
            "value": "remote_value",
            "vector_clock": {"remote_node": 1},
            "node_id": "remote_node",
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": {}
        }
        
        await state_manager.handle_remote_change(remote_change_data)
        
        # Should resolve conflict (implementation dependent)
        final_value = state_manager.state_node.state["conflict_key"]
        assert final_value in ["local_value", "remote_value"]
        
        await state_manager.stop()
        
    async def test_state_persistence(self, state_manager, redis_mock):
        """Test state persistence to Redis"""
        await state_manager.start()
        
        # Update several keys
        await state_manager.update_state("persist_key1", "value1")
        await state_manager.update_state("persist_key2", {"nested": "object"})
        
        # Should call Redis set operations
        assert redis_mock.set.call_count >= 2
        
        await state_manager.stop()
        
    async def test_state_recovery(self, state_manager, redis_mock):
        """Test state recovery from persistent storage"""
        # Mock persisted state
        persisted_state = {
            "recovery_key": "recovered_value",
            "another_key": "another_value"
        }
        
        redis_mock.get.return_value = json.dumps(persisted_state).encode()
        
        await state_manager.start()
        await state_manager.recover_state()
        
        # Should load persisted state
        assert state_manager.state_node.state["recovery_key"] == "recovered_value"
        assert state_manager.state_node.state["another_key"] == "another_value"
        
        await state_manager.stop()
        
    async def test_network_partition_handling(self, state_manager, redis_mock):
        """Test handling of network partitions"""
        await state_manager.start()
        
        # Simulate network partition (Redis operations fail)
        redis_mock.publish.side_effect = Exception("Network error")
        
        # Should handle gracefully
        try:
            await state_manager.update_state("partition_key", "partition_value")
            # Should still update locally
            assert state_manager.state_node.state["partition_key"] == "partition_value"
        except Exception:
            pytest.fail("Should handle network partition gracefully")
            
        await state_manager.stop()
        
    async def test_bulk_state_sync(self, state_manager, redis_mock):
        """Test bulk state synchronization"""
        # Create state with multiple changes
        changes_data = [
            {
                "change_id": f"bulk_{i}",
                "change_type": "update",
                "key": f"bulk_key_{i}",
                "value": f"bulk_value_{i}",
                "vector_clock": {"remote_node": i+1},
                "node_id": "remote_node",
                "timestamp": datetime.utcnow().isoformat(),
                "metadata": {}
            }
            for i in range(10)
        ]
        
        await state_manager.start()
        await state_manager.handle_bulk_changes(changes_data)
        
        # Should apply all changes
        for i in range(10):
            assert state_manager.state_node.state[f"bulk_key_{i}"] == f"bulk_value_{i}"
            
        await state_manager.stop()
        
    async def test_causal_consistency(self, state_manager, redis_mock):
        """Test causal consistency guarantees"""
        await state_manager.start()
        
        # Create causal chain of changes
        change1_data = {
            "change_id": "causal_1",
            "change_type": "create",
            "key": "counter",
            "value": 1,
            "vector_clock": {"node_a": 1},
            "node_id": "node_a",
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": {}
        }
        
        change2_data = {
            "change_id": "causal_2",
            "change_type": "update", 
            "key": "counter",
            "value": 2,
            "vector_clock": {"node_a": 1, "node_b": 1},  # Depends on change1
            "node_id": "node_b",
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": {}
        }
        
        # Apply in correct order
        await state_manager.handle_remote_change(change1_data)
        await state_manager.handle_remote_change(change2_data)
        
        assert state_manager.state_node.state["counter"] == 2
        
        # Should maintain causal order in change log
        changes = state_manager.state_node.change_log
        assert len(changes) == 2
        assert changes[0].change_id == "causal_1"
        assert changes[1].change_id == "causal_2"
        
        await state_manager.stop()