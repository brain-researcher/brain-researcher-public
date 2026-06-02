"""KG evidence model + aggregation helpers.

This module is intentionally lightweight and dependency-injection friendly:
- Evidence aggregation is pure/deterministic (unit-testable).
- Persistence is delegated to writer/reader interfaces (Neo4j or mocks).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from brain_researcher.core.contracts.loop_signals import (
    LoopSignalBaseV1,
    parse_loop_signals,
)
from brain_researcher.services.agent.error_taxonomy import classify_failure
from brain_researcher.services.agent.planner.kg_bridge import resolve_dataset_id
from brain_researcher.services.agent.planner.kg_utils import (
    extract_dataset_from_context,
    normalize_dataset_id,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolEvidenceRecord:
    """A single evidence datapoint for tool performance on a task family."""

    tool_id: str
    tool_version: str
    task_family: str
    outcome: str  # "success" | "fail"
    latency_ms: int | None = None
    failure_category: str | None = None
    dataset_id: str | None = None
    dataset_family: str | None = None
    run_id: str | None = None
    plan_id: str | None = None
    loop_signals: tuple[LoopSignalBaseV1, ...] = ()


@dataclass(frozen=True)
class ToolEvidenceStats:
    """Aggregated evidence stats read from storage."""

    success_count: int = 0
    fail_count: int = 0
    latency_ms_samples: tuple[int, ...] = ()
    failure_categories: tuple[str, ...] = ()
    layer_used: str | None = None
    samples_used: int = 0

    def total(self) -> int:
        return max(0, self.success_count) + max(0, self.fail_count)

    def success_rate_smoothed(self, *, alpha: float = 1.0, beta: float = 1.0) -> float:
        """Beta-smoothed success rate in [0, 1]."""

        total = self.total()
        if total <= 0:
            return 0.5
        return float((self.success_count + alpha) / (total + alpha + beta))

    def p95_latency_ms(self) -> int | None:
        samples = [s for s in self.latency_ms_samples if isinstance(s, int) and s >= 0]
        if not samples:
            return None
        samples.sort()
        idx = int(round(0.95 * (len(samples) - 1)))
        return samples[max(0, min(len(samples) - 1, idx))]

    def latency_score(self, *, fast_ms: int = 1_000, slow_ms: int = 60_000) -> float:
        """Convert p95 latency into a preference score in [0, 1] (higher is better)."""

        p95 = self.p95_latency_ms()
        if p95 is None:
            return 0.5
        if p95 <= fast_ms:
            return 1.0
        if p95 >= slow_ms:
            return 0.0
        return 1.0 - (p95 - fast_ms) / float(slow_ms - fast_ms)

    def failure_penalty(self) -> float:
        """Low-cardinality penalty in [0, 0.5] based on failure share + dominant category."""

        total = self.total()
        if total <= 0 or self.fail_count <= 0:
            return 0.0

        # Dominant failure category over a recent window (if present).
        counts: dict[str, int] = {}
        for cat in self.failure_categories:
            if not cat:
                continue
            counts[cat] = counts.get(cat, 0) + 1
        dominant = max(counts.items(), key=lambda kv: kv[1])[0] if counts else "unknown"

        # Weight categories by how "actionable/serious" they are.
        weights = {
            "infra": 0.06,
            "tool": 0.15,
            "data": 0.15,
            "stats": 0.10,
            "concept": 0.06,
            "user_input": 0.10,
            "unknown": 0.10,
        }
        fail_share = self.fail_count / float(total)
        return min(0.5, fail_share * weights.get(dominant, 0.10))


class ToolEvidenceWriter(Protocol):
    def write(self, records: Sequence[ToolEvidenceRecord]) -> None: ...


class ToolEvidenceReader(Protocol):
    def read_stats(
        self,
        *,
        tool_versions: Mapping[str, str],
        task_family: str,
        tool_ids: Sequence[str],
    ) -> dict[str, ToolEvidenceStats]: ...


def _truthy_env(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def is_writeback_enabled() -> bool:
    """Feature flag for KG evidence writeback (default: off)."""

    return _truthy_env(os.environ.get("BR_KG_WRITEBACK"))


def aggregate_plan_job_evidence(
    *,
    job_payload: Mapping[str, Any],
    workflow_result: Mapping[str, Any],
    duration_ms: int | None,
    tool_versions: Mapping[str, str] | None = None,
    dataset_id: str | None = None,
    run_id: str | None = None,
    plan_id: str | None = None,
) -> list[ToolEvidenceRecord]:
    """Aggregate evidence from a plan_execution job payload + workflow result.

    Deterministic ordering:
    - tool ids are de-duplicated and sorted (stable across runs)
    """

    tool_versions = dict(tool_versions or {})

    snapshot = (
        job_payload.get("snapshot")
        if isinstance(job_payload.get("snapshot"), dict)
        else {}
    )
    context = (
        job_payload.get("context")
        if isinstance(job_payload.get("context"), dict)
        else {}
    )
    plan_id = plan_id or job_payload.get("plan_id") or snapshot.get("plan_id")
    if run_id is None:
        run_id = job_payload.get("job_id") or context.get("run_id")

    intent = snapshot.get("intent")
    task_family = None
    if isinstance(intent, list) and intent and isinstance(intent[0], str):
        task_family = intent[0]
    if not task_family:
        pipeline = context.get("pipeline")
        task_family = (
            pipeline if isinstance(pipeline, str) and pipeline.strip() else "unknown"
        )

    state = workflow_result.get("state")
    succeeded = str(state).lower() == "succeeded"

    step_results = workflow_result.get("steps")
    tool_status: dict[str, str] = {}
    tool_error: dict[str, str] = {}
    tool_duration_ms: dict[str, int] = {}
    if isinstance(step_results, list):
        for row in step_results:
            if not isinstance(row, dict):
                continue
            tool = row.get("tool")
            status = row.get("status")
            if isinstance(tool, str):
                if isinstance(status, str):
                    tool_status[tool] = status
                err = row.get("error")
                if isinstance(err, str) and err:
                    tool_error[tool] = err
                dur = row.get("duration_ms")
                if isinstance(dur, (int, float)) and dur >= 0:
                    tool_duration_ms[tool] = int(dur)

    # Tool ids: prefer plan steps; fallback to chosen_tool only.
    tool_ids: set[str] = set()
    steps = job_payload.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, dict) and isinstance(step.get("tool"), str):
                tool_ids.add(step["tool"])
    chosen_tool = snapshot.get("chosen_tool")
    if not tool_ids and isinstance(chosen_tool, str):
        tool_ids.add(chosen_tool)

    # dataset resolution (optional)
    if dataset_id is None:
        dataset_id = extract_dataset_from_context(context)
    dataset_id = normalize_dataset_id(dataset_id)
    resolved_dataset_id = resolve_dataset_id(dataset_id) if dataset_id else None
    dataset_family = None
    if dataset_id and ":" in dataset_id:
        parts = dataset_id.split(":")
        if len(parts) >= 2:
            dataset_family = ":".join(parts[:2])

    raw_loop_signals = []
    if isinstance(snapshot.get("loop_signals"), list):
        raw_loop_signals.extend(snapshot.get("loop_signals") or [])
    if isinstance(context.get("loop_signals"), list):
        raw_loop_signals.extend(context.get("loop_signals") or [])
    loop_signals = tuple(parse_loop_signals(raw_loop_signals))

    records: list[ToolEvidenceRecord] = []
    for tool_id in sorted(tool_ids):
        status = tool_status.get(tool_id, "")
        per_tool_failed = status.lower() == "error"
        outcome = "success" if (succeeded and not per_tool_failed) else "fail"

        failure_category = None
        if outcome == "fail":
            err = tool_error.get(tool_id) or workflow_result.get("error")
            err_msg = err if isinstance(err, str) else None
            taxonomy = classify_failure(error_message=err_msg)
            failure_category = taxonomy.debug.get("rule") or taxonomy.category.value

        records.append(
            ToolEvidenceRecord(
                tool_id=tool_id,
                tool_version=tool_versions.get(tool_id, "") or "",
                task_family=task_family,
                outcome=outcome,
                latency_ms=tool_duration_ms.get(tool_id, duration_ms),
                failure_category=failure_category,
                dataset_id=resolved_dataset_id or dataset_id,
                dataset_family=dataset_family,
                run_id=run_id,
                plan_id=plan_id,
                loop_signals=loop_signals,
            )
        )

    return records
