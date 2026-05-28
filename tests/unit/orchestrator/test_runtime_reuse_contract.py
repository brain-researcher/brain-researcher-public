from __future__ import annotations

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
    def __init__(self) -> None:
        self.destroy_calls: list[str] = []

    def ensure_target(self, spec) -> MarimoRuntimeTarget:
        service_name = f"br-marimo-{spec.runtime_session_id}"
        return MarimoRuntimeTarget(
            provisioner="fake",
            connection_mode="iframe",
            ready=True,
            public_url=f"https://workspace.example/hub/{service_name}",
            websocket_url=f"wss://workspace.example/hub/{service_name}",
            internal_url=f"http://{service_name}:2718",
            namespace="test",
            pod_name=f"{service_name}-pod",
            service_name=service_name,
            workspace_mount_path=spec.absolute_working_directory,
            workspace_volume_kind="persistentVolumeClaim",
            status_reason="ready",
        )

    def destroy_target(self, target: MarimoRuntimeTarget) -> None:
        if target.service_name:
            self.destroy_calls.append(target.service_name)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "studio_sessions.sqlite"


@pytest.mark.asyncio
async def test_closed_jupyter_session_keeps_runtime_row_but_does_not_orphan_reuse(
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    monkeypatch.setenv("BR_STUDIO_JUPYTER_TOKEN", "tok_test")
    runtime = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=db_path,
    )

    first = await runtime.create_or_attach_session(
        "user_demo",
        CreateStudioSessionRequest(
            project_id="proj_contract_jupyter",
            display_name="First",
            runtime_profile_id="standard",
            runtime_kind=StudioRuntimeKind.JUPYTER,
        ),
    )
    await runtime.perform_action(
        "user_demo",
        first.id,
        "close",
        None,
    )
    stopped_session = await runtime.get_session(first.id)
    preserved_runtime = await runtime.get_runtime_session(first.runtime_session_id)
    assert stopped_session is not None
    assert stopped_session.status.value == "stopped"
    assert preserved_runtime is not None
    assert preserved_runtime.kind == StudioRuntimeKind.JUPYTER
    assert preserved_runtime.status.value == "ready"

    second = await runtime.create_or_attach_session(
        "user_demo",
        CreateStudioSessionRequest(
            project_id="proj_contract_jupyter",
            display_name="Second",
            runtime_profile_id="standard",
            runtime_kind=StudioRuntimeKind.JUPYTER,
            attach_if_exists=True,
        ),
    )

    assert second.id != first.id
    assert second.runtime_session_id != first.runtime_session_id


@pytest.mark.asyncio
async def test_closing_marimo_session_tears_down_runtime_and_forces_fresh_runtime(
    db_path: Path,
) -> None:
    fake = _FakeProvisioner()
    runtime = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=db_path,
        marimo_runtime_provisioner=fake,
    )

    first = await runtime.create_or_attach_session(
        "user_demo",
        CreateStudioSessionRequest(
            project_id="proj_contract_marimo",
            display_name="First",
            runtime_profile_id="standard",
            runtime_kind=StudioRuntimeKind.MARIMO,
        ),
    )
    await runtime.perform_action(
        "user_demo",
        first.id,
        "close",
        None,
    )

    stopped_runtime = await runtime.get_runtime_session(first.runtime_session_id)
    assert stopped_runtime is not None
    assert stopped_runtime.kind == StudioRuntimeKind.MARIMO
    assert stopped_runtime.status.value == "stopped"
    assert fake.destroy_calls == [f"br-marimo-{first.runtime_session_id}"]

    second = await runtime.create_or_attach_session(
        "user_demo",
        CreateStudioSessionRequest(
            project_id="proj_contract_marimo",
            display_name="Second",
            runtime_profile_id="standard",
            runtime_kind=StudioRuntimeKind.MARIMO,
            attach_if_exists=True,
        ),
    )

    assert second.id != first.id
    assert second.runtime_session_id != first.runtime_session_id
