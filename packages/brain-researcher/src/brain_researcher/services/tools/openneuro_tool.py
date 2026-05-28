"""OpenNeuro dataset query tools for searching and inspecting datasets."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from brain_researcher.config.paths import resolve_from_config
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

# Paths to OpenNeuro catalog and local mounts (concise + env overrides)
OPENNEURO_CATALOG_PATH = resolve_from_config("datasets", "catalog_openneuro.jsonl")

DEFAULT_MOUNT = os.getenv("OPENNEURO_MOUNT_ROOT", "/app/data/openneuro")


def get_openneuro_mount_root() -> Path:
    return Path(DEFAULT_MOUNT)


OPENNEURO_MOUNT_ROOT = get_openneuro_mount_root()
OPENNEURO_METADATA_ROOT = Path(os.getenv("OPENNEURO_METADATA_ROOT", "/app/data/openneuro_metadata"))
OPENNEURO_DERIV_ROOT = Path(os.getenv("OPENNEURO_DERIV_ROOT", "/app/data/OpenNeuroDerivatives"))


@lru_cache(maxsize=1)
def _load_openneuro_catalog() -> List[Dict[str, Any]]:
    """Load and cache the OpenNeuro catalog from JSONL file."""
    if not OPENNEURO_CATALOG_PATH.exists():
        return []
    records = []
    with OPENNEURO_CATALOG_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def _normalize_dataset_id(dataset_id: str) -> str:
    """Normalize dataset ID: ds:openneuro:ds000001 -> ds000001"""
    return dataset_id.split(":")[-1].lower()


def _path_available(path_value: Optional[str]) -> bool:
    """Return True if a given path exists on disk."""
    if not path_value:
        return False
    try:
        return Path(path_value).exists()
    except Exception:
        return False


def _dataset_root_exists(dataset_id: str) -> bool:
    """Check if dataset root exists under the mounted OpenNeuro directory."""
    norm = _normalize_dataset_id(dataset_id)
    root = get_openneuro_mount_root()
    return (root / norm).exists()


# =============================================================================
# Pydantic Argument Schemas
# =============================================================================


class OpenNeuroSearchArgs(BaseModel):
    """Arguments for searching OpenNeuro datasets."""

    query: Optional[str] = Field(
        default=None,
        description="Free-text search across dataset names, tasks, and authors",
    )
    modality: Optional[str] = Field(
        default=None,
        description="Filter by modality: fMRI, MRI, DWI, EEG, MEG, iEEG, PET",
    )
    task: Optional[str] = Field(
        default=None,
        description="Filter by task name (partial match supported)",
    )
    min_subjects: Optional[int] = Field(
        default=None,
        ge=1,
        description="Minimum number of subjects",
    )
    has_fmriprep: Optional[bool] = Field(
        default=None,
        description="Filter for datasets with fMRIPrep derivatives available",
    )
    has_mriqc: Optional[bool] = Field(
        default=None,
        description="Filter for datasets with MRIQC derivatives available",
    )
    has_glmfitlins: Optional[bool] = Field(
        default=None,
        description="Filter for datasets with GLM/FitLins stat maps available",
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of results to return",
    )


class OpenNeuroGetDatasetArgs(BaseModel):
    """Arguments for getting complete dataset metadata."""

    dataset_id: str = Field(
        description="Dataset ID (e.g., 'ds000001' or 'ds:openneuro:ds000001')"
    )


class OpenNeuroGetSummaryArgs(BaseModel):
    """Arguments for getting a lightweight dataset summary."""

    dataset_id: str = Field(
        description="Dataset ID (e.g., 'ds000001' or 'ds:openneuro:ds000001')"
    )


# =============================================================================
# Tool Implementations
# =============================================================================


class OpenNeuroSearchTool(NeuroToolWrapper):
    """Search OpenNeuro datasets with filtering by modality, task, subjects, derivatives."""

    TAGS = ["openneuro", "dataset_catalog"]

    def get_tool_name(self) -> str:
        return "openneuro.search"

    def get_tool_description(self) -> str:
        return (
            "Search 1594 OpenNeuro datasets by free-text query, modality, task, "
            "subject count, or derivative availability (fMRIPrep, MRIQC, GLM stat maps)."
        )

    def get_args_schema(self):
        return OpenNeuroSearchArgs

    def _run(
        self,
        query: Optional[str] = None,
        modality: Optional[str] = None,
        task: Optional[str] = None,
        min_subjects: Optional[int] = None,
        has_fmriprep: Optional[bool] = None,
        has_mriqc: Optional[bool] = None,
        has_glmfitlins: Optional[bool] = None,
        limit: int = 20,
    ) -> ToolResult:
        catalog = _load_openneuro_catalog()
        if not catalog:
            return ToolResult(
                status="error",
                error="OpenNeuro catalog not available or empty",
                data=None,
            )

        results = []
        for rec in catalog:
            # Free-text search across name, tasks, authors
            if query:
                name = rec.get("name", "") or ""
                tasks_str = " ".join(rec.get("tasks", []) or [])
                authors_str = " ".join(rec.get("authors", []) or [])
                searchable = f"{name} {tasks_str} {authors_str}".lower()
                if query.lower() not in searchable:
                    continue

            # Modality filter (case-insensitive)
            if modality:
                rec_mods = [m.upper() for m in (rec.get("modalities", []) or [])]
                if modality.upper() not in rec_mods:
                    continue

            # Task filter (partial match)
            if task:
                rec_tasks = [t.lower() for t in (rec.get("tasks", []) or [])]
                task_match = any(task.lower() in t for t in rec_tasks)
                if not task_match:
                    continue

            # Subject count filter
            subj_count = rec.get("subjects_count") or 0
            if min_subjects and subj_count < min_subjects:
                continue

            # Derivative availability filters (verify on disk when possible)
            if has_fmriprep is not None:
                has_it = _path_available(rec.get("path_fmriprep"))
                if has_it != has_fmriprep:
                    continue

            if has_mriqc is not None:
                has_it = _path_available(rec.get("path_mriqc"))
                if has_it != has_mriqc:
                    continue

            if has_glmfitlins is not None:
                has_it = _path_available(rec.get("path_glmfitlins"))
                if has_it != has_glmfitlins:
                    continue

            # Build result entry (compact format)
            results.append({
                "dataset_id": rec.get("dataset_id"),
                "name": rec.get("name"),
                "modalities": rec.get("modalities"),
                "tasks": (rec.get("tasks") or [])[:5],  # Limit tasks for readability
                "subjects_count": rec.get("subjects_count"),
                "has_fmriprep": _path_available(rec.get("path_fmriprep")),
                "has_mriqc": _path_available(rec.get("path_mriqc")),
                "has_glmfitlins": _path_available(rec.get("path_glmfitlins")),
            })

        total = len(results)
        return ToolResult(
            status="success",
            data={
                "items": results[:limit],
                "total": total,
                "returned": min(limit, total),
            },
        )


class OpenNeuroGetDatasetTool(NeuroToolWrapper):
    """Get complete metadata for a specific OpenNeuro dataset."""

    TAGS = ["openneuro", "dataset_catalog"]

    def get_tool_name(self) -> str:
        return "openneuro.get_dataset"

    def get_tool_description(self) -> str:
        return (
            "Get complete metadata for a specific OpenNeuro dataset including "
            "modalities, tasks, subject count, authors, paths, and derivative availability."
        )

    def get_args_schema(self):
        return OpenNeuroGetDatasetArgs

    def _run(self, dataset_id: str) -> ToolResult:
        catalog = _load_openneuro_catalog()
        if not catalog:
            return ToolResult(
                status="error",
                error="OpenNeuro catalog not available or empty",
                data=None,
            )

        norm_id = _normalize_dataset_id(dataset_id)

        for rec in catalog:
            rec_id = _normalize_dataset_id(rec.get("dataset_id", ""))
            source_id = _normalize_dataset_id(rec.get("source_repo_id", ""))
            if rec_id == norm_id or source_id == norm_id:
                # Enrich with live availability checks
                enriched = dict(rec)
                enriched["available_locally"] = (
                    _path_available(rec.get("path_dataset")) or _dataset_root_exists(rec_id)
                )
                enriched["has_fmriprep"] = _path_available(rec.get("path_fmriprep"))
                enriched["has_mriqc"] = _path_available(rec.get("path_mriqc"))
                enriched["has_glmfitlins"] = _path_available(rec.get("path_glmfitlins"))
                return ToolResult(status="success", data=enriched)

        return ToolResult(
            status="error",
            error=f"Dataset '{dataset_id}' not found in OpenNeuro catalog",
            data=None,
        )


class OpenNeuroGetSummaryTool(NeuroToolWrapper):
    """Get a lightweight summary of an OpenNeuro dataset for quick chat display."""

    TAGS = ["openneuro", "dataset_catalog"]

    def get_tool_name(self) -> str:
        return "openneuro.get_dataset_summary"

    def get_tool_description(self) -> str:
        return (
            "Get a lightweight summary of an OpenNeuro dataset with key info: "
            "name, modalities, tasks, subject count, and local availability."
        )

    def get_args_schema(self):
        return OpenNeuroGetSummaryArgs

    def _run(self, dataset_id: str) -> ToolResult:
        catalog = _load_openneuro_catalog()
        if not catalog:
            return ToolResult(
                status="error",
                error="OpenNeuro catalog not available or empty",
                data=None,
            )

        norm_id = _normalize_dataset_id(dataset_id)

        for rec in catalog:
            rec_id = _normalize_dataset_id(rec.get("dataset_id", ""))
            source_id = _normalize_dataset_id(rec.get("source_repo_id", ""))
            if rec_id == norm_id or source_id == norm_id:
                has_fmriprep = _path_available(rec.get("path_fmriprep"))
                has_mriqc = _path_available(rec.get("path_mriqc"))
                has_glm = _path_available(rec.get("path_glmfitlins"))
                available = _path_available(rec.get("path_dataset")) or _dataset_root_exists(rec_id)
                summary = {
                    "dataset_id": rec.get("dataset_id"),
                    "name": rec.get("name"),
                    "modalities": rec.get("modalities"),
                    "tasks": (rec.get("tasks") or [])[:5],
                    "subjects": rec.get("subjects_count"),
                    "license": rec.get("license"),
                    "url": rec.get("primary_url"),
                    "available_locally": available,
                    "derivatives_available": {
                        "fmriprep": has_fmriprep,
                        "mriqc": has_mriqc,
                        "glmfitlins": has_glm,
                    },
                }
                return ToolResult(status="success", data=summary)

        return ToolResult(
            status="error",
            error=f"Dataset '{dataset_id}' not found in OpenNeuro catalog",
            data=None,
        )


# =============================================================================
# Factory
# =============================================================================


class OpenNeuroTools:
    """Factory for OpenNeuro query tools."""

    def get_all_tools(self) -> list[NeuroToolWrapper]:
        return [
            OpenNeuroSearchTool(),
            OpenNeuroGetDatasetTool(),
            OpenNeuroGetSummaryTool(),
        ]


def get_all_tools() -> list[NeuroToolWrapper]:
    """Return all OpenNeuro tools for registration."""
    return OpenNeuroTools().get_all_tools()
