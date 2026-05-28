from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brain_researcher.services.agent.tool_executor import ToolExecutionResult
from brain_researcher.services.orchestrator.endpoints.studio_executions import (
    router as execution_router,
)
from brain_researcher.services.orchestrator.endpoints.studio_sessions import (
    router as session_router,
)
from brain_researcher.services.orchestrator.studio_execution_runtime import (
    StudioExecution,
    StudioExecutionBackend,
    StudioExecutionKind,
    StudioExecutionRequest,
    StudioExecutionResult,
    StudioExecutionRuntime,
    StudioExecutionStatus,
)
from brain_researcher.services.orchestrator.studio_session_runtime import (
    CreateStudioSessionRequest,
    StudioSessionRuntime,
    StudioSessionStatus,
)


@pytest.fixture
def studio_execution_db_path(tmp_path: Path) -> Path:
    return tmp_path / "studio_execution_sessions.sqlite"


@pytest.fixture
def studio_execution_backend_hooks(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    calls: dict[str, Any] = {
        "submit": [],
        "load": [],
        "cancel": [],
        "jobs": {},
    }

    async def _submit_backend_job(self, session, runtime_session, execution, request):
        backend_job_id = f"job_backend_{execution.id}"
        calls["submit"].append(
            {
                "session_id": session.id,
                "project_id": session.project_id,
                "runtime_session_id": runtime_session.id,
                "execution_id": execution.id,
                "request": request.model_dump(mode="json"),
            }
        )
        calls["jobs"][backend_job_id] = SimpleNamespace(
            id=backend_job_id,
            status="running",
            run_id=None,
            run_dir=None,
            provenance_path=None,
            error=None,
            artifacts=[],
            completed_at=None,
            started_at=datetime.now(timezone.utc),
            metadata={"backend_mode": "jobstore_worker"},
        )
        return {
            "backend_kind": "orchestrator_job",
            "backend_mode": "jobstore_worker",
            "backend_job_id": backend_job_id,
            "backend_job_url": f"/api/jobs/{backend_job_id}",
            "backend_artifacts_url": f"/api/jobs/{backend_job_id}/artifacts",
            "backend_logs_url": f"/api/jobs/{backend_job_id}/logs/stream",
            "submitted_command": "python -c 'print(1)'",
        }

    async def _load_backend_job(self, backend_job_id: str):
        calls["load"].append({"backend_job_id": backend_job_id})
        return calls["jobs"].get(backend_job_id)

    async def _cancel_backend_job(self, backend_job_id: str, reason: str):
        calls["cancel"].append(
            {
                "backend_job_id": backend_job_id,
                "reason": reason,
            }
        )
        job = calls["jobs"].get(backend_job_id)
        if job is not None:
            job.status = "cancelled"
            job.error = reason
            job.completed_at = datetime.now(timezone.utc)
        return True

    monkeypatch.setattr(
        StudioExecutionRuntime,
        "_submit_backend_job",
        _submit_backend_job,
        raising=False,
    )
    monkeypatch.setattr(
        StudioExecutionRuntime,
        "_load_backend_job",
        _load_backend_job,
        raising=False,
    )
    monkeypatch.setattr(
        StudioExecutionRuntime,
        "_cancel_backend_job",
        _cancel_backend_job,
        raising=False,
    )
    return calls


@pytest.fixture
def studio_execution_client(
    monkeypatch: pytest.MonkeyPatch,
    studio_execution_db_path: Path,
) -> TestClient:
    async def _fake_user(_request):
        return SimpleNamespace(id="user_demo"), {}

    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.endpoints.studio_sessions._resolve_request_user",
        _fake_user,
    )
    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.endpoints.studio_executions._resolve_request_user",
        _fake_user,
    )

    app = FastAPI()
    app.include_router(session_router)
    app.include_router(execution_router)
    app.state.studio_session_runtime = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=studio_execution_db_path,
    )
    app.state.studio_execution_runtime = StudioExecutionRuntime(
        studio_session_runtime=app.state.studio_session_runtime
    )
    with TestClient(app) as client:
        yield client


def _create_session(client: TestClient) -> dict[str, object]:
    resp = client.post(
        "/api/studio/sessions",
        json={
            "project_id": "proj_exec_demo",
            "display_name": "Execution Demo",
            "runtime_profile_id": "standard",
        },
        headers={"Authorization": "Bearer test"},
    )
    assert resp.status_code == 200
    return resp.json()["session"]


def test_create_code_execution_and_list(
    studio_execution_client: TestClient,
    studio_execution_backend_hooks: dict[str, Any],
) -> None:
    session = _create_session(studio_execution_client)

    create_resp = studio_execution_client.post(
        f"/api/studio/sessions/{session['id']}/executions",
        json={
            "kind": "code",
            "language": "bash",
            "code": "echo hello from studio",
            "runtime_backend": "container",
            "runtime_profile_id": "standard",
            "working_directory": "notebooks",
            "env": {"PYTHONUNBUFFERED": "1"},
            "timeout_seconds": 60,
            "dry_run": False,
            "metadata": {"source": "studio"},
        },
        headers={"Authorization": "Bearer test"},
    )
    assert create_resp.status_code == 200
    execution = create_resp.json()["execution"]
    assert execution["session_id"] == session["id"]
    assert execution["runtime_session_id"] == session["runtime_session_id"]
    assert execution["kind"] == "code"
    assert execution["status"] == "running"
    assert execution["result"]["stubbed"] is False
    assert execution["result"]["summary"] == "Execution is running on the orchestrator backend"
    assert execution["metadata"]["backend_job_id"] == f"job_backend_{execution['id']}"
    assert "stub" not in execution["request_summary"].lower()

    assert studio_execution_backend_hooks["submit"] == [
        {
            "session_id": session["id"],
            "project_id": session["project_id"],
            "runtime_session_id": session["runtime_session_id"],
            "execution_id": execution["id"],
            "request": {
                "kind": "code",
                "language": "bash",
                "code": "echo hello from studio",
                "command": [],
                "runtime_backend": "container",
                "runtime_profile_id": "standard",
                "working_directory": "notebooks",
                "env": {"PYTHONUNBUFFERED": "1"},
                "timeout_seconds": 60,
                "dry_run": False,
                "metadata": {"source": "studio"},
            },
        }
    ]

    list_resp = studio_execution_client.get(
        f"/api/studio/sessions/{session['id']}/executions",
        headers={"Authorization": "Bearer test"},
    )
    assert list_resp.status_code == 200
    listed_items = list_resp.json()["items"]
    assert [item["id"] for item in listed_items] == [execution["id"]]
    assert listed_items[0]["metadata"]["backend_job_id"] == f"job_backend_{execution['id']}"

    get_resp = studio_execution_client.get(
        f"/api/studio/sessions/{session['id']}/executions/{execution['id']}",
        headers={"Authorization": "Bearer test"},
    )
    assert get_resp.status_code == 200
    hydrated = get_resp.json()["execution"]
    assert hydrated["id"] == execution["id"]
    assert hydrated["status"] == "running"
    assert hydrated["result"]["summary"] == "Execution is running on the orchestrator backend"
    assert hydrated["metadata"]["backend_job_status"] == "running"
    assert studio_execution_backend_hooks["load"]


def test_create_command_execution_and_cancel(
    studio_execution_client: TestClient,
    studio_execution_backend_hooks: dict[str, Any],
) -> None:
    session = _create_session(studio_execution_client)

    create_resp = studio_execution_client.post(
        f"/api/studio/sessions/{session['id']}/executions",
        json={
            "kind": "command",
            "command": ["bash", "-lc", "echo hello"],
            "runtime_backend": "neurodesk_module",
            "runtime_profile_id": "high_mem",
            "working_directory": "/tmp",
            "dry_run": False,
        },
        headers={"Authorization": "Bearer test"},
    )
    assert create_resp.status_code == 200
    execution = create_resp.json()["execution"]
    assert execution["kind"] == "command"
    assert execution["runtime_session_id"] == session["runtime_session_id"]
    assert execution["runtime_backend"] == "neurodesk_module"
    assert execution["command"] == ["bash", "-lc", "echo hello"]
    assert execution["result"]["stubbed"] is False
    assert execution["metadata"]["backend_job_id"] == f"job_backend_{execution['id']}"

    cancel_resp = studio_execution_client.post(
        f"/api/studio/sessions/{session['id']}/executions/{execution['id']}/actions/cancel",
        json={"reason": "user_stopped"},
        headers={"Authorization": "Bearer test"},
    )
    assert cancel_resp.status_code == 200
    canceled = cancel_resp.json()["execution"]
    assert canceled["status"] == "canceled"
    assert canceled["result"]["summary"] == "user_stopped"
    assert canceled["metadata"]["backend_job_id"] == f"job_backend_{execution['id']}"
    assert studio_execution_backend_hooks["cancel"] == [
        {
            "backend_job_id": f"job_backend_{execution['id']}",
            "reason": "user_stopped",
        }
    ]


def test_rejects_missing_code_for_code_execution(
    studio_execution_client: TestClient,
) -> None:
    session = _create_session(studio_execution_client)

    resp = studio_execution_client.post(
        f"/api/studio/sessions/{session['id']}/executions",
        json={
            "kind": "code",
            "language": "python",
            "runtime_backend": "container",
        },
        headers={"Authorization": "Bearer test"},
    )
    assert resp.status_code == 400
    assert "non-empty code" in resp.json()["detail"]


def test_build_shell_command_wraps_neurodesk_module_backend() -> None:
    runtime = StudioExecutionRuntime()
    command, runtime_kind = runtime._build_shell_command(  # noqa: SLF001
        StudioExecutionRequest(
            kind=StudioExecutionKind.COMMAND,
            command=["python", "demo.py", "--flag"],
            runtime_backend=StudioExecutionBackend.NEURODESK_MODULE,
            dry_run=False,
            working_directory="/workspace/demo",
            env={"PYTHONUNBUFFERED": "1"},
        )
    )

    assert runtime_kind == "container"
    assert "source /etc/profile.d/lmod.sh" in command
    assert "cd /workspace/demo" in command
    assert "export PYTHONUNBUFFERED=1" in command
    assert "python demo.py --flag" in command


@pytest.mark.asyncio
async def test_jupyter_kernel_execution_binds_to_runtime_session(
    monkeypatch: pytest.MonkeyPatch,
    studio_execution_db_path: Path,
) -> None:
    session_runtime = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=studio_execution_db_path,
    )
    created_session = await session_runtime.create_or_attach_session(
        "user_demo",
        CreateStudioSessionRequest(
            project_id="proj_jupyter_demo",
            display_name="Jupyter Demo",
            runtime_profile_id="standard",
            metadata={
                "jupyter_base_url": "https://runtime.example/user/demo",
                "jupyter_token": "secret-token",
            },
        ),
    )
    execution_runtime = StudioExecutionRuntime(studio_session_runtime=session_runtime)

    async def _fake_ensure_session(target, *, existing_session_id, timeout_seconds=None):
        assert target.base_url == "https://runtime.example/user/demo"
        assert target.token == "secret-token"
        assert target.session_path.startswith("projects/proj_jupyter_demo")
        return SimpleNamespace(
            session_id="jupyter-session-123",
            kernel_id="kernel-abc",
            kernel_name="python3",
        )

    async def _fake_execute_python_code(
        target,
        *,
        handle,
        code,
        working_directory=None,
        env=None,
        timeout_seconds=None,
    ):
        assert handle.session_id == "jupyter-session-123"
        assert handle.kernel_id == "kernel-abc"
        assert working_directory == "projects/proj_jupyter_demo/notebooks"
        assert env == {}
        assert "print('hello from jupyter runtime')" in code
        return SimpleNamespace(
            status="ok",
            execution_count=7,
            stdout="hello from jupyter runtime\n",
            stderr="",
            outputs=[],
            summary="Execution completed on the bound Jupyter kernel",
            error_name=None,
            error_value=None,
        )

    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.studio_execution_runtime.ensure_session",
        _fake_ensure_session,
    )
    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.studio_execution_runtime.execute_python_code",
        _fake_execute_python_code,
    )

    created_execution = await execution_runtime.create_execution(
        "user_demo",
        created_session.id,
        StudioExecutionRequest(
            kind=StudioExecutionKind.CODE,
            language="python",
            code="print('hello from jupyter runtime')",
            runtime_backend=StudioExecutionBackend.JUPYTER_KERNEL,
            runtime_profile_id="standard",
            working_directory="notebooks",
            dry_run=False,
        ),
    )

    assert created_execution.runtime_session_id == created_session.runtime_session_id
    assert created_execution.metadata["runtime_session_id"] == created_session.runtime_session_id
    assert created_execution.status in {
        StudioExecutionStatus.ACCEPTED,
        StudioExecutionStatus.RUNNING,
    }

    await asyncio.sleep(0)

    hydrated = await execution_runtime.get_execution(
        "user_demo",
        created_session.id,
        created_execution.id,
    )
    assert hydrated is not None
    assert hydrated.status == StudioExecutionStatus.SUCCEEDED
    assert hydrated.result is not None
    assert hydrated.result.stdout == "hello from jupyter runtime\n"
    assert hydrated.metadata["backend_mode"] == "jupyter_kernel"
    assert hydrated.metadata["backend_jupyter_session_id"] == "jupyter-session-123"
    assert hydrated.metadata["backend_jupyter_kernel_id"] == "kernel-abc"

    runtime = await session_runtime.get_runtime_session(created_session.runtime_session_id)
    assert runtime is not None
    assert runtime.jupyter_session_id == "jupyter-session-123"
    assert runtime.jupyter_kernel_id == "kernel-abc"
    assert runtime.status == StudioSessionStatus.READY


def test_create_jupyter_execution_binds_runtime_session(
    studio_execution_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _create_session(studio_execution_client)
    runtime = studio_execution_client.app.state.studio_session_runtime

    async def _ensure_session(*_args, **_kwargs):
        return SimpleNamespace(
            session_id="jupyter_session_123",
            kernel_id="kernel_123",
            kernel_name="python3",
        )

    async def _execute_python_code(*_args, **_kwargs):
        return SimpleNamespace(
            status="ok",
            execution_count=7,
            stdout="hello from kernel\n",
            stderr="",
            outputs=[{"type": "execute_result", "data": {"text/plain": "42"}}],
            summary="Execution completed on the bound Jupyter kernel",
            error_name=None,
            error_value=None,
        )

    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.studio_execution_runtime.ensure_session",
        _ensure_session,
    )
    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.studio_execution_runtime.execute_python_code",
        _execute_python_code,
    )

    create_resp = studio_execution_client.post(
        f"/api/studio/sessions/{session['id']}/executions",
        json={
            "kind": "code",
            "language": "python",
            "code": "x = 41 + 1\nprint(x)",
            "runtime_backend": "container",
            "runtime_profile_id": "standard",
            "working_directory": "notebooks",
            "dry_run": False,
        },
        headers={"Authorization": "Bearer test"},
    )
    assert create_resp.status_code == 200
    execution = create_resp.json()["execution"]
    assert execution["runtime_session_id"] == session["runtime_session_id"]
    assert execution["runtime_backend"] == "jupyter_kernel"
    assert execution["status"] in {"accepted", "running"}

    import time

    deadline = time.time() + 2.0
    latest = execution
    while time.time() < deadline:
        get_resp = studio_execution_client.get(
            f"/api/studio/sessions/{session['id']}/executions/{execution['id']}",
            headers={"Authorization": "Bearer test"},
        )
        assert get_resp.status_code == 200
        latest = get_resp.json()["execution"]
        if latest["status"] == "succeeded":
            break
        time.sleep(0.05)

    assert latest["status"] == "succeeded"
    assert latest["result"]["stdout"] == "hello from kernel\n"
    assert latest["metadata"]["backend_jupyter_session_id"] == "jupyter_session_123"
    assert latest["metadata"]["backend_jupyter_kernel_id"] == "kernel_123"

    persisted_runtime = runtime._connect().execute(
        "SELECT * FROM studio_runtime_sessions WHERE id = ?",
        (session["runtime_session_id"],),
    ).fetchone()
    assert persisted_runtime is not None
    assert persisted_runtime["status"] == StudioSessionStatus.READY.value
    assert persisted_runtime["jupyter_session_id"] == "jupyter_session_123"
    assert persisted_runtime["jupyter_kernel_id"] == "kernel_123"


@pytest.mark.asyncio
async def test_apply_tool_result_to_job_uses_stderr_and_returncode(
    studio_execution_db_path: Path,
) -> None:
    runtime = StudioExecutionRuntime(
        studio_session_runtime=StudioSessionRuntime(
            workspace_base_url="https://workspace.example",
            db_path=studio_execution_db_path,
        )
    )

    class _Adapter:
        async def update_job(self, _job: Any) -> None:
            return None

    stderr_job = SimpleNamespace(
        run_id=None,
        run_dir=None,
        provenance_path=None,
        metadata={},
        completed_at=None,
        error=None,
        status="running",
    )
    await runtime._apply_tool_result_to_job(
        stderr_job,
        _Adapter(),
        ToolExecutionResult(
            execution_id="exec_stderr",
            tool_name="shell_command",
            status="error",
            result={
                "stdout": "",
                "stderr": "FileNotFoundError: missing T1 image",
                "returncode": 1,
            },
        ),
    )
    assert getattr(stderr_job.status, "value", stderr_job.status) == "failed"
    assert stderr_job.error == "FileNotFoundError: missing T1 image"
    assert stderr_job.metadata["result_stderr"] == "FileNotFoundError: missing T1 image"
    assert stderr_job.metadata["result_returncode"] == 1

    returncode_job = SimpleNamespace(
        run_id=None,
        run_dir=None,
        provenance_path=None,
        metadata={},
        completed_at=None,
        error=None,
        status="running",
    )
    await runtime._apply_tool_result_to_job(
        returncode_job,
        _Adapter(),
        ToolExecutionResult(
            execution_id="exec_returncode",
            tool_name="shell_command",
            status="error",
            result={
                "stdout": "",
                "stderr": "",
                "returncode": 1,
            },
        ),
    )
    assert getattr(returncode_job.status, "value", returncode_job.status) == "failed"
    assert returncode_job.error == "Command failed with exit code 1"
    assert returncode_job.metadata["result_returncode"] == 1


def test_update_bound_execution_from_tool_result_surfaces_direct_failure(
    studio_execution_db_path: Path,
) -> None:
    runtime = StudioExecutionRuntime(
        studio_session_runtime=StudioSessionRuntime(
            workspace_base_url="https://workspace.example",
            db_path=studio_execution_db_path,
        )
    )
    execution = StudioExecution(
        id="exec_BoundFailure1",
        session_id="studio_BoundFailure1",
        runtime_session_id="rt_BoundFailure1",
        project_id="proj_bound_failure",
        owner_user_id="user_demo",
        kind=StudioExecutionKind.CODE,
        runtime_backend=StudioExecutionBackend.JUPYTER_KERNEL,
        runtime_profile_id="standard",
        status=StudioExecutionStatus.RUNNING,
        language="python",
        code="print('hello')",
        command=[],
        working_directory="notebooks",
        env={},
        timeout_seconds=30,
        metadata={"backend_job_id": "jobBoundFailure1"},
        request_summary="Notebook cell execution",
        result=StudioExecutionResult(stubbed=False, summary="Execution is running"),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        accepted_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    with runtime._lock:
        runtime._executions[execution.id] = execution
    runtime._job_bindings["jobBoundFailure1"] = execution.id

    updated = runtime._update_bound_execution_from_tool_result(
        "jobBoundFailure1",
        SimpleNamespace(
            status="failed",
            run_id=None,
            run_dir=None,
            provenance_path=None,
            completed_at=datetime.now(timezone.utc),
            error="Command failed with exit code 1",
        ),
        ToolExecutionResult(
            execution_id=execution.id,
            tool_name="shell_command",
            status="error",
            result={"stdout": "", "stderr": "", "returncode": 1},
        ),
    )

    assert updated is True
    with runtime._lock:
        hydrated = runtime._executions[execution.id]
    assert hydrated.status == StudioExecutionStatus.FAILED
    assert hydrated.result is not None
    assert hydrated.result.summary == "Command failed with exit code 1"
    assert hydrated.result.exit_code == 1
    assert hydrated.metadata["backend_returncode"] == 1
    assert hydrated.metadata["backend_error"] == "Command failed with exit code 1"
