from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brain_researcher.services.orchestrator.endpoints.studio_sessions import router
from brain_researcher.services.orchestrator.studio_session_runtime import (
    CreateStudioSessionRequest,
    HubWorkspaceHandoffRequest,
    StudioSessionRuntime,
    WorkspaceHandoffRequest,
)


@pytest.fixture
def studio_session_db_path(tmp_path: Path) -> Path:
    return tmp_path / "studio_sessions.sqlite"


@pytest.fixture
def studio_session_client(
    monkeypatch: pytest.MonkeyPatch,
    studio_session_db_path: Path,
) -> TestClient:
    async def _fake_user(_request):
        return SimpleNamespace(id="user_demo"), {}

    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.endpoints.studio_sessions._resolve_request_user",
        _fake_user,
    )

    app = FastAPI()
    app.include_router(router)
    app.state.studio_session_runtime = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=studio_session_db_path,
    )
    with TestClient(app) as client:
        yield client


def test_create_attach_get_and_list_studio_sessions(
    studio_session_client: TestClient,
) -> None:
    create_resp = studio_session_client.post(
        "/api/studio/sessions",
        json={
            "project_id": "proj_motor_demo",
            "display_name": "Motor Demo",
            "runtime_profile_id": "standard",
            "attach_if_exists": True,
            "metadata": {"source": "studio"},
        },
        headers={"Authorization": "Bearer test"},
    )
    assert create_resp.status_code == 200
    created = create_resp.json()["session"]
    assert created["project_id"] == "proj_motor_demo"
    assert created["runtime_profile_id"] == "standard"
    assert created["metadata"]["source"] == "studio"
    runtime = studio_session_client.app.state.studio_session_runtime

    attach_resp = studio_session_client.post(
        "/api/studio/sessions",
        json={
            "project_id": "proj_motor_demo",
            "display_name": "Motor Demo Restored",
            "runtime_profile_id": "standard",
            "attach_if_exists": True,
            "metadata": {"restored": True},
        },
        headers={"Authorization": "Bearer test"},
    )
    assert attach_resp.status_code == 200
    attached = attach_resp.json()["session"]
    assert attached["id"] == created["id"]
    assert attached["metadata"]["source"] == "studio"
    assert attached["metadata"]["restored"] is True
    persisted_runtime = runtime._connect().execute(
        "SELECT * FROM studio_runtime_sessions WHERE id = ?",
        (created["runtime_session_id"],),
    ).fetchone()
    assert persisted_runtime is not None

    get_resp = studio_session_client.get(
        f"/api/studio/sessions/{created['id']}",
        headers={"Authorization": "Bearer test"},
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["session"]["assistant_session_id"].startswith("ast_")

    list_resp = studio_session_client.get(
        "/api/studio/sessions?project_id=proj_motor_demo",
        headers={"Authorization": "Bearer test"},
    )
    assert list_resp.status_code == 200
    assert [item["id"] for item in list_resp.json()["items"]] == [created["id"]]


def test_studio_session_actions_touch_and_close(
    studio_session_client: TestClient,
) -> None:
    create_resp = studio_session_client.post(
        "/api/studio/sessions",
        json={
            "project_id": "proj_action_demo",
            "display_name": "Action Demo",
            "runtime_profile_id": "standard",
        },
        headers={"Authorization": "Bearer test"},
    )
    session = create_resp.json()["session"]

    touch_resp = studio_session_client.post(
        f"/api/studio/sessions/{session['id']}/actions/touch",
        json={},
        headers={"Authorization": "Bearer test"},
    )
    assert touch_resp.status_code == 200
    assert touch_resp.json()["action"] == "touch"
    assert touch_resp.json()["session"]["status"] == "ready"

    close_resp = studio_session_client.post(
        f"/api/studio/sessions/{session['id']}/actions/close",
        json={"reason": "user_closed_panel"},
        headers={"Authorization": "Bearer test"},
    )
    assert close_resp.status_code == 200
    closed = close_resp.json()["session"]
    assert closed["status"] == "stopped"
    assert closed["metadata"]["close_reason"] == "user_closed_panel"


def test_workspace_handoff_reuses_active_runtime_by_default(
    studio_session_client: TestClient,
) -> None:
    create_resp = studio_session_client.post(
        "/api/studio/sessions",
        json={
            "project_id": "proj_workspace_demo",
            "display_name": "Workspace Demo",
            "runtime_profile_id": "high_mem",
        },
        headers={"Authorization": "Bearer test"},
    )
    session = create_resp.json()["session"]

    handoff_resp = studio_session_client.post(
        f"/api/studio/sessions/{session['id']}/workspace-handoff",
        json={
            "target_path": "scripts/demo.py",
            "initial_focus": "editor",
        },
        headers={"Authorization": "Bearer test"},
    )
    assert handoff_resp.status_code == 200
    handoff = handoff_resp.json()["handoff"]
    assert handoff["launch_mode"] == "reuse_active_runtime"
    assert handoff["runtime_profile_id"] == "high_mem"
    assert handoff["runtime_session_id"] == session["runtime_session_id"]
    assert (
        handoff["workspace_url"]
        == "https://workspace.example/lab/tree/projects/proj_workspace_demo/scripts/demo.py"
    )
    assert handoff["target_path"] == "projects/proj_workspace_demo/scripts/demo.py"


def test_workspace_handoff_can_request_clean_workspace(
    studio_session_client: TestClient,
) -> None:
    create_resp = studio_session_client.post(
        "/api/studio/sessions",
        json={
            "project_id": "proj_clean_workspace_demo",
            "display_name": "Clean Workspace Demo",
            "runtime_profile_id": "standard",
        },
        headers={"Authorization": "Bearer test"},
    )
    session = create_resp.json()["session"]

    handoff_resp = studio_session_client.post(
        f"/api/studio/sessions/{session['id']}/workspace-handoff",
        json={
            "notebook_path": "notebooks/analysis.ipynb",
            "runtime_profile_id": "gpu",
            "materialize_notebook_if_needed": True,
            "open_clean_workspace": True,
        },
        headers={"Authorization": "Bearer test"},
    )
    assert handoff_resp.status_code == 200
    handoff = handoff_resp.json()["handoff"]
    assert handoff["launch_mode"] == "provision_new_runtime"
    assert handoff["runtime_profile_id"] == "gpu"
    assert handoff["runtime_session_id"] is None
    assert (
        handoff["workspace_url"]
        == "https://workspace.example/lab/tree/projects/proj_clean_workspace_demo/notebooks/analysis.ipynb"
    )
    assert (
        handoff["notebook_path"]
        == "projects/proj_clean_workspace_demo/notebooks/analysis.ipynb"
    )
    assert handoff["materialize_notebook_if_needed"] is True


@pytest.mark.asyncio
async def test_create_attach_session_stops_stale_marimo_runtime_without_backing_pod(
    monkeypatch: pytest.MonkeyPatch,
    studio_session_db_path: Path,
) -> None:
    monkeypatch.setenv("BR_STUDIO_RUNTIME_LIVE_CHECK_ENABLED", "true")
    runtime = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=studio_session_db_path,
    )

    created = await runtime.create_or_attach_session(
        "user_demo",
        CreateStudioSessionRequest(
            project_id="proj_stale_attach_demo",
            display_name="Stale Attach Demo",
            runtime_profile_id="standard",
            runtime_kind="marimo",
        ),
    )

    monkeypatch.setattr(
        StudioSessionRuntime,
        "_runtime_backing_pod_is_live",
        lambda self, candidate: False if candidate.id == created.runtime_session_id else None,
    )

    attached = await runtime.create_or_attach_session(
        "user_demo",
        CreateStudioSessionRequest(
            project_id="proj_stale_attach_demo",
            display_name="Fresh Attach Demo",
            runtime_profile_id="standard",
            runtime_kind="marimo",
            attach_if_exists=True,
        ),
    )

    assert attached.id != created.id
    assert attached.runtime_session_id != created.runtime_session_id

    stale_session = await runtime.get_session(created.id)
    stale_runtime = await runtime.get_runtime_session(created.runtime_session_id)
    assert stale_session is not None
    assert stale_runtime is not None
    assert stale_session.status == "stopped"
    assert stale_runtime.status == "stopped"
    assert stale_session.metadata["cleanup_reason"] == "runtime_backing_pod_missing"
    assert stale_runtime.metadata["cleanup_reason"] == "runtime_backing_pod_missing"


@pytest.mark.asyncio
async def test_hub_handoff_does_not_reuse_runtime_without_backing_pod(
    monkeypatch: pytest.MonkeyPatch,
    studio_session_db_path: Path,
) -> None:
    monkeypatch.setenv("BR_STUDIO_RUNTIME_LIVE_CHECK_ENABLED", "true")
    runtime = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=studio_session_db_path,
    )

    created = await runtime.create_or_attach_session(
        "user_demo",
        CreateStudioSessionRequest(
            project_id="proj_stale_handoff_demo",
            display_name="Stale Handoff Demo",
            runtime_profile_id="standard",
            runtime_kind="marimo",
        ),
    )

    monkeypatch.setattr(
        StudioSessionRuntime,
        "_runtime_backing_pod_is_live",
        lambda self, candidate: False if candidate.id == created.runtime_session_id else None,
    )

    handoff = await runtime.build_hub_handoff(
        "user_demo",
        created.id,
        HubWorkspaceHandoffRequest(target_path="scripts/demo.py"),
    )

    assert handoff.launch_mode == "provision_new_runtime"
    assert handoff.runtime_session_id is None
    assert (
        handoff.workspace_url
        == f"https://workspace.example/hub?session_id={created.id}"
        "&path=projects%2Fproj_stale_handoff_demo%2Fscripts%2Fdemo.py"
    )

    stale_session = await runtime.get_session(created.id)
    stale_runtime = await runtime.get_runtime_session(created.runtime_session_id)
    assert stale_session is not None
    assert stale_runtime is not None
    assert stale_session.status == "stopped"
    assert stale_runtime.status == "stopped"


@pytest.mark.asyncio
async def test_studio_sessions_persist_across_runtime_instances(
    studio_session_db_path: Path,
) -> None:
    runtime_a = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=studio_session_db_path,
    )
    created = await runtime_a.create_or_attach_session(
        "user_demo",
        CreateStudioSessionRequest(
            project_id="proj_persist_demo",
            display_name="Persist Demo",
            runtime_profile_id="standard",
            metadata={"source": "first"},
        ),
    )

    runtime_b = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=studio_session_db_path,
    )
    loaded = await runtime_b.get_session(created.id)
    assert loaded is not None
    assert loaded.id == created.id
    assert loaded.metadata["source"] == "first"
    runtime = await runtime_b.get_runtime_session(created.runtime_session_id)
    assert runtime is not None
    assert runtime.project_id == "proj_persist_demo"
    assert runtime.jupyter_kernel_name == "python3"

    listed = await runtime_b.list_sessions(owner_user_id="user_demo")
    assert [item.id for item in listed] == [created.id]


@pytest.mark.asyncio
async def test_runtime_session_can_render_jupyter_base_url_from_template(
    monkeypatch: pytest.MonkeyPatch,
    studio_session_db_path: Path,
) -> None:
    monkeypatch.setenv(
        "BR_STUDIO_JUPYTER_BASE_URL_TEMPLATE",
        "https://hub.example/user/{jupyter_user_name_url}",
    )
    runtime = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=studio_session_db_path,
    )

    created = await runtime.create_or_attach_session(
        "user+demo@example.com",
        CreateStudioSessionRequest(
            project_id="proj_template_demo",
            display_name="Template Demo",
            runtime_profile_id="standard",
            metadata={"jupyter_user_name": "user+demo@example.com"},
        ),
    )

    bound_runtime = await runtime.get_runtime_session(created.runtime_session_id)
    assert bound_runtime is not None
    assert (
        bound_runtime.jupyter_base_url
        == "https://hub.example/user/user%2Bdemo%40example.com"
    )


@pytest.mark.asyncio
async def test_workspace_handoff_uses_runtime_jupyter_base_url_for_launch_url(
    monkeypatch: pytest.MonkeyPatch,
    studio_session_db_path: Path,
) -> None:
    monkeypatch.setenv(
        "BR_STUDIO_JUPYTER_BASE_URL_TEMPLATE",
        "https://hub.example/user/{jupyter_user_name_url}",
    )
    runtime = StudioSessionRuntime(
        workspace_base_url="https://hub.example",
        db_path=studio_session_db_path,
    )

    created = await runtime.create_or_attach_session(
        "user+demo@example.com",
        CreateStudioSessionRequest(
            project_id="proj_workspace_url_demo",
            display_name="Workspace URL Demo",
            runtime_profile_id="standard",
            metadata={"jupyter_user_name": "user+demo@example.com"},
        ),
    )

    handoff = await runtime.build_workspace_handoff(
        "user+demo@example.com",
        created.id,
        WorkspaceHandoffRequest(
            notebook_path="notebooks/analysis.ipynb",
        ),
    )

    assert (
        handoff.workspace_url
        == "https://hub.example/user/user%2Bdemo%40example.com/lab/tree/"
        "projects/proj_workspace_url_demo/notebooks/analysis.ipynb"
    )


@pytest.mark.asyncio
async def test_runtime_session_avoids_hosted_jupyter_default_in_local_dev(
    monkeypatch: pytest.MonkeyPatch,
    studio_session_db_path: Path,
) -> None:
    monkeypatch.setenv("BR_DEV_MODE", "true")
    monkeypatch.delenv("BR_STUDIO_JUPYTER_BASE_URL", raising=False)
    monkeypatch.delenv("BR_STUDIO_JUPYTER_BASE_URL_TEMPLATE", raising=False)
    monkeypatch.delenv("BR_PUBLIC_WORKSPACE_URL", raising=False)

    runtime = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=studio_session_db_path,
    )

    created = await runtime.create_or_attach_session(
        "user_demo",
        CreateStudioSessionRequest(
            project_id="proj_local_dev_runtime",
            display_name="Local Dev Runtime",
            runtime_profile_id="standard",
        ),
    )

    bound_runtime = await runtime.get_runtime_session(created.runtime_session_id)
    assert bound_runtime is not None
    assert bound_runtime.jupyter_base_url is None
    assert bound_runtime.status == "degraded"


@pytest.mark.asyncio
async def test_runtime_session_falls_back_to_local_writable_root(
    monkeypatch: pytest.MonkeyPatch,
    studio_session_db_path: Path,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("BR_STUDIO_JUPYTER_WORKDIR_ROOT", raising=False)
    monkeypatch.setenv("BR_STATE_DB", str(tmp_path / "state.sqlite"))

    def _fake_writable(path: Path) -> bool:
        if str(path).startswith("/home/jovyan/work/projects"):
            return False
        path.mkdir(parents=True, exist_ok=True)
        return True

    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.studio_session_runtime._path_is_writable_or_creatable",
        _fake_writable,
    )

    runtime = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=studio_session_db_path,
    )

    created = await runtime.create_or_attach_session(
        "user_demo",
        CreateStudioSessionRequest(
            project_id="proj_local_fallback",
            display_name="Local Fallback",
            runtime_profile_id="standard",
        ),
    )

    bound_runtime = await runtime.get_runtime_session(created.runtime_session_id)
    assert bound_runtime is not None
    assert bound_runtime.metadata["absolute_working_directory"] == str(
        (tmp_path / "studio-workspaces" / "proj_local_fallback").resolve()
    )
