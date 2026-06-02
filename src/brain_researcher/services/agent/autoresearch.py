"""Failure-attribution-first autoresearch helpers.

This module implements a bounded self-improvement loop for Brain Researcher:

1. Mine real MCP runs for recurring failure motifs.
2. Materialize bounded fix candidates in isolated git worktrees.
3. Validate candidates with touched-surface checks plus a small benchmark slice.

The v1 implementation deliberately keeps all decisions explicit and
machine-readable. It does not auto-merge or mutate the primary worktree.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover - import exercised in tests
    import yaml
except Exception:  # pragma: no cover
    yaml = None

from brain_researcher.config.run_artifacts import (
    get_mcp_run_root,
    get_repo_root,
    iter_mcp_run_dirs,
)
from brain_researcher.services.shared.loop_primitives import (
    DEFAULT_LOOP_PROFILE_ID,
    build_run_bundle_payload,
    build_run_scorecard,
)

REPO_ROOT = get_repo_root()
DEFAULT_AUTORESEARCH_ROOT = (REPO_ROOT / "data" / "autoresearch").resolve()
DEFAULT_BENCHMARK_ROOT = (REPO_ROOT.parent / "brain_researcher_benchmark").resolve()
DEFAULT_MOTIF_SLICE_PATH = (
    DEFAULT_BENCHMARK_ROOT / "configs" / "autoresearch" / "motif_slices.yaml"
)
DEFAULT_CANARY_SLICE_PATH = (
    DEFAULT_BENCHMARK_ROOT / "configs" / "autoresearch" / "canary_slice.yaml"
)
HARBOR_INDEX_PRIORITY = (
    "neuroimage-code-bench.harbor.json",
    "neuroimage-meta-analysis.harbor.json",
    "neuroimage-qa-bench.harbor.json",
    "neuroimage-theory-bench.harbor.json",
)
ACTIVE_RUN_STATES = frozenset({"running", "queued", "in_progress", "pending"})
PREVIEW_ONLY_MOTIFS = frozenset(
    {
        "preflight_contract_failure",
        "workflow_discoverability_mismatch",
        "tool_param_fill_failure",
    }
)
MOTIF_FAMILIES = (
    "preflight_contract_failure",
    "workflow_discoverability_mismatch",
    "tool_param_fill_failure",
    "runtime_stall_or_incomplete_bundle",
    "trace_or_bundle_corruption",
    "artifact_contract_miss",
    "step_skipped_without_useful_result",
    "tool_execution_failure",
    "wrong_tool_or_workflow_routing",
)

MOTIF_CANDIDATE_BLUEPRINTS: dict[str, list[dict[str, Any]]] = {
    "preflight_contract_failure": [
        {
            "target_surface": "mcp_preflight_contracts",
            "allowed_paths": [
                "src/brain_researcher/services/mcp/server.py",
                "src/brain_researcher/services/mcp/execution_recipes.py",
            ],
            "patch_rationale": (
                "Tighten preflight validation, required-parameter surfacing, and "
                "policy issue propagation before execution starts."
            ),
        },
        {
            "target_surface": "workflow_metadata_contracts",
            "allowed_paths": [
                "configs/workflows/workflow_catalog.yaml",
                "configs/grandmaster/toolset_vfinal.yaml",
                "src/brain_researcher/services/mcp/execution_recipes.py",
            ],
            "patch_rationale": (
                "Align workflow metadata and recipe discovery so invalid empty "
                "plans or missing-required-param paths are surfaced earlier."
            ),
        },
    ],
    "workflow_discoverability_mismatch": [
        {
            "target_surface": "workflow_registry_visibility",
            "allowed_paths": [
                "configs/workflows/workflow_catalog.yaml",
                "configs/grandmaster/toolset_vfinal.yaml",
                "src/brain_researcher/services/mcp/server.py",
                "src/brain_researcher/services/mcp/execution_recipes.py",
            ],
            "patch_rationale": (
                "Fix discoverability mismatches between catalog, registry, and "
                "recipe surfaces so valid workflows are consistently exposed."
            ),
        },
    ],
    "tool_param_fill_failure": [
        {
            "target_surface": "tool_schema_and_param_fill",
            "allowed_paths": [
                "src/brain_researcher/services/mcp/server.py",
                "src/brain_researcher/services/mcp/execution_recipes.py",
                "src/brain_researcher/cli/commands/agent_commands.py",
            ],
            "patch_rationale": (
                "Improve required-parameter inference and validation so the "
                "planner/CLI stop emitting under-specified tool calls."
            ),
        },
        {
            "target_surface": "workflow_required_param_contracts",
            "allowed_paths": [
                "configs/workflows/workflow_catalog.yaml",
                "src/brain_researcher/services/mcp/execution_recipes.py",
            ],
            "patch_rationale": (
                "Correct workflow metadata or recipe inference when parameter "
                "requirements are silently dropped."
            ),
        },
    ],
    "runtime_stall_or_incomplete_bundle": [
        {
            "target_surface": "run_bundle_persistence",
            "allowed_paths": [
                "src/brain_researcher/services/mcp/server.py",
                "src/brain_researcher/services/mcp/loop_primitives.py",
                "src/brain_researcher/services/agent/run_bundle.py",
            ],
            "patch_rationale": (
                "Harden run-bundle persistence and terminalization so stuck or "
                "half-written runs resolve into complete observation bundles."
            ),
        },
    ],
    "trace_or_bundle_corruption": [
        {
            "target_surface": "trace_bundle_integrity",
            "allowed_paths": [
                "src/brain_researcher/services/mcp/server.py",
                "src/brain_researcher/services/mcp/loop_primitives.py",
                "src/brain_researcher/services/agent/run_bundle.py",
            ],
            "patch_rationale": (
                "Fix corrupted trace/bundle writes and unreadable JSON payloads "
                "so loop analysis has reliable persisted evidence."
            ),
        },
    ],
    "artifact_contract_miss": [
        {
            "target_surface": "artifact_contract_persistence",
            "allowed_paths": [
                "src/brain_researcher/services/mcp/server.py",
                "src/brain_researcher/services/mcp/loop_primitives.py",
                "src/brain_researcher/core/artifact_validator.py",
            ],
            "patch_rationale": (
                "Make artifact recording and completeness checks reflect the real "
                "contract so successful runs do not silently miss required files."
            ),
        },
    ],
    "step_skipped_without_useful_result": [
        {
            "target_surface": "skip_reason_contract",
            "allowed_paths": [
                "src/brain_researcher/services/mcp/server.py",
                "src/brain_researcher/services/mcp/loop_primitives.py",
            ],
            "patch_rationale": (
                "Require skipped steps to carry an actionable reason and useful "
                "result payload instead of silently producing no output."
            ),
        },
    ],
    "tool_execution_failure": [
        {
            "target_surface": "tool_executor_recovery",
            "allowed_paths": [
                "src/brain_researcher/services/agent/tool_executor.py",
                "src/brain_researcher/services/tools/runner.py",
                "src/brain_researcher/services/mcp/server.py",
            ],
            "patch_rationale": (
                "Tighten tool execution, timeout/error propagation, and recovery "
                "surface so hard tool failures become actionable and testable."
            ),
        },
    ],
    "wrong_tool_or_workflow_routing": [
        {
            "target_surface": "planner_routing_contracts",
            "allowed_paths": [
                "src/brain_researcher/services/agent/tool_router.py",
                "src/brain_researcher/services/agent/tool_retriever.py",
                "src/brain_researcher/services/mcp/server.py",
                "src/brain_researcher/services/mcp/execution_recipes.py",
            ],
            "patch_rationale": (
                "Correct tool/workflow routing and selection metadata when the "
                "system chooses the wrong execution surface."
            ),
        },
    ],
}

MOTIF_LOCAL_CHECKS: dict[str, list[str]] = {
    "preflight_contract_failure": [
        "pytest -q tests/unit/mcp/test_local_mcp_server.py tests/unit/mcp/test_workflow_resolution.py tests/cli/test_agent_commands.py"
    ],
    "workflow_discoverability_mismatch": [
        "pytest -q tests/unit/mcp/test_workflow_resolution.py tests/unit/tools/test_catalog_loader.py tests/cli/test_agent_commands.py"
    ],
    "tool_param_fill_failure": [
        "pytest -q tests/unit/mcp/test_local_mcp_server.py tests/cli/test_agent_commands.py"
    ],
    "runtime_stall_or_incomplete_bundle": [
        "pytest -q tests/unit/mcp/test_local_mcp_server.py tests/unit/agent/test_act_run_bundle.py tests/unit/agent/test_chat_stream_run_bundle.py"
    ],
    "trace_or_bundle_corruption": [
        "pytest -q tests/unit/mcp/test_local_mcp_server.py tests/unit/agent/test_act_run_bundle.py"
    ],
    "artifact_contract_miss": [
        "pytest -q tests/unit/mcp/test_local_mcp_server.py tests/unit/agent/test_act_run_bundle.py"
    ],
    "step_skipped_without_useful_result": [
        "pytest -q tests/unit/mcp/test_local_mcp_server.py tests/unit/agent/test_act_run_bundle.py"
    ],
    "tool_execution_failure": [
        "pytest -q tests/unit/agent/test_tool_executor_execution_policy.py tests/unit/mcp/test_local_mcp_server.py"
    ],
    "wrong_tool_or_workflow_routing": [
        "pytest -q tests/unit/mcp/test_workflow_resolution.py tests/cli/test_agent_commands.py"
    ],
}

_TEMP_MARKER_RE = re.compile(r"\b(TODO|FIXME|XXX|HACK|TEMP)\b", re.IGNORECASE)
_DEBUG_MARKER_RE = re.compile(
    r"(print\s*\(|console\.log\s*\(|breakpoint\s*\(|pdb\.set_trace\s*\()"
)


@dataclass
class ObservedRun:
    """Normalized MCP run evidence used for deterministic failure mining."""

    run_id: str
    run_dir: str
    status: str
    dry_run: bool
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    tool_ids: list[str] = field(default_factory=list)
    step_statuses: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    violation_codes: list[str] = field(default_factory=list)
    violation_messages: list[str] = field(default_factory=list)
    artifact_completeness_ratio: float | None = None
    policy_issue_count: int = 0
    scorecard: dict[str, Any] = field(default_factory=dict)
    bundle: dict[str, Any] = field(default_factory=dict)


@dataclass
class FailureObservation:
    """One motif hit extracted from one observed run."""

    motif_family: str
    run_id: str
    severity: str
    tool_ids: list[str] = field(default_factory=list)
    evidence_snippets: list[str] = field(default_factory=list)
    suspected_surface: str | None = None


@dataclass
class FailureMotifCard:
    """Aggregated recurring failure motif."""

    motif_id: str
    motif_family: str
    severity: str
    frequency: int
    affected_tools_workflows: list[str]
    representative_runs: list[str]
    evidence_snippets: list[str]
    suspected_surface: str
    suggested_fix_surfaces: list[str]
    recommended_benchmark_slice_id: str
    source_corpus_summary: dict[str, Any]


@dataclass
class FixCandidate:
    """Persisted bounded fix candidate bound to a failure motif."""

    candidate_id: str
    motif_id: str
    motif_family: str
    target_surface: str
    allowed_paths: list[str]
    worktree_path: str
    patch_rationale: str
    validation_slice_id: str
    local_check_commands: list[str]
    created_at: str
    status: str = "created"


@dataclass
class BenchmarkTaskAssessment:
    """Normalized task-level comparison input."""

    task_id: str
    final_status: str
    score: float
    blocker: bool
    motif_present: bool


@dataclass
class ValidationReport:
    """Result of validating one fix candidate."""

    candidate_id: str
    motif_id: str
    motif_family: str
    baseline_summary: dict[str, Any]
    candidate_summary: dict[str, Any]
    gate_verdict: str
    larger_benchmark_eligible: bool
    regressions: list[str] = field(default_factory=list)
    fixed_failures: list[str] = field(default_factory=list)
    local_checks: dict[str, Any] = field(default_factory=dict)
    touched_paths: list[str] = field(default_factory=list)
    patch_legibility: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    status_explanation: str | None = None
    recommended_action: str | None = None


def get_autoresearch_root(root: Path | str | None = None) -> Path:
    """Return the root directory used for autoresearch state."""

    if root is not None:
        return Path(root).expanduser().resolve()
    raw = os.getenv("BR_AUTORESEARCH_ROOT")
    if raw:
        return Path(raw).expanduser().resolve()
    return DEFAULT_AUTORESEARCH_ROOT


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _failure_motif_dir(root: Path) -> Path:
    return _ensure_dir(root / "failure_motifs")


def _candidate_dir(root: Path, candidate_id: str) -> Path:
    return _ensure_dir(root / "candidates" / candidate_id)


def _validation_dir(root: Path, candidate_id: str) -> Path:
    return _ensure_dir(root / "validations" / candidate_id)


def _worktrees_dir(root: Path) -> Path:
    return _ensure_dir(root / "worktrees")


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso() -> str:
    return _utc_now().isoformat()


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    candidate = str(ts).strip()
    if not candidate:
        return None
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=False, default=_json_default),
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, default=_json_default))
            handle.write("\n")


def _normalize_step_from_observation(step: dict[str, Any]) -> dict[str, Any]:
    return {
        "step_id": step.get("tool_call_id") or step.get("step_id") or step.get("id"),
        "tool_id": step.get("name") or step.get("tool_id") or step.get("tool"),
        "status": step.get("status") or step.get("state"),
        "started_at": step.get("started_at"),
        "finished_at": step.get("finished_at"),
        "policy_issues": [],
        "error": step.get("error"),
        "result_path": step.get("result_path"),
    }


def _normalize_step_from_run_json(step: dict[str, Any]) -> dict[str, Any]:
    return {
        "step_id": step.get("step_id") or step.get("id"),
        "tool_id": step.get("tool_id") or step.get("tool") or step.get("name"),
        "status": step.get("status") or step.get("state"),
        "started_at": step.get("started_at"),
        "finished_at": step.get("finished_at"),
        "policy_issues": list(step.get("policy_issues") or []),
        "error": step.get("error"),
        "result_path": step.get("result_path"),
    }


def _normalize_record_for_loop_primitives(
    run_json: dict[str, Any],
    observation: dict[str, Any] | None,
) -> dict[str, Any]:
    if observation is not None:
        raw_steps = observation.get("steps")
        steps = raw_steps if isinstance(raw_steps, list) else []
        return {
            "run_id": run_json.get("run_id") or observation.get("run_id"),
            "status": observation.get("state")
            or observation.get("status")
            or run_json.get("status")
            or "unknown",
            "started_at": observation.get("started_at") or run_json.get("started_at"),
            "finished_at": observation.get("finished_at")
            or run_json.get("finished_at"),
            "error": run_json.get("error") or observation.get("error"),
            "steps": [
                _normalize_step_from_observation(step)
                for step in steps
                if isinstance(step, dict)
            ],
        }
    raw_steps = run_json.get("steps")
    steps = raw_steps if isinstance(raw_steps, list) else []
    return {
        "run_id": run_json.get("run_id"),
        "status": run_json.get("status") or "unknown",
        "started_at": run_json.get("started_at"),
        "finished_at": run_json.get("finished_at"),
        "error": run_json.get("error"),
        "steps": [
            _normalize_step_from_run_json(step)
            for step in steps
            if isinstance(step, dict)
        ],
    }


def _load_step_payload(run_dir: Path, result_path: str | None) -> dict[str, Any]:
    if not result_path:
        return {}
    candidate = (run_dir / result_path).resolve()
    if not candidate.exists():
        return {}
    return _read_json(candidate) or {}


def _build_local_metrics(record: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    totals = {
        "steps": len(record.get("steps") or []),
        "succeeded": 0,
        "failed": 0,
        "skipped": 0,
        "execution_time_s_sum": 0.0,
        "tokens_sum": 0,
        "cost_usd_sum": 0.0,
    }
    for step in record.get("steps") or []:
        if not isinstance(step, dict):
            continue
        status = step.get("status")
        if status == "succeeded":
            totals["succeeded"] += 1
        elif status == "failed":
            totals["failed"] += 1
        elif status == "skipped":
            totals["skipped"] += 1

        payload = _load_step_payload(run_dir, step.get("result_path"))
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        metadata = (
            payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        )
        execution_time = None
        for key in (
            "execution_time",
            "execution_time_s",
            "execution_time_seconds",
            "runtime_s",
        ):
            if key in data:
                execution_time = data[key]
                break
            if key in metadata:
                execution_time = metadata[key]
                break
        if isinstance(execution_time, (int, float)):
            totals["execution_time_s_sum"] += float(execution_time)

        tokens = metadata.get("tokens") or metadata.get("total_tokens")
        if tokens is None:
            input_tokens = metadata.get("input_tokens")
            output_tokens = metadata.get("output_tokens")
            if isinstance(input_tokens, (int, float)) or isinstance(
                output_tokens, (int, float)
            ):
                tokens = int(input_tokens or 0) + int(output_tokens or 0)
        if isinstance(tokens, (int, float)):
            totals["tokens_sum"] += int(tokens)

        cost = metadata.get("cost_usd") or metadata.get("estimated_usd")
        if isinstance(cost, (int, float)):
            totals["cost_usd_sum"] += float(cost)

    started = _parse_iso(record.get("started_at"))
    finished = _parse_iso(record.get("finished_at"))
    duration_s = (
        (finished - started).total_seconds()
        if started is not None and finished is not None
        else None
    )
    return {
        "run_id": record.get("run_id"),
        "status": record.get("status"),
        "started_at": record.get("started_at"),
        "finished_at": record.get("finished_at"),
        "duration_s": duration_s,
        "totals": totals,
    }


def _extract_observation_violations(
    observation: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(observation, dict):
        return []
    raw = observation.get("violations")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def load_observed_run(
    run_dir: Path,
    *,
    profile_id: str = DEFAULT_LOOP_PROFILE_ID,
) -> ObservedRun | None:
    """Load one MCP run directory into a normalized observation."""

    run_json = _read_json(run_dir / "run.json")
    if run_json is None:
        return None
    observation = _read_json(run_dir / "observation.json")
    record = _normalize_record_for_loop_primitives(run_json, observation)
    bundle, bundle_warnings = build_run_bundle_payload(
        str(run_json.get("run_id") or run_dir.name),
        record=record,
        run_dir=run_dir,
    )
    metrics = _build_local_metrics(record, run_dir)
    scorecard = build_run_scorecard(
        str(run_json.get("run_id") or run_dir.name),
        profile_id=profile_id,
        record=record,
        run_dir=run_dir,
        metrics=metrics,
        bundle_payload=bundle,
        bundle_warnings=bundle_warnings,
    )
    violations = _extract_observation_violations(observation)
    violation_codes = [
        str(item.get("code") or "").strip()
        for item in violations
        if str(item.get("code") or "").strip()
    ]
    violation_messages = [
        str(item.get("message") or "").strip()
        for item in violations
        if str(item.get("message") or "").strip()
    ]
    steps = record.get("steps") if isinstance(record.get("steps"), list) else []
    tool_ids = [
        str(step.get("tool_id") or "").strip()
        for step in steps
        if str(step.get("tool_id") or "").strip()
    ]
    step_statuses = [
        str(step.get("status") or "").strip()
        for step in steps
        if str(step.get("status") or "").strip()
    ]
    errors = [
        str(item).strip()
        for item in list(scorecard.get("errors") or [])
        if str(item).strip()
    ]
    warnings = [
        str(item).strip()
        for item in list(scorecard.get("warnings") or [])
        if str(item).strip()
    ]
    artifact_ratio = None
    summary_metrics = scorecard.get("summary_metrics")
    if isinstance(summary_metrics, dict):
        value = summary_metrics.get("artifact_completeness_ratio")
        if isinstance(value, (int, float)):
            artifact_ratio = float(value)
    return ObservedRun(
        run_id=str(run_json.get("run_id") or run_dir.name),
        run_dir=str(run_dir),
        status=str(record.get("status") or "unknown"),
        dry_run=bool(run_json.get("dry_run")),
        created_at=run_json.get("created_at"),
        started_at=record.get("started_at"),
        finished_at=record.get("finished_at"),
        tool_ids=tool_ids,
        step_statuses=step_statuses,
        errors=errors,
        warnings=warnings,
        violation_codes=violation_codes,
        violation_messages=violation_messages,
        artifact_completeness_ratio=artifact_ratio,
        policy_issue_count=int(
            ((scorecard.get("policy") or {}).get("issue_count")) or 0
        ),
        scorecard=scorecard,
        bundle=bundle,
    )


def _all_text(observed: ObservedRun) -> str:
    parts: list[str] = []
    parts.extend(observed.errors)
    parts.extend(observed.warnings)
    parts.extend(observed.violation_codes)
    parts.extend(observed.violation_messages)
    parts.extend(observed.tool_ids)
    return "\n".join(part.lower() for part in parts if part)


def _snippets(observed: ObservedRun, *, limit: int = 4) -> list[str]:
    snippets: list[str] = []
    for item in (
        list(observed.violation_messages)
        + list(observed.errors)
        + list(observed.warnings)
    ):
        text = str(item).strip()
        if not text:
            continue
        if text not in snippets:
            snippets.append(text)
        if len(snippets) >= limit:
            break
    return snippets


def detect_failure_observations(observed: ObservedRun) -> list[FailureObservation]:
    """Deterministically classify one observed run into failure motifs."""

    text = _all_text(observed)
    snippets = _snippets(observed)
    findings: list[FailureObservation] = []

    def add(motif_family: str, *, severity: str = "medium") -> None:
        if observed.dry_run and motif_family not in PREVIEW_ONLY_MOTIFS:
            return
        if any(item.motif_family == motif_family for item in findings):
            return
        blueprints = MOTIF_CANDIDATE_BLUEPRINTS.get(motif_family) or []
        suspected_surface = (
            str(blueprints[0].get("target_surface"))
            if blueprints
            else "unknown_surface"
        )
        findings.append(
            FailureObservation(
                motif_family=motif_family,
                run_id=observed.run_id,
                severity=severity,
                tool_ids=list(observed.tool_ids),
                evidence_snippets=list(snippets),
                suspected_surface=suspected_surface,
            )
        )

    violation_codes = set(code.lower() for code in observed.violation_codes)
    if (
        "params_missing_required" in violation_codes
        or "validation_error" in text
        or "plan_invalid" in text
    ):
        add("preflight_contract_failure", severity="high")

    if (
        "params_missing_required" in violation_codes
        or "missing required" in text
        or "required params" in text
        or "validation error" in text
        or "value error" in text
        or "type error" in text
    ):
        add("tool_param_fill_failure", severity="high")

    if (
        ("workflow" in text and "not found" in text)
        or ("workflow" in text and "discover" in text)
        or ("workflow" in text and "allowlisted" in text)
        or ("tool_search" in text and "workflow" in text)
    ):
        add("workflow_discoverability_mismatch", severity="medium")

    if (
        observed.status in ACTIVE_RUN_STATES
        or any(status in ACTIVE_RUN_STATES for status in observed.step_statuses)
        or (
            isinstance(observed.artifact_completeness_ratio, float)
            and observed.artifact_completeness_ratio < 1.0
            and observed.status not in {"succeeded", "failed", "cancelled"}
        )
    ):
        add("runtime_stall_or_incomplete_bundle", severity="high")

    if (
        "jsondecodeerror" in text
        or "unreadable" in text
        or "corrupt" in text
        or "trace_jsonl" in text
        and "missing from persisted run bundle" in text
    ):
        add("trace_or_bundle_corruption", severity="high")

    if (
        observed.status == "succeeded"
        and isinstance(observed.artifact_completeness_ratio, float)
        and observed.artifact_completeness_ratio < 1.0
    ):
        add("artifact_contract_miss", severity="medium")

    if any(status == "skipped" for status in observed.step_statuses):
        if observed.dry_run or not observed.errors:
            add("step_skipped_without_useful_result", severity="medium")

    if any(status == "failed" for status in observed.step_statuses) or (
        observed.status == "failed"
        and "plan_invalid" not in text
        and "missing required" not in text
    ):
        add("tool_execution_failure", severity="medium")

    if (
        "tool_not_allowlisted" in text
        or "wrong tool" in text
        or "no suitable tool" in text
        or ("routing" in text and "tool" in text)
    ):
        add("wrong_tool_or_workflow_routing", severity="medium")

    return findings


def _run_timestamp(observed: ObservedRun) -> datetime | None:
    for value in (observed.finished_at, observed.started_at, observed.created_at):
        parsed = _parse_iso(value)
        if parsed is not None:
            return parsed
    return None


def collect_observed_runs(
    *,
    limit: int = 200,
    days: int = 14,
    profile_id: str = DEFAULT_LOOP_PROFILE_ID,
    run_root: Path | str | None = None,
) -> list[ObservedRun]:
    """Collect recent MCP runs for failure mining."""

    root = Path(run_root) if run_root is not None else get_mcp_run_root()
    cutoff = _utc_now() - timedelta(days=days)
    collected: list[ObservedRun] = []
    for run_dir in sorted(
        iter_mcp_run_dirs(root), key=lambda p: p.stat().st_mtime, reverse=True
    ):
        observed = load_observed_run(run_dir, profile_id=profile_id)
        if observed is None:
            continue
        ts = _run_timestamp(observed)
        if ts is not None and ts < cutoff:
            continue
        if observed.dry_run:
            collected.append(observed)
            continue
        # Prioritize completed runs, but keep stale active runs because they are
        # informative for incomplete-bundle motifs.
        if observed.status in ACTIVE_RUN_STATES:
            age = _utc_now() - datetime.fromtimestamp(
                run_dir.stat().st_mtime, tz=timezone.utc
            )
            if age < timedelta(minutes=10):
                continue
        collected.append(observed)
        if len([run for run in collected if not run.dry_run]) >= limit:
            break
    return collected


def mine_failure_motifs(
    *,
    limit: int = 200,
    days: int = 14,
    profile_id: str = DEFAULT_LOOP_PROFILE_ID,
    autoresearch_root: Path | str | None = None,
    run_root: Path | str | None = None,
) -> list[FailureMotifCard]:
    """Mine recurring failure motifs from recent MCP runs and persist them."""

    state_root = get_autoresearch_root(autoresearch_root)
    observed_runs = collect_observed_runs(
        limit=limit,
        days=days,
        profile_id=profile_id,
        run_root=run_root,
    )
    grouped: dict[str, list[FailureObservation]] = defaultdict(list)
    counts = {"total_runs": len(observed_runs), "real_runs": 0, "dry_runs": 0}
    for observed in observed_runs:
        if observed.dry_run:
            counts["dry_runs"] += 1
        else:
            counts["real_runs"] += 1
        for finding in detect_failure_observations(observed):
            grouped[finding.motif_family].append(finding)

    cards: list[FailureMotifCard] = []
    severity_rank = {"high": 2, "medium": 1, "low": 0}
    for motif_family in MOTIF_FAMILIES:
        findings = grouped.get(motif_family) or []
        if not findings:
            continue
        tool_counter: Counter[str] = Counter()
        run_ids: list[str] = []
        snippets: list[str] = []
        surfaces: list[str] = []
        severities: list[str] = []
        for finding in findings:
            run_ids.append(finding.run_id)
            severities.append(finding.severity)
            if finding.suspected_surface:
                surfaces.append(finding.suspected_surface)
            for tool_id in finding.tool_ids:
                tool_counter[tool_id] += 1
            for snippet in finding.evidence_snippets:
                if snippet not in snippets:
                    snippets.append(snippet)
        dominant_surface = surfaces[0] if surfaces else "unknown_surface"
        highest_severity = max(severities, key=lambda item: severity_rank.get(item, 0))
        blueprints = MOTIF_CANDIDATE_BLUEPRINTS.get(motif_family) or []
        cards.append(
            FailureMotifCard(
                motif_id=motif_family,
                motif_family=motif_family,
                severity=highest_severity,
                frequency=len(findings),
                affected_tools_workflows=[
                    name for name, _ in tool_counter.most_common(8)
                ],
                representative_runs=run_ids[:8],
                evidence_snippets=snippets[:8],
                suspected_surface=dominant_surface,
                suggested_fix_surfaces=[
                    str(item.get("target_surface"))
                    for item in blueprints
                    if str(item.get("target_surface") or "").strip()
                ],
                recommended_benchmark_slice_id=motif_family,
                source_corpus_summary={
                    **counts,
                    "window_days": days,
                    "run_limit": limit,
                    "profile_id": profile_id,
                },
            )
        )

    cards.sort(key=lambda item: (-item.frequency, item.motif_family))
    motif_dir = _failure_motif_dir(state_root)
    timestamp = _utc_now().strftime("%Y%m%d_%H%M%S")
    timestamped = motif_dir / f"failure_motifs_{timestamp}.jsonl"
    latest = motif_dir / "failure_motifs_latest.jsonl"
    rows = [asdict(card) for card in cards]
    _write_jsonl(timestamped, rows)
    _write_jsonl(latest, rows)
    return cards


def load_failure_motifs(
    *,
    autoresearch_root: Path | str | None = None,
    path: Path | str | None = None,
) -> list[FailureMotifCard]:
    """Load persisted failure motifs from the latest or a specific path."""

    if path is None:
        path = (
            _failure_motif_dir(get_autoresearch_root(autoresearch_root))
            / "failure_motifs_latest.jsonl"
        )
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Failure motifs file not found: {source}")
    cards: list[FailureMotifCard] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        payload = json.loads(text)
        cards.append(FailureMotifCard(**payload))
    return cards


def _git(*args: str, cwd: Path | str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def _materialize_worktree(
    candidate_id: str,
    *,
    repo_root: Path = REPO_ROOT,
    autoresearch_root: Path,
) -> Path:
    worktree_path = _worktrees_dir(autoresearch_root) / candidate_id
    if worktree_path.exists():
        return worktree_path
    result = _git(
        "worktree", "add", "--detach", str(worktree_path), "HEAD", cwd=repo_root
    )
    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip() or result.stdout.strip() or "git worktree add failed"
        )
    return worktree_path


def _write_fix_brief(
    worktree_path: Path,
    *,
    motif: FailureMotifCard,
    blueprint: dict[str, Any],
    candidate: FixCandidate,
) -> None:
    allowlist_block = "\n".join(f"- `{item}`" for item in candidate.allowed_paths)
    snippet_block = (
        "\n".join(f"- {item}" for item in motif.evidence_snippets[:6]) or "- none"
    )
    brief = (
        f"# Fix Candidate {candidate.candidate_id}\n\n"
        f"Motif: `{motif.motif_id}`\n"
        f"Target surface: `{candidate.target_surface}`\n\n"
        f"Patch rationale:\n{candidate.patch_rationale}\n\n"
        f"Allowed paths:\n{allowlist_block}\n\n"
        f"Representative evidence:\n{snippet_block}\n\n"
        "Constraints:\n"
        "- Edit only the allowed paths.\n"
        "- Keep changes bounded to this failure motif.\n"
        "- Validation uses a fail-fast regression gate on motif slice + canary.\n"
    )
    (worktree_path / "fix_brief.md").write_text(brief, encoding="utf-8")


def propose_fix_candidates(
    motif_id: str,
    *,
    max_candidates: int = 3,
    autoresearch_root: Path | str | None = None,
    motifs_path: Path | str | None = None,
) -> list[FixCandidate]:
    """Create bounded fix candidates for one persisted failure motif."""

    state_root = get_autoresearch_root(autoresearch_root)
    cards = load_failure_motifs(autoresearch_root=state_root, path=motifs_path)
    motif = next((card for card in cards if card.motif_id == motif_id), None)
    if motif is None:
        raise ValueError(f"Unknown motif_id: {motif_id}")
    blueprints = list(MOTIF_CANDIDATE_BLUEPRINTS.get(motif.motif_family) or [])
    if not blueprints:
        raise ValueError(
            f"No candidate blueprint registered for motif: {motif.motif_family}"
        )

    created: list[FixCandidate] = []
    timestamp = _utc_now().strftime("%Y%m%d_%H%M%S")
    for idx, blueprint in enumerate(blueprints[:max_candidates], start=1):
        candidate_id = f"{motif.motif_family}_{timestamp}_{idx:02d}"
        worktree_path = _materialize_worktree(
            candidate_id,
            repo_root=REPO_ROOT,
            autoresearch_root=state_root,
        )
        local_checks = list(MOTIF_LOCAL_CHECKS.get(motif.motif_family) or [])
        candidate = FixCandidate(
            candidate_id=candidate_id,
            motif_id=motif.motif_id,
            motif_family=motif.motif_family,
            target_surface=str(blueprint.get("target_surface") or "unknown_surface"),
            allowed_paths=[
                str(item) for item in list(blueprint.get("allowed_paths") or [])
            ],
            worktree_path=str(worktree_path),
            patch_rationale=str(blueprint.get("patch_rationale") or "").strip(),
            validation_slice_id=motif.recommended_benchmark_slice_id,
            local_check_commands=local_checks,
            created_at=_utc_iso(),
        )
        candidate_root = _candidate_dir(state_root, candidate_id)
        _write_json(candidate_root / "candidate_fix.json", asdict(candidate))
        _write_fix_brief(
            worktree_path, motif=motif, blueprint=blueprint, candidate=candidate
        )
        created.append(candidate)
    return created


def load_fix_candidate(
    candidate_id: str,
    *,
    autoresearch_root: Path | str | None = None,
) -> FixCandidate:
    """Load a persisted fix candidate by identifier."""

    state_root = get_autoresearch_root(autoresearch_root)
    path = _candidate_dir(state_root, candidate_id) / "candidate_fix.json"
    payload = _read_json(path)
    if payload is None:
        raise FileNotFoundError(f"Candidate manifest not found: {path}")
    return FixCandidate(**payload)


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _is_allowed_path(path_str: str, allowed_paths: list[str]) -> bool:
    candidate = Path(path_str)
    for item in allowed_paths:
        allowed = Path(item)
        if candidate == allowed:
            return True
        try:
            candidate.relative_to(allowed)
            return True
        except ValueError:
            continue
    return False


def _load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load benchmark slice configs")
    if not path.exists():
        raise FileNotFoundError(path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Expected mapping at {path}")
    return payload


def load_motif_slice_config(
    motif_family: str,
    *,
    benchmark_root: Path | str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    """Return the raw benchmark slice config entry for one failure motif."""

    root = (
        Path(benchmark_root) if benchmark_root is not None else DEFAULT_BENCHMARK_ROOT
    )
    config_path = (
        Path(path)
        if path is not None
        else root / "configs" / "autoresearch" / "motif_slices.yaml"
    )
    payload = _load_yaml(config_path)
    motifs = payload.get("motifs")
    if not isinstance(motifs, dict):
        raise ValueError(f"Invalid motif config: {config_path}")
    entry = motifs.get(motif_family)
    if not isinstance(entry, dict):
        raise KeyError(f"No benchmark slice registered for motif: {motif_family}")
    return entry


def load_motif_slice_task_ids(
    motif_family: str,
    *,
    benchmark_root: Path | str | None = None,
    path: Path | str | None = None,
) -> list[str]:
    """Return benchmark task IDs associated with one failure motif."""

    entry = load_motif_slice_config(
        motif_family,
        benchmark_root=benchmark_root,
        path=path,
    )
    task_ids = entry.get("task_ids")
    if not isinstance(task_ids, list):
        raise ValueError(f"motif slice task_ids must be a list for {motif_family}")
    return [str(item).strip() for item in task_ids if str(item).strip()]


def load_motif_canary_task_ids(
    motif_family: str,
    *,
    benchmark_root: Path | str | None = None,
    path: Path | str | None = None,
) -> list[str]:
    """Return optional motif-specific canary task IDs."""

    entry = load_motif_slice_config(
        motif_family,
        benchmark_root=benchmark_root,
        path=path,
    )
    task_ids = entry.get("canary_task_ids")
    if task_ids is None:
        return []
    if not isinstance(task_ids, list):
        raise ValueError(f"motif canary_task_ids must be a list for {motif_family}")
    return [str(item).strip() for item in task_ids if str(item).strip()]


def load_motif_scaffold_task_ids(
    motif_family: str,
    *,
    benchmark_root: Path | str | None = None,
    path: Path | str | None = None,
) -> list[str]:
    """Return optional motif-specific draft HARNESS task IDs."""

    entry = load_motif_slice_config(
        motif_family,
        benchmark_root=benchmark_root,
        path=path,
    )
    task_ids = entry.get("scaffold_task_ids")
    if task_ids is None:
        return []
    if not isinstance(task_ids, list):
        raise ValueError(f"motif scaffold_task_ids must be a list for {motif_family}")
    return [str(item).strip() for item in task_ids if str(item).strip()]


def load_canary_task_ids(
    *,
    benchmark_root: Path | str | None = None,
    path: Path | str | None = None,
) -> list[str]:
    """Return the fixed canary benchmark slice."""

    root = (
        Path(benchmark_root) if benchmark_root is not None else DEFAULT_BENCHMARK_ROOT
    )
    config_path = (
        Path(path)
        if path is not None
        else root / "configs" / "autoresearch" / "canary_slice.yaml"
    )
    payload = _load_yaml(config_path)
    task_ids = payload.get("task_ids")
    if not isinstance(task_ids, list):
        raise ValueError(f"canary task_ids must be a list in {config_path}")
    return [str(item).strip() for item in task_ids if str(item).strip()]


def load_canary_scaffold_task_ids(
    *,
    benchmark_root: Path | str | None = None,
    path: Path | str | None = None,
) -> list[str]:
    """Return optional draft HARNESS task IDs from the global canary config."""

    root = (
        Path(benchmark_root) if benchmark_root is not None else DEFAULT_BENCHMARK_ROOT
    )
    config_path = (
        Path(path)
        if path is not None
        else root / "configs" / "autoresearch" / "canary_slice.yaml"
    )
    payload = _load_yaml(config_path)
    task_ids = payload.get("scaffold_task_ids")
    if task_ids is None:
        return []
    if not isinstance(task_ids, list):
        raise ValueError(f"canary scaffold_task_ids must be a list in {config_path}")
    return [str(item).strip() for item in task_ids if str(item).strip()]


def _is_native_harness_task(task_id: str) -> bool:
    return str(task_id).strip().upper().startswith("HARNESS-")


def _load_harbor_task_definition(
    benchmark_root: Path,
    task_id: str,
) -> dict[str, Any] | None:
    harbor_root = benchmark_root / "harbor_json"
    for filename in HARBOR_INDEX_PRIORITY:
        path = harbor_root / filename
        payload = _read_json(path)
        tasks = payload.get("tasks") if isinstance(payload, dict) else None
        if not isinstance(tasks, list):
            continue
        for task in tasks:
            if not isinstance(task, dict):
                continue
            if str(task.get("id") or "").strip() == task_id:
                return task
    return None


def _harbor_required_outputs(
    benchmark_root: Path,
    task_id: str,
) -> list[str]:
    definition = _load_harbor_task_definition(benchmark_root, task_id)
    if not isinstance(definition, dict):
        return []
    input_block = definition.get("input")
    if isinstance(input_block, dict):
        required_outputs = input_block.get("required_outputs")
        if isinstance(required_outputs, list):
            return [str(item).strip() for item in required_outputs if str(item).strip()]
    expected_outputs = definition.get("expected_outputs")
    if isinstance(expected_outputs, list):
        for item in expected_outputs:
            if not isinstance(item, dict):
                continue
            required_outputs = item.get("required_outputs")
            if isinstance(required_outputs, list):
                return [
                    str(value).strip()
                    for value in required_outputs
                    if str(value).strip()
                ]
    return []


def _run_native_harness_slice(
    *,
    benchmark_root: Path,
    task_ids: list[str],
    python_repo: Path,
    candidate_label: str,
    timeout_s: int,
    candidate_id: str,
    slice_name: str,
) -> dict[str, Any]:
    workdir_base = (
        get_autoresearch_root()
        / "benchmark_workdirs"
        / candidate_id
        / candidate_label
        / slice_name
    )
    python_bin = shutil.which("python") or "python"
    results: list[dict[str, Any]] = []

    for task_id in task_ids:
        task_root = benchmark_root / "harbor" / task_id
        solve_sh = task_root / "solution" / "solve.sh"
        verifier = task_root / "tests" / "test_outputs.py"
        if not solve_sh.exists():
            raise FileNotFoundError(
                f"Native harness solve.sh missing for {task_id}: {solve_sh}"
            )
        if not verifier.exists():
            raise FileNotFoundError(
                f"Native harness verifier missing for {task_id}: {verifier}"
            )

        attempt_root = workdir_base / task_id / "attempt_1"
        if attempt_root.exists():
            shutil.rmtree(attempt_root)
        output_dir = attempt_root / "data"
        output_dir.mkdir(parents=True, exist_ok=True)

        env = {
            **os.environ,
            "BRAINR_PYTHON_REPO": str(python_repo),
            "BRAIN_RESEARCHER_REPO": str(python_repo),
            "OUTPUT_DIR": str(output_dir),
            "CACHE_DIR": str(output_dir / "_cache"),
        }

        start = _utc_now()
        solve_proc = subprocess.run(
            ["bash", str(solve_sh.resolve())],
            cwd=str(benchmark_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        solve_stdout = solve_proc.stdout or ""
        solve_stderr = solve_proc.stderr or ""

        verifier_proc = subprocess.run(
            [python_bin, "-m", "pytest", "-q", str(verifier.resolve())],
            cwd=str(benchmark_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=min(timeout_s, 300),
            check=False,
        )
        end = _utc_now()

        verifier_stdout = verifier_proc.stdout or ""
        verifier_stderr = verifier_proc.stderr or ""
        required_outputs = _harbor_required_outputs(benchmark_root, task_id)
        evidence_found: list[str] = []
        evidence_missing: list[str] = []
        for relpath in required_outputs:
            if (output_dir / relpath).exists():
                evidence_found.append(relpath)
            else:
                evidence_missing.append(relpath)

        run_summary = _read_json(output_dir / "run_summary.json") or {}
        run_metadata = _read_json(output_dir / "run_metadata.json") or {}
        observation = _read_json(output_dir / "observation.json") or {}
        analysis_bundle = _read_json(output_dir / "analysis_bundle.json") or {}
        trajectory = _read_json(output_dir / "trajectory.json") or {}

        metrics_met: list[str] = []
        metrics_failed: list[str] = []
        if bool(run_summary.get("terminal")):
            metrics_met.append("run_terminal")
        else:
            metrics_failed.append("run_terminal")
        if all(
            bool(run_summary.get(key))
            for key in (
                "has_trace",
                "has_observation",
                "has_trajectory",
                "has_analysis_bundle",
            )
        ):
            metrics_met.append("bundle_persisted")
        else:
            metrics_failed.append("bundle_persisted")
        if (output_dir / "input_manifest.csv").exists():
            metrics_met.append("trace_hash_verified")
        else:
            metrics_failed.append("trace_hash_verified")

        passed = (
            solve_proc.returncode == 0
            and verifier_proc.returncode == 0
            and not evidence_missing
        )
        final_status = "success" if passed else "max_attempts_reached"
        score = 1.0 if passed else (0.3 if evidence_found or metrics_met else 0.0)
        error_parts = [
            text.strip()
            for text in (
                solve_stderr,
                solve_stdout,
                verifier_stderr,
                verifier_stdout,
                str(run_summary.get("failure_reason") or ""),
            )
            if text and text.strip()
        ]
        error_message = "\n\n".join(error_parts[:3]) if error_parts else None
        artifact_ratio = (
            len(evidence_found) / len(required_outputs)
            if required_outputs
            else (1.0 if passed else 0.0)
        )
        run_state = str(
            run_summary.get("status") or ("succeeded" if passed else "failed")
        ).strip()
        completion_state = (
            "succeeded"
            if passed
            else (
                "failed" if run_state in {"failed", "queued", "running"} else run_state
            )
        )
        motif_present = not passed

        results.append(
            {
                "task_id": task_id,
                "final_status": final_status,
                "motif_present": motif_present,
                "blocker": not passed,
                "final_evaluation": {
                    "score": score,
                    "evidence_missing": evidence_missing,
                    "metrics_met": metrics_met,
                },
                "attempts": [
                    {
                        "attempt_number": 1,
                        "status": "success" if passed else "failed",
                        "score": score,
                        "execution_time_s": round((end - start).total_seconds(), 6),
                        "start_time": start.isoformat(),
                        "end_time": end.isoformat(),
                        "tokens_estimated": True,
                        "workdir": str(attempt_root),
                        "run_dir": str(run_summary.get("run_dir") or ""),
                        "analysis_bundle_json": analysis_bundle or None,
                        "analysis_bundle_path": (
                            str(output_dir / "analysis_bundle.json")
                            if (output_dir / "analysis_bundle.json").exists()
                            else None
                        ),
                        "brainr_run_id": str(run_summary.get("run_id") or ""),
                        "loop_profile_id": None,
                        "run_bundle": {
                            "observation": observation or None,
                            "analysis_bundle": analysis_bundle or None,
                            "trajectory": trajectory or None,
                        },
                        "run_scorecard": {
                            "status": run_state,
                            "completion_state": completion_state,
                            "policy": {"issue_count": 0},
                            "warnings": (
                                []
                                if passed
                                else [text for text in error_parts[:1] if text]
                            ),
                            "errors": (
                                []
                                if passed
                                else [text for text in error_parts[:1] if text]
                            ),
                            "summary_metrics": {
                                "artifact_completeness_ratio": round(artifact_ratio, 6),
                                "error_count": 0 if passed else 1,
                            },
                            "steps": [
                                {
                                    "step_id": task_id.lower(),
                                    "tool_id": task_id,
                                    "status": "succeeded" if passed else "failed",
                                }
                            ],
                        },
                        "run_warnings": [],
                        "error_message": error_message,
                        "evidence_found": evidence_found,
                        "evidence_missing": evidence_missing,
                        "metrics_met": metrics_met,
                        "metrics_failed": metrics_failed,
                    }
                ],
            }
        )

    payload = {"results": results}
    results_path = workdir_base / "native_results.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(results_path, payload)
    return {
        "returncode": (
            0 if all(item.get("final_status") == "success" for item in results) else 2
        ),
        "stdout": "",
        "stderr": "",
        "results_path": str(results_path),
        "payload": payload,
    }


def _first_attempt(result: dict[str, Any]) -> dict[str, Any]:
    attempts = result.get("attempts")
    if isinstance(attempts, list) and attempts:
        first = attempts[0]
        if isinstance(first, dict):
            return first
    return {}


def _observed_run_from_benchmark_attempt(result: dict[str, Any]) -> ObservedRun:
    attempt = _first_attempt(result)
    run_scorecard = (
        attempt.get("run_scorecard")
        if isinstance(attempt.get("run_scorecard"), dict)
        else {}
    )
    run_bundle = (
        attempt.get("run_bundle") if isinstance(attempt.get("run_bundle"), dict) else {}
    )
    observation = (
        run_bundle.get("observation")
        if isinstance(run_bundle.get("observation"), dict)
        else {}
    )
    violation_payload = (
        observation.get("violations")
        if isinstance(observation.get("violations"), list)
        else []
    )
    violation_codes = []
    violation_messages = []
    for item in violation_payload:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        message = str(item.get("message") or "").strip()
        if code:
            violation_codes.append(code)
        if message:
            violation_messages.append(message)
    steps = (
        run_scorecard.get("steps")
        if isinstance(run_scorecard.get("steps"), list)
        else []
    )
    tool_ids = [
        str(step.get("tool_id") or "").strip()
        for step in steps
        if isinstance(step, dict) and str(step.get("tool_id") or "").strip()
    ]
    step_statuses = [
        str(step.get("status") or "").strip()
        for step in steps
        if isinstance(step, dict) and str(step.get("status") or "").strip()
    ]
    warnings = [
        str(item).strip()
        for item in list(run_scorecard.get("warnings") or [])
        + list(attempt.get("run_warnings") or [])
        if str(item).strip()
    ]
    errors = [
        str(item).strip()
        for item in list(run_scorecard.get("errors") or [])
        if str(item).strip()
    ]
    attempt_error = str(attempt.get("error_message") or "").strip()
    if attempt_error:
        errors.append(attempt_error)
    summary_metrics = (
        run_scorecard.get("summary_metrics")
        if isinstance(run_scorecard.get("summary_metrics"), dict)
        else {}
    )
    artifact_ratio = summary_metrics.get("artifact_completeness_ratio")
    if not isinstance(artifact_ratio, (int, float)):
        artifact_ratio = None
    return ObservedRun(
        run_id=str(attempt.get("brainr_run_id") or result.get("task_id") or "unknown"),
        run_dir=str(attempt.get("run_dir") or attempt.get("workdir") or ""),
        status=str(
            run_scorecard.get("status")
            or attempt.get("status")
            or result.get("final_status")
            or "unknown"
        ),
        dry_run=(
            bool(observation.get("policy", {}).get("dry_run"))
            if isinstance(observation.get("policy"), dict)
            else False
        ),
        created_at=None,
        started_at=attempt.get("start_time"),
        finished_at=attempt.get("end_time"),
        tool_ids=tool_ids,
        step_statuses=step_statuses,
        errors=errors,
        warnings=warnings,
        violation_codes=violation_codes,
        violation_messages=violation_messages,
        artifact_completeness_ratio=(
            float(artifact_ratio) if isinstance(artifact_ratio, (int, float)) else None
        ),
        policy_issue_count=int(
            ((run_scorecard.get("policy") or {}).get("issue_count")) or 0
        ),
        scorecard=run_scorecard,
        bundle=run_bundle,
    )


def _assess_task_result(
    result: dict[str, Any], motif_family: str
) -> BenchmarkTaskAssessment:
    motif_present_override = result.get("motif_present")
    if isinstance(motif_present_override, bool):
        motif_present = motif_present_override
    else:
        observed = _observed_run_from_benchmark_attempt(result)
        motifs = detect_failure_observations(observed)
        motif_present = any(item.motif_family == motif_family for item in motifs)
    attempt = _first_attempt(result)
    run_scorecard = (
        attempt.get("run_scorecard")
        if isinstance(attempt.get("run_scorecard"), dict)
        else {}
    )
    completion_state = str(run_scorecard.get("completion_state") or "").strip()
    policy_issue_count = int(
        ((run_scorecard.get("policy") or {}).get("issue_count")) or 0
    )
    error_count = int(
        ((run_scorecard.get("summary_metrics") or {}).get("error_count")) or 0
    )
    blocker_override = result.get("blocker")
    if isinstance(blocker_override, bool):
        blocker = blocker_override
    else:
        blocker = bool(
            result.get("final_status") != "success"
            or completion_state in {"failed", "in_progress"}
            or policy_issue_count > 0
            or error_count > 0
        )
    final_eval = (
        result.get("final_evaluation")
        if isinstance(result.get("final_evaluation"), dict)
        else {}
    )
    score = final_eval.get("score")
    if not isinstance(score, (int, float)):
        score = 0.0
    return BenchmarkTaskAssessment(
        task_id=str(result.get("task_id") or ""),
        final_status=str(result.get("final_status") or "unknown"),
        score=float(score),
        blocker=blocker,
        motif_present=motif_present,
    )


def _read_benchmark_results(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    if payload is None:
        raise ValueError(f"Benchmark results file is missing or invalid JSON: {path}")
    return payload


def _run_benchmark_slice(
    *,
    benchmark_root: Path,
    task_ids: list[str],
    python_repo: Path,
    candidate_label: str,
    loop_profile_id: str,
    timeout_s: int,
    candidate_id: str,
    slice_name: str,
) -> dict[str, Any]:
    if not task_ids:
        raise ValueError(f"No task ids supplied for benchmark slice: {slice_name}")
    results_dir = benchmark_root / "benchmark_results"
    before = (
        {
            path.resolve()
            for path in results_dir.glob("results_*.json")
            if path.is_file()
        }
        if results_dir.exists()
        else set()
    )
    workdir_base = (
        get_autoresearch_root()
        / "benchmark_workdirs"
        / candidate_id
        / candidate_label
        / slice_name
    )
    pythonpath_parts = []
    python_src = python_repo / "src"
    if python_src.exists():
        pythonpath_parts.append(str(python_src))
    pythonpath_parts.append(str(python_repo))
    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    env = {
        **os.environ,
        "BRAINR_PYTHON_REPO": str(python_repo),
        "BENCHMARK_WORKDIR_BASE": str(workdir_base),
        "PYTHONPATH": ":".join(pythonpath_parts),
    }
    cmd = [
        shutil.which("python") or "python",
        "run_benchmark.py",
        "--mode",
        "brainr",
        "--max-attempts",
        "1",
        "--timeout",
        str(timeout_s),
        "--loop-profile-id",
        loop_profile_id,
        "--quiet",
        "--tasks",
        *task_ids,
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(benchmark_root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    after = (
        {
            path.resolve()
            for path in results_dir.glob("results_*.json")
            if path.is_file()
        }
        if results_dir.exists()
        else set()
    )
    new_files = sorted(after - before, key=lambda item: item.stat().st_mtime)
    if not new_files:
        latest = sorted(after, key=lambda item: item.stat().st_mtime)
        if not latest:
            raise RuntimeError(
                f"Benchmark runner did not produce a results file for {slice_name}. "
                f"stdout={proc.stdout}\nstderr={proc.stderr}"
            )
        result_path = latest[-1]
    else:
        result_path = new_files[-1]
    payload = _read_benchmark_results(result_path)
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "results_path": str(result_path),
        "payload": payload,
    }


def _run_validation_slice(
    *,
    benchmark_root: Path,
    task_ids: list[str],
    python_repo: Path,
    candidate_label: str,
    loop_profile_id: str,
    timeout_s: int,
    candidate_id: str,
    slice_name: str,
) -> dict[str, Any]:
    native_ids = [task_id for task_id in task_ids if _is_native_harness_task(task_id)]
    benchmark_ids = [
        task_id for task_id in task_ids if not _is_native_harness_task(task_id)
    ]

    native_result = (
        _run_native_harness_slice(
            benchmark_root=benchmark_root,
            task_ids=native_ids,
            python_repo=python_repo,
            candidate_label=candidate_label,
            timeout_s=timeout_s,
            candidate_id=candidate_id,
            slice_name=slice_name,
        )
        if native_ids
        else None
    )
    benchmark_result = (
        _run_benchmark_slice(
            benchmark_root=benchmark_root,
            task_ids=benchmark_ids,
            python_repo=python_repo,
            candidate_label=candidate_label,
            loop_profile_id=loop_profile_id,
            timeout_s=timeout_s,
            candidate_id=candidate_id,
            slice_name=slice_name,
        )
        if benchmark_ids
        else None
    )

    if native_result is None:
        return benchmark_result or {
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "results_path": "",
            "payload": {"results": []},
        }
    if benchmark_result is None:
        return native_result

    merged_results: list[dict[str, Any]] = []
    for source in (benchmark_result["payload"], native_result["payload"]):
        rows = source.get("results") if isinstance(source, dict) else None
        if isinstance(rows, list):
            merged_results.extend(row for row in rows if isinstance(row, dict))
    merged_payload = {"results": merged_results}
    merged_path = (
        get_autoresearch_root()
        / "benchmark_workdirs"
        / candidate_id
        / candidate_label
        / slice_name
        / "merged_results.json"
    )
    _write_json(merged_path, merged_payload)
    return {
        "returncode": max(
            int(benchmark_result.get("returncode", 0)),
            int(native_result.get("returncode", 0)),
        ),
        "stdout": "\n".join(
            text
            for text in (
                benchmark_result.get("stdout", ""),
                native_result.get("stdout", ""),
            )
            if text
        ),
        "stderr": "\n".join(
            text
            for text in (
                benchmark_result.get("stderr", ""),
                native_result.get("stderr", ""),
            )
            if text
        ),
        "results_path": str(merged_path),
        "payload": merged_payload,
    }


def _summarize_slice(payload: dict[str, Any], motif_family: str) -> dict[str, Any]:
    results = payload.get("results")
    if not isinstance(results, list):
        results = []
    assessments = [
        _assess_task_result(item, motif_family)
        for item in results
        if isinstance(item, dict)
    ]
    if not assessments:
        return {
            "total_tasks": 0,
            "success_rate": 0.0,
            "blocker_count": 0,
            "motif_blocker_count": 0,
            "motif_hit_count": 0,
            "tasks": [],
        }
    total = len(assessments)
    success_count = sum(1 for item in assessments if item.final_status == "success")
    blocker_count = sum(1 for item in assessments if item.blocker)
    motif_hit_count = sum(1 for item in assessments if item.motif_present)
    motif_blocker_count = sum(
        1 for item in assessments if item.motif_present and item.blocker
    )
    return {
        "total_tasks": total,
        "success_rate": round(success_count / total, 6),
        "blocker_count": blocker_count,
        "motif_blocker_count": motif_blocker_count,
        "motif_hit_count": motif_hit_count,
        "tasks": [asdict(item) for item in assessments],
    }


def _diff_task_outcomes(
    baseline_summary: dict[str, Any],
    candidate_summary: dict[str, Any],
) -> tuple[list[str], list[str]]:
    baseline_tasks = {
        str(item.get("task_id")): item
        for item in baseline_summary.get("tasks", [])
        if isinstance(item, dict)
    }
    candidate_tasks = {
        str(item.get("task_id")): item
        for item in candidate_summary.get("tasks", [])
        if isinstance(item, dict)
    }
    fixed: list[str] = []
    regressions: list[str] = []
    for task_id, base in baseline_tasks.items():
        cand = candidate_tasks.get(task_id)
        if cand is None:
            continue
        base_success = str(base.get("final_status")) == "success"
        cand_success = str(cand.get("final_status")) == "success"
        if not base_success and cand_success:
            fixed.append(task_id)
        if base_success and not cand_success:
            regressions.append(task_id)
    return fixed, regressions


def _run_local_checks(candidate: FixCandidate) -> dict[str, Any]:
    worktree = Path(candidate.worktree_path)
    commands = list(candidate.local_check_commands)
    results: list[dict[str, Any]] = []
    for command in commands:
        proc = subprocess.run(
            command,
            cwd=str(worktree),
            shell=True,
            capture_output=True,
            text=True,
            check=False,
        )
        results.append(
            {
                "command": command,
                "returncode": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            }
        )
        if proc.returncode != 0:
            return {"ok": False, "results": results}
    return {"ok": True, "results": results}


def _list_touched_paths(worktree_path: Path) -> list[str]:
    proc = _git("diff", "--name-only", "HEAD", "--", cwd=worktree_path)
    if proc.returncode != 0:
        raise RuntimeError(
            proc.stderr.strip() or proc.stdout.strip() or "git diff failed"
        )
    touched = []
    for line in proc.stdout.splitlines():
        text = line.strip()
        if text and text not in touched:
            touched.append(text)
    return touched


def _diff_numstat(
    worktree_path: Path,
) -> tuple[int, int, dict[str, dict[str, int]], list[str]]:
    proc = _git("diff", "--numstat", "HEAD", "--", cwd=worktree_path)
    if proc.returncode != 0:
        return 0, 0, {}, ["diff_numstat_unavailable"]
    total_added = 0
    total_deleted = 0
    per_file: dict[str, dict[str, int]] = {}
    warnings: list[str] = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added_raw, deleted_raw, path_str = (
            parts[0].strip(),
            parts[1].strip(),
            parts[2].strip(),
        )
        try:
            added = int(added_raw) if added_raw != "-" else 0
            deleted = int(deleted_raw) if deleted_raw != "-" else 0
        except ValueError:
            warnings.append(f"unparseable_numstat:{path_str}")
            continue
        total_added += added
        total_deleted += deleted
        per_file[path_str] = {"added": added, "deleted": deleted}
    return total_added, total_deleted, per_file, warnings


def _scan_added_diff_markers(worktree_path: Path) -> dict[str, list[str]]:
    proc = _git("diff", "--unified=0", "--no-color", "HEAD", "--", cwd=worktree_path)
    if proc.returncode != 0:
        return {
            "temp_markers": [],
            "debug_markers": [],
            "warnings": ["diff_patch_unavailable"],
        }
    temp_hits: list[str] = []
    debug_hits: list[str] = []
    for raw_line in proc.stdout.splitlines():
        if not raw_line.startswith("+") or raw_line.startswith("+++"):
            continue
        line = raw_line[1:]
        if _TEMP_MARKER_RE.search(line):
            temp_hits.append(line.strip())
        if _DEBUG_MARKER_RE.search(line):
            debug_hits.append(line.strip())
    return {
        "temp_markers": temp_hits[:8],
        "debug_markers": debug_hits[:8],
        "warnings": [],
    }


def _matching_allowlist_root(path_str: str, allowed_paths: list[str]) -> str | None:
    normalized = str(path_str).strip()
    for item in allowed_paths:
        prefix = str(item).strip()
        if prefix and (
            normalized == prefix or normalized.startswith(prefix.rstrip("/") + "/")
        ):
            return prefix
    return None


def _assess_patch_legibility(
    worktree_path: Path,
    candidate: FixCandidate,
    *,
    touched_paths: list[str] | None = None,
) -> dict[str, Any]:
    touched = list(touched_paths or _list_touched_paths(worktree_path))
    outside_allowlist = [
        path for path in touched if not _is_allowed_path(path, candidate.allowed_paths)
    ]
    lines_added, lines_deleted, per_file, warnings = _diff_numstat(worktree_path)
    marker_info = _scan_added_diff_markers(worktree_path)
    warnings.extend(marker_info.get("warnings") or [])
    temp_hits = [str(item) for item in marker_info.get("temp_markers") or []]
    debug_hits = [str(item) for item in marker_info.get("debug_markers") or []]
    allowlist_roots_used = {
        root
        for path in touched
        for root in [_matching_allowlist_root(path, candidate.allowed_paths)]
        if root
    }
    total_changed = lines_added + lines_deleted
    score = 100.0
    findings: list[str] = []

    if outside_allowlist:
        score -= min(40.0, 20.0 + 10.0 * len(outside_allowlist))
        findings.append("Touches files outside the candidate allowlist.")
    if len(touched) > 1:
        score -= min(20.0, float((len(touched) - 1) * 5))
        findings.append("Patch spans multiple files; review surface area.")
    if len(allowlist_roots_used) > 1:
        score -= min(10.0, float((len(allowlist_roots_used) - 1) * 5))
        findings.append("Patch is spread across multiple allowed roots.")
    if total_changed > 40:
        score -= 5.0
        findings.append(
            "Patch is larger than a small surgical edit (>40 changed lines)."
        )
    if total_changed > 120:
        score -= 10.0
        findings.append(
            "Patch is large enough to merit extra review (>120 changed lines)."
        )
    if temp_hits:
        score -= min(15.0, float(len(temp_hits) * 5))
        findings.append("Added temporary markers such as TODO/FIXME/HACK.")
    if debug_hits:
        score -= min(10.0, float(len(debug_hits) * 5))
        findings.append("Added debug-style statements in the diff.")

    score = max(0.0, round(score, 2))
    if score >= 85:
        band = "high"
    elif score >= 70:
        band = "medium"
    else:
        band = "low"

    return {
        "score": score,
        "band": band,
        "files_touched": len(touched),
        "allowed_path_count": len(candidate.allowed_paths),
        "allowlist_roots_used": sorted(allowlist_roots_used),
        "outside_allowlist_count": len(outside_allowlist),
        "outside_allowlist_paths": outside_allowlist,
        "lines_added": lines_added,
        "lines_deleted": lines_deleted,
        "total_changed_lines": total_changed,
        "temp_marker_hits": temp_hits,
        "debug_marker_hits": debug_hits,
        "per_file_stats": per_file,
        "findings": findings,
        "warnings": sorted({str(item) for item in warnings if str(item).strip()}),
    }


def validate_fix_candidate(
    candidate_id: str,
    *,
    loop_profile_id: str = DEFAULT_LOOP_PROFILE_ID,
    benchmark_root: Path | str | None = None,
    motif_slice_path: Path | str | None = None,
    canary_slice_path: Path | str | None = None,
    timeout_s: int = 600,
    autoresearch_root: Path | str | None = None,
) -> ValidationReport:
    """Validate a fix candidate with local checks plus motif-slice benchmark."""

    state_root = get_autoresearch_root(autoresearch_root)
    candidate = load_fix_candidate(candidate_id, autoresearch_root=state_root)
    worktree = Path(candidate.worktree_path)
    touched_paths = _list_touched_paths(worktree)
    patch_legibility = _assess_patch_legibility(
        worktree,
        candidate,
        touched_paths=touched_paths,
    )
    if not touched_paths:
        report = ValidationReport(
            candidate_id=candidate.candidate_id,
            motif_id=candidate.motif_id,
            motif_family=candidate.motif_family,
            baseline_summary={},
            candidate_summary={},
            gate_verdict="not_validatable",
            larger_benchmark_eligible=False,
            warnings=["Candidate has no diff against HEAD; nothing to validate."],
            touched_paths=[],
            patch_legibility=patch_legibility,
        )
        _persist_validation_report(state_root, candidate, report)
        return report

    unauthorized = [
        path
        for path in touched_paths
        if not _is_allowed_path(path, candidate.allowed_paths)
    ]
    if unauthorized:
        report = ValidationReport(
            candidate_id=candidate.candidate_id,
            motif_id=candidate.motif_id,
            motif_family=candidate.motif_family,
            baseline_summary={},
            candidate_summary={},
            gate_verdict="rejected_out_of_scope",
            larger_benchmark_eligible=False,
            warnings=["Touched paths exceeded candidate allowlist."],
            touched_paths=touched_paths,
            patch_legibility=patch_legibility,
            local_checks={"ok": False, "unauthorized_paths": unauthorized},
        )
        _persist_validation_report(state_root, candidate, report)
        return report

    local_checks = _run_local_checks(candidate)
    if not local_checks.get("ok", False):
        report = ValidationReport(
            candidate_id=candidate.candidate_id,
            motif_id=candidate.motif_id,
            motif_family=candidate.motif_family,
            baseline_summary={},
            candidate_summary={},
            gate_verdict="failed_local_checks",
            larger_benchmark_eligible=False,
            warnings=["Touched-surface local checks failed."],
            touched_paths=touched_paths,
            patch_legibility=patch_legibility,
            local_checks=local_checks,
        )
        _persist_validation_report(state_root, candidate, report)
        return report

    benchmark_root_path = (
        Path(benchmark_root).expanduser().resolve()
        if benchmark_root is not None
        else DEFAULT_BENCHMARK_ROOT
    )
    motif_task_ids = load_motif_slice_task_ids(
        candidate.motif_family,
        benchmark_root=benchmark_root_path,
        path=motif_slice_path,
    )
    canary_task_ids = load_motif_canary_task_ids(
        candidate.motif_family,
        benchmark_root=benchmark_root_path,
        path=motif_slice_path,
    )
    if not canary_task_ids:
        canary_task_ids = load_canary_task_ids(
            benchmark_root=benchmark_root_path,
            path=canary_slice_path,
        )
    if not motif_task_ids:
        report = ValidationReport(
            candidate_id=candidate.candidate_id,
            motif_id=candidate.motif_id,
            motif_family=candidate.motif_family,
            baseline_summary={},
            candidate_summary={},
            gate_verdict="not_validatable",
            larger_benchmark_eligible=False,
            warnings=["Motif slice is empty; candidate cannot be benchmarked."],
            touched_paths=touched_paths,
            patch_legibility=patch_legibility,
            local_checks=local_checks,
        )
        _persist_validation_report(state_root, candidate, report)
        return report

    baseline_motif = _run_validation_slice(
        benchmark_root=benchmark_root_path,
        task_ids=motif_task_ids,
        python_repo=REPO_ROOT,
        candidate_label="baseline",
        loop_profile_id=loop_profile_id,
        timeout_s=timeout_s,
        candidate_id=candidate.candidate_id,
        slice_name="motif_slice",
    )
    candidate_motif = _run_validation_slice(
        benchmark_root=benchmark_root_path,
        task_ids=motif_task_ids,
        python_repo=worktree,
        candidate_label="candidate",
        loop_profile_id=loop_profile_id,
        timeout_s=timeout_s,
        candidate_id=candidate.candidate_id,
        slice_name="motif_slice",
    )
    baseline_canary = _run_validation_slice(
        benchmark_root=benchmark_root_path,
        task_ids=canary_task_ids,
        python_repo=REPO_ROOT,
        candidate_label="baseline",
        loop_profile_id=loop_profile_id,
        timeout_s=timeout_s,
        candidate_id=candidate.candidate_id,
        slice_name="canary_slice",
    )
    candidate_canary = _run_validation_slice(
        benchmark_root=benchmark_root_path,
        task_ids=canary_task_ids,
        python_repo=worktree,
        candidate_label="candidate",
        loop_profile_id=loop_profile_id,
        timeout_s=timeout_s,
        candidate_id=candidate.candidate_id,
        slice_name="canary_slice",
    )

    baseline_motif_summary = _summarize_slice(
        baseline_motif["payload"], candidate.motif_family
    )
    candidate_motif_summary = _summarize_slice(
        candidate_motif["payload"], candidate.motif_family
    )
    baseline_canary_summary = _summarize_slice(
        baseline_canary["payload"], candidate.motif_family
    )
    candidate_canary_summary = _summarize_slice(
        candidate_canary["payload"], candidate.motif_family
    )
    fixed_failures, motif_regressions = _diff_task_outcomes(
        baseline_motif_summary,
        candidate_motif_summary,
    )
    _, canary_regressions = _diff_task_outcomes(
        baseline_canary_summary,
        candidate_canary_summary,
    )
    regressions = sorted(set(motif_regressions + canary_regressions))
    status_explanation: str | None = None
    recommended_action: str | None = None

    if baseline_motif_summary["motif_hit_count"] == 0:
        eligible = False
        absorbed_upstream = bool(
            candidate_motif_summary["motif_hit_count"] == 0
            and candidate_motif_summary["blocker_count"]
            <= baseline_motif_summary["blocker_count"]
            and candidate_canary_summary["blocker_count"]
            <= baseline_canary_summary["blocker_count"]
            and not regressions
        )
        if absorbed_upstream:
            verdict = "absorbed_upstream"
            warnings = []
            status_explanation = (
                "The baseline no longer reproduces the target failure motif. "
                "Mainline appears to already include this repair, so the candidate "
                "is no longer actionable as a separate promotion."
            )
            recommended_action = (
                "Archive or close this candidate and treat the fix as already "
                "absorbed into main."
            )
        else:
            verdict = "not_validatable"
            warnings = [
                "Motif slice did not reproduce the target failure motif on the baseline."
            ]
            status_explanation = (
                "The benchmark slice did not reproduce the target failure on the "
                "baseline, so autoresearch cannot attribute a before/after win to "
                "this candidate."
            )
            recommended_action = (
                "Refresh the motif slice or reproduce the failure with a more "
                "targeted harness probe before attempting promotion."
            )
    else:
        canary_drop = (
            baseline_canary_summary["success_rate"]
            - candidate_canary_summary["success_rate"]
        )
        eligible = bool(
            candidate_motif_summary["motif_blocker_count"]
            < baseline_motif_summary["motif_blocker_count"]
            and len(fixed_failures) >= 1
            and candidate_canary_summary["blocker_count"]
            <= baseline_canary_summary["blocker_count"]
            and canary_drop <= 0.10
        )
        verdict = "passed" if eligible else "failed_gate"
        warnings = []
        if (
            candidate_motif_summary["motif_blocker_count"]
            >= baseline_motif_summary["motif_blocker_count"]
        ):
            warnings.append("Target motif blocker incidence did not decrease.")
        if not fixed_failures:
            warnings.append("Candidate did not fix any baseline failing motif task.")
        if (
            candidate_canary_summary["blocker_count"]
            > baseline_canary_summary["blocker_count"]
        ):
            warnings.append("Candidate introduced a new blocker on the canary slice.")
        if canary_drop > 0.10:
            warnings.append("Candidate reduced canary success rate by more than 10%.")
        if eligible:
            status_explanation = (
                "The candidate reduced target motif blockers without introducing "
                "new blocker regressions on the canary slice."
            )
            recommended_action = (
                "Queue this candidate for the next larger benchmark tier."
            )
        else:
            status_explanation = (
                "The target motif was reproduced on baseline, but the candidate "
                "did not clear the fail-fast validation gate."
            )
            recommended_action = (
                "Inspect the warnings and regressions, then revise the candidate "
                "before retrying validation."
            )

    report = ValidationReport(
        candidate_id=candidate.candidate_id,
        motif_id=candidate.motif_id,
        motif_family=candidate.motif_family,
        baseline_summary={
            "motif_slice": baseline_motif_summary,
            "canary_slice": baseline_canary_summary,
            "results_paths": {
                "motif_slice": baseline_motif["results_path"],
                "canary_slice": baseline_canary["results_path"],
            },
        },
        candidate_summary={
            "motif_slice": candidate_motif_summary,
            "canary_slice": candidate_canary_summary,
            "results_paths": {
                "motif_slice": candidate_motif["results_path"],
                "canary_slice": candidate_canary["results_path"],
            },
        },
        gate_verdict=verdict,
        larger_benchmark_eligible=eligible,
        regressions=regressions,
        fixed_failures=fixed_failures,
        local_checks=local_checks,
        touched_paths=touched_paths,
        patch_legibility=patch_legibility,
        warnings=warnings,
        status_explanation=status_explanation,
        recommended_action=recommended_action,
    )
    _persist_validation_report(state_root, candidate, report)
    return report


def _persist_validation_report(
    state_root: Path,
    candidate: FixCandidate,
    report: ValidationReport,
) -> None:
    validation_root = _validation_dir(state_root, candidate.candidate_id)
    _write_json(validation_root / "validation_report.json", asdict(report))
    candidate_root = _candidate_dir(state_root, candidate.candidate_id)
    candidate_payload = asdict(candidate)
    candidate_payload["status"] = (
        "larger_benchmark_eligible"
        if report.larger_benchmark_eligible
        else report.gate_verdict
    )
    _write_json(candidate_root / "candidate_fix.json", candidate_payload)


__all__ = [
    "DEFAULT_AUTORESEARCH_ROOT",
    "DEFAULT_BENCHMARK_ROOT",
    "DEFAULT_CANARY_SLICE_PATH",
    "DEFAULT_MOTIF_SLICE_PATH",
    "FailureMotifCard",
    "FixCandidate",
    "MOTIF_FAMILIES",
    "MOTIF_LOCAL_CHECKS",
    "ObservedRun",
    "ValidationReport",
    "collect_observed_runs",
    "detect_failure_observations",
    "get_autoresearch_root",
    "load_canary_task_ids",
    "load_failure_motifs",
    "load_fix_candidate",
    "load_motif_canary_task_ids",
    "load_motif_slice_config",
    "load_motif_slice_task_ids",
    "load_observed_run",
    "mine_failure_motifs",
    "propose_fix_candidates",
    "validate_fix_candidate",
]
