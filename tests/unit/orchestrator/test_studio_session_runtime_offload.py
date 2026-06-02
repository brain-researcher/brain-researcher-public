"""Track A P0b: blocking provisioning runs off the event loop.

StudioSessionRuntime's public methods hold a process-wide threading.Lock and do
blocking SQLite + kubernetes-client I/O. They are wrapped in asyncio.to_thread so
the asyncio event loop stays free (otherwise a provisioning burst stalls the
liveness/readiness probes and every other request). This proves the heavy k8s
call runs on a worker thread, not the loop thread.
"""

from __future__ import annotations

import threading
from pathlib import Path

from brain_researcher.services.orchestrator.marimo_runtime_provisioner import (
    MarimoRuntimeTarget,
)
from brain_researcher.services.orchestrator.studio_session_runtime import (
    CreateStudioSessionRequest,
    StudioRuntimeKind,
    StudioSessionRuntime,
)


class _ThreadRecordingProvisioner:
    def __init__(self) -> None:
        self.ensure_thread_ident: int | None = None

    def ensure_runtime_token(self, spec, target, *, existing_token=None):
        return existing_token or "tok"

    def ensure_target(self, spec) -> MarimoRuntimeTarget:
        self.ensure_thread_ident = threading.get_ident()
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


async def test_create_or_attach_runs_provisioning_off_the_event_loop(
    tmp_path: Path,
) -> None:
    fake = _ThreadRecordingProvisioner()
    runtime = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=tmp_path / "offload.sqlite",
        marimo_runtime_provisioner=fake,
    )
    loop_thread_ident = threading.get_ident()

    session = await runtime.create_or_attach_session(
        "user_demo",
        CreateStudioSessionRequest(
            project_id="proj_offload",
            display_name="Offload Demo",
            runtime_kind=StudioRuntimeKind.MARIMO,
            attach_if_exists=False,
            metadata={},
        ),
    )

    assert session is not None
    # The blocking k8s provisioning executed on a worker thread (to_thread), not
    # the event-loop thread -> the loop stays free for probes and other requests.
    assert fake.ensure_thread_ident is not None
    assert fake.ensure_thread_ident != loop_thread_ident


async def test_offloaded_methods_remain_coroutine_functions() -> None:
    import asyncio

    # The decorator must keep these awaitable (callers use `await`).
    assert asyncio.iscoroutinefunction(StudioSessionRuntime.create_or_attach_session)
    assert asyncio.iscoroutinefunction(StudioSessionRuntime.get_session)
    assert asyncio.iscoroutinefunction(StudioSessionRuntime.build_hub_handoff)
