"""Small file-backed cache helper for core retrieval code.

This module intentionally lives under ``core`` so core analysis utilities do
not depend on concrete BRKG service packages for generic caching.
"""

from __future__ import annotations

import gzip
import hashlib
import logging
import os
import pickle
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CacheManager:
    """File-backed cache with an in-memory hot path."""

    def __init__(
        self,
        cache_dir: str | None = None,
        max_age_days: int = 30,
        use_compression: bool = True,
    ) -> None:
        if cache_dir is None:
            cache_dir = os.path.join(Path.home(), ".brain_researcher_cache")

        self.cache_dir = Path(cache_dir)
        self.max_age_seconds = max_age_days * 24 * 60 * 60
        self.use_compression = use_compression
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.memory_cache: dict[str, dict[str, Any]] = {}
        self.stats: dict[str, int] = {
            "hits": 0,
            "misses": 0,
            "memory_hits": 0,
            "file_hits": 0,
            "stores": 0,
            "evictions": 0,
        }

    def get(self, namespace: str, key: str, use_memory: bool = True) -> Any | None:
        memory_key = f"{namespace}:{key}"
        if use_memory and memory_key in self.memory_cache:
            item = self.memory_cache[memory_key]
            if not self._is_expired(item["timestamp"]):
                self.stats["hits"] += 1
                self.stats["memory_hits"] += 1
                return item["value"]
            del self.memory_cache[memory_key]
            self.stats["evictions"] += 1

        cache_file = self._cache_file(namespace, key)
        if cache_file.exists():
            item = self._read_cache_file(cache_file)
            if item and not self._is_expired(item["timestamp"]):
                if use_memory:
                    self.memory_cache[memory_key] = item
                self.stats["hits"] += 1
                self.stats["file_hits"] += 1
                return item["value"]
            cache_file.unlink(missing_ok=True)
            self.stats["evictions"] += 1

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
        item = {
            "timestamp": time.time(),
            "expires": time.time() + (max_age_seconds or self.max_age_seconds),
            "value": value,
        }
        if use_memory:
            self.memory_cache[f"{namespace}:{key}"] = item

        cache_file = self._cache_file(namespace, key)
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            self._write_cache_file(cache_file, item)
        except Exception as exc:
            logger.warning("Could not write cache file %s: %s", cache_file, exc)
            return False

        self.stats["stores"] += 1
        return True

    def invalidate(self, namespace: str, key: str | None = None) -> int:
        count = 0
        if key is None:
            for memory_key in list(self.memory_cache):
                if memory_key.startswith(f"{namespace}:"):
                    del self.memory_cache[memory_key]
                    count += 1
            namespace_dir = self.cache_dir / namespace
            if namespace_dir.exists():
                shutil.rmtree(namespace_dir)
                count += 1
            return count

        memory_key = f"{namespace}:{key}"
        if memory_key in self.memory_cache:
            del self.memory_cache[memory_key]
            count += 1
        cache_file = self._cache_file(namespace, key)
        if cache_file.exists():
            cache_file.unlink()
            count += 1
        return count

    def get_stats(self) -> dict[str, Any]:
        total = self.stats["hits"] + self.stats["misses"]
        hit_rate = self.stats["hits"] / total if total else 0.0
        size_bytes = self._cache_size()
        return {
            **self.stats,
            "hit_rate": hit_rate,
            "cache_size_bytes": size_bytes,
            "cache_size_mb": size_bytes / (1024 * 1024),
            "memory_cache_items": len(self.memory_cache),
            "timestamp": datetime.now().isoformat(),
        }

    def _cache_file(self, namespace: str, key: str) -> Path:
        hashed_key = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / namespace / hashed_key[:2] / f"{hashed_key}.cache"

    def _write_cache_file(self, path: Path, item: dict[str, Any]) -> None:
        data = pickle.dumps(item)
        if self.use_compression:
            with gzip.open(path, "wb") as handle:
                handle.write(data)
            return
        with path.open("wb") as handle:
            handle.write(data)

    def _read_cache_file(self, path: Path) -> dict[str, Any] | None:
        try:
            try:
                with gzip.open(path, "rb") as handle:
                    return pickle.loads(handle.read())
            except OSError:
                with path.open("rb") as handle:
                    return pickle.loads(handle.read())
        except Exception as exc:
            logger.warning("Could not read cache file %s: %s", path, exc)
            return None

    def _is_expired(self, timestamp: float) -> bool:
        return time.time() - timestamp > self.max_age_seconds

    def _cache_size(self) -> int:
        total = 0
        for path in self.cache_dir.rglob("*.cache"):
            try:
                total += path.stat().st_size
            except OSError:
                continue
        return total


_cache_manager: CacheManager | None = None


def get_cache_manager(
    cache_dir: str | None = None,
    max_age_days: int = 30,
    use_compression: bool = True,
) -> CacheManager:
    """Return a process-global cache manager."""

    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager(
            cache_dir=cache_dir,
            max_age_days=max_age_days,
            use_compression=use_compression,
        )
    return _cache_manager


__all__ = ["CacheManager", "get_cache_manager"]
