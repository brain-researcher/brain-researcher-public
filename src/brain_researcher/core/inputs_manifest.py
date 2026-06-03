"""Inputs manifest writer.

Best-effort emission of `inputs_manifest.json` with input snapshot refs and
checksums for local files where possible.

This is intentionally lightweight and defensive: its job is to make runs more
replayable/benchmarkable without requiring all upstream callers to conform to
one payload schema immediately.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brain_researcher.core.artifact_checksums import compute_file_sha256


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


_URI_PREFIXES = ("http://", "https://", "s3://", "gs://", "hf://")


def _is_uri(value: str) -> bool:
    v = value.strip().lower()
    return any(v.startswith(p) for p in _URI_PREFIXES)


def _resolve_candidate_path(raw: str, *, run_dir: Path) -> Path | None:
    p = Path(raw).expanduser()
    if p.is_absolute():
        return p

    candidate = run_dir / p
    if candidate.exists():
        return candidate

    cwd_candidate = Path.cwd() / p
    if cwd_candidate.exists():
        return cwd_candidate

    return None


def _is_candidate_key(key: str) -> bool:
    k = key.lower()
    if k in {
        "input",
        "inputs",
        "in_file",
        "source",
        "image",
        "img",
        "atlas",
        "mask",
        "mask_img",
        "events",
        "confounds",
        "bids_dir",
        "bids_root",
        "data_dir",
        "dataset_dir",
    }:
        return True
    if k.endswith("_path") or k.endswith("_file") or k.endswith("_dir"):
        return True
    return False


def _walk_input_refs(obj: Any, *, prefix: str) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                continue
            if k in {"artifacts", "produces", "outputs", "output"}:
                continue

            key_path = f"{prefix}.{k}" if prefix else k
            if _is_candidate_key(k):
                if isinstance(v, str) and v.strip():
                    refs.append((key_path, v))
                elif isinstance(v, list):
                    for idx, item in enumerate(v):
                        if isinstance(item, str) and item.strip():
                            refs.append((f"{key_path}[{idx}]", item))

            refs.extend(_walk_input_refs(v, prefix=key_path))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            refs.extend(_walk_input_refs(item, prefix=f"{prefix}[{idx}]"))
    return refs


def _extract_payload(job: Any) -> dict[str, Any]:
    payload_json = getattr(job, "payload_json", None)
    if not payload_json:
        return {}
    try:
        payload = json.loads(payload_json)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _collect_datasets(payload: dict[str, Any]) -> list[dict[str, Any]]:
    meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    datasets: list[dict[str, Any]] = []
    if not isinstance(meta, dict):
        return datasets

    for key in (
        "datasets",
        "dataset",
        "dataset_id",
        "datasetId",
        "openneuro_dataset",
        "openneuro_dataset_id",
        "openneuro_datasetId",
    ):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            datasets.append({"ref": value.strip(), "source": f"metadata.{key}"})
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    datasets.append({"ref": item.strip(), "source": f"metadata.{key}"})
    return datasets


def save_inputs_manifest(job: Any, output_dir: Path) -> None:
    """Best-effort write inputs_manifest.json for a run.

    Args:
        job: Job-ish object with payload_json/run_dir fields.
        output_dir: run directory.
    """
    try:
        run_dir = Path(getattr(job, "run_dir", output_dir))
    except Exception:
        run_dir = Path(output_dir)

    payload = _extract_payload(job)
    datasets = _collect_datasets(payload)

    inputs: list[dict[str, Any]] = []
    cache: dict[str, tuple[str | None, str, str | None, int | None]] = {}

    # Scan common payload locations for file/dataset refs.
    roots: list[tuple[str, Any]] = []
    if "inputs" in payload:
        roots.append(("payload.inputs", payload.get("inputs")))
    if "input" in payload:
        roots.append(("payload.input", payload.get("input")))
    if "plan" in payload:
        roots.append(("payload.plan", payload.get("plan")))
    if "params" in payload:
        roots.append(("payload.params", payload.get("params")))
    if "parameters" in payload:
        roots.append(("payload.parameters", payload.get("parameters")))

    refs: list[tuple[str, str]] = []
    for prefix, obj in roots:
        refs.extend(_walk_input_refs(obj, prefix=prefix))

    for key_path, raw_value in refs:
        raw_value = raw_value.strip()
        entry: dict[str, Any] = {"key": key_path, "path": raw_value}

        if _is_uri(raw_value):
            entry["checksum_status"] = "skipped"
            entry["checksum_reason"] = "remote_uri"
            inputs.append(entry)
            continue

        resolved = _resolve_candidate_path(raw_value, run_dir=run_dir)
        if resolved is None:
            entry["checksum_status"] = "missing"
            entry["checksum_reason"] = "path_not_found"
            inputs.append(entry)
            continue

        entry["resolved_path"] = str(resolved)
        cache_key = str(resolved)
        if cache_key in cache:
            hexdigest, status, reason, size = cache[cache_key]
        else:
            if resolved.is_file():
                hexdigest, status, reason = compute_file_sha256(resolved)
                try:
                    size = resolved.stat().st_size
                except Exception:
                    size = None
            elif resolved.is_dir():
                hexdigest, status, reason, size = None, "skipped", "is_directory", None
            else:
                hexdigest, status, reason, size = None, "skipped", "not_a_regular_file", None
            cache[cache_key] = (hexdigest, status, reason, size)

        if size is not None:
            entry["size"] = size
        if hexdigest:
            entry["checksum"] = f"sha256:{hexdigest}"
        entry["checksum_status"] = status
        if reason:
            entry["checksum_reason"] = reason
        inputs.append(entry)

    manifest = {
        "schema_version": "inputs-manifest-v1",
        "job_id": _extract_job_id(job),
        "run_id": _extract_run_id(job),
        "run_dir": str(run_dir),
        "generated_at": _isoformat_z(datetime.now(timezone.utc)),
        "datasets": datasets,
        "inputs": inputs,
    }

    try:
        _atomic_write_json(run_dir / "inputs_manifest.json", manifest)
    except Exception:
        return


__all__ = ["save_inputs_manifest"]
