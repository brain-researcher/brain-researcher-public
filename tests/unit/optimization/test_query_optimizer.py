"""Unit tests for query optimization engine."""

import pytest
import re
from datetime import datetime
from unittest.mock import Mock, MagicMock
from brain_researcher.services.neurokg.optimization.query_optimizer import (
    QueryType,
    OptimizationStrategy,
    QueryPlan,
    QueryStatistics,
    QueryCache,
    QueryOptimizer
)


class TestQueryCache:
    """Test suite for QueryCache."""
    
    @pytest.fixture
    def cache(self):
        """Create cache instance."""
        return QueryCache(max_size=10, ttl_seconds=60)
    
    def test_cache_creation(self, cache):
        """Test cache initialization."""
        assert cache.max_size == 10
        assert cache.ttl_seconds == 60
        assert len(cache.cache) == 0
        assert cache.hit_count == 0
        assert cache.miss_count == 0
    
    def test_cache_put_get(self, cache):
        """Test putting and getting from cache."""
        cache.put('key1', 'value1')
        
        result = cache.get('key1')
        assert result == 'value1'
        assert cache.hit_count == 1
        assert cache.miss_count == 0
    
    def test_cache_miss(self, cache):
        """Test cache miss."""
        result = cache.get('nonexistent')
        assert result is None
        assert cache.miss_count == 1
    
    def test_cache_lru_eviction(self, cache):
        """Test LRU eviction."""
        # Fill cache to capacity
        for i in range(10):
            cache.put(f'key{i}', f'value{i}')
        
        assert len(cache.cache) == 10
        
        # Add one more, should evict oldest
        cache.put('key10', 'value10')
        assert len(cache.cache) == 10
        assert cache.get('key0') is None  # Evicted
        assert cache.get('key10') == 'value10'  # Present
    
    def test_cache_hit_rate(self, cache):
        """Test hit rate calculation."""
        cache.put('key1', 'value1')
        
        # 3 hits, 2 misses
        cache.get('key1')  # Hit
        cache.get('key1')  # Hit
        cache.get('key1')  # Hit
        cache.get('key2')  # Miss
        cache.get('key3')  # Miss
        
        hit_rate = cache.get_hit_rate()
        assert hit_rate == 0.6  # 3/5


class TestQueryOptimizer:
    """Test suite for QueryOptimizer."""
    
    @pytest.fixture
    def optimizer(self):
        """Create optimizer instance."""
        return QueryOptimizer(
            enable_cache=True,
            cache_size=100,
            collect_statistics=True
        )
    
    def test_optimizer_creation(self, optimizer):
        """Test optimizer initialization."""
        assert optimizer.enable_cache is True
        assert optimizer.cache is not None
        assert optimizer.collect_statistics is True
        assert len(optimizer.statistics) == 0
        assert len(optimizer.optimization_rules) > 0
    
    def test_identify_query_type(self, optimizer):
        """Test query type identification."""
        # Path query
        query = "MATCH p=shortestPath((a)-[*]-(b)) RETURN p"
        assert optimizer._identify_query_type(query) == QueryType.PATH
        
        # Traverse query
        query = "MATCH (n)-[*1..3]->(m) RETURN m"
        assert optimizer._identify_query_type(query) == QueryType.TRAVERSE
        
        # Aggregate query
        query = "MATCH (n) RETURN count(n)"
        assert optimizer._identify_query_type(query) == QueryType.AGGREGATE
        
        # Simple match
        query = "MATCH (n) RETURN n"
        assert optimizer._identify_query_type(query) == QueryType.MATCH
    
    def test_estimate_cost(self, optimizer):
        """Test query cost estimation."""
        # Simple query
        query1 = "MATCH (n:Task) WHERE n.id = '123' RETURN n"
        cost1 = optimizer._estimate_cost(query1)
        
        # Unbounded traversal (higher cost)
        query2 = "MATCH (n)-[*..]->(m) RETURN m"
        cost2 = optimizer._estimate_cost(query2)
        
        assert cost2 > cost1  # Unbounded should cost more
        
        # Query without WHERE (higher cost)
        query3 = "MATCH (n) RETURN n"
        cost3 = optimizer._estimate_cost(query3)
        
        assert cost3 > cost1  # No filter should cost more
    
    def test_optimize_index_lookup(self, optimizer):
        """Test index optimization."""
        query = "MATCH (t:Task {name: 'test'}) RETURN t"
        result = optimizer._optimize_index_lookup(query)
        
        assert OptimizationStrategy.INDEX_SCAN in result['strategies']
        assert len(result['hints']) > 0
        assert 'USING INDEX' in result['hints'][0]
    
    def test_optimize_filter_pushdown(self, optimizer):
        """Test filter pushdown optimization."""
        query = "MATCH (n:Task) WHERE n.name = 'test' RETURN n"
        result = optimizer._optimize_filter_pushdown(query)
        
        assert OptimizationStrategy.FILTER_PUSH_DOWN in result['strategies']
    
    def test_optimize_path_query(self, optimizer):
        """Test path query optimization."""
        # Unbounded path
        query = "MATCH (a)-[*..]->(b) RETURN b"
        result = optimizer._optimize_path_query(query)
        
        assert OptimizationStrategy.EXPAND in result['strategies']
        assert '*1..5' in result['query']  # Should add upper bound
    
    def test_optimize_aggregation(self, optimizer):
        """Test aggregation optimization."""
        query = "WITH n, collect(m) AS items RETURN n, items"
        result = optimizer._optimize_aggregation(query)
        
        assert OptimizationStrategy.HASH_JOIN in result['strategies']
        assert 'DISTINCT' in result['query']
    
    def test_optimize_query(self, optimizer):
        """Test full query optimization."""
        query = "MATCH (t:Task {name: 'test'}) WHERE t.contrast = 'motor' RETURN t"
        plan = optimizer.optimize_query(query)
        
        assert isinstance(plan, QueryPlan)
        assert plan.original_query == query
        assert len(plan.strategies) > 0
        assert plan.estimated_cost > 0
    
    def test_query_caching(self, optimizer):
        """Test query plan caching."""
        query = "MATCH (n:Concept) RETURN n LIMIT 10"
        
        # First optimization
        plan1 = optimizer.optimize_query(query)
        
        # Second optimization (should use cache)
        plan2 = optimizer.optimize_query(query)
        
        assert plan1.query_id == plan2.query_id
        assert optimizer.cache.hit_count > 0
    
    def test_execute_with_optimization(self, optimizer):
        """Test query execution with optimization."""
        query = "MATCH (n:Region) RETURN n.name"
        
        # Mock executor
        def mock_executor(optimized_query, params):
            return [{'n.name': 'Region1'}, {'n.name': 'Region2'}]
        
        results, plan = optimizer.execute_with_optimization(
            query,
            executor=mock_executor
        )
        
        assert len(results) == 2
        assert plan.execution_time is not None
        assert plan.execution_time > 0
    
    def test_statistics_collection(self, optimizer):
        """Test statistics collection."""
        # Execute some queries
        query1 = "MATCH (n) RETURN n"
        query2 = "MATCH (n) WHERE n.id = 123 RETURN n"
        
        optimizer._update_statistics(query1, 0.1, 10)
        optimizer._update_statistics(query1, 0.2, 15)
        optimizer._update_statistics(query2, 0.05, 1)
        
        assert len(optimizer.statistics) == 2
        
        # Check statistics for query1
        pattern1 = list(optimizer.statistics.keys())[0]
        stats1 = optimizer.statistics[pattern1]
        assert stats1.execution_count == 2
        # Floating point math can produce tiny rounding errors (e.g. 0.15000000000000002).
        assert stats1.avg_time == pytest.approx(0.15)  # (0.1 + 0.2) / 2
        assert stats1.min_time == 0.1
        assert stats1.max_time == 0.2
    
    def test_statistics_report(self, optimizer):
        """Test statistics report generation."""
        # Add some statistics
        for i in range(5):
            query = f"MATCH (n) WHERE n.id = {i} RETURN n"
            optimizer._update_statistics(query, 0.1 * (i + 1), 10)
        
        report = optimizer.get_statistics_report()
        
        assert 'cache_hit_rate' in report
        assert 'total_queries' in report
        assert report['total_queries'] == 5
        assert 'top_queries' in report
        assert 'slowest_queries' in report
        assert len(report['slowest_queries']) > 0
    
    def test_complex_query_optimization(self, optimizer):
        """Test optimization of complex query."""
        query = """
        MATCH (t:Task {contrast: 'motor'})-[:ACTIVATES]->(r:Region)
        WHERE r.coordinates[0] > 0
        WITH t, collect(DISTINCT r) as regions
        MATCH (t)-[:MEASURES]->(c:Concept)
        RETURN t.name, regions, collect(c.name) as concepts
        """
        
        plan = optimizer.optimize_query(query)
        
        assert plan is not None
        assert len(plan.strategies) > 0
        # Should have multiple optimizations applied
        assert any(s in plan.strategies for s in [
            OptimizationStrategy.INDEX_SCAN,
            OptimizationStrategy.FILTER_PUSH_DOWN,
            OptimizationStrategy.HASH_JOIN
        ])


class TestQueryPlan:
    """Test suite for QueryPlan."""
    
    def test_query_plan_creation(self):
        """Test creating query plan."""
        plan = QueryPlan(
            query_id="q123",
            original_query="MATCH (n) RETURN n",
            optimized_query="MATCH (n) USING INDEX n:Node(id) RETURN n",
            estimated_cost=5.0,
            strategies=[OptimizationStrategy.INDEX_SCAN],
            index_hints=["USING INDEX n:Node(id)"]
        )
        
        assert plan.query_id == "q123"
        assert plan.estimated_cost == 5.0
        assert OptimizationStrategy.INDEX_SCAN in plan.strategies
        assert len(plan.index_hints) == 1


class TestQueryStatistics:
    """Test suite for QueryStatistics."""
    
    def test_statistics_creation(self):
        """Test creating query statistics."""
        stats = QueryStatistics(
            query_pattern="MATCH (n) RETURN n"
        )
        
        assert stats.query_pattern == "MATCH (n) RETURN n"
        assert stats.execution_count == 0
        assert stats.total_time == 0.0
        assert stats.avg_time == 0.0
        assert stats.min_time == float('inf')
        assert stats.max_time == 0.0
