"""
Unit tests for Query Caching and Memoization Module (AGENT-016)

Tests cover:
- Cache hit/miss scenarios
- TTL expiration behavior
- Key generation consistency
- Metrics calculation
- Cache policies
- Property-based tests for cache operations
"""

import json
import pytest
import time
import pickle
from unittest.mock import MagicMock, patch, call
from pathlib import Path

from hypothesis import given, strategies as st

# Import modules under test
from brain_researcher.services.agent.cache_manager import (
    QueryCacheManager,
    CachePolicy,
    CacheKeyType,
    CacheMetrics,
    CacheEntry,
    CacheKeyGenerator,
    cached,
    get_global_cache_manager,
    set_global_cache_manager
)


class MockRedis:
    """Mock Redis client for testing."""
    
    def __init__(self):
        self.data = {}
        self.ttl_data = {}
        self.call_count = 0
        
    def get(self, key):
        self.call_count += 1
        return self.data.get(key)
    
    def set(self, key, value, ex=None):
        self.call_count += 1
        self.data[key] = value
        if ex:
            self.ttl_data[key] = time.time() + ex
        return True
    
    def delete(self, *keys):
        self.call_count += 1
        count = 0
        for key in keys:
            if key in self.data:
                del self.data[key]
                count += 1
            if key in self.ttl_data:
                del self.ttl_data[key]
        return count
    
    def keys(self, pattern):
        self.call_count += 1
        # Simple pattern matching (for testing)
        if pattern.endswith('*'):
            prefix = pattern[:-1]
            return [key for key in self.data.keys() if key.startswith(prefix)]
        return [key for key in self.data.keys() if key == pattern]
    
    def sadd(self, key, *members):
        self.call_count += 1
        if key not in self.data:
            self.data[key] = set()
        if isinstance(self.data[key], bytes):
            self.data[key] = set()
        for member in members:
            self.data[key].add(member)
        return len(members)
    
    def smembers(self, key):
        self.call_count += 1
        return self.data.get(key, set())
    
    def expire(self, key, seconds):
        self.call_count += 1
        if key in self.data:
            self.ttl_data[key] = time.time() + seconds
        return True
    
    def ping(self):
        return True
    
    def info(self):
        return {
            'used_memory': len(str(self.data).encode()) + 1000,  # Approximate
            'total_commands_processed': self.call_count
        }
    
    def is_expired(self, key):
        """Helper to check if key should be expired."""
        if key in self.ttl_data:
            return time.time() > self.ttl_data[key]
        return False


class TestCacheMetrics:
    """Test CacheMetrics dataclass and calculations."""
    
    def test_metrics_initialization(self):
        """Test metrics initialization with defaults."""
        metrics = CacheMetrics()
        
        assert metrics.total_hits == 0
        assert metrics.total_misses == 0
        assert metrics.total_sets == 0
        assert metrics.total_evictions == 0
        assert metrics.total_invalidations == 0
        assert len(metrics.hit_latency_ms) == 0
        assert len(metrics.miss_latency_ms) == 0
        assert metrics.cache_size_bytes == 0
        assert isinstance(metrics.last_updated, float)
    
    def test_hit_rate_calculation(self):
        """Test hit rate calculation."""
        metrics = CacheMetrics()
        
        # No requests yet
        assert metrics.hit_rate == 0.0
        
        # Some hits and misses
        metrics.total_hits = 7
        metrics.total_misses = 3
        assert metrics.hit_rate == 0.7
        
        # Only hits
        metrics.total_hits = 10
        metrics.total_misses = 0
        assert metrics.hit_rate == 1.0
        
        # Only misses
        metrics.total_hits = 0
        metrics.total_misses = 5
        assert metrics.hit_rate == 0.0
    
    def test_latency_calculations(self):
        """Test latency calculation methods."""
        metrics = CacheMetrics()
        
        # Empty latencies
        assert metrics.avg_hit_latency_ms == 0.0
        assert metrics.avg_miss_latency_ms == 0.0
        
        # Add some latencies
        metrics.hit_latency_ms = [1.0, 2.0, 3.0]
        metrics.miss_latency_ms = [10.0, 20.0]
        
        assert metrics.avg_hit_latency_ms == 2.0
        assert metrics.avg_miss_latency_ms == 15.0
    
    @given(hits=st.integers(min_value=0, max_value=1000),
           misses=st.integers(min_value=0, max_value=1000))
    def test_hit_rate_properties(self, hits, misses):
        """Property test: hit rate should always be between 0 and 1."""
        metrics = CacheMetrics()
        metrics.total_hits = hits
        metrics.total_misses = misses
        
        hit_rate = metrics.hit_rate
        assert 0.0 <= hit_rate <= 1.0


class TestCacheEntry:
    """Test CacheEntry dataclass and methods."""
    
    def test_cache_entry_creation(self):
        """Test cache entry creation and properties."""
        entry = CacheEntry(
            key="test_key",
            value={"result": "test"},
            created_at=time.time(),
            ttl_seconds=3600,
            access_count=0,
            key_type=CacheKeyType.QUERY_RESULT,
            size_bytes=100,
            tags={"tag1", "tag2"}
        )
        
        assert entry.key == "test_key"
        assert entry.value == {"result": "test"}
        assert entry.ttl_seconds == 3600
        assert entry.key_type == CacheKeyType.QUERY_RESULT
        assert len(entry.tags) == 2
        assert isinstance(entry.last_accessed, float)
    
    def test_is_expired_property(self):
        """Test expiration checking."""
        now = time.time()
        
        # Not expired
        entry_valid = CacheEntry("key", "value", now, 3600)
        assert not entry_valid.is_expired
        
        # Expired
        entry_expired = CacheEntry("key", "value", now - 7200, 3600)  # Created 2 hours ago, TTL 1 hour
        assert entry_expired.is_expired
    
    def test_age_property(self):
        """Test age calculation."""
        now = time.time()
        entry = CacheEntry("key", "value", now - 300, 3600)  # Created 5 minutes ago
        
        age = entry.age_seconds
        assert 295 < age < 305  # Should be around 300 seconds


class TestCacheKeyGenerator:
    """Test cache key generation logic."""
    
    def test_key_generator_initialization(self):
        """Test key generator initialization."""
        generator = CacheKeyGenerator("test_namespace")
        assert generator.namespace == "test_namespace"
        
        # Default namespace
        generator_default = CacheKeyGenerator()
        assert generator_default.namespace == "brain_researcher"
    
    def test_generate_key_basic(self):
        """Test basic key generation."""
        generator = CacheKeyGenerator("test")
        
        key = generator.generate_key("test query", {"param": "value"})
        
        assert isinstance(key, str)
        assert key.startswith("test:query_result:")
        assert len(key.split(":")) == 3  # namespace:type:hash
        assert len(key.split(":")[-1]) == 32  # SHA256 hash truncated to 32 chars
    
    def test_generate_key_deterministic(self):
        """Test that key generation is deterministic."""
        generator = CacheKeyGenerator("test")
        
        query = "analyze working memory"
        context = {"dataset": "ds001", "task": "nback"}
        
        key1 = generator.generate_key(query, context)
        key2 = generator.generate_key(query, context)
        
        assert key1 == key2
    
    def test_generate_key_different_inputs(self):
        """Test that different inputs generate different keys."""
        generator = CacheKeyGenerator("test")
        
        key1 = generator.generate_key("query1", {"param": "value1"})
        key2 = generator.generate_key("query2", {"param": "value1"})
        key3 = generator.generate_key("query1", {"param": "value2"})
        
        assert key1 != key2
        assert key1 != key3
        assert key2 != key3
    
    def test_normalize_query(self):
        """Test query normalization."""
        generator = CacheKeyGenerator("test")
        
        # Test whitespace normalization
        assert generator._normalize_query("  test   query  ") == "test query"
        
        # Test case normalization
        assert generator._normalize_query("TEST Query") == "test query"
    
    def test_normalize_context(self):
        """Test context normalization."""
        generator = CacheKeyGenerator("test")
        
        context = {
            "dataset": "ds001",
            "timestamp": 1234567890,  # Should be filtered out
            "nested_dict": {"key": "value"},
            "list_data": [1, 2, 3]
        }
        
        normalized = generator._normalize_context(context)
        
        assert "dataset" in normalized
        assert "timestamp" not in normalized  # Should be filtered
        assert "nested_dict" in normalized
        assert "list_data" in normalized
        
        # Values should be strings
        assert isinstance(normalized["dataset"], str)
        assert isinstance(normalized["nested_dict"], str)
        assert isinstance(normalized["list_data"], str)
    
    def test_key_generation_with_different_types(self):
        """Test key generation with different cache key types."""
        generator = CacheKeyGenerator("test")
        
        query = "test query"
        context = {"param": "value"}
        
        types_to_test = [
            CacheKeyType.QUERY_RESULT,
            CacheKeyType.TOOL_EXECUTION,
            CacheKeyType.PLANNING_RESULT,
            CacheKeyType.REASONING_TRACE
        ]
        
        keys = []
        for key_type in types_to_test:
            key = generator.generate_key(query, context, key_type)
            keys.append(key)
            assert f":{key_type.value}:" in key
        
        # All keys should be different
        assert len(set(keys)) == len(keys)


class TestQueryCacheManager:
    """Test the main QueryCacheManager class."""
    
    def test_cache_manager_initialization_default(self):
        """Test cache manager initialization with defaults."""
        with patch('brain_researcher.services.agent.cache_manager.redis') as mock_redis_module:
            # Mock redis.from_url to return our mock
            mock_redis = MockRedis()
            mock_redis_module.from_url.return_value = mock_redis
            
            cache_manager = QueryCacheManager()
            
            assert cache_manager.ttl_seconds == 3600
            assert cache_manager.max_memory_mb == 512
            assert cache_manager.policy == CachePolicy.MODERATE
            assert cache_manager.namespace == "brain_researcher"
            assert isinstance(cache_manager.key_generator, CacheKeyGenerator)
            assert isinstance(cache_manager.metrics, CacheMetrics)
    
    def test_cache_manager_initialization_custom(self):
        """Test cache manager initialization with custom parameters."""
        mock_redis = MockRedis()
        
        cache_manager = QueryCacheManager(
            redis_client=mock_redis,
            ttl_seconds=7200,
            max_memory_mb=1024,
            policy=CachePolicy.AGGRESSIVE,
            namespace="custom"
        )
        
        assert cache_manager.ttl_seconds == 7200
        assert cache_manager.max_memory_mb == 1024
        assert cache_manager.policy == CachePolicy.AGGRESSIVE
        assert cache_manager.namespace == "custom"
        assert cache_manager.redis == mock_redis
    
    def test_policy_configuration(self):
        """Test policy-specific configurations."""
        mock_redis = MockRedis()
        
        # Test aggressive policy
        cache_aggressive = QueryCacheManager(mock_redis, policy=CachePolicy.AGGRESSIVE)
        config_aggressive = cache_aggressive.policy_config
        assert config_aggressive["cache_everything"] == True
        assert config_aggressive["default_ttl"] == 7200
        
        # Test conservative policy
        cache_conservative = QueryCacheManager(mock_redis, policy=CachePolicy.CONSERVATIVE)
        config_conservative = cache_conservative.policy_config
        assert config_conservative["cache_everything"] == False
        assert config_conservative["min_execution_time"] == 5.0
        
        # Test disabled policy
        cache_disabled = QueryCacheManager(mock_redis, policy=CachePolicy.DISABLED)
        config_disabled = cache_disabled.policy_config
        assert config_disabled["default_ttl"] == 0
        assert config_disabled["min_execution_time"] == float('inf')
    
    def test_should_cache_policy_decisions(self):
        """Test cache decision logic based on policies."""
        mock_redis = MockRedis()
        
        # Aggressive policy - should cache everything
        cache_aggressive = QueryCacheManager(mock_redis, policy=CachePolicy.AGGRESSIVE)
        assert cache_aggressive._should_cache(0.1, CacheKeyType.QUERY_RESULT) == True
        assert cache_aggressive._should_cache(10.0, CacheKeyType.QUERY_RESULT) == True
        
        # Conservative policy - should cache only slow operations
        cache_conservative = QueryCacheManager(mock_redis, policy=CachePolicy.CONSERVATIVE) 
        assert cache_conservative._should_cache(0.5, CacheKeyType.QUERY_RESULT) == False
        assert cache_conservative._should_cache(10.0, CacheKeyType.QUERY_RESULT) == True
        
        # Disabled policy - should never cache
        cache_disabled = QueryCacheManager(mock_redis, policy=CachePolicy.DISABLED)
        assert cache_disabled._should_cache(0.1, CacheKeyType.QUERY_RESULT) == False
        assert cache_disabled._should_cache(10.0, CacheKeyType.QUERY_RESULT) == False
    
    def test_get_or_compute_cache_hit(self):
        """Test cache hit scenario."""
        mock_redis = MockRedis()
        cache_manager = QueryCacheManager(mock_redis)
        
        # Prepare mock cache entry
        test_value = {"result": "cached_result"}
        cache_entry = CacheEntry(
            key="test_key",
            value=test_value,
            created_at=time.time(),
            ttl_seconds=3600
        )
        mock_redis.data["test_key"] = pickle.dumps(cache_entry)
        
        # Compute function (should not be called)
        compute_fn = MagicMock(return_value={"result": "computed_result"})
        
        result = cache_manager.get_or_compute("test_key", compute_fn)
        
        assert result == test_value
        assert compute_fn.call_count == 0  # Should not be called
        assert cache_manager.metrics.total_hits == 1
        assert cache_manager.metrics.total_misses == 0
    
    def test_get_or_compute_cache_miss(self):
        """Test cache miss scenario."""
        mock_redis = MockRedis()
        cache_manager = QueryCacheManager(mock_redis, policy=CachePolicy.AGGRESSIVE)
        
        computed_value = {"result": "computed_result"}
        compute_fn = MagicMock(return_value=computed_value)
        
        result = cache_manager.get_or_compute("missing_key", compute_fn)
        
        assert result == computed_value
        assert compute_fn.call_count == 1  # Should be called
        assert cache_manager.metrics.total_hits == 0
        assert cache_manager.metrics.total_misses == 1
        assert cache_manager.metrics.total_sets == 1
    
    def test_get_or_compute_disabled_policy(self):
        """Test get_or_compute with disabled caching policy."""
        mock_redis = MockRedis()
        cache_manager = QueryCacheManager(mock_redis, policy=CachePolicy.DISABLED)
        
        computed_value = {"result": "computed_result"}
        compute_fn = MagicMock(return_value=computed_value)
        
        result = cache_manager.get_or_compute("test_key", compute_fn)
        
        assert result == computed_value
        assert compute_fn.call_count == 1
        # No cache operations should occur
        assert cache_manager.metrics.total_hits == 0
        assert cache_manager.metrics.total_misses == 0
        assert cache_manager.metrics.total_sets == 0
    
    def test_get_or_compute_force_refresh(self):
        """Test force refresh functionality."""
        mock_redis = MockRedis()
        cache_manager = QueryCacheManager(mock_redis, policy=CachePolicy.AGGRESSIVE)
        
        # Set up existing cache entry
        old_value = {"result": "old_result"}
        cache_entry = CacheEntry("test_key", old_value, time.time(), 3600)
        mock_redis.data["test_key"] = pickle.dumps(cache_entry)
        
        # New computed value
        new_value = {"result": "new_result"}
        compute_fn = MagicMock(return_value=new_value)
        
        result = cache_manager.get_or_compute("test_key", compute_fn, force_refresh=True)
        
        assert result == new_value
        assert compute_fn.call_count == 1  # Should be called despite cache hit
        assert cache_manager.metrics.total_hits == 0  # No hit due to force refresh
        assert cache_manager.metrics.total_misses == 1
    
    def test_cache_expiration_handling(self):
        """Test handling of expired cache entries."""
        mock_redis = MockRedis()
        cache_manager = QueryCacheManager(mock_redis)
        
        # Create expired cache entry
        old_time = time.time() - 7200  # 2 hours ago
        expired_entry = CacheEntry("test_key", {"result": "expired"}, old_time, 3600)  # 1 hour TTL
        mock_redis.data["test_key"] = pickle.dumps(expired_entry)
        
        computed_value = {"result": "fresh_result"}
        compute_fn = MagicMock(return_value=computed_value)
        
        result = cache_manager.get_or_compute("test_key", compute_fn, 
                                            ttl_seconds=3600, 
                                            key_type=CacheKeyType.QUERY_RESULT)
        
        # Should get fresh computed value
        assert result == computed_value
        assert compute_fn.call_count == 1
        # Should be treated as cache miss
        assert cache_manager.metrics.total_misses == 1
    
    def test_invalidate_by_pattern(self):
        """Test cache invalidation by pattern."""
        mock_redis = MockRedis()
        cache_manager = QueryCacheManager(mock_redis)
        
        # Set up multiple cache entries
        keys = ["ns:type:key1", "ns:type:key2", "ns:other:key3"]
        for key in keys:
            mock_redis.data[key] = b"data"
        
        # Invalidate by pattern
        invalidated_count = cache_manager.invalidate(pattern="type:*")
        
        assert invalidated_count == 2  # Should match key1 and key2
        assert cache_manager.metrics.total_invalidations == 2
    
    def test_invalidate_by_tags(self):
        """Test cache invalidation by tags."""
        mock_redis = MockRedis()
        cache_manager = QueryCacheManager(mock_redis)
        
        # Set up cache entries with tags
        keys_with_tag = ["key1", "key2"]
        for key in keys_with_tag:
            mock_redis.data[key] = b"data"
        
        # Set up tag sets
        tag_key = f"{cache_manager.namespace}:tag:test_tag"
        mock_redis.data[tag_key] = set(keys_with_tag)
        
        # Invalidate by tags
        invalidated_count = cache_manager.invalidate(tags={"test_tag"})
        
        assert invalidated_count == 2
        assert cache_manager.metrics.total_invalidations == 2
    
    def test_invalidate_by_key_type(self):
        """Test cache invalidation by key type."""
        mock_redis = MockRedis()
        cache_manager = QueryCacheManager(mock_redis)
        
        # Set up cache entries of specific type
        keys = [
            f"{cache_manager.namespace}:query_result:hash1",
            f"{cache_manager.namespace}:query_result:hash2", 
            f"{cache_manager.namespace}:tool_exec:hash3"
        ]
        for key in keys:
            mock_redis.data[key] = b"data"
        
        # Invalidate by key type
        invalidated_count = cache_manager.invalidate(key_type=CacheKeyType.QUERY_RESULT)
        
        assert invalidated_count == 2  # Should match only query_result keys
    
    def test_warm_cache(self):
        """Test cache warming functionality."""
        mock_redis = MockRedis()
        cache_manager = QueryCacheManager(mock_redis, policy=CachePolicy.AGGRESSIVE)
        
        queries = ["query1", "query2", "query3"]
        contexts = [{"param": f"value{i}"} for i in range(3)]
        
        def mock_compute_fn(query, context):
            return {"query": query, "context": context}
        
        cache_manager.warm_cache(queries, contexts, mock_compute_fn)
        
        # Should have cached all queries
        assert cache_manager.metrics.total_sets == 3
        
        # Verify cache entries exist
        for i, query in enumerate(queries):
            cache_key = cache_manager.key_generator.generate_key(query, contexts[i])
            cached_entry = cache_manager._get_from_cache(cache_key)
            assert cached_entry is not None
            assert cached_entry["query"] == query
    
    def test_get_stats(self):
        """Test cache statistics retrieval."""
        mock_redis = MockRedis()
        cache_manager = QueryCacheManager(mock_redis)
        
        # Set some metrics
        cache_manager.metrics.total_hits = 10
        cache_manager.metrics.total_misses = 5
        cache_manager.metrics.total_sets = 5
        cache_manager.metrics.hit_latency_ms = [1.0, 2.0, 3.0]
        cache_manager.metrics.miss_latency_ms = [10.0, 20.0]
        
        stats = cache_manager.get_stats()
        
        assert stats["hit_rate"] == 2/3  # 10/(10+5)
        assert stats["total_hits"] == 10
        assert stats["total_misses"] == 5
        assert stats["total_sets"] == 5
        assert stats["avg_hit_latency_ms"] == 2.0
        assert stats["avg_miss_latency_ms"] == 15.0
        assert stats["policy"] == CachePolicy.MODERATE.value
        assert "memory_used_bytes" in stats
        assert "last_updated" in stats
    
    def test_clear_all(self):
        """Test clearing all cache entries."""
        mock_redis = MockRedis()
        cache_manager = QueryCacheManager(mock_redis)
        
        # Set up some cache entries
        test_keys = [f"{cache_manager.namespace}:type:key{i}" for i in range(5)]
        for key in test_keys:
            mock_redis.data[key] = b"data"
        
        # Set some metrics
        cache_manager.metrics.total_hits = 10
        cache_manager.metrics.total_sets = 5
        
        cleared_count = cache_manager.clear_all()
        
        assert cleared_count == 5
        # Metrics should be reset
        assert cache_manager.metrics.total_hits == 0
        assert cache_manager.metrics.total_sets == 0
    
    @given(ttl=st.integers(min_value=1, max_value=86400),
           cache_size=st.integers(min_value=1, max_value=100))
    def test_cache_manager_properties(self, ttl, cache_size):
        """Property test: cache manager should handle various configurations."""
        mock_redis = MockRedis()
        
        cache_manager = QueryCacheManager(
            redis_client=mock_redis,
            ttl_seconds=ttl,
            max_memory_mb=cache_size
        )
        
        assert cache_manager.ttl_seconds == ttl
        assert cache_manager.max_memory_mb == cache_size
        assert isinstance(cache_manager.metrics, CacheMetrics)


class TestCachedDecorator:
    """Test the @cached decorator functionality."""
    
    def test_cached_decorator_basic(self):
        """Test basic cached decorator functionality."""
        mock_redis = MockRedis()
        cache_manager = QueryCacheManager(mock_redis, policy=CachePolicy.AGGRESSIVE)
        
        call_count = 0
        
        @cached(ttl_seconds=3600, cache_manager=cache_manager)
        def expensive_function(x, y):
            nonlocal call_count
            call_count += 1
            return x + y
        
        # First call should execute function
        result1 = expensive_function(1, 2)
        assert result1 == 3
        assert call_count == 1
        
        # Second call with same args should use cache
        result2 = expensive_function(1, 2)
        assert result2 == 3
        assert call_count == 1  # Function not called again
        
        # Different args should execute function again
        result3 = expensive_function(2, 3)
        assert result3 == 5
        assert call_count == 2
    
    def test_cached_decorator_with_global_manager(self):
        """Test cached decorator using global cache manager."""
        mock_redis = MockRedis()
        cache_manager = QueryCacheManager(mock_redis, policy=CachePolicy.AGGRESSIVE)
        set_global_cache_manager(cache_manager)
        
        call_count = 0
        
        @cached(ttl_seconds=1800)  # No explicit cache_manager
        def test_function(value):
            nonlocal call_count
            call_count += 1
            return value * 2
        
        result1 = test_function(5)
        result2 = test_function(5)
        
        assert result1 == result2 == 10
        assert call_count == 1  # Should use cache
    
    def test_cached_decorator_with_kwargs(self):
        """Test cached decorator with keyword arguments."""
        mock_redis = MockRedis()
        cache_manager = QueryCacheManager(mock_redis, policy=CachePolicy.AGGRESSIVE)
        
        call_count = 0
        
        @cached(ttl_seconds=3600, cache_manager=cache_manager)
        def function_with_kwargs(a, b=10, c=20):
            nonlocal call_count
            call_count += 1
            return a + b + c
        
        # Test with different kwargs combinations
        result1 = function_with_kwargs(1, b=2, c=3)
        result2 = function_with_kwargs(1, b=2, c=3)  # Same call
        result3 = function_with_kwargs(1, c=3, b=2)  # Same values, different order
        
        assert result1 == result2 == result3 == 6
        # Should be cached (though order might affect caching)
        assert call_count <= 2


class TestGlobalCacheManager:
    """Test global cache manager functionality."""
    
    def test_get_global_cache_manager_singleton(self):
        """Test that global cache manager is a singleton."""
        # Clear any existing global manager
        set_global_cache_manager(None)
        
        with patch('brain_researcher.services.agent.cache_manager.QueryCacheManager') as MockCacheManager:
            mock_instance = MagicMock()
            MockCacheManager.return_value = mock_instance
            
            manager1 = get_global_cache_manager()
            manager2 = get_global_cache_manager()
            
            assert manager1 == manager2  # Should be same instance
            assert MockCacheManager.call_count == 1  # Should be created only once
    
    def test_set_global_cache_manager(self):
        """Test setting custom global cache manager."""
        custom_manager = MagicMock()
        set_global_cache_manager(custom_manager)
        
        retrieved_manager = get_global_cache_manager()
        assert retrieved_manager == custom_manager


class TestIntegrationWithFixtures:
    """Test integration with fixture data."""
    
    @pytest.fixture
    def cache_test_data(self):
        """Load cache test data from fixtures."""
        fixture_path = Path(__file__).parent.parent / "fixtures" / "AGENT-016" / "cache_test_data.json"
        with open(fixture_path, 'r') as f:
            return json.load(f)
    
    @pytest.fixture
    def expected_hit_patterns(self):
        """Load expected hit patterns from fixtures."""
        fixture_path = Path(__file__).parent.parent / "fixtures" / "AGENT-016" / "expected_hit_patterns.json"
        with open(fixture_path, 'r') as f:
            return json.load(f)
    
    def test_cache_scenarios_from_fixtures(self, cache_test_data):
        """Test cache scenarios defined in fixtures."""
        mock_redis = MockRedis()
        cache_manager = QueryCacheManager(mock_redis, policy=CachePolicy.AGGRESSIVE)
        
        for scenario in cache_test_data["cache_scenarios"]:
            scenario_name = scenario["scenario_name"]
            
            if scenario_name == "basic_hit_miss":
                operations = scenario["operations"]
                
                # Process set operation
                set_op = operations[0]
                assert set_op["operation"] == "set"
                cache_entry = CacheEntry(
                    key=set_op["key"],
                    value=set_op["value"],
                    created_at=time.time(),
                    ttl_seconds=set_op["ttl"]
                )
                mock_redis.data[set_op["key"]] = pickle.dumps(cache_entry)
                
                # Process get operations
                for get_op in operations[1:]:
                    if get_op["operation"] == "get":
                        result = cache_manager._get_from_cache(get_op["key"])
                        if get_op["expected_hit"]:
                            assert result == get_op["expected_result"]
                        else:
                            assert result is None
    
    def test_key_generation_consistency_from_fixtures(self, cache_test_data):
        """Test key generation consistency based on fixture data."""
        generator = CacheKeyGenerator("brain_researcher")
        
        key_tests = cache_test_data["key_generation_tests"]
        
        first_test = key_tests[0]
        first_key = generator.generate_key(
            first_test["query"], 
            first_test["context"]
        )
        
        # Should match expected pattern
        import re
        pattern = first_test["expected_key_pattern"]
        assert re.match(pattern, first_key)
        
        # Test case sensitivity
        case_test = key_tests[1]
        if case_test["expected_same_key_as_previous"]:
            case_key = generator.generate_key(
                case_test["query"],
                case_test["context"]
            )
            assert case_key == first_key
        
        # Test different context
        diff_context_test = key_tests[2] 
        if diff_context_test["expected_different_key_from_first"]:
            diff_key = generator.generate_key(
                diff_context_test["query"],
                diff_context_test["context"]
            )
            assert diff_key != first_key
    
    def test_policy_behavior_from_fixtures(self, cache_test_data):
        """Test cache policy behavior based on fixture data."""
        mock_redis = MockRedis()
        
        policy_tests = cache_test_data["policy_tests"]
        
        for policy_test in policy_tests:
            policy_name = policy_test["policy"]
            policy = CachePolicy(policy_name)
            
            cache_manager = QueryCacheManager(mock_redis, policy=policy)
            
            for operation in policy_test["operations"]:
                execution_time = operation["execution_time"]
                expected_cache = operation["should_cache"]
                
                actual_cache = cache_manager._should_cache(execution_time, CacheKeyType.QUERY_RESULT)
                assert actual_cache == expected_cache, f"Policy {policy_name}, execution_time {execution_time}"


class TestErrorHandling:
    """Test error handling in cache operations."""
    
    def test_redis_connection_failure(self):
        """Test handling of Redis connection failures."""
        with patch('brain_researcher.services.agent.cache_manager.redis') as mock_redis_module:
            # Mock Redis connection failure
            mock_redis_module.from_url.side_effect = Exception("Connection failed")
            
            # Should fall back to fakeredis
            with patch('brain_researcher.services.agent.cache_manager.fakeredis') as mock_fakeredis:
                mock_fakeredis.FakeRedis.return_value = MockRedis()
                
                cache_manager = QueryCacheManager()
                assert cache_manager.redis is not None
    
    def test_compute_function_exception(self):
        """Test handling when compute function raises exception."""
        mock_redis = MockRedis()
        cache_manager = QueryCacheManager(mock_redis)
        
        def failing_compute():
            raise ValueError("Computation failed")
        
        with pytest.raises(ValueError, match="Computation failed"):
            cache_manager.get_or_compute("test_key", failing_compute)
    
    def test_serialization_errors(self):
        """Test handling of serialization errors."""
        mock_redis = MockRedis()
        cache_manager = QueryCacheManager(mock_redis, policy=CachePolicy.AGGRESSIVE)
        
        # Object that can't be pickled
        class UnpicklableObject:
            def __getstate__(self):
                raise Exception("Cannot pickle")
        
        def compute_unpicklable():
            return UnpicklableObject()
        
        # Should handle serialization error gracefully
        result = cache_manager.get_or_compute("test_key", compute_unpicklable)
        assert isinstance(result, UnpicklableObject)
        # Cache operation should have failed, but function should still return result
    
    def test_corrupted_cache_data(self):
        """Test handling of corrupted cache data."""
        mock_redis = MockRedis()
        cache_manager = QueryCacheManager(mock_redis)
        
        # Store corrupted data
        mock_redis.data["test_key"] = b"corrupted_pickle_data"
        
        def compute_fresh():
            return {"fresh": "data"}
        
        # Should handle corrupted data and compute fresh result
        result = cache_manager.get_or_compute("test_key", compute_fresh)
        assert result == {"fresh": "data"}


class TestPerformance:
    """Test performance characteristics."""
    
    def test_large_cache_operations(self):
        """Test performance with large number of cache operations."""
        mock_redis = MockRedis()
        cache_manager = QueryCacheManager(mock_redis, policy=CachePolicy.AGGRESSIVE)
        
        # Perform many cache operations
        start_time = time.time()
        
        for i in range(100):
            key = f"test_key_{i}"
            def compute(i=i):
                return {"result": f"value_{i}"}
            
            result = cache_manager.get_or_compute(key, compute)
            assert result["result"] == f"value_{i}"
        
        elapsed = time.time() - start_time
        
        # Should complete reasonably fast
        assert elapsed < 1.0  # Less than 1 second for 100 operations
        assert cache_manager.metrics.total_sets == 100
    
    def test_memory_efficient_operations(self):
        """Test memory efficiency of cache operations."""
        mock_redis = MockRedis()
        cache_manager = QueryCacheManager(mock_redis, max_memory_mb=1)  # Small memory limit
        
        # Store some data
        large_data = {"data": "x" * 10000}  # ~10KB data
        
        result = cache_manager.get_or_compute(
            "large_data_key",
            lambda: large_data,
            key_type=CacheKeyType.QUERY_RESULT
        )
        
        assert result == large_data
        # Should have calculated size
        stats = cache_manager.get_stats()
        assert stats["cache_size_bytes"] > 0