"""Run-level diagnostics summary (v1).

This module aggregates stable, UI-friendly diagnostics from best-effort inputs:
- job state + error message
- provenance child step summaries (errors, recoveries, taxonomy)
- artifact checksum statuses
- plan warnings

The output is embedded into the canonical `observation.json` as
`diagnostics_summary`.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any


def _as_dict(val: Any) -> dict[str, Any] | None:
    return val if isinstance(val, dict) else None


def _as_list(val: Any) -> list[Any] | None:
    return val if isinstance(val, list) else None


def _dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def build_diagnostics_summary(
    *,
    job_state: str,
    job_error_message: str | None,
    step_summaries: list[dict[str, Any]] | None,
    artifacts: list[dict[str, Any]] | None,
    plan_warnings: list[str] | None = None,
    violations: list[dict[str, Any]] | None = None,
    degraded: bool = False,
    top_k_codes: int = 8,
    max_next_actions: int = 5,
) -> dict[str, Any]:
    """Build a compact diagnostic summary for a run.

    This is intentionally best-effort and tolerant of missing/partial inputs.
    """

    warning_count = 0
    error_count = 0

    codes: Counter[str] = Counter()
    next_actions: list[str] = []
    sample_errors: list[dict[str, Any]] = []
    sample_warnings: list[dict[str, Any]] = []

    terminal_failure_states = {"failed", "timeout", "cancelled"}
    terminal_success_states = {"succeeded", "success"}

    # Job-level blocking severity.
    blocking_count = 1 if str(job_state).lower() in terminal_failure_states else 0
    if degraded and blocking_count == 0:
        warning_count += 1
        codes["job_state:degraded"] += 1
    if blocking_count:
        codes[f"job_state:{str(job_state).lower()}"] += 1
        if job_error_message:
            sample_errors.append({"scope": "job", "message": str(job_error_message)[:800]})

    # Plan warnings (planner output).
    if plan_warnings:
        warning_count += len([w for w in plan_warnings if isinstance(w, str) and w.strip()])
        for w in plan_warnings:
            if not isinstance(w, str) or not w.strip():
                continue
            codes["plan_warning"] += 1
            if len(sample_warnings) < 5:
                sample_warnings.append({"scope": "plan", "message": w[:800]})

    # Violations (gate/action masking/compliance)
    for v in violations or []:
        if not isinstance(v, dict):
            continue
        code = v.get("code") or "violation"
        severity = (v.get("severity") or "warn").lower()
        blocking = bool(v.get("blocking"))
        codes[f"violation:{code}"] += 1
        if blocking:
            blocking_count += 1
        elif severity in {"error", "critical"}:
            error_count += 1
        else:
            warning_count += 1
        if len(sample_errors) < 5 and (blocking or severity in {"error", "critical"}):
            sample_errors.append({
                "scope": "violation",
                "code": code,
                "message": v.get("message"),
                "stage": v.get("where", {}).get("stage") if isinstance(v.get("where"), dict) else None,
            })
        elif len(sample_warnings) < 5:
            sample_warnings.append({
                "scope": "violation",
                "code": code,
                "message": v.get("message"),
                "stage": v.get("where", {}).get("stage") if isinstance(v.get("where"), dict) else None,
            })

    # Step summaries (from provenance.json child_runs).
    for step in (step_summaries or []):
        if not isinstance(step, dict):
            continue
        state = str(step.get("state") or "unknown").lower()
        step_id = step.get("step_id") or step.get("id")
        step_id = str(step_id) if step_id is not None else None

        taxonomy = _as_dict(step.get("error_taxonomy"))
        recovery = _as_dict(step.get("recovery"))

        # Recovered steps are warnings (even if final state succeeded).
        if recovery is not None:
            warning_count += 1
            codes["step_recovered"] += 1
            if step_id and len(sample_warnings) < 5:
                sample_warnings.append(
                    {
                        "scope": "step",
                        "step_id": step_id,
                        "message": "step_recovered",
                        "recovery": recovery,
                    }
                )

        if state in {"failed", "timeout", "error"}:
            error_count += 1
            codes[f"step_state:{state}"] += 1
            if taxonomy:
                category = taxonomy.get("category")
                recovery_action = taxonomy.get("recovery_action")
                debug = _as_dict(taxonomy.get("debug")) or {}
                rule = debug.get("rule")
                if isinstance(rule, str) and rule:
                    codes[f"taxonomy:{rule}"] += 1
                elif isinstance(category, str) and category:
                    if isinstance(recovery_action, str) and recovery_action:
                        codes[f"taxonomy:{category}:{recovery_action}"] += 1
                    else:
                        codes[f"taxonomy:{category}"] += 1

                suggestions = _as_list(taxonomy.get("recovery_suggestions")) or []
                for s in suggestions:
                    if isinstance(s, str) and s.strip():
                        next_actions.append(s.strip())

            msg = step.get("error") or step.get("error_message") or step.get("last_error")
            if msg and len(sample_errors) < 5:
                sample_errors.append(
                    {
                        "scope": "step",
                        "step_id": step_id,
                        "state": state,
                        "message": str(msg)[:800],
                    }
                )
        elif state not in terminal_success_states and state != "unknown":
            # Non-terminal, non-success step states are warnings (e.g. skipped).
            warning_count += 1
            codes[f"step_state:{state}"] += 1

    # Artifact checksum statuses.
    for art in (artifacts or []):
        if not isinstance(art, dict):
            continue
        status = art.get("checksum_status")
        if not isinstance(status, str) or not status:
            continue
        status = status.lower()
        if status == "ok":
            continue
        codes[f"artifact_checksum:{status}"] += 1
        # Treat checksum gaps as warnings (the run may still be useful).
        warning_count += 1
        if len(sample_warnings) < 5:
            sample_warnings.append(
                {
                    "scope": "artifact",
                    "name": art.get("name"),
                    "path": art.get("path"),
                    "checksum_status": status,
                    "checksum_reason": art.get("checksum_reason"),
                }
            )

    # If the job succeeded but has step errors, avoid marking as blocking.
    if blocking_count == 0 and str(job_state).lower() in terminal_success_states:
        # Nothing to do; blocking_count already 0.
        pass

    top_codes = [{"code": code, "count": count} for code, count in codes.most_common(top_k_codes)]
    recommended = [{"action": a} for a in _dedupe_preserve_order(next_actions)[:max_next_actions]]

    return {
        "schema_version": "diagnostics-v1",
        "counts": {"warning": warning_count, "error": error_count, "blocking": blocking_count},
        "top_codes": top_codes,
        "recommended_next_actions": recommended,
        "sample_errors": sample_errors,
        "sample_warnings": sample_warnings,
    }


__all__ = ["build_diagnostics_summary"]
