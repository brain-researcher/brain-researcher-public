"""Reproducibility scoring (v1).

This module computes a 0..1 reproducibility score from concrete, verifiable
evidence produced by a run. It is intentionally best-effort: missing files or
partial producers should reduce the score rather than raise exceptions.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from brain_researcher.core.contracts.policy_ref import PolicyRefV1
from brain_researcher.core.contracts.version_ref import VersionRefV1


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp_01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _as_sha256(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    v = value.strip()
    if not v:
        return None
    if v.startswith("sha256:"):
        hex_part = v.split("sha256:", 1)[1]
        if len(hex_part) == 64 and all(
            c in "0123456789abcdef" for c in hex_part.lower()
        ):
            return v
        return None
    if len(v) == 64 and all(c in "0123456789abcdef" for c in v.lower()):
        return f"sha256:{v.lower()}"
    return None


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _iter_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                yield item


def _count_sha256(items: Iterable[dict[str, Any]], *, key: str = "checksum") -> int:
    count = 0
    for item in items:
        if _as_sha256(item.get(key)) is not None:
            count += 1
    return count


def _trace_terminal_event_type(trace_path: Path) -> str | None:
    """Best-effort: parse the last JSONL line and extract a terminal-ish event type."""
    if not trace_path.exists() or not trace_path.is_file():
        return None
    try:
        with trace_path.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            chunk = 64 * 1024
            fh.seek(max(0, size - chunk))
            tail = fh.read().decode("utf-8", errors="ignore")
    except Exception:
        return None

    lines = [ln for ln in tail.splitlines() if ln.strip()]
    for raw in reversed(lines[-50:]):
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        for key in ("event_type", "event", "type"):
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
    return None


@dataclass(frozen=True)
class RubricCheck:
    check_id: str
    weight: float
    passed: bool
    details: dict[str, Any]


def compute_reproducibility_v1(
    *,
    run_dir: Path | None,
    datasets: list[dict[str, Any]] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    parameters: dict[str, Any] | None = None,
    versions: VersionRefV1 | dict[str, Any] | None = None,
    policy: PolicyRefV1 | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute reproducibility evidence + score.

    Returns a dict intended to live under RunCardV1.reproducibility.
    The score is always 0..1 (float) and is derived from verifiable evidence
    (files, checksums, version ids, etc.) when available.
    """
    datasets = datasets or []
    artifacts = artifacts or []
    parameters = parameters or {}

    policy_ref: PolicyRefV1 | None = None
    if isinstance(policy, PolicyRefV1):
        policy_ref = policy
    elif isinstance(policy, dict):
        try:
            policy_ref = PolicyRefV1.model_validate(policy)
        except Exception:
            policy_ref = None

    version_ref: VersionRefV1 | None = None
    if isinstance(versions, VersionRefV1):
        version_ref = versions
    elif isinstance(versions, dict):
        try:
            version_ref = VersionRefV1.model_validate(versions)
        except Exception:
            version_ref = None

    inputs_manifest = _load_json(run_dir / "inputs_manifest.json") if run_dir else None
    artifact_manifest = (
        _load_json(run_dir / "artifact_manifest.json") if run_dir else None
    )

    # Inputs evidence
    datasets_from_manifest = list(
        _iter_dicts(inputs_manifest.get("datasets") if inputs_manifest else None)
    )
    inputs_from_manifest = list(
        _iter_dicts(inputs_manifest.get("inputs") if inputs_manifest else None)
    )
    inputs_sha256_count = _count_sha256(inputs_from_manifest, key="checksum")

    datasets_ref_count = 0
    for ds in datasets:
        ref = ds.get("id") or ds.get("ref") or ds.get("dataset_id")
        if isinstance(ref, str) and ref.strip():
            datasets_ref_count += 1
    for ds in datasets_from_manifest:
        ref = ds.get("ref") or ds.get("id")
        if isinstance(ref, str) and ref.strip():
            datasets_ref_count += 1

    datasets_sha256_count = 0
    for ds in datasets:
        if _as_sha256(ds.get("checksum")) is not None:
            datasets_sha256_count += 1

    # Output evidence
    artifacts_from_manifest = list(
        _iter_dicts(artifact_manifest.get("artifacts") if artifact_manifest else None)
    )
    artifacts_sha256_count = (
        _count_sha256(artifacts_from_manifest, key="checksum")
        if artifacts_from_manifest
        else _count_sha256(
            [a for a in artifacts if isinstance(a, dict)], key="checksum"
        )
    )

    # Trace evidence
    trace_path = run_dir / "trace.jsonl" if run_dir else None
    trace_exists = bool(trace_path and trace_path.exists() and trace_path.is_file())
    last_trace_event = _trace_terminal_event_type(trace_path) if trace_path else None
    terminal_events = {
        "done",
        "job_finalized",
        "job_completed",
        "job_failed",
        "job_cancelled",
        "job_succeeded",
        "analysis.completed",
    }
    trace_terminal = bool(last_trace_event and last_trace_event in terminal_events)

    # Versions/policy evidence
    has_git_commit = bool(
        version_ref
        and isinstance(version_ref.git_commit, str)
        and version_ref.git_commit
    )
    has_pkg_version = bool(
        version_ref
        and isinstance(version_ref.brain_researcher_version, str)
        and version_ref.brain_researcher_version
    )
    tool_versions_count = len(version_ref.tool_versions) if version_ref else 0
    image_digests_count = 0
    if version_ref:
        for digest in version_ref.image_digests.values():
            if _as_sha256(digest) is not None:
                image_digests_count += 1

    policy_hash_ok = bool(policy_ref and _as_sha256(policy_ref.policy_hash) is not None)

    # Parameters evidence
    has_parameters = bool(parameters)
    has_random_seed = (
        parameters.get("random_seed") is not None or parameters.get("seed") is not None
    )

    checks: list[RubricCheck] = [
        RubricCheck(
            "inputs.dataset_ref",
            0.10,
            datasets_ref_count > 0,
            {"count": datasets_ref_count},
        ),
        RubricCheck(
            "inputs.dataset_sha256",
            0.10,
            datasets_sha256_count > 0 or inputs_sha256_count > 0,
            {
                "datasets_sha256": datasets_sha256_count,
                "inputs_sha256": inputs_sha256_count,
            },
        ),
        RubricCheck(
            "inputs.parameters",
            0.05,
            has_parameters,
            {"count": len(parameters)},
        ),
        RubricCheck(
            "inputs.random_seed",
            0.05,
            has_random_seed,
            {"present": has_random_seed},
        ),
        RubricCheck(
            "outputs.artifact_manifest",
            0.10,
            bool(artifact_manifest),
            {"present": bool(artifact_manifest)},
        ),
        RubricCheck(
            "outputs.artifact_sha256",
            0.20,
            artifacts_sha256_count > 0,
            {"sha256_count": artifacts_sha256_count},
        ),
        RubricCheck(
            "versions.git_commit",
            0.05,
            has_git_commit,
            {"present": has_git_commit},
        ),
        RubricCheck(
            "versions.pkg_version",
            0.05,
            has_pkg_version,
            {"present": has_pkg_version},
        ),
        RubricCheck(
            "versions.tool_versions",
            0.10,
            tool_versions_count > 0,
            {"count": tool_versions_count},
        ),
        RubricCheck(
            "versions.image_digest",
            0.10,
            image_digests_count > 0,
            {"count": image_digests_count},
        ),
        RubricCheck(
            "policy.policy_hash",
            0.05,
            policy_hash_ok,
            {"present": policy_hash_ok},
        ),
        RubricCheck(
            "trace.exists",
            0.03,
            trace_exists,
            {"present": trace_exists},
        ),
        RubricCheck(
            "trace.terminal",
            0.02,
            trace_terminal,
            {"last_event_type": last_trace_event},
        ),
    ]

    total_weight = sum(c.weight for c in checks) or 1.0
    score = sum(c.weight for c in checks if c.passed) / total_weight
    score = round(_clamp_01(score), 2)

    return {
        "score": score,
        "score_method": "reproducibility_rubric_v1",
        "breakdown": [
            {
                "id": c.check_id,
                "weight": c.weight,
                "passed": c.passed,
                "details": c.details,
            }
            for c in checks
        ],
        "is_reproducible": score >= 0.8,
    }


__all__ = ["compute_reproducibility_v1"]
