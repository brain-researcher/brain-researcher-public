"""Cache store abstraction for deterministic result caching.

Provides SQLite and in-memory implementations of cache storage with:
- State-based locking (pending/completed/failed)
- LRU eviction
- Tool and git-based invalidation
- Statistics tracking
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Represents a cache entry."""

    cache_key: str
    run_id: str
    run_dir: str
    state: str  # pending, completed, failed
    meta_json: str
    created_at: int
    last_accessed_at: int
    tool_version: str | None = None
    git_sha: str | None = None
    size_bytes: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "cache_key": self.cache_key,
            "run_id": self.run_id,
            "run_dir": self.run_dir,
            "state": self.state,
            "meta": json.loads(self.meta_json),
            "created_at": self.created_at,
            "last_accessed_at": self.last_accessed_at,
            "tool_version": self.tool_version,
            "git_sha": self.git_sha,
            "size_bytes": self.size_bytes,
        }


@dataclass
class CacheStats:
    """Cache statistics."""

    total_entries: int
    pending_entries: int
    completed_entries: int
    failed_entries: int
    total_size_bytes: int
    hit_count: int  # Tracked separately (not in DB)
    miss_count: int  # Tracked separately (not in DB)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        hit_rate = (
            self.hit_count / (self.hit_count + self.miss_count)
            if (self.hit_count + self.miss_count) > 0
            else 0.0
        )
        return {
            "total_entries": self.total_entries,
            "pending_entries": self.pending_entries,
            "completed_entries": self.completed_entries,
            "failed_entries": self.failed_entries,
            "total_size_mb": round(self.total_size_bytes / (1024 * 1024), 2),
            "hit_count": self.hit_count,
            "miss_count": self.miss_count,
            "hit_rate": round(hit_rate, 3),
        }


class CacheStore(ABC):
    """Abstract base class for cache storage backends."""

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the cache store (create tables, etc.)."""
        pass

    @abstractmethod
    async def lookup(self, cache_key: str) -> CacheEntry | None:
        """Look up a cache entry by key.

        Args:
            cache_key: Cache key to look up

        Returns:
            CacheEntry if found, None otherwise
        """
        pass

    @abstractmethod
    async def create_and_mark_pending(
        self,
        cache_key: str,
        run_id: str,
        meta: dict[str, Any],
        tool_version: str | None = None,
        git_sha: str | None = None,
    ) -> bool:
        """Create or reset a cache entry to pending state.

        Args:
            cache_key: Cache key
            run_id: Run ID for the pending computation
            meta: Metadata dict to store
            tool_version: Tool version for invalidation
            git_sha: Git SHA for invalidation

        Returns:
            True if the entry is now in pending state and reserved for this run_id,
            False if another worker already holds the reservation.
        """
        pass

    @abstractmethod
    async def mark_completed(
        self,
        cache_key: str,
        run_id: str,
        run_dir: str,
        size_bytes: int | None = None,
    ) -> bool:
        """Mark a pending entry as completed.

        Args:
            cache_key: Cache key
            run_id: Job/run identifier associated with the cache entry
            run_dir: Path to run directory with results
            size_bytes: Optional total size of outputs

        Returns:
            True if updated, False if not found or not in pending state
        """
        pass

    @abstractmethod
    async def mark_failed(
        self,
        cache_key: str,
        run_id: str,
        error: str,
    ) -> bool:
        """Mark a pending entry as failed.

        Args:
            cache_key: Cache key
            run_id: Job/run identifier associated with the cache entry
            error: Error message

        Returns:
            True if updated, False if not found
        """
        pass

    @abstractmethod
    async def get_stats(self) -> CacheStats:
        """Get cache statistics.

        Returns:
            CacheStats object
        """
        pass

    @abstractmethod
    async def clear_all(self) -> int:
        """Clear all cache entries.

        Returns:
            Number of entries deleted
        """
        pass

    @abstractmethod
    async def clear_by_tool(self, tool_version: str) -> int:
        """Clear cache entries for a specific tool version.

        Args:
            tool_version: Tool version to clear

        Returns:
            Number of entries deleted
        """
        pass

    @abstractmethod
    async def clear_by_git(self, git_sha: str) -> int:
        """Clear cache entries for a specific git SHA.

        Args:
            git_sha: Git SHA to clear

        Returns:
            Number of entries deleted
        """
        pass

    @abstractmethod
    async def gc_lru(self, max_entries: int) -> int:
        """Run garbage collection to keep cache under size limit.

        Removes oldest entries (by last_accessed_at) until total is <= max_entries.

        Args:
            max_entries: Maximum number of entries to keep

        Returns:
            Number of entries evicted
        """
        pass


class MemoryCacheStore(CacheStore):
    """In-memory cache store for testing or when SQLite is unavailable."""

    def __init__(self):
        self._cache: dict[str, CacheEntry] = {}
        self._hit_count = 0
        self._miss_count = 0

    async def initialize(self) -> None:
        """No-op for memory store."""
        pass

    async def lookup(self, cache_key: str) -> CacheEntry | None:
        """Look up cache entry in memory."""
        entry = self._cache.get(cache_key)
        if entry:
            self._hit_count += 1
            # Update last_accessed_at
            entry.last_accessed_at = int(time.time())
        else:
            self._miss_count += 1
        return entry

    async def create_and_mark_pending(
        self,
        cache_key: str,
        run_id: str,
        meta: dict[str, Any],
        tool_version: str | None = None,
        git_sha: str | None = None,
    ) -> bool:
        """Ensure an entry exists in pending state; return True if reserved."""
        now = int(time.time())
        entry = self._cache.get(cache_key)

        if entry is None:
            self._cache[cache_key] = CacheEntry(
                cache_key=cache_key,
                run_id=run_id,
                run_dir="",
                state="pending",
                meta_json=json.dumps(meta),
                created_at=now,
                last_accessed_at=now,
                tool_version=tool_version,
                git_sha=git_sha,
            )
            return True

        if entry.state != "pending":
            entry.state = "pending"
            entry.run_id = run_id
            entry.run_dir = ""
            entry.meta_json = json.dumps(meta)
            entry.tool_version = tool_version or entry.tool_version
            entry.git_sha = git_sha or entry.git_sha
            entry.size_bytes = None
            entry.last_accessed_at = now
            return True

        return False

    async def mark_completed(
        self,
        cache_key: str,
        run_id: str,
        run_dir: str,
        size_bytes: int | None = None,
    ) -> bool:
        """Mark entry as completed in memory."""
        entry = self._cache.get(cache_key)
        if entry and entry.state == "pending":
            if entry.run_id != run_id:
                logger.warning(
                    "Cache reservation mismatch for %s (expected %s, got %s)",
                    cache_key[:16],
                    entry.run_id,
                    run_id,
                )
            entry.run_id = run_id
            entry.state = "completed"
            entry.run_dir = run_dir
            entry.size_bytes = size_bytes
            entry.last_accessed_at = int(time.time())
            return True
        return False

    async def mark_failed(
        self,
        cache_key: str,
        run_id: str,
        error: str,
    ) -> bool:
        """Mark entry as failed in memory."""
        entry = self._cache.get(cache_key)
        if entry and entry.state == "pending":
            if entry.run_id != run_id:
                logger.warning(
                    "Cache reservation mismatch for %s (expected %s, got %s)",
                    cache_key[:16],
                    entry.run_id,
                    run_id,
                )
            entry.run_id = run_id
            entry.state = "failed"
            # Store error in meta
            meta = json.loads(entry.meta_json)
            meta["error"] = error
            entry.meta_json = json.dumps(meta)
            return True
        return False

    async def get_stats(self) -> CacheStats:
        """Get cache statistics from memory."""
        entries = list(self._cache.values())
        return CacheStats(
            total_entries=len(entries),
            pending_entries=sum(1 for e in entries if e.state == "pending"),
            completed_entries=sum(1 for e in entries if e.state == "completed"),
            failed_entries=sum(1 for e in entries if e.state == "failed"),
            total_size_bytes=sum(e.size_bytes or 0 for e in entries),
            hit_count=self._hit_count,
            miss_count=self._miss_count,
        )

    async def clear_all(self) -> int:
        """Clear all entries from memory."""
        count = len(self._cache)
        self._cache.clear()
        return count

    async def clear_by_tool(self, tool_version: str) -> int:
        """Clear entries by tool version from memory."""
        to_delete = [
            key
            for key, entry in self._cache.items()
            if entry.tool_version == tool_version
        ]
        for key in to_delete:
            del self._cache[key]
        return len(to_delete)

    async def clear_by_git(self, git_sha: str) -> int:
        """Clear entries by git SHA from memory."""
        to_delete = [
            key for key, entry in self._cache.items() if entry.git_sha == git_sha
        ]
        for key in to_delete:
            del self._cache[key]
        return len(to_delete)

    async def gc_lru(self, max_entries: int) -> int:
        """Evict oldest entries to keep cache under limit."""
        if len(self._cache) <= max_entries:
            return 0

        # Sort by last_accessed_at (oldest first)
        entries = sorted(self._cache.items(), key=lambda item: item[1].last_accessed_at)

        # Delete oldest until we're under limit
        to_delete = entries[: len(entries) - max_entries]
        for key, _ in to_delete:
            del self._cache[key]

        return len(to_delete)


# Phase 3: Global cache store accessor
_global_cache_store: CacheStore | None = None


async def get_cache_store() -> CacheStore:
    """Get or create the global cache store instance.

    Phase 3.1: Provides singleton access to cache store for endpoints.

    Returns:
        CacheStore instance (MemoryCacheStore by default)
    """
    global _global_cache_store
    if _global_cache_store is None:
        _global_cache_store = MemoryCacheStore()
        await _global_cache_store.initialize()
    return _global_cache_store
