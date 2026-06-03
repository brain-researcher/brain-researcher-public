from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple


@dataclass
class CachedResult:
    value: Any
    expires_at: float


class OnDemandRegistry:
    """Lightweight registry for on-demand data fetches (e.g., Crossref, NIDM)."""

    def __init__(self) -> None:
        self._adapters: Dict[str, Callable[..., Any]] = {}
        self._ttl: Dict[str, Optional[float]] = {}
        self._cache: Dict[Tuple[str, Tuple[Tuple[str, Any], ...]], CachedResult] = {}

    def register(self, name: str, adapter: Callable[..., Any], ttl_seconds: Optional[int] = None) -> None:
        self._adapters[name] = adapter
        self._ttl[name] = float(ttl_seconds) if ttl_seconds else None

    def available(self) -> Dict[str, Callable[..., Any]]:
        return dict(self._adapters)

    def fetch(self, name: str, **kwargs: Any) -> Any:
        if name not in self._adapters:
            raise KeyError(f"No on-demand adapter registered for '{name}'")

        ttl = self._ttl.get(name)
        cache_key = (name, tuple(sorted(kwargs.items())))
        if ttl:
            cached = self._cache.get(cache_key)
            if cached and cached.expires_at > time.time():
                return cached.value

        result = self._adapters[name](**kwargs)
        if ttl:
            self._cache[cache_key] = CachedResult(result, time.time() + ttl)
        return result

    def clear_cache(self) -> None:
        self._cache.clear()
