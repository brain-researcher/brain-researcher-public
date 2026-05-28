from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from brain_researcher.services.orchestrator import state_store as state_store_module
from brain_researcher.services.orchestrator.job_state import (
    jobs_db,
    messages_db,
    threads_db,
)
from brain_researcher.services.orchestrator.models import Message, Thread
from brain_researcher.services.orchestrator.monitor_runtime import (
    MonitorRuntime,
    MonitorStatus,
)
from brain_researcher.services.orchestrator.session_runtime import (
    CreateSessionRequest,
    SessionActionRequest,
    SessionKind,
    SessionRuntime,
)


@pytest.fixture
def isolated_state_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BR_STATE_STORE_ENABLED", "true")
    monkeypatch.setenv("BR_STATE_DB", str(tmp_path / "state.sqlite"))
    state_store_module._STATE_STORE = None
    jobs_db.clear()
    messages_db.clear()
    threads_db.clear()
    yield
    state_store_module._STATE_STORE = None
    jobs_db.clear()
    messages_db.clear()
    threads_db.clear()


@pytest.mark.asyncio
async def test_mcp_run_session_supports_status_logs_and_cancel(
    isolated_state_store,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from brain_researcher.services.mcp import server as mcp_server

    run_dir = tmp_path / "runs" / "run_demo"
    logs_dir = run_dir / "logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "stdout.log").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    run_state = {"status": "running", "step_status": "running"}

    def _run_get(run_id: str) -> dict[str, object]:
        assert run_id == "run_demo"
        return {
            "ok": True,
            "run": {
                "run_id": run_id,
                "status": run_state["status"],
                "steps": [
                    {"step_id": "prepare", "title": "Prepare inputs", "status": "succeeded"},
                    {"step_id": "fit", "title": "Fit model", "status": run_state["step_status"]},
                ],
            },
            "run_dir": str(run_dir),
        }

    def _run_metrics(run_id: str) -> dict[str, object]:
        assert run_id == "run_demo"
        return {"ok": True, "metrics": {"totals": {"steps": 2, "succeeded": 1}}}

    def _run_cancel(run_id: str, reason: str | None = None) -> dict[str, object]:
        assert run_id == "run_demo"
        run_state["status"] = "cancelled"
        run_state["step_status"] = "cancelled"
        return {"ok": True, "run_id": run_id, "status": "cancelled", "reason": reason}

    monkeypatch.setattr(mcp_server, "run_get", _run_get)
    monkeypatch.setattr(mcp_server, "run_metrics", _run_metrics)
    monkeypatch.setattr(mcp_server, "run_cancel", _run_cancel)

    runtime = SessionRuntime(None, MonitorRuntime())
    session = await runtime.create_session(
        "user_demo",
        CreateSessionRequest(
            kind=SessionKind.MCP_RUN,
            session_ref="run_demo",
            display_name="Demo MCP Run",
        ),
    )

    assert session.status == MonitorStatus.RUNNING
    assert session.summary == "Fit model"

    logs = await runtime.perform_action(
        session.id,
        "logs",
        SessionActionRequest(tail=2),
    )
    assert logs["logs"]["stdout"] == "beta\ngamma"

    cancelled = await runtime.perform_action(
        session.id,
        "cancel",
        SessionActionRequest(reason="phone"),
    )
    assert cancelled["session"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_coding_session_wraps_thread_linked_br_job(
    isolated_state_store,
    tmp_path: Path,
) -> None:
    thread_id = "thread_code123"
    threads_db[thread_id] = Thread(
        thread_id=thread_id,
        title="Code Thread",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        context={},
        metadata={"owner_user_id": "user_demo"},
        scenario_id=None,
    )
    messages_db[thread_id] = [
        Message(
            id="msg_code123",
            thread_id=thread_id,
            role="assistant",
            content="Updated the parser and reran the focused tests.",
            timestamp=datetime.utcnow(),
            metadata={"job_id": "job_code123"},
        )
    ]

    run_dir = tmp_path / "job_code123"
    run_dir.mkdir()
    (run_dir / "stdout.txt").write_text("plan\npatch\ntest\n", encoding="utf-8")
    jobs_db["job_code123"] = SimpleNamespace(
        status="running",
        progress={"percentage": 60},
        run_dir=str(run_dir),
        error=None,
        cancellation_reason=None,
        status_message="Applying patch",
        metadata={"pipeline": "code_agent"},
    )

    runtime = SessionRuntime(None, MonitorRuntime())
    session = await runtime.create_session(
        "user_demo",
        CreateSessionRequest(
            kind=SessionKind.CODING_SESSION,
            session_ref=thread_id,
            thread_id=thread_id,
            display_name="Repo Fix Session",
        ),
    )

    assert session.status == MonitorStatus.RUNNING
    assert session.metadata["job_id"] == "job_code123"
    assert session.summary == "Applying patch"

    logs = await runtime.perform_action(
        session.id,
        "logs",
        SessionActionRequest(tail=2),
    )
    assert logs["logs"]["stdout"] == "patch\ntest"
