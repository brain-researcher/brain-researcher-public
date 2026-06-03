"""
Query Caching and Memoization Module for Brain Researcher Agent (AGENT-016)

This module implements Redis-backed caching with TTL support, cache key generation,
invalidation strategies, and performance metrics tracking.
"""

import hashlib
import json
import logging
import pickle
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Union
from functools import wraps

import redis
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class CachePolicy(str, Enum):
    """Cache policies for different types of operations."""

    AGGRESSIVE = "aggressive"  # Cache everything, long TTL
    MODERATE = "moderate"     # Cache most things, medium TTL
    CONSERVATIVE = "conservative"  # Cache only expensive operations, short TTL
    DISABLED = "disabled"     # No caching


class CacheKeyType(str, Enum):
    """Types of cache keys for different data."""

    QUERY_RESULT = "query_result"
    TOOL_EXECUTION = "tool_exec"
    PLANNING_RESULT = "planning"
    REASONING_TRACE = "reasoning"
    DATA_ANALYSIS = "analysis"
    VISUALIZATION = "viz"


@dataclass
class CacheMetrics:
    """Cache performance metrics."""

    total_hits: int = 0
    total_misses: int = 0
    total_sets: int = 0
    total_evictions: int = 0
    total_invalidations: int = 0
    hit_latency_ms: List[float] = field(default_factory=list)
    miss_latency_ms: List[float] = field(default_factory=list)
    cache_size_bytes: int = 0
    last_updated: float = field(default_factory=time.time)

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total_requests = self.total_hits + self.total_misses
        return self.total_hits / total_requests if total_requests > 0 else 0.0

    @property
    def avg_hit_latency_ms(self) -> float:
        """Average latency for cache hits."""
        return sum(self.hit_latency_ms) / len(self.hit_latency_ms) if self.hit_latency_ms else 0.0

    @property
    def avg_miss_latency_ms(self) -> float:
        """Average latency for cache misses (includes computation time)."""
        return sum(self.miss_latency_ms) / len(self.miss_latency_ms) if self.miss_latency_ms else 0.0


@dataclass
class CacheEntry:
    """Represents a cached entry with metadata."""

    key: str
    value: Any
    created_at: float
    ttl_seconds: float
    access_count: int = 0
    last_accessed: float = field(default_factory=time.time)
    key_type: CacheKeyType = CacheKeyType.QUERY_RESULT
    size_bytes: int = 0
    tags: Set[str] = field(default_factory=set)

    @property
    def is_expired(self) -> bool:
        """Check if the cache entry has expired."""
        return time.time() > (self.created_at + self.ttl_seconds)

    @property
    def age_seconds(self) -> float:
        """Get the age of the cache entry in seconds."""
        return time.time() - self.created_at


class CacheKeyGenerator:
    """Generates deterministic cache keys from queries and context."""

    def __init__(self, namespace: str = "brain_researcher"):
        """
        Initialize the cache key generator.

        Args:
            namespace: Namespace for cache keys
        """
        self.namespace = namespace

    def generate_key(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        key_type: CacheKeyType = CacheKeyType.QUERY_RESULT,
        **kwargs
    ) -> str:
        """
        Generate a deterministic cache key.

        Args:
            query: The query string
            context: Additional context that affects the result
            key_type: Type of cache key
            **kwargs: Additional parameters

        Returns:
            Deterministic cache key
        """
        # Build components for key generation
        components = {
            "query": self._normalize_query(query),
            "context": self._normalize_context(context or {}),
            "type": key_type.value,
            "kwargs": self._normalize_context(kwargs)
        }

        # Create deterministic JSON representation
        key_data = json.dumps(components, sort_keys=True, separators=(',', ':'))

        # Generate hash
        key_hash = hashlib.sha256(key_data.encode()).hexdigest()[:32]

        # Build final key
        cache_key = f"{self.namespace}:{key_type.value}:{key_hash}"

        return cache_key

    def _normalize_query(self, query: str) -> str:
        """Normalize query for consistent key generation."""
        # Remove extra whitespace, convert to lowercase
        normalized = " ".join(query.strip().lower().split())
        return normalized

    def _normalize_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize context dictionary for consistent key generation."""
        normalized = {}

        for key, value in context.items():
            # Skip non-deterministic values
            if key in ['timestamp', 'session_id', 'request_id']:
                continue

            # Convert to string for consistency
            if isinstance(value, (dict, list)):
                normalized[key] = json.dumps(value, sort_keys=True)
            else:
                normalized[key] = str(value)

        return normalized


class QueryCacheManager:
    """
    Redis-backed cache manager for query results and memoization.

    Features:
    - TTL support with configurable expiration
    - Cache invalidation on data updates
    - Hit rate metrics (target >60%)
    - Configurable cache policies
    - Memory-efficient serialization
    """

    def __init__(
        self,
        redis_client: Optional[redis.Redis] = None,
        ttl_seconds: int = 3600,
        max_memory_mb: int = 512,
        policy: CachePolicy = CachePolicy.MODERATE,
        namespace: str = "brain_researcher"
    ):
        """
        Initialize the cache manager.

        Args:
            redis_client: Redis client instance (will create if None)
            ttl_seconds: Default TTL for cache entries
            max_memory_mb: Maximum memory usage in MB
            policy: Cache policy to use
            namespace: Namespace for cache keys
        """
        self.ttl_seconds = ttl_seconds
        self.max_memory_mb = max_memory_mb
        self.policy = policy
        self.namespace = namespace

        # Initialize Redis client
        if redis_client:
            self.redis = redis_client
        else:
            self.redis = self._create_redis_client()

        # Initialize components
        self.key_generator = CacheKeyGenerator(namespace)
        self.metrics = CacheMetrics()

        # Cache invalidation tracking
        self.invalidation_patterns: Dict[str, List[str]] = {}

        # Policy-specific configurations
        self.policy_config = self._get_policy_config()

        logger.info(f"Cache manager initialized with policy: {policy.value}")

    def _create_redis_client(self) -> redis.Redis:
        """Create Redis client with fallback to fakeredis for testing."""
        try:
            import os
            redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
            client = redis.from_url(redis_url, decode_responses=False)

            # Test connection
            client.ping()
            logger.info(f"Connected to Redis at {redis_url}")

            return client

        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}, using fakeredis")

            try:
                import fakeredis
                return fakeredis.FakeRedis(decode_responses=False)
            except ImportError:
                raise Exception("Neither Redis nor fakeredis available")

    def _get_policy_config(self) -> Dict[str, Any]:
        """Get configuration based on cache policy."""
        configs = {
            CachePolicy.AGGRESSIVE: {
                "default_ttl": 7200,  # 2 hours
                "cache_everything": True,
                "min_execution_time": 0.0,  # Cache all results
            },
            CachePolicy.MODERATE: {
                "default_ttl": 3600,  # 1 hour
                "cache_everything": False,
                "min_execution_time": 1.0,  # Cache if execution > 1s
            },
            CachePolicy.CONSERVATIVE: {
                "default_ttl": 900,  # 15 minutes
                "cache_everything": False,
                "min_execution_time": 5.0,  # Cache if execution > 5s
            },
            CachePolicy.DISABLED: {
                "default_ttl": 0,
                "cache_everything": False,
                "min_execution_time": float('inf'),  # Never cache
            }
        }

        return configs.get(self.policy, configs[CachePolicy.MODERATE])

    def get_or_compute(
        self,
        key: str,
        compute_fn: Callable[[], Any],
        ttl_seconds: Optional[int] = None,
        force_refresh: bool = False,
        key_type: CacheKeyType = CacheKeyType.QUERY_RESULT,
        tags: Optional[Set[str]] = None
    ) -> Any:
        """
        Get value from cache or compute if not present.

        Args:
            key: Cache key
            compute_fn: Function to compute the value if not cached
            ttl_seconds: TTL for this entry (uses default if None)
            force_refresh: Force recomputation even if cached
            key_type: Type of cache key for metrics
            tags: Tags for invalidation

        Returns:
            Cached or computed value
        """
        start_time = time.time()

        # Check if caching is disabled
        if self.policy == CachePolicy.DISABLED:
            return compute_fn()

        # Check cache first (unless force refresh)
        if not force_refresh:
            cached_value = self._get_from_cache(key)
            if cached_value is not None:
                # Cache hit
                hit_latency = (time.time() - start_time) * 1000
                self.metrics.hit_latency_ms.append(hit_latency)
                self.metrics.total_hits += 1
                self.metrics.last_updated = time.time()

                logger.debug(f"Cache hit for key: {key[:32]}...")
                return cached_value

        # Cache miss - compute value
        logger.debug(f"Cache miss for key: {key[:32]}...")

        compute_start = time.time()
        try:
            value = compute_fn()
            execution_time = time.time() - compute_start

            # Decide whether to cache based on policy
            should_cache = self._should_cache(execution_time, key_type)

            if should_cache:
                # Store in cache
                effective_ttl = ttl_seconds or self.policy_config["default_ttl"]
                self._set_in_cache(key, value, effective_ttl, key_type, tags or set())
                self.metrics.total_sets += 1

        except Exception as e:
            logger.error(f"Compute function failed for key {key[:32]}...: {e}")
            raise

        # Update metrics
        miss_latency = (time.time() - start_time) * 1000
        self.metrics.miss_latency_ms.append(miss_latency)
        self.metrics.total_misses += 1
        self.metrics.last_updated = time.time()

        return value

    def _should_cache(self, execution_time: float, key_type: CacheKeyType) -> bool:
        """Determine if a result should be cached based on policy and execution time."""
        if self.policy == CachePolicy.DISABLED:
            return False

        if self.policy_config["cache_everything"]:
            return True

        # Cache based on execution time threshold
        return execution_time >= self.policy_config["min_execution_time"]

    def _get_from_cache(self, key: str) -> Any:
        """Get value from Redis cache."""
        try:
            data = self.redis.get(key)
            if data is None:
                return None

            # Deserialize
            cache_entry = pickle.loads(data)

            # Check expiration
            if cache_entry.is_expired:
                self.redis.delete(key)
                return None

            # Update access info
            cache_entry.access_count += 1
            cache_entry.last_accessed = time.time()

            # Store updated entry
            self.redis.set(key, pickle.dumps(cache_entry), ex=int(cache_entry.ttl_seconds))

            return cache_entry.value

        except Exception as e:
            logger.error(f"Failed to get from cache: {e}")
            return None

    def _set_in_cache(
        self,
        key: str,
        value: Any,
        ttl_seconds: int,
        key_type: CacheKeyType,
        tags: Set[str]
    ):
        """Set value in Redis cache."""
        try:
            # Calculate size (approximate)
            serialized_value = pickle.dumps(value)
            size_bytes = len(serialized_value)

            # Create cache entry
            cache_entry = CacheEntry(
                key=key,
                value=value,
                created_at=time.time(),
                ttl_seconds=ttl_seconds,
                key_type=key_type,
                size_bytes=size_bytes,
                tags=tags
            )

            # Serialize and store
            serialized_entry = pickle.dumps(cache_entry)
            self.redis.set(key, serialized_entry, ex=ttl_seconds)

            # Update tags for invalidation
            for tag in tags:
                tag_key = f"{self.namespace}:tag:{tag}"
                self.redis.sadd(tag_key, key)
                self.redis.expire(tag_key, ttl_seconds)

            # Update metrics
            self.metrics.cache_size_bytes += size_bytes

            logger.debug(f"Cached value for key: {key[:32]}... (TTL: {ttl_seconds}s)")

        except Exception as e:
            logger.error(f"Failed to set cache: {e}")

    def invalidate(
        self,
        pattern: Optional[str] = None,
        tags: Optional[Set[str]] = None,
        key_type: Optional[CacheKeyType] = None
    ) -> int:
        """
        Invalidate cache entries by pattern, tags, or key type.

        Args:
            pattern: Redis key pattern to match
            tags: Tags to invalidate
            key_type: Specific key type to invalidate

        Returns:
            Number of keys invalidated
        """
        invalidated_count = 0

        try:
            keys_to_delete = set()

            # Invalidate by pattern
            if pattern:
                pattern_key = f"{self.namespace}:{pattern}"
                matching_keys = self.redis.keys(pattern_key)
                keys_to_delete.update(matching_keys)

            # Invalidate by tags
            if tags:
                for tag in tags:
                    tag_key = f"{self.namespace}:tag:{tag}"
                    tagged_keys = self.redis.smembers(tag_key)
                    keys_to_delete.update(tagged_keys)

                    # Clean up tag set
                    self.redis.delete(tag_key)

            # Invalidate by key type
            if key_type:
                type_pattern = f"{self.namespace}:{key_type.value}:*"
                matching_keys = self.redis.keys(type_pattern)
                keys_to_delete.update(matching_keys)

            # Delete all identified keys
            if keys_to_delete:
                invalidated_count = self.redis.delete(*keys_to_delete)
                self.metrics.total_invalidations += invalidated_count

                logger.info(f"Invalidated {invalidated_count} cache entries")

        except Exception as e:
            logger.error(f"Cache invalidation failed: {e}")

        return invalidated_count

    def warm_cache(
        self,
        queries: List[str],
        context_list: Optional[List[Dict[str, Any]]] = None,
        compute_fn: Optional[Callable[[str, Dict[str, Any]], Any]] = None
    ):
        """
        Warm the cache with common queries.

        Args:
            queries: List of queries to warm
            context_list: List of contexts for each query
            compute_fn: Function to compute values for warming
        """
        if not compute_fn:
            logger.warning("No compute function provided for cache warming")
            return

        context_list = context_list or [{}] * len(queries)

        logger.info(f"Warming cache with {len(queries)} queries")

        for i, query in enumerate(queries):
            try:
                context = context_list[i] if i < len(context_list) else {}
                cache_key = self.key_generator.generate_key(query, context)

                # Compute and cache
                self.get_or_compute(
                    cache_key,
                    lambda q=query, c=context: compute_fn(q, c),
                    tags={"warmup"}
                )

            except Exception as e:
                logger.error(f"Failed to warm cache for query {i}: {e}")

        logger.info("Cache warming completed")

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive cache statistics."""
        try:
            # Get Redis info
            redis_info = self.redis.info()
            memory_used = redis_info.get('used_memory', 0)

            # Calculate additional metrics
            total_requests = self.metrics.total_hits + self.metrics.total_misses

            stats = {
                "hit_rate": self.metrics.hit_rate,
                "total_hits": self.metrics.total_hits,
                "total_misses": self.metrics.total_misses,
                "total_requests": total_requests,
                "total_sets": self.metrics.total_sets,
                "total_invalidations": self.metrics.total_invalidations,
                "avg_hit_latency_ms": self.metrics.avg_hit_latency_ms,
                "avg_miss_latency_ms": self.metrics.avg_miss_latency_ms,
                "memory_used_bytes": memory_used,
                "memory_limit_bytes": self.max_memory_mb * 1024 * 1024,
                "memory_usage_percent": (memory_used / (self.max_memory_mb * 1024 * 1024)) * 100,
                "policy": self.policy.value,
                "default_ttl_seconds": self.policy_config["default_ttl"],
                "last_updated": datetime.fromtimestamp(self.metrics.last_updated).isoformat()
            }

            return stats

        except Exception as e:
            logger.error(f"Failed to get cache stats: {e}")
            return {"error": str(e)}

    def clear_all(self) -> int:
        """Clear all cache entries in namespace."""
        try:
            pattern = f"{self.namespace}:*"
            keys = self.redis.keys(pattern)

            if keys:
                deleted = self.redis.delete(*keys)
                logger.info(f"Cleared {deleted} cache entries")

                # Reset metrics
                self.metrics = CacheMetrics()

                return deleted

            return 0

        except Exception as e:
            logger.error(f"Failed to clear cache: {e}")
            return 0


def cached(
    ttl_seconds: int = 3600,
    key_type: CacheKeyType = CacheKeyType.QUERY_RESULT,
    cache_manager: Optional[QueryCacheManager] = None
):
    """
    Decorator for automatic function result caching.

    Args:
        ttl_seconds: TTL for cached results
        key_type: Type of cache key
        cache_manager: Cache manager instance (uses global if None)

    Returns:
        Decorated function with caching
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            nonlocal cache_manager

            if not cache_manager:
                # Get or create global cache manager
                cache_manager = get_global_cache_manager()

            # Generate cache key from function name and arguments
            key_data = {
                "function": func.__name__,
                "args": str(args),
                "kwargs": kwargs
            }

            cache_key = cache_manager.key_generator.generate_key(
                str(key_data), key_type=key_type
            )

            # Use cache manager
            return cache_manager.get_or_compute(
                cache_key,
                lambda: func(*args, **kwargs),
                ttl_seconds=ttl_seconds,
                key_type=key_type
            )

        return wrapper
    return decorator


# Global cache manager instance
_global_cache_manager: Optional[QueryCacheManager] = None


def get_global_cache_manager() -> QueryCacheManager:
    """Get or create the global cache manager."""
    global _global_cache_manager

    if _global_cache_manager is None:
        _global_cache_manager = QueryCacheManager()

    return _global_cache_manager


def set_global_cache_manager(cache_manager: QueryCacheManager):
    """Set the global cache manager."""
    global _global_cache_manager
    _global_cache_manager = cache_manager