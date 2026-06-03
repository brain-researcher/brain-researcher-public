from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brain_researcher.services.orchestrator.endpoints.hub_sessions import router
from brain_researcher.services.orchestrator.marimo_runtime_provisioner import (
    MarimoRuntimeTarget,
)
from brain_researcher.services.orchestrator.studio_session_runtime import (
    CreateStudioSessionRequest,
    HubWorkspaceHandoffRequest,
    StudioRuntimeKind,
    StudioSessionRuntime,
)


@pytest.fixture
def hub_session_db_path(tmp_path: Path) -> Path:
    return tmp_path / "hub_sessions.sqlite"


@pytest.fixture
def hub_session_client(
    monkeypatch: pytest.MonkeyPatch,
    hub_session_db_path: Path,
) -> TestClient:
    async def _fake_user(_request):
        return SimpleNamespace(id="user_demo"), {}

    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.endpoints.hub_sessions._resolve_request_user",
        _fake_user,
    )

    app = FastAPI()
    app.include_router(router)
    app.state.studio_session_runtime = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=hub_session_db_path,
    )
    with TestClient(app) as client:
        yield client


class _FakeProvisioner:
    def __init__(self, *, ready: bool = True, token: str | None = None) -> None:
        self.ready = ready
        self.token = token
        self.calls: list[str] = []
        self.destroy_calls: list[str] = []

    def ensure_runtime_token(self, spec, target, *, existing_token=None) -> str | None:
        return existing_token or self.token

    def ensure_target(self, spec) -> MarimoRuntimeTarget:
        self.calls.append(spec.runtime_session_id)
        service_name = f"br-marimo-{spec.runtime_session_id}"
        return MarimoRuntimeTarget(
            provisioner="fake",
            connection_mode="iframe" if self.ready else "pending",
            ready=self.ready,
            public_url=(
                f"https://workspace.example/hub/{service_name}" if self.ready else None
            ),
            websocket_url=(
                f"wss://workspace.example/hub/{service_name}" if self.ready else None
            ),
            internal_url=f"http://{service_name}:2718",
            namespace="test",
            pod_name=f"{service_name}-pod",
            service_name=service_name,
            workspace_mount_path=spec.absolute_working_directory,
            workspace_volume_kind="persistentVolumeClaim",
            status_reason="ready" if self.ready else "pod_pending",
        )

    def destroy_target(self, target: MarimoRuntimeTarget) -> None:
        if target.service_name:
            self.destroy_calls.append(target.service_name)


def test_create_get_and_delete_hub_session(hub_session_client: TestClient) -> None:
    create_resp = hub_session_client.post(
        "/api/hub/sessions",
        json={
            "project_id": "proj_marimo_demo",
            "display_name": "Marimo Demo",
            "runtime_profile_id": "standard",
            "metadata": {"source": "hub"},
            "notebook_path": "notebooks/demo.py",
            "initial_focus": "editor",
        },
        headers={"Authorization": "Bearer test"},
    )
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert created["session"]["project_id"] == "proj_marimo_demo"
    assert created["runtime"]["kind"] == "marimo"
    assert created["runtime"]["marimo_base_url"] == "https://workspace.example/hub"
    assert created["runtime"]["marimo_port"] == 2718
    assert created["session"]["metadata"]["runtime_binding"]["runtime_kind"] == "marimo"
    assert created["handoff"]["runtime_kind"] == "marimo"
    assert created["handoff"]["hub_base_url"] == "https://workspace.example/hub"
    assert (
        created["handoff"]["runtime_session_id"]
        == created["session"]["runtime_session_id"]
    )
    launch_qs = parse_qs(urlparse(created["handoff"]["workspace_url"]).query)
    assert launch_qs["session_id"] == [created["session"]["id"]]
    assert launch_qs["path"] == ["projects/proj_marimo_demo/notebooks/demo.py"]
    assert launch_qs["focus"] == ["editor"]

    get_resp = hub_session_client.get(
        f"/api/hub/sessions/{created['session']['id']}",
        headers={"Authorization": "Bearer test"},
    )
    assert get_resp.status_code == 200
    fetched = get_resp.json()
    assert fetched["session"]["id"] == created["session"]["id"]
    assert fetched["runtime"]["id"] == created["runtime"]["id"]
    assert fetched["handoff"]["workspace_url"] == (
        f"https://workspace.example/hub?session_id={created['session']['id']}"
    )

    delete_resp = hub_session_client.delete(
        f"/api/hub/sessions/{created['session']['id']}",
        headers={"Authorization": "Bearer test"},
    )
    assert delete_resp.status_code == 200
    deleted = delete_resp.json()
    assert deleted["action"] == "close"
    assert deleted["session"]["status"] == "stopped"


def test_hub_session_reuses_existing_marimo_runtime(
    hub_session_client: TestClient,
) -> None:
    first = hub_session_client.post(
        "/api/hub/sessions",
        json={
            "project_id": "proj_reuse_demo",
            "display_name": "Reuse Demo",
            "runtime_profile_id": "high_mem",
        },
        headers={"Authorization": "Bearer test"},
    )
    assert first.status_code == 200
    second = hub_session_client.post(
        "/api/hub/sessions",
        json={
            "project_id": "proj_reuse_demo",
            "display_name": "Reuse Demo Again",
            "runtime_profile_id": "high_mem",
            "attach_if_exists": True,
        },
        headers={"Authorization": "Bearer test"},
    )
    assert second.status_code == 200
    assert second.json()["session"]["id"] == first.json()["session"]["id"]
    assert second.json()["runtime"]["kind"] == "marimo"
    assert second.json()["handoff"]["launch_mode"] == "reuse_active_runtime"


def test_hub_workspace_handoff_supports_clean_launch_requests(
    hub_session_client: TestClient,
) -> None:
    created = hub_session_client.post(
        "/api/hub/sessions",
        json={
            "project_id": "proj_clean_demo",
            "display_name": "Clean Demo",
            "runtime_profile_id": "standard",
        },
        headers={"Authorization": "Bearer test"},
    ).json()

    handoff_resp = hub_session_client.post(
        f"/api/hub/sessions/{created['session']['id']}/handoff",
        json={
            "notebook_path": "notebooks/analysis.py",
            "initial_focus": "notebook",
            "materialize_notebook_if_needed": True,
            "open_clean_workspace": True,
        },
        headers={"Authorization": "Bearer test"},
    )
    assert handoff_resp.status_code == 200
    handoff = handoff_resp.json()["handoff"]
    assert handoff["launch_mode"] == "provision_new_runtime"
    assert handoff["runtime_session_id"] is None
    parsed = urlparse(handoff["workspace_url"])
    assert (
        f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        == "https://workspace.example/hub"
    )
    qs = parse_qs(parsed.query)
    assert qs["session_id"] == [created["session"]["id"]]
    assert qs["path"] == ["projects/proj_clean_demo/notebooks/analysis.py"]
    assert qs["focus"] == ["notebook"]
    assert qs["materialize_notebook_if_needed"] == ["1"]
    assert qs["open_clean_workspace"] == ["1"]


def test_create_hub_session_threads_taskbeacon_seed_into_runtime_metadata(
    hub_session_client: TestClient,
) -> None:
    response = hub_session_client.post(
        "/api/hub/sessions",
        json={
            "project_id": "proj_taskbeacon_demo",
            "display_name": "TaskBeacon Demo",
            "taskbeacon_repo": "TaskBeacon/T000015-ant",
            "taskbeacon_ref": "main",
        },
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["session"]["metadata"]["taskbeacon_repo"] == "TaskBeacon/T000015-ant"
    assert payload["session"]["metadata"]["taskbeacon_ref"] == "main"
    assert (
        payload["session"]["metadata"]["taskbeacon_target_path"]
        == "projects/proj_taskbeacon_demo/taskbeacon/T000015-ant"
    )
    assert payload["handoff"]["target_path"] == (
        "projects/proj_taskbeacon_demo/taskbeacon/T000015-ant"
    )
    launch_qs = parse_qs(urlparse(payload["handoff"]["workspace_url"]).query)
    assert launch_qs["path"] == ["projects/proj_taskbeacon_demo/taskbeacon/T000015-ant"]

    fetched = hub_session_client.get(
        f"/api/hub/sessions/{payload['session']['id']}",
        headers={"Authorization": "Bearer test"},
    )
    assert fetched.status_code == 200
    assert fetched.json()["handoff"]["target_path"] == (
        "projects/proj_taskbeacon_demo/taskbeacon/T000015-ant"
    )


def test_hub_session_resources_return_same_origin_manifest(
    hub_session_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = hub_session_client.post(
        "/api/hub/sessions",
        json={
            "project_id": "proj_resource_demo",
            "display_name": "Resource Demo",
            "runtime_profile_id": "standard",
        },
        headers={"Authorization": "Bearer test"},
    ).json()

    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.endpoints.hub_sessions._hub_session_resource_manifest",
        lambda: (
            {
                "uri": "tool://fsl_bet",
                "name": "fsl_bet",
                "description": "Skull-strip a T1 image.",
                "type": "tool",
                "data": {"tool_id": "fsl_bet", "backend": "python"},
                "details": "backend=python",
            },
            {
                "uri": "dataset://ds:openneuro:ds000001",
                "name": "Balloon Analog Risk Task",
                "description": "OpenNeuro example dataset.",
                "type": "dataset",
                "data": {"dataset_id": "ds:openneuro:ds000001"},
                "details": "repo=openneuro",
            },
            {
                "uri": "kg://Task:n-back",
                "name": "n-back",
                "description": "Task",
                "type": "kg",
                "data": {"kg_id": "Task:n-back", "node_type": "Task"},
                "details": "type=Task",
            },
        ),
    )

    response = hub_session_client.get(
        f"/api/hub/sessions/{created['session']['id']}/resources",
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert [item["uri"] for item in payload["resources"]] == [
        "tool://fsl_bet",
        "dataset://ds:openneuro:ds000001",
        "kg://Task:n-back",
    ]
    assert payload["resources"][0]["type"] == "tool"
    assert payload["resources"][1]["data"]["dataset_id"] == "ds:openneuro:ds000001"
    assert payload["resources"][2]["data"]["kg_id"] == "Task:n-back"


def test_build_kg_resource_items_returns_curated_manifest() -> None:
    from brain_researcher.services.orchestrator.endpoints import hub_sessions

    items = hub_sessions._build_kg_resource_items()

    assert any(item.uri == "kg://Task:n-back" for item in items)
    assert any(item.uri == "kg://Concept:working-memory" for item in items)
    assert any(item.uri == "kg://BrainRegion:hippocampus" for item in items)
    assert any(item.uri == "kg://Disorder:depression" for item in items)
    assert all(item.type == "kg" for item in items)


@pytest.mark.asyncio
async def test_hub_sessions_do_not_attach_to_existing_jupyter_sessions(
    hub_session_db_path: Path,
) -> None:
    runtime = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=hub_session_db_path,
    )
    jupyter_session = await runtime.create_or_attach_session(
        "user_demo",
        CreateStudioSessionRequest(
            project_id="proj_split_demo",
            display_name="Studio Session",
        ),
    )
    jupyter_runtime = await runtime.get_runtime_session(
        jupyter_session.runtime_session_id
    )
    assert jupyter_runtime is not None
    assert jupyter_runtime.kind == StudioRuntimeKind.JUPYTER

    marimo_session = await runtime.create_or_attach_session(
        "user_demo",
        CreateStudioSessionRequest(
            project_id="proj_split_demo",
            display_name="Hub Session",
            runtime_kind=StudioRuntimeKind.MARIMO,
        ),
    )
    marimo_runtime = await runtime.get_runtime_session(
        marimo_session.runtime_session_id
    )
    assert marimo_runtime is not None
    assert marimo_runtime.kind == StudioRuntimeKind.MARIMO
    assert marimo_session.id != jupyter_session.id
    assert marimo_session.runtime_session_id != jupyter_session.runtime_session_id


@pytest.mark.asyncio
async def test_marimo_runtime_uses_dedicated_workdir_root(
    monkeypatch: pytest.MonkeyPatch,
    hub_session_db_path: Path,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        "BR_STUDIO_MARIMO_WORKDIR_ROOT",
        str(tmp_path / "marimo-workdir"),
    )

    runtime = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=hub_session_db_path,
    )
    marimo_session = await runtime.create_or_attach_session(
        "user_demo",
        CreateStudioSessionRequest(
            project_id="proj_marimo_workdir",
            display_name="Hub Workdir",
            runtime_kind=StudioRuntimeKind.MARIMO,
        ),
    )
    marimo_runtime = await runtime.get_runtime_session(
        marimo_session.runtime_session_id
    )

    assert marimo_runtime is not None
    assert marimo_runtime.kind == StudioRuntimeKind.MARIMO
    assert marimo_runtime.metadata["absolute_working_directory"] == str(
        tmp_path / "marimo-workdir" / "proj_marimo_workdir"
    )


def test_hub_session_surfaces_runtime_target_and_reconciles_reuse(
    monkeypatch: pytest.MonkeyPatch,
    hub_session_db_path: Path,
) -> None:
    async def _fake_user(_request):
        return SimpleNamespace(id="user_demo"), {}

    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.endpoints.hub_sessions._resolve_request_user",
        _fake_user,
    )

    fake = _FakeProvisioner(ready=True)
    app = FastAPI()
    app.include_router(router)
    app.state.studio_session_runtime = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=hub_session_db_path,
        marimo_runtime_provisioner=fake,
    )

    with TestClient(app) as client:
        created = client.post(
            "/api/hub/sessions",
            json={
                "project_id": "proj_runtime_target",
                "display_name": "Runtime Target",
            },
            headers={"Authorization": "Bearer test"},
        )
        assert created.status_code == 200
        payload = created.json()
        runtime_id = payload["runtime"]["id"]
        target = payload["runtime"]["metadata"]["marimo_runtime_target"]
        assert target["provisioner"] == "fake"
        expected_runtime_url = f"https://workspace.example/hub/br-marimo-{runtime_id}"
        assert target["public_url"] == expected_runtime_url
        assert payload["handoff"]["runtime_target_url"] == expected_runtime_url
        assert payload["handoff"][
            "runtime_websocket_url"
        ] == expected_runtime_url.replace("https://", "wss://", 1)
        assert payload["handoff"]["runtime_connection_mode"] == "iframe"
        assert payload["handoff"]["runtime_target_ready"] is True

        fetched = client.get(
            f"/api/hub/sessions/{payload['session']['id']}",
            headers={"Authorization": "Bearer test"},
        )
        assert fetched.status_code == 200
        assert fetched.json()["handoff"]["runtime_target_url"] == expected_runtime_url
        assert fake.calls.count(runtime_id) >= 2

        deleted = client.delete(
            f"/api/hub/sessions/{payload['session']['id']}",
            headers={"Authorization": "Bearer test"},
        )
        assert deleted.status_code == 200
        assert fake.destroy_calls == [f"br-marimo-{runtime_id}"]


def test_hub_session_handoff_appends_marimo_access_token(
    monkeypatch: pytest.MonkeyPatch,
    hub_session_db_path: Path,
) -> None:
    async def _fake_user(_request):
        return SimpleNamespace(id="user_demo"), {}

    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.endpoints.hub_sessions._resolve_request_user",
        _fake_user,
    )

    fake = _FakeProvisioner(ready=True, token="tok_secret_123")
    app = FastAPI()
    app.include_router(router)
    app.state.studio_session_runtime = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=hub_session_db_path,
        marimo_runtime_provisioner=fake,
    )

    with TestClient(app) as client:
        created = client.post(
            "/api/hub/sessions",
            json={"project_id": "proj_token", "display_name": "Token"},
            headers={"Authorization": "Bearer test"},
        )
        assert created.status_code == 200
        payload = created.json()
        runtime_id = payload["runtime"]["id"]
        target_url = payload["handoff"]["runtime_target_url"]

        base = f"https://workspace.example/hub/br-marimo-{runtime_id}"
        assert target_url.startswith(f"{base}?")
        query = parse_qs(urlparse(target_url).query)
        assert query["access_token"] == ["tok_secret_123"]

        # The raw token must still be scrubbed from the runtime metadata payload;
        # it may only ride along on the handoff URL's access_token param.
        assert "marimo_runtime_token" not in payload["runtime"]["metadata"]


def test_hub_session_marks_pending_targets_as_provisioning(
    monkeypatch: pytest.MonkeyPatch,
    hub_session_db_path: Path,
) -> None:
    async def _fake_user(_request):
        return SimpleNamespace(id="user_demo"), {}

    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.endpoints.hub_sessions._resolve_request_user",
        _fake_user,
    )

    fake = _FakeProvisioner(ready=False)
    app = FastAPI()
    app.include_router(router)
    app.state.studio_session_runtime = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=hub_session_db_path,
        marimo_runtime_provisioner=fake,
    )

    with TestClient(app) as client:
        created = client.post(
            "/api/hub/sessions",
            json={
                "project_id": "proj_runtime_pending",
                "display_name": "Runtime Pending",
            },
            headers={"Authorization": "Bearer test"},
        )
        assert created.status_code == 200
        payload = created.json()
        assert payload["runtime"]["status"] == "provisioning"
        assert payload["session"]["status"] == "provisioning"
        assert payload["handoff"]["runtime_target_ready"] is False
        assert payload["handoff"]["runtime_target_reason"] == "pod_pending"
        assert payload["handoff"]["launch_mode"] == "provision_new_runtime"

        fetched = client.get(
            f"/api/hub/sessions/{payload['session']['id']}",
            headers={"Authorization": "Bearer test"},
        )
        assert fetched.status_code == 200
        refreshed = fetched.json()
        assert refreshed["runtime"]["status"] == "provisioning"
        assert refreshed["session"]["status"] == "provisioning"
        assert refreshed["handoff"]["runtime_target_ready"] is False
        assert refreshed["handoff"]["runtime_target_reason"] == "pod_pending"


@pytest.mark.asyncio
async def test_hub_session_handoff_ignores_jupyter_base_url_template(
    hub_session_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "BR_STUDIO_JUPYTER_BASE_URL_TEMPLATE",
        "https://hub.${PUBLIC_HOSTNAME}/user/{owner_user_id}",
    )

    runtime = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=hub_session_db_path,
    )

    session = await runtime.create_or_attach_session(
        "user_demo",
        CreateStudioSessionRequest(
            project_id="proj_ignore_jupyter_template",
            display_name="Hub Launch",
            runtime_kind=StudioRuntimeKind.MARIMO,
        ),
    )
    handoff = await runtime.build_hub_handoff(
        "user_demo",
        session.id,
        HubWorkspaceHandoffRequest(),
    )
    assert handoff.runtime_kind == StudioRuntimeKind.MARIMO
    assert handoff.hub_base_url == "https://workspace.example/hub"
    assert handoff.workspace_url.startswith("https://workspace.example/hub?")
    assert "hub.${PUBLIC_HOSTNAME}/user/" not in handoff.workspace_url


@pytest.mark.asyncio
async def test_attach_reuses_still_provisioning_marimo_runtime(
    hub_session_db_path: Path,
) -> None:
    # A runtime whose pod is still Pending stays in PROVISIONING; attaching again
    # for the same (owner, project, profile) must REUSE it, not mint a new pod.
    fake = _FakeProvisioner(ready=False)
    runtime = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=hub_session_db_path,
        marimo_runtime_provisioner=fake,
    )

    def _req() -> CreateStudioSessionRequest:
        return CreateStudioSessionRequest(
            project_id="proj_reuse_provisioning",
            display_name="Reuse Provisioning",
            runtime_kind=StudioRuntimeKind.MARIMO,
            attach_if_exists=True,
        )

    first = await runtime.create_or_attach_session("user_demo", _req())
    second = await runtime.create_or_attach_session("user_demo", _req())

    assert first.runtime_session_id is not None
    assert second.runtime_session_id == first.runtime_session_id


@pytest.mark.asyncio
async def test_get_marimo_runtime_target_refreshes_stale_readiness(
    hub_session_db_path: Path,
) -> None:
    # Pod starts Pending (ready=False); once it is Running, get_marimo_runtime_target
    # must re-reconcile and report ready instead of a stale not-ready target.
    fake = _FakeProvisioner(ready=False)
    runtime = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=hub_session_db_path,
        marimo_runtime_provisioner=fake,
    )
    session = await runtime.create_or_attach_session(
        "user_demo",
        CreateStudioSessionRequest(
            project_id="proj_readiness_refresh",
            display_name="Readiness Refresh",
            runtime_kind=StudioRuntimeKind.MARIMO,
        ),
    )

    _, target = await runtime.get_marimo_runtime_target(session.id)
    assert target.ready is False

    fake.ready = True
    _, refreshed = await runtime.get_marimo_runtime_target(session.id)
    assert refreshed.ready is True
