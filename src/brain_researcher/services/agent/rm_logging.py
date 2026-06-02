"""Helpers for optional redact+raw-vault RM logging."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brain_researcher.core.artifact_checksums import compute_file_sha256
from brain_researcher.core.contracts.observation import RMLogMetadataV1
from brain_researcher.services.shared.log_scrubber import scrub_data


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _validate_relpath(run_dir: Path, relpath: str) -> Path:
    if not isinstance(relpath, str) or not relpath.strip():
        raise ValueError("RM log path must be a non-empty string")

    candidate = Path(relpath.strip())
    if candidate.is_absolute():
        raise ValueError("RM log path must be relative to run_dir")

    run_root = run_dir.resolve()
    resolved = (run_root / candidate).resolve()
    if not resolved.is_relative_to(run_root):
        raise ValueError("RM log path resolves outside run_dir")
    return resolved


def write_rm_log_pair(
    run_dir: Path,
    *,
    payload: Any,
    redacted_relpath: str,
    raw_relpath: str,
    policy: str = "redact+raw-vault",
    metadata: dict[str, Any] | None = None,
) -> tuple[RMLogMetadataV1, str, str]:
    """Write raw+redacted RM JSON logs and return metadata with relative paths.

    Raises on serialization or file errors; callers decide fail-open behavior.
    """

    run_dir.mkdir(parents=True, exist_ok=True)
    redacted_path = _validate_relpath(run_dir, redacted_relpath)
    raw_path = _validate_relpath(run_dir, raw_relpath)

    _atomic_write_json(raw_path, payload)
    _atomic_write_json(redacted_path, scrub_data(payload))

    redacted_hex, redacted_status, redacted_reason = compute_file_sha256(redacted_path)
    raw_hex, raw_status, raw_reason = compute_file_sha256(raw_path)

    rm_meta = RMLogMetadataV1(
        policy=policy,
        redacted_json=redacted_relpath,
        raw_json=raw_relpath,
        redacted_checksum=f"sha256:{redacted_hex}" if redacted_hex else None,
        raw_checksum=f"sha256:{raw_hex}" if raw_hex else None,
        redacted_checksum_status=redacted_status,
        raw_checksum_status=raw_status,
        redacted_checksum_reason=redacted_reason,
        raw_checksum_reason=raw_reason,
        generated_at=_iso_utc_now(),
        metadata=metadata,
    )
    return rm_meta, redacted_relpath, raw_relpath


def _iso_to_epoch_ms(ts: Any) -> int | None:
    if not isinstance(ts, str) or not ts.strip():
        return None
    value = ts.strip()
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp() * 1000)
    except Exception:
        return None


def _step_reward(step: dict[str, Any]) -> tuple[float, dict[str, float]]:
    status = str(step.get("status") or "").lower()
    error = str(step.get("error") or "").strip().lower()
    reward = 0.0
    breakdown: dict[str, float] = {}

    if status == "succeeded":
        reward += 0.5
        breakdown["succeeded"] = 0.5
    elif status in {"failed", "error"}:
        reward -= 0.6
        breakdown["failed"] = -0.6
    elif status == "skipped":
        reward -= 0.1
        breakdown["skipped"] = -0.1

    if "timeout" in error:
        reward -= 0.3
        breakdown["timeout_penalty"] = -0.3
    if "blocked" in error:
        reward -= 0.2
        breakdown["blocked_penalty"] = -0.2

    return reward, breakdown


def _build_pairwise_payload(
    *,
    run_id: str,
    policy: str,
    provenance: dict[str, Any],
    tool_calls: list[dict[str, Any]],
    preflight_issues: list[dict[str, Any]],
) -> dict[str, Any]:
    candidates = []
    for idx, call in enumerate(tool_calls, start=1):
        status = str(call.get("status") or "").lower()
        score = 1.0 if status in {"succeeded", "ok", "success"} else 0.0
        candidates.append(
            {
                "candidate_id": f"c{idx}",
                "tool": call.get("name"),
                "status": status,
                "score": score,
                "error": call.get("error"),
            }
        )

    winner = "tie"
    if len(candidates) >= 2:
        a = candidates[0]
        b = candidates[1]
        if a["score"] > b["score"]:
            winner = "A"
        elif b["score"] > a["score"]:
            winner = "B"
    elif len(candidates) == 1:
        winner = "A"

    return {
        "schema_version": "rm-pairwise-v1",
        "run_id": run_id,
        "policy": policy,
        "label_source": "llm_as_judge+rules",
        "confidence": 0.5,
        "request": provenance.get("request"),
        "preflight_issues": preflight_issues,
        "candidates": candidates,
        "winner": winner,
    }


def _build_process_payload(
    *,
    run_id: str,
    policy: str,
    record: dict[str, Any],
    tool_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    step_index: dict[str, dict[str, Any]] = {}
    for step in record.get("steps") or []:
        if isinstance(step, dict):
            step_id = str(step.get("step_id") or "")
            if step_id:
                step_index[step_id] = step

    rows = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        step_id = str(call.get("tool_call_id") or "")
        step = step_index.get(step_id, {})
        started = _iso_to_epoch_ms(step.get("started_at"))
        finished = _iso_to_epoch_ms(step.get("finished_at"))
        latency_ms = None
        if started is not None and finished is not None and finished >= started:
            latency_ms = finished - started

        reward, breakdown = _step_reward(step)
        rows.append(
            {
                "step_id": step_id,
                "tool": call.get("name"),
                "status": step.get("status") or call.get("status"),
                "error": step.get("error") or call.get("error"),
                "latency_ms": latency_ms,
                "reward": reward,
                "reward_breakdown": breakdown,
                "terminal": False,
            }
        )

    if rows:
        rows[-1]["terminal"] = True

    return {
        "schema_version": "rm-process-v1",
        "run_id": run_id,
        "policy": policy,
        "label_source": "llm_as_judge+rules",
        "steps": rows,
        "summary": {
            "total_steps": len(rows),
            "succeeded": sum(1 for r in rows if str(r.get("status")) == "succeeded"),
            "failed": sum(
                1 for r in rows if str(r.get("status")) in {"failed", "error"}
            ),
        },
    }


def generate_rm_logging_files(
    *,
    run_dir: Path,
    run_id: str,
    policy: str,
    provenance: dict[str, Any],
    record: dict[str, Any],
    tool_calls: list[dict[str, Any]],
    preflight_issues: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build and persist pairwise/process RM logs (raw + redacted)."""

    pairwise_payload = _build_pairwise_payload(
        run_id=run_id,
        policy=policy,
        provenance=provenance,
        tool_calls=tool_calls,
        preflight_issues=preflight_issues,
    )
    process_payload = _build_process_payload(
        run_id=run_id,
        policy=policy,
        record=record,
        tool_calls=tool_calls,
    )

    pairwise_meta, pairwise_redacted, pairwise_raw = write_rm_log_pair(
        run_dir,
        payload=pairwise_payload,
        redacted_relpath="rm/pairwise.redacted.json",
        raw_relpath="vault/rm_pairwise.raw.json",
        policy=policy,
        metadata={"role": "rm_pairwise"},
    )
    process_meta, process_redacted, process_raw = write_rm_log_pair(
        run_dir,
        payload=process_payload,
        redacted_relpath="rm/process.redacted.json",
        raw_relpath="vault/rm_process.raw.json",
        policy=policy,
        metadata={"role": "rm_process"},
    )

    return {
        "status": "ok",
        "policy": policy,
        "files": {
            "rm_pairwise_redacted_json": pairwise_redacted,
            "rm_pairwise_raw_json": pairwise_raw,
            "rm_process_redacted_json": process_redacted,
            "rm_process_raw_json": process_raw,
        },
        "rm_pairwise": pairwise_meta.model_dump(exclude_none=True),
        "rm_process": process_meta.model_dump(exclude_none=True),
    }


__all__ = ["generate_rm_logging_files", "write_rm_log_pair"]
