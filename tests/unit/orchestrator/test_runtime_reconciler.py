from __future__ import annotations

import secrets
from pathlib import Path

import pytest

from brain_researcher.services.orchestrator.marimo_runtime_provisioner import (
    MarimoRuntimeTarget,
)
from brain_researcher.services.orchestrator.studio_session_runtime import (
    CreateStudioSessionRequest,
    StudioRuntimeKind,
    StudioSessionRuntime,
)


class _FakeProvisioner:
    def __init__(self, *, ready: bool) -> None:
        self.ready = ready
        self.destroy_calls: list[str] = []

    def ensure_target(self, spec) -> MarimoRuntimeTarget:
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


async def _seed_second_bound_session(runtime: StudioSessionRuntime, session_id: str):
    with runtime._lock:
        with runtime._connect() as conn:
            original = runtime._get_session_locked(conn, session_id)
            assert original is not None
            duplicate = original.model_copy(
                update={
                    "id": f"studio_{secrets.token_urlsafe(9).replace('-', '').replace('_', '')}",
                    "assistant_session_id": (
                        f"ast_{secrets.token_urlsafe(9).replace('-', '').replace('_', '')}"
                    ),
                }
            )
            runtime._upsert_session_locked(conn, duplicate)
            return duplicate


@pytest.mark.asyncio
async def test_reconcile_runtime_sessions_once_stops_stale_runtime_and_bound_sessions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake = _FakeProvisioner(ready=True)
    runtime = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=tmp_path / "studio_sessions.sqlite",
        marimo_runtime_provisioner=fake,
    )
    created = await runtime.create_or_attach_session(
        "user_demo",
        CreateStudioSessionRequest(
            project_id="proj_reconcile_stale",
            display_name="Primary",
            runtime_profile_id="standard",
            runtime_kind=StudioRuntimeKind.MARIMO,
        ),
    )
    duplicate = await _seed_second_bound_session(runtime, created.id)

    monkeypatch.setattr(
        runtime,
        "_runtime_backing_pod_is_live",
        lambda candidate: False if candidate.id == created.runtime_session_id else None,
    )

    summary = await runtime.reconcile_runtime_sessions_once()

    stopped_runtime = await runtime.get_runtime_session(created.runtime_session_id)
    first_stopped = await runtime.get_session(created.id)
    second_stopped = await runtime.get_session(duplicate.id)

    assert summary == {
        "scanned": 1,
        "refreshed": 0,
        "stopped": 1,
        "still_provisioning": 0,
    }
    assert stopped_runtime is not None
    assert first_stopped is not None
    assert second_stopped is not None
    assert stopped_runtime.status.value == "stopped"
    assert first_stopped.status.value == "stopped"
    assert second_stopped.status.value == "stopped"
    assert stopped_runtime.metadata["cleanup_reason"] == "runtime_backing_pod_missing"
    assert first_stopped.metadata["cleanup_reason"] == "runtime_backing_pod_missing"
    assert second_stopped.metadata["cleanup_reason"] == "runtime_backing_pod_missing"
    assert fake.destroy_calls == [f"br-marimo-{created.runtime_session_id}"]


@pytest.mark.asyncio
async def test_reconcile_runtime_sessions_once_keeps_provisioning_runtime_alive(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake = _FakeProvisioner(ready=False)
    runtime = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=tmp_path / "studio_sessions.sqlite",
        marimo_runtime_provisioner=fake,
    )
    created = await runtime.create_or_attach_session(
        "user_demo",
        CreateStudioSessionRequest(
            project_id="proj_reconcile_pending",
            display_name="Pending",
            runtime_profile_id="standard",
            runtime_kind=StudioRuntimeKind.MARIMO,
        ),
    )

    monkeypatch.setattr(
        runtime,
        "_runtime_backing_pod_is_live",
        lambda candidate: (_ for _ in ()).throw(
            AssertionError("provisioning runtimes should not go through live-check stop logic")
        ),
    )

    summary = await runtime.reconcile_runtime_sessions_once()

    refreshed_runtime = await runtime.get_runtime_session(created.runtime_session_id)
    refreshed_session = await runtime.get_session(created.id)

    assert summary == {
        "scanned": 1,
        "refreshed": 0,
        "stopped": 0,
        "still_provisioning": 1,
    }
    assert refreshed_runtime is not None
    assert refreshed_session is not None
    assert refreshed_runtime.status.value == "provisioning"
    assert refreshed_session.status.value == "provisioning"
    assert fake.destroy_calls == []
