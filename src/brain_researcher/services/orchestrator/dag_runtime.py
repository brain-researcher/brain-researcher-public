"""DAG executor with dependency-aware parallel execution and retries.

This replaces the old sequential stub. It keeps the same public API so the
orchestrator and worker can drop it in, but now honors step dependencies,
concurrency limits, timeouts, and retries while emitting detailed events.
"""

from __future__ import annotations

import concurrent.futures
import queue
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from brain_researcher.services.agent.error_taxonomy import classify_failure
from brain_researcher.services.shared.workflow_models import WorkflowStep

DEFAULT_MAX_CONCURRENCY = 4
DEFAULT_RETRY_DELAY = 0.5


class WorkflowState(Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class WorkflowDefinition:
    workflow_id: str
    steps: List[WorkflowStep]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowResult:
    state: WorkflowState
    error: Optional[str] = None
    run_dir: Optional[str] = None
    step_results: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "error": self.error,
            "run_dir": self.run_dir,
            "steps": self.step_results,
        }


class DAGExecutor:
    """Dependency-aware executor with parallelism and retries."""

    def __init__(
        self,
        tool_executor: Any = None,
        recorder_factory: Callable[..., Any] | None = None,
        *,
        max_concurrency: int | None = None,
        event_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> None:
        self.tool_executor = tool_executor
        self.event_callback = event_callback
        self.max_concurrency = max_concurrency or DEFAULT_MAX_CONCURRENCY

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def execute(self, workflow: WorkflowDefinition) -> WorkflowResult:
        graph = _ExecutionGraph(workflow, self.max_concurrency)
        runner = _ExecutionRunner(
            graph=graph,
            tool_executor=self.tool_executor,
            event_callback=self.event_callback,
        )
        return runner.run()


# Alias for compatibility with older imports
__all__ = [
    "WorkflowState",
    "WorkflowStep",
    "WorkflowDefinition",
    "WorkflowResult",
    "DAGExecutor",
]


# ---------------------------------------------------------------------------
# Internal execution graph and runner
# ---------------------------------------------------------------------------


class _ExecutionGraph:
    def __init__(self, workflow: WorkflowDefinition, max_concurrency: int) -> None:
        self.workflow = workflow
        self.max_concurrency = max(1, int(max_concurrency or DEFAULT_MAX_CONCURRENCY))
        self.nodes: Dict[str, WorkflowStep] = {s.step_id: s for s in workflow.steps}
        self.in_degree: Dict[str, int] = {sid: 0 for sid in self.nodes}
        self.children: Dict[str, List[str]] = {sid: [] for sid in self.nodes}
        self._build()

    def _build(self) -> None:
        for step in self.nodes.values():
            for dep in step.depends_on or []:
                if dep not in self.nodes:
                    raise ValueError(
                        f"Step '{step.step_id}' depends on unknown step '{dep}'"
                    )
                self.in_degree[step.step_id] += 1
                self.children[dep].append(step.step_id)

    def roots(self) -> List[str]:
        return [sid for sid, deg in self.in_degree.items() if deg == 0]


class _ExecutionRunner:
    def __init__(
        self,
        graph: _ExecutionGraph,
        tool_executor: Any,
        event_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> None:
        self.graph = graph
        self.tool_executor = tool_executor
        self.event_callback = event_callback
        self.ctx: Dict[str, Any] = {}
        self.step_results: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Lock()
        self.todo = queue.Queue()
        # Track steps that are queued vs currently executing. Without this,
        # `_enqueue_ready` can reschedule a runnable step many times before it
        # finishes, causing `wait(futures)` to block far longer than intended.
        self._queued: set[str] = set()
        self._in_flight: set[str] = set()
        self.fail_error: Optional[str] = None

    def run(self) -> WorkflowResult:
        # Seed ready nodes
        for sid in self.graph.roots():
            self.todo.put(sid)
            self._queued.add(sid)

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.graph.max_concurrency
        ) as pool:
            futures = []
            while not self._all_done():
                self._enqueue_ready()
                try:
                    sid = self.todo.get(timeout=0.1)
                except queue.Empty:
                    continue
                with self.lock:
                    self._queued.discard(sid)
                    if sid in self.step_results or sid in self._in_flight:
                        continue
                    self._in_flight.add(sid)
                futures.append(pool.submit(self._run_step_safe, sid))

            wait_timeout = self._overall_timeout()
            if wait_timeout is not None:
                done, not_done = concurrent.futures.wait(futures, timeout=wait_timeout)
                if not_done:
                    for fut in not_done:
                        fut.cancel()
                    if self.fail_error is None:
                        self.fail_error = "workflow timed out"
            else:
                concurrent.futures.wait(futures)

        state = (
            WorkflowState.SUCCEEDED if self.fail_error is None else WorkflowState.FAILED
        )
        return WorkflowResult(
            state=state,
            error=self.fail_error,
            step_results=list(self.step_results.values()),
        )

    def _all_done(self) -> bool:
        with self.lock:
            return (
                len(self.step_results) == len(self.graph.nodes)
                or self.fail_error is not None
            )

    def _enqueue_ready(self) -> None:
        with self.lock:
            for sid, deg in list(self.graph.in_degree.items()):
                if (
                    deg == 0
                    and sid not in self.step_results
                    and sid not in self._queued
                    and sid not in self._in_flight
                ):
                    self.todo.put(sid)
                    self._queued.add(sid)

    def _run_step_safe(self, step_id: str) -> None:
        try:
            self._run_step(step_id)
        except Exception as exc:  # pragma: no cover - defensive
            with self.lock:
                if self.fail_error is None:
                    self.fail_error = str(exc)
        finally:
            with self.lock:
                self._in_flight.discard(step_id)

    def _run_step(self, step_id: str) -> None:
        step = self.graph.nodes[step_id]
        self._emit("step_scheduled", {"step_id": step.step_id, "tool": step.tool_name})

        # Resolve parameters with context and consumes mapping
        resolved_params = self._resolve(step.parameters)
        if step.metadata and isinstance(step.metadata.get("consumes"), dict):
            for param_name, ctx_key in step.metadata.get("consumes", {}).items():
                if (
                    param_name not in resolved_params
                    or resolved_params[param_name] is None
                ):
                    if ctx_key in self.ctx:
                        resolved_params[param_name] = self.ctx[ctx_key]

        # Retry loop
        retries = (
            int(step.metadata.get("retries", 0))
            if isinstance(step.metadata, dict)
            else 0
        )
        delay = (
            float(step.metadata.get("retry_delay", DEFAULT_RETRY_DELAY))
            if isinstance(step.metadata, dict)
            else DEFAULT_RETRY_DELAY
        )
        attempt = 0
        status = "error"
        error = None
        result = None
        start_ns = time.perf_counter_ns()

        while attempt <= retries:
            attempt += 1
            self._emit(
                "step_started",
                {"step_id": step.step_id, "tool": step.tool_name, "attempt": attempt},
            )
            try:
                result, status, error = self._execute_tool(step, resolved_params)
            except Exception as exc:  # pragma: no cover
                status, error = "error", str(exc)

            if status in {"success", "succeeded"}:
                break
            if attempt <= retries:
                self._emit(
                    "step_retry",
                    {
                        "step_id": step.step_id,
                        "tool": step.tool_name,
                        "attempt": attempt,
                        "retries": retries,
                        "error": error,
                        "status": status,
                    },
                )
                time.sleep(delay)

        duration_ms = (time.perf_counter_ns() - start_ns) // 1_000_000

        # Build step result
        step_result: Dict[str, Any] = {
            "step_id": step.step_id,
            "tool": step.tool_name,
            "status": status,
            "result": result,
            "error": error,
            "duration_ms": duration_ms,
            "attempts": attempt,
        }

        if status not in {"success", "succeeded"}:
            taxonomy = None
            if isinstance(result, dict):
                taxonomy = result.get("error_taxonomy") or result.get(
                    "metadata", {}
                ).get("error_taxonomy")
            if taxonomy is None:
                taxonomy_obj = classify_failure(status="error", error_message=error)
                taxonomy = taxonomy_obj.to_dict()
            if isinstance(taxonomy, dict):
                step_result["error_taxonomy"] = taxonomy
                step_result["error_category"] = taxonomy.get("category")
                step_result["is_retryable"] = taxonomy.get("is_retryable")
                step_result["recovery_strategy"] = taxonomy.get("recovery_action")
                step_result["recovery_suggestions"] = taxonomy.get(
                    "recovery_suggestions"
                )

        # Success path: merge outputs into ctx
        if status in {"success", "succeeded"}:
            outputs = None
            if isinstance(result, dict):
                data = result.get("data", result)
                if isinstance(data, dict):
                    outputs = (
                        data.get("outputs")
                        if isinstance(data.get("outputs"), dict)
                        else None
                    )
            if outputs:
                with self.lock:
                    self.ctx.update(outputs)

        with self.lock:
            self.step_results[step.step_id] = step_result
            # Unlock children
            for child in self.graph.children.get(step.step_id, []):
                self.graph.in_degree[child] -= 1
            if status not in {"success", "succeeded"} and self.fail_error is None:
                self.fail_error = error or "step failed"

        complete_payload = {
            "step_id": step.step_id,
            "tool": step.tool_name,
            "status": status,
            "attempts": attempt,
            "duration_ms": duration_ms,
        }
        if error:
            complete_payload["error"] = error
        if step_result.get("error_taxonomy"):
            complete_payload["error_taxonomy"] = step_result.get("error_taxonomy")
        self._emit("step_completed", complete_payload)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _resolve(self, val):
        if isinstance(val, str):
            try:
                return val.format_map({k: v for k, v in self.ctx.items()})
            except Exception:
                return val
        if isinstance(val, list):
            return [self._resolve(v) for v in val]
        if isinstance(val, dict):
            return {k: self._resolve(v) for k, v in val.items()}
        return val

    def _execute_tool(self, step: WorkflowStep, params: Dict[str, Any]):
        if not self.tool_executor or not hasattr(self.tool_executor, "run_tool"):
            return None, "skipped", None

        execution_context: Dict[str, Any] = {
            "parent_run_id": self.graph.workflow.workflow_id,
            "step_id": step.step_id,
        }
        if isinstance(step.metadata, dict):
            execution_context["runtime_kind"] = step.metadata.get(
                "runtime_kind", "container"
            )
            execution_context["step_metadata"] = step.metadata
        workflow_meta = (
            self.graph.workflow.metadata
            if isinstance(self.graph.workflow.metadata, dict)
            else {}
        )
        run_dir_value = workflow_meta.get("run_dir")
        if isinstance(run_dir_value, str) and run_dir_value.strip():
            run_dir = Path(run_dir_value.strip())
            execution_context["work_dir"] = str(run_dir)
            execution_context["output_dir"] = str((run_dir / "outputs").resolve())

        timeout = None
        if isinstance(step.metadata, dict) and step.metadata.get("timeout_sec"):
            try:
                timeout = float(step.metadata.get("timeout_sec"))
            except (TypeError, ValueError):
                timeout = None

        if timeout:
            pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            fut = pool.submit(
                self.tool_executor.run_tool,
                step.tool_name,
                _execution_context=execution_context,
                **params,
            )
            try:
                result = fut.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                fut.cancel()
                pool.shutdown(wait=False, cancel_futures=True)
                return None, "timeout", "step timed out"
            else:
                pool.shutdown(wait=True, cancel_futures=False)
        else:
            result = self.tool_executor.run_tool(
                step.tool_name,
                _execution_context=execution_context,
                **params,
            )

        status = (
            result.get("status", "unknown")
            if isinstance(result, dict)
            else getattr(result, "status", "unknown")
        )
        error = (
            result.get("error")
            if isinstance(result, dict)
            else getattr(result, "error", None)
        )
        return result, status, error

    def _overall_timeout(self) -> float | None:
        """Compute a conservative overall timeout when every step has one."""
        max_budget = 0.0
        for step in self.graph.nodes.values():
            if not isinstance(step.metadata, dict):
                return None
            raw_timeout = step.metadata.get("timeout_sec")
            if raw_timeout is None:
                return None
            try:
                timeout_sec = float(raw_timeout)
            except (TypeError, ValueError):
                return None
            if timeout_sec <= 0:
                return None
            retries = int(step.metadata.get("retries", 0))
            delay = float(step.metadata.get("retry_delay", DEFAULT_RETRY_DELAY))
            budget = timeout_sec * (retries + 1) + max(0.0, delay) * retries
            if budget > max_budget:
                max_budget = budget
        if max_budget <= 0:
            return None
        return max_budget + 0.5

    def _emit(self, event: str, payload: Dict[str, Any]) -> None:
        if self.event_callback:
            try:
                self.event_callback(event, payload)
            except Exception:  # pragma: no cover - best effort
                pass
