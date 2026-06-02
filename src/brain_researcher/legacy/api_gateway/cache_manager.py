"""
Cache Manager for API Gateway.

Provides intelligent caching capabilities for HTTP responses with:

Features:
- Redis-based distributed caching
- TTL-based expiration
- Cache invalidation strategies
- ETag and conditional request support
- Vary header support for cache keys
- Compression-aware caching
- Cache statistics and monitoring
- Cache warming and preloading
- Cache bypass for authenticated requests
"""

import gzip
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

import redis
from fastapi import Request, Response
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class CacheStrategy(str, Enum):
    """Cache strategy types."""

    LRU = "lru"  # Least Recently Used
    LFU = "lfu"  # Least Frequently Used
    TTL = "ttl"  # Time To Live
    FIFO = "fifo"  # First In First Out


class CacheStatus(str, Enum):
    """Cache hit/miss status."""

    HIT = "hit"
    MISS = "miss"
    STALE = "stale"
    BYPASS = "bypass"
    ERROR = "error"


@dataclass
class CacheRule:
    """Cache rule configuration."""

    name: str
    path_patterns: List[str]
    methods: List[str] = None
    ttl_seconds: int = 300
    vary_headers: List[str] = None
    cache_private: bool = False
    cache_authenticated: bool = False
    max_size_bytes: int = 1024 * 1024  # 1MB
    compress_response: bool = False
    enabled: bool = True
    priority: int = 0

    def __post_init__(self):
        if self.methods is None:
            self.methods = ["GET", "HEAD"]
        if self.vary_headers is None:
            self.vary_headers = []


class CacheEntry(BaseModel):
    """Cache entry model."""

    key: str = Field(..., description="Cache key")
    data: bytes = Field(..., description="Cached response data")
    headers: Dict[str, str] = Field(..., description="Response headers")
    status_code: int = Field(..., description="HTTP status code")
    content_type: str = Field(..., description="Content type")
    compressed: bool = Field(False, description="Whether data is compressed")
    created_at: datetime = Field(..., description="Creation timestamp")
    expires_at: datetime = Field(..., description="Expiration timestamp")
    access_count: int = Field(0, description="Number of times accessed")
    last_accessed: datetime = Field(..., description="Last access timestamp")
    etag: Optional[str] = Field(None, description="ETag for conditional requests")
    vary_values: Dict[str, str] = Field(
        default_factory=dict, description="Vary header values"
    )


class CacheStats(BaseModel):
    """Cache statistics."""

    total_requests: int = Field(0, description="Total cache requests")
    cache_hits: int = Field(0, description="Cache hits")
    cache_misses: int = Field(0, description="Cache misses")
    cache_bypasses: int = Field(0, description="Cache bypasses")
    cache_errors: int = Field(0, description="Cache errors")
    total_size_bytes: int = Field(0, description="Total cache size in bytes")
    entry_count: int = Field(0, description="Number of cache entries")
    hit_rate: float = Field(0.0, description="Cache hit rate percentage")
    average_response_time_ms: float = Field(0.0, description="Average response time")


class CacheManager:
    """Main cache manager implementation."""

    def __init__(
        self,
        redis_client: redis.Redis,
        default_ttl: int = 300,
        max_size_mb: int = 512,
        compression_threshold: int = 1024,
    ):
        """Initialize cache manager.

        Args:
            redis_client: Redis client for cache storage
            default_ttl: Default TTL in seconds
            max_size_mb: Maximum cache size in MB
            compression_threshold: Minimum size for compression
        """
        self.redis = redis_client
        self.default_ttl = default_ttl
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.compression_threshold = compression_threshold

        # Cache rules
        self.rules: List[CacheRule] = []

        # Statistics
        self.stats = CacheStats()

        # Cache key prefix
        self.key_prefix = "gateway:cache:"

        # Load default rules
        self._load_default_rules()

    def _load_default_rules(self):
        """Load default cache rules."""
        default_rules = [
            CacheRule(
                name="static_resources",
                path_patterns=["/static/**", "/assets/**", "/images/**"],
                ttl_seconds=3600,  # 1 hour
                compress_response=True,
                priority=1,
            ),
            CacheRule(
                name="api_search_results",
                path_patterns=["/api/kg/search/**", "/api/orchestrator/search/**"],
                ttl_seconds=300,  # 5 minutes
                vary_headers=["Authorization", "Accept-Language"],
                cache_authenticated=True,
                priority=2,
            ),
            CacheRule(
                name="health_checks",
                path_patterns=["/health", "/api/*/health"],
                ttl_seconds=60,  # 1 minute
                cache_private=True,
                priority=3,
            ),
        ]

        self.rules.extend(default_rules)
        self.rules.sort(key=lambda r: r.priority, reverse=True)

    def add_rule(self, rule: CacheRule):
        """Add a cache rule.

        Args:
            rule: Cache rule to add
        """
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority, reverse=True)

    def remove_rule(self, rule_name: str) -> bool:
        """Remove a cache rule by name.

        Args:
            rule_name: Name of rule to remove

        Returns:
            True if rule was removed
        """
        for i, rule in enumerate(self.rules):
            if rule.name == rule_name:
                del self.rules[i]
                return True
        return False

    async def get_cached_response(
        self, request: Request, cache_key: Optional[str] = None
    ) -> Tuple[Optional[Response], CacheStatus]:
        """Get cached response for a request.

        Args:
            request: HTTP request
            cache_key: Optional cache key override

        Returns:
            Tuple of (response, cache_status)
        """
        try:
            self.stats.total_requests += 1

            # Check if request should be cached
            rule = self._find_cache_rule(request)
            if not rule:
                return None, CacheStatus.BYPASS

            # Generate cache key
            key = cache_key or self._generate_cache_key(request, rule)

            # Check for cached entry
            cached_entry = await self._get_cache_entry(key)
            if not cached_entry:
                self.stats.cache_misses += 1
                return None, CacheStatus.MISS

            # Check expiration
            if datetime.utcnow() > cached_entry.expires_at:
                await self._delete_cache_entry(key)
                self.stats.cache_misses += 1
                return None, CacheStatus.STALE

            # Check conditional requests (ETag)
            if cached_entry.etag:
                if_none_match = request.headers.get("If-None-Match")
                if if_none_match == cached_entry.etag:
                    # Return 304 Not Modified
                    self.stats.cache_hits += 1
                    await self._update_access_stats(key, cached_entry)

                    return (
                        Response(
                            status_code=304,
                            headers={
                                "ETag": cached_entry.etag,
                                "Cache-Control": f"max-age={rule.ttl_seconds}",
                                "X-Cache": "HIT",
                            },
                        ),
                        CacheStatus.HIT,
                    )

            # Decompress if needed
            response_data = cached_entry.data
            if cached_entry.compressed:
                try:
                    response_data = gzip.decompress(response_data)
                except:
                    logger.error(f"Failed to decompress cached response for {key}")
                    return None, CacheStatus.ERROR

            # Update access statistics
            await self._update_access_stats(key, cached_entry)

            # Create response
            headers = cached_entry.headers.copy()
            headers["X-Cache"] = "HIT"
            headers["Age"] = str(
                int((datetime.utcnow() - cached_entry.created_at).total_seconds())
            )

            self.stats.cache_hits += 1

            return (
                Response(
                    content=response_data,
                    status_code=cached_entry.status_code,
                    headers=headers,
                    media_type=cached_entry.content_type,
                ),
                CacheStatus.HIT,
            )

        except Exception as e:
            logger.error(f"Cache get error: {e}")
            self.stats.cache_errors += 1
            return None, CacheStatus.ERROR

    async def cache_response(
        self, request: Request, response: Response, cache_key: Optional[str] = None
    ) -> bool:
        """Cache a response.

        Args:
            request: HTTP request
            response: HTTP response to cache
            cache_key: Optional cache key override

        Returns:
            True if response was cached
        """
        try:
            # Check if response should be cached
            rule = self._find_cache_rule(request)
            if not rule:
                return False

            # Check response status
            if response.status_code not in [200, 203, 300, 301, 302, 404, 410]:
                return False

            # Check response size
            response_size = len(response.body) if hasattr(response, "body") else 0
            if response_size > rule.max_size_bytes:
                logger.debug(f"Response too large for cache: {response_size} bytes")
                return False

            # Check cache control headers
            cache_control = response.headers.get("Cache-Control", "")
            if "no-cache" in cache_control or "no-store" in cache_control:
                return False

            # Generate cache key
            key = cache_key or self._generate_cache_key(request, rule)

            # Prepare response data
            response_data = response.body if hasattr(response, "body") else b""

            # Compress if configured and data is large enough
            compressed = False
            if (
                rule.compress_response
                and len(response_data) >= self.compression_threshold
            ):
                try:
                    response_data = gzip.compress(response_data)
                    compressed = True
                except:
                    logger.warning(f"Failed to compress response for {key}")

            # Generate ETag
            etag = hashlib.md5(response_data).hexdigest()

            # Prepare vary values
            vary_values = {}
            for header in rule.vary_headers:
                vary_values[header] = request.headers.get(header, "")

            # Create cache entry
            cache_entry = CacheEntry(
                key=key,
                data=response_data,
                headers=dict(response.headers),
                status_code=response.status_code,
                content_type=response.headers.get(
                    "Content-Type", "application/octet-stream"
                ),
                compressed=compressed,
                created_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(seconds=rule.ttl_seconds),
                last_accessed=datetime.utcnow(),
                etag=etag,
                vary_values=vary_values,
            )

            # Store cache entry
            await self._store_cache_entry(key, cache_entry, rule.ttl_seconds)

            # Add cache headers to response
            response.headers["ETag"] = etag
            response.headers["Cache-Control"] = f"max-age={rule.ttl_seconds}"
            response.headers["X-Cache"] = "MISS"

            return True

        except Exception as e:
            logger.error(f"Cache store error: {e}")
            return False

    async def invalidate_cache(
        self,
        pattern: Optional[str] = None,
        path: Optional[str] = None,
        service: Optional[str] = None,
    ) -> int:
        """Invalidate cache entries.

        Args:
            pattern: Cache key pattern to match
            path: Request path to invalidate
            service: Service name to invalidate

        Returns:
            Number of entries invalidated
        """
        try:
            keys_to_delete = []

            if pattern:
                # Find keys matching pattern
                search_pattern = f"{self.key_prefix}{pattern}"
                keys_to_delete = self.redis.keys(search_pattern)

            elif path:
                # Invalidate by path
                # This is simplified - in practice you'd maintain path->key mappings
                search_pattern = f"{self.key_prefix}*{path}*"
                keys_to_delete = self.redis.keys(search_pattern)

            elif service:
                # Invalidate by service
                search_pattern = f"{self.key_prefix}*{service}*"
                keys_to_delete = self.redis.keys(search_pattern)

            # Delete keys
            if keys_to_delete:
                self.redis.delete(*keys_to_delete)

            logger.info(f"Invalidated {len(keys_to_delete)} cache entries")
            return len(keys_to_delete)

        except Exception as e:
            logger.error(f"Cache invalidation error: {e}")
            return 0

    async def get_cache_stats(self) -> CacheStats:
        """Get cache statistics.

        Returns:
            Cache statistics
        """
        try:
            # Update current statistics
            total_size = 0
            entry_count = 0

            # Get all cache keys
            cache_keys = self.redis.keys(f"{self.key_prefix}*")
            entry_count = len(cache_keys)

            # Calculate total size (approximate)
            for key in cache_keys[:100]:  # Sample first 100 for performance
                try:
                    size = self.redis.memory_usage(key)
                    if size:
                        total_size += size
                except:
                    pass

            # Extrapolate if we sampled
            if len(cache_keys) > 100:
                total_size = int(total_size * len(cache_keys) / 100)

            self.stats.total_size_bytes = total_size
            self.stats.entry_count = entry_count

            # Calculate hit rate
            total_cache_requests = self.stats.cache_hits + self.stats.cache_misses
            self.stats.hit_rate = (
                (self.stats.cache_hits / total_cache_requests * 100)
                if total_cache_requests > 0
                else 0.0
            )

            return self.stats

        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return self.stats

    async def clear_cache(self) -> int:
        """Clear all cache entries.

        Returns:
            Number of entries cleared
        """
        try:
            cache_keys = self.redis.keys(f"{self.key_prefix}*")
            if cache_keys:
                self.redis.delete(*cache_keys)

            # Reset stats
            self.stats = CacheStats()

            logger.info(f"Cleared {len(cache_keys)} cache entries")
            return len(cache_keys)

        except Exception as e:
            logger.error(f"Cache clear error: {e}")
            return 0

    def _find_cache_rule(self, request: Request) -> Optional[CacheRule]:
        """Find applicable cache rule for request.

        Args:
            request: HTTP request

        Returns:
            Matching cache rule or None
        """
        for rule in self.rules:
            if not rule.enabled:
                continue

            # Check method
            if request.method not in rule.methods:
                continue

            # Check path patterns
            path_matches = False
            for pattern in rule.path_patterns:
                if self._path_matches(request.url.path, pattern):
                    path_matches = True
                    break

            if not path_matches:
                continue

            # Check authentication requirements
            if not rule.cache_authenticated:
                auth_header = request.headers.get("Authorization")
                if auth_header:
                    continue

            return rule

        return None

    def _path_matches(self, path: str, pattern: str) -> bool:
        """Check if path matches pattern."""
        import re

        regex_pattern = pattern.replace("**", ".*").replace("*", "[^/]*")
        regex_pattern = f"^{regex_pattern}$"
        return bool(re.match(regex_pattern, path))

    def _generate_cache_key(self, request: Request, rule: CacheRule) -> str:
        """Generate cache key for request.

        Args:
            request: HTTP request
            rule: Cache rule

        Returns:
            Cache key string
        """
        # Base components
        key_parts = [
            request.method,
            request.url.path,
        ]

        # Add query parameters (sorted for consistency)
        if request.query_params:
            query_string = "&".join(
                f"{k}={v}" for k, v in sorted(request.query_params.items())
            )
            key_parts.append(query_string)

        # Add vary header values
        for header in rule.vary_headers:
            header_value = request.headers.get(header, "")
            key_parts.append(f"{header}:{header_value}")

        # Create hash of all components
        key_string = "|".join(key_parts)
        key_hash = hashlib.sha256(key_string.encode()).hexdigest()

        return f"{self.key_prefix}{rule.name}:{key_hash}"

    async def _get_cache_entry(self, key: str) -> Optional[CacheEntry]:
        """Get cache entry from Redis.

        Args:
            key: Cache key

        Returns:
            Cache entry or None
        """
        try:
            data = self.redis.get(key)
            if data:
                entry_data = json.loads(data)
                # Convert datetime strings
                entry_data["created_at"] = datetime.fromisoformat(
                    entry_data["created_at"]
                )
                entry_data["expires_at"] = datetime.fromisoformat(
                    entry_data["expires_at"]
                )
                entry_data["last_accessed"] = datetime.fromisoformat(
                    entry_data["last_accessed"]
                )

                # Decode base64 data
                import base64

                entry_data["data"] = base64.b64decode(entry_data["data"])

                return CacheEntry(**entry_data)
            return None

        except Exception as e:
            logger.error(f"Error getting cache entry {key}: {e}")
            return None

    async def _store_cache_entry(self, key: str, entry: CacheEntry, ttl: int):
        """Store cache entry in Redis.

        Args:
            key: Cache key
            entry: Cache entry
            ttl: TTL in seconds
        """
        try:
            # Prepare data for storage
            import base64

            entry_data = entry.dict()
            entry_data["data"] = base64.b64encode(entry.data).decode("ascii")

            # Convert datetime objects to strings
            entry_data["created_at"] = entry.created_at.isoformat()
            entry_data["expires_at"] = entry.expires_at.isoformat()
            entry_data["last_accessed"] = entry.last_accessed.isoformat()

            # Store with TTL
            self.redis.setex(key, ttl, json.dumps(entry_data))

        except Exception as e:
            logger.error(f"Error storing cache entry {key}: {e}")

    async def _update_access_stats(self, key: str, entry: CacheEntry):
        """Update cache entry access statistics.

        Args:
            key: Cache key
            entry: Cache entry
        """
        try:
            entry.access_count += 1
            entry.last_accessed = datetime.utcnow()

            # Update in Redis
            await self._store_cache_entry(
                key, entry, int((entry.expires_at - datetime.utcnow()).total_seconds())
            )

        except Exception as e:
            logger.error(f"Error updating access stats for {key}: {e}")

    async def _delete_cache_entry(self, key: str):
        """Delete cache entry from Redis.

        Args:
            key: Cache key
        """
        try:
            self.redis.delete(key)
        except Exception as e:
            logger.error(f"Error deleting cache entry {key}: {e}")


# Export components
__all__ = [
    "CacheManager",
    "CacheRule",
    "CacheEntry",
    "CacheStats",
    "CacheStrategy",
    "CacheStatus",
]
