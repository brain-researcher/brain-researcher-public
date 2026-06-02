"""Unified analysis manifest writer.

Best-effort emission of `analysis.json` with artifact checksums for a run.
Uses the shared checksum helper so MCP/orchestrator agree on values.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brain_researcher.core.artifact_checksums import fill_artifact_checksums


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


def save_analysis_manifest(job, output_dir: Path) -> None:
    """Best-effort write analysis.json with artifacts + checksums.

    Args:
        job: JobAdapter or similar object with payload_json/artifacts/run_dir
        output_dir: run directory path
    """

    try:
        run_dir = Path(getattr(job, "run_dir", output_dir))
    except Exception:
        run_dir = Path(output_dir)

    artifacts: list[dict[str, Any]] = []

    # Prefer artifacts from observation.json if present (more complete)
    obs_path = run_dir / "observation.json"
    if obs_path.exists():
        try:
            obs = json.loads(obs_path.read_text())
            if isinstance(obs, dict):
                artifacts = obs.get("artifacts") or []
        except Exception:
            pass

    # Fallback: artifacts from job payload
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

    # Fill checksums with shared helper (mandatory status/skipped)
    artifacts = fill_artifact_checksums(artifacts, run_dir=run_dir)

    manifest = {
        "schema_version": "analysis-manifest-v1",
        "job_id": _extract_job_id(job),
        "run_id": _extract_run_id(job),
        "run_dir": str(run_dir),
        "generated_at": _isoformat_z(datetime.now(timezone.utc)),
        "artifacts": artifacts,
    }

    try:
        _atomic_write_json(run_dir / "analysis.json", manifest)
    except Exception:
        # best effort; ignore
        return


__all__ = ["save_analysis_manifest"]
