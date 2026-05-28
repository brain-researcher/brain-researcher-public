"""Tests for Distributed Coordinator

Tests leader election, consensus algorithms, node registration,
and cluster management functionality.
"""

import pytest
import asyncio
import json
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, List

import redis.asyncio as redis
from brain_researcher.services.agent.distributed.coordinator import (
    DistributedCoordinator, NodeInfo, ResourceCapacity, NodeStatus,
    HeartbeatManager
)


class TestResourceCapacity:
    """Test resource capacity validation"""
    
    def test_valid_resource_capacity(self):
        """Test valid resource capacity creation"""
        capacity = ResourceCapacity(
            cpu_cores=8,
            memory_gb=32.0,
            gpu_count=2,
            storage_gb=1000.0,
            network_mbps=10000.0
        )
        
        assert capacity.cpu_cores == 8
        assert capacity.memory_gb == 32.0
        assert capacity.gpu_count == 2
        
    def test_negative_cpu_cores_raises_error(self):
        """Test negative CPU cores raises ValueError"""
        with pytest.raises(ValueError, match="CPU cores cannot be negative"):
            ResourceCapacity(cpu_cores=-1, memory_gb=16.0)
            
    def test_negative_memory_raises_error(self):
        """Test negative memory raises ValueError"""
        with pytest.raises(ValueError, match="Memory cannot be negative"):
            ResourceCapacity(cpu_cores=4, memory_gb=-8.0)
            
    def test_default_values(self):
        """Test default values are set correctly"""
        capacity = ResourceCapacity(cpu_cores=4, memory_gb=16.0)
        
        assert capacity.gpu_count == 0
        assert capacity.storage_gb == 0.0
        assert capacity.network_mbps == 1000.0


class TestNodeInfo:
    """Test node information handling"""
    
    def test_node_info_creation(self):
        """Test node info creation with all fields"""
        capacity = ResourceCapacity(cpu_cores=8, memory_gb=32.0)
        node_info = NodeInfo(
            node_id="node1",
            hostname="worker1.cluster.local",
            capacity=capacity,
            status=NodeStatus.ACTIVE,
            leader=True,
            tasks_running=5,
            load_average=2.5
        )
        
        assert node_info.node_id == "node1"
        assert node_info.hostname == "worker1.cluster.local"
        assert node_info.capacity == capacity
        assert node_info.status == NodeStatus.ACTIVE
        assert node_info.leader is True
        assert node_info.tasks_running == 5
        assert node_info.load_average == 2.5
        
    def test_node_info_to_dict(self):
        """Test node info serialization to dictionary"""
        capacity = ResourceCapacity(cpu_cores=4, memory_gb=16.0)
        now = datetime.utcnow()
        
        node_info = NodeInfo(
            node_id="node1",
            hostname="worker1",
            capacity=capacity,
            last_heartbeat=now,
            joined_at=now
        )
        
        data = node_info.to_dict()
        
        assert data['node_id'] == "node1"
        assert data['hostname'] == "worker1"
        assert data['last_heartbeat'] == now.isoformat()
        assert data['joined_at'] == now.isoformat()
        assert 'capacity' in data
        
    def test_node_info_from_dict(self):
        """Test node info deserialization from dictionary"""
        now = datetime.utcnow()
        data = {
            'node_id': 'node1',
            'hostname': 'worker1',
            'capacity': {
                'cpu_cores': 4,
                'memory_gb': 16.0,
                'gpu_count': 1,
                'storage_gb': 500.0,
                'network_mbps': 1000.0
            },
            'status': 'active',
            'leader': False,
            'last_heartbeat': now.isoformat(),
            'joined_at': now.isoformat(),
            'tasks_running': 3,
            'load_average': 1.2
        }
        
        node_info = NodeInfo.from_dict(data)
        
        assert node_info.node_id == "node1"
        assert node_info.hostname == "worker1"
        assert isinstance(node_info.capacity, ResourceCapacity)
        assert node_info.capacity.cpu_cores == 4
        assert node_info.last_heartbeat == now
        assert node_info.joined_at == now


class TestHeartbeatManager:
    """Test heartbeat management functionality"""
    
    @pytest.fixture
    async def redis_mock(self):
        """Mock Redis client for testing"""
        mock_redis = AsyncMock(spec=redis.Redis)
        mock_redis.setex = AsyncMock(return_value=True)
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.delete = AsyncMock(return_value=1)
        return mock_redis
        
    @pytest.fixture
    def heartbeat_manager(self, redis_mock):
        """Create heartbeat manager with mocked Redis"""
        return HeartbeatManager(redis_mock, heartbeat_interval=1)
        
    @pytest.mark.asyncio
    async def test_start_stop_heartbeat(self, heartbeat_manager, redis_mock):
        """Test starting and stopping heartbeat"""
        node_id = "test_node"
        
        # Start heartbeat
        await heartbeat_manager.start_heartbeat(node_id)
        assert heartbeat_manager._running is True
        assert heartbeat_manager._heartbeat_task is not None
        
        # Allow one heartbeat cycle
        await asyncio.sleep(1.1)
        
        # Verify Redis calls were made
        redis_mock.setex.assert_called()
        
        # Stop heartbeat
        await heartbeat_manager.stop_heartbeat()
        assert heartbeat_manager._running is False
        
    @pytest.mark.asyncio
    async def test_heartbeat_sends_data(self, heartbeat_manager, redis_mock):
        """Test heartbeat sends correct data to Redis"""
        node_id = "test_node"
        
        await heartbeat_manager.start_heartbeat(node_id)
        await asyncio.sleep(1.1)
        await heartbeat_manager.stop_heartbeat()
        
        # Verify setex was called with correct key pattern
        calls = redis_mock.setex.call_args_list
        assert len(calls) >= 1
        
        key = calls[0][0][0]
        ttl = calls[0][0][1]
        
        assert f"heartbeat:{node_id}" in key
        assert ttl == heartbeat_manager.heartbeat_timeout
        
    @pytest.mark.asyncio
    async def test_check_node_alive(self, heartbeat_manager, redis_mock):
        """Test checking if node is alive"""
        node_id = "test_node"
        
        # Node alive case
        redis_mock.get.return_value = json.dumps({
            'timestamp': datetime.utcnow().isoformat(),
            'load': 1.5
        }).encode()
        
        is_alive = await heartbeat_manager.is_node_alive(node_id)
        assert is_alive is True
        
        # Node dead case
        redis_mock.get.return_value = None
        is_alive = await heartbeat_manager.is_node_alive(node_id)
        assert is_alive is False


@pytest.mark.asyncio
class TestDistributedCoordinator:
    """Test distributed coordinator functionality"""
    
    @pytest.fixture
    async def redis_mock(self):
        """Mock Redis client"""
        mock_redis = AsyncMock(spec=redis.Redis)
        mock_redis.setnx = AsyncMock(return_value=True)
        mock_redis.setex = AsyncMock(return_value=True)
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.delete = AsyncMock(return_value=1)
        mock_redis.keys = AsyncMock(return_value=[])
        mock_redis.hgetall = AsyncMock(return_value={})
        mock_redis.hset = AsyncMock(return_value=1)
        mock_redis.hdel = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock(return_value=True)
        return mock_redis
        
    @pytest.fixture
    async def coordinator(self, redis_mock):
        """Create coordinator with mocked Redis"""
        coord = DistributedCoordinator("test_coordinator", redis_mock)
        return coord
        
    async def test_coordinator_initialization(self, coordinator):
        """Test coordinator initializes correctly"""
        assert coordinator.node_id == "test_coordinator"
        assert coordinator.cluster_id == "brain_researcher_cluster"
        assert coordinator.leader_id is None
        assert len(coordinator.nodes) == 0
        
    async def test_start_coordinator(self, coordinator, redis_mock):
        """Test starting coordinator"""
        await coordinator.start()
        
        assert coordinator.is_running is True
        assert coordinator._heartbeat_task is not None
        
        # Verify Redis operations
        redis_mock.hset.assert_called()
        
        await coordinator.stop()
        
    async def test_leader_election_single_node(self, coordinator, redis_mock):
        """Test leader election with single node"""
        # Mock successful election
        redis_mock.setnx.return_value = True
        
        await coordinator.start()
        leader_id = await coordinator.elect_leader()
        
        assert leader_id == coordinator.node_id
        assert coordinator.is_leader() is True
        
        await coordinator.stop()
        
    async def test_leader_election_multiple_nodes(self, coordinator, redis_mock):
        """Test leader election with multiple nodes"""
        # Mock failed election (another node is leader)
        redis_mock.setnx.return_value = False
        redis_mock.get.return_value = b"other_node"
        
        await coordinator.start()
        leader_id = await coordinator.elect_leader()
        
        assert leader_id == "other_node"
        assert coordinator.is_leader() is False
        
        await coordinator.stop()
        
    async def test_node_registration(self, coordinator, redis_mock):
        """Test node registration"""
        capacity = ResourceCapacity(cpu_cores=4, memory_gb=16.0)
        node_info = NodeInfo(
            node_id="worker1",
            hostname="worker1.local",
            capacity=capacity
        )
        
        await coordinator.start()
        success = await coordinator.register_node(node_info)
        
        assert success is True
        assert "worker1" in coordinator.nodes
        assert coordinator.nodes["worker1"].status == NodeStatus.ACTIVE
        
        # Verify Redis operations
        redis_mock.hset.assert_called()
        
        await coordinator.stop()
        
    async def test_node_deregistration(self, coordinator, redis_mock):
        """Test node deregistration"""
        # First register a node
        capacity = ResourceCapacity(cpu_cores=4, memory_gb=16.0)
        node_info = NodeInfo(
            node_id="worker1",
            hostname="worker1.local",
            capacity=capacity
        )
        
        await coordinator.start()
        await coordinator.register_node(node_info)
        
        # Then deregister it
        success = await coordinator.deregister_node("worker1")
        
        assert success is True
        assert "worker1" not in coordinator.nodes
        
        # Verify Redis operations
        redis_mock.hdel.assert_called()
        
        await coordinator.stop()
        
    async def test_cluster_status(self, coordinator, redis_mock):
        """Test getting cluster status"""
        # Register a few nodes
        for i in range(3):
            capacity = ResourceCapacity(cpu_cores=4, memory_gb=16.0)
            node_info = NodeInfo(
                node_id=f"worker{i}",
                hostname=f"worker{i}.local",
                capacity=capacity,
                status=NodeStatus.ACTIVE,
                tasks_running=i * 2,
                load_average=1.0 + i * 0.5
            )
            coordinator.nodes[f"worker{i}"] = node_info
            
        status = await coordinator.get_cluster_status()
        
        assert len(status['nodes']) == 3
        assert status['total_capacity']['cpu_cores'] == 12
        assert status['total_capacity']['memory_gb'] == 48.0
        assert status['active_tasks'] == 0 + 2 + 4  # Sum of tasks_running
        
    async def test_consensus_algorithm(self, coordinator, redis_mock):
        """Test consensus algorithm for cluster decisions"""
        # Mock nodes for consensus
        coordinator.nodes = {
            "node1": NodeInfo("node1", "host1", ResourceCapacity(4, 16.0), NodeStatus.ACTIVE),
            "node2": NodeInfo("node2", "host2", ResourceCapacity(4, 16.0), NodeStatus.ACTIVE),
            "node3": NodeInfo("node3", "host3", ResourceCapacity(4, 16.0), NodeStatus.ACTIVE)
        }
        
        # Mock Redis responses for voting
        vote_responses = [b"yes", b"yes", b"no"]  # 2/3 majority
        redis_mock.get.side_effect = vote_responses
        
        proposal = {"action": "scale_up", "target_nodes": 5}
        result = await coordinator.reach_consensus(proposal, timeout=5.0)
        
        assert result['consensus_reached'] is True
        assert result['votes_for'] == 2
        assert result['votes_against'] == 1
        
    async def test_partition_detection(self, coordinator, redis_mock):
        """Test network partition detection"""
        # Add nodes
        coordinator.nodes = {
            "node1": NodeInfo("node1", "host1", ResourceCapacity(4, 16.0), NodeStatus.ACTIVE),
            "node2": NodeInfo("node2", "host2", ResourceCapacity(4, 16.0), NodeStatus.FAILED)
        }
        
        # Mock heartbeat failures
        redis_mock.get.side_effect = [None, None]  # No heartbeats
        
        partition_detected = await coordinator.detect_partition()
        
        assert partition_detected is True
        
    async def test_leader_failover(self, coordinator, redis_mock):
        """Test leader failover scenario"""
        # Initially not leader
        redis_mock.get.return_value = b"old_leader"
        await coordinator.start()
        
        # Simulate leader failure - Redis returns None
        redis_mock.get.return_value = None
        redis_mock.setnx.return_value = True  # We can become leader
        
        # Trigger election
        new_leader = await coordinator.elect_leader()
        
        assert new_leader == coordinator.node_id
        assert coordinator.is_leader() is True
        
        await coordinator.stop()
        
    async def test_cluster_health_monitoring(self, coordinator, redis_mock):
        """Test cluster health monitoring"""
        # Add mix of healthy and unhealthy nodes
        coordinator.nodes = {
            "node1": NodeInfo("node1", "host1", ResourceCapacity(4, 16.0), NodeStatus.ACTIVE),
            "node2": NodeInfo("node2", "host2", ResourceCapacity(4, 16.0), NodeStatus.FAILED),
            "node3": NodeInfo("node3", "host3", ResourceCapacity(4, 16.0), NodeStatus.DRAINING)
        }
        
        health = await coordinator.get_cluster_health()
        
        assert health['total_nodes'] == 3
        assert health['healthy_nodes'] == 1  # Only ACTIVE nodes
        assert health['health_ratio'] == 1/3
        assert health['overall_health'] == 'degraded'
        
    @pytest.mark.parametrize("node_count,expected_quorum", [
        (1, 1),
        (3, 2),
        (5, 3),
        (7, 4),
        (10, 6)
    ])
    async def test_quorum_calculation(self, coordinator, node_count, expected_quorum):
        """Test quorum calculation for different cluster sizes"""
        # Add nodes
        for i in range(node_count):
            coordinator.nodes[f"node{i}"] = NodeInfo(
                f"node{i}", f"host{i}", 
                ResourceCapacity(4, 16.0), 
                NodeStatus.ACTIVE
            )
            
        quorum = coordinator.calculate_quorum()
        assert quorum == expected_quorum
        
    async def test_concurrent_leader_election(self, coordinator, redis_mock):
        """Test concurrent leader election handling"""
        # Simulate race condition
        election_attempts = []
        
        async def mock_setnx_with_delay(key, value):
            await asyncio.sleep(0.1)  # Simulate network delay
            election_attempts.append(coordinator.node_id)
            return len(election_attempts) == 1  # Only first succeeds
        
        redis_mock.setnx.side_effect = mock_setnx_with_delay
        
        # Start multiple election attempts
        tasks = [
            asyncio.create_task(coordinator.elect_leader())
            for _ in range(5)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # First should succeed, others should get existing leader
        successful_elections = [r for r in results if r == coordinator.node_id]
        assert len(successful_elections) <= 1
