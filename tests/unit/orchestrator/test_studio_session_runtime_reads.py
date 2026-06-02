"""Track A P0c (safe subset): pure-read methods are lock-free.

The 5 read-only StudioSessionRuntime methods (get_session, list_sessions,
get_runtime_session, get_runtime_token, get_runtime_skew_token) no longer take
the process-wide write lock. SQLite WAL gives readers a consistent snapshot even
while a writer holds the lock, so read traffic (e.g. the UI polling a session's
readiness) stays responsive during a provisioning burst instead of queuing
behind writes.
"""

from __future__ import annotations

import asyncio
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


class _FakeProvisioner:
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


async def test_reads_do_not_block_on_the_runtime_write_lock(tmp_path: Path) -> None:
    runtime = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=tmp_path / "reads.sqlite",
        marimo_runtime_provisioner=_FakeProvisioner(),
    )
    session = await runtime.create_or_attach_session(
        "user_demo",
        CreateStudioSessionRequest(
            project_id="proj_reads",
            display_name="Reads Demo",
            runtime_kind=StudioRuntimeKind.MARIMO,
            attach_if_exists=False,
            metadata={},
        ),
    )

    # Simulate a long-running writer holding the process-wide lock.
    lock_held = threading.Event()
    release = threading.Event()

    def holder():
        with runtime._lock:
            lock_held.set()
            release.wait(timeout=5)

    t = threading.Thread(target=holder)
    t.start()
    try:
        assert lock_held.wait(timeout=2), "writer never acquired the lock"
        # While the write lock is held, a read must still complete promptly.
        # If get_session still took self._lock it would block until release and
        # this wait_for would time out.
        got = await asyncio.wait_for(runtime.get_session(session.id), timeout=2.0)
        assert got is not None and got.id == session.id
        # The token read path (two SELECTs) is also lock-free.
        tok = await asyncio.wait_for(runtime.get_runtime_token(session.id), timeout=2.0)
        assert tok == "tok"
    finally:
        release.set()
        t.join()
