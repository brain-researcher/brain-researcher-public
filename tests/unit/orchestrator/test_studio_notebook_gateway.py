from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brain_researcher.services.orchestrator.endpoints.studio_notebook import (
    router as notebook_router,
)
from brain_researcher.services.orchestrator.endpoints.studio_sessions import (
    router as session_router,
)
from brain_researcher.services.orchestrator.studio_execution_runtime import (
    StudioExecution,
    StudioExecutionResult,
    StudioExecutionStatus,
)
from brain_researcher.services.orchestrator.studio_notebook_runtime import (
    StudioNotebookRuntime,
)
from brain_researcher.services.orchestrator.studio_session_runtime import (
    StudioSessionRuntime,
)


class _FakeExecutionRuntime:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def create_execution(self, owner_user_id, session_id, request):
        execution = StudioExecution(
            id="exec_fake001",
            session_id=session_id,
            runtime_session_id="rt_fake001",
            project_id="proj_notebook_demo",
            owner_user_id=owner_user_id,
            kind=request.kind,
            runtime_backend=request.runtime_backend,
            runtime_profile_id=request.runtime_profile_id,
            status=StudioExecutionStatus.SUCCEEDED,
            language=request.language,
            code=request.code,
            command=request.command,
            working_directory=request.working_directory,
            env=request.env,
            timeout_seconds=request.timeout_seconds,
            metadata={
                "backend_mode": "jupyter_kernel",
                "backend_jupyter_error_name": None,
                "backend_jupyter_error_value": None,
            },
            request_summary="Notebook cell execution",
            result=StudioExecutionResult(
                stubbed=False,
                exit_code=0,
                stdout="hello from notebook\n",
                stderr="",
                artifacts=[
                    {
                        "type": "execute_result",
                        "data": {"text/plain": "hello from notebook"},
                        "metadata": {},
                        "execution_count": 7,
                    }
                ],
                summary="Execution completed on the bound Jupyter kernel",
            ),
        )
        self.calls.append(
            {
                "owner_user_id": owner_user_id,
                "session_id": session_id,
                "working_directory": request.working_directory,
                "env": dict(request.env),
                "metadata": dict(request.metadata),
            }
        )
        return execution

    async def get_execution(self, owner_user_id, session_id, execution_id):
        return None


@pytest.fixture
def notebook_gateway_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> TestClient:
    async def _fake_user(_request):
        return SimpleNamespace(id="user_demo"), {}

    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.endpoints.studio_sessions._resolve_request_user",
        _fake_user,
    )
    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.endpoints.studio_notebook._resolve_request_user",
        _fake_user,
    )
    monkeypatch.setenv(
        "BR_STUDIO_JUPYTER_WORKDIR_ROOT",
        str(tmp_path / "workdir"),
    )

    app = FastAPI()
    app.include_router(session_router)
    app.include_router(notebook_router)
    app.state.studio_session_runtime = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=tmp_path / "studio_sessions.sqlite",
    )
    app.state.studio_notebook_runtime = StudioNotebookRuntime(
        studio_session_runtime=app.state.studio_session_runtime,
        studio_execution_runtime=_FakeExecutionRuntime(),
    )
    with TestClient(app) as client:
        yield client


def _create_session(client: TestClient, project_id: str) -> dict[str, object]:
    response = client.post(
        "/api/studio/sessions",
        json={
            "project_id": project_id,
            "display_name": "Notebook Demo",
            "runtime_profile_id": "standard",
            "metadata": {"source": "studio"},
        },
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 200
    return response.json()["session"]


def test_open_create_get_patch_and_execute_studio_notebook(
    notebook_gateway_client: TestClient,
    tmp_path: Path,
) -> None:
    session = _create_session(notebook_gateway_client, "proj_notebook_demo")

    open_resp = notebook_gateway_client.post(
        f"/api/studio/sessions/{session['id']}/notebook/open-or-create",
        json={
            "title": "Brain Researcher Notebook",
            "metadata": {"surface": "studio"},
            "cells": [
                {
                    "cell_type": "code",
                    "source": "print('hello from notebook')",
                },
                {
                    "cell_type": "markdown",
                    "source": "# Notes",
                },
            ],
        },
        headers={"Authorization": "Bearer test"},
    )
    assert open_resp.status_code == 200
    notebook = open_resp.json()["notebook"]
    assert notebook["title"] == "Brain Researcher Notebook"
    assert (
        notebook["path"]
        == f"projects/proj_notebook_demo/notebooks/studio/{session['id']}.ipynb"
    )
    assert len(notebook["cells"]) == 2
    code_cell = notebook["cells"][0]
    assert code_cell["cell_type"] == "code"
    assert code_cell["id"].startswith("cell_")

    notebook_file = (
        tmp_path
        / "workdir"
        / "proj_notebook_demo"
        / "notebooks/studio"
        / f"{session['id']}.ipynb"
    )
    assert notebook_file.exists()

    get_resp = notebook_gateway_client.get(
        f"/api/studio/sessions/{session['id']}/notebook",
        headers={"Authorization": "Bearer test"},
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["notebook"]["title"] == "Brain Researcher Notebook"

    patch_resp = notebook_gateway_client.patch(
        f"/api/studio/sessions/{session['id']}/notebook",
        json={
            "title": "Updated Notebook Title",
            "metadata": {"surface": "studio", "updated": True},
        },
        headers={"Authorization": "Bearer test"},
    )
    assert patch_resp.status_code == 200
    patched = patch_resp.json()["notebook"]
    assert patched["title"] == "Updated Notebook Title"
    assert patched["revision"] == notebook["revision"] + 1

    execute_resp = notebook_gateway_client.post(
        f"/api/studio/sessions/{session['id']}/notebook/cells/{code_cell['id']}/execute",
        json={"timeout_seconds": 30, "env": {"BR_NOTEBOOK_SMOKE": "1"}},
        headers={"Authorization": "Bearer test"},
    )
    assert execute_resp.status_code == 200
    executed = execute_resp.json()["notebook"]
    executed_cell = executed["cells"][0]
    assert executed_cell["execution_count"] == 7
    assert executed_cell["outputs"][0]["text"] == "hello from notebook\n"
    assert executed_cell["status"] == "succeeded"

    execution_runtime = notebook_gateway_client.app.state.studio_notebook_runtime._studio_execution_runtime
    assert execution_runtime.calls[0]["working_directory"] == "notebooks/studio"
    assert execution_runtime.calls[0]["env"] == {"BR_NOTEBOOK_SMOKE": "1"}

    persisted = notebook_file.read_text(encoding="utf-8")
    assert "hello from notebook" in persisted


def test_failed_local_execution_surfaces_error_output(
    notebook_gateway_client: TestClient,
) -> None:
    session = _create_session(notebook_gateway_client, "proj_notebook_failure")
    runtime = notebook_gateway_client.app.state.studio_notebook_runtime

    class _FailingExecutionRuntime:
        async def create_execution(self, owner_user_id, session_id, request):
            return StudioExecution(
                id="exec_failed001",
                session_id=session_id,
                runtime_session_id="rt_failed001",
                project_id="proj_notebook_failure",
                owner_user_id=owner_user_id,
                kind=request.kind,
                runtime_backend=request.runtime_backend,
                runtime_profile_id=request.runtime_profile_id,
                status=StudioExecutionStatus.FAILED,
                language=request.language,
                code=request.code,
                command=request.command,
                working_directory=request.working_directory,
                env=request.env,
                timeout_seconds=request.timeout_seconds,
                metadata={
                    "backend_kind": "orchestrator_job",
                    "backend_mode": "tool_executor_direct",
                    "backend_error": "Execution failed",
                    "resolved_working_directory": "/tmp/studio/projects/proj_notebook_failure/notebooks/studio",
                    "submitted_command": "python -c 'raise FileNotFoundError()'",
                },
                request_summary="Notebook cell execution",
                result=StudioExecutionResult(
                    stubbed=False,
                    exit_code=1,
                    stdout="",
                    stderr="",
                    artifacts=[],
                    summary="Execution failed",
                ),
            )

        async def get_execution(self, owner_user_id, session_id, execution_id):
            return None

    runtime._studio_execution_runtime = _FailingExecutionRuntime()

    open_resp = notebook_gateway_client.post(
        f"/api/studio/sessions/{session['id']}/notebook/open-or-create",
        json={
            "title": "Failure Notebook",
            "cells": [
                {
                    "cell_type": "code",
                    "source": "raise FileNotFoundError('missing file')",
                }
            ],
        },
        headers={"Authorization": "Bearer test"},
    )
    notebook = open_resp.json()["notebook"]
    code_cell = notebook["cells"][0]

    execute_resp = notebook_gateway_client.post(
        f"/api/studio/sessions/{session['id']}/notebook/cells/{code_cell['id']}/execute",
        json={"timeout_seconds": 30},
        headers={"Authorization": "Bearer test"},
    )
    assert execute_resp.status_code == 200
    executed = execute_resp.json()["notebook"]
    executed_cell = executed["cells"][0]
    assert executed_cell["status"] == "failed"
    assert executed_cell["outputs"][0]["output_type"] == "error"
    assert executed_cell["outputs"][0]["evalue"] == "Execution failed"
    joined_traceback = "\n".join(executed_cell["outputs"][0]["traceback"])
    assert "Working directory:" in joined_traceback
    assert "Backend: tool_executor_direct" in joined_traceback


def test_studio_notebook_operations_append_edit_and_move(
    notebook_gateway_client: TestClient,
) -> None:
    session = _create_session(notebook_gateway_client, "proj_ops_demo")

    notebook_gateway_client.post(
        f"/api/studio/sessions/{session['id']}/notebook/open-or-create",
        json={
            "title": "Ops Notebook",
            "cells": [
                {
                    "cell_type": "markdown",
                    "source": "## First note",
                }
            ],
        },
        headers={"Authorization": "Bearer test"},
    )

    get_resp = notebook_gateway_client.get(
        f"/api/studio/sessions/{session['id']}/notebook",
        headers={"Authorization": "Bearer test"},
    )
    cell_id = get_resp.json()["notebook"]["cells"][0]["id"]

    append_resp = notebook_gateway_client.post(
        f"/api/studio/sessions/{session['id']}/notebook/ops",
        json={
            "op": "append",
            "cell": {
                "cell_type": "markdown",
                "source": "## Second note",
            },
        },
        headers={"Authorization": "Bearer test"},
    )
    assert append_resp.status_code == 200
    notebook = append_resp.json()["notebook"]
    assert len(notebook["cells"]) == 2

    edit_resp = notebook_gateway_client.post(
        f"/api/studio/sessions/{session['id']}/notebook/ops",
        json={
            "op": "edit",
            "cell_id": cell_id,
            "source": "## Updated note",
        },
        headers={"Authorization": "Bearer test"},
    )
    assert edit_resp.status_code == 200
    assert edit_resp.json()["notebook"]["cells"][0]["source"] == "## Updated note"

    move_resp = notebook_gateway_client.post(
        f"/api/studio/sessions/{session['id']}/notebook/ops",
        json={
            "op": "edit_and_move",
            "cell_id": cell_id,
            "cell": {
                "cell_type": "markdown",
                "source": "## Relocated note",
            },
        },
        headers={"Authorization": "Bearer test"},
    )
    assert move_resp.status_code == 200
    moved_notebook = move_resp.json()["notebook"]
    assert len(moved_notebook["cells"]) == 2
    assert moved_notebook["cells"][-1]["source"] == "## Relocated note"


def test_studio_notebook_operations_accept_batch_operations_payload(
    notebook_gateway_client: TestClient,
) -> None:
    session = _create_session(notebook_gateway_client, "proj_batch_ops_demo")

    response = notebook_gateway_client.post(
        f"/api/studio/sessions/{session['id']}/notebook/ops",
        json={
            "ops": [
                {
                    "type": "append",
                    "cell": {
                        "cell_type": "markdown",
                        "source": "## Batch note",
                    },
                },
                {
                    "type": "append",
                    "cell": {
                        "cell_type": "code",
                        "source": 'print("batch")',
                    },
                },
            ],
        },
        headers={"Authorization": "Bearer test"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["operations"]) == 2
    notebook = payload["notebook"]
    assert any(cell["source"] == "## Batch note" for cell in notebook["cells"])
    assert any(cell["source"] == 'print("batch")' for cell in notebook["cells"])


def test_studio_notebook_falls_back_from_unwritable_jovyan_root(
    notebook_gateway_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session = _create_session(notebook_gateway_client, "proj_jovyan_fallback")
    session_runtime = notebook_gateway_client.app.state.studio_session_runtime

    runtime = asyncio.run(session_runtime.get_runtime_session(session["runtime_session_id"]))
    assert runtime is not None
    asyncio.run(
        session_runtime.update_runtime_session(
            runtime.id,
            metadata_updates={
                "absolute_working_directory": "/home/jovyan/work/projects/proj_jovyan_fallback"
            },
        )
    )

    def _fake_writable(path: Path) -> bool:
        if str(path).startswith("/home/jovyan/work/projects"):
            return False
        path.mkdir(parents=True, exist_ok=True)
        return True

    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.studio_session_runtime._path_is_writable_or_creatable",
        _fake_writable,
    )

    open_resp = notebook_gateway_client.post(
        f"/api/studio/sessions/{session['id']}/notebook/open-or-create",
        json={"title": "Fallback Notebook"},
        headers={"Authorization": "Bearer test"},
    )
    assert open_resp.status_code == 200

    fallback_file = (
        tmp_path
        / "workdir"
        / "proj_jovyan_fallback"
        / "notebooks/studio"
        / f"{session['id']}.ipynb"
    )
    assert fallback_file.exists()
