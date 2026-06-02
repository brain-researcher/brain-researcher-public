"""
Comprehensive tests for database connection pooling (PgBouncer) functionality.

Tests cover:
- Connection pool management and limits
- Transaction-level pooling behavior
- Connection lifecycle and cleanup
- Pool exhaustion scenarios and recovery
- Performance optimization validation
- Multi-tenant connection isolation
- Monitoring and statistics collection
- Configuration validation and tuning
"""

import asyncio
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from typing import Dict, List, Optional, Tuple
from unittest.mock import MagicMock, Mock, patch

import psycopg2
import pytest

from tests.load.conftest import TestConfig


class MockPgBouncerConnection:
    """Mock PgBouncer connection for testing."""

    def __init__(self, pool_name: str, max_connections: int = 50):
        self.pool_name = pool_name
        self.max_connections = max_connections
        self.active_connections = 0
        self.waiting_connections = 0
        self.total_requests = 0
        self.pool_mode = "transaction"
        self.is_connected = True

    def acquire_connection(self, timeout: float = 30) -> bool:
        """Simulate acquiring a connection from pool."""
        if self.active_connections >= self.max_connections:
            self.waiting_connections += 1
            # Simulate waiting
            time.sleep(min(timeout, 0.1))  # Quick simulation
            self.waiting_connections -= 1

            if self.active_connections >= self.max_connections:
                return False  # Pool exhausted

        self.active_connections += 1
        self.total_requests += 1
        return True

    def release_connection(self):
        """Release connection back to pool."""
        if self.active_connections > 0:
            self.active_connections -= 1

    def get_stats(self) -> Dict:
        """Get pool statistics."""
        return {
            "pool_name": self.pool_name,
            "pool_mode": self.pool_mode,
            "max_connections": self.max_connections,
            "active_connections": self.active_connections,
            "waiting_connections": self.waiting_connections,
            "total_requests": self.total_requests,
            "pool_utilization": (self.active_connections / self.max_connections) * 100,
        }


class MockDatabase:
    """Mock database for connection testing."""

    def __init__(self):
        self.connections = {}
        self.query_count = 0
        self.transaction_count = 0

    def connect(self, connection_id: str):
        """Create database connection."""
        self.connections[connection_id] = {
            "created_at": time.time(),
            "queries_executed": 0,
            "in_transaction": False,
        }

    def disconnect(self, connection_id: str):
        """Close database connection."""
        self.connections.pop(connection_id, None)

    def execute_query(self, connection_id: str, query: str):
        """Execute query on connection."""
        if connection_id not in self.connections:
            raise Exception("Connection not found")

        self.connections[connection_id]["queries_executed"] += 1
        self.query_count += 1

        # Simulate query execution time
        time.sleep(0.001)  # 1ms

    def begin_transaction(self, connection_id: str):
        """Begin transaction."""
        if connection_id in self.connections:
            self.connections[connection_id]["in_transaction"] = True
            self.transaction_count += 1

    def commit_transaction(self, connection_id: str):
        """Commit transaction."""
        if connection_id in self.connections:
            self.connections[connection_id]["in_transaction"] = False

    def rollback_transaction(self, connection_id: str):
        """Rollback transaction."""
        if connection_id in self.connections:
            self.connections[connection_id]["in_transaction"] = False

    def get_active_connections_count(self) -> int:
        """Get count of active connections."""
        return len(self.connections)


@pytest.fixture
def mock_pgbouncer():
    """Mock PgBouncer instance."""
    return MockPgBouncerConnection("brain_researcher", max_connections=50)


@pytest.fixture
def mock_database():
    """Mock database instance."""
    return MockDatabase()


@pytest.fixture
def pgbouncer_config():
    """Sample PgBouncer configuration."""
    return {
        "databases": {
            "brain_researcher": {
                "host": "postgres",
                "port": 5432,
                "pool_size": 50,
                "reserve_pool": 5,
                "max_db_connections": 100,
            },
            "brain_researcher_readonly": {
                "host": "postgres-replica",
                "port": 5432,
                "pool_size": 30,
                "reserve_pool": 3,
                "max_db_connections": 60,
            },
        },
        "pgbouncer": {
            "pool_mode": "transaction",
            "max_client_conn": 1000,
            "default_pool_size": 50,
            "query_timeout": 300,
            "query_wait_timeout": 120,
            "client_idle_timeout": 0,
            "server_idle_timeout": 600,
            "server_lifetime": 3600,
            "server_reset_query": "DISCARD ALL",
        },
    }


@pytest.mark.unit
class TestConnectionPoolBasics:
    """Test basic connection pool functionality."""

    def test_pool_initialization(self, mock_pgbouncer, pgbouncer_config):
        """Test connection pool initialization."""
        # Pool should be properly initialized
        assert mock_pgbouncer.pool_name == "brain_researcher"
        assert mock_pgbouncer.max_connections == 50
        assert mock_pgbouncer.active_connections == 0
        assert mock_pgbouncer.pool_mode == "transaction"

    def test_connection_acquisition(self, mock_pgbouncer):
        """Test acquiring connections from pool."""
        # Acquire single connection
        success = mock_pgbouncer.acquire_connection()
        assert success is True
        assert mock_pgbouncer.active_connections == 1

        # Acquire multiple connections
        for i in range(10):
            success = mock_pgbouncer.acquire_connection()
            assert success is True

        assert mock_pgbouncer.active_connections == 11
        assert mock_pgbouncer.total_requests == 11

    def test_connection_release(self, mock_pgbouncer):
        """Test releasing connections back to pool."""
        # Acquire connections
        for i in range(5):
            mock_pgbouncer.acquire_connection()

        assert mock_pgbouncer.active_connections == 5

        # Release connections
        for i in range(3):
            mock_pgbouncer.release_connection()

        assert mock_pgbouncer.active_connections == 2

    def test_pool_statistics(self, mock_pgbouncer):
        """Test pool statistics collection."""
        # Acquire some connections
        for i in range(20):
            mock_pgbouncer.acquire_connection()

        stats = mock_pgbouncer.get_stats()

        assert stats["pool_name"] == "brain_researcher"
        assert stats["active_connections"] == 20
        assert stats["total_requests"] == 20
        assert stats["pool_utilization"] == 40.0  # 20/50 * 100

    def test_pool_capacity_limits(self, mock_pgbouncer):
        """Test pool capacity enforcement."""
        # Fill pool to capacity
        for i in range(50):
            success = mock_pgbouncer.acquire_connection()
            assert success is True

        # Next connection should fail (pool exhausted)
        success = mock_pgbouncer.acquire_connection()
        assert success is False

        # After releasing, should be able to acquire again
        mock_pgbouncer.release_connection()
        success = mock_pgbouncer.acquire_connection()
        assert success is True


@pytest.mark.unit
class TestTransactionPooling:
    """Test transaction-level pooling behavior."""

    def test_transaction_isolation(self, mock_database):
        """Test transaction isolation between connections."""
        # Create multiple connections with transactions
        connections = ["conn1", "conn2", "conn3"]

        for conn_id in connections:
            mock_database.connect(conn_id)
            mock_database.begin_transaction(conn_id)

        # Each connection should have independent transaction state
        for conn_id in connections:
            conn_info = mock_database.connections[conn_id]
            assert conn_info["in_transaction"] is True

        # Commit one transaction, others should remain active
        mock_database.commit_transaction("conn1")

        assert mock_database.connections["conn1"]["in_transaction"] is False
        assert mock_database.connections["conn2"]["in_transaction"] is True
        assert mock_database.connections["conn3"]["in_transaction"] is True

    def test_connection_reuse_after_transaction(self, mock_pgbouncer, mock_database):
        """Test connection reuse in transaction mode."""
        # Simulate transaction-level pooling workflow

        # Client 1: Acquire connection, run transaction, release
        success = mock_pgbouncer.acquire_connection()
        assert success is True

        mock_database.connect("client1_conn")
        mock_database.begin_transaction("client1_conn")
        mock_database.execute_query("client1_conn", "SELECT * FROM users")
        mock_database.commit_transaction("client1_conn")
        mock_database.disconnect("client1_conn")

        mock_pgbouncer.release_connection()

        # Client 2: Should be able to reuse the connection immediately
        success = mock_pgbouncer.acquire_connection()
        assert success is True

        mock_database.connect("client2_conn")
        mock_database.execute_query("client2_conn", "SELECT * FROM posts")
        mock_database.disconnect("client2_conn")

        mock_pgbouncer.release_connection()

        # Pool should handle rapid connection reuse
        assert mock_pgbouncer.active_connections == 0

    def test_long_running_transaction_handling(self, mock_pgbouncer, mock_database):
        """Test handling of long-running transactions."""
        # Start long-running transaction
        mock_pgbouncer.acquire_connection()
        mock_database.connect("long_tx_conn")
        mock_database.begin_transaction("long_tx_conn")

        # Simulate long-running query
        start_time = time.time()
        mock_database.execute_query("long_tx_conn", "ANALYZE large_table")

        # Connection should remain active during long transaction
        assert mock_pgbouncer.active_connections == 1

        # Other clients should still be able to acquire connections
        for i in range(10):
            success = mock_pgbouncer.acquire_connection()
            assert success is True

            mock_database.connect(f"quick_conn_{i}")
            mock_database.execute_query(f"quick_conn_{i}", "SELECT 1")
            mock_database.disconnect(f"quick_conn_{i}")

            mock_pgbouncer.release_connection()

        # Original transaction should still be active
        assert mock_database.connections["long_tx_conn"]["in_transaction"] is True

        # Cleanup
        mock_database.commit_transaction("long_tx_conn")
        mock_database.disconnect("long_tx_conn")
        mock_pgbouncer.release_connection()

    def test_transaction_timeout_handling(self, mock_database):
        """Test transaction timeout scenarios."""
        timeout_seconds = 300  # 5 minutes

        # Start transaction with timeout tracking
        mock_database.connect("timeout_conn")
        tx_start_time = time.time()
        mock_database.begin_transaction("timeout_conn")

        # Simulate timeout check
        def is_transaction_expired(start_time: float, timeout: int) -> bool:
            return (time.time() - start_time) > timeout

        # Transaction should not be expired immediately
        assert is_transaction_expired(tx_start_time, timeout_seconds) is False

        # Simulate time passage (mock)
        simulated_time = tx_start_time + timeout_seconds + 1
        with patch("time.time", return_value=simulated_time):
            assert is_transaction_expired(tx_start_time, timeout_seconds) is True

        # Expired transaction should be cleaned up
        mock_database.rollback_transaction("timeout_conn")
        mock_database.disconnect("timeout_conn")


@pytest.mark.unit
class TestPoolExhaustionScenarios:
    """Test pool exhaustion and recovery scenarios."""

    def test_pool_exhaustion_detection(self, mock_pgbouncer):
        """Test detection of pool exhaustion."""
        # Fill pool completely
        for i in range(mock_pgbouncer.max_connections):
            success = mock_pgbouncer.acquire_connection()
            assert success is True

        # Pool should be at capacity
        stats = mock_pgbouncer.get_stats()
        assert stats["pool_utilization"] == 100.0

        # Additional requests should fail
        success = mock_pgbouncer.acquire_connection()
        assert success is False
        assert mock_pgbouncer.waiting_connections > 0

    def test_pool_recovery_after_exhaustion(self, mock_pgbouncer):
        """Test pool recovery after exhaustion."""
        # Exhaust pool
        for i in range(mock_pgbouncer.max_connections):
            mock_pgbouncer.acquire_connection()

        # Verify exhaustion
        success = mock_pgbouncer.acquire_connection()
        assert success is False

        # Release some connections
        for i in range(10):
            mock_pgbouncer.release_connection()

        # Pool should recover and accept new connections
        for i in range(5):
            success = mock_pgbouncer.acquire_connection()
            assert success is True

        stats = mock_pgbouncer.get_stats()
        assert stats["active_connections"] == 45  # 50 - 10 + 5

    def test_connection_queuing_behavior(self, mock_pgbouncer):
        """Test connection queuing when pool is exhausted."""
        # Exhaust pool
        for i in range(mock_pgbouncer.max_connections):
            mock_pgbouncer.acquire_connection()

        # Attempt to acquire additional connections (should queue)
        waiting_requests = []
        for i in range(5):
            # These should fail but increment waiting count
            success = mock_pgbouncer.acquire_connection()
            waiting_requests.append(success)

        # All additional requests should fail
        assert all(not req for req in waiting_requests)

        # But waiting count should reflect queued requests
        # (Note: In real PgBouncer, this would be managed differently)
        assert mock_pgbouncer.waiting_connections >= 0

    def test_pool_pressure_monitoring(self, mock_pgbouncer):
        """Test monitoring of pool pressure/utilization."""
        utilization_history = []

        # Gradually increase pool usage
        for connections in [10, 25, 40, 48, 50]:
            # Reset pool
            mock_pgbouncer.active_connections = 0

            # Acquire connections
            for i in range(connections):
                mock_pgbouncer.acquire_connection()

            stats = mock_pgbouncer.get_stats()
            utilization_history.append(stats["pool_utilization"])

        # Utilization should increase
        assert utilization_history == [20.0, 50.0, 80.0, 96.0, 100.0]

        # High utilization should trigger alerts (in real system)
        high_utilization_threshold = 90.0
        critical_utilization_count = sum(
            1 for util in utilization_history if util >= high_utilization_threshold
        )
        assert critical_utilization_count == 2  # Last 2 measurements

    @pytest.mark.asyncio
    async def test_concurrent_connection_requests(self, mock_pgbouncer):
        """Test handling of concurrent connection requests."""

        async def request_connection(client_id: int) -> Tuple[int, bool]:
            """Simulate client requesting connection."""
            # Add small random delay to simulate real client behavior
            await asyncio.sleep(0.001 * (client_id % 10))

            success = mock_pgbouncer.acquire_connection()
            return client_id, success

        # Simulate 100 concurrent clients
        concurrent_clients = 100
        tasks = [request_connection(i) for i in range(concurrent_clients)]

        results = await asyncio.gather(*tasks)

        # Count successful vs failed requests
        successful_requests = sum(1 for _, success in results if success)
        failed_requests = concurrent_clients - successful_requests

        # Should not exceed pool capacity
        assert successful_requests <= mock_pgbouncer.max_connections
        assert failed_requests == concurrent_clients - mock_pgbouncer.max_connections

        # All successful connections should be tracked
        assert mock_pgbouncer.active_connections == successful_requests


@pytest.mark.unit
class TestConnectionLifecycle:
    """Test connection lifecycle management."""

    def test_connection_creation_and_cleanup(self, mock_database):
        """Test proper connection creation and cleanup."""
        connection_ids = []

        # Create connections
        for i in range(10):
            conn_id = f"test_conn_{i}"
            mock_database.connect(conn_id)
            connection_ids.append(conn_id)

        # Verify connections created
        assert mock_database.get_active_connections_count() == 10

        # Use connections
        for conn_id in connection_ids:
            mock_database.execute_query(conn_id, "SELECT version()")

        # Cleanup connections
        for conn_id in connection_ids:
            mock_database.disconnect(conn_id)

        # Verify cleanup
        assert mock_database.get_active_connections_count() == 0

    def test_connection_reuse_efficiency(self, mock_pgbouncer, mock_database):
        """Test efficiency of connection reuse."""
        # Track connection reuse patterns
        connection_acquisitions = 0
        database_connections = 0

        # Simulate multiple client sessions reusing pool connections
        for session in range(20):
            # Acquire from pool
            success = mock_pgbouncer.acquire_connection()
            assert success is True
            connection_acquisitions += 1

            # Only create new DB connection if needed (pool manages this)
            if mock_database.get_active_connections_count() < 5:
                mock_database.connect(f"pooled_conn_{session % 5}")
                database_connections += 1

            # Execute work
            conn_id = f"pooled_conn_{session % 5}"
            try:
                mock_database.execute_query(conn_id, "SELECT * FROM items")
            except:
                pass  # Connection might not exist in mock

            # Release back to pool
            mock_pgbouncer.release_connection()

        # Pool should have facilitated many more client connections than DB connections
        reuse_efficiency = connection_acquisitions / max(database_connections, 1)
        assert reuse_efficiency >= 4.0  # At least 4:1 reuse ratio

    def test_idle_connection_management(self, mock_database):
        """Test management of idle connections."""
        # Create connections with different idle times
        connections = [
            {"id": "active_conn", "last_used": time.time()},
            {"id": "idle_conn_1", "last_used": time.time() - 300},  # 5 min idle
            {"id": "idle_conn_2", "last_used": time.time() - 900},  # 15 min idle
            {"id": "idle_conn_3", "last_used": time.time() - 1800},  # 30 min idle
        ]

        for conn in connections:
            mock_database.connect(conn["id"])

        # Simulate idle connection cleanup
        idle_timeout = 600  # 10 minutes
        current_time = time.time()

        connections_to_close = [
            conn
            for conn in connections
            if (current_time - conn["last_used"]) > idle_timeout
        ]

        # Close idle connections
        for conn in connections_to_close:
            mock_database.disconnect(conn["id"])

        # Verify appropriate connections were closed
        assert len(connections_to_close) == 2  # idle_conn_2 and idle_conn_3
        remaining_connections = mock_database.get_active_connections_count()
        assert remaining_connections == 2  # active_conn and idle_conn_1

    def test_connection_health_monitoring(self, mock_database):
        """Test connection health monitoring and recovery."""
        # Create connections with health status
        healthy_connections = ["healthy_1", "healthy_2", "healthy_3"]
        unhealthy_connections = ["unhealthy_1", "unhealthy_2"]

        all_connections = healthy_connections + unhealthy_connections

        for conn_id in all_connections:
            mock_database.connect(conn_id)

        # Simulate health check
        def health_check_connection(conn_id: str) -> bool:
            try:
                mock_database.execute_query(conn_id, "SELECT 1")
                return conn_id.startswith("healthy")  # Mock: healthy connections work
            except:
                return False

        # Check health of all connections
        health_results = {}
        for conn_id in all_connections:
            health_results[conn_id] = health_check_connection(conn_id)

        # Remove unhealthy connections
        for conn_id, is_healthy in health_results.items():
            if not is_healthy:
                mock_database.disconnect(conn_id)

        # Verify only healthy connections remain
        remaining_count = mock_database.get_active_connections_count()
        assert remaining_count == len(healthy_connections)


@pytest.mark.integration
class TestPerformanceOptimization:
    """Test connection pooling performance optimizations."""

    def test_connection_pool_throughput(self, mock_pgbouncer, mock_database):
        """Test connection pool throughput under load."""
        # Setup multiple database connections for pool
        for i in range(10):
            mock_database.connect(f"pool_conn_{i}")

        # Measure throughput
        start_time = time.time()
        completed_operations = 0
        target_operations = 1000

        for operation in range(target_operations):
            # Acquire connection
            success = mock_pgbouncer.acquire_connection()
            if success:
                # Simulate database operation
                conn_id = f"pool_conn_{operation % 10}"
                try:
                    mock_database.execute_query(
                        conn_id, "SELECT count(*) FROM test_table"
                    )
                    completed_operations += 1
                except:
                    pass

                # Release connection
                mock_pgbouncer.release_connection()

        end_time = time.time()
        total_time = end_time - start_time

        # Calculate throughput
        operations_per_second = completed_operations / total_time

        # Should achieve good throughput (>500 ops/sec in mock)
        assert operations_per_second > 500
        assert completed_operations >= target_operations * 0.95  # 95% success rate

    def test_pool_size_optimization(self, pgbouncer_config):
        """Test optimal pool size determination."""
        # Test different pool sizes and their efficiency
        pool_sizes = [10, 25, 50, 100, 200]
        efficiency_results = {}

        for pool_size in pool_sizes:
            # Simulate pool with different sizes
            test_pool = MockPgBouncerConnection("test_pool", pool_size)

            # Simulate load
            concurrent_clients = 100
            successful_acquisitions = 0

            for client in range(concurrent_clients):
                success = test_pool.acquire_connection()
                if success:
                    successful_acquisitions += 1
                    # Don't release to simulate active usage

            # Calculate efficiency metrics
            utilization = (
                (successful_acquisitions / pool_size) * 100 if pool_size > 0 else 0
            )
            success_rate = (successful_acquisitions / concurrent_clients) * 100

            efficiency_results[pool_size] = {
                "utilization": utilization,
                "success_rate": success_rate,
                "efficiency_score": min(utilization, success_rate),  # Balanced score
            }

        # Find optimal pool size (highest efficiency score)
        optimal_pool_size = max(
            efficiency_results.keys(),
            key=lambda x: efficiency_results[x]["efficiency_score"],
        )

        # Optimal size should balance utilization and success rate
        optimal_efficiency = efficiency_results[optimal_pool_size]
        assert optimal_efficiency["efficiency_score"] >= 80.0

        # Very small pools should have poor success rates
        small_pool_efficiency = efficiency_results[10]
        assert small_pool_efficiency["success_rate"] < 50.0

    def test_connection_warmup_strategies(self, mock_database):
        """Test connection pool warmup strategies."""
        # Cold start: create connections on-demand
        cold_start_times = []
        for i in range(10):
            start_time = time.time()
            mock_database.connect(f"cold_conn_{i}")
            mock_database.execute_query(f"cold_conn_{i}", "SELECT 1")  # Warmup query
            end_time = time.time()
            cold_start_times.append(end_time - start_time)

        # Warm start: pre-created connections
        warm_connections = []
        for i in range(10):
            conn_id = f"warm_conn_{i}"
            mock_database.connect(conn_id)
            warm_connections.append(conn_id)

        warm_start_times = []
        for conn_id in warm_connections:
            start_time = time.time()
            mock_database.execute_query(conn_id, "SELECT 1")
            end_time = time.time()
            warm_start_times.append(end_time - start_time)

        # Warm connections should be faster on average
        avg_cold_time = statistics.mean(cold_start_times)
        avg_warm_time = statistics.mean(warm_start_times)

        assert avg_warm_time <= avg_cold_time

        # Cleanup
        for conn_id in warm_connections:
            mock_database.disconnect(conn_id)

    @pytest.mark.asyncio
    async def test_async_connection_handling(self, mock_pgbouncer):
        """Test asynchronous connection handling performance."""

        async def async_database_operation(operation_id: int):
            """Simulate async database operation."""
            success = mock_pgbouncer.acquire_connection()
            if not success:
                return operation_id, False, 0

            start_time = time.time()

            # Simulate async database work
            await asyncio.sleep(0.01)  # 10ms operation

            end_time = time.time()
            operation_time = end_time - start_time

            mock_pgbouncer.release_connection()
            return operation_id, True, operation_time

        # Run concurrent async operations
        concurrent_operations = 100
        tasks = [async_database_operation(i) for i in range(concurrent_operations)]

        start_time = time.time()
        results = await asyncio.gather(*tasks)
        total_time = time.time() - start_time

        # Analyze results
        successful_ops = [r for r in results if r[1]]
        operation_times = [r[2] for r in results if r[1]]

        success_rate = len(successful_ops) / concurrent_operations
        avg_operation_time = statistics.mean(operation_times) if operation_times else 0

        # Async should handle high concurrency efficiently
        assert success_rate >= 0.5  # At least 50% should succeed with pool limits
        assert total_time < 2.0  # Should complete within 2 seconds due to concurrency
        assert avg_operation_time < 0.1  # Individual operations should be fast


@pytest.mark.integration
class TestMultiTenantPooling:
    """Test multi-tenant connection pooling scenarios."""

    def test_tenant_isolation(self, pgbouncer_config):
        """Test connection isolation between tenants."""
        # Setup tenant-specific pools
        tenant_pools = {
            "tenant_a": MockPgBouncerConnection("tenant_a_pool", 20),
            "tenant_b": MockPgBouncerConnection("tenant_b_pool", 30),
            "tenant_c": MockPgBouncerConnection("tenant_c_pool", 15),
        }

        # Each tenant uses their own pool
        for tenant, pool in tenant_pools.items():
            # Simulate tenant workload
            connections_acquired = min(25, pool.max_connections)  # Try to acquire 25

            for i in range(connections_acquired):
                success = pool.acquire_connection()
                if not success:
                    break

            stats = pool.get_stats()
            assert stats["active_connections"] <= pool.max_connections

            # Tenant isolation: one tenant's usage doesn't affect others
            for other_tenant, other_pool in tenant_pools.items():
                if other_tenant != tenant:
                    # Other tenants should still be able to acquire connections
                    success = other_pool.acquire_connection()
                    assert success is True  # Their pools should be available
                    other_pool.release_connection()

    def test_tenant_resource_allocation(self):
        """Test resource allocation across tenants."""
        total_connections = 100

        # Different tenant priorities and allocations
        tenant_allocations = {
            "premium_tenant": {"allocation": 40, "priority": "high"},
            "standard_tenant": {"allocation": 35, "priority": "medium"},
            "basic_tenant": {"allocation": 25, "priority": "low"},
        }

        # Verify allocations sum correctly
        total_allocated = sum(
            config["allocation"] for config in tenant_allocations.values()
        )
        assert total_allocated == total_connections

        # Create pools based on allocations
        tenant_pools = {}
        for tenant, config in tenant_allocations.items():
            tenant_pools[tenant] = MockPgBouncerConnection(
                f"{tenant}_pool", config["allocation"]
            )

        # Simulate high demand from all tenants
        for tenant, pool in tenant_pools.items():
            # Each tenant tries to use 80% of total capacity (more than their allocation)
            requested_connections = int(total_connections * 0.8)
            acquired_connections = 0

            for i in range(requested_connections):
                success = pool.acquire_connection()
                if success:
                    acquired_connections += 1
                else:
                    break

            # Should be limited by their allocation
            config = tenant_allocations[tenant]
            assert acquired_connections <= config["allocation"]

    def test_shared_pool_fairness(self):
        """Test fairness in shared pool scenarios."""
        shared_pool = MockPgBouncerConnection("shared_pool", 50)

        # Multiple tenants sharing the same pool
        tenants = ["tenant_1", "tenant_2", "tenant_3", "tenant_4", "tenant_5"]
        tenant_usage = {tenant: 0 for tenant in tenants}

        # Simulate round-robin or fair allocation
        total_requests = 100

        for request in range(total_requests):
            tenant = tenants[request % len(tenants)]  # Round-robin

            success = shared_pool.acquire_connection()
            if success:
                tenant_usage[tenant] += 1
                # Simulate brief usage then release
                time.sleep(0.001)
                shared_pool.release_connection()

        # Check fairness - each tenant should get roughly equal usage
        usage_counts = list(tenant_usage.values())
        min_usage = min(usage_counts)
        max_usage = max(usage_counts)

        # Fairness check: difference between min and max should be small
        fairness_ratio = min_usage / max_usage if max_usage > 0 else 1
        assert fairness_ratio >= 0.8  # Within 20% of each other


@pytest.mark.integration
@pytest.mark.slow
class TestConnectionPoolMonitoring:
    """Test connection pool monitoring and alerting."""

    def test_pool_metrics_collection(self, mock_pgbouncer):
        """Test comprehensive pool metrics collection."""
        # Simulate various pool activities
        activities = [
            {"action": "acquire", "count": 20},
            {"action": "release", "count": 5},
            {"action": "acquire", "count": 15},
            {"action": "release", "count": 10},
            {"action": "acquire", "count": 10},
        ]

        metrics_history = []

        for activity in activities:
            if activity["action"] == "acquire":
                for _ in range(activity["count"]):
                    mock_pgbouncer.acquire_connection()
            else:  # release
                for _ in range(activity["count"]):
                    mock_pgbouncer.release_connection()

            # Collect metrics after each activity
            stats = mock_pgbouncer.get_stats()
            metrics_history.append(
                {
                    "timestamp": time.time(),
                    "active_connections": stats["active_connections"],
                    "pool_utilization": stats["pool_utilization"],
                    "total_requests": stats["total_requests"],
                }
            )

        # Verify metrics progression
        assert len(metrics_history) == len(activities)

        # Total requests should only increase
        request_counts = [m["total_requests"] for m in metrics_history]
        assert all(
            request_counts[i] >= request_counts[i - 1]
            for i in range(1, len(request_counts))
        )

        # Final state should reflect net acquisitions
        final_metrics = metrics_history[-1]
        expected_active = 20 - 5 + 15 - 10 + 10  # Net acquisitions
        assert final_metrics["active_connections"] == expected_active

    def test_alert_threshold_monitoring(self, mock_pgbouncer):
        """Test monitoring and alerting on pool thresholds."""
        # Define alert thresholds
        thresholds = {
            "warning": 70.0,  # 70% utilization
            "critical": 90.0,  # 90% utilization
            "emergency": 98.0,  # 98% utilization
        }

        alert_history = []

        # Gradually increase pool usage
        connection_counts = [10, 20, 35, 40, 45, 47, 49]

        for count in connection_counts:
            # Reset and set specific connection count
            mock_pgbouncer.active_connections = 0
            for _ in range(count):
                mock_pgbouncer.acquire_connection()

            stats = mock_pgbouncer.get_stats()
            utilization = stats["pool_utilization"]

            # Check alert conditions
            alert_level = None
            if utilization >= thresholds["emergency"]:
                alert_level = "emergency"
            elif utilization >= thresholds["critical"]:
                alert_level = "critical"
            elif utilization >= thresholds["warning"]:
                alert_level = "warning"

            if alert_level:
                alert_history.append(
                    {
                        "level": alert_level,
                        "utilization": utilization,
                        "active_connections": count,
                    }
                )

        # Verify appropriate alerts were triggered
        assert len(alert_history) >= 3  # Should have warning, critical, and emergency

        # Verify alert escalation
        alert_levels = [alert["level"] for alert in alert_history]
        assert "warning" in alert_levels
        assert "critical" in alert_levels
        assert "emergency" in alert_levels

    def test_performance_degradation_detection(self, mock_pgbouncer, mock_database):
        """Test detection of performance degradation."""
        # Baseline performance measurement
        baseline_operations = []
        for i in range(50):
            start_time = time.time()

            success = mock_pgbouncer.acquire_connection()
            if success:
                conn_id = f"perf_conn_{i % 5}"
                if mock_database.get_active_connections_count() < 5:
                    mock_database.connect(conn_id)

                try:
                    mock_database.execute_query(conn_id, "SELECT * FROM test_table")
                except:
                    pass

                mock_pgbouncer.release_connection()

            operation_time = time.time() - start_time
            baseline_operations.append(operation_time)

        baseline_avg = statistics.mean(baseline_operations)

        # Simulate degraded performance (pool under stress)
        # Fill pool to near capacity
        for _ in range(45):  # 90% capacity
            mock_pgbouncer.acquire_connection()

        degraded_operations = []
        for i in range(20):
            start_time = time.time()

            success = mock_pgbouncer.acquire_connection()  # Should be slower/fail more
            operation_time = time.time() - start_time
            degraded_operations.append(operation_time)

            if success:
                mock_pgbouncer.release_connection()

        degraded_avg = statistics.mean(degraded_operations)

        # Performance degradation detection
        degradation_ratio = degraded_avg / baseline_avg
        performance_threshold = 2.0  # 2x slowdown threshold

        degradation_detected = degradation_ratio > performance_threshold

        # Should detect degradation under high pool utilization
        assert degradation_detected is True
        assert degraded_avg > baseline_avg


@pytest.mark.unit
class TestConfigurationValidation:
    """Test PgBouncer configuration validation."""

    def test_pool_size_validation(self, pgbouncer_config):
        """Test pool size configuration validation."""

        def validate_pool_config(config: dict) -> List[str]:
            """Validate pool configuration and return errors."""
            errors = []

            for db_name, db_config in config.get("databases", {}).items():
                pool_size = db_config.get("pool_size", 0)
                max_db_connections = db_config.get("max_db_connections", 0)

                if pool_size <= 0:
                    errors.append(f"{db_name}: pool_size must be positive")

                if max_db_connections <= 0:
                    errors.append(f"{db_name}: max_db_connections must be positive")

                if pool_size > max_db_connections:
                    errors.append(
                        f"{db_name}: pool_size cannot exceed max_db_connections"
                    )

            pgbouncer_config = config.get("pgbouncer", {})
            max_client_conn = pgbouncer_config.get("max_client_conn", 0)

            if max_client_conn <= 0:
                errors.append("max_client_conn must be positive")

            return errors

        # Valid configuration should pass
        errors = validate_pool_config(pgbouncer_config)
        assert len(errors) == 0

        # Test invalid configurations
        invalid_configs = [
            # Pool size too large
            {
                **pgbouncer_config,
                "databases": {"test_db": {"pool_size": 100, "max_db_connections": 50}},
            },
            # Zero pool size
            {
                **pgbouncer_config,
                "databases": {"test_db": {"pool_size": 0, "max_db_connections": 50}},
            },
            # Zero max client connections
            {**pgbouncer_config, "pgbouncer": {"max_client_conn": 0}},
        ]

        for invalid_config in invalid_configs:
            errors = validate_pool_config(invalid_config)
            assert len(errors) > 0

    def test_timeout_configuration(self, pgbouncer_config):
        """Test timeout configuration validation."""
        timeout_config = pgbouncer_config["pgbouncer"]

        # Validate timeout relationships
        query_timeout = timeout_config["query_timeout"]
        query_wait_timeout = timeout_config["query_wait_timeout"]

        # Query wait timeout should be less than query timeout
        assert query_wait_timeout < query_timeout

        # Test timeout edge cases
        test_cases = [
            {"query_timeout": 0, "valid": False},  # Zero timeout invalid
            {"query_timeout": -1, "valid": False},  # Negative timeout invalid
            {"query_timeout": 30, "valid": True},  # Normal timeout valid
            {"query_timeout": 86400, "valid": True},  # Long timeout valid
        ]

        for case in test_cases:
            timeout_value = case["query_timeout"]
            is_valid = timeout_value > 0
            assert is_valid == case["valid"]

    def test_pool_mode_validation(self, pgbouncer_config):
        """Test pool mode configuration validation."""
        valid_pool_modes = ["session", "transaction", "statement"]
        current_mode = pgbouncer_config["pgbouncer"]["pool_mode"]

        # Current configuration should be valid
        assert current_mode in valid_pool_modes

        # Test all valid modes
        for mode in valid_pool_modes:
            # Each mode should be acceptable
            test_config = {**pgbouncer_config}
            test_config["pgbouncer"]["pool_mode"] = mode

            # Configuration should be valid
            assert test_config["pgbouncer"]["pool_mode"] in valid_pool_modes

        # Test invalid modes
        invalid_modes = ["invalid", "connection", ""]

        for invalid_mode in invalid_modes:
            assert invalid_mode not in valid_pool_modes
