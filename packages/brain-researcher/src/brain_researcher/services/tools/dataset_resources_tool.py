"""Dataset resource lookup tools (local/derivatives/remote)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from brain_researcher.core.datasets.catalog import (
    DEFAULT_CATALOG_PATH,
    DatasetRecord,
    load_catalog,
)
from brain_researcher.services.neurokg import query_service
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class DatasetResourcesArgs(BaseModel):
    dataset_ref: str = Field(
        description="Dataset id or alias (e.g., ds000114, ds:openneuro:ds000114)"
    )
    dataset_version: str | None = Field(
        default=None,
        description=(
            "Optional requested dataset version (e.g., v1.0.2, latest). "
            "Used for provenance and downstream resource selection hints."
        ),
    )
    analysis_goal: str = Field(
        default="generic",
        description=(
            "Readiness profile: generic, fmri-glm, lnm, or bold-layer1. "
            "Controls required-files checks."
        ),
    )
    semantic_intent: str | None = Field(
        default=None,
        description=(
            "Optional free text intent used for semantic compatibility checks "
            "(e.g., 'stroke depression lesion')."
        ),
    )
    auto_heal: bool = Field(
        default=False,
        description=(
            "If true, attempt one-shot selective OpenNeuro recovery for missing files "
            "using aws s3 sync includes."
        ),
    )
    run_bids_validation: bool = Field(
        default=True,
        description="If true, run bids-validator (if available) and report errors/warnings.",
    )
    enforce_semantic_gate: bool = Field(
        default=True,
        description=(
            "If true, readiness is blocked when semantic intent requirements are not met."
        ),
    )
    check_source_access: bool = Field(
        default=True,
        description=(
            "If true, probe remote/source metadata such as OpenNeuro bucket state. "
            "Set false for local-fast readiness checks that should not wait on source metadata."
        ),
    )


class DatasetDescribeArgs(BaseModel):
    dataset_ref: str = Field(
        description="Dataset id or alias (e.g., ds000114, ds:openneuro:ds000114)"
    )
    analysis_goal: str = Field(
        default="generic",
        description=(
            "Readiness profile: generic, fmri-glm, lnm, or bold-layer1. "
            "Controls required-files checks."
        ),
    )
    include_files: bool = Field(
        default=True,
        description="If true, include required-file group summaries and pattern counts.",
    )
    include_sensitive_paths: bool = Field(
        default=False,
        description=(
            "If true, include internal mounted paths (bids path / derivative paths / trace candidates). "
            "Leave false for safe summaries."
        ),
    )


def _coerce_string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


def _match_catalog_record(dataset_ref: str) -> Optional[DatasetRecord]:
    target = (dataset_ref or "").strip().lower()
    if not target:
        return None

    try:
        catalog = load_catalog(DEFAULT_CATALOG_PATH)
    except Exception:
        return None

    ranked: List[tuple[int, DatasetRecord]] = []
    for rec in catalog:
        rid = rec.dataset_id.lower()
        rid_simple = rid.split(":")[-1]
        repo_id = (rec.source_repo_id or "").strip().lower()
        aliases = [a.strip().lower() for a in rec.alias or [] if str(a).strip()]
        name = rec.name.strip().lower()

        if target == rid:
            ranked.append((120, rec))
            continue
        if target == rid_simple:
            ranked.append((115, rec))
            continue
        if repo_id and target == repo_id:
            ranked.append((110, rec))
            continue
        if target in aliases:
            ranked.append((108, rec))
            continue
        if target == name:
            ranked.append((100, rec))
            continue
        if target in name:
            ranked.append((70, rec))

    if not ranked:
        return None
    ranked.sort(key=lambda item: (-item[0], item[1].dataset_id))
    return ranked[0][1]


def _build_versions(record: Optional[DatasetRecord], resources: Any) -> List[str]:
    versions: List[str] = []
    if record and getattr(record, "source_version", None):
        versions.append(str(record.source_version))

    remote_urls = dict(getattr(resources, "remote_urls", {}) or {})
    for candidate in (
        remote_urls.get("openneuro"),
        remote_urls.get("primary"),
        getattr(record, "primary_url", None) if record else None,
    ):
        text = str(candidate or "")
        if not text:
            continue
        if ".v" in text:
            # keep the tail token lightweight, e.g. ...ds000114.v1.0.2 -> v1.0.2
            tail = text.split(".v")[-1]
            if tail and all(part.isdigit() for part in tail.split(".") if part):
                versions.append(f"v{tail}")

    deduped: List[str] = []
    seen = set()
    for version in versions:
        key = version.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(version.strip())
    return deduped


def collect_dataset_resources(dataset_ref: str, **kwargs: Any) -> Any:
    """Compatibility wrapper for dataset resource resolution.

    Kept as a module-level helper so tests and callers can monkeypatch the
    lightweight dataset resolver without reaching into query_service internals.
    """

    return query_service.dataset_resources(dataset_ref, **kwargs)


class DatasetResourcesTool(NeuroToolWrapper):
    """List available resources (paths/derivatives/remote URLs) for a dataset."""

    TAGS = ["dataset_catalog", "neurokg"]

    def get_tool_name(self) -> str:
        return "datasets.list_resources"

    def get_tool_description(self) -> str:
        return (
            "List available resources for a dataset: local dataset path or BIDS path, "
            "existing derivatives (fmriprep/mriqc/glmfitlins), remote URLs, and "
            "availability flags."
        )

    def get_args_schema(self):
        return DatasetResourcesArgs

    def _run(
        self,
        dataset_ref: str,
        dataset_version: str | None = None,
        analysis_goal: str = "generic",
        semantic_intent: str | None = None,
        auto_heal: bool = False,
        run_bids_validation: bool = True,
        enforce_semantic_gate: bool = True,
        check_source_access: bool = True,
    ) -> ToolResult:
        resources = collect_dataset_resources(
            dataset_ref,
            dataset_version=dataset_version,
            analysis_goal=analysis_goal,
            semantic_intent=semantic_intent,
            auto_heal=auto_heal,
            run_bids_validation=run_bids_validation,
            enforce_semantic_gate=enforce_semantic_gate,
            check_source_access=check_source_access,
        )
        if not resources:
            return ToolResult(
                status="error",
                error=f"Dataset '{dataset_ref}' not found in catalog",
                data=None,
            )

        data: Dict[str, Any] = {
            "dataset_ref": dataset_ref,
            "resolved_dataset_id": resources.resolved_dataset_id or dataset_ref,
            "resolution_mode": resources.resolution_mode,
            "resolver_warnings": list(resources.resolver_warnings or []),
            "requested_version": (
                dataset_version.strip()
                if isinstance(dataset_version, str) and dataset_version.strip()
                else None
            ),
            "bids_path": str(resources.bids_path) if resources.bids_path else None,
            "is_bids_available": resources.is_bids_available,
            "derivatives": resources.derivatives,
            "available_derivatives": resources.available_derivatives,
            "remote_urls": resources.remote_urls,
            "size_bytes": resources.size_bytes,
            "analysis_goal": resources.analysis_goal,
            "source_trace": resources.source_trace,
            "required_files": resources.required_files,
            "readiness": resources.readiness,
            "auto_heal": resources.auto_heal,
            "semantic_match": resources.semantic_match,
            "source_access": resources.source_access,
        }

        return ToolResult(status="success", data=data)


class DatasetDescribeTool(NeuroToolWrapper):
    """Describe dataset resources with catalog + mount-aware summary."""

    TAGS = ["dataset_catalog", "neurokg"]

    def get_tool_name(self) -> str:
        return "datasets.describe_resources"

    def get_tool_description(self) -> str:
        return (
            "Describe dataset availability and content summary: participants/sessions, "
            "modalities/tasks, version hints, local mount readiness, derivatives, and "
            "required-file coverage."
        )

    def get_args_schema(self):
        return DatasetDescribeArgs

    def _run(
        self,
        dataset_ref: str,
        analysis_goal: str = "generic",
        include_files: bool = True,
        include_sensitive_paths: bool = False,
    ) -> ToolResult:
        resources = collect_dataset_resources(
            dataset_ref,
            dataset_version=None,
            analysis_goal=analysis_goal,
            auto_heal=False,
            run_bids_validation=False,
            enforce_semantic_gate=False,
        )
        if not resources:
            return ToolResult(
                status="error",
                error=f"Dataset '{dataset_ref}' not found in catalog",
                data=None,
            )

        resolved_dataset_ref = resources.resolved_dataset_id or dataset_ref
        record = _match_catalog_record(resolved_dataset_ref)
        required_files = dict(resources.required_files or {}) if include_files else {}
        groups = (
            required_files.get("groups") if isinstance(required_files, dict) else None
        )
        groups = groups if isinstance(groups, list) else []
        total_matched_files = 0
        for group in groups:
            counts = group.get("counts", {}) if isinstance(group, dict) else {}
            if isinstance(counts, dict):
                total_matched_files += sum(
                    int(v) for v in counts.values() if isinstance(v, (int, float))
                )

        derivatives = dict(resources.derivatives or {})
        available_derivatives = _coerce_string_list(resources.available_derivatives)
        derivative_items = []
        for kind, path in derivatives.items():
            derivative_items.append(
                {
                    "kind": kind,
                    "path": str(path) if include_sensitive_paths else None,
                    "available": kind in available_derivatives or bool(path),
                }
            )

        trace_summary = []
        for item in list(resources.source_trace or [])[:48]:
            if not isinstance(item, dict):
                continue
            trace_summary.append(
                {
                    "stage": str(item.get("stage", "unknown")),
                    "kind": str(item.get("kind", "unknown")),
                    "hit": bool(item.get("hit")),
                    "candidate": (
                        str(item.get("candidate"))
                        if include_sensitive_paths and item.get("candidate")
                        else None
                    ),
                    "root": (
                        str(item.get("root"))
                        if include_sensitive_paths and item.get("root")
                        else None
                    ),
                    "note": str(item.get("note")) if item.get("note") else None,
                }
            )

        data: Dict[str, Any] = {
            "dataset_ref": dataset_ref,
            "resolved_dataset_id": resolved_dataset_ref,
            "resolution_mode": resources.resolution_mode,
            "resolver_warnings": list(resources.resolver_warnings or []),
            "dataset_name": record.name if record else dataset_ref,
            "source_repo": record.source_repo if record else None,
            "source_repo_id": record.source_repo_id if record else None,
            "access_type": str(record.access_type) if record else None,
            "subjects_count": record.subjects_count if record else None,
            "sessions_count": record.sessions_count if record else None,
            "modalities": [str(m) for m in (record.modalities if record else [])],
            "tasks": list(record.tasks) if record else [],
            "source_version": record.source_version if record else None,
            "versions": _build_versions(record, resources),
            "readiness": resources.readiness,
            "storage": {
                "bids_path_available": resources.is_bids_available,
                "bids_path": (
                    str(resources.bids_path)
                    if include_sensitive_paths and resources.bids_path
                    else None
                ),
                "remote_urls": resources.remote_urls,
                "size_bytes": resources.size_bytes,
                "available_derivatives": available_derivatives,
                "derivatives": derivative_items,
            },
            "files": {
                "analysis_goal": (
                    required_files.get("analysis_goal")
                    if isinstance(required_files, dict)
                    else analysis_goal
                ),
                "required_total": (
                    required_files.get("required_total")
                    if isinstance(required_files, dict)
                    else None
                ),
                "required_passed": (
                    required_files.get("required_passed")
                    if isinstance(required_files, dict)
                    else None
                ),
                "all_required_passed": (
                    required_files.get("all_required_passed")
                    if isinstance(required_files, dict)
                    else None
                ),
                "missing_patterns": (
                    required_files.get("missing_patterns")
                    if isinstance(required_files, dict)
                    else []
                ),
                "groups": groups if include_files else [],
                "total_matched_files": total_matched_files if include_files else None,
            },
            "trace_summary": trace_summary,
            "source_access": resources.source_access,
        }

        return ToolResult(status="success", data=data)


def get_all_tools() -> list[NeuroToolWrapper]:
    return [DatasetResourcesTool(), DatasetDescribeTool()]
