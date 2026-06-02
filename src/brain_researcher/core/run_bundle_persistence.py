"""Persistence helpers for ObservationSpecV1 / AnalysisBundleV1 contracts.

Extracted from `services/agent/run_bundle.py` so that non-service callers
(research/, behavior/, autoresearch/) can persist canonical run bundles
without crossing the core -> services boundary. The service module
continues to re-export these helpers for backward compatibility.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from brain_researcher.core.analysis_bundle import (
    materialize_analysis_bundle_distribution_files,
    review_context_file_refs,
)
from brain_researcher.core.artifact_checksums import compute_file_sha256
from brain_researcher.core.artifact_manifest import save_artifact_manifest
from brain_researcher.core.contracts import (
    AnalysisBundleFiles,
    AnalysisBundleV1,
    BundleFileEntry,
    ObservationFiles,
    ObservationSpecV1,
    RMLogMetadataV1,
)
from brain_researcher.core.contracts.native_review_contract import (
    build_native_review_context,
)
from brain_researcher.core.execution_manifest import save_execution_manifest


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _atomic_write_json(path: Path, obj: dict[str, Any]) -> None:
    _atomic_write(path, json.dumps(obj, ensure_ascii=False, indent=2))


def _coerce_relpath(value: Any, *, run_dir: Path) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(run_dir.resolve()).as_posix()
        except Exception:
            return candidate.name
    return raw


def _coerce_rm_metadata(
    value: RMLogMetadataV1 | dict[str, Any] | None,
) -> RMLogMetadataV1 | dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, RMLogMetadataV1):
        return value
    if isinstance(value, dict):
        try:
            return RMLogMetadataV1.model_validate(value)
        except Exception:
            return value
    return None


def _extract_rm_paths(
    run_dir: Path,
    metadata: RMLogMetadataV1 | dict[str, Any] | None,
) -> tuple[str | None, str | None]:
    if isinstance(metadata, RMLogMetadataV1):
        return (
            _coerce_relpath(metadata.redacted_json, run_dir=run_dir),
            _coerce_relpath(metadata.raw_json, run_dir=run_dir),
        )
    if isinstance(metadata, dict):
        redacted = (
            metadata.get("redacted_json")
            or metadata.get("redacted_relpath")
            or metadata.get("redacted_path")
            or metadata.get("path_redacted")
        )
        raw = (
            metadata.get("raw_json")
            or metadata.get("raw_relpath")
            or metadata.get("raw_path")
            or metadata.get("path_raw")
        )
        return (
            _coerce_relpath(redacted, run_dir=run_dir),
            _coerce_relpath(raw, run_dir=run_dir),
        )
    return None, None


def _iter_bundle_entries(
    run_dir: Path, files: AnalysisBundleFiles
) -> Iterable[tuple[str, str]]:
    mapping = {
        "observation": files.observation_json,
        "analysis": files.analysis_json,
        "artifact_manifest": files.artifact_manifest_json,
        "trace": files.trace_jsonl,
        "trajectory": files.trajectory_json,
        "provenance": files.provenance_json,
        "execution_manifest": files.execution_manifest_json,
        "research_episode": files.research_episode_json,
        "option_set": files.option_set_json,
        "evidence_gate": files.evidence_gate_json,
        "commitment": files.commitment_json,
        "claim_report": files.claim_report_json,
        "claim_update": files.claim_update_json,
        "correction_summary": files.correction_summary_json,
        "threshold_summary": files.threshold_summary_json,
        "thresholded_map": files.thresholded_map,
        "design_matrix": files.design_matrix,
        "contrast_table": files.contrast_table,
        "cluster_table": files.cluster_table,
        "peak_table": files.peak_table,
        "analysis_script": files.analysis_script_py,
        "run_script": files.run_script_sh,
        "requirements": files.requirements_txt,
        "environment": files.environment_yml,
        "docker_compose": files.docker_compose_yml,
        "user_environment": files.user_environment_yml,
        "user_docker_compose": files.user_docker_compose_yml,
        "user_env_example": files.user_env_example,
        "user_quickstart": files.user_quickstart_md,
        "user_installation": files.user_installation_md,
        "reward_breakdown": files.reward_breakdown_json,
        "stdout": files.stdout_txt,
        "stderr": files.stderr_txt,
        "rm_pairwise_redacted": files.rm_pairwise_redacted_json,
        "rm_pairwise_raw": files.rm_pairwise_raw_json,
        "rm_process_redacted": files.rm_process_redacted_json,
        "rm_process_raw": files.rm_process_raw_json,
    }
    for role, rel in mapping.items():
        if not rel:
            continue
        yield role, rel


def persist_agent_observation(
    run_dir: Path,
    *,
    job_id: str,
    run_id: str,
    state: str,
    run_card: dict[str, Any] | None,
    provenance: dict[str, Any] | None,
    tool_calls: list[dict[str, Any]] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    violations: list[dict[str, Any]] | None = None,
    created_at_ms: int | None = None,
    started_at_ms: int | None = None,
    finished_at_ms: int | None = None,
    rm_pairwise: RMLogMetadataV1 | dict[str, Any] | None = None,
    rm_process: RMLogMetadataV1 | dict[str, Any] | None = None,
) -> Path:
    rm_pairwise_meta = _coerce_rm_metadata(rm_pairwise)
    rm_process_meta = _coerce_rm_metadata(rm_process)
    rm_pairwise_redacted, rm_pairwise_raw = _extract_rm_paths(run_dir, rm_pairwise_meta)
    rm_process_redacted, rm_process_raw = _extract_rm_paths(run_dir, rm_process_meta)

    files = ObservationFiles(
        observation_json="observation.json",
        trace_jsonl="trace.jsonl",
        provenance_json="provenance.json",
        reward_breakdown_json=None,
        rm_pairwise_redacted_json=rm_pairwise_redacted,
        rm_pairwise_raw_json=rm_pairwise_raw,
        rm_process_redacted_json=rm_process_redacted,
        rm_process_raw_json=rm_process_raw,
    )
    spec = ObservationSpecV1(
        job_id=job_id,
        run_id=run_id,
        state=state,
        created_at=created_at_ms,
        started_at=started_at_ms,
        finished_at=finished_at_ms,
        run_dir=str(run_dir),
        files=files,
        run_card=run_card,
        provenance=provenance,
        artifacts=list(artifacts or []),
        steps=list(tool_calls or []),
        violations=violations,
        rm_pairwise=rm_pairwise_meta,
        rm_process=rm_process_meta,
    )
    path = run_dir / "observation.json"
    _atomic_write_json(path, spec.model_dump(exclude_none=True))
    return path


def persist_agent_analysis_bundle(
    run_dir: Path,
    *,
    job_id: str,
    run_id: str,
    state: str,
    run_card: dict[str, Any] | None,
    provenance: dict[str, Any] | None,
    policy: dict[str, Any] | None = None,
    include_embedded: bool = True,
    rm_pairwise: RMLogMetadataV1 | dict[str, Any] | None = None,
    rm_process: RMLogMetadataV1 | dict[str, Any] | None = None,
) -> Path:
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    rm_pairwise_meta = _coerce_rm_metadata(rm_pairwise)
    rm_process_meta = _coerce_rm_metadata(rm_process)
    rm_pairwise_redacted, rm_pairwise_raw = _extract_rm_paths(run_dir, rm_pairwise_meta)
    rm_process_redacted, rm_process_raw = _extract_rm_paths(run_dir, rm_process_meta)
    try:
        save_execution_manifest(
            None,
            run_dir,
            observation=None,
            provenance=provenance if isinstance(provenance, dict) else None,
            run_card=run_card if isinstance(run_card, dict) else None,
        )
    except Exception:
        pass

    execution_manifest_path = run_dir / "execution_manifest.json"
    try:
        save_artifact_manifest(
            SimpleNamespace(
                job_id=job_id,
                run_id=run_id,
                run_dir=str(run_dir),
                payload_json=json.dumps({"artifacts": []}, ensure_ascii=False),
            ),
            run_dir,
        )
    except Exception:
        pass

    artifact_manifest_path = run_dir / "artifact_manifest.json"
    analysis_script_path = run_dir / "analysis.py"
    run_script_path = run_dir / "run.sh"
    requirements_path = run_dir / "requirements.txt"
    environment_path = run_dir / "environment.yml"
    docker_compose_path = run_dir / "docker-compose.repro.yml"
    fallback_docker_compose_path = run_dir / "docker-compose.yml"
    user_bundle_files = materialize_analysis_bundle_distribution_files(run_dir)

    files = AnalysisBundleFiles(
        observation_json="observation.json",
        artifact_manifest_json=(
            "artifact_manifest.json" if artifact_manifest_path.exists() else None
        ),
        trace_jsonl="trace.jsonl",
        trajectory_json="trajectory.json",
        provenance_json="provenance.json",
        execution_manifest_json=(
            "execution_manifest.json" if execution_manifest_path.exists() else None
        ),
        research_episode_json=(
            "research_episode.json"
            if (run_dir / "research_episode.json").exists()
            else None
        ),
        option_set_json=(
            "option_set.json" if (run_dir / "option_set.json").exists() else None
        ),
        evidence_gate_json=(
            "evidence_gate.json" if (run_dir / "evidence_gate.json").exists() else None
        ),
        commitment_json=(
            "commitment.json" if (run_dir / "commitment.json").exists() else None
        ),
        claim_report_json=(
            "claim_report.json" if (run_dir / "claim_report.json").exists() else None
        ),
        claim_update_json=(
            "claim_update.json" if (run_dir / "claim_update.json").exists() else None
        ),
        correction_summary_json=None,
        threshold_summary_json=None,
        thresholded_map=None,
        design_matrix=None,
        contrast_table=None,
        cluster_table=None,
        peak_table=None,
        analysis_script_py="analysis.py" if analysis_script_path.exists() else None,
        run_script_sh="run.sh" if run_script_path.exists() else None,
        requirements_txt="requirements.txt" if requirements_path.exists() else None,
        environment_yml="environment.yml" if environment_path.exists() else None,
        docker_compose_yml=(
            "docker-compose.repro.yml"
            if docker_compose_path.exists()
            else "docker-compose.yml" if fallback_docker_compose_path.exists() else None
        ),
        user_environment_yml=user_bundle_files.get("user_environment_yml"),
        user_docker_compose_yml=user_bundle_files.get("user_docker_compose_yml"),
        user_env_example=user_bundle_files.get("user_env_example"),
        user_quickstart_md=user_bundle_files.get("user_quickstart_md"),
        user_installation_md=user_bundle_files.get("user_installation_md"),
        rm_pairwise_redacted_json=rm_pairwise_redacted,
        rm_pairwise_raw_json=rm_pairwise_raw,
        rm_process_redacted_json=rm_process_redacted,
        rm_process_raw_json=rm_process_raw,
    )

    manifest: list[BundleFileEntry] = []
    for role, rel in _iter_bundle_entries(run_dir, files):
        path = run_dir / rel
        size = None
        try:
            size = path.stat().st_size if path.exists() and path.is_file() else None
        except OSError:
            size = None

        hexdigest, status, reason = compute_file_sha256(path)
        checksum = f"sha256:{hexdigest}" if hexdigest else None
        manifest.append(
            BundleFileEntry(
                role=role,
                path=rel,
                size=size,
                checksum=checksum,
                checksum_status=status,
                checksum_reason=reason,
            )
        )

    bundle = AnalysisBundleV1(
        job_id=job_id,
        run_id=run_id,
        state=state,
        run_dir=str(run_dir),
        generated_at=generated_at,
        files=files,
        file_manifest=manifest,
        run_card=run_card,
        provenance=provenance,
        artifact_manifest=(
            json.loads(artifact_manifest_path.read_text(encoding="utf-8"))
            if artifact_manifest_path.exists()
            else None
        ),
        execution_manifest=(
            json.loads(execution_manifest_path.read_text(encoding="utf-8"))
            if execution_manifest_path.exists()
            else None
        ),
        policy_snapshot=policy,
        rm_pairwise=rm_pairwise_meta,
        rm_process=rm_process_meta,
    )

    if include_embedded:
        try:
            obs_path = run_dir / files.observation_json
            if obs_path.exists():
                bundle.observation = json.loads(obs_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        try:
            traj_path = run_dir / (files.trajectory_json or "")
            if files.trajectory_json and traj_path.exists():
                bundle.trajectory = json.loads(traj_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    observation_payload = (
        bundle.observation if isinstance(bundle.observation, dict) else None
    )
    execution_payload = (
        bundle.execution_manifest
        if isinstance(bundle.execution_manifest, dict)
        else (
            bundle.execution_manifest.model_dump(exclude_none=True)
            if bundle.execution_manifest is not None
            else None
        )
    )
    review_context = build_native_review_context(
        bundle.model_dump(exclude_none=True),
        observation=observation_payload,
        execution_manifest=execution_payload,
    )
    if review_context:
        bundle.review_context = review_context
        for field_name, rel in review_context_file_refs(
            run_dir, review_context
        ).items():
            if rel:
                setattr(bundle.files, field_name, rel)
        if isinstance(bundle.run_card, dict):
            bundle.run_card["review_context"] = dict(review_context)
        if isinstance(observation_payload, dict):
            observation_run_card = observation_payload.get("run_card")
            if isinstance(observation_run_card, dict):
                observation_run_card["review_context"] = dict(review_context)
            bundle.observation = observation_payload

    known_roles = {entry.role for entry in bundle.file_manifest}
    for role, rel in (
        ("correction_summary", bundle.files.correction_summary_json),
        ("threshold_summary", bundle.files.threshold_summary_json),
        ("thresholded_map", bundle.files.thresholded_map),
        ("design_matrix", bundle.files.design_matrix),
        ("contrast_table", bundle.files.contrast_table),
        ("cluster_table", bundle.files.cluster_table),
        ("peak_table", bundle.files.peak_table),
    ):
        if not rel or role in known_roles:
            continue
        path = run_dir / rel
        if not path.exists():
            continue
        size = None
        try:
            size = path.stat().st_size if path.is_file() else None
        except OSError:
            size = None
        hexdigest, status, reason = compute_file_sha256(path)
        bundle.file_manifest.append(
            BundleFileEntry(
                role=role,
                path=rel,
                size=size,
                checksum=(f"sha256:{hexdigest}" if hexdigest else None),
                checksum_status=status,
                checksum_reason=reason,
            )
        )

    path = run_dir / "analysis_bundle.json"
    _atomic_write_json(path, bundle.model_dump(exclude_none=True))
    return path


__all__ = ["persist_agent_analysis_bundle", "persist_agent_observation"]
