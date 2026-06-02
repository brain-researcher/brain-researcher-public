"""Track A P1: session-create load shedding.

Under a provisioning burst the create endpoint must shed with a fast, retryable
429 instead of hanging to the client's request timeout. A bounded asyncio
Semaphore (installed on app.state in lifespan) gates concurrent creates.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brain_researcher.services.orchestrator.endpoints import (
    hub_sessions as hub_sessions_module,
)
from brain_researcher.services.orchestrator.endpoints.hub_sessions import router
from brain_researcher.services.orchestrator.marimo_runtime_provisioner import (
    MarimoRuntimeTarget,
)
from brain_researcher.services.orchestrator.studio_session_runtime import (
    StudioSessionRuntime,
)


class _FakeProvisioner:
    ready = True

    def ensure_runtime_token(self, spec, target, *, existing_token=None):
        return existing_token or "tok"

    def ensure_target(self, spec) -> MarimoRuntimeTarget:
        name = f"br-marimo-{spec.runtime_session_id}"
        return MarimoRuntimeTarget(
            provisioner="fake",
            connection_mode="iframe",
            ready=True,
            public_url=f"https://workspace.example/hub/{name}",
            websocket_url=f"wss://workspace.example/hub/{name}",
            internal_url=f"http://{name}:2718",
            namespace="test",
            pod_name=f"{name}-pod",
            service_name=name,
            workspace_mount_path=spec.absolute_working_directory,
            workspace_volume_kind="persistentVolumeClaim",
            status_reason="ready",
        )

    def destroy_target(self, target) -> None:
        return None


_CREATE_BODY = {
    "project_id": "proj_shed",
    "display_name": "Shed Demo",
    "runtime_profile_id": "standard",
    "metadata": {"source": "hub"},
}


def _build_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
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
        db_path=tmp_path / "hub.sqlite",
        marimo_runtime_provisioner=_FakeProvisioner(),
    )
    return app


def test_create_sheds_with_429_and_retry_after_when_saturated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _build_app(tmp_path, monkeypatch)
    # Semaphore(0) is already fully saturated -> every acquire times out fast.
    app.state.hub_create_semaphore = asyncio.Semaphore(0)
    monkeypatch.setattr(hub_sessions_module, "_HUB_CREATE_ACQUIRE_TIMEOUT_S", 0.1)
    monkeypatch.setattr(hub_sessions_module, "_HUB_CREATE_RETRY_AFTER_S", 7)

    with TestClient(app) as client:
        resp = client.post(
            "/api/hub/sessions",
            json=_CREATE_BODY,
            headers={"Authorization": "Bearer test"},
        )

    assert resp.status_code == 429
    assert resp.headers.get("Retry-After") == "7"
    assert resp.json()["detail"]["reason"] == "session_create_capacity"


def test_create_releases_the_semaphore_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _build_app(tmp_path, monkeypatch)
    app.state.hub_create_semaphore = asyncio.Semaphore(2)

    with TestClient(app) as client:
        resp = client.post(
            "/api/hub/sessions",
            json=_CREATE_BODY,
            headers={"Authorization": "Bearer test"},
        )

    assert resp.status_code == 200
    # The acquire is released in a finally, so capacity returns to full.
    assert app.state.hub_create_semaphore._value == 2


def test_create_succeeds_when_no_semaphore_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Backward-compat: if lifespan didn't install a semaphore, creates still work
    # (the gate is skipped).
    app = _build_app(tmp_path, monkeypatch)
    assert getattr(app.state, "hub_create_semaphore", None) is None
    with TestClient(app) as client:
        resp = client.post(
            "/api/hub/sessions",
            json=_CREATE_BODY,
            headers={"Authorization": "Bearer test"},
        )
    assert resp.status_code == 200
