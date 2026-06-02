"""Process-wide cache-store registry (dependency-inversion seam)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_cache_store_instance: Any | None = None


def set_initialized_cache_store(cache_store: Any | None) -> Any | None:
    """Set or clear the process-wide cache-store instance."""

    global _cache_store_instance
    _cache_store_instance = cache_store
    if cache_store is None:
        logger.info("CacheStore instance cleared")
    else:
        logger.info("CacheStore instance set: %s", type(cache_store).__name__)
    return _cache_store_instance


def peek_initialized_cache_store() -> Any | None:
    """Return the registered CacheStore if set (no auto-initialize)."""

    return _cache_store_instance
