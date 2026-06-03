"""Browse dataset-side assets before resolving specific files."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.br_kg import query_service
from brain_researcher.services.tools.asset_provenance import build_provenance_record
from brain_researcher.services.tools.glm_stat_map_selector import (
    GLMStatMapQuery,
    select_glm_stat_map_matches,
)
from brain_researcher.services.tools.resolve_dataset_asset_tool import (
    _bids_download_patterns,
    _confounds_download_patterns,
    _dataset_file_download_patterns,
    _derivative_download_patterns,
    _download_openneuro_subset_checked,
    _events_download_patterns,
    _find_downloaded_derivative_root,
    _first_existing,
    _normalize_derivative_kind,
    _search_files,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

_KINDS = {"all", "dataset", "derivative", "bids", "events", "confounds", "stat_map"}
_FILE_KINDS = {"bids", "events", "confounds", "stat_map"}
_FAST_DATASET_RESOURCE_KWARGS = {
    "run_bids_validation": False,
    "enforce_semantic_gate": False,
    "check_source_access": False,
}
_RUNTIME_ONLY_ARG_NAMES = {"output_dir", "work_dir"}


class ListDatasetAssetsArgs(BaseModel):
    """Arguments for enumerating dataset-side assets."""

    model_config = ConfigDict(extra="forbid")

    dataset_ref: str = Field(
        description="Dataset id or alias (for example ds000114 or ds:openneuro:ds000114)."
    )
    kind: str = Field(
        default="all",
        description=(
            "Browse scope. Supported values: all, dataset, derivative, bids, "
            "events, confounds, stat_map."
        ),
    )
    scope: str | None = Field(
        default=None,
        description="Legacy alias for kind. Accepted for backward compatibility.",
    )
    asset_type: str | None = Field(
        default=None,
        description="Legacy alias for kind. Accepted for backward compatibility.",
    )
    query: str | None = Field(
        default=None,
        description=(
            "Optional fuzzy query over IDs, titles, summaries, paths, and metadata."
        ),
    )
    analysis_goal: str = Field(
        default="generic",
        description="Readiness profile used during dataset resource resolution.",
    )
    subject_id: str | None = Field(default=None, description="Optional subject id.")
    subject: str | None = Field(
        default=None,
        description="Legacy alias for subject_id. Accepted for backward compatibility.",
    )
    session_id: str | None = Field(default=None, description="Optional session id.")
    session: str | None = Field(
        default=None,
        description="Legacy alias for session_id. Accepted for backward compatibility.",
    )
    task: str | None = Field(default=None, description="Optional task label.")
    run: str | None = Field(default=None, description="Optional run label.")
    datatype: str | None = Field(
        default=None, description="Optional BIDS datatype such as anat or func."
    )
    suffix: str | None = Field(default=None, description="Optional BIDS suffix.")
    space: str | None = Field(default=None, description="Optional space label.")
    derivative_kind: str | None = Field(
        default=None,
        description="Optional derivative family such as fmriprep.",
    )
    derivative_type: str | None = Field(
        default=None,
        description=(
            "Legacy alias for derivative_kind. Accepted for backward compatibility."
        ),
    )
    contrast: str | None = Field(
        default=None, description="Optional GLM contrast selector."
    )
    statistic: str | None = Field(
        default=None, description="Optional GLM statistic selector."
    )
    node: str | None = Field(default=None, description="Optional GLM node selector.")
    include_metadata: bool = Field(
        default=False,
        description="Include raw metadata payloads for each returned asset.",
    )
    limit: int = Field(
        default=200,
        ge=1,
        le=1000,
        description="Maximum number of assets to return.",
    )
    download_missing: bool = Field(
        default=False,
        description=(
            "If true and local files are missing, selectively download matching public "
            "OpenNeuro files into a writable cache before browsing."
        ),
    )
    download_root: str | None = Field(
        default=None,
        description=(
            "Optional writable cache root for selective OpenNeuro downloads. Defaults "
            "to BR_DATA_CACHE_ROOT/openneuro/<dataset_id>."
        ),
    )


def _normalize_kind(value: str) -> str:
    kind = str(value or "").strip().lower()
    kind = {
        "derivatives": "derivative",
        "datasets": "dataset",
    }.get(kind, kind)
    if kind not in _KINDS:
        supported = ", ".join(sorted(_KINDS))
        raise ValueError(f"Unsupported kind '{value}'. Supported values: {supported}")
    return kind


def _normalize_subject_id(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("sub-"):
        return text
    return f"sub-{text}"


def _normalize_session_id(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("ses-"):
        return text
    return f"ses-{text}"


def _normalize_legacy_filter_aliases(kwargs: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(kwargs)

    kind = normalized.get("kind")
    for alias_name in ("scope", "asset_type"):
        alias_value = normalized.pop(alias_name, None)
        if alias_value in (None, ""):
            continue
        alias_kind = _normalize_kind(str(alias_value))
        if kind not in (None, "", "all") and _normalize_kind(str(kind)) != alias_kind:
            raise ValueError(
                "Conflicting kind, scope, and asset_type values were provided."
            )
        kind = alias_kind
    if kind not in (None, ""):
        normalized["kind"] = kind

    derivative_type = normalized.pop("derivative_type", None)
    derivative_kind = normalized.get("derivative_kind")
    if derivative_type not in (None, ""):
        if derivative_kind not in (None, "") and str(derivative_kind).strip().lower() != str(
            derivative_type
        ).strip().lower():
            raise ValueError(
                "Conflicting derivative_kind and derivative_type values were provided."
            )
        if derivative_kind in (None, ""):
            normalized["derivative_kind"] = derivative_type

    subject = normalized.pop("subject", None)
    subject_id = normalized.get("subject_id")
    if subject not in (None, ""):
        alias_subject = _normalize_subject_id(subject)
        if subject_id not in (None, "") and _normalize_subject_id(subject_id) != alias_subject:
            raise ValueError(
                "Conflicting subject_id and subject values were provided."
            )
        if subject_id in (None, ""):
            normalized["subject_id"] = alias_subject

    session = normalized.pop("session", None)
    session_id = normalized.get("session_id")
    if session not in (None, ""):
        alias_session = _normalize_session_id(session)
        if session_id not in (None, "") and _normalize_session_id(session_id) != alias_session:
            raise ValueError(
                "Conflicting session_id and session values were provided."
            )
        if session_id in (None, ""):
            normalized["session_id"] = alias_session

    return normalized


def _normalize_query(value: str | None) -> str:
    return str(value or "").strip()


def _matches_query(asset: dict[str, Any], query: str | None) -> bool:
    if not query:
        return True
    needle = _normalize_query(query)
    if not needle:
        return True
    token = needle.lower()

    metadata = asset.get("metadata") or {}
    fields: list[Any] = [
        asset.get("id") or "",
        asset.get("canonical_id") or "",
        asset.get("kind") or "",
        asset.get("title") or "",
        asset.get("summary") or "",
        asset.get("source") or "",
        asset.get("source_path") or "",
        asset.get("relative_path") or "",
        asset.get("dataset_ref") or "",
        asset.get("resolved_dataset_id") or "",
        asset.get("derivative_kind") or "",
        asset.get("subject_id") or "",
        asset.get("session_id") or "",
        asset.get("task") or "",
        asset.get("run") or "",
        asset.get("datatype") or "",
        asset.get("suffix") or "",
        asset.get("space") or "",
        asset.get("contrast") or "",
        asset.get("statistic") or "",
        asset.get("level") or "",
        asset.get("estimator") or "",
    ]
    manifest_fields = asset.get("manifest_fields") or {}
    if isinstance(manifest_fields, dict):
        fields.extend(manifest_fields.keys())
        fields.extend(manifest_fields.values())
    elif isinstance(manifest_fields, list | tuple):
        fields.extend(manifest_fields)
    fields.extend(metadata.values())
    return any(token in str(value).lower() for value in fields if value not in (None, ""))


def _common_summary(
    resources: Any, dataset_ref: str, dataset_resolution: Any
) -> dict[str, Any]:
    metadata = getattr(dataset_resolution, "metadata", {}) or {}
    return {
        "dataset_ref": dataset_ref,
        "resolved_dataset_id": getattr(resources, "resolved_dataset_id", None)
        or dataset_ref,
        "analysis_goal": getattr(resources, "analysis_goal", "generic"),
        "resolution_mode": getattr(resources, "resolution_mode", ""),
        "readiness_status": (getattr(resources, "readiness", {}) or {}).get(
            "status", ""
        ),
        "available_derivatives": list(
            getattr(resources, "available_derivatives", []) or []
        ),
        "source_repo": getattr(dataset_resolution, "source_repo", "") or "",
        "display_name": getattr(dataset_resolution, "display_name", None)
        or getattr(dataset_resolution, "name", None)
        or "",
        "tasks": list(metadata.get("tasks", []) or []),
        "modalities": list(metadata.get("modalities", []) or []),
    }


def _dataset_identity(resources: Any) -> SimpleNamespace:
    metadata = dict(getattr(resources, "dataset_metadata", {}) or {})
    return SimpleNamespace(
        source_repo=getattr(resources, "source_repo", "") or "",
        display_name=getattr(resources, "display_name", "") or "",
        name=getattr(resources, "dataset_name", "") or "",
        metadata=metadata,
    )


def _dataset_context(
    dataset_ref: str, analysis_goal: str
) -> tuple[Any, Any, Path | None]:
    resources = query_service.dataset_resources(
        dataset_ref,
        analysis_goal=analysis_goal,
        **_FAST_DATASET_RESOURCE_KWARGS,
    )
    if resources is None:
        raise FileNotFoundError(
            f"Dataset '{dataset_ref}' was not found in dataset resources."
        )
    dataset_resolution = _dataset_identity(resources)
    bids_path = _first_existing(
        Path(resources.bids_path).expanduser()
        if getattr(resources, "bids_path", None)
        else None
    )
    return resources, dataset_resolution, bids_path


def _resource_with_derivative(resources: Any, derivative_kind: str, root: Path) -> Any:
    payload = dict(getattr(resources, "__dict__", {}) or {})
    derivatives = dict(getattr(resources, "derivatives", {}) or {})
    derivatives[derivative_kind] = str(root)
    payload["derivatives"] = derivatives
    available = list(getattr(resources, "available_derivatives", []) or [])
    if derivative_kind not in available:
        available.append(derivative_kind)
    payload["available_derivatives"] = available
    return SimpleNamespace(**payload)


def _base_row(
    *,
    kind: str,
    title: str,
    summary: str,
    dataset_ref: str,
    resolved_dataset_id: str,
    source_path: str | Path | None,
    roots: list[str | Path | None],
    source: str,
    metadata: dict[str, Any] | None = None,
    dataset_id: str | None = None,
    derivative_kind: str | None = None,
    subject_id: str | None = None,
    session_id: str | None = None,
    task: str | None = None,
    run: str | None = None,
    datatype: str | None = None,
    suffix: str | None = None,
    space: str | None = None,
    contrast: str | None = None,
    statistic: str | None = None,
    level: str | None = None,
    estimator: str | None = None,
    preferred_id: str | None = None,
    include_metadata: bool = False,
) -> dict[str, Any]:
    record = build_provenance_record(
        kind=kind,
        preferred_id=preferred_id,
        source=source,
        source_path=source_path,
        roots=roots,
        dataset_id=dataset_id or resolved_dataset_id,
        derivative_kind=derivative_kind,
        subject_id=subject_id,
        session_id=session_id,
        task=task,
        run=run,
        datatype=datatype,
        suffix=suffix,
        space=space,
        contrast=contrast,
        statistic=statistic,
        level=level,
        estimator=estimator,
        metadata=metadata,
    )
    row = {
        "id": record["canonical_id"],
        "canonical_id": record["canonical_id"],
        "kind": kind,
        "family_id": "dataset_assets",
        "title": title,
        "summary": summary,
        "dataset_ref": dataset_ref,
        "resolved_dataset_id": resolved_dataset_id,
        "source": record["source"],
        "source_path": record["source_path"],
        "relative_path": record["relative_path"],
        "checksum": record["checksum"],
        "level": record["level"],
        "estimator": record["estimator"],
        "manifest_fields": record["manifest_fields"],
        "derivative_kind": derivative_kind or "",
        "subject_id": subject_id or "",
        "session_id": session_id or "",
        "task": task or "",
        "run": run or "",
        "datatype": datatype or "",
        "suffix": suffix or "",
        "space": space or "",
        "contrast": contrast or "",
        "statistic": statistic or "",
    }
    if include_metadata:
        row["metadata"] = dict(metadata or {})
    return row


def _write_inventory_json(output_dir: str, assets: list[dict[str, Any]]) -> str:
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / "dataset_asset_inventory.json"
    output_path.write_text(json.dumps(assets, indent=2), encoding="utf-8")
    return str(output_path)


def _dataset_rows(
    *,
    dataset_ref: str,
    resolved_dataset_id: str,
    bids_path: Path | None,
    dataset_resolution: Any,
    include_metadata: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    dataset_meta = getattr(dataset_resolution, "metadata", {}) or {}
    roots = [bids_path]
    if bids_path:
        rows.append(
            _base_row(
                kind="dataset",
                title="BIDS root",
                summary="Resolved local BIDS root for the dataset.",
                dataset_ref=dataset_ref,
                resolved_dataset_id=resolved_dataset_id,
                source_path=bids_path,
                roots=roots,
                source="dataset_resources",
                metadata=dataset_meta,
                preferred_id=f"dataset:{resolved_dataset_id}:bids-root",
                include_metadata=include_metadata,
            )
        )
        for filename in ("dataset_description.json", "participants.tsv"):
            candidate = bids_path / filename
            if candidate.exists():
                rows.append(
                    _base_row(
                        kind="dataset",
                        title=filename,
                        summary=f"Dataset-level file `{filename}`.",
                        dataset_ref=dataset_ref,
                        resolved_dataset_id=resolved_dataset_id,
                        source_path=candidate,
                        roots=roots,
                        source="dataset_root",
                        metadata=dataset_meta,
                        suffix=filename,
                        preferred_id=f"dataset:{resolved_dataset_id}:{filename}",
                        include_metadata=include_metadata,
                    )
                )
    return rows


def _derivative_rows(
    *,
    dataset_ref: str,
    resolved_dataset_id: str,
    resources: Any,
    include_metadata: bool,
    requested_kind: str | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    derivatives = dict(getattr(resources, "derivatives", {}) or {})
    available = set(getattr(resources, "available_derivatives", []) or [])
    normalized_requested = _normalize_derivative_kind(requested_kind)
    for derivative_kind, root in sorted(derivatives.items()):
        if normalized_requested and derivative_kind != normalized_requested:
            continue
        if not root:
            continue
        root_path = _first_existing(Path(root).expanduser())
        if root_path is None:
            continue
        rows.append(
            _base_row(
                kind="derivative",
                title=derivative_kind,
                summary=f"Derivative root for `{derivative_kind}`.",
                dataset_ref=dataset_ref,
                resolved_dataset_id=resolved_dataset_id,
                source_path=root_path,
                roots=[root_path],
                source="dataset_resources",
                metadata={"available": derivative_kind in available},
                derivative_kind=derivative_kind,
                preferred_id=f"derivative:{resolved_dataset_id}:{derivative_kind}",
                include_metadata=include_metadata,
            )
        )
    return rows


def _bids_rows(
    *,
    dataset_ref: str,
    resolved_dataset_id: str,
    bids_path: Path | None,
    args: ListDatasetAssetsArgs,
) -> list[dict[str, Any]]:
    if bids_path is None:
        return []
    if not (args.subject_id and args.datatype and args.suffix):
        return []
    matches = _search_files(
        bids_path,
        subject_id=args.subject_id,
        session_id=args.session_id,
        datatype=args.datatype,
        task=args.task,
        run=args.run,
        space=args.space,
        suffix=args.suffix,
    )
    rows: list[dict[str, Any]] = []
    for path in matches:
        rows.append(
            _base_row(
                kind="bids",
                title=path.name,
                summary="Targeted BIDS file candidate.",
                dataset_ref=dataset_ref,
                resolved_dataset_id=resolved_dataset_id,
                source_path=path,
                roots=[bids_path],
                source="bids_local_scan",
                subject_id=args.subject_id,
                session_id=args.session_id,
                task=args.task,
                run=args.run,
                datatype=args.datatype,
                suffix=args.suffix,
                space=args.space,
                include_metadata=args.include_metadata,
            )
        )
    return rows


def _events_rows(
    *,
    dataset_ref: str,
    resolved_dataset_id: str,
    bids_path: Path | None,
    args: ListDatasetAssetsArgs,
) -> list[dict[str, Any]]:
    if bids_path is None or not (args.subject_id or args.task):
        return []
    matches = _search_files(
        bids_path,
        subject_id=args.subject_id,
        session_id=args.session_id,
        datatype=args.datatype or "func",
        task=args.task,
        run=args.run,
        suffix="events",
        extension=".tsv",
    )
    return [
        _base_row(
            kind="events",
            title=path.name,
            summary="Targeted events.tsv candidate.",
            dataset_ref=dataset_ref,
            resolved_dataset_id=resolved_dataset_id,
            source_path=path,
            roots=[bids_path],
            source="bids_local_scan",
            subject_id=args.subject_id,
            session_id=args.session_id,
            task=args.task,
            run=args.run,
            datatype=args.datatype or "func",
            suffix="events",
            include_metadata=args.include_metadata,
        )
        for path in matches
    ]


def _confounds_rows(
    *,
    dataset_ref: str,
    resolved_dataset_id: str,
    resources: Any,
    args: ListDatasetAssetsArgs,
) -> list[dict[str, Any]]:
    if not (args.subject_id or args.task):
        return []
    derivatives = dict(getattr(resources, "derivatives", {}) or {})
    fmriprep_root = derivatives.get("fmriprep")
    if not fmriprep_root:
        return []
    root_path = _first_existing(Path(fmriprep_root).expanduser())
    if root_path is None:
        return []
    matches = _search_files(
        root_path,
        subject_id=args.subject_id,
        session_id=args.session_id,
        datatype=args.datatype or "func",
        task=args.task,
        run=args.run,
        space=args.space,
        desc="confounds",
        suffix="timeseries",
        extension=".tsv",
    )
    return [
        _base_row(
            kind="confounds",
            title=path.name,
            summary="Targeted fMRIPrep confounds file candidate.",
            dataset_ref=dataset_ref,
            resolved_dataset_id=resolved_dataset_id,
            source_path=path,
            roots=[root_path],
            source="fmriprep_local_scan",
            derivative_kind="fmriprep",
            subject_id=args.subject_id,
            session_id=args.session_id,
            task=args.task,
            run=args.run,
            datatype=args.datatype or "func",
            suffix="timeseries",
            space=args.space,
            include_metadata=args.include_metadata,
        )
        for path in matches
    ]


def _stat_map_rows(
    *,
    dataset_ref: str,
    resolved_dataset_id: str,
    resources: Any,
    args: ListDatasetAssetsArgs,
) -> list[dict[str, Any]]:
    if not any(
        [
            str(args.contrast or "").strip(),
            str(args.task or "").strip(),
            str(args.node or "").strip(),
            str(args.subject_id or "").strip(),
            str(args.statistic or "").strip(),
            str(args.space or "").strip(),
        ]
    ):
        return []
    derivatives = dict(getattr(resources, "derivatives", {}) or {})
    derivative_kind = _normalize_derivative_kind(args.derivative_kind)
    if derivative_kind:
        derivative_roots = {
            derivative_kind: derivatives.get(derivative_kind)
            for derivative_kind in [derivative_kind]
            if derivatives.get(derivative_kind)
        }
    else:
        derivative_roots = dict(derivatives)
    matches = select_glm_stat_map_matches(
        query=GLMStatMapQuery(
            dataset_ref=dataset_ref,
            task=args.task,
            node=args.node,
            subject_id=args.subject_id,
            session_id=args.session_id,
            run=args.run,
            contrast=args.contrast,
            statistic=args.statistic,
            space=args.space,
        ),
        derivative_roots=derivative_roots,
        include_registry=True,
    )
    rows: list[dict[str, Any]] = []
    for match in matches:
        metadata = {
            "asset_id": match.get("asset_id") or "",
            "canonical_runtime_name": match.get("canonical_runtime_name") or "",
            "space_inferred": bool(match.get("space_inferred")),
            "format": match.get("format") or "",
        }
        source_path = match.get("source_path") or match.get("path") or ""
        root = match.get("root") or derivative_roots.get(
            match.get("derivative_kind") or ""
        )
        roots = [root] if root else []
        rows.append(
            _base_row(
                kind="stat_map",
                title=Path(str(source_path)).name if source_path else "stat_map",
                summary="Targeted GLM stat-map candidate.",
                dataset_ref=dataset_ref,
                resolved_dataset_id=resolved_dataset_id,
                source_path=source_path,
                roots=roots,
                source=match.get("source") or "",
                metadata=metadata,
                dataset_id=match.get("dataset_id") or resolved_dataset_id,
                derivative_kind=match.get("derivative_kind") or "",
                subject_id=match.get("subject_id") or "",
                session_id=match.get("session_id") or "",
                task=match.get("task") or "",
                run=match.get("run") or "",
                space=match.get("space") or "",
                contrast=match.get("contrast") or "",
                statistic=match.get("statistic") or "",
                level=match.get("level") or "",
                preferred_id=match.get("asset_id") or None,
                include_metadata=args.include_metadata,
            )
        )
    return rows


class ListDatasetAssetsTool(NeuroToolWrapper):
    """Browse local dataset-side assets before resolving a specific file."""

    execution_backend = "python"
    TIMEOUT_S = 300
    TAGS = ["dataset_catalog", "inventory", "derivative"]

    def get_tool_name(self) -> str:
        return "list_dataset_assets"

    def get_tool_description(self) -> str:
        return (
            "Browse local dataset assets before resolve: dataset files, derivative "
            "roots, targeted BIDS/events/confounds candidates, structured GLM stat "
            "maps, and optional fuzzy query filtering."
        )

    def get_args_schema(self):
        return ListDatasetAssetsArgs

    def _run(self, **kwargs) -> ToolResult:
        output_dir = kwargs.get("output_dir")
        user_kwargs = {
            key: value
            for key, value in kwargs.items()
            if key not in _RUNTIME_ONLY_ARG_NAMES
        }
        try:
            args = ListDatasetAssetsArgs(**user_kwargs)
            normalized_kwargs = _normalize_legacy_filter_aliases(
                args.model_dump(exclude_none=True)
            )
            args = ListDatasetAssetsArgs(**normalized_kwargs)
            kind = _normalize_kind(args.kind)
        except Exception as exc:
            return ToolResult(status="error", error=str(exc), data={})

        try:
            resources, dataset_resolution, bids_path = _dataset_context(
                args.dataset_ref, args.analysis_goal
            )
        except Exception as exc:
            return ToolResult(
                status="error",
                error=str(exc),
                data={"dataset_ref": args.dataset_ref},
            )

        resolved_dataset_id = (
            getattr(resources, "resolved_dataset_id", None) or args.dataset_ref
        )
        effective_bids_path = bids_path
        effective_resources = resources
        download_infos: list[dict[str, Any]] = []

        if args.download_missing:
            if effective_bids_path is None and kind in {"all", "dataset"}:
                try:
                    effective_bids_path, download_info = (
                        _download_openneuro_subset_checked(
                            resources=resources,
                            dataset_ref=args.dataset_ref,
                            resolved_dataset_id=resolved_dataset_id,
                            download_root=args.download_root,
                            include_patterns=_dataset_file_download_patterns(None),
                        )
                    )
                    download_infos.append(download_info)
                except Exception:
                    pass
            if (
                effective_bids_path is None
                and kind in {"all", "bids"}
                and args.subject_id
                and args.datatype
                and args.suffix
            ):
                try:
                    effective_bids_path, download_info = (
                        _download_openneuro_subset_checked(
                            resources=resources,
                            dataset_ref=args.dataset_ref,
                            resolved_dataset_id=resolved_dataset_id,
                            download_root=args.download_root,
                            include_patterns=_bids_download_patterns(args),
                        )
                    )
                    download_infos.append(download_info)
                except Exception:
                    pass
            if (
                effective_bids_path is None
                and kind in {"all", "events"}
                and (args.subject_id or args.task)
            ):
                try:
                    effective_bids_path, download_info = (
                        _download_openneuro_subset_checked(
                            resources=resources,
                            dataset_ref=args.dataset_ref,
                            resolved_dataset_id=resolved_dataset_id,
                            download_root=args.download_root,
                            include_patterns=_events_download_patterns(args),
                        )
                    )
                    download_infos.append(download_info)
                except Exception:
                    pass

            requested_derivative_kind = _normalize_derivative_kind(args.derivative_kind)
            derivative_download_specs: list[tuple[str, list[str]]] = []
            if kind in {"all", "derivative"} and requested_derivative_kind:
                derivative_download_specs.append(
                    (
                        requested_derivative_kind,
                        _derivative_download_patterns(
                            requested_derivative_kind,
                            subject_id=args.subject_id,
                            session_id=args.session_id,
                            task=args.task,
                            run=args.run,
                            space=args.space,
                            suffix=args.suffix,
                            extensions=[".nii.gz", ".nii", ".json", ".tsv", ".txt"],
                        ),
                    )
                )
            if kind in {"all", "confounds"} and (args.subject_id or args.task):
                derivative_download_specs.append(
                    ("fmriprep", _confounds_download_patterns(args))
                )

            for derivative_kind, patterns in derivative_download_specs:
                existing_root = _first_existing(
                    Path(
                        dict(getattr(effective_resources, "derivatives", {}) or {}).get(
                            derivative_kind, ""
                        )
                    ).expanduser()
                    if dict(getattr(effective_resources, "derivatives", {}) or {}).get(
                        derivative_kind
                    )
                    else None
                )
                if existing_root is not None:
                    continue
                try:
                    downloaded_root, download_info = _download_openneuro_subset_checked(
                        resources=resources,
                        dataset_ref=args.dataset_ref,
                        resolved_dataset_id=resolved_dataset_id,
                        download_root=args.download_root,
                        include_patterns=patterns,
                    )
                except Exception:
                    continue
                resolved_downloaded_root = _find_downloaded_derivative_root(
                    downloaded_root, derivative_kind
                )
                if resolved_downloaded_root is None:
                    continue
                effective_resources = _resource_with_derivative(
                    effective_resources, derivative_kind, resolved_downloaded_root
                )
                download_infos.append(download_info)

        assets: list[dict[str, Any]] = []
        needs_filters = False
        suggested_filters: list[str] = []

        if kind in {"all", "dataset"}:
            assets.extend(
                _dataset_rows(
                    dataset_ref=args.dataset_ref,
                    resolved_dataset_id=resolved_dataset_id,
                    bids_path=effective_bids_path,
                    dataset_resolution=dataset_resolution,
                    include_metadata=args.include_metadata,
                )
            )
        if kind in {"all", "derivative"}:
            assets.extend(
                _derivative_rows(
                    dataset_ref=args.dataset_ref,
                    resolved_dataset_id=resolved_dataset_id,
                    resources=effective_resources,
                    include_metadata=args.include_metadata,
                    requested_kind=args.derivative_kind,
                )
            )
        if kind in {"all", "bids"}:
            bids_assets = _bids_rows(
                dataset_ref=args.dataset_ref,
                resolved_dataset_id=resolved_dataset_id,
                bids_path=effective_bids_path,
                args=args,
            )
            assets.extend(bids_assets)
            if not bids_assets and kind in {"all", "bids"}:
                needs_filters = needs_filters or kind == "bids"
                if not (args.subject_id and args.datatype and args.suffix):
                    suggested_filters.append("subject_id+datatype+suffix")
        if kind in {"all", "events"}:
            event_assets = _events_rows(
                dataset_ref=args.dataset_ref,
                resolved_dataset_id=resolved_dataset_id,
                bids_path=effective_bids_path,
                args=args,
            )
            assets.extend(event_assets)
            if (
                not event_assets
                and kind == "events"
                and not (args.subject_id or args.task)
            ):
                needs_filters = True
                suggested_filters.append("subject_id or task")
        if kind in {"all", "confounds"}:
            confound_assets = _confounds_rows(
                dataset_ref=args.dataset_ref,
                resolved_dataset_id=resolved_dataset_id,
                resources=effective_resources,
                args=args,
            )
            assets.extend(confound_assets)
            if (
                not confound_assets
                and kind == "confounds"
                and not (args.subject_id or args.task)
            ):
                needs_filters = True
                suggested_filters.append("subject_id or task")
        if kind in {"all", "stat_map"}:
            stat_map_assets = _stat_map_rows(
                dataset_ref=args.dataset_ref,
                resolved_dataset_id=resolved_dataset_id,
                resources=resources,
                args=args,
            )
            assets.extend(stat_map_assets)
            if (
                not stat_map_assets
                and kind == "stat_map"
                and not any(
                    [
                        args.contrast,
                        args.task,
                        args.node,
                        args.subject_id,
                        args.statistic,
                        args.space,
                    ]
                )
            ):
                needs_filters = True
                suggested_filters.append(
                    "contrast/task/node/subject_id/statistic/space"
                )

        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for asset in assets:
            key = str(asset.get("id") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(asset)
        filtered = [asset for asset in deduped if _matches_query(asset, args.query)]
        limited = filtered[: args.limit]

        kind_counts: dict[str, int] = {}
        for asset in filtered:
            asset_kind = str(asset.get("kind") or "")
            kind_counts[asset_kind] = kind_counts.get(asset_kind, 0) + 1

        outputs: dict[str, Any] = {
            "assets": limited,
            "asset_ids": [asset["id"] for asset in limited],
        }
        if output_dir:
            outputs["inventory_json"] = _write_inventory_json(output_dir, limited)

        summary = _common_summary(
            effective_resources, args.dataset_ref, dataset_resolution
        )
        summary.update(
            {
                "browse_kind": kind,
                "query": args.query or "",
                "count": len(limited),
                "total_matches": len(filtered),
                "needs_filters": needs_filters,
                "suggested_filters": sorted(set(suggested_filters)),
                "kind_counts": kind_counts,
                "filters": {
                    "kind": kind,
                    "subject_id": args.subject_id or "",
                    "session_id": args.session_id or "",
                    "task": args.task or "",
                    "run": args.run or "",
                    "datatype": args.datatype or "",
                    "suffix": args.suffix or "",
                    "space": args.space or "",
                    "derivative_kind": args.derivative_kind or "",
                    "contrast": args.contrast or "",
                    "statistic": args.statistic or "",
                    "node": args.node or "",
                },
            }
        )
        if download_infos:
            summary["download_missing_used"] = True
            summary["download_roots"] = sorted(
                {
                    info["download_root"]
                    for info in download_infos
                    if info.get("download_root")
                }
            )
        return ToolResult(
            status="success",
            data={
                "outputs": outputs,
                "summary": summary,
                "downloads": download_infos or None,
            },
        )


class ListDatasetAssetsTools:
    @staticmethod
    def get_all_tools():
        return [ListDatasetAssetsTool()]


__all__ = ["ListDatasetAssetsTool", "ListDatasetAssetsTools"]
