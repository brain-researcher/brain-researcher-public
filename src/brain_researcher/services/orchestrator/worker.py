"""
Worker loop for processing jobs from the JobStore queue.

The worker continuously claims jobs, executes them, sends heartbeats,
and updates job state using the JobStore API.
"""

from __future__ import annotations

import asyncio
import heapq
import importlib
import json
import logging
import os
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from urllib.parse import quote

try:  # Optional dependency for resource snapshots
    import psutil  # type: ignore
except ImportError:  # pragma: no cover
    psutil = None

from brain_researcher.core.contracts import Violation
from brain_researcher.core.gates import GateEngine
from brain_researcher.services.orchestrator.dag_runtime import (
    DAGExecutor,
    WorkflowDefinition,
    WorkflowResult,
    WorkflowState,
    WorkflowStep,
)
from brain_researcher.services.orchestrator.event_log import emit_job_event
from brain_researcher.services.orchestrator.reward import write_reward_breakdown
from brain_researcher.services.orchestrator.trace import (
    build_atif_trajectory,
    log_trace_event,
    write_trajectory_json,
)
from brain_researcher.services.shared.settings import Settings, get_settings
from brain_researcher.services.telemetry.metrics_kind_resolver import resolve_job_kind

from .job_adapter import JobAdapter
from .job_store import JobState, JobStore
from .models import CacheMetadata

logger = logging.getLogger(__name__)


def _tool_executor_required() -> bool:
    """Whether ToolExecutor must be available (fail-fast) instead of stubbing."""
    explicit = os.getenv("BR_REQUIRE_TOOL_EXECUTOR") or os.getenv(
        "BR_WORKER_REQUIRE_TOOL_EXECUTOR"
    )
    if explicit is not None:
        return explicit.strip().lower() in {"1", "true", "yes", "y", "on"}

    runtime_env = (os.getenv("APP_ENV") or os.getenv("ENV") or "").strip().lower()
    return runtime_env in {"prod", "production"}


def _anchor_plan_step_output_dirs(
    step_defs: List[Dict[str, Any]],
    *,
    run_dir: Path | None,
) -> bool:
    """Force plan step output directories onto the job-specific run directory."""

    if run_dir is None:
        return False

    output_file_keys = {
        "output_file",
        "out_file",
        "output_csv",
        "output_tsv",
        "output_json",
        "output_html",
        "output_pdf",
        "report_file",
        "report_path",
        "figure_file",
        "figure_path",
        "qc_tsv",
    }
    changed = False
    for raw in step_defs:
        if not isinstance(raw, dict):
            continue
        tool_name = str(raw.get("tool") or "")
        params = raw.get("params")
        if not isinstance(params, dict):
            params = {}
        has_output_dir = isinstance(params.get("output_dir"), str) and bool(
            params.get("output_dir", "").strip()
        )
        if not has_output_dir and not tool_name.startswith("workflow_"):
            continue
        updated = dict(params)
        previous_output_dir = None
        if has_output_dir:
            previous = str(params.get("output_dir") or "").strip()
            if previous and "://" not in previous:
                candidate = Path(previous).expanduser()
                if candidate.is_absolute():
                    previous_output_dir = candidate

        if updated.get("output_dir") != str(run_dir):
            updated["output_dir"] = str(run_dir)
            raw["params"] = updated
            changed = True
        for key in output_file_keys:
            value = updated.get(key)
            if not isinstance(value, str):
                continue
            raw_value = value.strip()
            if not raw_value or "://" in raw_value:
                continue
            path_obj = Path(raw_value).expanduser()
            if not path_obj.is_absolute():
                continue
            rel_path: Path | None = None
            if previous_output_dir is not None:
                try:
                    rel_path = path_obj.relative_to(previous_output_dir)
                except ValueError:
                    rel_path = None
            if rel_path is None:
                rel_path = Path(path_obj.name or key)
            anchored = str((run_dir / rel_path).resolve())
            if updated.get(key) != anchored:
                updated[key] = anchored
                raw["params"] = updated
                changed = True

    return changed


# Import ToolExecutor for job execution
try:
    from brain_researcher.services.agent.tool_executor import (
        ExecutionMode,
        ToolExecutionRequest,
        ToolExecutor,
    )

    TOOL_EXECUTOR_AVAILABLE = True
except ImportError:
    TOOL_EXECUTOR_AVAILABLE = False
    logger.warning("ToolExecutor not available - worker will use stub execution")

_plan_executor_lock = threading.Lock()
_shared_plan_executor: Optional["ToolExecutor"] = None
_tool_modules_loaded = False
_tool_import_lock = threading.Lock()


def _resolve_gate_config_path() -> Path | None:
    env_path = os.getenv("BR_GATES_CONFIG_PATH")
    if env_path:
        candidate = Path(env_path).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        if candidate.exists():
            return candidate
        logger.warning(
            "BR_GATES_CONFIG_PATH is set but file does not exist: %s", candidate
        )

    # Search repo parents + cwd to handle different layouts (dev, package, worktree).
    roots = [Path.cwd(), *Path(__file__).resolve().parents]
    seen: set[Path] = set()
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        for rel in (
            Path("configs/gates.yaml"),
            Path("configs/gates.yml"),
        ):
            candidate = root / rel
            if candidate.exists():
                return candidate
    return None


def _parse_violations(raw: Any) -> List[Violation]:
    violations: List[Violation] = []
    if not isinstance(raw, list):
        return violations
    for item in raw:
        if isinstance(item, Violation):
            violations.append(item)
            continue
        if isinstance(item, str):
            violations.append(Violation(code=item, message=item))
            continue
        if isinstance(item, dict):
            try:
                violations.append(Violation.model_validate(item))
                continue
            except Exception:
                code = item.get("code") or "violation"
                message = item.get("message") or str(code)
                violations.append(Violation(code=str(code), message=str(message)))
                continue
    return violations


def _merge_errors(*parts: Optional[str]) -> Optional[str]:
    chunks = [p for p in parts if p]
    if not chunks:
        return None
    return "; ".join(chunks)


if TYPE_CHECKING:  # pragma: no cover
    from brain_researcher.services.agent.planner.evidence import ToolEvidenceWriter
    from brain_researcher.services.orchestrator.job_store import JobRecord


class ResourceUsageTracker:
    """Capture coarse resource metrics during job execution."""

    def __init__(self) -> None:
        self._start_time = time.time()
        self._proc = psutil.Process(os.getpid()) if psutil else None
        if self._proc:
            cpu_times = self._proc.cpu_times()
            self._start_cpu_user = cpu_times.user
            self._start_cpu_system = cpu_times.system
        else:  # pragma: no cover - psutil unavailable
            self._start_cpu_user = 0.0
            self._start_cpu_system = 0.0

    def snapshot(self) -> Dict[str, Any]:
        metrics: Dict[str, Any] = {
            "duration_ms": int(max(time.time() - self._start_time, 0) * 1000)
        }
        if self._proc:
            try:
                cpu_times = self._proc.cpu_times()
                metrics["cpu_user_sec"] = max(
                    0.0, cpu_times.user - self._start_cpu_user
                )
                metrics["cpu_system_sec"] = max(
                    0.0, cpu_times.system - self._start_cpu_system
                )
                rss_mb = self._proc.memory_info().rss / (1024 * 1024)
                metrics["rss_mb"] = round(rss_mb, 2)
            except (psutil.Error, OSError):  # pragma: no cover - best effort
                pass
        return metrics


def _merge_resource_usage(
    primary: Optional[Dict[str, Any]],
    tracker_metrics: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not primary and not tracker_metrics:
        return None
    merged: Dict[str, Any] = {}
    if tracker_metrics:
        merged.update(tracker_metrics)
    if primary:
        merged.update(primary)
    return merged


def _prune_registry_for_allowlist(registry, settings: Settings) -> int:
    """Remove tools blocked by the environment allowlist."""

    if settings.allow_all_tools:
        return 0

    removed = 0
    for tool_name in list(getattr(registry, "tools", {}).keys()):
        try:
            allowed = settings.is_tool_allowed(tool_name)
        except Exception:
            allowed = True
        if allowed:
            continue
        registry.tools.pop(tool_name, None)
        if hasattr(registry, "tool_descriptions"):
            registry.tool_descriptions.pop(tool_name, None)
        removed += 1

    return removed


def _ensure_tool_modules_loaded() -> None:
    """Import agent tool modules so ToolRegistry discovery sees stubs."""

    global _tool_modules_loaded
    if _tool_modules_loaded:
        return

    with _tool_import_lock:
        if _tool_modules_loaded:
            return

        try:
            from brain_researcher.services.agent import tools as tools_pkg

            module_names = list(getattr(tools_pkg, "__all__", []))
            if not module_names:
                pkg_path = Path(tools_pkg.__file__).parent
                module_names = [
                    path.stem
                    for path in pkg_path.glob("*.py")
                    if not path.name.startswith("_")
                ]

            loaded = 0
            for short_name in sorted(module_names):
                module_path = f"{tools_pkg.__name__}.{short_name}"
                try:
                    importlib.import_module(module_path)
                except Exception as exc:  # pragma: no cover - best effort logging
                    logger.debug("Skipping tool module %s: %s", module_path, exc)
                    continue
                loaded += 1

            _tool_modules_loaded = True
            logger.info("Imported %d agent tool modules for plan executor", loaded)
        except Exception as exc:  # pragma: no cover - logging only
            logger.warning("Unable to preload agent tool modules: %s", exc)


def _is_test_env() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


def _quote_grounded_enabled() -> bool:
    raw = os.getenv("BR_QUOTE_GROUNDED_ENABLED", "").strip().lower()
    return raw in {"1", "true", "yes", "y", "on"}


def _get_shared_plan_tool_executor(settings: Settings) -> Optional["ToolExecutor"]:
    """Lazily construct a ToolExecutor for plan/DAG jobs."""

    if not TOOL_EXECUTOR_AVAILABLE:
        return None
    if _is_test_env():
        return None

    global _shared_plan_executor
    if _shared_plan_executor is not None:
        return _shared_plan_executor

    with _plan_executor_lock:
        if _shared_plan_executor is not None:
            return _shared_plan_executor

        try:
            _ensure_tool_modules_loaded()
            from brain_researcher.services.tools.tool_registry import ToolRegistry

            registry = ToolRegistry.from_env(auto_discover=True)
            removed = _prune_registry_for_allowlist(registry, settings)
            executor = ToolExecutor(
                tool_registry=registry,
                safe_mode=settings.sandbox_enabled,
                max_workers=max(1, settings.dag_max_concurrency),
                bg_loop_name="PlanExecutor-AsyncLoop",
            )
            _shared_plan_executor = executor
            logger.info(
                "Initialized plan ToolExecutor with %d tools (removed %d disallowed)",
                len(registry.get_all_tools()),
                removed,
            )
            return executor
        except Exception as exc:  # pragma: no cover - logging only
            logger.error(
                "Failed to initialize plan ToolExecutor: %s", exc, exc_info=True
            )
            return None


class ResourceUsageTracker:
    """Capture coarse resource metrics during job execution."""

    def __init__(self) -> None:
        self._start_time = time.time()
        self._proc = psutil.Process(os.getpid()) if psutil else None
        if self._proc:
            cpu_times = self._proc.cpu_times()
            self._start_cpu_user = cpu_times.user
            self._start_cpu_system = cpu_times.system
        else:  # pragma: no cover - psutil unavailable
            self._start_cpu_user = 0.0
            self._start_cpu_system = 0.0

    def snapshot(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "duration_ms": int(max(time.time() - self._start_time, 0) * 1000)
        }
        if self._proc:
            try:
                cpu_times = self._proc.cpu_times()
                data["cpu_user_sec"] = max(0.0, cpu_times.user - self._start_cpu_user)
                data["cpu_system_sec"] = max(
                    0.0, cpu_times.system - self._start_cpu_system
                )
                rss_mb = self._proc.memory_info().rss / (1024 * 1024)
                data["rss_mb"] = round(rss_mb, 2)
            except (psutil.Error, OSError):  # pragma: no cover - best effort
                pass
        return data


def _merge_resource_usage(
    primary: Optional[Dict[str, Any]],
    tracker_metrics: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not primary and not tracker_metrics:
        return None
    merged: Dict[str, Any] = {}
    if tracker_metrics:
        merged.update(tracker_metrics)
    if primary:
        merged.update(primary)
    return merged


class JobWorker:
    """
    Worker that claims and executes jobs from JobStore.

    Implements the standard worker pattern:
    1. Claim next available job using claim_next()
    2. Send periodic heartbeats using heartbeat()
    3. Update state using update_state()
    4. Handle cancellation signals
    """

    def __init__(
        self,
        job_store: JobStore,
        worker_id: str,
        lease_ttl: int = 60,
        heartbeat_interval: int = 30,
        tool_executor: Optional[ToolExecutor] = None,
        plan_tool_executor: Optional[ToolExecutor] = None,
        evidence_writer: "ToolEvidenceWriter | None" = None,
    ):
        """
        Initialize worker.

        Args:
            job_store: JobStore instance to claim jobs from
            worker_id: Unique identifier for this worker
            lease_ttl: Lease time-to-live in seconds (default: 60)
            heartbeat_interval: Interval between heartbeats in seconds (default: 30)
            tool_executor: Optional ToolExecutor instance for job execution
        """
        self.job_store = job_store
        self.worker_id = worker_id
        self.lease_ttl = lease_ttl
        self.heartbeat_interval = heartbeat_interval
        self.running = False
        self.current_job_id: Optional[str] = None
        self._heartbeat_task: Optional[asyncio.Task] = None

        # Set up graceful shutdown
        self._shutdown_event = asyncio.Event()

        self.settings = get_settings()

        if _tool_executor_required() and not TOOL_EXECUTOR_AVAILABLE:
            raise RuntimeError(
                "ToolExecutor is required but could not be imported. "
                "Install/enable the agent tool executor dependencies or set "
                "BR_REQUIRE_TOOL_EXECUTOR=false to allow stub execution."
            )

        # Tool executor for job execution
        if tool_executor is None and TOOL_EXECUTOR_AVAILABLE and not _is_test_env():
            self.tool_executor = ToolExecutor(bg_loop_name="WorkerExecutor-AsyncLoop")
        else:
            self.tool_executor = tool_executor
        if _tool_executor_required() and self.tool_executor is None:
            raise RuntimeError(
                "ToolExecutor is required but was not initialized for this worker. "
                "Provide tool_executor explicitly or ensure ToolExecutor can be constructed."
            )
        if plan_tool_executor is None and not _is_test_env():
            plan_tool_executor = _get_shared_plan_tool_executor(self.settings)
        self.plan_tool_executor = plan_tool_executor

        # Optional dependency-injected writer so unit tests do not require Neo4j.
        self._evidence_writer = evidence_writer

        # Optional gate engine (QC/validation). Loaded best-effort.
        self.gate_engine: GateEngine | None = None
        try:
            gate_path = _resolve_gate_config_path()
            if gate_path is not None:
                self.gate_engine = GateEngine.from_yaml(gate_path)
                logger.info(
                    "Gate engine loaded with %d rules from %s",
                    len(self.gate_engine.rules),
                    gate_path,
                )
            else:
                logger.debug("Gate engine config not found")
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug("Gate engine load failed: %s", exc)

    async def _run_in_executor(self, func, *args):
        """Run a blocking callable in an executor, isolating test env threads."""
        loop = asyncio.get_running_loop()
        test_executor: ThreadPoolExecutor | None = None
        run_executor: ThreadPoolExecutor | None = None
        if _is_test_env() and hasattr(loop, "set_default_executor"):
            test_executor = ThreadPoolExecutor(max_workers=1)
            run_executor = test_executor
        try:
            return await loop.run_in_executor(run_executor, func, *args)
        finally:
            if test_executor is not None:
                test_executor.shutdown(wait=True)

    def _get_plan_tool_executor(self):
        """Return the executor to use for plan/DAG jobs."""

        if self.plan_tool_executor is not None:
            return self.plan_tool_executor
        if self.tool_executor is None:
            logger.warning(
                "Plan ToolExecutor unavailable; plan_execution jobs will fail"
            )
        return self.tool_executor

    def _evaluate_gates(
        self,
        stage: str,
        context: Dict[str, Any],
        component: str | None = "worker",
        step_id: str | None = None,
    ) -> List[Violation]:
        """Run gate evaluations for the given stage and context."""
        if not self.gate_engine:
            return []
        evaluations = self.gate_engine.evaluate(
            context=context, stage=stage, component=component, step_id=step_id
        )
        return [ev.violation for ev in evaluations if ev.violation]

    @staticmethod
    def _emit_terminal_metric(
        job_id: str,
        attempt: int,
        final_state: str,
        exit_code: int | None,
        final_error: str | None,
        duration_seconds: float | None = None,
        job_kind: str | None = None,
    ) -> None:
        """Best-effort structured metric for terminal job outcomes."""
        try:
            # Determine reason label
            if final_state == JobState.SUCCEEDED:
                reason_label = "success"
            elif final_state == JobState.CANCELLED:
                reason_label = "cancelled"
            elif final_state == JobState.TIMEOUT:
                reason_label = "timeout"
            else:
                # Attempt classification for failures
                try:
                    from brain_researcher.services.orchestrator.retry import (  # local import
                        classify_failure,
                    )

                    reason_label = (
                        classify_failure(exit_code or -1, final_error or "") or "failed"
                    )
                except Exception:
                    reason_label = "failed"

            logger.info(
                "METRIC: job_final_state_total",
                extra={
                    "metric_name": "job_final_state_total",
                    "job_id": job_id,
                    "attempt": attempt,
                    "outcome": (
                        final_state.value
                        if hasattr(final_state, "value")
                        else str(final_state)
                    ),
                    "reason": reason_label,
                    "exit_code": exit_code,
                },
            )

            # Record Prometheus metrics (P5.11)
            if duration_seconds is not None and job_kind is not None:
                try:
                    from .metrics import get_metrics_collector

                    metrics = get_metrics_collector()
                    # Map JobState to metric state labels
                    state_label = (
                        final_state.value
                        if hasattr(final_state, "value")
                        else str(final_state).lower()
                    )
                    metrics.record_job_completed(
                        kind=job_kind, state=state_label, duration=duration_seconds
                    )
                except Exception as e:
                    logger.debug(
                        f"Failed to record Prometheus job completion metric: {e}"
                    )
        except Exception:
            # Never break execution due to metrics
            pass

    async def start(self):
        """Start the worker loop."""
        self.running = True
        logger.info(f"Worker {self.worker_id} starting")

        try:
            while self.running:
                # Check for shutdown signal
                if self._shutdown_event.is_set():
                    logger.info(f"Worker {self.worker_id} received shutdown signal")
                    break

                try:
                    # Claim next job
                    job = await self.job_store.claim_next(
                        worker_id=self.worker_id, lease_ttl=self.lease_ttl
                    )

                    if job is None:
                        # No jobs available, sleep briefly
                        await asyncio.sleep(5)
                        continue

                    # Execute job
                    self.current_job_id = job.job_id
                    logger.info(f"Worker {self.worker_id} claimed job {job.job_id}")

                    # Start heartbeat task
                    self._heartbeat_task = asyncio.create_task(
                        self._send_heartbeats(job.job_id)
                    )

                    # Execute job
                    await self._execute_job(job)

                    # Stop heartbeat
                    if self._heartbeat_task:
                        self._heartbeat_task.cancel()
                        try:
                            await self._heartbeat_task
                        except asyncio.CancelledError:
                            pass
                        self._heartbeat_task = None

                    self.current_job_id = None

                except asyncio.CancelledError:
                    logger.info(f"Worker {self.worker_id} cancelled")
                    break
                except Exception as e:
                    logger.error(f"Worker {self.worker_id} error: {e}", exc_info=True)
                    # Continue processing other jobs
                    await asyncio.sleep(1)

        finally:
            self.running = False
            logger.info(f"Worker {self.worker_id} stopped")

    async def stop(self):
        """Stop the worker gracefully."""
        logger.info(f"Stopping worker {self.worker_id}")
        self.running = False
        self._shutdown_event.set()

        # Cancel heartbeat if running
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        # If currently processing a job, try to release it
        if self.current_job_id:
            try:
                # Reset worker_id so job can be reclaimed
                await self.job_store.update_state(
                    self.current_job_id, JobState.QUEUED, worker_id=None
                )
                logger.info(f"Released job {self.current_job_id} back to queue")
            except Exception as e:
                logger.error(f"Failed to release job {self.current_job_id}: {e}")

    async def _send_heartbeats(self, job_id: str):
        """
        Send periodic heartbeats for a job.

        Args:
            job_id: Job ID to send heartbeats for
        """
        try:
            while True:
                await asyncio.sleep(self.heartbeat_interval)

                # Send heartbeat
                result = await self.job_store.heartbeat(
                    worker_id=self.worker_id, job_id=job_id, lease_ttl=self.lease_ttl
                )

                if result is None or result == 0:
                    logger.warning(
                        f"Heartbeat failed for job {job_id} - may have been cancelled"
                    )
                    # Job may have been cancelled or reassigned
                    break

                logger.debug(f"Sent heartbeat for job {job_id}")

        except asyncio.CancelledError:
            logger.debug(f"Heartbeat task cancelled for job {job_id}")
        except Exception as e:
            logger.error(f"Heartbeat error for job {job_id}: {e}")

    async def _add_retry_metadata_to_provenance(
        self,
        provenance_path: str,
        job: "JobRecord",
    ):
        """
        Add retry metadata to provenance.json file (P2.6).

        Adds information about retry attempts, category, and delays
        to help users understand execution history.

        Args:
            provenance_path: Path to provenance.json file
            job: JobRecord with retry metadata
        """
        import json
        from pathlib import Path

        try:
            prov_file = Path(provenance_path)
            if not prov_file.exists():
                logger.warning(f"Provenance file not found: {provenance_path}")
                return

            # Load existing provenance
            with open(prov_file, "r") as f:
                provenance = json.load(f)

            # Add retry metadata
            provenance["retry_metadata"] = {
                "attempt_number": job.attempt,
                "max_attempts": job.max_attempts,
                "is_retry": job.attempt > 1,
                "total_attempts": job.attempt,  # This is the current/final attempt
            }

            # Write back
            with open(prov_file, "w") as f:
                json.dump(provenance, f, indent=2)

            logger.info(
                f"Added retry metadata to provenance: "
                f"attempt {job.attempt}/{job.max_attempts}"
            )

        except Exception as e:
            # Don't fail job if provenance update fails
            logger.warning(f"Failed to update provenance with retry metadata: {e}")

    async def _finalize_job(
        self,
        job_id: str,
        exit_code: int,
        error_message: Optional[str] = None,
        run_id: Optional[str] = None,
        run_dir: Optional[str] = None,
        provenance_path: Optional[str] = None,
        actual_resources: Optional[Dict[str, Any]] = None,
        payload_json: Optional[str] = None,
    ):
        """
        Finalize job state with cancel-wins rule and retry logic (P2.6).

        Implements CF-4 cancel-wins finalization with P2.6 retry:
        - If cancellation was requested, always mark as CANCELLED (cancel wins)
        - If exit_code != 0, check retry eligibility:
            - If retryable: transition to RETRYING, schedule delayed retry
            - If not retryable: mark as FAILED/TIMEOUT
        - Otherwise, use exit_code to determine final state:
            - 0 → SUCCEEDED
            - 124 → TIMEOUT (if not retrying)
            - other → FAILED (if not retrying)

        This prevents race conditions where a job completes successfully
        but cancellation was requested during execution.

        Args:
            job_id: Job ID to finalize
            exit_code: Process exit code
            error_message: Optional error message
            run_id: Optional run ID for provenance
            run_dir: Optional run directory
            provenance_path: Optional provenance file path
            actual_resources: Optional actual resource usage data (P3.7)
        """
        # Re-fetch job to check for cancellation requests
        current_job = await self.job_store.get(job_id)
        if not current_job:
            logger.warning(f"Job {job_id} not found during finalization")
            return

        # Determine attempt number for this completion (1-indexed)
        current_attempt = (current_job.attempt or 0) + 1

        retry_decision = None

        # Apply cancel-wins rule
        if current_job.cancel_reason or current_job.cancellation_requested:
            # Cancel wins - override exit code
            final_state = JobState.CANCELLED
            final_error = (
                f"Cancelled: {current_job.cancel_reason or 'Cancellation requested'}"
            )
            logger.info(
                f"Job {job_id} finalized as CANCELLED (cancel-wins), exit_code={exit_code}"
            )

        elif exit_code == 0:
            final_state = JobState.SUCCEEDED
            final_error = None
            logger.info(f"Job {job_id} finalized as SUCCEEDED")

        else:
            # P2.6: Check retry eligibility for failed jobs
            from brain_researcher.config.retry_settings import get_retry_settings
            from brain_researcher.services.orchestrator.retry import (
                format_retry_summary,
                should_retry,
            )

            retry_settings = get_retry_settings()
            retry_decision = should_retry(
                exit_code=exit_code,
                stderr=error_message or "",
                attempt=current_attempt,
                job_id=job_id,
                settings=retry_settings,
            )

            if retry_decision.should_retry:
                # Transition to RETRYING state with delayed execution
                run_after_ts = (
                    int(retry_decision.next_retry_at.timestamp())
                    if retry_decision.next_retry_at
                    else None
                )

                # Release any GPU slots held by the failed attempt so retries and
                # other jobs can acquire them immediately.
                try:
                    await self.job_store.release_gpus(job_id)
                except AttributeError:
                    # Legacy backends may not implement release_gpus; ignore.
                    pass

                await self.job_store.update_state(
                    job_id,
                    JobState.RETRYING,
                    run_after=run_after_ts,
                    attempt=current_attempt,
                    max_attempts=retry_decision.max_attempts,
                    error_message=f"Retry scheduled: {retry_decision.reason}",
                    worker_id=None,
                    lease_expires_at=None,
                    claimed_at=None,
                    last_heartbeat=None,
                )

                # Log retry decision
                summary = format_retry_summary(retry_decision)
                logger.info(f"Job {job_id} will retry: {summary}")

                # One structured line per decision for ingestion
                try:
                    logger.info(
                        "retry_decision",
                        extra={
                            "event": "retry_decision",
                            "job_id": job_id,
                            "attempt": current_attempt,
                            "reason": retry_decision.reason,
                            "category": retry_decision.category,
                            "delay_seconds": retry_decision.delay_seconds,
                            "next_retry_at": (
                                retry_decision.next_retry_at.isoformat()
                                if retry_decision.next_retry_at
                                else None
                            ),
                            "max_attempts": retry_decision.max_attempts,
                        },
                    )
                except Exception:
                    pass

                # Persist retry scheduling as replayable event (best-effort).
                try:
                    await emit_job_event(
                        self.job_store,
                        job_id=job_id,
                        event_type="retry_scheduled",
                        payload={
                            "attempt": current_attempt,
                            "max_attempts": retry_decision.max_attempts,
                            "category": retry_decision.category,
                            "delay_seconds": retry_decision.delay_seconds,
                            "next_retry_at": run_after_ts,
                            "reason": retry_decision.reason,
                        },
                        run_id=str(run_id or current_job.run_id or job_id),
                        run_dir=run_dir or current_job.run_dir,
                    )
                except Exception:  # pragma: no cover - best effort
                    pass

                # Emit a durable metric event for retry delay (best-effort). This is
                # useful for downstream observability even when logs/SSE are not
                # collected.
                try:
                    delay_seconds = retry_decision.delay_seconds
                    try:
                        delay_value = (
                            float(delay_seconds) if delay_seconds is not None else 0.0
                        )
                    except Exception:
                        delay_value = 0.0

                    metric_tags: Dict[str, str] = {}
                    if retry_decision.category:
                        metric_tags["category"] = str(retry_decision.category)
                    metric_tags["attempt"] = str(current_attempt)

                    await emit_job_event(
                        self.job_store,
                        job_id=job_id,
                        event_type="metric",
                        payload={
                            "name": "retry.delay_seconds",
                            "value": delay_value,
                            "unit": "s",
                            "tags": metric_tags,
                            "details": {
                                "attempt": current_attempt,
                                "max_attempts": retry_decision.max_attempts,
                                "next_retry_at": run_after_ts,
                                "reason": retry_decision.reason,
                            },
                        },
                        run_id=str(run_id or current_job.run_id or job_id),
                        run_dir=run_dir or current_job.run_dir,
                    )
                except Exception:  # pragma: no cover - best effort
                    pass

                # Best-effort SSE notify (if enhanced app is running)
                try:
                    from .main_enhanced import job_updates  # type: ignore

                    q = job_updates.get(job_id)
                    if q is not None:
                        await q.put(
                            {
                                "type": "retry_scheduled",
                                "job_id": job_id,
                                "status": "retrying",
                                "attempt": current_attempt,
                                "delay_seconds": retry_decision.delay_seconds,
                                "next_retry_at": run_after_ts,
                                "category": retry_decision.category,
                            }
                        )
                except Exception as e:
                    logger.debug("SSE retry_scheduled emit failed: %s", e)

                # Keep cache in pending state (don't mark failed)
                # Early return - don't finalize as FAILED yet
                return

            # Not retrying - proceed with finalization
            if exit_code == 124:
                final_state = JobState.TIMEOUT
                final_error = error_message or "Execution timed out"
                logger.info(
                    f"Job {job_id} finalized as TIMEOUT (not retrying: {retry_decision.reason})"
                )
            else:
                final_state = JobState.FAILED
                final_error = error_message or f"Exit code {exit_code}"
                logger.info(
                    f"Job {job_id} finalized as FAILED (not retrying: {retry_decision.reason}), exit_code={exit_code}"
                )

        # P3.7: Release GPU slots for all terminal states (CANCELLED, FAILED, TIMEOUT, SUCCEEDED)
        # This ensures resources are freed immediately regardless of job outcome
        if final_state in (
            JobState.CANCELLED,
            JobState.FAILED,
            JobState.TIMEOUT,
            JobState.SUCCEEDED,
        ):
            try:
                await self.job_store.release_gpus(job_id)
                logger.debug(
                    f"Released GPU slots for job {job_id} in state {final_state.value}"
                )
            except AttributeError:
                # Legacy backends may not implement release_gpus; ignore.
                pass
            except Exception as e:
                logger.warning(f"Failed to release GPU slots for job {job_id}: {e}")

        # Update final state
        update_kwargs = {
            "finished_at": int(time.time()),
            "exit_code": exit_code,
            "error_message": final_error,
            "run_id": run_id,
            "run_dir": run_dir,
            "provenance_path": provenance_path,
            "attempt": current_attempt,
        }
        if payload_json is not None:
            update_kwargs["payload_json"] = payload_json

        if retry_decision is not None:
            update_kwargs["max_attempts"] = retry_decision.max_attempts

        # P3.7: Store actual resource usage in job metadata
        if actual_resources:
            update_kwargs["actual_resources"] = actual_resources

        await self.job_store.update_state(
            job_id,
            final_state,
            **update_kwargs,
        )

        # Persist terminal state as replayable event (best-effort).
        try:
            final_state_value = (
                final_state.value if hasattr(final_state, "value") else str(final_state)
            )
            normalized_state = str(final_state_value or "").strip().lower()
            status_map = {
                "succeeded": "succeeded",
                "success": "succeeded",
                "failed": "failed",
                "error": "failed",
                "cancelled": "cancelled",
                "canceled": "cancelled",
                "timeout": "timeout",
                "skipped": "skipped",
            }
            completed_status = status_map.get(normalized_state, "failed")
            await emit_job_event(
                self.job_store,
                job_id=job_id,
                event_type="analysis.completed",
                payload={
                    "status": completed_status,
                    "message": str(final_error) if final_error else None,
                    "state": (
                        final_state.value
                        if hasattr(final_state, "value")
                        else str(final_state)
                    ),
                    "exit_code": exit_code,
                    "error": final_error,
                    "attempt": current_attempt,
                    "max_attempts": update_kwargs.get("max_attempts"),
                    "run_dir": run_dir,
                    "provenance_path": provenance_path,
                },
                run_id=str(run_id or job_id),
                run_dir=run_dir,
            )
        except Exception:  # pragma: no cover - best effort
            pass

        if final_state == JobState.SUCCEEDED and run_dir:
            await self._write_quote_grounded_artifacts(job_id, run_dir)
            await self._write_analysis_manifest(job_id, run_dir)

        if run_dir and final_state in (
            JobState.CANCELLED,
            JobState.FAILED,
            JobState.TIMEOUT,
            JobState.SUCCEEDED,
        ):
            await self._write_inputs_manifest(job_id, run_dir)
            await self._write_observation_manifest(job_id, run_dir)
            if final_state == JobState.SUCCEEDED:
                await self._write_artifact_manifest(job_id, run_dir)
            await self._write_analysis_bundle_manifest(job_id, run_dir)
        # Emit terminal metric line (best-effort)
        try:
            # Calculate duration for Prometheus metrics (P5.11)
            duration_seconds = None
            job_kind = None
            payload = {}
            if current_job:
                finished_at = update_kwargs.get("finished_at", int(time.time()))
                if current_job.created_at:
                    duration_seconds = finished_at - current_job.created_at
                try:
                    payload = (
                        json.loads(current_job.payload_json)
                        if current_job.payload_json
                        else {}
                    )
                except Exception:
                    payload = {}
                job_kind = payload.get("metadata", {}).get("job_kind")
                if not job_kind:
                    job_kind = resolve_job_kind(payload=payload)

            self._emit_terminal_metric(
                job_id=job_id,
                attempt=current_attempt,
                final_state=final_state,
                exit_code=exit_code,
                final_error=final_error,
                duration_seconds=duration_seconds,
                job_kind=job_kind,
            )
        except Exception:
            pass

        # Update cache (P2.5)
        try:
            from .main_enhanced import cache_store

            if cache_store:
                # Get job metadata to check for cache_key
                current_job = await self.job_store.get(job_id)
                if current_job:
                    payload = json.loads(current_job.payload_json)
                    metadata = payload.get("metadata", {})
                    cache_key = metadata.get("cache_key")

                    if cache_key:
                        if final_state == JobState.SUCCEEDED:
                            # Mark cache completed
                            size_bytes = None
                            if run_dir:
                                from pathlib import Path

                                try:
                                    run_path = Path(run_dir)
                                    if run_path.exists():
                                        size_bytes = sum(
                                            f.stat().st_size
                                            for f in run_path.rglob("*")
                                            if f.is_file()
                                        )
                                except Exception:
                                    pass

                            success = await cache_store.mark_completed(
                                cache_key=cache_key,
                                run_id=job_id,
                                run_dir=run_dir or "",
                                size_bytes=size_bytes,
                            )

                            if success:
                                logger.info(
                                    f"✓ Marked cache entry {cache_key[:16]}... as completed"
                                )
                            else:
                                logger.warning(
                                    f"✗ Failed to mark cache entry {cache_key[:16]}... as completed"
                                )
                            await self._annotate_cache_metadata(
                                job_id,
                                cache_key,
                                hit=True,
                                run_dir=run_dir,
                                metadata=metadata,
                                payload=payload,
                                job_record=current_job,
                            )
                            await self._emit_cache_event(
                                job_id, {"key": cache_key, "hit": True}
                            )

                        elif final_state in (JobState.FAILED, JobState.TIMEOUT):
                            # Mark cache failed (only if still pending)
                            error_msg = final_error or f"Job {final_state.value}"
                            await cache_store.mark_failed(
                                cache_key=cache_key,
                                run_id=job_id,
                                error=error_msg,
                            )
                            logger.info(
                                f"Marked cache entry {cache_key[:16]}... as failed"
                            )
                            await self._annotate_cache_metadata(
                                job_id,
                                cache_key,
                                hit=False,
                                error=error_msg,
                                run_dir=run_dir,
                                metadata=metadata,
                                payload=payload,
                                job_record=current_job,
                            )
                            await self._emit_cache_event(
                                job_id,
                                {"key": cache_key, "hit": False, "error": error_msg},
                            )

        except Exception as e:
            logger.error(f"Failed to update cache: {e}", exc_info=True)

    def _sort_steps_by_dependencies(
        self, steps: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Return plan steps ordered by explicit + implicit dependencies.

        The orchestrator historically accepted plan payloads that either declared
        `depends_on` relationships or relied on artifact flow (`produces` /
        `consumes`).  This helper merges both sources into a single DAG and
        performs a deterministic topological sort.  If a cycle is detected we
        log a warning and return the original order so legacy plans still run.
        """

        if not steps:
            return []

        step_by_id: Dict[str, Dict[str, Any]] = {}
        original_index: Dict[str, int] = {}
        produced_by: Dict[str, str] = {}
        step_ids: List[str] = []

        for idx, step in enumerate(steps):
            step_id = step.get("id") or step.get("step_id") or f"step-{idx:04d}"
            step_id = str(step_id)
            step_by_id[step_id] = step
            original_index[step_id] = idx
            step_ids.append(step_id)

            produces = step.get("produces") or {}
            if isinstance(produces, dict):
                for artifact in produces.values():
                    if (
                        isinstance(artifact, str)
                        and artifact
                        and artifact not in produced_by
                    ):
                        produced_by[artifact] = step_id

        graph: Dict[str, set[str]] = {sid: set() for sid in step_ids}
        indegree: Dict[str, int] = {sid: 0 for sid in step_ids}

        for step_id in step_ids:
            step = step_by_id[step_id]
            dependencies: set[str] = set()

            explicit = step.get("depends_on") or []
            for dep in explicit:
                if isinstance(dep, str):
                    normalized = dep.strip()
                    if normalized and normalized in graph and normalized != step_id:
                        dependencies.add(normalized)

            consumes = step.get("consumes") or {}
            if isinstance(consumes, dict):
                for artifact in consumes.values():
                    if isinstance(artifact, str):
                        producer = produced_by.get(artifact)
                        if producer and producer != step_id:
                            dependencies.add(producer)

            for dep in dependencies:
                if step_id not in graph[dep]:
                    graph[dep].add(step_id)
                    indegree[step_id] += 1

        ready: List[tuple[int, str]] = [
            (original_index[sid], sid)
            for sid, degree in indegree.items()
            if degree == 0
        ]
        heapq.heapify(ready)

        ordered: List[str] = []
        while ready:
            _, current = heapq.heappop(ready)
            ordered.append(current)
            neighbors = sorted(
                graph[current],
                key=lambda sid: original_index.get(sid, float("inf")),
            )
            for neighbor in neighbors:
                indegree[neighbor] -= 1
                if indegree[neighbor] == 0:
                    heapq.heappush(ready, (original_index[neighbor], neighbor))

        if len(ordered) != len(step_ids):
            logger.warning(
                "Detected dependency cycle in plan steps; preserving original order"
            )
            return steps

        return [step_by_id[sid] for sid in ordered]

    async def _write_analysis_manifest(self, job_id: str, run_dir: str) -> None:
        """Best-effort emit analysis.json manifest for completed jobs."""
        try:
            if _is_test_env():
                return
            record = await self.job_store.get(job_id)
            if not record:
                return
            job = JobAdapter.from_record(record)
            output_dir = Path(run_dir)
            if not output_dir.exists():
                return
            from brain_researcher.core.analysis_manifest import save_analysis_manifest

            await self._run_in_executor(save_analysis_manifest, job, output_dir)
            logger.info("Saved analysis manifest for job %s", job_id)
        except Exception as exc:
            logger.warning(
                "Failed to write analysis manifest for job %s: %s", job_id, exc
            )

    async def _write_inputs_manifest(self, job_id: str, run_dir: str) -> None:
        """Best-effort emit inputs_manifest.json for terminal jobs."""
        try:
            if _is_test_env():
                return
            record = await self.job_store.get(job_id)
            if not record:
                return
            job = JobAdapter.from_record(record)
            output_dir = Path(run_dir)
            if not output_dir.exists():
                return
            from brain_researcher.core.inputs_manifest import save_inputs_manifest

            await self._run_in_executor(save_inputs_manifest, job, output_dir)
            logger.info("Saved inputs manifest for job %s", job_id)
        except Exception as exc:
            logger.warning(
                "Failed to write inputs manifest for job %s: %s", job_id, exc
            )

    async def _write_quote_grounded_artifacts(self, job_id: str, run_dir: str) -> None:
        """Best-effort emit quote-grounded evidence/claims artifacts for succeeded jobs."""
        try:
            if _is_test_env() or not _quote_grounded_enabled():
                return

            record = await self.job_store.get(job_id)
            if not record:
                return

            output_dir = Path(run_dir)
            if not output_dir.exists():
                return

            from brain_researcher.core.quote_grounded import (
                QUOTE_GROUNDED_CLAIMS_FILENAME,
                QUOTE_GROUNDED_EVIDENCE_ITEMS_FILENAME,
                QUOTE_GROUNDED_FILE_SEARCH_FILENAME,
                write_quote_grounded_artifacts,
            )

            # Idempotent: don't overwrite existing artifacts.
            if (output_dir / QUOTE_GROUNDED_EVIDENCE_ITEMS_FILENAME).exists() or (
                output_dir / QUOTE_GROUNDED_CLAIMS_FILENAME
            ).exists():
                return

            try:
                payload = json.loads(record.payload_json or "{}")
            except Exception:
                payload = {}

            query = (
                payload.get("prompt")
                or (payload.get("metadata") or {}).get("name")
                or record.job_name
                or ""
            )
            query = str(query or "").strip()
            if not query:
                return

            top_k = int(os.getenv("BR_QUOTE_GROUNDED_TOP_K", "5") or "5")
            payload_max_chars = int(
                os.getenv("BR_QUOTE_GROUNDED_PAYLOAD_MAX_CHARS", "4000") or "4000"
            )
            max_claims = int(os.getenv("BR_QUOTE_GROUNDED_MAX_CLAIMS", "10") or "10")

            def _generate():
                from brain_researcher.core.literature.gfs_store import search_gfs_auto

                store_override = (
                    os.getenv("BR_QUOTE_GROUNDED_FILE_SEARCH_STORE_NAMES")
                    or os.getenv("BR_QUOTE_GROUNDED_FILE_SEARCH_STORE")
                    or None
                )
                model_override = (
                    os.getenv("BR_QUOTE_GROUNDED_FILE_SEARCH_MODEL") or None
                )
                res = search_gfs_auto(
                    query,
                    top_k=max(1, top_k),
                    store=store_override,
                    model=model_override,
                    weak_evidence=True,
                    max_calls=2,
                )
                if not isinstance(res, dict) or res.get("status") != "ok":
                    return {"status": "skip", "reason": res.get("status"), "res": res}

                # Persist a small, reproducible search payload (without duplicating full text).
                try:
                    import hashlib

                    def _sha(text: str) -> str:
                        return hashlib.sha256(text.encode("utf-8")).hexdigest()

                    hits = []
                    for hit in res.get("hits") or []:
                        if not isinstance(hit, dict):
                            continue
                        text = (
                            hit.get("text") if isinstance(hit.get("text"), str) else ""
                        )
                        hits.append(
                            {
                                "doc_id": hit.get("doc_id"),
                                "title": hit.get("title"),
                                "score": hit.get("score"),
                                "pmid": hit.get("pmid"),
                                "pmcid": hit.get("pmcid"),
                                "doi": hit.get("doi"),
                                "snippet": hit.get("snippet"),
                                "text_sha256": _sha(text) if text else None,
                            }
                        )

                    (output_dir / QUOTE_GROUNDED_FILE_SEARCH_FILENAME).write_text(
                        json.dumps(
                            {
                                "schema_version": "quote-grounded-file-search-v1",
                                "query": query,
                                "status": res.get("status"),
                                "stores": res.get("stores")
                                or ([res.get("store")] if res.get("store") else None),
                                "model": res.get("model"),
                                "summary": res.get("summary"),
                                "hits": hits,
                                "anchors": res.get("anchors") or [],
                            },
                            ensure_ascii=False,
                            indent=2,
                            default=str,
                        ),
                        encoding="utf-8",
                    )
                except Exception:
                    pass

                return write_quote_grounded_artifacts(
                    run_dir=output_dir,
                    query=query,
                    hits=res.get("hits") or [],
                    payload_max_chars=max(1, payload_max_chars),
                    max_claims=max(1, max_claims),
                )

            result = await self._run_in_executor(_generate)
            if isinstance(result, dict) and result.get("status") == "ok":
                logger.info("Saved quote-grounded artifacts for job %s", job_id)
        except Exception as exc:
            logger.warning(
                "Failed to write quote-grounded artifacts for job %s: %s", job_id, exc
            )

    async def _write_artifact_manifest(self, job_id: str, run_dir: str) -> None:
        """Best-effort emit artifact_manifest.json for completed jobs."""
        try:
            if _is_test_env():
                return
            record = await self.job_store.get(job_id)
            if not record:
                return
            job = JobAdapter.from_record(record)
            output_dir = Path(run_dir)
            if not output_dir.exists():
                return
            from brain_researcher.core.artifact_manifest import save_artifact_manifest

            await self._run_in_executor(save_artifact_manifest, job, output_dir)
            logger.info("Saved artifact manifest for job %s", job_id)
        except Exception as exc:
            logger.warning(
                "Failed to write artifact manifest for job %s: %s", job_id, exc
            )

    async def _write_analysis_bundle_manifest(self, job_id: str, run_dir: str) -> None:
        """Best-effort emit analysis_bundle.json for terminal jobs."""
        try:
            if _is_test_env():
                return
            record = await self.job_store.get(job_id)
            if not record:
                return
            job = JobAdapter.from_record(record)
            output_dir = Path(run_dir)
            if not output_dir.exists():
                return
            from brain_researcher.core.analysis_bundle import save_analysis_bundle

            await self._run_in_executor(save_analysis_bundle, job, output_dir)
            logger.info("Saved analysis bundle for job %s", job_id)
        except Exception as exc:
            logger.warning(
                "Failed to write analysis bundle for job %s: %s", job_id, exc
            )

    async def _write_observation_manifest(self, job_id: str, run_dir: str) -> None:
        """Best-effort emit observation.json manifest for completed jobs."""
        try:
            record = await self.job_store.get(job_id)
            if not record:
                return
            if not record.run_dir:
                record.run_dir = run_dir

            from brain_researcher.services.orchestrator.observation import (
                persist_observation,
            )

            # NOTE: In some deployment environments, threadpool helpers can stall.
            # Persist synchronously to ensure observation.json is always produced.
            persist_observation(record)

            try:
                if record.payload_json:
                    await self.job_store.update_state(
                        job_id,
                        record.state,
                        payload_json=record.payload_json,
                    )
            except Exception as exc:  # pragma: no cover - best effort
                logger.debug(
                    "Failed to persist updated artifact checksums for job %s: %s",
                    job_id,
                    exc,
                )
            logger.info("Saved observation manifest for job %s", job_id)
        except Exception as exc:
            logger.debug(
                "Failed to write observation manifest for job %s: %s", job_id, exc
            )

    def _update_provenance_phases(
        self,
        provenance_path: str | None,
        workflow_result: Dict[str, Any],
        mask_reasons: list[Any] | None = None,
    ) -> None:
        """Best-effort merge phase metadata and mask reasons into provenance.json."""
        if not provenance_path:
            return
        try:
            prov_file = Path(provenance_path)
            if not prov_file.exists():
                return
            data = json.loads(prov_file.read_text())
            if not isinstance(data, dict):
                return

            if mask_reasons:
                parsed = _parse_violations(mask_reasons)
                if parsed:
                    data.setdefault("mask_reasons", [v.model_dump() for v in parsed])

            steps = data.get("steps") or data.get("child_runs")
            if not isinstance(steps, list):
                steps = None

            wr_steps = (
                workflow_result.get("steps")
                if isinstance(workflow_result, dict)
                else None
            )
            if steps is not None and isinstance(wr_steps, list):
                index: dict[str, dict[str, Any]] = {}
                for s in steps:
                    if isinstance(s, dict):
                        sid = str(
                            s.get("step_id") or s.get("id") or s.get("name") or ""
                        )
                        if sid:
                            index[sid] = s
                for wr in wr_steps:
                    if not isinstance(wr, dict):
                        continue
                    sid = str(wr.get("step_id") or wr.get("id") or wr.get("name") or "")
                    if not sid or sid not in index:
                        continue
                    target = index[sid]
                    for key in (
                        "preflight_result",
                        "exec_result",
                        "postcheck_result",
                        "violations",
                        "phases",
                    ):
                        if key in wr:
                            target[key] = wr.get(key)

            tmp = prov_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            tmp.replace(prov_file)
        except Exception:
            return

    async def _execute_plan_job(self, job, payload: Dict[str, Any]) -> None:
        """Execute a planner DAG job via DAGExecutor and ToolExecutor."""

        job_id = job.job_id
        plan_payload = payload.get("plan") or {}
        dag_payload = plan_payload.get("dag") or {}
        step_defs = dag_payload.get("steps") or []
        workflow_id = str(
            plan_payload.get("plan_id") or payload.get("plan_id") or job_id
        )
        run_id = job_id
        run_dir: Path | None = None
        try:
            from brain_researcher.config.run_artifacts import (
                build_run_dir,
                get_recorder_config,
            )

            cfg = get_recorder_config()
            root = cfg.root
            if not root.is_absolute():
                root = (Path.cwd() / root).resolve()
            run_dir = build_run_dir(root, run_id)
            job.run_id = run_id
            job.run_dir = str(run_dir)
            try:
                run_dir.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                logger.warning(
                    "Worker assigned run_dir for job %s but could not pre-create it (%s): %s",
                    job_id,
                    run_dir,
                    exc,
                )
            try:
                await self.job_store.update_state(
                    job_id,
                    None,
                    run_id=run_id,
                    run_dir=str(run_dir),
                )
            except Exception:
                pass
        except Exception:
            run_dir = None

        if _anchor_plan_step_output_dirs(step_defs, run_dir=run_dir):
            try:
                payload["plan"] = plan_payload
                job.payload_json = json.dumps(payload)
                await self.job_store.update_state(
                    job_id,
                    None,
                    payload_json=job.payload_json,
                )
            except Exception:
                pass

        start_ts = time.perf_counter()

        all_violations: List[Violation] = []
        preflight_results: Dict[str, Dict[str, Any]] = {}
        blocking_postcheck: List[Violation] = []

        def _step_id(raw: Dict[str, Any], idx: int) -> str:
            return str(
                raw.get("id")
                or raw.get("step_id")
                or raw.get("name")
                or f"step-{idx + 1:03d}"
            )

        # Run declarative preflight gates on step definitions
        if step_defs and self.gate_engine:
            blocking: List[Violation] = []
            for idx, raw in enumerate(step_defs):
                sid = _step_id(raw, idx)
                context = {
                    "step": raw,
                    "params": raw.get("params"),
                    "metadata": raw.get("metadata"),
                    "consumes": raw.get("consumes"),
                    "produces": raw.get("produces"),
                }
                step_violations = self._evaluate_gates(
                    stage="preflight",
                    context=context,
                    component="plan",
                    step_id=sid,
                )
                all_violations.extend(step_violations)
                status = "ok"
                if step_violations:
                    status = (
                        "blocked"
                        if any(v.blocking for v in step_violations)
                        else "warn"
                    )
                preflight_results[sid] = {
                    "status": status,
                    "violations": [v.model_dump() for v in step_violations],
                }
                if run_dir is not None:
                    log_trace_event(
                        run_dir,
                        run_id=workflow_id,
                        event_type="step_preflight_completed",
                        payload={
                            "job_id": job_id,
                            "plan_id": workflow_id,
                            "step_id": sid,
                            "preflight_result": preflight_results[sid],
                        },
                    )
                blocking.extend([v for v in step_violations if v.blocking])

            if blocking:
                # Persist violations onto payload metadata for observability
                try:
                    payload.setdefault("metadata", {})["violations"] = [
                        v.model_dump() for v in all_violations
                    ]
                    job.payload_json = json.dumps(payload)
                except Exception:
                    pass

                msg = "; ".join([f"{v.code}: {v.message}" for v in blocking])
                if run_dir is not None:
                    log_trace_event(
                        run_dir,
                        run_id=workflow_id,
                        event_type="plan_preflight_blocked",
                        payload={
                            "job_id": job_id,
                            "plan_id": workflow_id,
                            "error": msg,
                            "violations": [v.model_dump() for v in blocking],
                        },
                    )
                await self._finalize_job(
                    job_id=job_id,
                    exit_code=1,
                    error_message=f"Plan preflight blocked: {msg}",
                    payload_json=job.payload_json,
                )
                return

        if not step_defs:
            await self._finalize_job(
                job_id=job_id,
                exit_code=1,
                error_message="Plan is missing executable steps",
            )
            return

        env_allowlist = self.settings.tool_allowlist
        if env_allowlist:
            disallowed = [
                step.get("tool")
                for step in step_defs
                if step.get("tool") not in env_allowlist
            ]
            if disallowed:
                await self._finalize_job(
                    job_id=job_id,
                    exit_code=1,
                    error_message=f"Plan references disallowed tools: {sorted(set(disallowed))}",
                )
                return

        tool_executor = self._get_plan_tool_executor()
        if tool_executor is None:
            await self._finalize_job(
                job_id=job_id,
                exit_code=1,
                error_message="ToolExecutor unavailable for plan execution",
            )
            return

        from brain_researcher.services.tools.executors import create_recorder_factory

        def _branch_execution_enabled() -> bool:
            return os.getenv("BR_BRANCH_EXECUTION", "false").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }

        def _group_branch_steps(
            steps: List[Dict[str, Any]],
        ) -> Dict[str, List[Dict[str, Any]]]:
            groups: Dict[str, List[Dict[str, Any]]] = {}
            for step in steps:
                meta = step.get("metadata") or {}
                group_id = meta.get("branch_group_id")
                if not group_id:
                    continue
                groups.setdefault(str(group_id), []).append(step)
            return groups

        def _dedupe_branch_events(
            events: List[Dict[str, Any]], max_items: int = 200
        ) -> List[Dict[str, Any]]:
            seen: set[tuple[Any, Any, Any, Any]] = set()
            deduped: List[Dict[str, Any]] = []
            for event in events:
                key = (
                    event.get("event_type"),
                    event.get("branch_step_id"),
                    event.get("branch_rank"),
                    event.get("ts"),
                )
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(event)
            if max_items > 0 and len(deduped) > max_items:
                return deduped[-max_items:]
            return deduped

        branch_groups = _group_branch_steps(step_defs)
        branch_exec_enabled = _branch_execution_enabled()

        try:
            from .main_enhanced import job_updates  # type: ignore

            queue = job_updates.get(job_id)
        except Exception:
            queue = None

        branch_event_payloads: List[Dict[str, Any]] = []

        loop = asyncio.get_running_loop()

        plan_conf = plan_payload.get("plan_conf") or (
            plan_payload.get("run_summary") or {}
        ).get("plan_conf")

        def emit(event_type: str, data: Dict[str, Any]):
            event_payload = {
                "type": event_type,
                "job_id": job_id,
                "plan_id": workflow_id,
            }
            if plan_conf is not None:
                event_payload["plan_conf"] = plan_conf
            if data:
                event_payload.update(data)
            if isinstance(event_type, str) and event_type.startswith("branch_"):
                record = dict(event_payload)
                record.setdefault("event_type", event_type)
                record.setdefault("ts", datetime.utcnow().isoformat())
                branch_event_payloads.append(record)
            if run_dir is not None:
                log_trace_event(
                    run_dir,
                    run_id=workflow_id,
                    event_type=event_type,
                    payload=event_payload,
                )
            if not queue:
                return
            loop.call_soon_threadsafe(queue.put_nowait, event_payload)

        # If the plan declares a neurodesk primary_runtime, wrap the tool executor
        # so every step is compiled into a Neurodesk sbatch script and dispatched.
        # Default dispatch mode is "handoff" — BR returns immediately with the
        # compiled script artifact; execution ownership stays with the user /
        # Neurodesk environment.  Set BR_NEURODESK_MODE=local or k8s to change.
        primary_runtime = plan_payload.get("primary_runtime") or (
            plan_payload.get("run_summary") or {}
        ).get("primary_runtime")
        if primary_runtime == "neurodesk":
            try:
                from brain_researcher.services.tools.neurodesk_compiler import (
                    _HEAVY_TOOLS,
                    NeurodeskCompiler,
                    NeurodeskDispatcher,
                    NeurodeskToolExecutor,
                )

                nd_run_dir = (
                    run_dir or Path("/tmp/brain_researcher_neurodesk") / workflow_id
                )
                nd_cluster_cfg: Dict[str, Any] = (
                    plan_payload.get("cluster_config") or {}
                )

                # Auto-select mode: heavy tools default to handoff; env var overrides globally
                first_tool = ""
                try:
                    first_tool = plan_payload["dag"]["steps"][0].get("tool", "")
                except Exception:
                    pass
                default_mode = (
                    "handoff"
                    if any(h in first_tool for h in _HEAVY_TOOLS)
                    else os.getenv("BR_NEURODESK_MODE", "handoff")
                )
                nd_mode = os.getenv("BR_NEURODESK_MODE", default_mode)

                nd_compiler = NeurodeskCompiler(
                    nd_run_dir,
                    conda_env_name=os.getenv("BR_CONDA_ENV", "brain_researcher"),
                    cluster_config=nd_cluster_cfg,
                )
                nd_confirm = os.getenv("BR_NEURODESK_CONFIRM", "true").lower() not in (
                    "false",
                    "0",
                    "no",
                )
                nd_dispatcher = NeurodeskDispatcher(
                    mode=nd_mode,
                    config={
                        "run_dir": str(nd_run_dir),
                        "namespace": os.getenv("BR_K8S_NAMESPACE", "default"),
                        "neurodesk_image": os.getenv(
                            "BR_NEURODESK_IMAGE",
                            "ghcr.io/neurodesk/neurodesktop:latest",
                        ),
                        "cvmfs_host_path": os.getenv("BR_CVMFS_HOST_PATH", "/cvmfs"),
                        **nd_cluster_cfg,
                    },
                    confirm_before_dispatch=nd_confirm,
                )
                tool_executor = NeurodeskToolExecutor(
                    dispatcher=nd_dispatcher,
                    compiler=nd_compiler,
                    fallback_executor=tool_executor,
                )
                logger.info(
                    "Worker: using NeurodeskToolExecutor for plan %s (mode=%s)",
                    workflow_id,
                    nd_mode,
                )
            except Exception as nd_exc:
                logger.warning(
                    "Worker: failed to build NeurodeskToolExecutor, falling back to default: %s",
                    nd_exc,
                )

        dag_executor = DAGExecutor(
            tool_executor,
            create_recorder_factory(),
            max_concurrency=self.settings.dag_max_concurrency,
            event_callback=emit,
        )

        if run_dir is not None:
            log_trace_event(
                run_dir,
                run_id=workflow_id,
                event_type="plan_started",
                payload={"job_id": job_id, "plan_id": workflow_id},
            )

        if queue:
            await queue.put(
                {"type": "plan_started", "job_id": job_id, "plan_id": workflow_id}
            )

        workflow = None
        result: Optional[WorkflowResult] = None
        if branch_exec_enabled and branch_groups:
            if len(branch_groups) > 1 or len(step_defs) != sum(
                len(v) for v in branch_groups.values()
            ):
                logger.warning(
                    "Branch execution only supports a single branch group with no extra steps; "
                    "falling back to standard DAG execution for job %s",
                    job_id,
                )
            else:
                group_id, branch_steps = next(iter(branch_groups.items()))

                def _branch_rank(step: Dict[str, Any]) -> int:
                    meta = step.get("metadata") or {}
                    try:
                        return int(meta.get("branch_rank", 0))
                    except (TypeError, ValueError):
                        return 0

                branch_steps_sorted = sorted(branch_steps, key=_branch_rank)
                combined_results: List[Dict[str, Any]] = []
                branch_event_records: List[Dict[str, Any]] = []
                success = False
                last_error: Optional[str] = None
                last_failed_tool: Optional[str] = None

                def _planner_event(
                    event_type: str,
                    payload: Dict[str, Any],
                    diff: Dict[str, Any] | None = None,
                ) -> None:
                    try:
                        event_id = f"pev_{uuid.uuid4().hex[:10]}"
                    except Exception:
                        event_id = f"pev_{int(time.time() * 1000)}"
                    branch_event_records.append(
                        {
                            "event_type": event_type,
                            "ts": time.time(),
                            "event_id": event_id,
                            "payload": payload,
                            "diff": diff or {},
                        }
                    )

                for idx, raw in enumerate(branch_steps_sorted):
                    meta = raw.get("metadata") or {}
                    branch_rank = _branch_rank(raw)
                    branch_tool = raw.get("tool")
                    branch_step_id = str(
                        raw.get("id") or raw.get("step_id") or f"step-{idx + 1:03d}"
                    )
                    hypothesis_id = f"hyp:{branch_tool}" if branch_tool else None
                    branch_id = f"br:{branch_tool}" if branch_tool else None

                    if branch_rank > 0 and last_failed_tool and branch_tool:
                        _planner_event(
                            "recovery_triggered",
                            {
                                "from_tool": last_failed_tool,
                                "to_tool": branch_tool,
                                "branch_group_id": group_id,
                                "branch_rank": branch_rank,
                            },
                        )

                    _planner_event(
                        "branch_started",
                        {
                            "branch_group_id": group_id,
                            "branch_rank": branch_rank,
                            "branch_tool": branch_tool,
                            "branch_step_id": branch_step_id,
                            "branch_id": branch_id,
                            "hypothesis_id": hypothesis_id,
                        },
                    )

                    emit(
                        "branch_started",
                        {
                            "branch_group_id": group_id,
                            "branch_rank": branch_rank,
                            "branch_tool": branch_tool,
                            "branch_step_id": branch_step_id,
                        },
                    )

                    workflow_steps = self._prepare_workflow_steps([raw])
                    if not workflow_steps:
                        last_error = "Branch step missing tool definition"
                        if hypothesis_id:
                            _planner_event(
                                "branch_failed",
                                {
                                    "branch_group_id": group_id,
                                    "branch_rank": branch_rank,
                                    "branch_tool": branch_tool,
                                    "branch_step_id": branch_step_id,
                                    "branch_id": branch_id,
                                    "hypothesis_id": hypothesis_id,
                                    "error": last_error,
                                },
                                diff={
                                    "pending_remove": [hypothesis_id],
                                    "rejected_add": [hypothesis_id],
                                },
                            )
                        emit(
                            "branch_failed",
                            {
                                "branch_group_id": group_id,
                                "branch_rank": branch_rank,
                                "branch_tool": branch_tool,
                                "branch_step_id": branch_step_id,
                                "error": last_error,
                            },
                        )
                        last_failed_tool = branch_tool or last_failed_tool
                        continue

                    base_branch_metadata = (
                        plan_payload.get("metadata")
                        if isinstance(plan_payload.get("metadata"), dict)
                        else {}
                    )
                    branch_workflow = WorkflowDefinition(
                        workflow_id=f"{workflow_id}:branch:{branch_rank}",
                        steps=workflow_steps,
                        metadata={
                            **base_branch_metadata,
                            **(
                                {"run_dir": str(run_dir)} if run_dir is not None else {}
                            ),
                        },
                    )

                    try:
                        branch_result = await self._run_in_executor(
                            dag_executor.execute, branch_workflow
                        )
                    except Exception as exc:  # pragma: no cover - defensive logging
                        logger.exception("Branch execution failed for job %s", job_id)
                        last_error = str(exc)
                        if hypothesis_id:
                            _planner_event(
                                "branch_failed",
                                {
                                    "branch_group_id": group_id,
                                    "branch_rank": branch_rank,
                                    "branch_tool": branch_tool,
                                    "branch_step_id": branch_step_id,
                                    "branch_id": branch_id,
                                    "hypothesis_id": hypothesis_id,
                                    "error": last_error,
                                },
                                diff={
                                    "pending_remove": [hypothesis_id],
                                    "rejected_add": [hypothesis_id],
                                },
                            )
                        emit(
                            "branch_failed",
                            {
                                "branch_group_id": group_id,
                                "branch_rank": branch_rank,
                                "branch_tool": branch_tool,
                                "branch_step_id": branch_step_id,
                                "error": last_error,
                            },
                        )
                        last_failed_tool = branch_tool or last_failed_tool
                        continue

                    for step_result in branch_result.step_results:
                        step_result["branch_group_id"] = group_id
                        step_result["branch_rank"] = branch_rank
                        step_result["branch_step_id"] = branch_step_id
                    combined_results.extend(branch_result.step_results)

                    if branch_result.state == WorkflowState.SUCCEEDED:
                        success = True
                        if hypothesis_id and branch_id and branch_tool:
                            _planner_event(
                                "branch_succeeded",
                                {
                                    "branch_group_id": group_id,
                                    "branch_rank": branch_rank,
                                    "branch_tool": branch_tool,
                                    "branch_step_id": branch_step_id,
                                    "branch_id": branch_id,
                                    "hypothesis_id": hypothesis_id,
                                },
                                diff={
                                    "pending_remove": [hypothesis_id],
                                    "selected_branch_id_set": branch_id,
                                    "selected_tool_ids_set": [branch_tool],
                                },
                            )
                        emit(
                            "branch_succeeded",
                            {
                                "branch_group_id": group_id,
                                "branch_rank": branch_rank,
                                "branch_tool": branch_tool,
                                "branch_step_id": branch_step_id,
                            },
                        )
                        for remaining in branch_steps_sorted[idx + 1 :]:
                            remaining_meta = remaining.get("metadata") or {}
                            remaining_rank = _branch_rank(remaining)
                            remaining_tool = remaining.get("tool")
                            remaining_step_id = str(
                                remaining.get("id")
                                or remaining.get("step_id")
                                or f"step-skip-{remaining_rank:03d}"
                            )
                            remaining_hypothesis = (
                                f"hyp:{remaining_tool}" if remaining_tool else None
                            )
                            remaining_branch = (
                                f"br:{remaining_tool}" if remaining_tool else None
                            )
                            combined_results.append(
                                {
                                    "step_id": remaining_step_id,
                                    "tool": remaining_tool,
                                    "status": "skipped",
                                    "branch_group_id": group_id,
                                    "branch_rank": remaining_rank,
                                    "branch_step_id": remaining_step_id,
                                }
                            )
                            if remaining_hypothesis:
                                _planner_event(
                                    "branch_skipped",
                                    {
                                        "branch_group_id": group_id,
                                        "branch_rank": remaining_rank,
                                        "branch_tool": remaining_tool,
                                        "branch_step_id": remaining_step_id,
                                        "branch_id": remaining_branch,
                                        "hypothesis_id": remaining_hypothesis,
                                    },
                                    diff={
                                        "pending_remove": [remaining_hypothesis],
                                        "rejected_add": [remaining_hypothesis],
                                    },
                                )
                            emit(
                                "branch_skipped",
                                {
                                    "branch_group_id": group_id,
                                    "branch_rank": remaining_rank,
                                    "branch_tool": remaining_tool,
                                    "branch_step_id": remaining_step_id,
                                },
                            )
                        break

                    last_error = branch_result.error or "Branch execution failed"
                    if hypothesis_id:
                        _planner_event(
                            "branch_failed",
                            {
                                "branch_group_id": group_id,
                                "branch_rank": branch_rank,
                                "branch_tool": branch_tool,
                                "branch_step_id": branch_step_id,
                                "branch_id": branch_id,
                                "hypothesis_id": hypothesis_id,
                                "error": last_error,
                            },
                            diff={
                                "pending_remove": [hypothesis_id],
                                "rejected_add": [hypothesis_id],
                            },
                        )
                    emit(
                        "branch_failed",
                        {
                            "branch_group_id": group_id,
                            "branch_rank": branch_rank,
                            "branch_tool": branch_tool,
                            "branch_step_id": branch_step_id,
                            "error": last_error,
                        },
                    )
                    last_failed_tool = branch_tool or last_failed_tool

                if not success and last_error is None:
                    last_error = "All branch candidates failed"
                result = WorkflowResult(
                    state=WorkflowState.SUCCEEDED if success else WorkflowState.FAILED,
                    error=None if success else last_error,
                    step_results=combined_results,
                )

                if branch_event_records:
                    plan_payload.setdefault("planner_events", [])
                    plan_payload["planner_events"].extend(branch_event_records)
                    try:
                        from brain_researcher.services.agent.planner_state import (
                            replay_planner_events,
                        )

                        plan_payload["planner_state"] = replay_planner_events(
                            plan_payload["planner_events"]
                        )
                    except Exception as exc:  # pragma: no cover - best effort
                        logger.debug(
                            "Failed to update planner_state from branch events: %s", exc
                        )
                    metadata = payload.setdefault("metadata", {})
                    if branch_event_payloads:
                        existing_events = metadata.get("branch_events")
                        if not isinstance(existing_events, list):
                            existing_events = []
                        existing_events.extend(branch_event_payloads)
                        metadata["branch_events"] = _dedupe_branch_events(
                            existing_events
                        )
                    if plan_payload.get("planner_events") is not None:
                        metadata["planner_events"] = plan_payload.get(
                            "planner_events", []
                        )
                    if plan_payload.get("planner_state") is not None:
                        metadata["planner_state"] = plan_payload.get("planner_state")
                    payload["plan"] = plan_payload
                    job.payload_json = json.dumps(payload)
        if workflow is None and result is None:
            workflow_steps = self._prepare_workflow_steps(step_defs)

            if not workflow_steps:
                await self._finalize_job(
                    job_id=job_id,
                    exit_code=1,
                    error_message="Plan contains no runnable steps",
                )
                return

            base_workflow_metadata = (
                plan_payload.get("metadata")
                if isinstance(plan_payload.get("metadata"), dict)
                else {}
            )
            workflow = WorkflowDefinition(
                workflow_id=workflow_id,
                steps=workflow_steps,
                metadata={
                    **base_workflow_metadata,
                    **({"run_dir": str(run_dir)} if run_dir is not None else {}),
                },
            )

        try:
            if result is None:
                result = await self._run_in_executor(dag_executor.execute, workflow)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Plan execution failed for job %s", job_id)
            if queue:
                await queue.put(
                    {
                        "type": "plan_failed",
                        "job_id": job_id,
                        "plan_id": workflow_id,
                        "error": str(exc),
                    }
                )
            await self._finalize_job(
                job_id=job_id,
                exit_code=1,
                error_message=str(exc),
            )
            return

        success = result.state == WorkflowState.SUCCEEDED
        duration_ms = int(max((time.perf_counter() - start_ts) * 1000, 0))

        workflow_result_payload = result.to_dict()

        # Enrich step results with phase metadata and postcheck gates
        for step_payload in workflow_result_payload.get("steps", []) or []:
            if not isinstance(step_payload, dict):
                continue
            sid = str(
                step_payload.get("step_id")
                or step_payload.get("id")
                or step_payload.get("name")
                or "unknown"
            )

            # Exec phase snapshot
            step_payload.setdefault(
                "exec_result",
                {
                    "status": step_payload.get("status"),
                    "error": step_payload.get("error"),
                    "duration_ms": step_payload.get("duration_ms"),
                },
            )

            # Carry declarative preflight outcome
            if sid in preflight_results:
                step_payload.setdefault("preflight_result", preflight_results[sid])

            # Postcheck gates on executed steps
            post_status = "ok"
            if self.gate_engine:
                post_context = dict(step_payload)
                step_violations = self._evaluate_gates(
                    stage="postcheck",
                    context=post_context,
                    component="plan",
                    step_id=sid,
                )
                if step_violations:
                    step_payload.setdefault("violations", []).extend(
                        [v.model_dump() for v in step_violations]
                    )
                    all_violations.extend(step_violations)
                    blocking = [v for v in step_violations if v.blocking]
                    if blocking:
                        blocking_postcheck.extend(blocking)
                        post_status = "blocked"
                    else:
                        post_status = "warn"

            existing_violations = _parse_violations(step_payload.get("violations"))
            existing_blocking = [v for v in existing_violations if v.blocking]
            if existing_blocking:
                blocking_postcheck.extend(existing_blocking)
                post_status = "blocked"
            elif existing_violations and post_status == "ok":
                post_status = "warn"
            step_payload.setdefault(
                "postcheck_result",
                {
                    "status": post_status,
                    "violations": step_payload.get("violations", []),
                },
            )
            if run_dir is not None:
                log_trace_event(
                    run_dir,
                    run_id=workflow_id,
                    event_type="step_postcheck_completed",
                    payload={
                        "job_id": job_id,
                        "plan_id": workflow_id,
                        "step_id": sid,
                        "postcheck_result": step_payload.get("postcheck_result"),
                    },
                )
            # Phase snapshot for provenance consumers
            phase_meta = step_payload.setdefault("phases", {})
            phase_meta["preflight"] = step_payload.get("preflight_result")
            phase_meta["execute"] = step_payload.get("exec_result")
            phase_meta["postcheck"] = step_payload.get("postcheck_result")
        postcheck_error = None
        if blocking_postcheck:
            msg = "; ".join([f"{v.code}: {v.message}" for v in blocking_postcheck])
            postcheck_error = f"Postcheck blocked: {msg}"
            success = False
            workflow_result_payload["state"] = WorkflowState.FAILED.value
            workflow_result_payload["error"] = _merge_errors(
                workflow_result_payload.get("error"), postcheck_error
            )

        event_payload = {
            "type": "plan_completed" if success else "plan_failed",
            "job_id": job_id,
            "plan_id": workflow_id,
            "state": workflow_result_payload.get("state") or result.state.value,
        }
        merged_error = _merge_errors(result.error, postcheck_error)
        if merged_error:
            event_payload["error"] = merged_error
        if run_dir is not None:
            log_trace_event(
                run_dir,
                run_id=workflow_id,
                event_type=str(event_payload.get("type") or "plan_event"),
                payload=event_payload,
            )
        if queue:
            await queue.put(event_payload)

        provenance_path = None
        try:
            if run_dir is not None:
                candidate = run_dir / "provenance.json"
                if candidate.exists():
                    provenance_path = str(candidate)
        except Exception:  # pragma: no cover - best effort logging only
            logger.debug("Unable to locate provenance file for job %s", job_id)

        await self._persist_plan_result_metadata(
            job,
            workflow_result_payload,
            provenance_path,
        )

        # Best-effort merge phase metadata into provenance for downstream consumers
        if provenance_path:
            self._update_provenance_phases(
                provenance_path,
                workflow_result_payload,
                plan_payload.get("mask_reasons"),
            )

        # Persist aggregated violations + mask reasons into payload metadata for downstream observation
        payload_json_with_violations = None
        if all_violations or plan_payload.get("mask_reasons"):
            try:
                meta = payload.setdefault("metadata", {})
                meta["violations"] = [v.model_dump() for v in all_violations]
                if any(not v.blocking for v in all_violations):
                    meta["degraded"] = True
                if plan_payload.get("mask_reasons"):
                    # keep plan-level reasons alongside
                    payload.setdefault("plan", {})["mask_reasons"] = plan_payload.get(
                        "mask_reasons", []
                    )
                payload_json_with_violations = json.dumps(payload)
                job.payload_json = payload_json_with_violations
            except Exception:
                payload_json_with_violations = None

        # Write trajectory.json + reward_breakdown.json for plan runs (best-effort).
        try:
            if run_dir is not None:
                ctx = payload.get("context") or plan_payload.get("context") or {}
                user_message = None
                if isinstance(ctx, dict):
                    user_message = (
                        ctx.get("query")
                        or ctx.get("user_query")
                        or ctx.get("pipeline")
                        or (ctx.get("plan_request") or {}).get("pipeline")
                    )
                trajectory = build_atif_trajectory(
                    session_id=workflow_id,
                    workflow_steps=workflow_result_payload.get("steps") or [],
                    plan_steps=step_defs if isinstance(step_defs, list) else None,
                    user_message=str(user_message) if user_message else None,
                    extra={
                        "job_id": job_id,
                        "plan_id": workflow_id,
                        "state": workflow_result_payload.get("state"),
                        "mask_reasons": plan_payload.get("mask_reasons"),
                    },
                )
                write_trajectory_json(run_dir, trajectory)
                write_reward_breakdown(run_dir)
        except Exception:
            pass

        exit_code = 0 if success else 1
        await self._finalize_job(
            job_id=job_id,
            exit_code=exit_code,
            error_message=_merge_errors(result.error, postcheck_error),
            run_id=run_id,
            run_dir=str(run_dir) if run_dir is not None else None,
            provenance_path=provenance_path,
            payload_json=payload_json_with_violations,
        )

        await self._maybe_write_plan_evidence(
            job_id=job_id,
            job_payload=payload,
            workflow_result=workflow_result_payload,
            duration_ms=duration_ms,
        )

    async def _maybe_write_plan_evidence(
        self,
        *,
        job_id: str,
        job_payload: Dict[str, Any],
        workflow_result: Dict[str, Any],
        duration_ms: int,
    ) -> None:
        """Best-effort KG evidence writeback for plan_execution jobs.

        Guardrails:
        - behind BR_KG_WRITEBACK=1 (default off)
        - skip non-terminal states (e.g. RETRYING)
        - never fail the job if Neo4j unavailable
        """

        try:
            from brain_researcher.services.agent.planner.catalog_loader import (
                get_tool_by_id,
            )
            from brain_researcher.services.agent.planner.evidence import (
                aggregate_plan_job_evidence,
                is_writeback_enabled,
            )
            from brain_researcher.services.agent.planner.evidence_neo4j import (
                get_default_evidence_store,
            )
        except Exception:  # pragma: no cover - optional path
            return

        if not is_writeback_enabled():
            return

        try:
            current_job = await self.job_store.get(job_id)
        except Exception:
            current_job = None

        terminal = {
            JobState.SUCCEEDED,
            JobState.FAILED,
            JobState.TIMEOUT,
            JobState.CANCELLED,
        }
        if not current_job or current_job.state not in terminal:
            return

        writer = self._evidence_writer or get_default_evidence_store()
        if writer is None:
            return

        tool_ids: list[str] = []
        steps = job_payload.get("steps")
        if isinstance(steps, list):
            for step in steps:
                if isinstance(step, dict) and isinstance(step.get("tool"), str):
                    tool_ids.append(step["tool"])

        tool_versions: dict[str, str] = {}
        for tool_id in tool_ids:
            cap = get_tool_by_id(tool_id)
            tool_versions[tool_id] = getattr(cap, "entrypoint", None) or ""

        records = aggregate_plan_job_evidence(
            job_payload=job_payload,
            workflow_result=workflow_result,
            duration_ms=duration_ms,
            tool_versions=tool_versions,
            run_id=job_id,
        )

        if not records:
            return

        try:
            writer.write(records)
        except Exception as exc:  # pragma: no cover - best-effort
            logger.debug("Evidence writeback failed for job %s: %s", job_id, exc)

    def _prepare_workflow_steps(
        self, step_defs: List[Dict[str, Any]]
    ) -> List[WorkflowStep]:
        """Convert plan step definitions into WorkflowStep objects with metadata."""

        workflow_steps: List[WorkflowStep] = []
        for raw in step_defs:
            tool_name = raw.get("tool")
            if not tool_name:
                continue
            step_metadata = dict(raw.get("metadata") or {})
            step_metadata.setdefault("consumes", raw.get("consumes", {}))
            step_metadata.setdefault("produces", raw.get("produces", {}))
            runtime_kind = (
                raw.get("runtime_kind")
                or step_metadata.get("runtime_kind")
                or "container"
            )
            step_metadata["runtime_kind"] = runtime_kind
            workflow_steps.append(
                WorkflowStep(
                    step_id=str(
                        raw.get("id")
                        or raw.get("step_id")
                        or f"step-{len(workflow_steps) + 1:03d}"
                    ),
                    tool_name=tool_name,
                    parameters=raw.get("params", {}),
                    metadata=step_metadata,
                )
            )
        return workflow_steps

    async def _persist_plan_result_metadata(
        self,
        job,
        workflow_result: Dict[str, Any],
        provenance_path: Optional[str],
    ) -> None:
        """Attach workflow execution metadata to the job payload."""

        try:
            payload = json.loads(job.payload_json) if job.payload_json else {}
        except json.JSONDecodeError:
            payload = {}

        metadata = payload.setdefault("metadata", {})
        metadata["workflow_state"] = workflow_result.get("state")
        metadata["workflow_result"] = workflow_result
        if provenance_path:
            metadata["provenance_path"] = provenance_path

        payload["result"] = workflow_result
        job.payload_json = json.dumps(payload)

        try:
            await self.job_store.update_state(
                job.job_id,
                None,
                payload_json=job.payload_json,
            )
        except Exception as exc:  # pragma: no cover - best effort logging
            logger.debug(
                "Failed to persist workflow metadata for job %s: %s",
                job.job_id,
                exc,
            )

    async def _annotate_cache_metadata(
        self,
        job_id: str,
        cache_key: str,
        hit: bool,
        run_dir: Optional[str],
        metadata: Dict[str, Any],
        payload: Dict[str, Any],
        job_record,
        error: Optional[str] = None,
    ) -> None:
        """Persist cache metadata onto the job payload and in-memory stores."""
        try:
            metadata["cache_key"] = cache_key
            metadata["cache_hit"] = hit
            cache_meta = metadata.setdefault("cache", {})
            cache_meta["key"] = cache_key
            cache_meta["hit"] = hit
            if run_dir:
                cache_meta["run_dir"] = run_dir
            if error:
                cache_meta["error"] = error
            payload["metadata"] = metadata
            job_record.payload_json = json.dumps(payload)
            await self.job_store.update_state(
                job_id,
                job_record.state,
                payload_json=job_record.payload_json,
            )
            try:
                from .main_enhanced import jobs_db  # type: ignore

                job_model = jobs_db.get(job_id)
                if job_model:
                    job_model.metadata.setdefault("cache", {}).update(cache_meta)
                    job_model.metadata["cache_key"] = cache_key
                    job_model.metadata["cache_hit"] = hit
                    job_model.cache_metadata = CacheMetadata(
                        cache_key=cache_key,
                        cache_hit=hit,
                        cached_run_id=cache_meta.get("run_id"),
                        cache_timestamp=int(time.time()),
                    )
            except Exception:
                pass
        except Exception as exc:  # pragma: no cover - best effort logging
            logger.debug(
                "Failed to annotate cache metadata for job %s: %s", job_id, exc
            )

    async def _emit_cache_event(self, job_id: str, payload: Dict[str, Any]) -> None:
        """Send cache metadata updates over the SSE channel."""
        try:
            from .main_enhanced import job_updates  # type: ignore

            queue = job_updates.get(job_id)
            if queue is not None:
                await queue.put({"type": "cache", "cache": payload})
        except Exception as exc:  # pragma: no cover - best effort logging
            logger.debug("Failed to emit cache SSE for job %s: %s", job_id, exc)

    async def _execute_job(self, job):
        """
        Execute a job by invoking ToolExecutor with provenance tracking.

        Execution flow:
        1. Parse job.payload_json to get tool/command and parameters
        2. Create ToolExecutionRequest with job_store context for streaming
        3. Execute tool via ToolExecutor
        4. Extract provenance metadata (run_id, run_dir, provenance_path)
        5. Map result.status to exit_code
        6. Finalize job with provenance fields (respects cancel-wins rule)

        Args:
            job: JobRecord to execute
        """
        job_id = job.job_id

        try:
            # Update to RUNNING state
            await self.job_store.update_state(
                job_id, JobState.RUNNING, started_at=int(time.time())
            )

            logger.info(f"Executing job {job_id}")

            # Emit replayable event (best-effort). Note: run_dir may not exist yet.
            try:
                await emit_job_event(
                    self.job_store,
                    job_id=job_id,
                    event_type="job.started",
                    payload={"status": "running"},
                )
            except Exception:  # pragma: no cover - best effort
                pass

            resource_tracker = ResourceUsageTracker()

            def finalize_resource_usage(
                existing: Optional[Dict[str, Any]] = None,
            ) -> Optional[Dict[str, Any]]:
                return _merge_resource_usage(existing, resource_tracker.snapshot())

            resource_tracker = ResourceUsageTracker()

            def finalize_resource_usage(
                existing: Optional[Dict[str, Any]] = None,
            ) -> Optional[Dict[str, Any]]:
                return _merge_resource_usage(existing, resource_tracker.snapshot())

            # Check for cancellation before starting
            current_job = await self.job_store.get(job_id)
            if current_job and current_job.cancellation_requested:
                await self._handle_cancellation(job_id)
                return

            # Parse job payload to extract execution parameters
            try:
                payload = json.loads(job.payload_json)
            except json.JSONDecodeError:
                logger.error(f"Invalid payload JSON for job {job_id}")
                await self._finalize_job(
                    job_id=job_id,
                    exit_code=1,
                    error_message="Invalid job payload JSON",
                    actual_resources=finalize_resource_usage(),
                )
                return
            if payload.get("type") == "plan_execution":
                await self._execute_plan_job(job, payload)
                return

            # Extract tool execution parameters
            # Expected payload format:
            # {
            #   "tool_name": "tool_name",  # or "command": "shell command"
            #   "parameters": {...},       # tool parameters
            #   "execution_mode": "direct_execution" | "command_generation",
            #   ... other fields from enhanced Job model
            # }
            tool_name = payload.get("tool_name")
            command = payload.get("command")
            parameters = payload.get("parameters", {})
            execution_mode_str = payload.get("execution_mode", "direct_execution")
            step_identifier = tool_name or command or "job"

            # Preflight gates
            preflight_violations = self._evaluate_gates(
                stage="preflight",
                context=payload,
                component="worker",
                step_id=step_identifier,
            )
            blocking_preflight = [v for v in preflight_violations if v and v.blocking]
            if blocking_preflight:
                msg = "; ".join([f"{v.code}: {v.message}" for v in blocking_preflight])
                logger.warning("Preflight gate blocked job %s: %s", job_id, msg)
                await self._finalize_job(
                    job_id=job_id,
                    exit_code=1,
                    error_message=f"Preflight blocked: {msg}",
                    actual_resources=finalize_resource_usage(),
                )
                return

            # Extract resource requirements from job metadata (P3.7)
            metadata = payload.get("metadata", {})
            resource_requirements = metadata.get("resource_requirements")
            runtime_kind = metadata.get("runtime_kind")

            # Determine execution mode
            if execution_mode_str == "command_generation":
                execution_mode = ExecutionMode.COMMAND_GENERATION
            else:
                execution_mode = ExecutionMode.DIRECT_EXECUTION

            # Check if we have tool executor
            if not TOOL_EXECUTOR_AVAILABLE or self.tool_executor is None:
                logger.warning(
                    f"ToolExecutor not available for job {job_id}, using stub"
                )
                # Fall back to stub execution
                await asyncio.sleep(2)
                await self._finalize_job(
                    job_id=job_id,
                    exit_code=0,
                    actual_resources=finalize_resource_usage(),
                )
                return

            # Build ToolExecutionRequest
            # Prepare context with job store and resource requirements
            exec_context = {"job_store": self.job_store, "job_id": job_id}
            if resource_requirements:
                exec_context["resource_requirements"] = resource_requirements

            # For direct execution mode with shell commands
            if execution_mode == ExecutionMode.DIRECT_EXECUTION:
                if command:
                    # Shell command execution
                    request = ToolExecutionRequest(
                        tool_name="shell_command",
                        parameters={"command": command, **parameters},
                        execution_id=job_id,
                        mode=execution_mode,
                        execute_directly=True,
                        context=exec_context,
                        runtime_kind=runtime_kind,
                    )
                elif tool_name:
                    # Tool execution
                    request = ToolExecutionRequest(
                        tool_name=tool_name,
                        parameters=parameters,
                        execution_id=job_id,
                        mode=execution_mode,
                        execute_directly=True,
                        context=exec_context,
                        runtime_kind=runtime_kind,
                    )
                else:
                    logger.error(f"Job {job_id} missing tool_name or command")
                    await self._finalize_job(
                        job_id=job_id,
                        exit_code=1,
                        error_message="Missing tool_name or command in payload",
                        actual_resources=finalize_resource_usage(),
                    )
                    return
            else:
                # Command generation mode
                if not tool_name:
                    logger.error(
                        f"Job {job_id} missing tool_name for command generation"
                    )
                    await self._finalize_job(
                        job_id=job_id,
                        exit_code=1,
                        error_message="Missing tool_name for command generation",
                        actual_resources=finalize_resource_usage(),
                    )
                    return

                request = ToolExecutionRequest(
                    tool_name=tool_name,
                    parameters=parameters,
                    execution_id=job_id,
                    mode=execution_mode,
                    execute_directly=False,
                    context=exec_context,
                    runtime_kind=runtime_kind,
                )

            # Execute tool (runs in background thread pool)
            logger.info(f"Executing tool for job {job_id}: {tool_name or command}")
            tool_call_id = str(job_id)
            tool_id = str(
                getattr(request, "tool_name", None) or tool_name or command or "tool"
            )
            params: Dict[str, Any] = (
                request.parameters
                if hasattr(request, "parameters")
                and isinstance(request.parameters, dict)
                else (parameters if isinstance(parameters, dict) else {})
            )
            try:
                await emit_job_event(
                    self.job_store,
                    job_id=job_id,
                    event_type="tool_started",
                    payload={"tool": tool_name, "command": command},
                )
                await emit_job_event(
                    self.job_store,
                    job_id=job_id,
                    event_type="tool.call.started",
                    payload={
                        "tool_call_id": tool_call_id,
                        "step_id": step_identifier,
                        "tool_id": tool_id,
                        "params": params,
                        "execution_mode": str(execution_mode_str),
                        "runtime_kind": runtime_kind,
                    },
                )
            except Exception:  # pragma: no cover - best effort
                pass
            try:
                result = await self._run_in_executor(
                    self.tool_executor.execute, request
                )
            except asyncio.CancelledError:
                if TOOL_EXECUTOR_AVAILABLE and self.tool_executor:
                    try:
                        self.tool_executor.cancel(job_id)
                    except (
                        Exception
                    ) as cancel_error:  # pragma: no cover - best effort logging
                        logger.debug(
                            "Failed to cancel execution %s during worker shutdown: %s",
                            job_id,
                            cancel_error,
                        )
                raise

            # Extract provenance metadata from result
            run_id = result.metadata.get("run_id")
            run_dir = result.metadata.get("run_dir")
            provenance_path = result.metadata.get("provenance_path")

            # Emit ArtifactWritten events for core tool run artifacts (best-effort).
            # This keeps the analysis stream artifact index up to date and enables
            # replay/consumers to discover stdout/stderr/provenance/hash outputs.
            if run_dir:
                try:
                    from brain_researcher.core.artifact_checksums import (
                        compute_file_sha256,
                    )

                    run_path = Path(run_dir)
                    artifact_specs = [
                        ("stdout.txt", "log", "text/plain", ["stdout"]),
                        ("stderr.txt", "log", "text/plain", ["stderr"]),
                        ("provenance.json", "json", "application/json", ["provenance"]),
                        ("hash.json", "json", "application/json", ["hash"]),
                    ]
                    for uri, kind, media_type, tags in artifact_specs:
                        file_path = run_path / uri
                        if not file_path.exists():
                            continue
                        sha256, status, _reason = compute_file_sha256(file_path)
                        payload: dict[str, Any] = {
                            "job_id": job_id,
                            "uri": uri,
                            "kind": kind,
                            "media_type": media_type,
                            "tags": tags,
                        }
                        if sha256 and status == "ok":
                            payload["sha256"] = f"sha256:{sha256}"
                        try:
                            payload["bytes"] = file_path.stat().st_size
                        except OSError:
                            pass
                        await emit_job_event(
                            self.job_store,
                            job_id=job_id,
                            event_type="artifact.written",
                            payload={"artifact": payload},
                            run_id=str(run_id or job_id),
                            run_dir=run_path,
                        )
                except Exception:  # pragma: no cover - best effort
                    pass

            # Attach emitted artifact (e.g., behavior events) to payload for audit
            emitted_artifact: Dict[str, Any] | None = None
            try:
                run_path = (
                    Path(run_dir).resolve()
                    if isinstance(run_dir, str) and run_dir
                    else None
                )
                root_result: Dict[str, Any] = (
                    result.result if isinstance(result.result, dict) else {}
                )
                data = (
                    root_result.get("data")
                    if isinstance(root_result.get("data"), dict)
                    else None
                )

                def _infer_artifact_type(path_value: str) -> str:
                    lower = path_value.lower()
                    if lower.endswith(
                        (
                            ".png",
                            ".jpg",
                            ".jpeg",
                            ".svg",
                            ".gif",
                            ".webp",
                            ".nii",
                            ".nii.gz",
                        )
                    ):
                        return "image"
                    if lower.endswith((".csv", ".tsv", ".parquet", ".xlsx", ".xls")):
                        return "table"
                    if lower.endswith((".json", ".jsonl")):
                        return "json"
                    if lower.endswith((".html", ".pdf", ".md", ".txt", ".log")):
                        return "report"
                    return "file"

                def _to_artifact_record(entry: Dict[str, Any]) -> Dict[str, Any]:
                    artifact = dict(entry)
                    raw_path = None
                    for key in ("path", "uri", "file", "output_file"):
                        value = artifact.get(key)
                        if isinstance(value, str) and value.strip():
                            raw_path = value.strip()
                            break
                    if isinstance(raw_path, str):
                        path_obj = Path(raw_path).expanduser()
                        if not path_obj.is_absolute() and run_path is not None:
                            path_obj = (run_path / path_obj).resolve()
                        if path_obj.exists():
                            if run_path is not None:
                                try:
                                    rel = path_obj.relative_to(run_path).as_posix()
                                    artifact["path"] = rel
                                    artifact["uri"] = rel
                                    encoded_rel = quote(rel, safe="/._-")
                                    artifact.setdefault(
                                        "url",
                                        f"/api/jobs/{job_id}/artifacts/files/{encoded_rel}",
                                    )
                                    artifact.setdefault("download_url", artifact["url"])
                                except ValueError:
                                    artifact["path"] = str(path_obj)
                                    artifact["uri"] = str(path_obj)
                            else:
                                artifact["path"] = str(path_obj)
                                artifact["uri"] = str(path_obj)
                        else:
                            artifact["path"] = str(path_obj)
                            artifact["uri"] = str(path_obj)
                    path_text = (
                        str(artifact.get("path"))
                        if isinstance(artifact.get("path"), str)
                        else str(artifact.get("uri", ""))
                    )
                    artifact.setdefault(
                        "name", Path(path_text).name if path_text else "artifact"
                    )
                    artifact.setdefault("type", _infer_artifact_type(path_text))
                    artifact.setdefault(
                        "id",
                        f"artifact_{uuid.uuid4().hex[:10]}",
                    )
                    artifact.setdefault("artifact_id", artifact["id"])
                    return artifact

                discovered_files: List[str] = []
                seen_files: set[str] = set()

                def _collect_output_files(node: Any, depth: int = 0) -> None:
                    if depth > 8 or len(discovered_files) >= 128:
                        return
                    if isinstance(node, str):
                        text = node.strip()
                        if not text or "://" in text:
                            return
                        candidate = Path(text).expanduser()
                        candidate_paths: List[Path] = []
                        if candidate.is_absolute():
                            candidate_paths.append(candidate.resolve())
                        elif run_path is not None:
                            candidate_paths.append((run_path / candidate).resolve())
                        for candidate_path in candidate_paths:
                            if (
                                not candidate_path.exists()
                                or not candidate_path.is_file()
                            ):
                                continue
                            key = str(candidate_path)
                            if key in seen_files:
                                continue
                            seen_files.add(key)
                            discovered_files.append(key)
                        return
                    if isinstance(node, dict):
                        for value in node.values():
                            _collect_output_files(value, depth + 1)
                        return
                    if isinstance(node, (list, tuple, set)):
                        for value in node:
                            _collect_output_files(value, depth + 1)

                candidate_artifacts: List[Dict[str, Any]] = []
                for maybe_artifact in (
                    root_result.get("artifact"),
                    data.get("artifact") if isinstance(data, dict) else None,
                ):
                    if isinstance(maybe_artifact, dict):
                        candidate_artifacts.append(_to_artifact_record(maybe_artifact))

                for maybe_list in (
                    root_result.get("artifacts"),
                    data.get("artifacts") if isinstance(data, dict) else None,
                ):
                    if not isinstance(maybe_list, list):
                        continue
                    for entry in maybe_list:
                        if isinstance(entry, dict):
                            candidate_artifacts.append(_to_artifact_record(entry))

                for node in (
                    root_result.get("outputs"),
                    root_result.get("steps"),
                    data.get("outputs") if isinstance(data, dict) else None,
                    data.get("steps") if isinstance(data, dict) else None,
                ):
                    _collect_output_files(node)

                for file_path in discovered_files:
                    candidate_artifacts.append(
                        _to_artifact_record(
                            {
                                "path": file_path,
                                "name": Path(file_path).name,
                            }
                        )
                    )

                if candidate_artifacts:
                    emitted_artifact = candidate_artifacts[0]
                    artifacts = payload.get("artifacts")
                    if not isinstance(artifacts, list):
                        artifacts = []

                    existing_keys: set[str] = set()
                    for entry in artifacts:
                        if not isinstance(entry, dict):
                            continue
                        for key in ("artifact_id", "id", "path", "uri", "name"):
                            value = entry.get(key)
                            if isinstance(value, str) and value.strip():
                                existing_keys.add(f"{key}:{value.strip().lower()}")

                    for artifact in candidate_artifacts:
                        skip = False
                        for key in ("artifact_id", "id", "path", "uri", "name"):
                            value = artifact.get(key)
                            if not isinstance(value, str) or not value.strip():
                                continue
                            composite = f"{key}:{value.strip().lower()}"
                            if composite in existing_keys:
                                skip = True
                                break
                        if skip:
                            continue
                        artifacts.append(artifact)
                        for key in ("artifact_id", "id", "path", "uri", "name"):
                            value = artifact.get(key)
                            if isinstance(value, str) and value.strip():
                                existing_keys.add(f"{key}:{value.strip().lower()}")

                    payload["artifacts"] = artifacts
                    job.payload_json = json.dumps(payload)
                    await self.job_store.update_state(
                        job_id,
                        job.state,
                        payload_json=job.payload_json,
                    )
            except Exception as exc:  # pragma: no cover - best effort
                logger.debug("Failed to persist artifact for job %s: %s", job_id, exc)

            # Extract actual resource usage from result (P3.7)
            actual_resources = None
            if result.metadata.get("resource_usage"):
                actual_resources = result.metadata["resource_usage"]
                logger.info(
                    f"Job {job_id} resource usage: "
                    f"cpu_percent={actual_resources.get('cpu_percent')}, "
                    f"mem_mb={actual_resources.get('mem_mb')}, "
                    f"wall_time_sec={actual_resources.get('wall_time_sec')}"
                )

            actual_resources = finalize_resource_usage(actual_resources)
            logger.info(
                f"Job {job_id} completed with status={result.status}, "
                f"run_id={run_id}, provenance_path={provenance_path}"
            )

            # Postcheck gates against tool metadata/result
            post_context = result.metadata if isinstance(result.metadata, dict) else {}
            existing_violations = _parse_violations(post_context.get("violations"))
            postcheck_violations = self._evaluate_gates(
                stage="postcheck",
                context=post_context,
                component="worker",
                step_id=step_identifier,
            )
            blocking_post = [v for v in postcheck_violations if v and v.blocking]
            blocking_existing = [v for v in existing_violations if v.blocking]
            if blocking_existing:
                blocking_post.extend(blocking_existing)
            # Attach violations to metadata for downstream consumers
            if post_context is not None:
                post_context.setdefault("violations", [])
                post_context["violations"].extend(
                    [v.model_dump() for v in postcheck_violations if v]
                )
                result.metadata = post_context

            postcheck_error = None
            if blocking_post:
                msg = "; ".join([f"{v.code}: {v.message}" for v in blocking_post])
                logger.warning("Postcheck gate blocked job %s: %s", job_id, msg)
                postcheck_error = f"Postcheck blocked: {msg}"
            elif postcheck_violations:
                # mark degraded on non-blocking violations
                try:
                    payload.setdefault("metadata", {})["degraded"] = True
                except Exception:
                    pass

            # Collect violations (preflight + postcheck) for trace/export
            all_violations = preflight_violations + [
                v for v in postcheck_violations if v
            ]

            # Persist violations into the job payload so observation.json + UI can
            # render them even for single-tool jobs (which may not have a plan).
            payload_json_with_violations = None
            if all_violations:
                try:
                    meta = payload.setdefault("metadata", {})
                    meta["violations"] = [v.model_dump() for v in all_violations]
                    if any(not v.blocking for v in all_violations):
                        meta["degraded"] = True
                    payload_json_with_violations = json.dumps(payload)
                    job.payload_json = payload_json_with_violations
                except Exception:
                    payload_json_with_violations = None

            # P2.6: Add retry metadata to provenance if this was a retry
            if provenance_path and job.attempt > 1:
                await self._add_retry_metadata_to_provenance(
                    provenance_path=provenance_path,
                    job=job,
                )

            # Map result.status to exit_code
            # ToolExecutionResult.status: "success" | "error" | "timeout" | "cancelled"
            status_to_exit_code = {
                "success": 0,
                "error": 1,
                "timeout": 124,
                "cancelled": 1,  # Will be overridden by cancel-wins rule
            }
            exit_code = status_to_exit_code.get(result.status, 1)

            # Extract error message if present
            error_message = None
            if result.status != "success":
                error_message = (
                    result.error or f"Execution failed with status: {result.status}"
                )
            if blocking_post:
                if exit_code == 0:
                    exit_code = 1
                if postcheck_error:
                    if error_message:
                        error_message = f"{postcheck_error}; {error_message}"
                    else:
                        error_message = postcheck_error

            # Finalize with provenance (respects cancel-wins rule)
            await self._finalize_job(
                job_id=job_id,
                exit_code=exit_code,
                error_message=error_message,
                run_id=run_id,
                run_dir=run_dir,
                provenance_path=provenance_path,
                actual_resources=actual_resources,
                payload_json=payload_json_with_violations,
            )

            # Emit trace events + trajectory.json for single-tool jobs (best-effort)
            try:
                steps_payload = [
                    {
                        "step_id": step_identifier,
                        "tool": tool_name or command,
                        "status": result.status,
                        "state": result.status,
                        "error": result.error,
                        "duration_ms": (
                            actual_resources.get("wall_time_sec") * 1000
                            if isinstance(actual_resources, dict)
                            and actual_resources.get("wall_time_sec")
                            else None
                        ),
                        "violations": [v.model_dump() for v in all_violations],
                        "preflight_result": {
                            "status": "blocked" if blocking_preflight else "ok",
                            "violations": [
                                v.model_dump() for v in preflight_violations
                            ],
                        },
                        "exec_result": {
                            "status": result.status,
                            "error": result.error,
                        },
                        "postcheck_result": {
                            "status": (
                                "blocked"
                                if blocking_post
                                else ("warn" if postcheck_violations else "ok")
                            ),
                            "violations": [
                                v.model_dump() for v in postcheck_violations if v
                            ],
                        },
                    }
                ]
                if run_dir:
                    run_path = Path(run_dir)
                    try:
                        payload.setdefault("metadata", {})["degraded"] = bool(
                            preflight_violations or postcheck_violations
                        )
                    except Exception:
                        pass
                    try:
                        await emit_job_event(
                            self.job_store,
                            job_id=job_id,
                            event_type="tool_completed",
                            payload={
                                "state": "succeeded" if exit_code == 0 else "failed",
                                "step_id": step_identifier,
                                "tool": tool_name or command,
                                "status": result.status,
                                "error": error_message,
                            },
                            run_id=str(run_id or job_id),
                            run_dir=run_path,
                        )
                        await emit_job_event(
                            self.job_store,
                            job_id=job_id,
                            event_type="tool.call.finished",
                            payload={
                                "tool_call_id": tool_call_id,
                                "step_id": step_identifier,
                                "tool_id": tool_id,
                                "status": result.status,
                                "exit_code": exit_code,
                                "error_message": error_message,
                                "provenance_path": provenance_path,
                                "resource_usage": actual_resources,
                                "artifact": emitted_artifact,
                            },
                            run_id=str(run_id or job_id),
                            run_dir=run_path,
                        )
                    except Exception:  # pragma: no cover - best effort
                        pass
                    try:
                        trajectory = build_atif_trajectory(
                            session_id=str(run_id or job_id),
                            workflow_steps=steps_payload,
                            user_message=f"Run tool {tool_name or command}",
                            extra={"job_id": job_id, "run_phase": "tool"},
                        )
                        write_trajectory_json(run_path, trajectory)
                    except Exception:
                        pass
                    write_reward_breakdown(run_path)
            except Exception:
                pass

        except asyncio.CancelledError:
            # Worker was cancelled - job will be requeued by stop()
            logger.info(f"Worker cancelled while executing job {job_id}")
            raise
        except Exception as e:
            # Job failed - use finalize to respect cancel-wins
            logger.error(f"Job {job_id} failed: {e}", exc_info=True)

            await self._finalize_job(
                job_id=job_id,
                exit_code=1,
                error_message=str(e),
                actual_resources=finalize_resource_usage(),
            )

    async def _handle_cancellation(self, job_id: str):
        """
        Handle job cancellation request.

        Implements cancel-wins policy: cancellation takes precedence over completion.

        Args:
            job_id: Job ID to cancel
        """
        logger.info(f"Job {job_id} cancellation requested")

        # Update to CANCELLED state
        # Note: We use cancel() instead of update_state to ensure proper cancellation
        success = await self.job_store.cancel(
            job_id, reason="Cancelled during execution"
        )

        if success:
            logger.info(f"Job {job_id} cancelled successfully")
        else:
            logger.warning(f"Failed to cancel job {job_id}")


async def start_worker_pool(
    job_store: JobStore,
    num_workers: int = 1,
    worker_id_prefix: str = "worker",
    stop_event: Optional[asyncio.Event] = None,
) -> list[asyncio.Task]:
    """
    Start a pool of workers.

    Args:
        job_store: JobStore instance
        num_workers: Number of workers to start
        worker_id_prefix: Prefix for worker IDs
        stop_event: Optional event to signal shutdown

    Returns:
        List of worker tasks
    """
    workers = []
    tasks = []

    for i in range(num_workers):
        worker_id = f"{worker_id_prefix}-{i}"
        worker = JobWorker(job_store, worker_id)
        workers.append(worker)

        task = asyncio.create_task(worker.start())
        tasks.append(task)

    logger.info(f"Started {num_workers} workers")

    # Wait for stop signal if provided
    if stop_event:
        await stop_event.wait()

        # Stop all workers
        logger.info("Stopping worker pool")
        for worker in workers:
            await worker.stop()

        # Wait for all tasks to complete
        await asyncio.gather(*tasks, return_exceptions=True)

    return tasks
