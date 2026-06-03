"""Artifact manifest writer.

Best-effort emission of `artifact_manifest.json` with checksums and QC report refs.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brain_researcher.core.artifact_checksums import (
    compute_file_sha256,
    fill_artifact_checksums,
)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _isoformat_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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


def _collect_qc_reports(run_dir: Path) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for path in sorted(run_dir.rglob("*qc_report*.json")):
        if not path.is_file():
            continue
        rel = path.relative_to(run_dir).as_posix()
        hexdigest, status, reason = compute_file_sha256(path)
        entry: dict[str, Any] = {
            "path": rel,
            "checksum_status": status,
        }
        if hexdigest:
            entry["checksum"] = f"sha256:{hexdigest}"
        if reason:
            entry["checksum_reason"] = reason
        reports.append(entry)
    return reports


def save_artifact_manifest(job, output_dir: Path) -> None:
    """Best-effort write artifact_manifest.json with artifacts + QC report refs."""
    try:
        run_dir = Path(getattr(job, "run_dir", output_dir))
    except Exception:
        run_dir = Path(output_dir)

    artifacts: list[dict[str, Any]] = []
    obs_path = run_dir / "observation.json"
    if obs_path.exists():
        try:
            obs = json.loads(obs_path.read_text())
            if isinstance(obs, dict):
                artifacts = obs.get("artifacts") or []
        except Exception:
            pass

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

    artifacts = fill_artifact_checksums(artifacts, run_dir=run_dir)
    qc_reports = _collect_qc_reports(run_dir)

    manifest = {
        "schema_version": "artifact-manifest-v1",
        "job_id": _extract_job_id(job),
        "run_id": _extract_run_id(job),
        "run_dir": str(run_dir),
        "generated_at": _isoformat_z(datetime.now(timezone.utc)),
        "artifacts": artifacts,
        "qc_reports": qc_reports,
    }

    try:
        _atomic_write_json(run_dir / "artifact_manifest.json", manifest)
    except Exception:
        return


__all__ = ["save_artifact_manifest"]
