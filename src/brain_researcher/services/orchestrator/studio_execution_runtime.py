"""Hosted Studio execution gateway runtime.

This runtime stores lightweight Studio execution records and routes execution
requests into the existing orchestrator execution substrate.

- Preferred path: enqueue a JobStore-backed job for the embedded/external
  worker pool to claim and execute.
- Fallback path: when the orchestrator is not running workers, use the same
  ToolExecutor direct-execution path that workers use so Studio still runs
  against the real execution backend instead of a stub.
"""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import shlex
import threading
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from brain_researcher.integrations.jupyter.runtime_client import (
    JupyterRuntimeTarget,
    ensure_session,
    execute_python_code,
    interrupt_kernel,
)

from .studio_session_runtime import (
    StudioRuntimeKind,
    StudioRuntimeProfile,
    StudioRuntimeSession,
    StudioSession,
    StudioSessionStatus,
    resolve_runtime_absolute_working_directory,
)

logger = logging.getLogger(__name__)

_ENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TERMINAL_EXECUTION_STATUSES = {
    "succeeded",
    "failed",
    "canceled",
}
_LMOD_INIT_SNIPPET = (
    "source /etc/profile.d/lmod.sh 2>/dev/null"
    " || source /usr/share/lmod/lmod/init/bash 2>/dev/null"
    " || true"
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_naive() -> datetime:
    return datetime.utcnow()


class StudioExecutionKind(str, Enum):
    CODE = "code"
    COMMAND = "command"


class StudioExecutionBackend(str, Enum):
    STUB = "stub"
    JUPYTER_KERNEL = "jupyter_kernel"
    NEURODESK_MODULE = "neurodesk_module"
    CONTAINER = "container"


class StudioExecutionStatus(str, Enum):
    ACCEPTED = "accepted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class StudioExecutionResult(BaseModel):
    stubbed: bool = False
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    summary: str | None = None


class StudioExecution(BaseModel):
    id: str = Field(..., pattern=r"^exec_[A-Za-z0-9]+$")
    session_id: str = Field(..., pattern=r"^studio_[A-Za-z0-9]+$")
    runtime_session_id: str = Field(..., pattern=r"^rt_[A-Za-z0-9]+$")
    project_id: str = Field(..., min_length=1, max_length=200)
    owner_user_id: str = Field(..., min_length=1, max_length=200)
    kind: StudioExecutionKind
    runtime_backend: StudioExecutionBackend = StudioExecutionBackend.STUB
    runtime_profile_id: StudioRuntimeProfile = StudioRuntimeProfile.STANDARD
    status: StudioExecutionStatus = StudioExecutionStatus.ACCEPTED
    language: str | None = Field(default=None, max_length=50)
    code: str | None = None
    command: list[str] = Field(default_factory=list)
    working_directory: str | None = Field(default=None, max_length=2000)
    env: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    request_summary: str = Field(..., min_length=1, max_length=500)
    result: StudioExecutionResult | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    accepted_at: datetime | None = None
    completed_at: datetime | None = None


class StudioExecutionRequest(BaseModel):
    kind: StudioExecutionKind
    language: str | None = Field(default=None, max_length=50)
    code: str | None = Field(default=None, max_length=200000)
    command: list[str] = Field(default_factory=list)
    runtime_backend: StudioExecutionBackend = StudioExecutionBackend.STUB
    runtime_profile_id: StudioRuntimeProfile = StudioRuntimeProfile.STANDARD
    working_directory: str | None = Field(default=None, max_length=2000)
    env: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int | None = Field(default=None, ge=1)
    dry_run: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class StudioExecutionActionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class StudioExecutionRuntime:
    """Studio execution facade backed by orchestrator jobs or ToolExecutor."""

    def __init__(
        self,
        *,
        studio_session_runtime: Any | None = None,
        app_state: Any | None = None,
    ) -> None:
        self._studio_session_runtime = studio_session_runtime
        self._app_state = app_state
        self._lock = threading.Lock()
        self._executions: dict[str, StudioExecution] = {}
        self._job_bindings: dict[str, str] = {}
        self._backend_tasks: dict[str, asyncio.Task[None]] = {}
        self._runtime_task_bindings: dict[str, str] = {}
        self._direct_tool_executor: Any | None = None

    async def create_execution(
        self,
        owner_user_id: str,
        session_id: str,
        request: StudioExecutionRequest,
    ) -> StudioExecution:
        session = await self._resolve_session(owner_user_id, session_id)
        runtime_session = await self._resolve_runtime_session(session)
        self._validate_request(request)
        effective_runtime_backend = (
            StudioExecutionBackend.JUPYTER_KERNEL
            if self._should_use_jupyter_runtime(runtime_session, request)
            else request.runtime_backend
        )

        now = _utc_now()
        execution = StudioExecution(
            id=f"exec_{secrets.token_urlsafe(9).replace('-', '').replace('_', '')}",
            session_id=session.id,
            runtime_session_id=runtime_session.id,
            project_id=session.project_id,
            owner_user_id=owner_user_id,
            kind=request.kind,
            runtime_backend=effective_runtime_backend,
            runtime_profile_id=request.runtime_profile_id,
            status=StudioExecutionStatus.ACCEPTED,
            language=request.language,
            code=request.code,
            command=list(request.command or []),
            working_directory=request.working_directory,
            env=dict(request.env or {}),
            timeout_seconds=request.timeout_seconds,
            metadata=dict(request.metadata or {}),
            request_summary=self._build_request_summary(request),
            result=None,
            created_at=now,
            updated_at=now,
            accepted_at=now,
            completed_at=None,
        )
        with self._lock:
            self._executions[execution.id] = execution

        if request.dry_run:
            execution.result = StudioExecutionResult(
                stubbed=True,
                summary="Dry-run accepted; backend execution was skipped",
            )
            execution.metadata.update(
                {
                    "backend_mode": "dry_run",
                    "runtime_session_id": runtime_session.id,
                }
            )
        else:
            if execution.runtime_backend == StudioExecutionBackend.JUPYTER_KERNEL:
                try:
                    backend_metadata = await self._submit_jupyter_execution(
                        session,
                        runtime_session,
                        execution,
                        request,
                    )
                except RuntimeError:
                    logger.warning(
                        "Studio runtime %s could not bind to Jupyter; falling back to orchestrator backend",
                        runtime_session.id,
                        exc_info=True,
                    )
                    backend_metadata = await self._submit_backend_job(
                        session,
                        runtime_session,
                        execution,
                        request,
                    )
            else:
                backend_metadata = await self._submit_backend_job(
                    session,
                    runtime_session,
                    execution,
                    request,
                )
            execution.metadata.update(backend_metadata)
            execution.result = StudioExecutionResult(
                stubbed=False,
                summary=self._queued_summary(
                    str(backend_metadata.get("backend_mode") or "orchestrator_job")
                ),
            )
            backend_job_id = str(backend_metadata.get("backend_job_id") or "")
            if backend_job_id:
                self._job_bindings[backend_job_id] = execution.id
            runtime_task_id = str(backend_metadata.get("runtime_task_id") or "")
            if runtime_task_id:
                self._runtime_task_bindings[runtime_task_id] = execution.id

        with self._lock:
            self._executions[execution.id] = execution

        return await self._hydrate_execution(execution)

    @staticmethod
    def _should_use_jupyter_runtime(
        runtime_session: StudioRuntimeSession,
        request: StudioExecutionRequest,
    ) -> bool:
        if request.kind != StudioExecutionKind.CODE:
            return False
        language = (request.language or "python").strip().lower()
        if language not in {"python", "python3", "py"}:
            return False
        return runtime_session.kind == StudioRuntimeKind.JUPYTER

    async def list_executions(
        self,
        *,
        owner_user_id: str,
        session_id: str,
        kind: StudioExecutionKind | None = None,
        status: StudioExecutionStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[StudioExecution]:
        with self._lock:
            items = [
                execution
                for execution in self._executions.values()
                if execution.owner_user_id == owner_user_id and execution.session_id == session_id
            ]
        hydrated = [await self._hydrate_execution(item) for item in items]
        if kind is not None:
            hydrated = [item for item in hydrated if item.kind == kind]
        if status is not None:
            hydrated = [item for item in hydrated if item.status == status]
        hydrated.sort(key=lambda item: item.updated_at, reverse=True)
        return hydrated[offset : offset + limit]

    async def get_execution(
        self, owner_user_id: str, session_id: str, execution_id: str
    ) -> StudioExecution | None:
        with self._lock:
            execution = self._executions.get(execution_id)
            if (
                execution is None
                or execution.owner_user_id != owner_user_id
                or execution.session_id != session_id
            ):
                return None
        return await self._hydrate_execution(execution)

    async def perform_action(
        self,
        owner_user_id: str,
        session_id: str,
        execution_id: str,
        action: str,
        request: StudioExecutionActionRequest | None = None,
    ) -> dict[str, Any]:
        payload = request or StudioExecutionActionRequest()
        with self._lock:
            execution = self._executions.get(execution_id)
            if (
                execution is None
                or execution.owner_user_id != owner_user_id
                or execution.session_id != session_id
            ):
                raise KeyError(execution_id)

        execution = await self._hydrate_execution(execution)
        if action == "touch":
            updated = self._touch(execution)
        elif action == "cancel":
            backend_job_id = str(execution.metadata.get("backend_job_id") or "")
            runtime_task_id = str(execution.metadata.get("runtime_task_id") or "")
            if backend_job_id:
                try:
                    await self._cancel_backend_job(
                        backend_job_id, payload.reason or "Studio execution canceled"
                    )
                except Exception:
                    logger.exception("Failed to cancel backend job %s", backend_job_id)
            elif runtime_task_id:
                try:
                    await self._cancel_runtime_task(execution, payload.reason)
                except Exception:
                    logger.exception("Failed to cancel runtime task %s", runtime_task_id)
            now = _utc_now()
            updated = execution.model_copy(
                update={
                    "status": StudioExecutionStatus.CANCELED,
                    "updated_at": now,
                    "completed_at": now,
                    "result": StudioExecutionResult(
                        stubbed=False,
                        exit_code=130,
                        stdout=execution.result.stdout if execution.result else "",
                        stderr=execution.result.stderr if execution.result else "",
                        artifacts=execution.result.artifacts if execution.result else [],
                        summary=payload.reason or "Execution canceled",
                    ),
                }
            )
        else:
            raise ValueError(action)

        with self._lock:
            self._executions[execution_id] = updated
        return {"action": action, "execution": updated.model_dump(mode="json")}

    async def _resolve_session(
        self, owner_user_id: str, session_id: str
    ) -> StudioSession:
        if self._studio_session_runtime is None:
            raise RuntimeError("Studio session runtime is not available")
        session = await self._studio_session_runtime.get_session(session_id)
        if session is None or session.owner_user_id != owner_user_id:
            raise KeyError(session_id)
        return session

    async def _resolve_runtime_session(
        self, session: StudioSession
    ) -> StudioRuntimeSession:
        runtime = await self._studio_session_runtime.get_runtime_session(
            session.runtime_session_id
        )
        if runtime is None:
            raise KeyError(session.runtime_session_id)
        return runtime

    @staticmethod
    def _validate_request(request: StudioExecutionRequest) -> None:
        if request.kind == StudioExecutionKind.CODE:
            if not (request.code or "").strip():
                raise ValueError("code execution requests require non-empty code")
            language = (request.language or "python").strip().lower()
            if language not in {"python", "python3", "py", "bash", "sh", "shell"}:
                raise ValueError(
                    f"Unsupported code execution language for hosted Studio: {language}"
                )
            if (
                request.runtime_backend == StudioExecutionBackend.JUPYTER_KERNEL
                and language not in {"python", "python3", "py"}
            ):
                raise ValueError(
                    "Jupyter kernel executions currently support Python code only"
                )
        elif request.kind == StudioExecutionKind.COMMAND:
            if not request.command:
                raise ValueError("command execution requests require a command list")
            if request.runtime_backend == StudioExecutionBackend.JUPYTER_KERNEL:
                raise ValueError(
                    "Jupyter kernel execution backend does not support command requests"
                )
        else:
            raise ValueError(f"Unsupported execution kind: {request.kind}")

        for key in request.env:
            if not _ENV_KEY_PATTERN.match(key):
                raise ValueError(f"Invalid environment variable name: {key}")

    @staticmethod
    def _build_request_summary(request: StudioExecutionRequest) -> str:
        if request.kind == StudioExecutionKind.CODE:
            lang = request.language or "code"
            return f"Queued {lang} code execution from Studio"
        return "Queued command execution from Studio"

    @staticmethod
    def _queued_summary(backend_mode: str) -> str:
        if backend_mode == "jupyter_kernel":
            return "Execution submitted to the bound Jupyter kernel runtime"
        if backend_mode == "tool_executor_direct":
            return "Execution submitted to the in-process tool executor backend"
        if backend_mode == "jobstore_worker":
            return "Execution submitted to the orchestrator worker backend"
        return "Execution submitted to the orchestrator backend"

    def _touch(self, execution: StudioExecution) -> StudioExecution:
        now = _utc_now()
        return execution.model_copy(
            update={
                "updated_at": now,
            }
        )

    def _get_app_state(self) -> Any | None:
        if self._app_state is not None:
            return self._app_state
        try:
            from brain_researcher.services.orchestrator import main_enhanced

            return getattr(main_enhanced.app, "state", None)
        except Exception:
            return None

    async def _submit_backend_job(
        self,
        session: StudioSession,
        runtime_session: StudioRuntimeSession,
        execution: StudioExecution,
        request: StudioExecutionRequest,
    ) -> dict[str, Any]:
        app_state = self._get_app_state()
        job_adapter = getattr(app_state, "job_adapter", None) if app_state else None
        job_store = getattr(app_state, "job_store", None) if app_state else None
        run_backend = (
            getattr(app_state, "run_execution_backend", None) if app_state else None
        ) or "inprocess"
        worker_pool = getattr(app_state, "worker_pool", None) if app_state else None
        if run_backend in {"job_store", "job-store"}:
            run_backend = "jobstore"
        if job_adapter is None or job_store is None:
            raise RuntimeError("Orchestrator job backend is not available")

        resolved_working_directory = self._resolve_backend_working_directory(
            runtime_session,
            request.working_directory,
        )
        normalized_request = request.model_copy(
            update={"working_directory": resolved_working_directory}
        )
        shell_command, runtime_kind = self._build_shell_command(normalized_request)
        backend_job_id = f"job_{secrets.token_urlsafe(9).replace('-', '').replace('_', '')}"

        from brain_researcher.services.orchestrator.job_management_endpoints import (
            Job,
            JobStatus,
        )

        queued_now = _utc_now_naive()
        job_status = JobStatus.QUEUED if run_backend == "jobstore" else JobStatus.PENDING
        backend_mode = "jobstore_worker"
        if run_backend != "jobstore" or not worker_pool:
            backend_mode = "tool_executor_direct"

        parameters = {
            "tool": "shell_command",
            "tool_name": "shell_command",
            "command": shell_command,
            "studio_execution_id": execution.id,
            "studio_session_id": session.id,
            "requested_runtime_backend": request.runtime_backend.value,
            "runtime_profile_id": request.runtime_profile_id.value,
            "runtime_session_id": runtime_session.id,
            "language": request.language,
            "working_directory": resolved_working_directory,
            "execution_origin": "studio_gateway",
            "_client_metadata": {
                "studio_execution_id": execution.id,
                "studio_session_id": session.id,
            },
        }
        job = Job(
            id=backend_job_id,
            name=f"Studio execution {execution.id}",
            description=execution.request_summary,
            prompt=execution.request_summary,
            status=job_status,
            user_id=execution.owner_user_id,
            session_id=session.id,
            project_id=session.project_id,
            queued_at=queued_now if job_status == JobStatus.QUEUED else None,
            metadata={
                "pipeline": "studio_execution",
                "backend_mode": backend_mode,
                "project_id": session.project_id,
                "thread_id": session.assistant_session_id or session.id,
                "runtime_kind": runtime_kind,
                "tool_name": "shell_command",
                "parameters": parameters,
                "studio_execution": {
                    "execution_id": execution.id,
                    "session_id": session.id,
                    "runtime_session_id": runtime_session.id,
                    "requested_backend": request.runtime_backend.value,
                    "runtime_profile_id": request.runtime_profile_id.value,
                },
            },
        )
        await job_adapter.create_job(job)

        if backend_mode == "tool_executor_direct":
            backend_mode = "tool_executor_direct"
            task = asyncio.create_task(
                self._execute_backend_job_inprocess(
                    backend_job_id=backend_job_id,
                    shell_command=shell_command,
                    runtime_kind=runtime_kind,
                    timeout_seconds=request.timeout_seconds,
                )
            )
            self._backend_tasks[backend_job_id] = task
            task.add_done_callback(lambda _task, job_id=backend_job_id: self._backend_tasks.pop(job_id, None))

        return {
            "backend_kind": "orchestrator_job",
            "backend_mode": backend_mode,
            "backend_job_id": backend_job_id,
            "runtime_session_id": runtime_session.id,
            "backend_run_backend": run_backend,
            "backend_requested_runtime_kind": runtime_kind,
            "backend_job_url": f"/api/jobs/{backend_job_id}",
            "backend_artifacts_url": f"/api/jobs/{backend_job_id}/artifacts",
            "backend_logs_url": f"/api/jobs/{backend_job_id}/logs/stream",
            "submitted_command": shell_command,
            "resolved_working_directory": resolved_working_directory,
        }

    async def _submit_jupyter_execution(
        self,
        session: StudioSession,
        runtime_session: StudioRuntimeSession,
        execution: StudioExecution,
        request: StudioExecutionRequest,
    ) -> dict[str, Any]:
        if not runtime_session.jupyter_base_url:
            raise RuntimeError(
                "The bound Studio runtime does not expose a Jupyter base URL."
            )
        runtime_task_id = (
            f"rtask_{secrets.token_urlsafe(9).replace('-', '').replace('_', '')}"
        )
        task = asyncio.create_task(
            self._execute_jupyter_runtime_task(
                runtime_task_id=runtime_task_id,
                session=session,
                runtime_session=runtime_session,
                execution_id=execution.id,
                request=request,
            )
        )
        self._backend_tasks[runtime_task_id] = task
        task.add_done_callback(
            lambda _task, task_id=runtime_task_id: self._backend_tasks.pop(task_id, None)
        )
        await self._studio_session_runtime.update_runtime_session(
            runtime_session.id,
            status=StudioSessionStatus.BUSY,
            metadata_updates={"last_execution_id": execution.id},
        )
        return {
            "backend_kind": "jupyter_session",
            "backend_mode": "jupyter_kernel",
            "runtime_task_id": runtime_task_id,
            "runtime_session_id": runtime_session.id,
            "backend_jupyter_base_url": runtime_session.jupyter_base_url,
            "backend_jupyter_session_id": runtime_session.jupyter_session_id,
            "backend_jupyter_kernel_id": runtime_session.jupyter_kernel_id,
        }

    def _build_jupyter_runtime_target(
        self,
        runtime_session: StudioRuntimeSession,
        *,
        project_id: str,
    ) -> JupyterRuntimeTarget:
        session_path = str(
            runtime_session.metadata.get("jupyter_session_path")
            or f"projects/{project_id}/.studio/{runtime_session.id}"
        )
        session_name = str(
            runtime_session.metadata.get("jupyter_session_name")
            or f"Brain Researcher Studio {project_id}"
        )
        return JupyterRuntimeTarget(
            base_url=str(runtime_session.jupyter_base_url or ""),
            token=runtime_session.jupyter_token,
            kernel_name=runtime_session.jupyter_kernel_name or "python3",
            session_name=session_name,
            session_path=session_path,
            working_directory=runtime_session.working_directory,
        )

    def _resolve_backend_working_directory(
        self,
        runtime_session: StudioRuntimeSession,
        requested_working_directory: str | None,
    ) -> str | None:
        requested = (requested_working_directory or "").strip()
        absolute_base = str(
            resolve_runtime_absolute_working_directory(runtime_session) or ""
        ).strip()
        base = absolute_base or (runtime_session.working_directory or "").rstrip("/")
        if not requested:
            return base or None
        if requested.startswith("/"):
            return requested
        if not base:
            return requested
        return f"{base}/{requested}"

    def _resolve_jupyter_working_directory(
        self,
        runtime_session: StudioRuntimeSession,
        requested_working_directory: str | None,
    ) -> str | None:
        requested = (requested_working_directory or "").strip()
        base = (runtime_session.working_directory or "").rstrip("/")
        if not requested:
            return base or None
        if requested.startswith("/"):
            return requested
        if not base:
            return requested
        return f"{base}/{requested}"

    async def _execute_jupyter_runtime_task(
        self,
        *,
        runtime_task_id: str,
        session: StudioSession,
        runtime_session: StudioRuntimeSession,
        execution_id: str,
        request: StudioExecutionRequest,
    ) -> None:
        target = self._build_jupyter_runtime_target(
            runtime_session,
            project_id=session.project_id,
        )
        with self._lock:
            current = self._executions.get(execution_id)
            if current is None:
                return
            running_execution = current.model_copy(
                update={
                    "status": StudioExecutionStatus.RUNNING,
                    "updated_at": _utc_now(),
                    "result": StudioExecutionResult(
                        stubbed=False,
                        summary="Execution is running on the bound Jupyter kernel",
                    ),
                }
            )
            self._executions[execution_id] = running_execution

        try:
            handle = await ensure_session(
                target,
                existing_session_id=runtime_session.jupyter_session_id,
                timeout_seconds=request.timeout_seconds,
            )
            await self._studio_session_runtime.update_runtime_session(
                runtime_session.id,
                status=StudioSessionStatus.BUSY,
                jupyter_session_id=handle.session_id,
                jupyter_kernel_id=handle.kernel_id,
                metadata_updates={
                    "last_execution_id": execution_id,
                    "last_execution_backend": StudioExecutionBackend.JUPYTER_KERNEL.value,
                },
            )
            result = await execute_python_code(
                target,
                handle=handle,
                code=request.code or "",
                working_directory=self._resolve_jupyter_working_directory(
                    runtime_session,
                    request.working_directory,
                ),
                env=request.env,
                timeout_seconds=request.timeout_seconds,
            )
        except asyncio.CancelledError:
            await self._studio_session_runtime.update_runtime_session(
                runtime_session.id,
                status=StudioSessionStatus.READY,
            )
            raise
        except Exception as exc:
            logger.exception(
                "Studio Jupyter execution failed for runtime session %s",
                runtime_session.id,
            )
            await self._mark_jupyter_execution_failed(
                execution_id,
                runtime_session.id,
                runtime_task_id=runtime_task_id,
                message=str(exc),
            )
            return

        status = (
            StudioExecutionStatus.SUCCEEDED
            if result.status == "ok"
            else StudioExecutionStatus.FAILED
        )
        now = _utc_now()
        with self._lock:
            current = self._executions.get(execution_id)
            if current is None:
                return
            metadata = dict(current.metadata or {})
            metadata.update(
                {
                    "runtime_session_id": runtime_session.id,
                    "runtime_task_id": runtime_task_id,
                    "backend_mode": "jupyter_kernel",
                    "backend_jupyter_session_id": handle.session_id,
                    "backend_jupyter_kernel_id": handle.kernel_id,
                    "backend_jupyter_execution_count": result.execution_count,
                    "backend_jupyter_error_name": result.error_name,
                    "backend_jupyter_error_value": result.error_value,
                }
            )
            updated = current.model_copy(
                update={
                    "status": status,
                    "metadata": metadata,
                    "updated_at": now,
                    "completed_at": now,
                    "result": StudioExecutionResult(
                        stubbed=False,
                        exit_code=0 if status == StudioExecutionStatus.SUCCEEDED else 1,
                        stdout=result.stdout,
                        stderr=result.stderr,
                        artifacts=result.outputs,
                        summary=result.summary,
                    ),
                }
            )
            self._executions[execution_id] = updated

        await self._studio_session_runtime.update_runtime_session(
            runtime_session.id,
            status=StudioSessionStatus.READY,
            jupyter_session_id=handle.session_id,
            jupyter_kernel_id=handle.kernel_id,
            metadata_updates={
                "last_execution_id": execution_id,
                "last_execution_status": status.value,
            },
        )

    async def _mark_jupyter_execution_failed(
        self,
        execution_id: str,
        runtime_session_id: str,
        *,
        runtime_task_id: str,
        message: str,
    ) -> None:
        now = _utc_now()
        with self._lock:
            current = self._executions.get(execution_id)
            if current is None:
                return
            metadata = dict(current.metadata or {})
            metadata.update(
                {
                    "runtime_session_id": runtime_session_id,
                    "runtime_task_id": runtime_task_id,
                    "backend_mode": "jupyter_kernel",
                    "backend_error": message,
                }
            )
            updated = current.model_copy(
                update={
                    "status": StudioExecutionStatus.FAILED,
                    "metadata": metadata,
                    "updated_at": now,
                    "completed_at": now,
                    "result": StudioExecutionResult(
                        stubbed=False,
                        exit_code=1,
                        stdout=current.result.stdout if current.result else "",
                        stderr=message,
                        artifacts=current.result.artifacts if current.result else [],
                        summary=message or "Execution failed on the bound Jupyter kernel",
                    ),
                }
            )
            self._executions[execution_id] = updated
        await self._studio_session_runtime.update_runtime_session(
            runtime_session_id,
            status=StudioSessionStatus.DEGRADED,
            metadata_updates={
                "last_execution_id": execution_id,
                "last_execution_status": StudioExecutionStatus.FAILED.value,
                "last_error": message,
            },
        )

    async def _load_backend_job(self, backend_job_id: str) -> Any | None:
        app_state = self._get_app_state()
        job_adapter = getattr(app_state, "job_adapter", None) if app_state else None
        if job_adapter is None:
            return None
        return await job_adapter.get_job(backend_job_id)

    async def _cancel_backend_job(self, backend_job_id: str, reason: str) -> bool:
        app_state = self._get_app_state()
        job_adapter = getattr(app_state, "job_adapter", None) if app_state else None
        if job_adapter is None:
            return False
        canceled = await job_adapter.cancel_job(backend_job_id, reason)
        if canceled:
            executor = self._get_direct_tool_executor()
            if executor is not None:
                try:
                    executor.cancel(backend_job_id)
                except Exception:
                    logger.debug("Direct executor cancellation failed for %s", backend_job_id)
        return canceled

    async def _cancel_runtime_task(
        self,
        execution: StudioExecution,
        reason: str | None,
    ) -> None:
        runtime_task_id = str(execution.metadata.get("runtime_task_id") or "")
        if not runtime_task_id:
            return
        runtime = await self._studio_session_runtime.get_runtime_session(
            execution.runtime_session_id
        )
        if runtime is not None and runtime.jupyter_kernel_id and runtime.jupyter_base_url:
            try:
                await interrupt_kernel(
                    self._build_jupyter_runtime_target(
                        runtime,
                        project_id=execution.project_id,
                    ),
                    kernel_id=runtime.jupyter_kernel_id,
                    timeout_seconds=5,
                )
            except Exception:
                logger.debug(
                    "Failed to interrupt Jupyter kernel %s",
                    runtime.jupyter_kernel_id,
                )
        task = self._backend_tasks.get(runtime_task_id)
        if task is not None and not task.done():
            task.cancel()
        if runtime is not None:
            await self._studio_session_runtime.update_runtime_session(
                runtime.id,
                status=StudioSessionStatus.READY,
                metadata_updates={
                    "last_execution_id": execution.id,
                    "last_execution_status": StudioExecutionStatus.CANCELED.value,
                    "last_cancel_reason": reason or "Studio execution canceled",
                },
            )

    async def _execute_backend_job_inprocess(
        self,
        *,
        backend_job_id: str,
        shell_command: str,
        runtime_kind: str,
        timeout_seconds: int | None,
    ) -> None:
        app_state = self._get_app_state()
        job_adapter = getattr(app_state, "job_adapter", None) if app_state else None
        job_store = getattr(app_state, "job_store", None) if app_state else None
        if job_adapter is None or job_store is None:
            return

        job = await job_adapter.get_job(backend_job_id)
        if job is None:
            return

        if getattr(job, "cancellation_requested", False) or str(getattr(job, "status", "")).lower() == "cancelled":
            await self._mark_job_cancelled(job, job_adapter, "Execution cancelled before start")
            return

        from brain_researcher.services.agent.tool_executor import (
            ToolExecutionRequest,
            ToolExecutor,
        )
        from brain_researcher.services.orchestrator.job_management_endpoints import (
            JobStatus,
        )

        executor = self._get_direct_tool_executor()
        if executor is None:
            executor = ToolExecutor(bg_loop_name="StudioExecutionRuntime-AsyncLoop")
            self._direct_tool_executor = executor

        now = _utc_now_naive()
        job.status = JobStatus.RUNNING
        job.started_at = now
        await job_adapter.update_job(job)

        tool_request = ToolExecutionRequest(
            tool_name="shell_command",
            parameters={"command": shell_command},
            execution_id=backend_job_id,
            timeout=timeout_seconds,
            execute_directly=True,
            context={"job_store": job_store, "job_id": backend_job_id},
            runtime_kind=runtime_kind,
        )

        try:
            result = await asyncio.to_thread(executor.execute, tool_request)
        except Exception as exc:
            logger.exception("Studio execution backend failed for job %s", backend_job_id)
            refreshed = await job_adapter.get_job(backend_job_id) or job
            await self._mark_job_failed(refreshed, job_adapter, str(exc))
            await self._refresh_bound_execution_from_job(backend_job_id)
            return

        refreshed = await job_adapter.get_job(backend_job_id) or job
        await self._apply_tool_result_to_job(refreshed, job_adapter, result)
        if not self._update_bound_execution_from_tool_result(backend_job_id, refreshed, result):
            await self._refresh_bound_execution_from_job(backend_job_id)

    async def _mark_job_cancelled(self, job: Any, job_adapter: Any, reason: str) -> None:
        from brain_researcher.services.orchestrator.job_management_endpoints import (
            JobStatus,
        )

        now = _utc_now_naive()
        job.status = JobStatus.CANCELLED
        job.completed_at = now
        job.error = reason
        await job_adapter.update_job(job)

    async def _mark_job_failed(self, job: Any, job_adapter: Any, reason: str) -> None:
        from brain_researcher.services.orchestrator.job_management_endpoints import (
            JobStatus,
        )

        now = _utc_now_naive()
        job.status = JobStatus.FAILED
        job.completed_at = now
        job.error = reason
        await job_adapter.update_job(job)

    async def _apply_tool_result_to_job(
        self,
        job: Any,
        job_adapter: Any,
        result: Any,
    ) -> None:
        from brain_researcher.services.orchestrator.job_management_endpoints import (
            JobStatus,
        )

        status = str(getattr(result, "status", "") or "").lower()
        metadata = dict(getattr(result, "metadata", {}) or {})
        payload = getattr(result, "result", None)
        payload_data = payload if isinstance(payload, dict) else {}
        stdout_text = self._coerce_result_text(payload_data.get("stdout"))
        stderr_text = self._coerce_result_text(payload_data.get("stderr"))
        returncode = payload_data.get("returncode")
        now = _utc_now_naive()

        job.run_id = metadata.get("run_id") or getattr(job, "run_id", None)
        job.run_dir = metadata.get("run_dir") or getattr(job, "run_dir", None)
        job.provenance_path = metadata.get("provenance_path") or getattr(
            job, "provenance_path", None
        )
        existing_job_metadata = dict(getattr(job, "metadata", {}) or {})
        if stdout_text:
            existing_job_metadata["result_stdout"] = stdout_text
        if stderr_text:
            existing_job_metadata["result_stderr"] = stderr_text
        if returncode is not None:
            existing_job_metadata["result_returncode"] = returncode
        if getattr(result, "command", None):
            existing_job_metadata["result_command"] = str(result.command)
        if metadata:
            existing_job_metadata.update(metadata)
        job.metadata = existing_job_metadata
        job.completed_at = now

        failure_message = self._derive_tool_result_error(result, payload_data)
        if status == "success":
            job.status = JobStatus.COMPLETED
            job.error = None
        elif status in {"cancelled", "canceled"}:
            job.status = JobStatus.CANCELLED
            job.error = failure_message or "Execution canceled"
        elif status == "timeout":
            job.status = JobStatus.TIMEOUT
            job.error = failure_message or "Execution timed out"
        else:
            job.status = JobStatus.FAILED
            job.error = failure_message or "Execution failed"

        await job_adapter.update_job(job)

    async def _refresh_bound_execution_from_job(self, backend_job_id: str) -> None:
        execution_id = self._job_bindings.get(backend_job_id)
        if not execution_id:
            return
        with self._lock:
            execution = self._executions.get(execution_id)
        if execution is None:
            return
        await self._hydrate_execution(execution)

    def _get_direct_tool_executor(self) -> Any | None:
        return self._direct_tool_executor

    async def _hydrate_execution(self, execution: StudioExecution) -> StudioExecution:
        backend_job_id = str(execution.metadata.get("backend_job_id") or "")
        runtime_task_id = str(execution.metadata.get("runtime_task_id") or "")
        if runtime_task_id and not backend_job_id:
            with self._lock:
                return self._executions.get(execution.id, execution)
        if not backend_job_id:
            return execution
        job = await self._load_backend_job(backend_job_id)
        if job is None:
            return execution

        hydrated = execution.model_copy(
            update=self._build_execution_update_from_job(execution, job)
        )
        if self._should_preserve_existing_execution(execution, hydrated):
            metadata = dict(hydrated.metadata or {})
            metadata.update(
                {
                    "backend_job_status": hydrated.metadata.get("backend_job_status"),
                    "backend_run_id": hydrated.metadata.get("backend_run_id"),
                    "backend_run_dir": hydrated.metadata.get("backend_run_dir"),
                    "backend_provenance_path": hydrated.metadata.get("backend_provenance_path"),
                }
            )
            hydrated = execution.model_copy(
                update={
                    "metadata": metadata,
                    "updated_at": hydrated.updated_at,
                    "completed_at": hydrated.completed_at,
                }
            )
        with self._lock:
            self._executions[execution.id] = hydrated
        return hydrated

    @staticmethod
    def _should_preserve_existing_execution(
        current: StudioExecution,
        hydrated: StudioExecution,
    ) -> bool:
        terminal_statuses = {
            StudioExecutionStatus.SUCCEEDED,
            StudioExecutionStatus.FAILED,
            StudioExecutionStatus.CANCELED,
        }
        if current.status not in terminal_statuses or hydrated.status != current.status:
            return False

        current_result = current.result
        hydrated_result = hydrated.result
        current_error = str(current.metadata.get("backend_error") or "").strip()
        hydrated_error = str(hydrated.metadata.get("backend_error") or "").strip()
        current_returncode = current.metadata.get("backend_returncode")
        hydrated_returncode = hydrated.metadata.get("backend_returncode")
        current_stdout = str(current_result.stdout or "").strip() if current_result else ""
        current_stderr = str(current_result.stderr or "").strip() if current_result else ""
        hydrated_stdout = str(hydrated_result.stdout or "").strip() if hydrated_result else ""
        hydrated_stderr = str(hydrated_result.stderr or "").strip() if hydrated_result else ""
        current_summary = str(current_result.summary or "").strip() if current_result else ""
        hydrated_summary = str(hydrated_result.summary or "").strip() if hydrated_result else ""

        current_is_richer = bool(
            current_error
            or current_returncode is not None
            or current_stdout
            or current_stderr
            or (
                current_summary
                and current_summary
                not in {
                    "Execution failed",
                    "Execution completed successfully",
                    "Execution canceled",
                }
            )
        )
        hydrated_is_sparse = not (
            hydrated_error
            or hydrated_returncode is not None
            or hydrated_stdout
            or hydrated_stderr
            or (
                hydrated_summary
                and hydrated_summary
                not in {
                    "Execution failed",
                    "Execution completed successfully",
                    "Execution canceled",
                }
            )
        )
        return current_is_richer and hydrated_is_sparse

    def _update_bound_execution_from_tool_result(
        self,
        backend_job_id: str,
        job: Any,
        result: Any,
    ) -> bool:
        execution_id = self._job_bindings.get(backend_job_id)
        if not execution_id:
            return False
        with self._lock:
            current = self._executions.get(execution_id)
        if current is None:
            return False

        normalized_job_status = self._normalize_job_status(getattr(job, "status", None))
        execution_status = self._map_job_status_to_execution_status(normalized_job_status)
        payload = getattr(result, "result", None)
        payload_data = payload if isinstance(payload, dict) else {}
        stdout_text = self._coerce_result_text(payload_data.get("stdout"))
        stderr_text = self._coerce_result_text(payload_data.get("stderr"))
        exit_code = self._coerce_exit_code(payload_data.get("returncode"))
        backend_error = self._derive_tool_result_error(result, payload_data) or self._stringify_job_error(
            getattr(job, "error", None)
        )
        summary = (
            backend_error
            if execution_status == StudioExecutionStatus.FAILED and backend_error
            else self._build_result_summary(job, execution_status)
        )

        metadata = dict(current.metadata or {})
        metadata.update(
            {
                "backend_job_status": normalized_job_status,
                "backend_run_id": getattr(job, "run_id", None),
                "backend_run_dir": str(self._resolve_run_dir(getattr(job, "run_dir", None)) or "")
                or None,
                "backend_provenance_path": getattr(job, "provenance_path", None),
                "backend_error": backend_error,
                "backend_returncode": exit_code,
            }
        )
        completed_at = self._coerce_datetime(getattr(job, "completed_at", None)) or _utc_now()
        updated = current.model_copy(
            update={
                "status": execution_status,
                "metadata": metadata,
                "updated_at": completed_at,
                "completed_at": completed_at
                if execution_status.value in _TERMINAL_EXECUTION_STATUSES
                else None,
                "result": StudioExecutionResult(
                    stubbed=False,
                    exit_code=exit_code
                    if exit_code is not None
                    else self._infer_exit_code(execution_status),
                    stdout=stdout_text,
                    stderr=stderr_text,
                    artifacts=[],
                    summary=summary,
                ),
            }
        )
        with self._lock:
            self._executions[execution_id] = updated
        return True

    def _build_execution_update_from_job(
        self, execution: StudioExecution, job: Any
    ) -> dict[str, Any]:
        normalized_job_status = self._normalize_job_status(getattr(job, "status", None))
        execution_status = self._map_job_status_to_execution_status(normalized_job_status)
        run_dir = self._resolve_run_dir(getattr(job, "run_dir", None))
        job_metadata = dict(getattr(job, "metadata", {}) or {})
        stdout_text = self._read_output_file(run_dir, "stdout.txt") or self._coerce_result_text(
            job_metadata.get("result_stdout")
        )
        stderr_text = self._read_output_file(run_dir, "stderr.txt") or self._coerce_result_text(
            job_metadata.get("result_stderr")
        )
        stored_returncode = job_metadata.get("result_returncode")
        result = StudioExecutionResult(
            stubbed=False,
            exit_code=self._coerce_exit_code(stored_returncode)
            if self._coerce_exit_code(stored_returncode) is not None
            else self._infer_exit_code(execution_status),
            stdout=stdout_text,
            stderr=stderr_text,
            artifacts=self._collect_artifacts(job, run_dir),
            summary=self._build_result_summary(job, execution_status),
        )

        metadata = dict(execution.metadata or {})
        metadata.update(
            {
                "backend_job_status": normalized_job_status,
                "backend_run_id": getattr(job, "run_id", None),
                "backend_run_dir": str(run_dir) if run_dir else None,
                "backend_provenance_path": getattr(job, "provenance_path", None),
                "backend_error": self._stringify_job_error(getattr(job, "error", None)),
                "backend_returncode": self._coerce_exit_code(stored_returncode),
            }
        )

        completed_at = self._coerce_datetime(getattr(job, "completed_at", None))
        updated_at = (
            completed_at
            or self._coerce_datetime(getattr(job, "started_at", None))
            or execution.updated_at
        )

        return {
            "status": execution_status,
            "metadata": metadata,
            "result": result,
            "updated_at": updated_at,
            "completed_at": completed_at
            if execution_status.value in _TERMINAL_EXECUTION_STATUSES
            else None,
        }

    @staticmethod
    def _map_job_status_to_execution_status(job_status: str) -> StudioExecutionStatus:
        if job_status in {"running", "claimed", "retrying", "cancelling"}:
            return StudioExecutionStatus.RUNNING
        if job_status == "completed":
            return StudioExecutionStatus.SUCCEEDED
        if job_status in {"failed", "timeout"}:
            return StudioExecutionStatus.FAILED
        if job_status == "cancelled":
            return StudioExecutionStatus.CANCELED
        return StudioExecutionStatus.ACCEPTED

    @staticmethod
    def _normalize_job_status(job_status: Any) -> str:
        if job_status is None:
            return "pending"
        value = getattr(job_status, "value", job_status)
        return str(value).strip().lower()

    @staticmethod
    def _coerce_datetime(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        return None

    @staticmethod
    def _resolve_run_dir(run_dir: Any) -> Path | None:
        if not run_dir:
            return None
        try:
            return Path(str(run_dir))
        except Exception:
            return None

    @staticmethod
    def _read_output_file(run_dir: Path | None, filename: str) -> str:
        if run_dir is None:
            return ""
        file_path = run_dir / filename
        if not file_path.exists():
            return ""
        try:
            return file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def _collect_artifacts(self, job: Any, run_dir: Path | None) -> list[dict[str, Any]]:
        artifacts: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        for artifact in getattr(job, "artifacts", []) or []:
            if hasattr(artifact, "model_dump"):
                payload = artifact.model_dump(mode="json")
            elif isinstance(artifact, dict):
                payload = dict(artifact)
            else:
                continue
            path_value = str(payload.get("path") or payload.get("url") or "")
            if path_value:
                seen_paths.add(path_value)
            artifacts.append(payload)

        if run_dir is not None:
            artifact_specs = [
                ("stdout.txt", "log", "text/plain"),
                ("stderr.txt", "log", "text/plain"),
                ("provenance.json", "json", "application/json"),
                ("hash.json", "json", "application/json"),
            ]
            for name, artifact_type, mime_type in artifact_specs:
                file_path = run_dir / name
                if not file_path.exists():
                    continue
                path_value = str(file_path)
                if path_value in seen_paths:
                    continue
                try:
                    file_size = file_path.stat().st_size
                except OSError:
                    file_size = None
                artifacts.append(
                    {
                        "id": f"studio:{name}",
                        "name": name,
                        "type": artifact_type,
                        "path": path_value,
                        "mime_type": mime_type,
                        "size": file_size,
                    }
                )
        return artifacts

    def _build_result_summary(
        self, job: Any, execution_status: StudioExecutionStatus
    ) -> str:
        if execution_status == StudioExecutionStatus.ACCEPTED:
            return self._queued_summary(
                str(getattr(job, "metadata", {}).get("backend_mode", "orchestrator_job"))
            )
        if execution_status == StudioExecutionStatus.RUNNING:
            return "Execution is running on the orchestrator backend"
        if execution_status == StudioExecutionStatus.SUCCEEDED:
            return "Execution completed successfully"
        if execution_status == StudioExecutionStatus.CANCELED:
            return self._stringify_job_error(getattr(job, "error", None)) or "Execution canceled"
        return self._stringify_job_error(getattr(job, "error", None)) or "Execution failed"

    @staticmethod
    def _stringify_job_error(error: Any) -> str | None:
        if error is None:
            return None
        if isinstance(error, str):
            return error
        if isinstance(error, dict):
            detail = error.get("error") if "error" in error else error
            if isinstance(detail, dict):
                message = detail.get("message") or detail.get("detail")
                if message:
                    return str(message)
            return str(detail)
        return str(error)

    @staticmethod
    def _infer_exit_code(status: StudioExecutionStatus) -> int | None:
        if status == StudioExecutionStatus.SUCCEEDED:
            return 0
        if status == StudioExecutionStatus.CANCELED:
            return 130
        if status == StudioExecutionStatus.FAILED:
            return 1
        return None

    @staticmethod
    def _coerce_result_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    @staticmethod
    def _coerce_exit_code(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _derive_tool_result_error(self, result: Any, payload_data: dict[str, Any]) -> str | None:
        explicit_error = str(getattr(result, "error", "") or "").strip()
        if explicit_error:
            return explicit_error
        stderr_text = self._coerce_result_text(payload_data.get("stderr")).strip()
        if stderr_text:
            return stderr_text
        returncode = self._coerce_exit_code(payload_data.get("returncode"))
        if returncode is not None and returncode != 0:
            return f"Command failed with exit code {returncode}"
        stdout_text = self._coerce_result_text(payload_data.get("stdout")).strip()
        if stdout_text:
            return stdout_text
        return None

    def _build_shell_command(
        self, request: StudioExecutionRequest
    ) -> tuple[str, str]:
        if request.kind == StudioExecutionKind.CODE:
            language = (request.language or "python").strip().lower()
            code = (request.code or "").strip()
            if language in {"python", "python3", "py"}:
                base_command = f"python -c {shlex.quote(code)}"
                runtime_kind = "python"
            else:
                base_command = f"bash -lc {shlex.quote(code)}"
                runtime_kind = "container"
        else:
            base_command = shlex.join(request.command)
            runtime_kind = "container"

        if request.runtime_backend == StudioExecutionBackend.JUPYTER_KERNEL:
            runtime_kind = "python"
        elif request.runtime_backend in {
            StudioExecutionBackend.CONTAINER,
            StudioExecutionBackend.NEURODESK_MODULE,
        }:
            runtime_kind = "container"

        script_lines = ["set -euo pipefail"]
        if request.runtime_backend == StudioExecutionBackend.NEURODESK_MODULE:
            # Neurodesk module execution must run inside a shell with Lmod initialized.
            script_lines.append(_LMOD_INIT_SNIPPET)
        for key, value in sorted((request.env or {}).items()):
            script_lines.append(f"export {key}={shlex.quote(value)}")
        if request.working_directory:
            script_lines.append(f"cd {shlex.quote(request.working_directory)}")
        script_lines.append(base_command)
        return f"bash -lc {shlex.quote(chr(10).join(script_lines))}", runtime_kind
