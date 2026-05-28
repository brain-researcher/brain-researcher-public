"""Contract tests for Studio runtime credentials + cleanup-reason values."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brain_researcher.services.orchestrator.cleanup_reasons import CleanupReason
from brain_researcher.services.orchestrator.endpoints.studio_sessions import (
    router as sessions_router,
)
from brain_researcher.services.orchestrator.studio_session_runtime import (
    CreateStudioSessionRequest,
    StudioSessionRuntime,
)


EXPECTED_CLEANUP_REASON_VALUES = {
    "POD_GONE": "runtime_backing_pod_missing",
    "POD_TERMINATING": "pod_terminating",
    "POD_UNREADY": "pod_unready",
    "KUBERNETES_UNAVAILABLE": "kubernetes_unavailable",
    "RUNTIME_RECORD_MISSING": "runtime_record_missing",
    "USER_CLOSE": "user_close",
    "IDLE_CULL": "idle_cull",
}


def test_cleanup_reason_members_match_contract() -> None:
    actual = {member.name: member.value for member in CleanupReason}
    assert actual == EXPECTED_CLEANUP_REASON_VALUES


def test_cleanup_reason_is_str_compatible() -> None:
    assert CleanupReason.POD_GONE == "runtime_backing_pod_missing"
    assert str(CleanupReason.POD_GONE) == "runtime_backing_pod_missing"


@pytest.fixture
def studio_session_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> StudioSessionRuntime:
    monkeypatch.setenv("BR_STUDIO_JUPYTER_TOKEN", "tok_SECRET_long_lived_value")
    return StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=tmp_path / "studio_sessions.sqlite",
    )


@pytest.mark.asyncio
async def test_runtime_token_is_shared_across_reattached_sessions(
    studio_session_runtime: StudioSessionRuntime,
) -> None:
    first = await studio_session_runtime.create_or_attach_session(
        "user_alpha",
        CreateStudioSessionRequest(
            project_id="proj_creds",
            display_name="Creds 1",
            runtime_profile_id="standard",
        ),
    )
    second = await studio_session_runtime.create_or_attach_session(
        "user_alpha",
        CreateStudioSessionRequest(
            project_id="proj_creds",
            display_name="Creds 2",
            runtime_profile_id="standard",
            attach_if_exists=True,
        ),
    )

    assert second.runtime_session_id == first.runtime_session_id
    rt = await studio_session_runtime.get_runtime_session(first.runtime_session_id)
    assert rt is not None
    assert rt.jupyter_token == "tok_SECRET_long_lived_value"


@pytest.mark.asyncio
async def test_close_does_not_invalidate_runtime_token(
    studio_session_runtime: StudioSessionRuntime,
) -> None:
    created = await studio_session_runtime.create_or_attach_session(
        "user_alpha",
        CreateStudioSessionRequest(
            project_id="proj_close_creds",
            display_name="Close Creds",
            runtime_profile_id="standard",
        ),
    )
    await studio_session_runtime.perform_action(
        "user_alpha", created.id, "close", None
    )
    rt = await studio_session_runtime.get_runtime_session(created.runtime_session_id)
    assert rt is not None
    assert rt.jupyter_token == "tok_SECRET_long_lived_value"


@pytest.fixture
def studio_session_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> TestClient:
    monkeypatch.setenv("BR_STUDIO_JUPYTER_TOKEN", "tok_SECRET_long_lived_value")
    monkeypatch.setenv("BR_MCP_TOKEN", "mcp_SECRET_must_not_leak")

    async def _fake_user(_request):
        return SimpleNamespace(id="user_alpha"), {}

    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.endpoints.studio_sessions._resolve_request_user",
        _fake_user,
    )

    app = FastAPI()
    app.include_router(sessions_router)
    app.state.studio_session_runtime = StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=tmp_path / "studio_sessions.sqlite",
    )
    with TestClient(app) as client:
        yield client


def _assert_no_secret_leak(payload_text: str) -> None:
    assert "tok_SECRET_long_lived_value" not in payload_text
    assert "mcp_SECRET_must_not_leak" not in payload_text


def test_session_api_responses_do_not_leak_credentials(
    studio_session_client: TestClient,
) -> None:
    create_resp = studio_session_client.post(
        "/api/studio/sessions",
        json={
            "project_id": "proj_leak_probe",
            "display_name": "Leak Probe",
            "runtime_profile_id": "standard",
        },
    )
    assert create_resp.status_code == 200
    _assert_no_secret_leak(create_resp.text)

    session_id = create_resp.json()["session"]["id"]

    get_resp = studio_session_client.get(f"/api/studio/sessions/{session_id}")
    assert get_resp.status_code == 200
    _assert_no_secret_leak(get_resp.text)

    list_resp = studio_session_client.get("/api/studio/sessions")
    assert list_resp.status_code == 200
    _assert_no_secret_leak(list_resp.text)

    handoff_resp = studio_session_client.post(
        f"/api/studio/sessions/{session_id}/workspace-handoff",
        json={"target_path": "scripts/x.py"},
    )
    assert handoff_resp.status_code == 200
    _assert_no_secret_leak(handoff_resp.text)

    close_resp = studio_session_client.post(
        f"/api/studio/sessions/{session_id}/actions/close",
        json={"reason": "user_closed_panel"},
    )
    assert close_resp.status_code == 200
    _assert_no_secret_leak(close_resp.text)
