"""Registry-backed resolver for mapping/crosswalk config paths.

This module centralizes runtime path resolution for mapping files/directories so
we do not drift between legacy service-local paths and canonical config paths.

Compatibility behavior:
- Canonical path is preferred (single source of truth).
- Legacy aliases are accepted as read-only input and remapped to canonical.
- Alias hits are counted in a structured JSON counter for easy weekly queries.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_ALIAS_COUNTER_LOCK = threading.Lock()


@dataclass(frozen=True)
class MappingSpec:
    mapping_id: str
    kind: str
    canonical_path: Path
    aliases: tuple[Path, ...]
    owner: str | None = None
    consumers: tuple[str, ...] = ()
    version: str | int | None = None


def _safe_resolve(path: Path) -> Path:
    return path.resolve(strict=False)


@lru_cache(maxsize=1)
def get_repo_root() -> Path:
    """Return repository root (directory containing configs/)."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "configs").exists():
            return parent
    # Fallback for unusual packaging layouts.
    return current.parents[2]


def _to_abs(path_like: str | Path) -> Path:
    path = Path(path_like).expanduser()
    if not path.is_absolute():
        path = get_repo_root() / path
    return _safe_resolve(path)


def get_mapping_registry_path() -> Path:
    configured = os.getenv("BR_MAPPING_REGISTRY_PATH")
    if configured:
        return _to_abs(configured)
    return get_repo_root() / "configs" / "mappings" / "registry.yaml"


def _env_override_name(mapping_id: str) -> str:
    return f"BR_MAPPING_PATH_{mapping_id.upper().replace('-', '_')}"


def _default_alias_counter_payload() -> dict[str, Any]:
    return {
        "updated_at": None,
        "total_hits": 0,
        "by_mapping": {},
        "by_alias": {},
        "by_day": {},
    }


def get_alias_hit_counter_path() -> Path:
    configured = os.getenv("BR_MAPPING_ALIAS_HIT_COUNTER_PATH")
    if configured:
        return _to_abs(configured)
    return get_repo_root() / "data" / "metrics" / "mapping_alias_hits.json"


def read_alias_hit_counts(path: str | Path | None = None) -> dict[str, Any]:
    counter_path = _to_abs(path) if path is not None else get_alias_hit_counter_path()
    if not counter_path.exists():
        return _default_alias_counter_payload()
    try:
        payload = json.loads(counter_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return _default_alias_counter_payload()
        return payload
    except Exception:
        return _default_alias_counter_payload()


def _write_alias_hit_counts(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _record_alias_hit(
    *,
    mapping_id: str,
    alias_path: Path,
    canonical_path: Path,
    reason: str,
) -> None:
    logger.warning(
        "mapping_alias_hit mapping_id=%s alias=%s canonical=%s reason=%s",
        mapping_id,
        alias_path,
        canonical_path,
        reason,
    )

    counter_path = get_alias_hit_counter_path()
    now = datetime.now(timezone.utc)
    day = now.date().isoformat()
    alias_key = str(alias_path)

    with _ALIAS_COUNTER_LOCK:
        payload = read_alias_hit_counts(counter_path)
        payload["updated_at"] = now.isoformat()
        payload["total_hits"] = int(payload.get("total_hits", 0)) + 1

        by_mapping = payload.setdefault("by_mapping", {})
        by_mapping[mapping_id] = int(by_mapping.get(mapping_id, 0)) + 1

        by_alias = payload.setdefault("by_alias", {})
        by_alias[alias_key] = int(by_alias.get(alias_key, 0)) + 1

        by_day = payload.setdefault("by_day", {})
        day_bucket = by_day.setdefault(day, {})
        day_bucket[mapping_id] = int(day_bucket.get(mapping_id, 0)) + 1

        _write_alias_hit_counts(payload, counter_path)


@lru_cache(maxsize=1)
def load_mapping_registry() -> dict[str, MappingSpec]:
    """Load resolver registry from YAML."""
    path = get_mapping_registry_path()
    if not path.exists():
        return {}

    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.warning("Failed to read mapping registry %s: %s", path, exc)
        return {}

    raw_mappings = payload.get("mappings")
    if not isinstance(raw_mappings, dict):
        return {}

    registry: dict[str, MappingSpec] = {}
    for mapping_id, raw_spec in raw_mappings.items():
        if not mapping_id or not isinstance(raw_spec, dict):
            continue
        canonical_raw = raw_spec.get("canonical")
        if not canonical_raw:
            continue
        aliases_raw = raw_spec.get("aliases") or []
        aliases: list[Path] = []
        if isinstance(aliases_raw, list):
            for alias in aliases_raw:
                if alias:
                    aliases.append(_to_abs(str(alias)))

        kind = str(raw_spec.get("kind") or "file").strip().lower()
        if kind not in {"file", "directory"}:
            kind = "file"

        consumers = raw_spec.get("consumers") or []
        consumer_items: list[str] = []
        if isinstance(consumers, list):
            consumer_items = [str(item) for item in consumers if item]

        registry[str(mapping_id)] = MappingSpec(
            mapping_id=str(mapping_id),
            kind=kind,
            canonical_path=_to_abs(str(canonical_raw)),
            aliases=tuple(aliases),
            owner=str(raw_spec.get("owner")) if raw_spec.get("owner") else None,
            consumers=tuple(consumer_items),
            version=raw_spec.get("version"),
        )

    return registry


def clear_mapping_registry_cache() -> None:
    """Clear resolver caches (useful for tests)."""
    load_mapping_registry.cache_clear()
    get_repo_root.cache_clear()


def _is_usable(path: Path, *, kind: str, must_exist: bool) -> bool:
    if not must_exist:
        return True
    if not path.exists():
        return False
    if kind == "directory":
        return path.is_dir()
    return path.is_file()


def resolve_mapping_path(
    mapping_id: str,
    *,
    requested_path: str | Path | None = None,
    fallback: str | Path | None = None,
    must_exist: bool = True,
) -> Path:
    """Resolve canonical path for a mapping id with legacy alias compatibility."""
    registry = load_mapping_registry()
    spec = registry.get(mapping_id)
    fallback_path = _to_abs(fallback) if fallback is not None else None
    requested_abs = _to_abs(requested_path) if requested_path is not None else None

    override = os.getenv(_env_override_name(mapping_id))
    if override:
        override_path = _to_abs(override)
        if spec and override_path in spec.aliases:
            _record_alias_hit(
                mapping_id=mapping_id,
                alias_path=override_path,
                canonical_path=spec.canonical_path,
                reason="env_override_alias",
            )
        if _is_usable(
            override_path, kind=spec.kind if spec else "file", must_exist=must_exist
        ):
            return override_path

    if spec is None:
        if requested_abs and _is_usable(
            requested_abs, kind="file", must_exist=must_exist
        ):
            return requested_abs
        if fallback_path and _is_usable(
            fallback_path, kind="file", must_exist=must_exist
        ):
            return fallback_path
        raise FileNotFoundError(
            f"Mapping '{mapping_id}' is not registered and no usable path was provided."
        )

    kind = spec.kind
    canonical = spec.canonical_path

    if requested_abs is not None:
        if requested_abs == canonical and _is_usable(
            canonical, kind=kind, must_exist=must_exist
        ):
            return canonical
        if requested_abs in spec.aliases:
            _record_alias_hit(
                mapping_id=mapping_id,
                alias_path=requested_abs,
                canonical_path=canonical,
                reason="requested_alias",
            )
            if _is_usable(canonical, kind=kind, must_exist=must_exist):
                return canonical
            if _is_usable(requested_abs, kind=kind, must_exist=must_exist):
                return requested_abs
        # Explicit custom path takes priority if it exists.
        if _is_usable(requested_abs, kind=kind, must_exist=must_exist):
            return requested_abs

    if _is_usable(canonical, kind=kind, must_exist=must_exist):
        return canonical

    for alias in spec.aliases:
        if _is_usable(alias, kind=kind, must_exist=must_exist):
            _record_alias_hit(
                mapping_id=mapping_id,
                alias_path=alias,
                canonical_path=canonical,
                reason="canonical_missing",
            )
            return alias

    if fallback_path and _is_usable(fallback_path, kind=kind, must_exist=must_exist):
        return fallback_path

    searched = [str(canonical), *[str(a) for a in spec.aliases]]
    if fallback_path:
        searched.append(str(fallback_path))
    raise FileNotFoundError(
        f"Unable to resolve mapping '{mapping_id}'. Searched: {searched}"
    )


__all__ = [
    "MappingSpec",
    "clear_mapping_registry_cache",
    "get_alias_hit_counter_path",
    "get_mapping_registry_path",
    "get_repo_root",
    "load_mapping_registry",
    "read_alias_hit_counts",
    "resolve_mapping_path",
]
