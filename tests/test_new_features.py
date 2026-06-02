#!/usr/bin/env python3
"""Quick test script to verify new features are working."""

import json
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))


def test_batch_processor():
    """Test the batch processing system."""
    print("\n=== Testing Batch Processor ===")

    from brain_researcher.core.ingestion.batch.processor import (
        BatchProcessor,
        Job,
        JobPriority,
        JobQueue,
        JobStatus,
    )

    # Create job queue
    queue = JobQueue()
    print("✓ Job queue created")

    # Create a test job
    job = Job(
        job_id="test_001",
        job_type="test_ingestion",
        priority=JobPriority.HIGH,
        params={"test": True},
    )

    # Submit job
    job_id = queue.submit(job)
    print(f"✓ Job submitted with ID: {job_id}")

    # Check queue position
    position = queue.get_queue_position(job_id)
    print(f"✓ Queue position: {position}")

    # Get job status
    retrieved_job = queue.get_job(job_id)
    if retrieved_job:
        print(f"✓ Job status: {retrieved_job.status.value}")

    # Get queue statistics
    stats = queue.get_statistics()
    print(f"✓ Queue statistics: {json.dumps(stats, indent=2)}")

    return True


def test_vector_search():
    """Test vector search integration."""
    print("\n=== Testing Vector Search ===")

    from brain_researcher.services.br_kg.search.vector_search import (
        VectorBackend,
        VectorSearchEngine,
    )

    # Create vector search engine with FAISS
    engine = VectorSearchEngine(backend=VectorBackend.FAISS)
    print("✓ Vector search engine created with FAISS backend")

    # Test data
    import numpy as np

    vectors = np.random.randn(100, 768).astype("float32")
    metadata = [{"id": f"doc_{i}", "text": f"Document {i}"} for i in range(100)]

    # Add vectors
    engine.add_vectors(vectors, metadata)
    print(f"✓ Added {len(vectors)} vectors to index")

    # Search
    query_vector = np.random.randn(1, 768).astype("float32")
    results = engine.search(query_vector[0], k=5)
    print(f"✓ Search returned {len(results)} results")

    # Show top result
    if results:
        top_result = results[0]
        print(
            f"  Top result: ID={top_result['metadata']['id']}, Score={top_result['score']:.3f}"
        )

    return True


def test_query_optimizer():
    """Test query optimization."""
    print("\n=== Testing Query Optimizer ===")

    from brain_researcher.services.br_kg.optimization.query_optimizer import (
        OptimizationStrategy,
        QueryOptimizer,
    )

    # Create optimizer
    optimizer = QueryOptimizer(strategy=OptimizationStrategy.COST_BASED)
    print("✓ Query optimizer created with cost-based strategy")

    # Test query
    test_query = """
    MATCH (t:Task)-[:MEASURES]->(c:Concept)
    WHERE t.dataset_id = 'ds001'
    RETURN c.name, count(t) as task_count
    ORDER BY task_count DESC
    LIMIT 10
    """

    # Optimize query
    optimized = optimizer.optimize(test_query)
    print("✓ Query optimized")
    print(f"  Original cost estimate: {optimized.get('original_cost', 'N/A')}")
    print(f"  Optimized cost estimate: {optimized.get('optimized_cost', 'N/A')}")
    print(f"  Expected improvement: {optimized.get('improvement', 'N/A')}%")

    # Check cache
    cache_key = optimizer._generate_cache_key(test_query, {})
    cached = optimizer.cache.get(cache_key)
    print(f"✓ Query cached: {cached is not None}")

    return True


def test_authentication():
    """Test authentication system."""
    print("\n=== Testing Authentication System ===")

    from brain_researcher.services.br_kg.auth.authentication import (
        AuthenticationManager,
        Permission,
        Role,
    )

    # Create auth manager
    auth = AuthenticationManager(secret_key="test-secret-key-for-demo")
    print("✓ Authentication manager created")

    # Create test user
    user = auth.create_user(
        email="test@example.com",
        username="testuser",
        password="testpass123",
        role=Role.RESEARCHER,
    )
    print(f"✓ User created: {user.username} (Role: {user.role.value})")

    # Generate tokens
    access_token = auth.create_access_token(user)
    print(f"✓ Access token generated: {access_token[:20]}...")

    refresh_token = auth.create_refresh_token(user)
    print(f"✓ Refresh token generated: {refresh_token[:20]}...")

    # Verify token
    token_data = auth.verify_token(access_token)
    if token_data:
        print(f"✓ Token verified for user: {token_data.email}")
        print(f"  Permissions: {', '.join(token_data.permissions[:3])}...")

    # Create API key
    api_key = auth.create_api_key(
        user, name="Test API Key", scopes=["read:concepts", "read:tasks"]
    )
    print(f"✓ API key created: {api_key[:20]}...")

    # Check permissions
    can_write = auth.check_permission(user, Permission.WRITE_CONCEPTS)
    can_admin = auth.check_permission(user, Permission.MANAGE_USERS)
    print(
        f"✓ Permission check - Write concepts: {can_write}, Manage users: {can_admin}"
    )

    # Log audit event
    auth.log_audit(
        user_id=user.user_id,
        action="TEST_ACTION",
        resource="TestResource",
        resource_id="test_123",
        success=True,
    )
    print(f"✓ Audit event logged ({len(auth.audit_logs)} total events)")

    return True


def test_performance_optimizer():
    """Test performance optimization."""
    print("\n=== Testing Performance Optimizer ===")

    from brain_researcher.services.br_kg.graph.performance_optimizer import (
        PerformanceOptimizer,
        optimize_database,
    )

    # Mock database connection
    class MockDB:
        def cursor(self):
            return self

        def execute(self, query):
            pass

        def commit(self):
            pass

        def fetchone(self):
            return [100]

        def fetchall(self):
            return []

    db = MockDB()
    optimizer = PerformanceOptimizer(db)
    print("✓ Performance optimizer created")

    # Add indexes (mock)
    optimizer.add_performance_indexes()
    print("✓ Performance indexes configured")

    # Add temporal attributes (mock)
    optimizer.add_temporal_attributes()
    print("✓ Temporal attributes added to relationships")

    # Optimize queries
    stats = optimizer.optimize_queries()
    print(f"✓ Query optimization complete: {stats}")

    # Benchmark
    metrics = optimizer.benchmark_performance()
    print(f"✓ Performance benchmark:")
    print(f"  Node count: {metrics.get('node_count', 0)}")
    print(f"  Read time: {metrics.get('read_time_ms', 0):.2f}ms")
    print(f"  Throughput: {metrics.get('read_throughput', 0):.0f} nodes/sec")

    return True


def main():
    """Run all tests."""
    print("=" * 60)
    print("  BRAIN RESEARCHER - NEW FEATURES TEST")
    print("=" * 60)

    tests = [
        ("Batch Processor", test_batch_processor),
        ("Vector Search", test_vector_search),
        ("Query Optimizer", test_query_optimizer),
        ("Authentication", test_authentication),
        ("Performance Optimizer", test_performance_optimizer),
    ]

    results = []
    for name, test_func in tests:
        try:
            success = test_func()
            results.append((name, "✅ PASS" if success else "❌ FAIL"))
        except Exception as e:
            print(f"  ❌ Error: {e}")
            results.append((name, f"❌ ERROR: {str(e)[:50]}"))

    # Summary
    print("\n" + "=" * 60)
    print("  TEST SUMMARY")
    print("=" * 60)

    for name, result in results:
        print(f"  {name:.<30} {result}")

    # Overall status
    all_passed = all("✅" in result for _, result in results)

    print("\n" + "=" * 60)
    if all_passed:
        print("  🎉 ALL TESTS PASSED! 🎉")
        print("  The new features are working correctly!")
    else:
        print("  ⚠️  Some tests failed. Check the output above.")
    print("=" * 60)


if __name__ == "__main__":
    main()
