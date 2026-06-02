"""Entity / task-tree caching substrate for the BR-KG Flask API.

Carved out of ``br_kg/app.py`` to give the entity-lookup hot path a
self-contained, one-way-dependency caching layer. ``app.py`` imports the
helpers, globals and config constants back from here (re-export); nothing in
this module imports ``app.py`` — the dependency flows ``app -> entity_cache``
only, so the cache substrate can be reasoned about and tested in isolation.

Three caches live here:

* ``_TASK_TREE_CACHE``     – small TTL cache for task-tree payloads (L1 only).
* ``_DISEASE_ENTITY_CACHE``– TTL cache for disease-entity lookups (L1 only).
* ``_TASK_ENTITY_CACHE``   – two-tier cache for task-entity lookups: an
  in-process L1 dict plus an optional Redis-backed L2, fronted by a
  per-key singleflight lock to collapse concurrent misses.

The TTLs / sizes / Redis wiring are driven by the ``BR_KG_TASK_*`` /
``BR_KG_DISEASE_*`` module constants, which are read live by the helpers (so
tests patch them on *this* module, not on ``app``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from copy import deepcopy
from threading import Lock
from time import monotonic
from typing import Any

try:  # optional dependency
    import redis  # type: ignore[import-untyped]
except Exception:  # pragma: no cover
    redis = None

logger = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning("Invalid float env %s=%r, using default=%s", name, raw, default)
        return default


# --- config -----------------------------------------------------------------
BR_KG_TASK_TREE_CACHE_TTL_SECONDS = _env_float(
    "BR_KG_TASK_TREE_CACHE_TTL_SECONDS",
    300.0,
)
BR_KG_DISEASE_ENTITY_CACHE_TTL_SECONDS = 60.0
BR_KG_TASK_ENTITY_CACHE_TTL_SECONDS = _env_float(
    "BR_KG_TASK_ENTITY_CACHE_TTL_SECONDS",
    300.0,
)
BR_KG_TASK_ENTITY_CACHE_MAX_ENTRIES = int(
    _env_float("BR_KG_TASK_ENTITY_CACHE_MAX_ENTRIES", 512.0)
)
BR_KG_TASK_ENTITY_REDIS_URL = (
    os.environ.get("BR_KG_TASK_ENTITY_REDIS_URL") or os.environ.get("REDIS_URL") or ""
).strip()
BR_KG_TASK_ENTITY_REDIS_PREFIX = os.environ.get(
    "BR_KG_TASK_ENTITY_REDIS_PREFIX",
    "br_kg:task-entity:v1",
)
BR_KG_TASK_ENTITY_REDIS_TTL_SECONDS = _env_float(
    "BR_KG_TASK_ENTITY_REDIS_TTL_SECONDS",
    max(BR_KG_TASK_ENTITY_CACHE_TTL_SECONDS, 1.0),
)


# --- mutable cache state -----------------------------------------------------
_TASK_TREE_CACHE: dict[tuple[str, int, bool], tuple[float, dict[str, Any]]] = {}
_DISEASE_ENTITY_CACHE: dict[tuple[Any, ...], tuple[float, list[dict[str, Any]]]] = {}
_TASK_ENTITY_CACHE: dict[tuple[Any, ...], tuple[float, Any]] = {}
_TASK_ENTITY_REDIS_CLIENT: Any | None = None
_TASK_ENTITY_REDIS_INITIALIZED = False
_TASK_ENTITY_SINGLEFLIGHT_LOCKS: dict[str, Lock] = {}
_TASK_ENTITY_SINGLEFLIGHT_LOCKS_GUARD = Lock()


# --- task-tree cache ---------------------------------------------------------
def _task_tree_cache_get(key: tuple[str, int, bool]) -> dict[str, Any] | None:
    if BR_KG_TASK_TREE_CACHE_TTL_SECONDS <= 0:
        return None
    entry = _TASK_TREE_CACHE.get(key)
    if not entry:
        return None
    expires_at, payload = entry
    if monotonic() >= expires_at:
        _TASK_TREE_CACHE.pop(key, None)
        return None
    return payload


def _task_tree_cache_set(key: tuple[str, int, bool], payload: dict[str, Any]) -> None:
    if BR_KG_TASK_TREE_CACHE_TTL_SECONDS <= 0:
        return
    ttl = max(float(BR_KG_TASK_TREE_CACHE_TTL_SECONDS), 1.0)
    _TASK_TREE_CACHE[key] = (monotonic() + ttl, payload)

    # Keep cache bounded for long-lived processes.
    if len(_TASK_TREE_CACHE) > 64:
        oldest_key = min(_TASK_TREE_CACHE.items(), key=lambda item: item[1][0])[0]
        _TASK_TREE_CACHE.pop(oldest_key, None)


# --- disease-entity cache ----------------------------------------------------
def _disease_entity_cache_key(
    *,
    lens: str,
    query: str,
    limit: int,
    scheme_filter: str | None,
    path_mode: str,
) -> tuple[Any, ...]:
    return (
        str(lens or "").strip().lower(),
        str(query or "").strip().lower(),
        int(limit),
        str(scheme_filter or ""),
        str(path_mode or "").strip().lower(),
    )


def _disease_entity_cache_get(key: tuple[Any, ...]) -> list[dict[str, Any]] | None:
    if BR_KG_DISEASE_ENTITY_CACHE_TTL_SECONDS <= 0:
        return None
    entry = _DISEASE_ENTITY_CACHE.get(key)
    if not entry:
        return None
    expires_at, payload = entry
    if monotonic() >= expires_at:
        _DISEASE_ENTITY_CACHE.pop(key, None)
        return None
    return deepcopy(payload)


def _disease_entity_cache_set(
    key: tuple[Any, ...],
    payload: list[dict[str, Any]],
) -> None:
    if BR_KG_DISEASE_ENTITY_CACHE_TTL_SECONDS <= 0:
        return
    ttl = max(float(BR_KG_DISEASE_ENTITY_CACHE_TTL_SECONDS), 1.0)
    _DISEASE_ENTITY_CACHE[key] = (monotonic() + ttl, deepcopy(payload))
    if len(_DISEASE_ENTITY_CACHE) > 256:
        oldest_key = min(_DISEASE_ENTITY_CACHE.items(), key=lambda item: item[1][0])[0]
        _DISEASE_ENTITY_CACHE.pop(oldest_key, None)


# --- task-entity cache (L1 dict + optional Redis L2 + singleflight) ----------
def _request_query_items() -> tuple[tuple[str, str], ...]:
    from flask import request

    pairs: list[tuple[str, str]] = []
    for key in sorted(request.args.keys()):
        normalized_key = str(key).strip().lower()
        values = [str(v) for v in request.args.getlist(key)]
        if not values:
            pairs.append((normalized_key, ""))
            continue
        for value in sorted(values):
            pairs.append((normalized_key, value))
    return tuple(pairs)


def _task_entity_cache_key(endpoint: str, lens: str, entity_id: str) -> tuple[Any, ...]:
    return (
        str(endpoint or "").strip().lower(),
        str(lens or "").strip().lower(),
        str(entity_id or "").strip(),
        _request_query_items(),
    )


def _task_entity_cache_fingerprint(key: tuple[Any, ...]) -> str:
    encoded = json.dumps(
        key,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    return hashlib.sha1(encoded.encode("utf-8")).hexdigest()


def _task_entity_redis_key(key: tuple[Any, ...]) -> str:
    return f"{BR_KG_TASK_ENTITY_REDIS_PREFIX}:{_task_entity_cache_fingerprint(key)}"


def _get_task_entity_redis_client() -> Any | None:
    global _TASK_ENTITY_REDIS_CLIENT, _TASK_ENTITY_REDIS_INITIALIZED
    if _TASK_ENTITY_REDIS_INITIALIZED:
        return _TASK_ENTITY_REDIS_CLIENT
    _TASK_ENTITY_REDIS_INITIALIZED = True

    if (
        not BR_KG_TASK_ENTITY_REDIS_URL
        or redis is None
        or BR_KG_TASK_ENTITY_REDIS_TTL_SECONDS <= 0
    ):
        return None

    try:
        _TASK_ENTITY_REDIS_CLIENT = redis.Redis.from_url(  # type: ignore[attr-defined]
            BR_KG_TASK_ENTITY_REDIS_URL,
            decode_responses=False,
            socket_connect_timeout=0.25,
            socket_timeout=0.5,
        )
        _TASK_ENTITY_REDIS_CLIENT.ping()
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "Task entity Redis cache unavailable; falling back to L1 only: %s",
            exc,
        )
        _TASK_ENTITY_REDIS_CLIENT = None
    return _TASK_ENTITY_REDIS_CLIENT


def _task_entity_cache_get_l1(key: tuple[Any, ...]) -> Any | None:
    if BR_KG_TASK_ENTITY_CACHE_TTL_SECONDS <= 0:
        return None
    entry = _TASK_ENTITY_CACHE.get(key)
    if not entry:
        return None
    expires_at, payload = entry
    if monotonic() >= expires_at:
        _TASK_ENTITY_CACHE.pop(key, None)
        return None
    return deepcopy(payload)


def _task_entity_cache_set_l1(key: tuple[Any, ...], payload: Any) -> None:
    if BR_KG_TASK_ENTITY_CACHE_TTL_SECONDS <= 0:
        return
    ttl = max(float(BR_KG_TASK_ENTITY_CACHE_TTL_SECONDS), 1.0)
    _TASK_ENTITY_CACHE[key] = (monotonic() + ttl, deepcopy(payload))

    max_entries = max(int(BR_KG_TASK_ENTITY_CACHE_MAX_ENTRIES), 16)
    if len(_TASK_ENTITY_CACHE) > max_entries:
        oldest_key = min(_TASK_ENTITY_CACHE.items(), key=lambda item: item[1][0])[0]
        _TASK_ENTITY_CACHE.pop(oldest_key, None)


def _task_entity_cache_get_with_source(key: tuple[Any, ...]) -> tuple[str, Any] | None:
    payload = _task_entity_cache_get_l1(key)
    if payload is not None:
        return "HIT_L1", payload

    client = _get_task_entity_redis_client()
    if client is None:
        return None

    redis_key = _task_entity_redis_key(key)
    try:
        raw = client.get(redis_key)
    except Exception:  # pragma: no cover
        return None
    if raw in (None, b"", ""):
        return None

    try:
        if isinstance(raw, bytes | bytearray):
            payload = json.loads(raw.decode("utf-8"))
        else:
            payload = json.loads(str(raw))
    except Exception:  # pragma: no cover
        try:
            client.delete(redis_key)
        except Exception:
            pass
        return None

    _task_entity_cache_set_l1(key, payload)
    return "HIT_REDIS", deepcopy(payload)


def _task_entity_cache_set_l2(key: tuple[Any, ...], payload: Any) -> None:
    client = _get_task_entity_redis_client()
    if client is None or BR_KG_TASK_ENTITY_REDIS_TTL_SECONDS <= 0:
        return
    ttl = max(int(BR_KG_TASK_ENTITY_REDIS_TTL_SECONDS), 1)
    try:
        serialized = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        client.setex(_task_entity_redis_key(key), ttl, serialized.encode("utf-8"))
    except Exception:  # pragma: no cover
        return


def _task_entity_cache_get(key: tuple[Any, ...]) -> Any | None:
    hit = _task_entity_cache_get_with_source(key)
    if hit is None:
        return None
    return hit[1]


def _task_entity_cache_set(key: tuple[Any, ...], payload: Any) -> None:
    _task_entity_cache_set_l1(key, payload)
    _task_entity_cache_set_l2(key, payload)


def _task_entity_singleflight_lock(key: tuple[Any, ...]) -> Lock:
    lock_key = _task_entity_cache_fingerprint(key)
    with _TASK_ENTITY_SINGLEFLIGHT_LOCKS_GUARD:
        lock = _TASK_ENTITY_SINGLEFLIGHT_LOCKS.get(lock_key)
        if lock is None:
            lock = Lock()
            _TASK_ENTITY_SINGLEFLIGHT_LOCKS[lock_key] = lock
        return lock
