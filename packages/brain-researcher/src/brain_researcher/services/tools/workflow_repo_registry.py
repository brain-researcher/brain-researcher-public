"""Registry-backed helpers for neuroimaging workflow-repo intake."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


_REGISTRY_ENV = "BR_WORKFLOW_REPO_REGISTRY"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _registry_path() -> Path:
    explicit = os.getenv(_REGISTRY_ENV, "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    return repo_root() / "configs" / "workflows" / "neuroimaging_repo_intake.yaml"


def clear_workflow_repo_registry_cache() -> None:
    _load_registry_cached.cache_clear()


@lru_cache(maxsize=4)
def _load_registry_cached(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid workflow repo registry root: {path}")
    return payload


def load_workflow_repo_registry() -> dict[str, Any]:
    return _load_registry_cached(str(_registry_path()))


def list_repo_candidates(
    *,
    family_id: str | None = None,
    current_state: str | None = None,
    packaging_mode: str | None = None,
    priority: str | None = None,
) -> list[dict[str, Any]]:
    payload = load_workflow_repo_registry()
    families = payload.get("families") or []
    selected: list[dict[str, Any]] = []

    for family in families:
        if not isinstance(family, dict):
            continue
        if family_id and family.get("family_id") != family_id:
            continue
        for entry in family.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            if current_state and entry.get("current_state") != current_state:
                continue
            if packaging_mode and entry.get("packaging_mode") != packaging_mode:
                continue
            if priority and entry.get("priority") != priority:
                continue
            candidate = dict(entry)
            candidate["family_id"] = family.get("family_id")
            candidate["family_title"] = family.get("title")
            selected.append(candidate)
    return selected


def get_repo_candidate(repo_slug: str) -> dict[str, Any] | None:
    key = str(repo_slug or "").strip().lower()
    if not key:
        return None
    for entry in list_repo_candidates():
        if str(entry.get("repo_slug") or "").strip().lower() == key:
            return entry
    return None


def get_repo_candidate_for_workflow(workflow_id: str) -> dict[str, Any] | None:
    needle = str(workflow_id or "").strip()
    if not needle:
        return None
    for entry in list_repo_candidates():
        if entry.get("recommended_workflow") == needle:
            return entry
    return None


__all__ = [
    "clear_workflow_repo_registry_cache",
    "get_repo_candidate",
    "get_repo_candidate_for_workflow",
    "list_repo_candidates",
    "load_workflow_repo_registry",
]
