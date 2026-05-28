"""Unified resolver for reusable dataset-side assets."""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Iterable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel, Field

from brain_researcher.core.ingestion.neuro_downloads import (
    download_openneuro_subset,
)
from brain_researcher.services.neurokg import query_service
from brain_researcher.services.tools.asset_provenance import build_provenance_record
from brain_researcher.services.tools.glm_stat_map_selector import (
    GLMStatMapQuery,
    select_glm_stat_map_matches,
)
from brain_researcher.services.tools.resolve_bids_tool import ResolveBIDSTool
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

_KIND_ALIASES = {
    "auto": "auto",
    "bids": "bids",
    "catalog": "dataset",
    "confounds": "confounds",
    "dataset": "dataset",
    "derivative": "derivative",
    "derivatives": "derivative",
    "events": "events",
    "metadata": "dataset",
    "qc": "derivative",
    "resource": "dataset",
    "statmap": "stat_map",
    "statmaps": "stat_map",
    "statsmap": "stat_map",
    "statsmaps": "stat_map",
    "glmstatmap": "stat_map",
    "glmstatmaps": "stat_map",
    "glmmap": "stat_map",
    "glmmaps": "stat_map",
    "map": "stat_map",
}
_DATASET_FILE_ALIASES = {
    "datasetdescription": "dataset_description.json",
    "datasetdescriptionjson": "dataset_description.json",
    "participants": "participants.tsv",
    "participantstsv": "participants.tsv",
}
_EVENT_ALIASES = {"events", "eventstsv"}
_CONFOUND_ALIASES = {"confounds", "confoundstsv", "descconfounds"}
_STAT_MAP_ALIASES = {
    "statmap",
    "statmaps",
    "glmstatmap",
    "glmstatmaps",
    "statsmap",
    "statsmaps",
}
_DERIVATIVE_KIND_ALIASES = {
    "fitlins": "glmfitlins",
    "fmriprep": "fmriprep",
    "glmfitlins": "glmfitlins",
    "glm": "glmfitlins",
    "mriqc": "mriqc",
    "xcpd": "xcpd",
}
_FAST_DATASET_RESOURCE_KWARGS = {
    "run_bids_validation": False,
    "enforce_semantic_gate": False,
    "check_source_access": False,
}
_DEFAULT_OPENNEURO_DOWNLOAD_ROOT = (
    Path(os.getenv("BR_DATA_CACHE_ROOT", "tmp/dataset_cache")) / "openneuro"
)
_PUBLIC_DERIVATIVE_DIR_ALIASES = {
    "fmriprep": ("fmriprep",),
    "glmfitlins": ("glmfitlins", "fitlins"),
    "mriqc": ("mriqc",),
    "xcpd": ("xcpd", "xcp_d"),
}


class ResolveDatasetAssetArgs(BaseModel):
    """Arguments for unified dataset asset resolution."""

    dataset_ref: str = Field(
        description="Dataset id or alias (for example ds000114 or ds:openneuro:ds000114)."
    )
    kind: str = Field(
        default="auto",
        description=(
            "Asset kind. Supported values: auto, dataset, bids, derivative, "
            "events, confounds, stat_map."
        ),
    )
    asset_name: str | None = Field(
        default=None,
        description=(
            "Optional asset query, for example dataset_description, participants, "
            "events, confounds, fmriprep, glmfitlins."
        ),
    )
    analysis_goal: str = Field(
        default="generic",
        description="Readiness profile used during dataset resource resolution.",
    )
    dataset_version: str | None = Field(
        default=None,
        description="Optional dataset version hint.",
    )
    subject_id: str | None = Field(
        default=None,
        description="Optional subject id without or with sub- prefix.",
    )
    session_id: str | None = Field(
        default=None,
        description="Optional session id without or with ses- prefix.",
    )
    task: str | None = Field(
        default=None,
        description="Optional BIDS task label for events/confounds/file lookup.",
    )
    run: str | None = Field(
        default=None,
        description="Optional run label for events/confounds/file lookup.",
    )
    datatype: str | None = Field(
        default=None,
        description="Optional BIDS datatype such as anat, func, dwi, eeg, ieeg.",
    )
    suffix: str | None = Field(
        default=None,
        description="Optional BIDS suffix such as T1w, bold, events.",
    )
    space: str | None = Field(
        default=None,
        description="Optional space entity for derivatives or BIDS queries.",
    )
    desc: str | None = Field(
        default=None,
        description="Optional desc entity for derivatives or BIDS queries.",
    )
    derivative_kind: str | None = Field(
        default=None,
        description="Optional derivative family such as fmriprep, mriqc, glmfitlins.",
    )
    contrast: str | None = Field(
        default=None,
        description="Optional GLM contrast selector for derivative stat-map lookup.",
    )
    statistic: str | None = Field(
        default=None,
        description="Optional GLM statistic selector such as z or t.",
    )
    node: str | None = Field(
        default=None,
        description="Optional GLM node selector such as subjectLevel or runLevel.",
    )
    download_missing: bool = Field(
        default=False,
        description=(
            "If true and local files are missing, selectively download matching public "
            "OpenNeuro files into a writable cache before resolving."
        ),
    )
    download_root: str | None = Field(
        default=None,
        description=(
            "Optional writable cache root for selective OpenNeuro downloads. Defaults "
            "to BR_DATA_CACHE_ROOT/openneuro/<dataset_id>."
        ),
    )


def _normalize_token(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _normalize_kind(kind: str) -> str:
    normalized = _KIND_ALIASES.get(_normalize_token(kind))
    if normalized is None:
        supported = ", ".join(sorted(_KIND_ALIASES))
        raise ValueError(f"Unsupported kind '{kind}'. Supported values: {supported}")
    return normalized


def _normalize_derivative_kind(value: str | None) -> str:
    token = _normalize_token(value)
    return _DERIVATIVE_KIND_ALIASES.get(token, token)


def _extract_dataset_simple_id(*candidates: str | None) -> str:
    for candidate in candidates:
        text = str(candidate or "").strip()
        if not text:
            continue
        match = re.search(r"(ds\d{6,})", text, flags=re.IGNORECASE)
        if match:
            return match.group(1).lower()
    return ""


def _openneuro_download_root(
    dataset_simple_id: str,
    *,
    download_root: str | None,
) -> Path:
    base_root = (
        Path(download_root).expanduser()
        if download_root
        else _DEFAULT_OPENNEURO_DOWNLOAD_ROOT
    )
    if base_root.name != dataset_simple_id:
        base_root = base_root / dataset_simple_id
    return base_root.resolve()


def _is_public_openneuro_dataset(resources: Any, dataset_ref: str) -> bool:
    remote_urls = dict(getattr(resources, "remote_urls", {}) or {})
    source_repo = str(getattr(resources, "source_repo", "") or "").strip().lower()
    dataset_simple_id = _extract_dataset_simple_id(
        getattr(resources, "resolved_dataset_id", None), dataset_ref
    )
    return bool(
        dataset_simple_id
        and (
            "openneuro" in source_repo
            or bool(remote_urls.get("openneuro"))
            or dataset_ref.strip().lower().startswith("ds")
        )
    )


def _downloadable_dataset_guard(resources: Any, dataset_ref: str) -> str:
    dataset_simple_id = _extract_dataset_simple_id(
        getattr(resources, "resolved_dataset_id", None), dataset_ref
    )
    if not dataset_simple_id or not _is_public_openneuro_dataset(resources, dataset_ref):
        raise RuntimeError(
            "download_missing is currently supported only for public OpenNeuro "
            "datasets with dsXXXXXX identifiers."
        )
    return dataset_simple_id


def _has_glm_stat_map_selectors(args: ResolveDatasetAssetArgs) -> bool:
    return any(
        [
            str(args.contrast or "").strip(),
            str(args.statistic or "").strip(),
            str(args.node or "").strip(),
        ]
    )


def _materialize_file(path: Path, output_dir: str | None) -> Path:
    if not output_dir or not path.is_file():
        return path
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    destination = output_root / path.name
    if destination.resolve() != path.resolve():
        shutil.copy2(path, destination)
    return destination


def _copy_file_map(
    mapping: dict[str, Path | None],
    output_dir: str | None,
) -> dict[str, str]:
    outputs: dict[str, str] = {}
    for key, path in mapping.items():
        if path is None or not path.exists():
            continue
        outputs[key] = str(_materialize_file(path, output_dir))
    return outputs


def _download_pattern_matches(
    dataset_root: Path, patterns: Iterable[str]
) -> list[Path]:
    matches: list[Path] = []
    seen: set[str] = set()
    for pattern in patterns:
        text = str(pattern or "").strip()
        if not text:
            continue
        for candidate in sorted(dataset_root.glob(text)):
            if not candidate.is_file():
                continue
            resolved = candidate.resolve()
            key = str(resolved)
            if key in seen:
                continue
            seen.add(key)
            matches.append(resolved)
    return matches


def _subject_label(subject_id: str | None) -> str:
    if not subject_id:
        return ""
    subject = str(subject_id).strip()
    if subject.startswith("sub-"):
        return subject
    return f"sub-{subject}"


def _session_label(session_id: str | None) -> str:
    if not session_id:
        return ""
    session = str(session_id).strip()
    if session.startswith("ses-"):
        return session
    return f"ses-{session}"


def _file_glob(
    *,
    subject_id: str | None = None,
    session_id: str | None = None,
    task: str | None = None,
    run: str | None = None,
    space: str | None = None,
    desc: str | None = None,
    suffix: str | None = None,
) -> str:
    tokens = [
        _subject_label(subject_id),
        _session_label(session_id),
        f"task-{task}" if task else "",
        f"run-{run}" if run else "",
        f"space-{space}" if space else "",
        f"desc-{desc}" if desc else "",
        suffix or "",
    ]
    cleaned = [token for token in tokens if token]
    if not cleaned:
        return "*"
    return "*" + "*".join(cleaned) + "*"


def _raw_subject_prefix(
    subject_id: str | None,
    session_id: str | None,
) -> str:
    subject = _subject_label(subject_id)
    session = _session_label(session_id)
    if subject and session:
        return f"{subject}/{session}"
    if subject:
        return subject
    if session:
        return f"sub-*/{session}"
    return "sub-*"


def _public_derivative_aliases(derivative_kind: str | None) -> tuple[str, ...]:
    normalized = _normalize_derivative_kind(derivative_kind)
    aliases = _PUBLIC_DERIVATIVE_DIR_ALIASES.get(normalized)
    if aliases:
        return aliases
    return (normalized,) if normalized else ()


def _derivative_download_patterns(
    derivative_kind: str,
    *,
    subject_id: str | None = None,
    session_id: str | None = None,
    task: str | None = None,
    run: str | None = None,
    space: str | None = None,
    desc: str | None = None,
    suffix: str | None = None,
    extensions: Iterable[str] | None = None,
) -> list[str]:
    aliases = _public_derivative_aliases(derivative_kind)
    if not aliases:
        return []
    filename_glob = _file_glob(
        subject_id=subject_id,
        session_id=session_id,
        task=task,
        run=run,
        space=space,
        desc=desc,
        suffix=suffix,
    )
    patterns: list[str] = []
    for alias in aliases:
        patterns.append(f"derivatives/{alias}/dataset_description.json")
        patterns.append(f"derivatives/{alias}/**/dataset_description.json")
        if extensions:
            for extension in extensions:
                suffix_text = extension if str(extension).startswith(".") else f".{extension}"
                patterns.append(f"derivatives/{alias}/**/{filename_glob}{suffix_text}")
        elif suffix or desc or task or run or subject_id or session_id or space:
            patterns.append(f"derivatives/{alias}/**/{filename_glob}")
    deduped: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        if pattern in seen:
            continue
        seen.add(pattern)
        deduped.append(pattern)
    return deduped


def _find_downloaded_derivative_root(
    dataset_root: Path, derivative_kind: str
) -> Path | None:
    derivatives_root = dataset_root / "derivatives"
    if not derivatives_root.exists():
        return None
    aliases = _public_derivative_aliases(derivative_kind)
    ranked: list[tuple[int, Path]] = []
    for candidate in sorted(derivatives_root.iterdir()):
        if not candidate.is_dir():
            continue
        name = candidate.name.lower()
        for alias in aliases:
            alias_lower = alias.lower()
            if name == alias_lower:
                ranked.append((0, candidate.resolve()))
                break
            if alias_lower in name:
                ranked.append((1, candidate.resolve()))
                break
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], str(item[1])))
    return ranked[0][1]


def _download_openneuro_subset_checked(
    *,
    resources: Any,
    dataset_ref: str,
    resolved_dataset_id: str,
    download_root: str | None,
    include_patterns: Iterable[str],
) -> tuple[Path, dict[str, Any]]:
    dataset_simple_id = _downloadable_dataset_guard(resources, dataset_ref)
    target_root = _openneuro_download_root(
        dataset_simple_id, download_root=download_root
    )
    patterns = [str(pattern).strip() for pattern in include_patterns if str(pattern).strip()]
    if not patterns:
        raise ValueError("No selective download patterns were generated.")
    download_openneuro_subset(
        dataset_simple_id,
        str(target_root),
        patterns,
        verify_hash=False,
        verify_size=True,
        max_retries=3,
        max_concurrent_downloads=3,
    )
    matched_files = _download_pattern_matches(target_root, patterns)
    if not matched_files:
        raise FileNotFoundError(
            "No public OpenNeuro files matched the requested selective download "
            f"patterns for dataset '{resolved_dataset_id or dataset_ref}': {patterns}"
        )
    return target_root, {
        "dataset_ref": dataset_ref,
        "resolved_dataset_id": resolved_dataset_id or dataset_ref,
        "dataset_simple_id": dataset_simple_id,
        "download_root": str(target_root),
        "download_patterns": patterns,
        "downloaded_files": [str(path) for path in matched_files],
    }


def _dataset_file_download_patterns(asset_name: str | None) -> list[str]:
    patterns = ["dataset_description.json", "participants.tsv"]
    mapped = _DATASET_FILE_ALIASES.get(_normalize_token(asset_name))
    if mapped and mapped not in patterns:
        patterns.append(mapped)
    return patterns


def _bids_download_patterns(args: ResolveDatasetAssetArgs) -> list[str]:
    prefix = _raw_subject_prefix(args.subject_id, args.session_id)
    filename_glob = _file_glob(
        subject_id=args.subject_id,
        session_id=args.session_id,
        task=args.task,
        run=args.run,
        space=args.space,
        desc=args.desc,
        suffix=args.suffix,
    )
    return [
        "dataset_description.json",
        "participants.tsv",
        f"{prefix}/**/{filename_glob}.nii.gz",
        f"{prefix}/**/{filename_glob}.nii",
        f"{prefix}/**/{filename_glob}.json",
        f"{prefix}/**/{filename_glob}.tsv",
    ]


def _events_download_patterns(args: ResolveDatasetAssetArgs) -> list[str]:
    prefix = _raw_subject_prefix(args.subject_id, args.session_id)
    filename_glob = _file_glob(
        subject_id=args.subject_id,
        session_id=args.session_id,
        task=args.task,
        run=args.run,
        suffix="events",
    )
    return [
        "dataset_description.json",
        "participants.tsv",
        f"{prefix}/**/{filename_glob}.tsv",
    ]


def _confounds_download_patterns(args: ResolveDatasetAssetArgs) -> list[str]:
    return _derivative_download_patterns(
        "fmriprep",
        subject_id=args.subject_id,
        session_id=args.session_id,
        task=args.task,
        run=args.run,
        space=args.space,
        desc="confounds",
        suffix="timeseries",
        extensions=[".tsv"],
    )


def _candidate_dirs(
    base_root: Path,
    *,
    subject_id: str | None,
    session_id: str | None,
    datatype: str | None,
) -> list[Path]:
    dirs: list[Path] = []
    datatype_label = str(datatype or "").strip()
    subject = _subject_label(subject_id)
    session = _session_label(session_id)

    if subject:
        subject_root = base_root / subject
        if session and datatype_label:
            dirs.append(subject_root / session / datatype_label)
        if session:
            dirs.append(subject_root / session)
        if datatype_label:
            dirs.append(subject_root / datatype_label)
        dirs.append(subject_root)
    elif datatype_label:
        dirs.extend(sorted(base_root.glob(f"sub-*/**/{datatype_label}")))

    dirs.append(base_root)

    unique_dirs: list[Path] = []
    seen: set[str] = set()
    for path in dirs:
        key = str(path)
        if key in seen or not path.exists():
            continue
        seen.add(key)
        unique_dirs.append(path)
    return unique_dirs


def _matches_extension(path: Path, extension: str | None) -> bool:
    if not extension:
        return True
    text = str(extension).strip().lower()
    if not text:
        return True
    if not text.startswith("."):
        text = f".{text}"
    return path.name.lower().endswith(text)


def _match_bids_like_file(
    path: Path,
    *,
    subject_id: str | None,
    session_id: str | None,
    task: str | None,
    run: str | None,
    space: str | None,
    desc: str | None,
    suffix: str | None,
    extension: str | None,
) -> bool:
    name = path.name
    subject = _subject_label(subject_id)
    session = _session_label(session_id)
    if subject and subject not in name:
        return False
    if session and session not in name:
        return False
    if task and f"task-{task}" not in name:
        return False
    if run and f"run-{run}" not in name:
        return False
    if space and f"space-{space}" not in name:
        return False
    if desc and f"desc-{desc}" not in name:
        return False
    if suffix:
        suffix_token = f"_{suffix}"
        if suffix_token not in name:
            return False
    return _matches_extension(path, extension)


def _search_files(
    base_root: Path,
    *,
    subject_id: str | None = None,
    session_id: str | None = None,
    datatype: str | None = None,
    task: str | None = None,
    run: str | None = None,
    space: str | None = None,
    desc: str | None = None,
    suffix: str | None = None,
    extension: str | None = None,
) -> list[Path]:
    matches: list[Path] = []
    for directory in _candidate_dirs(
        base_root,
        subject_id=subject_id,
        session_id=session_id,
        datatype=datatype,
    ):
        for path in sorted(directory.rglob("*")):
            if not path.is_file():
                continue
            if _match_bids_like_file(
                path,
                subject_id=subject_id,
                session_id=session_id,
                task=task,
                run=run,
                space=space,
                desc=desc,
                suffix=suffix,
                extension=extension,
            ):
                matches.append(path)
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in matches:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path.resolve())
    return deduped


def _first_existing(path: Path | None) -> Path | None:
    if path is None or not path.exists():
        return None
    return path.resolve()


def _root_file_target(bids_root: Path, asset_name: str | None) -> Path | None:
    mapped = _DATASET_FILE_ALIASES.get(_normalize_token(asset_name))
    if not mapped:
        return None
    candidate = bids_root / mapped
    return candidate.resolve() if candidate.exists() else None


def _infer_kind(args: ResolveDatasetAssetArgs) -> str:
    asset_token = _normalize_token(args.asset_name)
    derivative_kind = _normalize_derivative_kind(args.derivative_kind)
    if asset_token in _STAT_MAP_ALIASES:
        return "stat_map"
    if derivative_kind == "glmfitlins" and _has_glm_stat_map_selectors(args):
        return "stat_map"
    if _has_glm_stat_map_selectors(args):
        return "stat_map"
    if args.derivative_kind:
        return "derivative"
    if asset_token in _EVENT_ALIASES:
        return "events"
    if asset_token in _CONFOUND_ALIASES:
        return "confounds"
    if asset_token in _DATASET_FILE_ALIASES:
        return "dataset"
    if args.subject_id and args.datatype and args.suffix:
        return "bids"
    if asset_token in _DERIVATIVE_KIND_ALIASES:
        return "derivative"
    return "dataset"


def _glm_query_from_args(args: ResolveDatasetAssetArgs) -> GLMStatMapQuery:
    return GLMStatMapQuery(
        dataset_ref=args.dataset_ref,
        query_text=args.asset_name,
        task=args.task,
        node=args.node,
        subject_id=args.subject_id,
        session_id=args.session_id,
        run=args.run,
        contrast=args.contrast,
        statistic=args.statistic,
        space=args.space,
    )


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


def _resolved_asset_row(
    *,
    kind: str,
    dataset_ref: str,
    resolved_dataset_id: str,
    source_path: str | Path | None,
    roots: list[str | Path | None],
    source: str,
    metadata: dict[str, Any] | None = None,
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
) -> dict[str, Any]:
    provenance = build_provenance_record(
        kind=kind,
        preferred_id=preferred_id,
        source=source,
        source_path=source_path,
        roots=roots,
        dataset_id=resolved_dataset_id,
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
    return {
        "id": provenance["canonical_id"],
        "canonical_id": provenance["canonical_id"],
        "kind": kind,
        "dataset_ref": dataset_ref,
        "resolved_dataset_id": resolved_dataset_id,
        "source": provenance["source"],
        "source_path": provenance["source_path"],
        "relative_path": provenance["relative_path"],
        "checksum": provenance["checksum"],
        "level": provenance["level"],
        "estimator": provenance["estimator"],
        "manifest_fields": provenance["manifest_fields"],
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


def _resolve_dataset_context(
    args: ResolveDatasetAssetArgs,
) -> tuple[Any, Any, Path | None]:
    resources = query_service.dataset_resources(
        args.dataset_ref,
        dataset_version=args.dataset_version,
        analysis_goal=args.analysis_goal,
        **_FAST_DATASET_RESOURCE_KWARGS,
    )
    if resources is None:
        raise FileNotFoundError(
            f"Dataset '{args.dataset_ref}' was not found in dataset resources."
    )
    dataset_resolution = _dataset_identity(resources)
    bids_path = _first_existing(
        Path(resources.bids_path).expanduser()
        if getattr(resources, "bids_path", None)
        else None
    )
    return resources, dataset_resolution, bids_path


def _resolve_dataset_summary(
    args: ResolveDatasetAssetArgs,
    *,
    output_dir: str | None,
) -> ToolResult:
    resources, dataset_resolution, bids_path = _resolve_dataset_context(args)
    download_info: dict[str, Any] | None = None
    if bids_path is None:
        if not args.download_missing:
            return ToolResult(
                status="error",
                error=f"Dataset '{args.dataset_ref}' does not have a local BIDS root.",
                data={
                    "summary": _common_summary(
                        resources, args.dataset_ref, dataset_resolution
                    )
                },
            )
        bids_path, download_info = _download_openneuro_subset_checked(
            resources=resources,
            dataset_ref=args.dataset_ref,
            resolved_dataset_id=getattr(resources, "resolved_dataset_id", None)
            or args.dataset_ref,
            download_root=args.download_root,
            include_patterns=_dataset_file_download_patterns(args.asset_name),
        )

    dataset_description = _first_existing(bids_path / "dataset_description.json")
    participants_tsv = _first_existing(bids_path / "participants.tsv")
    root_file = _root_file_target(bids_path, args.asset_name)

    outputs = {
        "bids_root": str(bids_path),
        "derivative_roots": dict(getattr(resources, "derivatives", {}) or {}),
        **_copy_file_map(
            {
                "dataset_description": root_file
                if root_file and root_file.name == "dataset_description.json"
                else dataset_description,
                "participants_tsv": root_file
                if root_file and root_file.name == "participants.tsv"
                else participants_tsv,
            },
            output_dir,
        ),
    }
    summary = _common_summary(resources, args.dataset_ref, dataset_resolution)
    summary["resolved_kind"] = "dataset_file" if root_file else "dataset"
    summary["asset_name"] = args.asset_name or ""
    if download_info:
        summary["download_missing_used"] = True
        summary["download_root"] = download_info["download_root"]
    primary_path = root_file or dataset_description or participants_tsv or bids_path
    primary_name = ""
    if isinstance(primary_path, Path) and primary_path != bids_path:
        primary_name = primary_path.name
        preferred_id = f"dataset:{summary['resolved_dataset_id']}:{primary_name}"
    else:
        preferred_id = f"dataset:{summary['resolved_dataset_id']}:bids-root"
    return ToolResult(
        status="success",
        data={
            "outputs": outputs,
            "resolved_asset": _resolved_asset_row(
                kind="dataset",
                dataset_ref=args.dataset_ref,
                resolved_dataset_id=summary["resolved_dataset_id"],
                source_path=primary_path,
                roots=[bids_path],
                source="dataset_root",
                metadata=getattr(dataset_resolution, "metadata", {}) or {},
                suffix=primary_name,
                preferred_id=preferred_id,
            ),
            "summary": summary,
            "download": download_info,
        },
    )


def _resolve_bids_file(
    args: ResolveDatasetAssetArgs,
    *,
    output_dir: str | None,
) -> ToolResult:
    resources, dataset_resolution, bids_path = _resolve_dataset_context(args)
    download_info: dict[str, Any] | None = None
    if bids_path is None:
        if not args.download_missing:
            return ToolResult(
                status="error",
                error=f"Dataset '{args.dataset_ref}' does not have a local BIDS root.",
                data={
                    "summary": _common_summary(
                        resources, args.dataset_ref, dataset_resolution
                    )
                },
            )
        bids_path, download_info = _download_openneuro_subset_checked(
            resources=resources,
            dataset_ref=args.dataset_ref,
            resolved_dataset_id=getattr(resources, "resolved_dataset_id", None)
            or args.dataset_ref,
            download_root=args.download_root,
            include_patterns=_bids_download_patterns(args),
        )
    if not args.subject_id or not args.datatype or not args.suffix:
        return ToolResult(
            status="error",
            error="BIDS resolution requires subject_id, datatype, and suffix.",
            data={
                "summary": _common_summary(
                    resources, args.dataset_ref, dataset_resolution
                )
            },
        )

    matches: list[Path] = []
    bids_result = ResolveBIDSTool()._run(
        bids_root=str(bids_path),
        subject_id=args.subject_id,
        session_id=args.session_id,
        datatype=args.datatype,
        suffix=args.suffix,
        space=args.space,
        desc=args.desc,
    )
    if bids_result.status == "success":
        for path in bids_result.data["outputs"].get("resolved_paths", []):
            candidate = Path(path)
            if candidate.exists():
                matches.append(candidate.resolve())

    if not matches:
        matches = _search_files(
            bids_path,
            subject_id=args.subject_id,
            session_id=args.session_id,
            datatype=args.datatype,
            task=args.task,
            run=args.run,
            space=args.space,
            desc=args.desc,
            suffix=args.suffix,
        )

    if not matches:
        return ToolResult(
            status="error",
            error="No matching BIDS files found.",
            data={
                "summary": _common_summary(
                    resources, args.dataset_ref, dataset_resolution
                )
            },
        )

    materialized = [_materialize_file(path, output_dir) for path in matches]
    summary = _common_summary(resources, args.dataset_ref, dataset_resolution)
    summary.update(
        {
            "resolved_kind": "bids",
            "subject_id": args.subject_id,
            "session_id": args.session_id or "",
            "datatype": args.datatype,
            "suffix": args.suffix,
            "n_matches": len(materialized),
        }
    )
    if download_info:
        summary["download_missing_used"] = True
        summary["download_root"] = download_info["download_root"]
    return ToolResult(
        status="success",
        data={
            "outputs": {
                "resolved_file": str(materialized[0]),
                "resolved_files": [str(path) for path in materialized],
                "bids_root": str(bids_path),
                "matches": [
                    _resolved_asset_row(
                        kind="bids",
                        dataset_ref=args.dataset_ref,
                        resolved_dataset_id=summary["resolved_dataset_id"],
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
                    )
                    for path in materialized
                ],
            },
            "resolved_asset": _resolved_asset_row(
                kind="bids",
                dataset_ref=args.dataset_ref,
                resolved_dataset_id=summary["resolved_dataset_id"],
                source_path=materialized[0],
                roots=[bids_path],
                source="bids_local_scan",
                subject_id=args.subject_id,
                session_id=args.session_id,
                task=args.task,
                run=args.run,
                datatype=args.datatype,
                suffix=args.suffix,
                space=args.space,
            ),
            "summary": summary,
            "download": download_info,
        },
    )


def _resolve_derivative_root(
    args: ResolveDatasetAssetArgs,
    *,
    output_dir: str | None,
) -> ToolResult:
    del output_dir
    resources, dataset_resolution, _bids_path = _resolve_dataset_context(args)
    requested_kind = _normalize_derivative_kind(args.derivative_kind or args.asset_name)
    derivatives = dict(getattr(resources, "derivatives", {}) or {})
    if not requested_kind:
        return ToolResult(
            status="error",
            error=(
                "Derivative resolution requires derivative_kind or asset_name "
                "(for example fmriprep, mriqc, glmfitlins)."
            ),
            data={
                "summary": _common_summary(
                    resources, args.dataset_ref, dataset_resolution
                )
            },
        )
    derivative_root_value = derivatives.get(requested_kind)
    derivative_root_path = _first_existing(
        Path(derivative_root_value).expanduser() if derivative_root_value else None
    )
    download_info: dict[str, Any] | None = None
    derivative_root = str(derivative_root_path) if derivative_root_path else ""
    if not derivative_root and args.download_missing:
        derivative_download_patterns = _derivative_download_patterns(
            requested_kind,
            subject_id=args.subject_id,
            session_id=args.session_id,
            task=args.task,
            run=args.run,
            space=args.space,
            desc=args.desc,
            suffix=args.suffix,
            extensions=[".nii.gz", ".nii", ".json", ".tsv", ".txt"],
        )
        downloaded_root, download_info = _download_openneuro_subset_checked(
            resources=resources,
            dataset_ref=args.dataset_ref,
            resolved_dataset_id=getattr(resources, "resolved_dataset_id", None)
            or args.dataset_ref,
            download_root=args.download_root,
            include_patterns=derivative_download_patterns,
        )
        resolved_downloaded_root = _find_downloaded_derivative_root(
            downloaded_root, requested_kind
        )
        if resolved_downloaded_root is not None:
            derivative_root = str(resolved_downloaded_root)
    if not derivative_root:
        return ToolResult(
            status="error",
            error=(
                f"Derivative '{requested_kind}' is not available for "
                f"dataset '{args.dataset_ref}'."
            ),
            data={
                "summary": _common_summary(
                    resources, args.dataset_ref, dataset_resolution
                )
            },
        )

    summary = _common_summary(resources, args.dataset_ref, dataset_resolution)
    summary.update(
        {
            "resolved_kind": "derivative",
            "derivative_kind": requested_kind,
        }
    )
    if download_info:
        summary["download_missing_used"] = True
        summary["download_root"] = download_info["download_root"]
    return ToolResult(
        status="success",
        data={
            "outputs": {
                "derivative_root": derivative_root,
            },
            "resolved_asset": _resolved_asset_row(
                kind="derivative",
                dataset_ref=args.dataset_ref,
                resolved_dataset_id=summary["resolved_dataset_id"],
                source_path=derivative_root,
                roots=[derivative_root],
                source="dataset_resources",
                derivative_kind=requested_kind,
                preferred_id=f"derivative:{summary['resolved_dataset_id']}:{requested_kind}",
            ),
            "summary": summary,
            "download": download_info,
        },
    )


def _resolve_events_file(
    args: ResolveDatasetAssetArgs,
    *,
    output_dir: str | None,
) -> ToolResult:
    resources, dataset_resolution, bids_path = _resolve_dataset_context(args)
    download_info: dict[str, Any] | None = None
    if bids_path is None:
        if not args.download_missing:
            return ToolResult(
                status="error",
                error=f"Dataset '{args.dataset_ref}' does not have a local BIDS root.",
                data={
                    "summary": _common_summary(
                        resources, args.dataset_ref, dataset_resolution
                    )
                },
            )
        bids_path, download_info = _download_openneuro_subset_checked(
            resources=resources,
            dataset_ref=args.dataset_ref,
            resolved_dataset_id=getattr(resources, "resolved_dataset_id", None)
            or args.dataset_ref,
            download_root=args.download_root,
            include_patterns=_events_download_patterns(args),
        )
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
    if not matches:
        return ToolResult(
            status="error",
            error="No matching events.tsv files found.",
            data={
                "summary": _common_summary(
                    resources, args.dataset_ref, dataset_resolution
                )
            },
        )

    materialized = [_materialize_file(path, output_dir) for path in matches]
    summary = _common_summary(resources, args.dataset_ref, dataset_resolution)
    summary.update(
        {
            "resolved_kind": "events",
            "subject_id": args.subject_id or "",
            "task": args.task or "",
            "run": args.run or "",
            "n_matches": len(materialized),
        }
    )
    if download_info:
        summary["download_missing_used"] = True
        summary["download_root"] = download_info["download_root"]
    return ToolResult(
        status="success",
        data={
            "outputs": {
                "events_file": str(materialized[0]),
                "resolved_file": str(materialized[0]),
                "resolved_files": [str(path) for path in materialized],
                "matches": [
                    _resolved_asset_row(
                        kind="events",
                        dataset_ref=args.dataset_ref,
                        resolved_dataset_id=summary["resolved_dataset_id"],
                        source_path=path,
                        roots=[bids_path],
                        source="bids_local_scan",
                        subject_id=args.subject_id,
                        session_id=args.session_id,
                        task=args.task,
                        run=args.run,
                        datatype=args.datatype or "func",
                        suffix="events",
                    )
                    for path in materialized
                ],
            },
            "resolved_asset": _resolved_asset_row(
                kind="events",
                dataset_ref=args.dataset_ref,
                resolved_dataset_id=summary["resolved_dataset_id"],
                source_path=materialized[0],
                roots=[bids_path],
                source="bids_local_scan",
                subject_id=args.subject_id,
                session_id=args.session_id,
                task=args.task,
                run=args.run,
                datatype=args.datatype or "func",
                suffix="events",
            ),
            "summary": summary,
            "download": download_info,
        },
    )


def _resolve_confounds_file(
    args: ResolveDatasetAssetArgs,
    *,
    output_dir: str | None,
) -> ToolResult:
    resources, dataset_resolution, _bids_path = _resolve_dataset_context(args)
    derivatives = dict(getattr(resources, "derivatives", {}) or {})
    fmriprep_root_value = derivatives.get("fmriprep")
    fmriprep_root_path = _first_existing(
        Path(fmriprep_root_value).expanduser() if fmriprep_root_value else None
    )
    download_info: dict[str, Any] | None = None
    fmriprep_root = str(fmriprep_root_path) if fmriprep_root_path else ""
    if not fmriprep_root and args.download_missing:
        downloaded_root, download_info = _download_openneuro_subset_checked(
            resources=resources,
            dataset_ref=args.dataset_ref,
            resolved_dataset_id=getattr(resources, "resolved_dataset_id", None)
            or args.dataset_ref,
            download_root=args.download_root,
            include_patterns=_confounds_download_patterns(args),
        )
        resolved_downloaded_root = _find_downloaded_derivative_root(
            downloaded_root, "fmriprep"
        )
        if resolved_downloaded_root is not None:
            fmriprep_root = str(resolved_downloaded_root)
    if not fmriprep_root:
        return ToolResult(
            status="error",
            error=(
                f"Dataset '{args.dataset_ref}' does not have an fmriprep derivative "
                "root for confounds lookup."
            ),
            data={
                "summary": _common_summary(
                    resources, args.dataset_ref, dataset_resolution
                )
            },
        )

    matches = _search_files(
        Path(fmriprep_root),
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
    if not matches:
        return ToolResult(
            status="error",
            error="No matching fMRIPrep confounds files found.",
            data={
                "summary": _common_summary(
                    resources, args.dataset_ref, dataset_resolution
                )
            },
        )

    materialized = [_materialize_file(path, output_dir) for path in matches]
    summary = _common_summary(resources, args.dataset_ref, dataset_resolution)
    summary.update(
        {
            "resolved_kind": "confounds",
            "derivative_kind": "fmriprep",
            "subject_id": args.subject_id or "",
            "task": args.task or "",
            "run": args.run or "",
            "n_matches": len(materialized),
        }
    )
    if download_info:
        summary["download_missing_used"] = True
        summary["download_root"] = download_info["download_root"]
    return ToolResult(
        status="success",
        data={
            "outputs": {
                "confounds_file": str(materialized[0]),
                "resolved_file": str(materialized[0]),
                "resolved_files": [str(path) for path in materialized],
                "derivative_root": fmriprep_root,
                "matches": [
                    _resolved_asset_row(
                        kind="confounds",
                        dataset_ref=args.dataset_ref,
                        resolved_dataset_id=summary["resolved_dataset_id"],
                        source_path=path,
                        roots=[fmriprep_root],
                        source="fmriprep_local_scan",
                        derivative_kind="fmriprep",
                        subject_id=args.subject_id,
                        session_id=args.session_id,
                        task=args.task,
                        run=args.run,
                        datatype=args.datatype or "func",
                        suffix="timeseries",
                        space=args.space,
                    )
                    for path in materialized
                ],
            },
            "resolved_asset": _resolved_asset_row(
                kind="confounds",
                dataset_ref=args.dataset_ref,
                resolved_dataset_id=summary["resolved_dataset_id"],
                source_path=materialized[0],
                roots=[fmriprep_root],
                source="fmriprep_local_scan",
                derivative_kind="fmriprep",
                subject_id=args.subject_id,
                session_id=args.session_id,
                task=args.task,
                run=args.run,
                datatype=args.datatype or "func",
                suffix="timeseries",
                space=args.space,
            ),
            "summary": summary,
            "download": download_info,
        },
    )


def _resolve_glm_stat_map(
    args: ResolveDatasetAssetArgs,
    *,
    output_dir: str | None,
) -> ToolResult:
    resources, dataset_resolution, _bids_path = _resolve_dataset_context(args)
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
        query=_glm_query_from_args(args),
        derivative_roots=derivative_roots,
        include_registry=True,
    )
    if not matches:
        return ToolResult(
            status="error",
            error="No matching GLM stat maps were found.",
            data={
                "summary": {
                    **_common_summary(resources, args.dataset_ref, dataset_resolution),
                    "resolved_kind": "stat_map",
                    "filters": {
                        "task": args.task or "",
                        "node": args.node or "",
                        "subject_id": args.subject_id or "",
                        "session_id": args.session_id or "",
                        "run": args.run or "",
                        "contrast": args.contrast or "",
                        "statistic": args.statistic or "",
                        "space": args.space or "",
                    },
                }
            },
        )

    materialized_matches: list[dict[str, Any]] = []
    materialized_paths: list[str] = []
    for match in matches:
        original = Path(str(match["path"]))
        materialized = _materialize_file(original, output_dir)
        materialized_paths.append(str(materialized))
        materialized_match = dict(match)
        materialized_match["source_path"] = materialized_match.get(
            "source_path"
        ) or str(original)
        materialized_match["path"] = str(materialized)
        materialized_matches.append(materialized_match)

    primary = materialized_matches[0]
    summary = _common_summary(resources, args.dataset_ref, dataset_resolution)
    summary.update(
        {
            "resolved_kind": "stat_map",
            "derivative_kind": primary.get("derivative_kind") or "",
            "task": args.task or primary.get("task") or "",
            "node": args.node or primary.get("node") or "",
            "subject_id": args.subject_id or primary.get("subject_id") or "",
            "session_id": args.session_id or primary.get("session_id") or "",
            "run": args.run or primary.get("run") or "",
            "contrast": args.contrast or primary.get("contrast") or "",
            "statistic": args.statistic or primary.get("statistic") or "",
            "space": args.space or primary.get("space") or "",
            "n_matches": len(materialized_matches),
            "returned_all_matches": True,
            "filters": {
                "task": args.task or "",
                "node": args.node or "",
                "subject_id": args.subject_id or "",
                "session_id": args.session_id or "",
                "run": args.run or "",
                "contrast": args.contrast or "",
                "statistic": args.statistic or "",
                "space": args.space or "",
            },
        }
    )
    return ToolResult(
        status="success",
        data={
            "outputs": {
                "glm_stat_map": primary["path"],
                "resolved_file": primary["path"],
                "resolved_files": materialized_paths,
                "derivative_root": derivative_roots.get(
                    primary.get("derivative_kind") or "",
                    primary.get("root") or "",
                ),
                "matches": [
                    {
                        **match,
                        **build_provenance_record(
                            kind="stat_map",
                            preferred_id=match.get("asset_id") or None,
                            source=match.get("source") or "",
                            source_path=match.get("path") or "",
                            roots=[
                                derivative_roots.get(
                                    match.get("derivative_kind") or "", ""
                                ),
                                match.get("root") or "",
                            ],
                            dataset_id=match.get("dataset_id")
                            or summary["resolved_dataset_id"],
                            derivative_kind=match.get("derivative_kind") or "",
                            subject_id=match.get("subject_id") or "",
                            session_id=match.get("session_id") or "",
                            task=match.get("task") or "",
                            run=match.get("run") or "",
                            space=match.get("space") or "",
                            contrast=match.get("contrast") or "",
                            statistic=match.get("statistic") or "",
                            level=match.get("level") or "",
                            metadata={
                                "canonical_runtime_name": match.get(
                                    "canonical_runtime_name"
                                )
                                or "",
                                "space_inferred": bool(match.get("space_inferred")),
                                "format": match.get("format") or "",
                            },
                        ),
                    }
                    for match in materialized_matches
                ],
            },
            "resolved_asset": _resolved_asset_row(
                kind="stat_map",
                dataset_ref=args.dataset_ref,
                resolved_dataset_id=summary["resolved_dataset_id"],
                source_path=primary["path"],
                roots=[
                    derivative_roots.get(primary.get("derivative_kind") or "", ""),
                    primary.get("root") or "",
                ],
                source=primary.get("source") or "",
                metadata={
                    "canonical_runtime_name": primary.get("canonical_runtime_name")
                    or "",
                    "space_inferred": bool(primary.get("space_inferred")),
                    "format": primary.get("format") or "",
                },
                derivative_kind=primary.get("derivative_kind") or "",
                subject_id=primary.get("subject_id") or "",
                session_id=primary.get("session_id") or "",
                task=primary.get("task") or "",
                run=primary.get("run") or "",
                space=primary.get("space") or "",
                contrast=primary.get("contrast") or "",
                statistic=primary.get("statistic") or "",
                level=primary.get("level") or "",
                preferred_id=primary.get("asset_id") or None,
            ),
            "summary": summary,
        },
    )


class ResolveDatasetAssetTool(NeuroToolWrapper):
    """Resolve dataset metadata, BIDS files, and derivative-side assets."""

    execution_backend = "python"
    TIMEOUT_S = 300

    def get_tool_name(self) -> str:
        return "resolve_dataset_asset"

    def get_tool_description(self) -> str:
        return (
            "Resolve dataset-side assets through one entrypoint: dataset metadata, "
            "dataset-level files, raw BIDS files, derivative roots, events, "
            "confounds, and GLM stat maps."
        )

    def get_args_schema(self):
        return ResolveDatasetAssetArgs

    def _run(self, **kwargs) -> ToolResult:
        output_dir = kwargs.get("output_dir")
        try:
            args = ResolveDatasetAssetArgs(**kwargs)
            requested_kind = _normalize_kind(args.kind)
        except Exception as exc:
            return ToolResult(status="error", error=str(exc), data={})

        resolved_kind = (
            _infer_kind(args) if requested_kind == "auto" else requested_kind
        )
        if requested_kind == "derivative" and (
            _has_glm_stat_map_selectors(args)
            or _normalize_token(args.asset_name) in _STAT_MAP_ALIASES
        ):
            resolved_kind = "stat_map"
        asset_token = _normalize_token(args.asset_name)

        try:
            if resolved_kind == "dataset":
                if asset_token in _EVENT_ALIASES:
                    result = _resolve_events_file(args, output_dir=output_dir)
                elif asset_token in _CONFOUND_ALIASES:
                    result = _resolve_confounds_file(args, output_dir=output_dir)
                else:
                    result = _resolve_dataset_summary(args, output_dir=output_dir)
            elif resolved_kind == "bids":
                result = _resolve_bids_file(args, output_dir=output_dir)
            elif resolved_kind == "derivative":
                result = _resolve_derivative_root(args, output_dir=output_dir)
            elif resolved_kind == "events":
                result = _resolve_events_file(args, output_dir=output_dir)
            elif resolved_kind == "confounds":
                result = _resolve_confounds_file(args, output_dir=output_dir)
            elif resolved_kind == "stat_map":
                result = _resolve_glm_stat_map(args, output_dir=output_dir)
            else:
                raise ValueError(f"Unsupported resolved kind '{resolved_kind}'")
        except Exception as exc:
            return ToolResult(
                status="error",
                error=str(exc),
                data={"dataset_ref": args.dataset_ref, "requested_kind": args.kind},
            )

        if result.status != "success":
            return result

        data = dict(result.data or {})
        summary = dict(data.get("summary") or {})
        summary.update(
            {
                "requested_kind": args.kind,
                "dispatch_mode": "auto" if requested_kind == "auto" else "explicit",
            }
        )
        data["summary"] = summary
        return ToolResult(status="success", data=data, metadata=result.metadata)


class ResolveDatasetAssetTools:
    @staticmethod
    def get_all_tools():
        return [ResolveDatasetAssetTool()]


__all__ = ["ResolveDatasetAssetTool", "ResolveDatasetAssetTools"]
