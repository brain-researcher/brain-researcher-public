"""Analysis bundle writer.

Best-effort emission of `analysis_bundle.json`, the single "find everything for
this run" document used by export/benchmark/replay.
"""

from __future__ import annotations

import json
import mimetypes
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from brain_researcher.core.artifact_checksums import (
    compute_file_sha256,
    fill_artifact_checksums,
)
from brain_researcher.core.contracts.analysis_bundle import (
    AnalysisBundleFiles,
    AnalysisBundleV1,
    BundleFileEntry,
)
from brain_researcher.core.contracts.ids import IdsV1
from brain_researcher.core.contracts.loop_signals import (
    coerce_cross_stage_context,
    parse_loop_signals,
)
from brain_researcher.core.contracts.native_review_contract import (
    build_native_review_context,
)
from brain_researcher.core.contracts.policy_ref import PolicyRefV1
from brain_researcher.core.contracts.version_ref import VersionRefV1
from brain_researcher.core.execution_manifest import save_execution_manifest

_BUNDLE_SUPPORT_DIRNAME = ".bundle_support"
_USER_BUNDLE_FILE_SPECS: dict[str, tuple[str, str]] = {
    "user_environment_yml": ("environment.yml", "environment.yml"),
    "user_docker_compose_yml": ("docker-compose.yml", "docker-compose.yml"),
    "user_env_example": (".env.example", ".env.example"),
    "user_docs_index_md": ("docs/index.md", "docs_index.md"),
    "user_mcp_md": ("docs/mcp.md", "mcp.md"),
    "user_operations_md": ("docs/OPERATIONS.md", "operations.md"),
}


def _isoformat_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _relpath_or_name(path: Path, run_dir: Path) -> str:
    try:
        return path.relative_to(run_dir).as_posix()
    except Exception:
        return path.name


def _file_entry(path: Path, *, role: str, run_dir: Path) -> BundleFileEntry:
    rel = _relpath_or_name(path, run_dir)
    hexdigest, status, reason = compute_file_sha256(path)
    size = None
    try:
        size = path.stat().st_size if path.exists() and path.is_file() else None
    except Exception:
        size = None

    mime, _ = mimetypes.guess_type(path.name)
    entry = BundleFileEntry(
        role=role,
        path=rel,
        size=size,
        checksum=f"sha256:{hexdigest}" if hexdigest else None,
        checksum_status=status,
        checksum_reason=reason,
        mime=mime,
    )
    return entry


def _existing_relref(run_dir: Path, ref: str | None) -> str | None:
    if not isinstance(ref, str) or not ref.strip():
        return None
    candidate = Path(ref.strip()).expanduser()
    if not candidate.is_absolute():
        candidate = run_dir / candidate
    if not candidate.exists():
        return None
    try:
        return candidate.resolve().relative_to(run_dir.resolve()).as_posix()
    except Exception:
        return candidate.as_posix()


def _normalized_artifact_path(value: Any, *, run_dir: Path) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    marker = "/artifacts/files/"
    from_artifact_url = False
    if marker in text:
        text = text.split(marker, 1)[1]
        from_artifact_url = True
    else:
        parsed = urlparse(text)
        if parsed.scheme == "file":
            text = parsed.path
        elif parsed.scheme in {"http", "https"}:
            return None
    text = unquote(text).strip()
    if from_artifact_url:
        text = text.lstrip("/")
    if not text:
        return None
    try:
        candidate = Path(text)
        if candidate.is_absolute():
            text = candidate.resolve().relative_to(run_dir.resolve()).as_posix()
    except Exception:
        pass
    return text.lower()


def _artifact_key(artifact: dict[str, Any], *, run_dir: Path) -> str:
    for field in ("path", "uri", "file_path", "relative_path", "location"):
        path_value = _normalized_artifact_path(artifact.get(field), run_dir=run_dir)
        if path_value:
            return f"path:{path_value}"

    for nested_field in ("meta", "metadata"):
        nested = artifact.get(nested_field)
        if not isinstance(nested, dict):
            continue
        for field in ("path", "uri", "file_path", "relative_path", "location"):
            path_value = _normalized_artifact_path(nested.get(field), run_dir=run_dir)
            if path_value:
                return f"path:{path_value}"

    for field in ("url", "download_url"):
        value = artifact.get(field)
        if not (isinstance(value, str) and "/artifacts/files/" in value):
            continue
        path_value = _normalized_artifact_path(value, run_dir=run_dir)
        if path_value:
            return f"path:{path_value}"

    for field in ("url", "download_url", "name", "artifact_id", "id"):
        value = artifact.get(field)
        if isinstance(value, str) and value.strip():
            return f"{field}:{value.strip().lower()}"
    return ""


def _is_local_artifact_file_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    return text.startswith("/api/jobs/") and "/artifacts/files/" in text


def _merge_artifact_fields(target: dict[str, Any], source: dict[str, Any]) -> None:
    for field, value in source.items():
        if field in {"url", "download_url"} and _is_local_artifact_file_url(value):
            target[field] = value
            continue
        current = target.get(field)
        if current in (None, "", [], {}):
            target[field] = value
            continue
        if isinstance(current, dict) and isinstance(value, dict):
            for nested_field, nested_value in value.items():
                if current.get(nested_field) in (None, "", [], {}):
                    current[nested_field] = nested_value


def _dedupe_artifacts(
    artifacts: list[dict[str, Any]],
    *,
    run_dir: Path,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    merged_by_key: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        key = _artifact_key(artifact, run_dir=run_dir)
        if key and key in merged_by_key:
            _merge_artifact_fields(merged_by_key[key], artifact)
            continue
        artifact_payload = dict(artifact)
        if key:
            merged_by_key[key] = artifact_payload
        merged.append(artifact_payload)
    return merged


def review_context_file_refs(
    run_dir: Path,
    review_context: dict[str, Any] | None,
) -> dict[str, str | None]:
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
    return {
        "correction_summary_json": _existing_relref(
            run_dir,
            statistical_inference.get("correction_summary_path")
            or statistical_inference.get("threshold_summary_path"),
        ),
        "threshold_summary_json": _existing_relref(
            run_dir,
            statistical_inference.get("threshold_summary_path")
            or statistical_inference.get("correction_summary_path"),
        ),
        "thresholded_map": _existing_relref(
            run_dir,
            statistical_inference.get("thresholded_map_path"),
        ),
        "design_matrix": _existing_relref(
            run_dir,
            design_model.get("design_matrix_path"),
        ),
        "contrast_table": _existing_relref(
            run_dir,
            statistical_inference.get("contrast_table_path"),
        ),
        "cluster_table": _existing_relref(
            run_dir,
            statistical_inference.get("cluster_table_path"),
        ),
        "peak_table": _existing_relref(
            run_dir,
            statistical_inference.get("peak_table_path"),
        ),
    }


def statistical_inference_file_refs(
    run_dir: Path,
    review_context: dict[str, Any] | None,
) -> dict[str, str | None]:
    return review_context_file_refs(run_dir, review_context)


def _extract_job_id(job: Any) -> str | None:
    for key in ("job_id", "id", "jobId"):
        value = getattr(job, key, None)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _extract_run_id(job: Any) -> str | None:
    for key in ("run_id", "runId"):
        value = getattr(job, key, None)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _find_repo_root() -> Path | None:
    current = Path(__file__).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").exists():
            return candidate
    return None


def materialize_analysis_bundle_distribution_files(run_dir: Path) -> dict[str, str]:
    """Copy user-facing install assets into the run bundle when available."""

    support_dir = run_dir / _BUNDLE_SUPPORT_DIRNAME
    repo_root = _find_repo_root()
    resolved: dict[str, str] = {}

    for field_name, (source_relpath, dest_name) in _USER_BUNDLE_FILE_SPECS.items():
        dest_path = support_dir / dest_name
        if dest_path.exists() and dest_path.is_file():
            resolved[field_name] = dest_path.relative_to(run_dir).as_posix()
            continue

        if repo_root is None:
            continue
        source_path = repo_root / source_relpath
        if not source_path.exists() or not source_path.is_file():
            continue

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, dest_path)
        resolved[field_name] = dest_path.relative_to(run_dir).as_posix()

    return resolved


def save_analysis_bundle(job: Any, output_dir: Path) -> None:
    """Best-effort write analysis_bundle.json for a run directory.

    Args:
        job: Job-ish object (JobRecord adapter, enhanced Job, etc.)
        output_dir: run directory
    """

    try:
        run_dir = Path(getattr(job, "run_dir", output_dir))
    except Exception:
        run_dir = Path(output_dir)

    # Collect well-known docs (best-effort).
    obs_path = run_dir / "observation.json"
    analysis_path = run_dir / "analysis.json"
    artifact_manifest_path = run_dir / "artifact_manifest.json"
    trace_path = run_dir / "trace.jsonl"
    trajectory_path = run_dir / "trajectory.json"
    provenance_path = run_dir / "provenance.json"
    execution_manifest_path = run_dir / "execution_manifest.json"
    analysis_script_path = run_dir / "analysis.py"
    run_script_path = run_dir / "run.sh"
    requirements_path = run_dir / "requirements.txt"
    environment_path = run_dir / "environment.yml"
    docker_compose_path = run_dir / "docker-compose.repro.yml"
    fallback_docker_compose_path = run_dir / "docker-compose.yml"
    reward_path = run_dir / "reward_breakdown.json"
    inputs_manifest_path = run_dir / "inputs_manifest.json"
    stdout_path = run_dir / "stdout.txt"
    stderr_path = run_dir / "stderr.txt"

    observation = _safe_read_json(obs_path) if obs_path.exists() else None
    analysis_manifest = (
        _safe_read_json(analysis_path) if analysis_path.exists() else None
    )
    artifact_manifest = (
        _safe_read_json(artifact_manifest_path)
        if artifact_manifest_path.exists()
        else None
    )
    reward_breakdown = _safe_read_json(reward_path) if reward_path.exists() else None
    trajectory = _safe_read_json(trajectory_path) if trajectory_path.exists() else None
    inputs_manifest = (
        _safe_read_json(inputs_manifest_path) if inputs_manifest_path.exists() else None
    )
    user_bundle_files = materialize_analysis_bundle_distribution_files(run_dir)

    job_id = _extract_job_id(job)
    run_id = _extract_run_id(job)
    state = getattr(job, "state", None) or getattr(job, "status", None)
    if isinstance(state, str):
        state = state
    else:
        state = None

    created_at = getattr(job, "created_at", None)
    started_at = getattr(job, "started_at", None)
    finished_at = getattr(job, "finished_at", None)

    if isinstance(observation, dict):
        job_id = job_id or observation.get("job_id")
        run_id = run_id or observation.get("run_id")
        state = state or observation.get("state")
        created_at = (
            created_at if isinstance(created_at, int) else observation.get("created_at")
        )
        started_at = (
            started_at if isinstance(started_at, int) else observation.get("started_at")
        )
        finished_at = (
            finished_at
            if isinstance(finished_at, int)
            else observation.get("finished_at")
        )

    # Artifacts: prefer observation (most complete), then job payload.
    artifacts: list[dict[str, Any]] = []
    if isinstance(observation, dict) and isinstance(observation.get("artifacts"), list):
        artifacts = [a for a in observation.get("artifacts") if isinstance(a, dict)]
    if not artifacts:
        try:
            payload_json = getattr(job, "payload_json", None)
            if payload_json:
                payload = json.loads(payload_json)
                if isinstance(payload, dict) and isinstance(
                    payload.get("artifacts"), list
                ):
                    artifacts = [
                        a for a in payload.get("artifacts") if isinstance(a, dict)
                    ]
        except Exception:
            artifacts = []

    artifacts = _dedupe_artifacts(artifacts, run_dir=run_dir)
    artifacts = fill_artifact_checksums(artifacts, run_dir=run_dir)

    run_card = observation.get("run_card") if isinstance(observation, dict) else None
    provenance = (
        observation.get("provenance") if isinstance(observation, dict) else None
    )
    raw_context = None
    raw_signals = []
    if isinstance(observation, dict):
        raw_context = observation.get("cross_stage_context")
        if isinstance(observation.get("loop_signals"), list):
            raw_signals.extend(observation.get("loop_signals") or [])
    if isinstance(run_card, dict):
        raw_context = raw_context or run_card.get("cross_stage_context")
        if isinstance(run_card.get("loop_signals"), list):
            raw_signals.extend(run_card.get("loop_signals") or [])

    cross_stage_context = coerce_cross_stage_context(raw_context)
    loop_signals = parse_loop_signals(raw_signals)

    try:
        save_execution_manifest(
            job,
            run_dir,
            observation=observation,
            analysis_manifest=analysis_manifest,
            artifact_manifest=artifact_manifest,
            inputs_manifest=inputs_manifest,
            provenance=provenance if isinstance(provenance, dict) else None,
            run_card=run_card if isinstance(run_card, dict) else None,
        )
    except Exception:
        pass
    execution_manifest = (
        _safe_read_json(execution_manifest_path)
        if execution_manifest_path.exists()
        else None
    )

    files = AnalysisBundleFiles(
        observation_json="observation.json",
        inputs_manifest_json=(
            "inputs_manifest.json" if inputs_manifest_path.exists() else None
        ),
        analysis_json="analysis.json" if analysis_path.exists() else None,
        artifact_manifest_json=(
            "artifact_manifest.json" if artifact_manifest_path.exists() else None
        ),
        trace_jsonl="trace.jsonl" if trace_path.exists() else None,
        trajectory_json="trajectory.json" if trajectory_path.exists() else None,
        provenance_json="provenance.json" if provenance_path.exists() else None,
        execution_manifest_json=(
            "execution_manifest.json" if execution_manifest_path.exists() else None
        ),
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
        reward_breakdown_json="reward_breakdown.json" if reward_path.exists() else None,
        correction_summary_json=None,
        threshold_summary_json=None,
        thresholded_map=None,
        design_matrix=None,
        contrast_table=None,
        cluster_table=None,
        peak_table=None,
        stdout_txt="stdout.txt" if stdout_path.exists() else None,
        stderr_txt="stderr.txt" if stderr_path.exists() else None,
    )

    ids = None
    policy_ref = None
    versions = None
    if isinstance(observation, dict):
        if isinstance(observation.get("ids"), dict):
            try:
                ids = IdsV1.model_validate(observation["ids"])
            except Exception:
                ids = None
        if isinstance(observation.get("policy"), dict):
            try:
                policy_ref = PolicyRefV1.model_validate(observation["policy"])
            except Exception:
                policy_ref = None
        if isinstance(observation.get("versions"), dict):
            try:
                versions = VersionRefV1.model_validate(observation["versions"])
            except Exception:
                versions = None

    # File manifest with hashes for stable replay/export.
    file_manifest: list[BundleFileEntry] = []
    if obs_path.exists():
        file_manifest.append(_file_entry(obs_path, role="observation", run_dir=run_dir))
    if analysis_path.exists():
        file_manifest.append(
            _file_entry(analysis_path, role="analysis_manifest", run_dir=run_dir)
        )
    if artifact_manifest_path.exists():
        file_manifest.append(
            _file_entry(
                artifact_manifest_path, role="artifact_manifest", run_dir=run_dir
            )
        )
    if trace_path.exists():
        file_manifest.append(_file_entry(trace_path, role="trace", run_dir=run_dir))
    if trajectory_path.exists():
        file_manifest.append(
            _file_entry(trajectory_path, role="trajectory", run_dir=run_dir)
        )
    if provenance_path.exists():
        file_manifest.append(
            _file_entry(provenance_path, role="provenance", run_dir=run_dir)
        )
    if execution_manifest_path.exists():
        file_manifest.append(
            _file_entry(
                execution_manifest_path,
                role="execution_manifest",
                run_dir=run_dir,
            )
        )
    if analysis_script_path.exists():
        file_manifest.append(
            _file_entry(analysis_script_path, role="analysis_script", run_dir=run_dir)
        )
    if run_script_path.exists():
        file_manifest.append(
            _file_entry(run_script_path, role="run_script", run_dir=run_dir)
        )
    if requirements_path.exists():
        file_manifest.append(
            _file_entry(requirements_path, role="requirements", run_dir=run_dir)
        )
    if environment_path.exists():
        file_manifest.append(
            _file_entry(environment_path, role="environment", run_dir=run_dir)
        )
    if docker_compose_path.exists():
        file_manifest.append(
            _file_entry(docker_compose_path, role="docker_compose", run_dir=run_dir)
        )
    elif fallback_docker_compose_path.exists():
        file_manifest.append(
            _file_entry(
                fallback_docker_compose_path,
                role="docker_compose",
                run_dir=run_dir,
            )
        )
    for role, field_name in (
        ("user_environment", "user_environment_yml"),
        ("user_docker_compose", "user_docker_compose_yml"),
        ("user_env_example", "user_env_example"),
        ("user_quickstart", "user_quickstart_md"),
        ("user_installation", "user_installation_md"),
    ):
        relpath = user_bundle_files.get(field_name)
        if not relpath:
            continue
        file_manifest.append(_file_entry(run_dir / relpath, role=role, run_dir=run_dir))
    if reward_path.exists():
        file_manifest.append(
            _file_entry(reward_path, role="reward_breakdown", run_dir=run_dir)
        )
    if inputs_manifest_path.exists():
        file_manifest.append(
            _file_entry(inputs_manifest_path, role="inputs_manifest", run_dir=run_dir)
        )
    if stdout_path.exists():
        file_manifest.append(_file_entry(stdout_path, role="stdout", run_dir=run_dir))
    if stderr_path.exists():
        file_manifest.append(_file_entry(stderr_path, role="stderr", run_dir=run_dir))

    bundle_ids = ids or IdsV1(
        analysis_id=str(job_id) if job_id is not None else None,
        job_id=str(job_id) if job_id is not None else None,
        run_id=str(run_id) if run_id is not None else None,
    )

    bundle_kwargs: dict[str, Any] = {
        "ids": bundle_ids,
        "job_id": str(job_id) if job_id is not None else None,
        "run_id": str(run_id) if run_id is not None else None,
        "state": str(state) if state is not None else None,
        "created_at": created_at if isinstance(created_at, int) else None,
        "started_at": started_at if isinstance(started_at, int) else None,
        "finished_at": finished_at if isinstance(finished_at, int) else None,
        "run_dir": str(run_dir),
        "generated_at": _isoformat_z(datetime.now(timezone.utc)),
        "files": files,
        "file_manifest": file_manifest,
        "observation": observation,
        "inputs_manifest": inputs_manifest,
        "analysis_manifest": analysis_manifest,
        "artifact_manifest": artifact_manifest,
        "execution_manifest": execution_manifest,
        "reward_breakdown": reward_breakdown,
        "trajectory": trajectory,
        "artifacts": artifacts,
        "run_card": run_card if isinstance(run_card, dict) else None,
        "provenance": provenance if isinstance(provenance, dict) else None,
        "cross_stage_context": (
            cross_stage_context.model_dump(mode="json", exclude_none=True)
            if cross_stage_context
            else None
        ),
        "loop_signals": [
            signal.model_dump(mode="json", exclude_none=True) for signal in loop_signals
        ],
    }
    if policy_ref is not None:
        bundle_kwargs["policy"] = policy_ref
    if versions is not None:
        bundle_kwargs["versions"] = versions

    bundle = AnalysisBundleV1(**bundle_kwargs)

    review_context = build_native_review_context(
        bundle.model_dump(exclude_none=True),
        observation=observation if isinstance(observation, dict) else None,
        execution_manifest=(
            execution_manifest if isinstance(execution_manifest, dict) else None
        ),
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
        if isinstance(observation, dict):
            observation_run_card = observation.get("run_card")
            if isinstance(observation_run_card, dict):
                observation_run_card["review_context"] = dict(review_context)
            bundle.observation = observation

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
        if path.exists():
            bundle.file_manifest.append(_file_entry(path, role=role, run_dir=run_dir))

    try:
        _atomic_write_json(
            run_dir / "analysis_bundle.json", bundle.model_dump(exclude_none=True)
        )
    except Exception:
        return


__all__ = [
    "review_context_file_refs",
    "statistical_inference_file_refs",
    "materialize_analysis_bundle_distribution_files",
    "save_analysis_bundle",
]
