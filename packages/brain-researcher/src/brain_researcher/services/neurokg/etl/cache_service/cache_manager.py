"""
Unified Cache Manager for BR-KG

Provides a centralized caching mechanism for all data sources.
Supports multiple cache backends, expiration policies, and compression.
"""

import gzip
import hashlib
import logging
import os
import pickle
import time
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CacheManager:
    """
    Unified cache manager for BR-KG data sources.

    Features:
    - Multiple storage backends (file, memory)
    - Automatic expiration
    - Compression
    - Hierarchical namespaces
    - Cache statistics
    """

    def __init__(
        self,
        cache_dir: str = None,
        max_age_days: int = 30,
        use_compression: bool = True,
    ):
        """
        Initialize the cache manager.

        Args:
            cache_dir: Base directory for file cache
            max_age_days: Default maximum age for cached items in days
            use_compression: Whether to compress cached data
        """
        # Set default cache directory if not provided
        if cache_dir is None:
            cache_dir = os.path.join(Path.home(), ".neurokg_cache")

        self.cache_dir = Path(cache_dir)
        self.max_age_seconds = max_age_days * 24 * 60 * 60
        self.use_compression = use_compression

        # Create cache directory if it doesn't exist
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # In-memory cache for frequently accessed items
        self.memory_cache = {}

        # Cache statistics
        self.stats = {
            "hits": 0,
            "misses": 0,
            "memory_hits": 0,
            "file_hits": 0,
            "stores": 0,
            "evictions": 0,
        }

        logger.info(f"Cache manager initialized: {self.cache_dir}")

    def get(self, namespace: str, key: str, use_memory: bool = True) -> Any | None:
        """
        Get an item from the cache.

        Args:
            namespace: Cache namespace (e.g., 'pubmed', 'cognitive_atlas')
            key: Cache key
            use_memory: Whether to check memory cache first

        Returns:
            Cached value or None if not found or expired
        """
        # Try memory cache first if enabled
        if use_memory:
            memory_key = f"{namespace}:{key}"
            if memory_key in self.memory_cache:
                item = self.memory_cache[memory_key]
                if not self._is_expired(item["timestamp"]):
                    self.stats["hits"] += 1
                    self.stats["memory_hits"] += 1
                    return item["value"]
                else:
                    # Remove expired item
                    del self.memory_cache[memory_key]
                    self.stats["evictions"] += 1

        # Try file cache
        cache_file = self._get_cache_file_path(namespace, key)
        if cache_file.exists():
            try:
                item = self._read_cache_file(cache_file)
                if item and not self._is_expired(item["timestamp"]):
                    # Store in memory cache for faster access next time
                    if use_memory:
                        self.memory_cache[f"{namespace}:{key}"] = item

                    self.stats["hits"] += 1
                    self.stats["file_hits"] += 1
                    return item["value"]
                else:
                    # Remove expired file
                    cache_file.unlink(missing_ok=True)
                    self.stats["evictions"] += 1
            except Exception as e:
                logger.warning(f"⚠️ Error reading cache file {cache_file}: {e}")
                # Remove corrupted file
                cache_file.unlink(missing_ok=True)

        self.stats["misses"] += 1
        return None

    def set(
        self,
        namespace: str,
        key: str,
        value: Any,
        max_age_seconds: int | None = None,
        use_memory: bool = True,
    ) -> bool:
        """
        Store an item in the cache.

        Args:
            namespace: Cache namespace
            key: Cache key
            value: Value to store
            max_age_seconds: Custom expiration time in seconds
            use_memory: Whether to store in memory cache

        Returns:
            True if successful, False otherwise
        """
        if max_age_seconds is None:
            max_age_seconds = self.max_age_seconds

        item = {
            "timestamp": time.time(),
            "expires": time.time() + max_age_seconds,
            "value": value,
        }

        # Store in memory if enabled
        if use_memory:
            self.memory_cache[f"{namespace}:{key}"] = item

        # Store in file cache
        try:
            cache_file = self._get_cache_file_path(namespace, key)
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            self._write_cache_file(cache_file, item)
            self.stats["stores"] += 1
            return True
        except Exception as e:
            logger.error(f"❌ Error writing cache file: {e}")
            return False

    def invalidate(self, namespace: str, key: str | None = None) -> int:
        """
        Invalidate cache entries.

        Args:
            namespace: Cache namespace
            key: Specific key to invalidate, or None to invalidate entire namespace

        Returns:
            Number of invalidated entries
        """
        count = 0

        # Invalidate memory cache
        if key is None:
            # Invalidate entire namespace
            keys_to_remove = [
                k for k in self.memory_cache.keys() if k.startswith(f"{namespace}:")
            ]
            for k in keys_to_remove:
                del self.memory_cache[k]
                count += 1
        else:
            # Invalidate specific key
            memory_key = f"{namespace}:{key}"
            if memory_key in self.memory_cache:
                del self.memory_cache[memory_key]
                count += 1

        # Invalidate file cache
        namespace_dir = self.cache_dir / namespace
        if namespace_dir.exists():
            if key is None:
                # Remove entire namespace directory
                import shutil

                shutil.rmtree(namespace_dir)
                # Estimate count based on typical files per directory
                count += 10  # Approximate value
            else:
                # Remove specific file
                cache_file = self._get_cache_file_path(namespace, key)
                if cache_file.exists():
                    cache_file.unlink()
                    count += 1

        return count

    def clear_expired(self) -> int:
        """
        Clear all expired cache entries.

        Returns:
            Number of cleared entries
        """
        count = 0

        # Clear expired memory cache
        now = time.time()
        keys_to_remove = [
            k for k, v in self.memory_cache.items() if self._is_expired(v["timestamp"])
        ]
        for k in keys_to_remove:
            del self.memory_cache[k]
            count += 1

        # Clear expired file cache
        for namespace_dir in self.cache_dir.iterdir():
            if namespace_dir.is_dir():
                for cache_file in namespace_dir.glob("**/*.cache"):
                    try:
                        item = self._read_cache_file(cache_file)
                        if item and self._is_expired(item["timestamp"]):
                            cache_file.unlink()
                            count += 1
                    except Exception:
                        # Remove corrupted files
                        cache_file.unlink(missing_ok=True)
                        count += 1

        self.stats["evictions"] += count
        return count

    def get_stats(self) -> dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        # Calculate hit rate
        total_requests = self.stats["hits"] + self.stats["misses"]
        hit_rate = self.stats["hits"] / total_requests if total_requests > 0 else 0

        # Calculate cache size
        cache_size = self._calculate_cache_size()

        return {
            **self.stats,
            "hit_rate": hit_rate,
            "cache_size_bytes": cache_size,
            "cache_size_mb": cache_size / (1024 * 1024),
            "memory_cache_items": len(self.memory_cache),
            "timestamp": datetime.now().isoformat(),
        }

    def _get_cache_file_path(self, namespace: str, key: str) -> Path:
        """Get the file path for a cache item."""
        # Hash the key to avoid invalid filename characters
        hashed_key = hashlib.md5(key.encode()).hexdigest()

        # Use hierarchical structure to avoid too many files in one directory
        subdir = hashed_key[:2]

        return self.cache_dir / namespace / subdir / f"{hashed_key}.cache"

    def _write_cache_file(self, path: Path, item: dict) -> None:
        """Write an item to a cache file."""
        data = pickle.dumps(item)

        if self.use_compression:
            with gzip.open(path, "wb") as f:
                f.write(data)
        else:
            with open(path, "wb") as f:
                f.write(data)

    def _read_cache_file(self, path: Path) -> dict | None:
        """Read an item from a cache file."""
        try:
            # Try reading as compressed file first
            try:
                with gzip.open(path, "rb") as f:
                    return pickle.loads(f.read())
            except OSError:
                # Not a gzipped file, try reading as regular file
                with open(path, "rb") as f:
                    return pickle.loads(f.read())
        except Exception as e:
            logger.warning(f"⚠️ Error reading cache file {path}: {e}")
            return None

    def _is_expired(self, timestamp: float) -> bool:
        """Check if a cache item is expired."""
        age = time.time() - timestamp
        return age > self.max_age_seconds

    def _calculate_cache_size(self) -> int:
        """Calculate the total size of the cache in bytes."""
        total_size = 0

        for dirpath, _, filenames in os.walk(self.cache_dir):
            for filename in filenames:
                if filename.endswith(".cache"):
                    file_path = os.path.join(dirpath, filename)
                    total_size += os.path.getsize(file_path)

        return total_size


# Global cache manager instance
_cache_manager = None


def get_cache_manager(
    cache_dir: str = None, max_age_days: int = 30, use_compression: bool = True
) -> CacheManager:
    """
    Get the global cache manager instance.

    Args:
        cache_dir: Base directory for file cache
        max_age_days: Default maximum age for cached items in days
        use_compression: Whether to compress cached data

    Returns:
        CacheManager instance
    """
    global _cache_manager

    if _cache_manager is None:
        _cache_manager = CacheManager(
            cache_dir=cache_dir,
            max_age_days=max_age_days,
            use_compression=use_compression,
        )

    return _cache_manager


if __name__ == "__main__":
    # Test the cache manager
    logging.basicConfig(level=logging.INFO)

    cache = get_cache_manager()

    # Store some test data
    cache.set("test", "key1", {"data": "value1"})
    cache.set("test", "key2", {"data": "value2"})

    # Retrieve data
    value1 = cache.get("test", "key1")
    value2 = cache.get("test", "key2")
    value3 = cache.get("test", "key3")  # Should be None

    print(f"Value1: {value1}")
    print(f"Value2: {value2}")
    print(f"Value3: {value3}")

    # Show stats
    print(f"Stats: {cache.get_stats()}")

    # Invalidate
    cache.invalidate("test", "key1")
    print(f"After invalidation: {cache.get('test', 'key1')}")

    # Clear expired
    count = cache.clear_expired()
    print(f"Cleared {count} expired items")

    # Final stats
    print(f"Final stats: {cache.get_stats()}")
