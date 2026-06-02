"""Run artifact contract validation helpers.

Converts missing/empty required files into canonical Violation objects so
observation/build paths can surface structured degradations.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from brain_researcher.core.contracts import Violation, ViolationLocation
from brain_researcher.core.contracts.artifact_contract import (  # noqa: F401
    _ARTIFACT_CONTRACTS,
    CORE_RUN_ARTIFACT_COMPONENTS,
    ArtifactContractSpec,
    ArtifactFormat,
    MissingArtifactPolicy,
    _normalize_profile,
    artifact_contract_for_profile,
    infer_artifact_profile,
    optional_artifacts_for_profile,
    required_artifacts_for_profile,
)

_SUCCEEDED_STATES = {"succeeded", "completed", "success", "successful"}


def _artifact_file_status(
    path: Path,
    spec: ArtifactContractSpec,
) -> tuple[str, str | None]:
    if not path.exists() or not path.is_file():
        return "missing", "file_not_found"

    try:
        if path.stat().st_size == 0:
            return "empty", "zero_bytes"
    except OSError as exc:
        return "invalid", f"stat_failed:{type(exc).__name__}"

    if spec.artifact_format == "jsonl_objects":
        parsed_any = False
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception as exc:
            return "invalid", f"read_failed:{type(exc).__name__}"
        for line_number, raw_line in enumerate(lines, start=1):
            if not raw_line.strip():
                continue
            parsed_any = True
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError:
                return "invalid", f"line_{line_number}_not_json"
            if not isinstance(payload, dict):
                return "invalid", f"line_{line_number}_not_json_object"
        if not parsed_any:
            return "empty", "no_jsonl_events"
        return "present", None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "invalid", "not_json"
    except Exception as exc:
        return "invalid", f"read_failed:{type(exc).__name__}"
    if not isinstance(payload, dict):
        return "invalid", "not_json_object"
    return "present", None


def _violation_for_artifact_status(
    *,
    spec: ArtifactContractSpec,
    status: str,
    reason: str | None,
    job_profile: str,
) -> Violation:
    blocking = spec.missing_policy == "fail"
    status_label = {
        "missing": "missing",
        "empty": "empty",
        "invalid": "invalid",
    }.get(status, status)
    return Violation(
        code=f"ARTIFACT_{status.upper()}_{spec.code_suffix}",
        message=f"Required artifact is {status_label}: {spec.filename}",
        severity="error" if blocking else "warn",
        blocking=blocking,
        where=ViolationLocation(
            component="artifact_validator",
            stage="postcheck",
            path=spec.filename,
        ),
        suggested_fix=(
            "Ensure artifact writer is enabled and emits the documented minimum "
            "artifact contract."
        ),
        details={
            "job_profile": _normalize_profile(job_profile),
            "required_file": spec.filename,
            "missing_policy": spec.missing_policy,
            "minimum_contract": spec.minimum_contract,
            "status_reason": reason,
        },
    )


def validate_run_artifacts(
    *,
    run_dir: Path | str,
    job_profile: str,
    state: str | None,
    assume_present: set[str] | None = None,
) -> list[Violation]:
    """Validate required files for terminal-success runs.

    Returns violations only for succeeded/completed runs; non-success states
    intentionally skip strict artifact completeness checks.
    """

    normalized_state = (state or "").strip().lower()
    if "." in normalized_state:
        normalized_state = normalized_state.rsplit(".", 1)[-1]
    if normalized_state not in _SUCCEEDED_STATES:
        return []

    root = Path(run_dir)
    assumed = assume_present or set()

    violations: list[Violation] = []
    for spec in artifact_contract_for_profile(job_profile):
        if not spec.required:
            continue
        filename = spec.filename
        if filename in assumed:
            continue

        status, reason = _artifact_file_status(root / filename, spec)
        if status != "present":
            violations.append(
                _violation_for_artifact_status(
                    spec=spec,
                    status=status,
                    reason=reason,
                    job_profile=job_profile,
                )
            )

    return violations


def build_artifact_contract_summary(
    *,
    run_dir: Path | str,
    job_profile: str,
    state: str | None,
    assume_present: set[str] | None = None,
) -> dict[str, Any]:
    """Build a stable artifact contract summary for observation/certification."""

    normalized_state = (state or "").strip().lower()
    if "." in normalized_state:
        normalized_state = normalized_state.rsplit(".", 1)[-1]

    profile = _normalize_profile(job_profile)
    root = Path(run_dir)
    assumed = assume_present or set()
    specs = list(artifact_contract_for_profile(profile))
    required = [spec.filename for spec in specs if spec.required]
    optional = [spec.filename for spec in specs if not spec.required]

    present: list[str] = []
    missing: list[str] = []
    empty: list[str] = []
    invalid: list[str] = []
    artifact_rows: list[dict[str, Any]] = []
    impacted: dict[str, list[str]] = {
        "fail": [],
        "degraded": [],
        "still_evaluable": [],
    }
    for spec in specs:
        filename = spec.filename
        artifact_status = "missing"
        if filename in assumed:
            artifact_status = "present"
            reason = None
            present.append(filename)
        else:
            artifact_status, reason = _artifact_file_status(root / filename, spec)
            if artifact_status == "missing":
                missing.append(filename)
            elif artifact_status == "empty":
                empty.append(filename)
            elif artifact_status == "invalid":
                invalid.append(filename)
            else:
                present.append(filename)
        if artifact_status != "present":
            impacted[spec.missing_policy].append(filename)
        artifact_rows.append(
            {
                **asdict(spec),
                "status": artifact_status,
                "present": artifact_status == "present",
                "status_reason": reason,
            }
        )

    if normalized_state not in _SUCCEEDED_STATES:
        status = "skipped"
    elif impacted["fail"]:
        status = "failed"
    elif impacted["degraded"]:
        status = "degraded"
    else:
        status = "ok"

    if status == "failed":
        reviewability = "not_evaluable"
    elif status == "degraded":
        reviewability = "degraded_evaluable"
    elif status == "ok":
        reviewability = "fully_evaluable"
    else:
        reviewability = "not_applicable"

    complete_count = len(present)
    total = len(required)
    required_present = sum(1 for name in required if name in present)
    violations = validate_run_artifacts(
        run_dir=root,
        job_profile=profile,
        state=state,
        assume_present=assumed,
    )

    return {
        "profile": profile,
        "state": normalized_state,
        "status": status,
        "reviewability": reviewability,
        "required": required,
        "required_bundle_files": required,
        "optional": optional,
        "present": present,
        "missing": missing,
        "empty": empty,
        "invalid": invalid,
        "missing_by_policy": impacted,
        "artifact_policies": artifact_rows,
        "complete_count": required_present,
        "total_required": total,
        "completeness_ratio": (round(required_present / total, 4) if total else 1.0),
        "all_contract_files_present": complete_count == len(specs),
        "violation_codes": [violation.code for violation in violations],
    }


__all__ = [
    "ArtifactContractSpec",
    "CORE_RUN_ARTIFACT_COMPONENTS",
    "artifact_contract_for_profile",
    "build_artifact_contract_summary",
    "infer_artifact_profile",
    "optional_artifacts_for_profile",
    "required_artifacts_for_profile",
    "validate_run_artifacts",
]
