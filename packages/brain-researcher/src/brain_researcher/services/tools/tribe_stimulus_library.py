"""Helpers for loading TRIBE stimulus-library configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from brain_researcher.autoresearch.artifact_schema import (
    canonicalize_line_path,
    resolve_line_paths,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_TRIBE_STIMULUS_LIBRARY = (
    REPO_ROOT / "configs" / "experiments" / "tribe_ibc_stimulus_library.yaml"
)


def _resolve_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def load_stimulus_library_config(
    config_path: Path | str = DEFAULT_TRIBE_STIMULUS_LIBRARY,
) -> dict[str, Any]:
    resolved = _resolve_path(config_path)
    payload = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Stimulus library config must be a mapping: {resolved}")
    return payload


@dataclass(frozen=True)
class TribeProjectPaths:
    config_path: Path
    data_root: Path
    project_root: Path
    source_checkout_root: Path
    materialized_library_root: Path
    manifests_root: Path
    derived_media_root: Path
    analysis_root: Path
    prediction_root: Path
    tribe_cache_root: Path
    closed_loop_root: Path
    hypothesis_ledger_path: Path


@dataclass(frozen=True)
class TribeTaskConfig:
    task_id: str
    library_id: str
    priority: str
    family: str
    readiness: str
    source_subdir: str
    preferred_tribe_input: str
    source_root: Path
    source_glob: str
    manifest_path: Path
    materialized_root: Path
    note: str | None
    contrasts: tuple[dict[str, Any], ...]
    expected_rois: tuple[str, ...]
    neurokg_tags: tuple[str, ...]


def resolve_project_paths(
    config_path: Path | str = DEFAULT_TRIBE_STIMULUS_LIBRARY,
) -> TribeProjectPaths:
    resolved_config = _resolve_path(config_path)
    payload = load_stimulus_library_config(resolved_config)
    raw_paths = payload.get("brain_researcher_paths")
    if not isinstance(raw_paths, dict):
        raise ValueError(
            f"Stimulus library missing brain_researcher_paths: {resolved_config}"
        )

    shared_paths = resolve_line_paths("discovery", root=raw_paths["project_root"])
    project_root = shared_paths.project_root
    closed_loop_root = shared_paths.checkpoint_root or (project_root / "artifacts" / "closed_loop")
    return TribeProjectPaths(
        config_path=resolved_config,
        data_root=canonicalize_line_path(raw_paths["data_root"], "discovery"),
        project_root=project_root,
        source_checkout_root=canonicalize_line_path(
            raw_paths["source_checkout_root"], "discovery"
        ),
        materialized_library_root=canonicalize_line_path(
            raw_paths["materialized_library_root"], "discovery"
        ),
        manifests_root=canonicalize_line_path(raw_paths["manifests_root"], "discovery"),
        derived_media_root=canonicalize_line_path(
            raw_paths["derived_media_root"], "discovery"
        ),
        analysis_root=canonicalize_line_path(raw_paths["analysis_root"], "discovery"),
        prediction_root=canonicalize_line_path(
            raw_paths["prediction_root"], "discovery"
        ),
        tribe_cache_root=canonicalize_line_path(raw_paths["tribe_cache_root"], "discovery"),
        closed_loop_root=closed_loop_root,
        hypothesis_ledger_path=closed_loop_root / "tribe_hypothesis_ledger.jsonl",
    )


def resolve_task_config(
    task_id: str,
    config_path: Path | str = DEFAULT_TRIBE_STIMULUS_LIBRARY,
) -> TribeTaskConfig:
    payload = load_stimulus_library_config(config_path)
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError(f"Stimulus library missing tasks list: {config_path}")
    library_id = str(payload.get("library_id") or "").strip()

    for task in tasks:
        if not isinstance(task, dict):
            continue
        if str(task.get("task_id")) != task_id:
            continue
        source_assets = task.get("source_assets") or {}
        ingestion = task.get("ingestion") or {}
        modality = task.get("modality") or {}
        contrasts = task.get("contrasts") or []
        expected_rois = task.get("expected_rois") or []
        neurokg_tags = task.get("neurokg_tags") or []
        return TribeTaskConfig(
            task_id=task_id,
            library_id=library_id,
            priority=str(task.get("priority") or "").strip(),
            family=str(task.get("family") or "").strip(),
            readiness=str(task.get("readiness") or "").strip(),
            source_subdir=str(task.get("source_subdir") or "").strip(),
            preferred_tribe_input=str(
                modality.get("preferred_tribe_input") or ""
            ).strip(),
            source_root=canonicalize_line_path(source_assets["root"], "discovery"),
            source_glob=str(ingestion.get("source_glob") or "").strip(),
            manifest_path=canonicalize_line_path(
                ingestion["manifest_path"], "discovery"
            ),
            materialized_root=canonicalize_line_path(
                ingestion["materialized_root"], "discovery"
            ),
            note=(
                str(ingestion.get("note")).strip()
                if ingestion.get("note") is not None
                else None
            ),
            contrasts=tuple(
                contrast for contrast in contrasts if isinstance(contrast, dict)
            ),
            expected_rois=tuple(str(roi) for roi in expected_rois),
            neurokg_tags=tuple(str(tag) for tag in neurokg_tags),
        )
    raise KeyError(f"Task {task_id!r} not found in stimulus library {config_path}")


__all__ = [
    "DEFAULT_TRIBE_STIMULUS_LIBRARY",
    "TribeProjectPaths",
    "TribeTaskConfig",
    "load_stimulus_library_config",
    "resolve_project_paths",
    "resolve_task_config",
]
