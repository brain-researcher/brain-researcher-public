from __future__ import annotations

import builtins
from types import SimpleNamespace

import pytest

from brain_researcher.services.orchestrator.studio_session_runtime import (
    StudioRuntimeKind,
    StudioRuntimeProfile,
    StudioRuntimeSession,
    StudioSessionRuntime,
)


class _FakeApiException(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"status={status}")
        self.status = status


class _FakeCoreApi:
    def __init__(self, pod: object | None = None, exc: Exception | None = None) -> None:
        self._pod = pod
        self._exc = exc

    def read_namespaced_pod(self, *, name: str, namespace: str):
        if self._exc is not None:
            raise self._exc
        return self._pod


def _runtime() -> StudioRuntimeSession:
    return StudioRuntimeSession(
        id="rt_demo",
        project_id="proj_demo",
        owner_user_id="user_demo",
        runtime_profile_id=StudioRuntimeProfile.STANDARD,
        kind=StudioRuntimeKind.MARIMO,
        metadata={},
        marimo_base_url="https://workspace.example/hub",
        marimo_port=2718,
    )


def _pod(*, phase: str = "Running", ready: str = "True", deletion_timestamp=None):
    return SimpleNamespace(
        metadata=SimpleNamespace(deletion_timestamp=deletion_timestamp),
        status=SimpleNamespace(
            phase=phase,
            conditions=[SimpleNamespace(type="Ready", status=ready)],
        ),
    )


@pytest.fixture
def runtime_manager(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("BR_STUDIO_RUNTIME_LIVE_CHECK_ENABLED", "true")
    return StudioSessionRuntime(
        workspace_base_url="https://workspace.example",
        db_path=tmp_path / "studio_sessions.sqlite",
    )


def test_runtime_live_check_returns_none_when_core_api_unavailable(
    runtime_manager: StudioSessionRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime_manager, "_load_runtime_core_api", lambda: None)
    assert runtime_manager._runtime_backing_pod_is_live(_runtime()) is None


def test_runtime_live_check_returns_false_when_pod_is_missing(
    runtime_manager: StudioSessionRuntime,
) -> None:
    runtime_manager._runtime_core_api = _FakeCoreApi(exc=_FakeApiException(status=404))
    runtime_manager._runtime_api_exception_type = _FakeApiException
    runtime_manager._runtime_client_ready = True

    assert runtime_manager._runtime_backing_pod_is_live(_runtime()) is False


@pytest.mark.parametrize("status", [401, 403])
def test_runtime_live_check_disables_client_on_auth_error(
    runtime_manager: StudioSessionRuntime,
    status: int,
) -> None:
    runtime_manager._runtime_core_api = _FakeCoreApi(exc=_FakeApiException(status=status))
    runtime_manager._runtime_api_exception_type = _FakeApiException
    runtime_manager._runtime_client_ready = True

    assert runtime_manager._runtime_backing_pod_is_live(_runtime()) is None
    assert runtime_manager._runtime_client_ready is False
    assert runtime_manager._runtime_core_api is None


def test_runtime_live_check_returns_false_for_terminating_or_unready_pod(
    runtime_manager: StudioSessionRuntime,
) -> None:
    runtime_manager._runtime_api_exception_type = _FakeApiException
    runtime_manager._runtime_client_ready = True

    runtime_manager._runtime_core_api = _FakeCoreApi(
        pod=_pod(deletion_timestamp="2026-04-22T00:00:00Z")
    )
    assert runtime_manager._runtime_backing_pod_is_live(_runtime()) is False

    runtime_manager._runtime_core_api = _FakeCoreApi(pod=_pod(ready="False"))
    assert runtime_manager._runtime_backing_pod_is_live(_runtime()) is False


def test_runtime_live_check_returns_true_for_running_ready_pod(
    runtime_manager: StudioSessionRuntime,
) -> None:
    runtime_manager._runtime_core_api = _FakeCoreApi(pod=_pod())
    runtime_manager._runtime_api_exception_type = _FakeApiException
    runtime_manager._runtime_client_ready = True

    assert runtime_manager._runtime_backing_pod_is_live(_runtime()) is True


def test_load_runtime_core_api_disables_future_checks_when_kubernetes_client_missing(
    runtime_manager: StudioSessionRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "kubernetes" or name.startswith("kubernetes."):
            raise ImportError("missing kubernetes")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    assert runtime_manager._load_runtime_core_api() is None
    assert runtime_manager._runtime_client_ready is False
    assert runtime_manager._load_runtime_core_api() is None
