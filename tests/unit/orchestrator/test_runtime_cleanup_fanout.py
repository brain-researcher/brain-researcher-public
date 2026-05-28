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
        return None


@pytest.fixture
def studio_runtime(tmp_path: Path) -> StudioSessionRuntime:
    return StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=tmp_path / "studio_sessions.sqlite",
        marimo_runtime_provisioner=_FakeProvisioner(),
    )


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
async def test_runtime_record_missing_marks_bound_sessions_stopped(
    studio_runtime: StudioSessionRuntime,
) -> None:
    created = await studio_runtime.create_or_attach_session(
        "user_demo",
        CreateStudioSessionRequest(
            project_id="proj_runtime_missing",
            display_name="Primary",
            runtime_profile_id="standard",
            runtime_kind=StudioRuntimeKind.MARIMO,
        ),
    )
    duplicate = await _seed_second_bound_session(studio_runtime, created.id)

    with studio_runtime._lock:
        with studio_runtime._connect() as conn:
            conn.execute(
                "DELETE FROM studio_runtime_sessions WHERE id = ?",
                (created.runtime_session_id,),
            )
            conn.commit()
            first = studio_runtime._get_session_locked(conn, created.id)
            second = studio_runtime._get_session_locked(conn, duplicate.id)
            assert first is not None
            assert second is not None
            assert studio_runtime._resolve_session_runtime_locked(conn, first) is None
            assert studio_runtime._resolve_session_runtime_locked(conn, second) is None

    first_stopped = await studio_runtime.get_session(created.id)
    second_stopped = await studio_runtime.get_session(duplicate.id)
    assert first_stopped is not None
    assert second_stopped is not None
    assert first_stopped.status.value == "stopped"
    assert second_stopped.status.value == "stopped"
    assert first_stopped.metadata["cleanup_reason"] == "runtime_record_missing"
    assert second_stopped.metadata["cleanup_reason"] == "runtime_record_missing"


@pytest.mark.asyncio
async def test_mark_runtime_and_bound_sessions_stopped_fans_out_cleanup_reason(
    studio_runtime: StudioSessionRuntime,
) -> None:
    created = await studio_runtime.create_or_attach_session(
        "user_demo",
        CreateStudioSessionRequest(
            project_id="proj_cleanup_fanout",
            display_name="Primary",
            runtime_profile_id="standard",
            runtime_kind=StudioRuntimeKind.MARIMO,
        ),
    )
    duplicate = await _seed_second_bound_session(studio_runtime, created.id)

    with studio_runtime._lock:
        with studio_runtime._connect() as conn:
            runtime = studio_runtime._get_runtime_session_locked(conn, created.runtime_session_id)
            assert runtime is not None
            studio_runtime._mark_runtime_and_bound_sessions_stopped_locked(
                conn,
                runtime,
                reason="runtime_backing_pod_missing",
            )

    stopped_runtime = await studio_runtime.get_runtime_session(created.runtime_session_id)
    first_stopped = await studio_runtime.get_session(created.id)
    second_stopped = await studio_runtime.get_session(duplicate.id)
    assert stopped_runtime is not None
    assert first_stopped is not None
    assert second_stopped is not None
    assert stopped_runtime.status.value == "stopped"
    assert first_stopped.status.value == "stopped"
    assert second_stopped.status.value == "stopped"
    assert stopped_runtime.metadata["cleanup_reason"] == "runtime_backing_pod_missing"
    assert first_stopped.metadata["cleanup_reason"] == "runtime_backing_pod_missing"
    assert second_stopped.metadata["cleanup_reason"] == "runtime_backing_pod_missing"
    assert first_stopped.metadata["runtime_binding"]["status"] == "stopped"
    assert second_stopped.metadata["runtime_binding"]["status"] == "stopped"
