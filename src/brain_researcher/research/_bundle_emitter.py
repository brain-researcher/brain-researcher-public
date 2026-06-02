"""Shared native bundle emission helpers for research lines."""

from __future__ import annotations

import json
from collections.abc import Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from brain_researcher.core.artifact_checksums import compute_file_sha256
from brain_researcher.core.contracts.analysis_bundle import BundleFileEntry
from brain_researcher.core.contracts.native_review_contract import (
    build_native_review_context,
)
from brain_researcher.core.run_bundle_persistence import (
    persist_agent_analysis_bundle,
    persist_agent_observation,
)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _coerce_relpath(run_dir: Path, ref: str | Path | None) -> str | None:
    if ref is None:
        return None
    raw = str(ref).strip()
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(run_dir.resolve()).as_posix()
        except Exception:
            return candidate.name
    return candidate.as_posix()


def _normalize_relpaths(
    run_dir: Path,
    refs: Sequence[str | Path] | None,
) -> list[str]:
    normalized: list[str] = []
    for ref in refs or ():
        rel = _coerce_relpath(run_dir, ref)
        if rel and rel not in normalized:
            normalized.append(rel)
    return normalized


def _append_manifest_entry(
    *,
    run_dir: Path,
    manifest: list[dict[str, Any]],
    role: str,
    relpath: str | None,
) -> None:
    if not relpath:
        return
    if any(
        isinstance(entry, dict)
        and entry.get("role") == role
        and entry.get("path") == relpath
        for entry in manifest
    ):
        return
    path = run_dir / relpath
    if not path.exists():
        return
    hexdigest, status, reason = compute_file_sha256(path)
    entry = BundleFileEntry(
        role=role,
        path=relpath,
        size=path.stat().st_size if path.is_file() else None,
        checksum=f"sha256:{hexdigest}" if hexdigest else None,
        checksum_status=status,
        checksum_reason=reason,
    )
    manifest.append(entry.model_dump(exclude_none=True))


def emit_native_bundle(
    run_dir: Path | str,
    *,
    job_id: str,
    run_id: str,
    state: str,
    run_card: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    violations: list[dict[str, Any]] | None = None,
    policy: dict[str, Any] | None = None,
    created_at_ms: int | None = None,
    started_at_ms: int | None = None,
    finished_at_ms: int | None = None,
    round_id: str | None = None,
    inputs_manifest_ref: str | Path | None = None,
    failure_summary: str | None = None,
    qc_summary_ref: str | Path | None = None,
    source_manifests: Sequence[str | Path] | None = None,
    evidence_index: Sequence[str] | None = None,
) -> dict[str, Path]:
    run_dir = Path(run_dir).expanduser().resolve()
    observation_path = persist_agent_observation(
        run_dir,
        job_id=job_id,
        run_id=run_id,
        state=state,
        run_card=run_card,
        provenance=provenance,
        tool_calls=tool_calls,
        artifacts=artifacts,
        violations=violations,
        created_at_ms=created_at_ms,
        started_at_ms=started_at_ms,
        finished_at_ms=finished_at_ms,
    )
    bundle_path = persist_agent_analysis_bundle(
        run_dir,
        job_id=job_id,
        run_id=run_id,
        state=state,
        run_card=run_card,
        provenance=provenance,
        policy=policy,
    )

    observation = _read_json(observation_path)
    bundle = _read_json(bundle_path)
    execution_manifest_path = run_dir / "execution_manifest.json"
    execution_manifest = (
        _read_json(execution_manifest_path) if execution_manifest_path.exists() else {}
    )

    review_context = build_native_review_context(
        bundle,
        observation=observation,
        execution_manifest=execution_manifest,
    )
    if review_context:
        bundle["review_context"] = deepcopy(review_context)
        bundle_run_card = bundle.get("run_card")
        if isinstance(bundle_run_card, dict):
            bundle_run_card["review_context"] = deepcopy(review_context)
        observation_run_card = observation.get("run_card")
        if isinstance(observation_run_card, dict):
            observation_run_card["review_context"] = deepcopy(review_context)
    bundle["observation"] = observation

    inputs_manifest_rel = _coerce_relpath(run_dir, inputs_manifest_ref)
    qc_summary_rel = _coerce_relpath(run_dir, qc_summary_ref)
    manifest_refs = _normalize_relpaths(run_dir, source_manifests)
    if inputs_manifest_rel and inputs_manifest_rel not in manifest_refs:
        manifest_refs.append(inputs_manifest_rel)

    observation["round_id"] = round_id
    observation["inputs_manifest_ref"] = inputs_manifest_rel
    observation["failure_summary"] = failure_summary

    default_evidence_index = [
        rel
        for rel in (
            observation.get("files", {}).get("observation_json"),
            bundle.get("files", {}).get("execution_manifest_json"),
            qc_summary_rel,
            *manifest_refs,
        )
        if isinstance(rel, str) and rel
    ]
    merged_evidence_index: list[str] = []
    for rel in [*default_evidence_index, *(evidence_index or ())]:
        if rel and rel not in merged_evidence_index:
            merged_evidence_index.append(rel)

    bundle["evidence_index"] = merged_evidence_index
    bundle["qc_summary_ref"] = qc_summary_rel
    bundle["source_manifests"] = manifest_refs
    if inputs_manifest_rel and not bundle.get("inputs_manifest"):
        inputs_manifest_path = run_dir / inputs_manifest_rel
        if inputs_manifest_path.exists():
            try:
                bundle["inputs_manifest"] = _read_json(inputs_manifest_path)
            except Exception:
                pass
    file_manifest = bundle.get("file_manifest")
    if not isinstance(file_manifest, list):
        file_manifest = []
        bundle["file_manifest"] = file_manifest
    _append_manifest_entry(
        run_dir=run_dir,
        manifest=file_manifest,
        role="qc_summary",
        relpath=qc_summary_rel,
    )
    for relpath in manifest_refs:
        _append_manifest_entry(
            run_dir=run_dir,
            manifest=file_manifest,
            role="source_manifest",
            relpath=relpath,
        )

    _atomic_write_json(observation_path, observation)
    _atomic_write_json(bundle_path, bundle)
    return {
        "observation": observation_path,
        "analysis_bundle": bundle_path,
        "execution_manifest": run_dir / "execution_manifest.json",
    }


__all__ = ["emit_native_bundle"]
