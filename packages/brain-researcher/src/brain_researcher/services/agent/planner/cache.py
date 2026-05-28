"""Caching abstraction for planner components.

Provides Redis-backed caching with automatic fallback to in-memory TTL dict
when Redis is unavailable. Used primarily for preflight check results to avoid
repeated filesystem/import checks.

Environment Variables:
    BR_REDIS_URL: Redis connection URL (optional)
    BR_PREFLIGHT_TTL_SECONDS: Cache TTL in seconds (default: 900)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional

from brain_researcher.services.agent.planner.config_loader import load_planner_config


def _load_cache_settings() -> Dict[str, Any]:
    """Load cache-related settings from planner config."""
    config = load_planner_config("preflight.yaml")
    return config.get("cache", {})

logger = logging.getLogger(__name__)

# Try to import Redis, fallback gracefully if unavailable
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None  # type: ignore


@dataclass
class CacheEntry:
    """Cache entry with value and expiration."""
    value: Any
    expires_at: float  # Unix timestamp


class PreflightCache:
    """Cache abstraction for preflight check results.

    Automatically uses Redis if available, otherwise falls back to in-memory
    dict with TTL-based expiration.

    Examples:
        >>> cache = PreflightCache(ttl_seconds=900)
        >>> cache.set("fsl_bet", {"passed": True})
        >>> result = cache.get("fsl_bet")
        >>> cache.clear()
    """

    def __init__(
        self,
        ttl_seconds: Optional[int] = None,
        redis_url: Optional[str] = None,
    ):
        """Initialize cache.

        Args:
            ttl_seconds: Time-to-live in seconds (default from env or 900)
            redis_url: Redis URL (default from env or None for in-memory)
        """
        cache_settings = _load_cache_settings()

        configured_ttl = cache_settings.get("ttl_seconds")
        env_ttl = os.getenv("BR_PREFLIGHT_TTL_SECONDS")

        if ttl_seconds:
            self.ttl_seconds = ttl_seconds
        elif env_ttl:
            self.ttl_seconds = int(env_ttl)
        elif configured_ttl:
            self.ttl_seconds = int(configured_ttl)
        else:
            self.ttl_seconds = 900

        # Try Redis connection
        redis_url = redis_url or os.getenv("BR_REDIS_URL")
        self._redis_client: Optional[Any] = None
        self._use_redis = False

        if redis_url and REDIS_AVAILABLE:
            try:
                self._redis_client = redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                # Test connection
                self._redis_client.ping()
                self._use_redis = True
                logger.info(f"Using Redis cache at {redis_url}")
            except Exception as e:
                logger.warning(
                    f"Redis unavailable ({e}), falling back to in-memory cache"
                )
                self._redis_client = None

        # Fallback in-memory store
        self._memory_store: Dict[str, CacheEntry] = {}

        if not self._use_redis:
            logger.info("Using in-memory TTL cache")

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value dict or None if not found/expired
        """
        if self._use_redis and self._redis_client:
            try:
                value = self._redis_client.get(f"preflight:{key}")
                if value:
                    return json.loads(value)
            except Exception as e:
                logger.warning(f"Redis get error: {e}")
                # Fall through to memory cache

        # Check in-memory cache
        entry = self._memory_store.get(key)
        if entry:
            if time.time() < entry.expires_at:
                return entry.value
            else:
                # Expired, remove
                del self._memory_store[key]

        return None

    def set(self, key: str, value: Dict[str, Any]) -> None:
        """Store value in cache with TTL.

        Args:
            key: Cache key
            value: Value to cache (must be JSON-serializable)
        """
        if self._use_redis and self._redis_client:
            try:
                self._redis_client.setex(
                    f"preflight:{key}",
                    self.ttl_seconds,
                    json.dumps(value),
                )
            except Exception as e:
                logger.warning(f"Redis set error: {e}")
                # Fall through to memory cache

        # Also store in memory cache (for hybrid/fallback)
        self._memory_store[key] = CacheEntry(
            value=value,
            expires_at=time.time() + self.ttl_seconds,
        )

    def get_many(self, keys: list[str]) -> Dict[str, Optional[Dict[str, Any]]]:
        """Batch get multiple keys.

        Args:
            keys: List of cache keys

        Returns:
            Dict mapping keys to values (None for misses)
        """
        results = {}

        if self._use_redis and self._redis_client:
            try:
                # Use Redis pipeline for efficiency
                pipe = self._redis_client.pipeline()
                for key in keys:
                    pipe.get(f"preflight:{key}")
                redis_values = pipe.execute()

                for key, value in zip(keys, redis_values):
                    if value:
                        results[key] = json.loads(value)
                    else:
                        results[key] = None

                return results
            except Exception as e:
                logger.warning(f"Redis batch get error: {e}")
                # Fall through to memory cache

        # Memory cache fallback
        for key in keys:
            results[key] = self.get(key)

        return results

    def set_many(self, items: Dict[str, Dict[str, Any]]) -> None:
        """Batch set multiple key-value pairs.

        Args:
            items: Dict mapping keys to values
        """
        if self._use_redis and self._redis_client:
            try:
                # Use Redis pipeline for efficiency
                pipe = self._redis_client.pipeline()
                for key, value in items.items():
                    pipe.setex(
                        f"preflight:{key}",
                        self.ttl_seconds,
                        json.dumps(value),
                    )
                pipe.execute()
            except Exception as e:
                logger.warning(f"Redis batch set error: {e}")
                # Fall through to memory cache

        # Memory cache fallback
        now = time.time()
        for key, value in items.items():
            self._memory_store[key] = CacheEntry(
                value=value,
                expires_at=now + self.ttl_seconds,
            )

    def clear(self) -> None:
        """Clear all cache entries."""
        if self._use_redis and self._redis_client:
            try:
                # Delete all preflight:* keys
                cursor = 0
                while True:
                    cursor, keys = self._redis_client.scan(
                        cursor=cursor,
                        match="preflight:*",
                        count=100,
                    )
                    if keys:
                        self._redis_client.delete(*keys)
                    if cursor == 0:
                        break
            except Exception as e:
                logger.warning(f"Redis clear error: {e}")

        # Clear memory cache
        self._memory_store.clear()

    def evict_expired(self) -> int:
        """Remove expired entries from memory cache.

        Returns:
            Number of entries evicted
        """
        now = time.time()
        expired_keys = [
            key for key, entry in self._memory_store.items()
            if now >= entry.expires_at
        ]

        for key in expired_keys:
            del self._memory_store[key]

        return len(expired_keys)


def compute_cache_key(tool_id: str, digest: str) -> str:
    """Compute cache key for a tool.

    Args:
        tool_id: Tool identifier
        digest: Hash of tool configuration (container image path or python module)

    Returns:
        Cache key string

    Examples:
        >>> compute_cache_key("fsl.bet.run", "abc123")
        'fsl.bet.run:abc123'
    """
    return f"{tool_id}:{digest}"


def compute_tool_digest(tool: Any) -> str:
    """Compute digest/hash of tool configuration.

    Args:
        tool: ToolCapability object

    Returns:
        Hex digest string
    """
    # Hash relevant tool properties that affect preflight
    if tool.runtime_kind == "container":
        if tool.container and tool.container.image:
            content = tool.container.image
        else:
            content = f"{tool.id}:container:none"
    elif tool.runtime_kind == "python":
        if tool.python and tool.python.module:
            content = tool.python.module
        else:
            content = f"{tool.id}:python:none"
    else:
        content = f"{tool.id}:{tool.runtime_kind}"

    return hashlib.md5(content.encode()).hexdigest()[:16]


# Global cache instance
_global_cache: Optional[PreflightCache] = None


def get_preflight_cache() -> PreflightCache:
    """Get or create global preflight cache instance.

    Returns:
        PreflightCache singleton
    """
    global _global_cache
    if _global_cache is None:
        _global_cache = PreflightCache()
    return _global_cache


def clear_preflight_cache() -> None:
    """Clear global preflight cache."""
    cache = get_preflight_cache()
    cache.clear()
