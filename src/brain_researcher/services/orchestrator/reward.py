"""Reward breakdown generator.

We treat `trajectory.json` (ATIF) as the canonical source for training/eval.
`trace.jsonl` is an event stream and is only used for supplemental signals.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not path.exists():
        return out
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
    except Exception:
        return out
    return out


def compute_reward_breakdown_from_run_dir(run_dir: Path) -> dict[str, Any]:
    """Compute a simple reward signal from trajectory + events."""
    trajectory = _load_json(run_dir / "trajectory.json") or {}
    trace_events = _load_jsonl(run_dir / "trace.jsonl")

    violation_penalty = 0.0
    mask_penalty = 0.0
    recovery_bonus = 0.0
    success_bonus = 1.0

    # 1) Violations from trajectory step observations (best-effort).
    steps = trajectory.get("steps") or []
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            obs = step.get("observation") or {}
            results = obs.get("results") if isinstance(obs, dict) else None
            if not isinstance(results, list):
                continue
            for res in results:
                if not isinstance(res, dict):
                    continue
                content = res.get("content") or {}
                if not isinstance(content, dict):
                    continue
                for v in content.get("violations") or []:
                    if not isinstance(v, dict):
                        continue
                    sev = str(v.get("severity") or "warn").lower()
                    violation_penalty += 0.2 if sev in {"critical", "error"} else 0.1

    # 2) Plan mask reasons can be carried in trajectory.extra (best-effort).
    extra = trajectory.get("extra") if isinstance(trajectory, dict) else None
    if isinstance(extra, dict):
        mask_reasons = extra.get("mask_reasons") or []
        if isinstance(mask_reasons, list):
            mask_penalty += 0.05 * len([m for m in mask_reasons if m])

    # 3) Recovery bonus from branch/recovery events in trace.jsonl.
    for ev in trace_events:
        et = ev.get("event_type")
        if isinstance(et, str) and (
            et.startswith("branch_") or et.startswith("recovery_")
        ):
            recovery_bonus += 0.1
            break

        # New-format trace.jsonl uses AnalysisStreamEventV1 where legacy event types
        # may be carried in UnknownEvent.payload.raw_event_type.
        if et == "unknown":
            payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
            raw = payload.get("raw_event_type")
            if isinstance(raw, str) and (
                raw.startswith("branch_") or raw.startswith("recovery_")
            ):
                recovery_bonus += 0.1
                break

    total = success_bonus - violation_penalty - mask_penalty + recovery_bonus
    return {
        "schema_version": "reward-v1",
        "total": total,
        "components": {
            "success_bonus": success_bonus,
            "violation_penalty": violation_penalty,
            "mask_penalty": mask_penalty,
            "recovery_bonus": recovery_bonus,
        },
    }


def write_reward_breakdown(run_dir: Path) -> Path | None:
    """Compute and persist reward_breakdown.json next to trace/trajectory."""
    if not run_dir.exists():
        return None
    breakdown = compute_reward_breakdown_from_run_dir(run_dir)
    out = run_dir / "reward_breakdown.json"
    try:
        out.write_text(
            json.dumps(breakdown, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return out
    except Exception:
        return None


__all__ = ["compute_reward_breakdown_from_run_dir", "write_reward_breakdown"]
