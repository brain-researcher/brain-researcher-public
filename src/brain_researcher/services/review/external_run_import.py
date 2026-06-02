"""Helpers for reviewing and importing external artifact folders as BR runs."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from brain_researcher.config.run_artifacts import build_mcp_run_dir
from brain_researcher.core.analysis_bundle import review_context_file_refs
from brain_researcher.core.artifact_checksums import compute_file_sha256
from brain_researcher.core.artifact_manifest import save_artifact_manifest
from brain_researcher.core.contracts.analysis_bundle import (
    AnalysisBundleFiles,
    AnalysisBundleV1,
    BundleFileEntry,
)
from brain_researcher.core.contracts.observation import (
    ObservationFiles,
    ObservationSpecV1,
)
from brain_researcher.services.review.external_artifact_adapters import (
    ExternalArtifactAdapterPayload,
    available_external_artifact_adapters,
    detect_external_artifact_adapter,
)

LinkMode = Literal["symlink", "copy"]

_ROOT_REUSED_FILENAMES = (
    "observation.json",
    "analysis_bundle.json",
    "trajectory.json",
    "execution_manifest.json",
    "trace.jsonl",
    "stdout.txt",
    "stderr.txt",
    "artifact_manifest.json",
)
_ADAPTER_GENERATED_FILENAMES = frozenset(
    {
        "observation.json",
        "analysis_bundle.json",
        "artifact_manifest.json",
        "source_summary.json",
        "extraction_report.json",
    }
)


@dataclass(slots=True)
class ExternalRunImportSpec:
    run_id: str
    tool_id: str = "external_import"
    status: str = "succeeded"
    task: str | None = None
    contrast_name: str | None = None
    dataset_id: str | None = None
    study_id: str | None = None
    modality: str | None = None
    design_type: str | None = None
    statistical_method: str | None = None
    notes: str | None = None


@dataclass(slots=True)
class ExternalRunImportResult:
    run_id: str
    source_dir: str
    run_dir: str
    dry_run: bool
    link_mode: LinkMode
    created_files: list[str]
    reused_root_files: list[str]
    artifact_mount: str
    adapter_name: str | None = None
    review_tier: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc_iso() -> str:
    from datetime import datetime, timezone

    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _relative_symlink_target(source: Path, destination: Path) -> Path:
    return Path(
        os.path.relpath(str(source.resolve()), start=str(destination.parent.resolve()))
    )


def _link_or_copy(source: Path, destination: Path, *, link_mode: LinkMode) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
        else:
            destination.unlink()

    if link_mode == "symlink":
        if source.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            for child in sorted(source.iterdir()):
                _link_or_copy(child, destination / child.name, link_mode=link_mode)
            return
        destination.symlink_to(_relative_symlink_target(source, destination))
        return

    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)


def _merge_step_params(
    params: dict[str, Any],
    spec: ExternalRunImportSpec,
) -> dict[str, Any]:
    merged = dict(params)
    for key, value in (
        ("task", spec.task),
        ("contrast_name", spec.contrast_name),
        ("dataset_id", spec.dataset_id),
        ("study_id", spec.study_id),
        ("modality", spec.modality),
        ("design_type", spec.design_type),
        ("statistical_method", spec.statistical_method),
    ):
        if value and not merged.get(key):
            merged[key] = value
    return merged


def _resolved_review_context(
    run_record: dict[str, Any],
    adapter: ExternalArtifactAdapterPayload,
) -> dict[str, Any] | None:
    candidates = (
        run_record.get("review_context"),
        (
            run_record.get("review_contract")
            if isinstance(run_record.get("review_contract"), dict)
            else {}
        ).get("review_context"),
        (adapter.run_card if isinstance(adapter.run_card, dict) else {}).get(
            "review_context"
        ),
        (
            adapter.provenance_request_updates
            if isinstance(adapter.provenance_request_updates, dict)
            else {}
        ).get("review_context"),
        (
            adapter.source_summary.get("review_context")
            if isinstance(adapter.source_summary, dict)
            else None
        ),
    )
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return None


def _external_review_context_file_refs(
    run_dir: Path,
    review_context: dict[str, Any] | None,
) -> dict[str, str | None]:
    file_refs = review_context_file_refs(run_dir, review_context)
    statistical_inference = (
        review_context.get("statistical_inference")
        if isinstance(review_context, dict)
        and isinstance(review_context.get("statistical_inference"), dict)
        else {}
    )
    design_model = (
        review_context.get("design_model")
        if isinstance(review_context, dict)
        and isinstance(review_context.get("design_model"), dict)
        else {}
    )
    source_mount = run_dir / "artifacts" / "source"
    field_keys = (
        (
            "correction_summary_json",
            statistical_inference.get("correction_summary_path"),
        ),
        (
            "threshold_summary_json",
            statistical_inference.get("threshold_summary_path")
            or statistical_inference.get("correction_summary_path"),
        ),
        ("thresholded_map", statistical_inference.get("thresholded_map_path")),
        ("design_matrix", design_model.get("design_matrix_path")),
        ("contrast_table", statistical_inference.get("contrast_table_path")),
        ("cluster_table", statistical_inference.get("cluster_table_path")),
        ("peak_table", statistical_inference.get("peak_table_path")),
    )
    for field_name, raw_ref in field_keys:
        if file_refs.get(field_name):
            continue
        ref = raw_ref
        if not isinstance(ref, str) or not ref.strip():
            continue
        candidate = Path(ref.strip()).expanduser()
        if not candidate.is_absolute():
            candidate = source_mount / candidate
        if not candidate.exists():
            continue
        try:
            file_refs[field_name] = candidate.relative_to(run_dir).as_posix()
            continue
        except Exception:
            pass
        try:
            file_refs[field_name] = (
                candidate.resolve().relative_to(run_dir.resolve()).as_posix()
            )
        except Exception:
            file_refs[field_name] = candidate.as_posix()
    return file_refs


def _effective_spec(
    spec: ExternalRunImportSpec,
    adapter: ExternalArtifactAdapterPayload | None,
) -> ExternalRunImportSpec:
    if adapter is None:
        return spec

    merged = asdict(spec)
    overrides = dict(adapter.spec_overrides)
    for key, value in overrides.items():
        current = merged.get(key)
        if key == "tool_id":
            if current in (None, "", "external_import") and value:
                merged[key] = value
            continue
        if current in (None, "") and value not in (None, ""):
            merged[key] = value
    return ExternalRunImportSpec(**merged)


def _synthesized_step(spec: ExternalRunImportSpec) -> dict[str, Any]:
    params = _merge_step_params({}, spec)
    return {
        "step_id": "s1",
        "tool_id": spec.tool_id,
        "params": params,
        "status": spec.status,
        "started_at": None,
        "finished_at": None,
        "result_path": "artifacts/source",
        "stdout_path": "stdout.txt",
        "stderr_path": "stderr.txt",
        "error": None,
        "policy_issues": [],
    }


def build_imported_run_record(
    source_dir: Path,
    spec: ExternalRunImportSpec,
    *,
    adapter: ExternalArtifactAdapterPayload | None = None,
) -> dict[str, Any]:
    existing = _load_json(source_dir / "run.json") if source_dir.is_dir() else None
    existing = existing or {}
    record = dict(existing)
    steps = record.get("steps")
    if not isinstance(steps, list) or not steps:
        steps = [_synthesized_step(spec)]
    else:
        normalized_steps: list[dict[str, Any]] = []
        for idx, raw_step in enumerate(steps, start=1):
            step = dict(raw_step) if isinstance(raw_step, dict) else {}
            step["step_id"] = str(step.get("step_id") or f"s{idx}")
            step["tool_id"] = str(
                step.get("tool_id") or step.get("tool") or spec.tool_id
            )
            step["status"] = str(step.get("status") or spec.status)
            params = step.get("params") if isinstance(step.get("params"), dict) else {}
            step["params"] = _merge_step_params(params, spec)
            step.setdefault("result_path", "artifacts/source")
            step.setdefault("stdout_path", "stdout.txt")
            step.setdefault("stderr_path", "stderr.txt")
            step.setdefault("started_at", None)
            step.setdefault("finished_at", None)
            step.setdefault("error", None)
            step.setdefault("policy_issues", [])
            normalized_steps.append(step)
        steps = normalized_steps

    now = _utc_iso()
    record["run_id"] = spec.run_id
    record["created_at"] = record.get("created_at") or now
    record["started_at"] = record.get("started_at") or now
    record["finished_at"] = record.get("finished_at") or now
    record["status"] = str(record.get("status") or spec.status)
    record["dry_run"] = bool(record.get("dry_run", False))
    record["error"] = record.get("error")
    record["steps"] = steps
    if adapter is not None:
        for key, value in adapter.run_record_updates.items():
            record[key] = value
    return record


def build_imported_provenance(
    source_dir: Path,
    spec: ExternalRunImportSpec,
    *,
    adapter: ExternalArtifactAdapterPayload | None = None,
) -> dict[str, Any]:
    existing = (
        _load_json(source_dir / "provenance.json") if source_dir.is_dir() else None
    )
    existing = existing or {}
    provenance = dict(existing)
    provenance["run_id"] = spec.run_id
    provenance["mode"] = str(provenance.get("mode") or "external_import")
    provenance["route"] = str(provenance.get("route") or "external_run_import")
    provenance["transport"] = str(provenance.get("transport") or "local_filesystem")
    request = (
        provenance.get("request") if isinstance(provenance.get("request"), dict) else {}
    )
    request = dict(request)
    request.setdefault("source_dir", str(source_dir))
    request.setdefault("tool_id", spec.tool_id)
    for key, value in (
        ("task", spec.task),
        ("contrast_name", spec.contrast_name),
        ("dataset_id", spec.dataset_id),
        ("study_id", spec.study_id),
        ("modality", spec.modality),
        ("design_type", spec.design_type),
        ("statistical_method", spec.statistical_method),
        ("notes", spec.notes),
    ):
        if value and key not in request:
            request[key] = value
    if adapter is not None:
        for key, value in adapter.provenance_request_updates.items():
            if value not in (None, "", [], {}):
                request[key] = value
        provenance.setdefault("adapter_name", adapter.adapter_name)
        provenance.setdefault("source_kind", adapter.source_kind)
    provenance["request"] = request
    return provenance


def _write_observation_bundle(
    run_dir: Path,
    *,
    run_id: str,
    run_record: dict[str, Any],
    provenance: dict[str, Any],
    adapter: ExternalArtifactAdapterPayload,
) -> list[str]:
    created: list[str] = []
    review_context = _resolved_review_context(run_record, adapter)
    file_refs = _external_review_context_file_refs(run_dir, review_context)

    _write_json(run_dir / "source_summary.json", adapter.source_summary)
    _write_json(run_dir / "extraction_report.json", adapter.extraction_report)
    created.extend(["source_summary.json", "extraction_report.json"])

    files = ObservationFiles(
        observation_json="observation.json",
        provenance_json="provenance.json",
        trace_jsonl="trace.jsonl",
        correction_summary_json=file_refs.get("correction_summary_json"),
        threshold_summary_json=file_refs.get("threshold_summary_json"),
        thresholded_map=file_refs.get("thresholded_map"),
        design_matrix=file_refs.get("design_matrix"),
        contrast_table=file_refs.get("contrast_table"),
        cluster_table=file_refs.get("cluster_table"),
        peak_table=file_refs.get("peak_table"),
    )
    observation = ObservationSpecV1(
        job_id=run_id,
        run_id=run_id,
        state=str(run_record.get("status") or "succeeded"),
        run_dir=str(run_dir),
        files=files,
        run_card=adapter.run_card,
        provenance=provenance,
        artifacts=list(adapter.artifacts),
        steps=list(run_record.get("steps") or []),
        diagnostics_summary=adapter.diagnostics_summary,
    )
    _write_json(run_dir / "observation.json", observation.model_dump(exclude_none=True))
    created.append("observation.json")

    save_artifact_manifest(
        type(
            "ExternalImportJob",
            (),
            {
                "run_dir": str(run_dir),
                "job_id": run_id,
                "run_id": run_id,
            },
        )(),
        run_dir,
    )
    if (run_dir / "artifact_manifest.json").exists():
        created.append("artifact_manifest.json")

    analysis_files = AnalysisBundleFiles(
        observation_json="observation.json",
        provenance_json="provenance.json",
        artifact_manifest_json=(
            "artifact_manifest.json"
            if (run_dir / "artifact_manifest.json").exists()
            else None
        ),
        trace_jsonl="trace.jsonl" if (run_dir / "trace.jsonl").exists() else None,
        correction_summary_json=file_refs.get("correction_summary_json"),
        threshold_summary_json=file_refs.get("threshold_summary_json"),
        thresholded_map=file_refs.get("thresholded_map"),
        design_matrix=file_refs.get("design_matrix"),
        contrast_table=file_refs.get("contrast_table"),
        cluster_table=file_refs.get("cluster_table"),
        peak_table=file_refs.get("peak_table"),
    )
    manifest: list[BundleFileEntry] = []
    for role, rel in (
        ("observation", "observation.json"),
        ("provenance", "provenance.json"),
        ("artifact_manifest", "artifact_manifest.json"),
        ("source_summary", "source_summary.json"),
        ("extraction_report", "extraction_report.json"),
        ("trace", "trace.jsonl"),
        ("correction_summary", analysis_files.correction_summary_json),
        ("threshold_summary", analysis_files.threshold_summary_json),
        ("thresholded_map", analysis_files.thresholded_map),
        ("design_matrix", analysis_files.design_matrix),
        ("contrast_table", analysis_files.contrast_table),
        ("cluster_table", analysis_files.cluster_table),
        ("peak_table", analysis_files.peak_table),
    ):
        if not rel:
            continue
        path = run_dir / rel
        if not path.exists():
            continue
        hexdigest, status, reason = compute_file_sha256(path)
        manifest.append(
            BundleFileEntry(
                role=role,
                path=rel,
                size=path.stat().st_size if path.is_file() else None,
                checksum=(f"sha256:{hexdigest}" if hexdigest else None),
                checksum_status=status,
                checksum_reason=reason,
            )
        )

    bundle = AnalysisBundleV1(
        job_id=run_id,
        run_id=run_id,
        state=str(run_record.get("status") or "succeeded"),
        run_dir=str(run_dir),
        generated_at=_utc_iso(),
        files=analysis_files,
        file_manifest=manifest,
        observation=observation.model_dump(exclude_none=True),
        artifact_manifest=_load_json(run_dir / "artifact_manifest.json"),
        analysis_manifest=adapter.source_summary,
        run_card=adapter.run_card,
        provenance=provenance,
        artifacts=list(adapter.artifacts),
        policy_snapshot={
            "source": "external_artifact_adapter",
            "adapter_name": adapter.adapter_name,
            "source_kind": adapter.source_kind,
        },
    )
    _write_json(run_dir / "analysis_bundle.json", bundle.model_dump(exclude_none=True))
    created.append("analysis_bundle.json")
    return created


def stage_external_run(
    source_dir: Path | str,
    destination_run_dir: Path | str,
    *,
    spec: ExternalRunImportSpec,
    link_mode: LinkMode = "symlink",
    adapter_preference: str = "auto",
    overwrite: bool = False,
    dry_run: bool = False,
) -> ExternalRunImportResult:
    source = Path(source_dir).expanduser().resolve()
    destination = Path(destination_run_dir).expanduser().resolve()

    if not source.exists() or not (source.is_dir() or source.is_file()):
        raise FileNotFoundError(f"external source path not found: {source}")
    if destination.exists() and any(destination.iterdir()) and not overwrite:
        raise FileExistsError(
            f"destination run directory already exists: {destination}"
        )

    adapter = detect_external_artifact_adapter(source, preferred=adapter_preference)
    effective_spec = _effective_spec(spec, adapter)

    reused_root_files = (
        [name for name in _ROOT_REUSED_FILENAMES if (source / name).exists()]
        if source.is_dir()
        else []
    )
    if adapter is not None:
        reused_root_files = [
            name
            for name in reused_root_files
            if name not in _ADAPTER_GENERATED_FILENAMES
        ]
    extra_source_files = list(adapter.extra_source_files) if adapter is not None else []
    created_source_files = ["artifacts/source"]

    if not dry_run:
        destination.mkdir(parents=True, exist_ok=True)
        source_mount = destination / "artifacts" / "source"
        source_mount.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            _link_or_copy(source, source_mount, link_mode=link_mode)
        else:
            _link_or_copy(source, source_mount / source.name, link_mode=link_mode)
            created_source_files.append(f"artifacts/source/{source.name}")
        for extra_file in extra_source_files:
            source_path = Path(extra_file["source_path"]).expanduser().resolve()
            artifact_rel = extra_file["artifact_rel"]
            _link_or_copy(source_path, destination / artifact_rel, link_mode=link_mode)
            if artifact_rel not in created_source_files:
                created_source_files.append(artifact_rel)
        for name in reused_root_files:
            _link_or_copy(source / name, destination / name, link_mode=link_mode)
        run_record = build_imported_run_record(source, effective_spec, adapter=adapter)
        provenance = build_imported_provenance(source, effective_spec, adapter=adapter)
        _write_json(destination / "run.json", run_record)
        _write_json(
            destination / "provenance.json",
            provenance,
        )
        created_files = ["run.json", "provenance.json", *created_source_files]
        if adapter is not None:
            created_files.extend(
                name
                for name in _write_observation_bundle(
                    destination,
                    run_id=effective_spec.run_id,
                    run_record=run_record,
                    provenance=provenance,
                    adapter=adapter,
                )
                if name not in created_files
            )
    else:
        created_files = ["run.json", "provenance.json", "artifacts/source"]
        for extra_file in extra_source_files:
            artifact_rel = extra_file["artifact_rel"]
            if artifact_rel not in created_files:
                created_files.append(artifact_rel)
    return ExternalRunImportResult(
        run_id=effective_spec.run_id,
        source_dir=str(source),
        run_dir=str(destination),
        dry_run=dry_run,
        link_mode=link_mode,
        created_files=created_files,
        reused_root_files=reused_root_files,
        artifact_mount="artifacts/source",
        adapter_name=adapter.adapter_name if adapter is not None else None,
        review_tier="review_bundle_ready" if adapter is not None else None,
    )


def stage_external_run_in_mcp_store(
    source_dir: Path | str,
    *,
    spec: ExternalRunImportSpec,
    run_root: Path | str | None = None,
    link_mode: LinkMode = "symlink",
    adapter_preference: str = "auto",
    overwrite: bool = False,
    dry_run: bool = False,
) -> ExternalRunImportResult:
    destination = build_mcp_run_dir(spec.run_id, run_root)
    return stage_external_run(
        source_dir,
        destination,
        spec=spec,
        link_mode=link_mode,
        adapter_preference=adapter_preference,
        overwrite=overwrite,
        dry_run=dry_run,
    )


__all__ = [
    "ExternalRunImportResult",
    "ExternalRunImportSpec",
    "LinkMode",
    "available_external_artifact_adapters",
    "build_imported_provenance",
    "build_imported_run_record",
    "stage_external_run",
    "stage_external_run_in_mcp_store",
]
