from __future__ import annotations

import asyncio
from pathlib import Path
from types import MethodType, SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brain_researcher.services.orchestrator.endpoints.studio_assistant import (
    router as assistant_router,
)
from brain_researcher.services.orchestrator.endpoints.studio_notebook import (
    router as notebook_router,
)
from brain_researcher.services.orchestrator.endpoints.studio_sessions import (
    router as session_router,
)
from brain_researcher.services.orchestrator.studio_assistant_runtime import (
    StudioAssistantNotebookOp,
    StudioAssistantPlan,
    StudioAssistantPlannerSource,
    StudioAssistantRuntime,
)
from brain_researcher.services.orchestrator.studio_notebook_runtime import (
    StudioNotebookRuntime,
)
from brain_researcher.services.orchestrator.studio_session_runtime import (
    StudioSessionRuntime,
)


@pytest.fixture
def studio_assistant_client(
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
    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.endpoints.studio_assistant._resolve_request_user",
        _fake_user,
    )
    monkeypatch.setenv(
        "BR_STUDIO_JUPYTER_WORKDIR_ROOT",
        str(tmp_path / "workdir"),
    )

    app = FastAPI()
    app.include_router(session_router)
    app.include_router(notebook_router)
    app.include_router(assistant_router)
    app.state.studio_session_runtime = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=tmp_path / "studio_assistant.sqlite",
    )
    app.state.studio_notebook_runtime = StudioNotebookRuntime(
        studio_session_runtime=app.state.studio_session_runtime,
    )
    assistant_runtime = StudioAssistantRuntime(
        studio_session_runtime=app.state.studio_session_runtime,
        studio_notebook_runtime=app.state.studio_notebook_runtime,
    )

    async def _fake_request_agent_plan(self, **_kwargs):
        return StudioAssistantPlan(
            assistant_message="Added a markdown note and a Python cell.",
            ops=[
                StudioAssistantNotebookOp(
                    type="append",
                    cell_type="markdown",
                    source="## Research goal\n\nMap the task structure.",
                ),
                StudioAssistantNotebookOp(
                    type="append",
                    cell_type="code",
                    source='print("hello")',
                ),
            ],
            source=StudioAssistantPlannerSource.AGENT_TYPED,
        )

    assistant_runtime._request_agent_plan = MethodType(  # type: ignore[method-assign]
        _fake_request_agent_plan,
        assistant_runtime,
    )
    app.state.studio_assistant_runtime = assistant_runtime

    with TestClient(app) as client:
        yield client


def _create_session(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/studio/sessions",
        json={
            "project_id": "proj_studio_assistant",
            "display_name": "Studio Assistant Demo",
            "runtime_profile_id": "standard",
            "metadata": {"source": "studio"},
        },
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 200
    return response.json()["session"]


def test_get_studio_assistant_state_bootstraps_thread(
    studio_assistant_client: TestClient,
) -> None:
    session = _create_session(studio_assistant_client)

    response = studio_assistant_client.get(
        f"/api/studio/sessions/{session['id']}/assistant",
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["assistant_session_id"] == session["assistant_session_id"]
    assert payload["thread"]["thread_id"].startswith("thread_")
    assert payload["thread"]["message_count"] == 1
    assert payload["messages"][0]["role"] == "assistant"
    assert "Tell me what notebook you want to generate" in payload["messages"][0]["content"]


def test_submit_studio_assistant_turn_persists_thread_and_updates_notebook(
    studio_assistant_client: TestClient,
    tmp_path: Path,
) -> None:
    session = _create_session(studio_assistant_client)

    response = studio_assistant_client.post(
        f"/api/studio/sessions/{session['id']}/assistant/turns",
        json={
            "content": "Add a markdown research goal and a Python hello cell.",
            "notebook": {
                "path": f"projects/{session['project_id']}/notebooks/studio/{session['id']}.ipynb",
                "title": "Studio notebook",
                "kernel_name": "python3",
                "revision": 1,
                "cells": [],
            },
        },
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["plan"]["source"] == "agent_typed"
    assert payload["assistant_message"]["content"] == "Added a markdown note and a Python cell."
    assert payload["messages"][-2]["role"] == "user"
    assert payload["messages"][-1]["role"] == "assistant"
    cells = payload["notebook"]["cells"]
    assert any(cell["cell_type"] == "markdown" and "Research goal" in cell["source"] for cell in cells)
    assert any(cell["cell_type"] == "code" and 'print("hello")' in cell["source"] for cell in cells)

    notebook_file = (
        tmp_path
        / "workdir"
        / session["project_id"]
        / "notebooks/studio"
        / f"{session['id']}.ipynb"
    )
    assert notebook_file.exists()

    persisted = studio_assistant_client.get(
        f"/api/studio/sessions/{session['id']}/assistant",
        headers={"Authorization": "Bearer test"},
    )
    assert persisted.status_code == 200
    persisted_payload = persisted.json()
    assert persisted_payload["thread"]["message_count"] == 3
    assert persisted_payload["messages"][-1]["content"] == "Added a markdown note and a Python cell."


def test_submit_studio_assistant_turn_fallback_builds_t1_visualization_notebook(
    studio_assistant_client: TestClient,
) -> None:
    session = _create_session(studio_assistant_client)
    runtime = studio_assistant_client.app.state.studio_assistant_runtime
    planner_called = False

    async def _should_not_run_agent_plan(self, **_kwargs):
        nonlocal planner_called
        planner_called = True
        return None

    runtime._request_agent_plan = MethodType(  # type: ignore[method-assign]
        _should_not_run_agent_plan,
        runtime,
    )

    response = studio_assistant_client.post(
        f"/api/studio/sessions/{session['id']}/assistant/turns",
        json={
            "content": "Generate a notebook for visualizing T1 images.",
            "notebook": {
                "path": f"projects/{session['project_id']}/notebooks/studio/{session['id']}.ipynb",
                "title": "Studio notebook",
                "kernel_name": "python3",
                "revision": 1,
                "cells": [],
            },
        },
        headers={"Authorization": "Bearer test"},
    )

    assert response.status_code == 200
    assert planner_called is False
    payload = response.json()
    assert payload["plan"]["source"] == "heuristic_fallback"
    assert payload["plan"]["fallback_reason"] == "fast_path"
    assert "T1 visualization notebook scaffold" in payload["assistant_message"]["content"]
    cells = payload["notebook"]["cells"]
    assert any(
        cell["cell_type"] == "markdown" and "T1 visualization notebook" in cell["source"]
        for cell in cells
    )
    assert any(
        cell["cell_type"] == "code" and "nibabel" in cell["source"] and "sub-01_T1w.nii.gz" in cell["source"]
        for cell in cells
    )


def test_submit_studio_assistant_turn_same_prompt_does_not_append_duplicate_cells(
    studio_assistant_client: TestClient,
) -> None:
    session = _create_session(studio_assistant_client)
    payload = {
        "content": "Add a markdown research goal and a Python hello cell.",
        "notebook": {
            "path": f"projects/{session['project_id']}/notebooks/studio/{session['id']}.ipynb",
            "title": "Studio notebook",
            "kernel_name": "python3",
            "revision": 1,
            "cells": [],
        },
    }

    first = studio_assistant_client.post(
        f"/api/studio/sessions/{session['id']}/assistant/turns",
        json=payload,
        headers={"Authorization": "Bearer test"},
    )
    assert first.status_code == 200
    first_payload = first.json()
    assert len(first_payload["notebook"]["cells"]) >= 2

    payload["notebook"] = {
        "path": first_payload["notebook"]["path"],
        "title": first_payload["notebook"]["title"],
        "kernel_name": first_payload["notebook"]["kernel_name"],
        "revision": first_payload["notebook"]["revision"],
        "cells": [
            {
                "id": cell["id"],
                "cell_type": cell["cell_type"],
                "source": cell["source"],
                "status": cell["status"],
            }
            for cell in first_payload["notebook"]["cells"]
        ],
    }

    second = studio_assistant_client.post(
        f"/api/studio/sessions/{session['id']}/assistant/turns",
        json=payload,
        headers={"Authorization": "Bearer test"},
    )
    assert second.status_code == 200
    second_payload = second.json()
    assert len(second_payload["notebook"]["cells"]) == len(first_payload["notebook"]["cells"])
    assert "did not append the same cells again" in second_payload["assistant_message"]["content"]


def test_cat12_prompt_does_not_trigger_t1_visualization_scaffold(
    studio_assistant_client: TestClient,
) -> None:
    session = _create_session(studio_assistant_client)
    runtime = studio_assistant_client.app.state.studio_assistant_runtime

    async def _should_not_run_agent_plan(self, **_kwargs):
        return None

    runtime._request_agent_plan = MethodType(  # type: ignore[method-assign]
        _should_not_run_agent_plan,
        runtime,
    )

    response = studio_assistant_client.post(
        f"/api/studio/sessions/{session['id']}/assistant/turns",
        json={
            "content": "Generate a notebook to run CAT12 VBM via Neurodesk using module load cat12/r2166 and explain each step.",
            "notebook": {
                "path": f"projects/{session['project_id']}/notebooks/studio/{session['id']}.ipynb",
                "title": "Studio notebook",
                "kernel_name": "python3",
                "revision": 1,
                "cells": [],
            },
        },
        headers={"Authorization": "Bearer test"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["plan"]["source"] == "heuristic_fallback"
    assert "Neurodesk execution scaffold" in payload["assistant_message"]["content"]
    cells = payload["notebook"]["cells"]
    assert any(
        cell["cell_type"] == "markdown" and "Neurodesk execution scaffold" in cell["source"]
        for cell in cells
    )
    assert any(
        cell["cell_type"] == "code"
        and "module load cat12/r2166" in cell["source"]
        and "print(shell_script)" in cell["source"]
        for cell in cells
    )
    assert all("sub-01_T1w.nii.gz" not in cell["source"] for cell in cells)


def test_fmri_qc_prompt_builds_carpet_plot_scaffold(
    studio_assistant_client: TestClient,
) -> None:
    session = _create_session(studio_assistant_client)
    runtime = studio_assistant_client.app.state.studio_assistant_runtime

    async def _should_not_run_agent_plan(self, **_kwargs):
        return None

    runtime._request_agent_plan = MethodType(  # type: ignore[method-assign]
        _should_not_run_agent_plan,
        runtime,
    )

    response = studio_assistant_client.post(
        f"/api/studio/sessions/{session['id']}/assistant/turns",
        json={
            "content": "Generate a notebook that loads a preprocessed BOLD run, inspects confounds, and renders a carpet plot for QC.",
            "notebook": {
                "path": f"projects/{session['project_id']}/notebooks/studio/{session['id']}.ipynb",
                "title": "Studio notebook",
                "kernel_name": "python3",
                "revision": 1,
                "cells": [],
            },
        },
        headers={"Authorization": "Bearer test"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["plan"]["source"] == "heuristic_fallback"
    assert "fMRI QC scaffold" in payload["assistant_message"]["content"]
    cells = payload["notebook"]["cells"]
    assert any(
        cell["cell_type"] == "markdown" and "fMRI QC scaffold" in cell["source"]
        for cell in cells
    )
    assert any(
        cell["cell_type"] == "code"
        and "plot_carpet" in cell["source"]
        and "desc-confounds_timeseries.tsv" in cell["source"]
        for cell in cells
    )


def test_glm_prompt_builds_first_level_model_scaffold(
    studio_assistant_client: TestClient,
) -> None:
    session = _create_session(studio_assistant_client)
    runtime = studio_assistant_client.app.state.studio_assistant_runtime

    async def _should_not_run_agent_plan(self, **_kwargs):
        return None

    runtime._request_agent_plan = MethodType(  # type: ignore[method-assign]
        _should_not_run_agent_plan,
        runtime,
    )

    response = studio_assistant_client.post(
        f"/api/studio/sessions/{session['id']}/assistant/turns",
        json={
            "content": "Generate a notebook for an OpenNeuro motor task first-level GLM with events, confounds, and a design matrix.",
            "notebook": {
                "path": f"projects/{session['project_id']}/notebooks/studio/{session['id']}.ipynb",
                "title": "Studio notebook",
                "kernel_name": "python3",
                "revision": 1,
                "cells": [],
            },
        },
        headers={"Authorization": "Bearer test"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["plan"]["source"] == "heuristic_fallback"
    assert "first-level GLM scaffold" in payload["assistant_message"]["content"]
    cells = payload["notebook"]["cells"]
    assert any(
        cell["cell_type"] == "markdown" and "First-level GLM scaffold" in cell["source"]
        for cell in cells
    )
    assert any(
        cell["cell_type"] == "code"
        and "FirstLevelModel" in cell["source"]
        and "plot_design_matrix" in cell["source"]
        for cell in cells
    )


def test_request_agent_plan_hits_agent_route(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from brain_researcher.services.orchestrator.studio_assistant_runtime import (
        StudioAssistantRuntime,
    )

    requests: list[dict[str, object]] = []

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):  # noqa: D401 - signature parity
            self.timeout = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str, json: dict[str, object] | None = None):
            requests.append({"url": url, "json": json or {}})
            request = httpx.Request("POST", url)
            return httpx.Response(
                status_code=200,
                json={
                    "assistant_message": "Planned.",
                    "ops": [],
                    "source": "agent_typed",
                },
                request=request,
            )

    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.studio_assistant_runtime.httpx.AsyncClient",
        MockAsyncClient,
    )

    runtime = StudioAssistantRuntime(
        studio_session_runtime=SimpleNamespace(_db_path=tmp_path / "session.sqlite"),
        studio_notebook_runtime=SimpleNamespace(),
    )
    session = SimpleNamespace(
        id="studio_sess_1",
        assistant_session_id="ast_demo",
        project_id="proj_demo",
        metadata={},
    )
    thread = SimpleNamespace(thread_id="thread_demo")
    notebook = SimpleNamespace(
        id="nb_demo",
        path="projects/proj/notebooks/studio/studio_sess_1.ipynb",
        cells=[],
    )

    plan = asyncio.run(
        runtime._request_agent_plan(
            owner_user_id="user_demo",
            session=session,
            thread=thread,
            notebook=notebook,
            conversation=[],
            prompt="Add a markdown note.",
        )
    )

    assert len(requests) == 1
    request_payload = requests[0]
    assert isinstance(request_payload["url"], str)
    assert request_payload["url"].endswith("/agent/studio/plan")
    metadata = request_payload["json"]["metadata"]
    assert metadata["owner_user_id"] == "user_demo"
    assert metadata["project_id"] == "proj_demo"
    assert metadata["workspace_id"] == "proj_demo"
    assert plan is not None
    assert plan.source == StudioAssistantPlannerSource.AGENT_TYPED
    assert plan.assistant_message == "Planned."


def test_submit_studio_assistant_turn_exposes_planner_fallback_observability_on_agent_error(
    studio_assistant_client: TestClient,
) -> None:
    session = _create_session(studio_assistant_client)
    runtime = studio_assistant_client.app.state.studio_assistant_runtime

    async def _raise_agent_unavailable(self, **_kwargs):
        raise httpx.RequestError(
            "planner offline",
            request=httpx.Request("POST", "http://agent.example/agent/studio/plan"),
        )

    runtime._request_agent_plan = MethodType(  # type: ignore[method-assign]
        _raise_agent_unavailable,
        runtime,
    )

    response = studio_assistant_client.post(
        f"/api/studio/sessions/{session['id']}/assistant/turns",
        json={
            "content": "Add a markdown research goal and a Python hello cell.",
            "notebook": {
                "path": f"projects/{session['project_id']}/notebooks/studio/{session['id']}.ipynb",
                "title": "Studio notebook",
                "kernel_name": "python3",
                "revision": 1,
                "cells": [],
            },
        },
        headers={"Authorization": "Bearer test"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["plan"]["source"] == "heuristic_fallback"
    assert payload["plan"]["fallback_reason"] == "agent_error"
    assert payload["plan"]["planner_error"] == {
        "code": "agent_unavailable",
        "message": "planner offline",
        "status_code": None,
    }
    assert payload["assistant_message"]["metadata"]["planner_source"] == "heuristic_fallback"
    assert payload["assistant_message"]["metadata"]["planner_fallback_reason"] == "agent_error"
    assert payload["assistant_message"]["metadata"]["planner_error_code"] == "agent_unavailable"


def test_submit_studio_assistant_turn_normalizes_draft_notebook_path_on_first_turn(
    studio_assistant_client: TestClient,
    tmp_path: Path,
) -> None:
    session = _create_session(studio_assistant_client)

    response = studio_assistant_client.post(
        f"/api/studio/sessions/{session['id']}/assistant/turns",
        json={
            "content": "Add a markdown research goal and a Python hello cell.",
            "notebook": {
                "path": f"projects/{session['project_id']}/notebooks/studio/draft.ipynb",
                "title": "Studio notebook",
                "kernel_name": "python3",
                "revision": 1,
                "cells": [],
            },
        },
        headers={"Authorization": "Bearer test"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["notebook"]["path"] == (
        f"projects/{session['project_id']}/notebooks/studio/{session['id']}.ipynb"
    )
    notebook_file = (
        tmp_path
        / "workdir"
        / session["project_id"]
        / "notebooks/studio"
        / f"{session['id']}.ipynb"
    )
    assert notebook_file.exists()
