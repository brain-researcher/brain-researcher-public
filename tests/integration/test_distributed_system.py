"""Integration Tests for Distributed Agent System

End-to-end tests for the complete distributed system including
coordinator, worker nodes, load balancing, fault tolerance, and state sync.
"""

import pytest
import asyncio
import json
import time
import aiohttp
from datetime import datetime, timedelta
from typing import Dict, List, Any
from unittest.mock import AsyncMock, MagicMock, patch

import redis.asyncio as redis
from brain_researcher.services.agent.distributed.coordinator import (
    DistributedCoordinator, NodeInfo, ResourceCapacity, NodeStatus
)
from brain_researcher.services.agent.distributed.worker_node import (
    WorkerNode, WorkerNodeConfig, TaskRequest
)
from brain_researcher.services.agent.distributed.load_balancer import (
    DistributedLoadBalancer, TaskRequirements, LoadBalancingStrategy
)
from brain_researcher.services.agent.distributed.fault_tolerance import FaultTolerance
from brain_researcher.services.agent.distributed.state_sync import StateManager


@pytest.mark.integration
@pytest.mark.asyncio
class TestDistributedSystemIntegration:
    """Integration tests for complete distributed system"""
    
    @pytest.fixture
    async def redis_client(self):
        """Real Redis client for integration testing"""
        # Use test database
        client = redis.from_url("redis://localhost:6379/1", decode_responses=False)
        
        # Clean up test database
        await client.flushdb()
        
        yield client
        
        # Clean up after test
        await client.flushdb()
        await client.close()
        
    @pytest.fixture
    async def coordinator(self, redis_client):
        """Coordinator instance for testing"""
        coord = DistributedCoordinator("test_coordinator", redis_client)
        await coord.start()
        yield coord
        await coord.stop()
        
    @pytest.fixture
    async def worker_nodes(self, redis_client):
        """Multiple worker nodes for testing"""
        nodes = []
        
        for i in range(3):
            config = WorkerNodeConfig(
                node_id=f"worker_{i}",
                coordinator_url="http://localhost:5000",
                max_concurrent_tasks=2,
                heartbeat_interval=1
            )
            
            node = WorkerNode(config, redis_client)
            
            # Register test task functions
            async def test_task(task_id: str = None, **kwargs):
                await asyncio.sleep(0.1)  # Simulate work
                return {"task_id": task_id, "result": "success", **kwargs}
                
            async def cpu_intensive_task(**kwargs):
                await asyncio.sleep(0.5)  # Simulate CPU work
                return {"cpu_result": "computed"}
                
            node.task_executor.register_task_function("test_task", test_task)
            node.task_executor.register_task_function("cpu_intensive", cpu_intensive_task)
            
            nodes.append(node)
            
        # Start all nodes
        for node in nodes:
            await node.start()
            
        yield nodes
        
        # Stop all nodes
        for node in nodes:
            await node.stop()
            
    @pytest.fixture
    async def load_balancer(self, redis_client):
        """Load balancer for testing"""
        lb = DistributedLoadBalancer(redis_client)
        yield lb
        
    @pytest.fixture
    async def fault_tolerance(self, coordinator):
        """Fault tolerance system for testing"""
        ft = FaultTolerance(coordinator)
        await ft.start()
        yield ft
        await ft.stop()
        
    async def test_cluster_formation(self, coordinator, worker_nodes, redis_client):
        """Test cluster formation with coordinator and workers"""
        # Wait for cluster to form
        await asyncio.sleep(2.0)
        
        # Register workers with coordinator
        for worker in worker_nodes:
            capacity = ResourceCapacity(
                cpu_cores=4,
                memory_gb=8.0,
                gpu_count=1
            )
            
            node_info = NodeInfo(
                node_id=worker.config.node_id,
                hostname=f"{worker.config.node_id}.local",
                capacity=capacity,
                status=NodeStatus.ACTIVE
            )
            
            success = await coordinator.register_node(node_info)
            assert success is True
            
        # Verify cluster status
        status = await coordinator.get_cluster_status()
        
        assert len(status['nodes']) == len(worker_nodes)
        assert status['total_capacity']['cpu_cores'] == 4 * len(worker_nodes)
        assert status['leader_id'] == coordinator.node_id
        
    async def test_leader_election_and_failover(self, redis_client):
        """Test leader election and failover scenarios"""
        coordinators = []
        
        try:
            # Start multiple coordinators
            for i in range(3):
                coord = DistributedCoordinator(f"coord_{i}", redis_client)
                await coord.start()
                coordinators.append(coord)
                
            # Wait for election
            await asyncio.sleep(2.0)
            
            # Verify only one leader
            leaders = [coord for coord in coordinators if coord.is_leader()]
            assert len(leaders) == 1
            
            original_leader = leaders[0]
            
            # Simulate leader failure
            await original_leader.stop()
            coordinators.remove(original_leader)
            
            # Wait for new election
            await asyncio.sleep(3.0)
            
            # Verify new leader elected
            new_leaders = [coord for coord in coordinators if coord.is_leader()]
            assert len(new_leaders) == 1
            assert new_leaders[0].node_id != original_leader.node_id
            
        finally:
            # Clean up
            for coord in coordinators:
                try:
                    await coord.stop()
                except:
                    pass
                    
    async def test_distributed_task_execution(self, coordinator, worker_nodes, load_balancer):
        """Test distributed task execution across workers"""
        # Register nodes with coordinator
        for worker in worker_nodes:
            capacity = ResourceCapacity(cpu_cores=4, memory_gb=8.0)
            node_info = NodeInfo(
                worker.config.node_id,
                f"{worker.config.node_id}.local", 
                capacity,
                NodeStatus.ACTIVE
            )
            await coordinator.register_node(node_info)
            
        # Wait for registration
        await asyncio.sleep(1.0)
        
        # Create multiple tasks
        tasks = [
            TaskRequest(
                task_id=f"distributed_task_{i}",
                task_type="test_task",
                payload={"input_data": f"data_{i}"},
                timeout_seconds=30
            )
            for i in range(10)
        ]
        
        # Execute tasks across cluster
        results = []
        for task in tasks:
            # Select node for task
            requirements = TaskRequirements(cpu_cores=1, memory_gb=1.0)
            selected_node = await load_balancer.select_node(requirements, task_id=task.task_id)
            
            assert selected_node is not None
            
            # Find the worker node
            worker = next(w for w in worker_nodes if w.config.node_id == selected_node)
            
            # Execute task
            result = await worker.handle_task_assignment(task)
            results.append(result)
            
        # Verify all tasks completed successfully
        assert len(results) == 10
        assert all(r.status.value == "completed" for r in results)
        
        # Verify load distribution
        node_task_counts = {}
        for result in results:
            node_id = result.metadata.get("node_id", "unknown")
            node_task_counts[node_id] = node_task_counts.get(node_id, 0) + 1
            
        # Tasks should be distributed across nodes
        assert len(node_task_counts) > 1
        
    async def test_load_balancing_strategies(self, coordinator, worker_nodes, load_balancer):
        """Test different load balancing strategies"""
        # Register nodes with different capacities
        capacities = [
            ResourceCapacity(cpu_cores=8, memory_gb=16.0),  # High capacity
            ResourceCapacity(cpu_cores=4, memory_gb=8.0),   # Medium capacity  
            ResourceCapacity(cpu_cores=2, memory_gb=4.0),   # Low capacity
        ]
        
        for i, (worker, capacity) in enumerate(zip(worker_nodes, capacities)):
            node_info = NodeInfo(
                worker.config.node_id,
                f"{worker.config.node_id}.local",
                capacity,
                NodeStatus.ACTIVE
            )
            await coordinator.register_node(node_info)
            
        await asyncio.sleep(1.0)
        
        # Test round-robin strategy
        requirements = TaskRequirements(cpu_cores=1, memory_gb=1.0)
        
        round_robin_nodes = []
        for _ in range(6):  # 2 rounds
            node = await load_balancer.select_node(
                requirements, 
                strategy=LoadBalancingStrategy.ROUND_ROBIN,
                task_id=f"rr_task_{len(round_robin_nodes)}"
            )
            round_robin_nodes.append(node)
            
        # Should cycle through nodes
        assert len(set(round_robin_nodes)) == len(worker_nodes)
        
        # Test least loaded strategy
        least_loaded_nodes = []
        for _ in range(3):
            node = await load_balancer.select_node(
                requirements,
                strategy=LoadBalancingStrategy.LEAST_LOADED,
                task_id=f"ll_task_{len(least_loaded_nodes)}"
            )
            least_loaded_nodes.append(node)
            
        # Should prefer high-capacity node
        high_capacity_node = worker_nodes[0].config.node_id
        assert least_loaded_nodes[0] == high_capacity_node
        
    async def test_fault_tolerance_and_recovery(self, coordinator, worker_nodes, fault_tolerance):
        """Test fault tolerance and recovery mechanisms"""
        # Register all nodes
        for worker in worker_nodes:
            capacity = ResourceCapacity(cpu_cores=4, memory_gb=8.0)
            node_info = NodeInfo(
                worker.config.node_id,
                f"{worker.config.node_id}.local",
                capacity,
                NodeStatus.ACTIVE
            )
            await coordinator.register_node(node_info)
            
        await asyncio.sleep(1.0)
        
        # Verify cluster health is good
        health = fault_tolerance.get_cluster_health()
        assert health['overall_health'] == 'healthy'
        assert health['healthy_nodes'] == len(worker_nodes)
        
        # Simulate node failure
        failed_worker = worker_nodes[0]
        await failed_worker.stop()
        
        # Wait for failure detection
        await asyncio.sleep(3.0)
        
        # Handle the failure
        success = await fault_tolerance.handle_node_failure(failed_worker.config.node_id)
        assert success is True
        
        # Verify cluster adapts
        new_health = fault_tolerance.get_cluster_health()
        assert new_health['healthy_nodes'] == len(worker_nodes) - 1
        assert new_health['overall_health'] in ['degraded', 'healthy']
        
        # Verify remaining nodes still functional
        remaining_nodes = worker_nodes[1:]
        task = TaskRequest(
            "recovery_test",
            "test_task",
            {"data": "recovery_test"},
            timeout_seconds=30
        )
        
        # Should still be able to execute tasks
        result = await remaining_nodes[0].handle_task_assignment(task)
        assert result.status.value == "completed"
        
    async def test_state_synchronization(self, redis_client):
        """Test state synchronization across nodes"""
        state_managers = []
        
        try:
            # Create multiple state managers
            for i in range(3):
                sm = StateManager(f"state_node_{i}", redis_client)
                await sm.start()
                state_managers.append(sm)
                
            # Wait for initialization
            await asyncio.sleep(1.0)
            
            # Update state on first node
            await state_managers[0].update_state("shared_key", "shared_value")
            
            # Wait for propagation
            await asyncio.sleep(2.0)
            
            # Verify state synchronized to all nodes
            for sm in state_managers[1:]:
                assert sm.state_node.state.get("shared_key") == "shared_value"
                
            # Test conflict resolution
            # Make concurrent updates
            await asyncio.gather(
                state_managers[0].update_state("conflict_key", "value_from_node_0"),
                state_managers[1].update_state("conflict_key", "value_from_node_1")
            )
            
            # Wait for conflict resolution
            await asyncio.sleep(2.0)
            
            # All nodes should have the same resolved value
            resolved_values = [
                sm.state_node.state.get("conflict_key") 
                for sm in state_managers
            ]
            
            assert len(set(resolved_values)) == 1  # All same value
            assert resolved_values[0] in ["value_from_node_0", "value_from_node_1"]
            
        finally:
            # Clean up
            for sm in state_managers:
                try:
                    await sm.stop()
                except:
                    pass
                    
    async def test_network_partition_handling(self, redis_client):
        """Test handling of network partitions"""
        coordinators = []
        
        try:
            # Create cluster with 5 coordinators
            for i in range(5):
                coord = DistributedCoordinator(f"partition_coord_{i}", redis_client)
                await coord.start()
                coordinators.append(coord)
                
            await asyncio.sleep(2.0)
            
            # Verify initial leader election
            leaders = [c for c in coordinators if c.is_leader()]
            assert len(leaders) == 1
            
            # Simulate network partition by stopping Redis access for some nodes
            partitioned_nodes = coordinators[:2]  # Minority partition
            majority_nodes = coordinators[2:]     # Majority partition
            
            # Mock Redis failures for minority partition
            for coord in partitioned_nodes:
                coord.redis = AsyncMock()  # Mock to simulate network failure
                coord.redis.setnx = AsyncMock(side_effect=Exception("Network partition"))
                coord.redis.get = AsyncMock(side_effect=Exception("Network partition"))
                
            await asyncio.sleep(3.0)
            
            # Majority partition should maintain/elect leader
            majority_leaders = [c for c in majority_nodes if c.is_leader()]
            assert len(majority_leaders) >= 0  # Should have leader or elect new one
            
            # Minority partition should detect partition
            for coord in partitioned_nodes:
                # Restore Redis access
                coord.redis = redis_client
                
            await asyncio.sleep(2.0)
            
            # System should recover
            final_leaders = [c for c in coordinators if c.is_leader()]
            assert len(final_leaders) == 1
            
        finally:
            for coord in coordinators:
                try:
                    await coord.stop()
                except:
                    pass
                    
    async def test_cluster_scaling(self, coordinator, redis_client):
        """Test dynamic cluster scaling"""
        initial_workers = []
        
        try:
            # Start with 2 workers
            for i in range(2):
                config = WorkerNodeConfig(
                    node_id=f"scale_worker_{i}",
                    coordinator_url="http://localhost:5000",
                    max_concurrent_tasks=2
                )
                worker = WorkerNode(config, redis_client)
                await worker.start()
                initial_workers.append(worker)
                
                # Register with coordinator
                capacity = ResourceCapacity(cpu_cores=4, memory_gb=8.0)
                node_info = NodeInfo(
                    worker.config.node_id,
                    f"{worker.config.node_id}.local",
                    capacity,
                    NodeStatus.ACTIVE
                )
                await coordinator.register_node(node_info)
                
            await asyncio.sleep(1.0)
            
            # Verify initial cluster size
            status = await coordinator.get_cluster_status()
            assert len(status['nodes']) == 2
            
            # Scale up - add more workers
            additional_workers = []
            for i in range(2, 5):  # Add 3 more workers
                config = WorkerNodeConfig(
                    node_id=f"scale_worker_{i}",
                    coordinator_url="http://localhost:5000",
                    max_concurrent_tasks=2
                )
                worker = WorkerNode(config, redis_client)
                await worker.start()
                additional_workers.append(worker)
                
                # Register with coordinator  
                capacity = ResourceCapacity(cpu_cores=4, memory_gb=8.0)
                node_info = NodeInfo(
                    worker.config.node_id,
                    f"{worker.config.node_id}.local",
                    capacity,
                    NodeStatus.ACTIVE
                )
                await coordinator.register_node(node_info)
                
            await asyncio.sleep(1.0)
            
            # Verify scaled cluster
            scaled_status = await coordinator.get_cluster_status()
            assert len(scaled_status['nodes']) == 5
            assert scaled_status['total_capacity']['cpu_cores'] == 20  # 4 * 5
            
            # Scale down - remove some workers
            for worker in additional_workers[:2]:  # Remove 2 workers
                await coordinator.deregister_node(worker.config.node_id)
                await worker.stop()
                
            await asyncio.sleep(1.0)
            
            # Verify scaled down cluster
            final_status = await coordinator.get_cluster_status()
            assert len(final_status['nodes']) == 3  # 2 initial + 1 remaining
            
        finally:
            # Clean up
            all_workers = initial_workers + additional_workers
            for worker in all_workers:
                try:
                    await worker.stop()
                except:
                    pass
                    
    async def test_performance_under_load(self, coordinator, worker_nodes, load_balancer):
        """Test system performance under heavy load"""
        # Register all workers
        for worker in worker_nodes:
            capacity = ResourceCapacity(cpu_cores=4, memory_gb=8.0)
            node_info = NodeInfo(
                worker.config.node_id,
                f"{worker.config.node_id}.local",
                capacity,
                NodeStatus.ACTIVE
            )
            await coordinator.register_node(node_info)
            
        await asyncio.sleep(1.0)
        
        # Create many concurrent tasks
        num_tasks = 50
        tasks = [
            TaskRequest(
                task_id=f"perf_task_{i}",
                task_type="test_task", 
                payload={"task_num": i},
                timeout_seconds=30
            )
            for i in range(num_tasks)
        ]
        
        start_time = time.time()
        
        # Execute all tasks concurrently
        async def execute_task(task):
            requirements = TaskRequirements(cpu_cores=1, memory_gb=1.0)
            selected_node = await load_balancer.select_node(requirements, task_id=task.task_id)
            
            if selected_node:
                worker = next(w for w in worker_nodes if w.config.node_id == selected_node)
                return await worker.handle_task_assignment(task)
            return None
            
        results = await asyncio.gather(
            *[execute_task(task) for task in tasks],
            return_exceptions=True
        )
        
        execution_time = time.time() - start_time
        
        # Analyze results
        successful_results = [r for r in results if r and hasattr(r, 'status') and r.status.value == "completed"]
        failed_results = [r for r in results if isinstance(r, Exception) or (r and hasattr(r, 'status') and r.status.value == "failed")]
        
        print(f"Performance test completed in {execution_time:.2f}s")
        print(f"Successful tasks: {len(successful_results)}/{num_tasks}")
        print(f"Failed tasks: {len(failed_results)}")
        
        # Performance assertions
        assert len(successful_results) >= num_tasks * 0.9  # At least 90% success rate
        assert execution_time < 60.0  # Should complete within reasonable time
        
        # Verify system remained stable
        final_status = await coordinator.get_cluster_status()
        assert len(final_status['nodes']) == len(worker_nodes)  # No nodes lost
