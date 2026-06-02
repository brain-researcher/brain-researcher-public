from unittest.mock import patch

import pytest

from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore


def test_agent_job_service_rejects_memory_store_when_sqlite_required(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("BR_QUEUE_BACKEND", "sqlite")
    monkeypatch.setenv("BR_STRICT_SQLITE_BACKEND", "1")

    from brain_researcher.services.agent.job_service import AgentJobService

    with patch(
        "brain_researcher.services.shared.job_store_registry.get_initialized_job_store",
        return_value=MemoryJobStore(),
    ):
        with pytest.raises(RuntimeError, match="MemoryJobStore"):
            AgentJobService()


def test_agent_job_service_raises_when_initialize_fails_in_strict_sqlite_mode(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("BR_QUEUE_BACKEND", "sqlite")
    monkeypatch.setenv("BR_STRICT_SQLITE_BACKEND", "1")

    class DummyStore:
        async def initialize(self):
            raise RuntimeError("init failed")

    from brain_researcher.services.agent.job_service import AgentJobService

    with patch(
        "brain_researcher.services.shared.job_store_registry.get_initialized_job_store",
        return_value=DummyStore(),
    ):
        with pytest.raises(RuntimeError, match="JobStore.initialize failed"):
            AgentJobService()


def test_agent_job_service_startup_helper_skips_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("BR_AGENT_EAGER_JOB_SERVICE_INIT", raising=False)

    from brain_researcher.services.agent import job_service as job_service_module

    with patch.object(job_service_module, "get_job_service") as get_job_service:
        assert job_service_module.maybe_initialize_job_service_for_startup() is False
        get_job_service.assert_not_called()


def test_agent_job_service_startup_helper_eager_inits_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("BR_AGENT_EAGER_JOB_SERVICE_INIT", "1")

    from brain_researcher.services.agent import job_service as job_service_module

    class DummyService:
        def __init__(self):
            self._store = MemoryJobStore()

    with patch.object(
        job_service_module,
        "get_job_service",
        return_value=DummyService(),
    ) as get_job_service:
        assert job_service_module.maybe_initialize_job_service_for_startup() is True
        get_job_service.assert_called_once()


def test_agent_job_service_registers_shared_job_store_autoinit(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("BR_QUEUE_BACKEND", "memory")
    monkeypatch.delenv("BR_STRICT_SQLITE_BACKEND", raising=False)

    from brain_researcher.services.shared import job_store_registry

    monkeypatch.setattr(job_store_registry, "_job_store_instance", None)
    monkeypatch.setattr(job_store_registry, "_autoinit", None)

    from brain_researcher.services.agent.job_service import AgentJobService

    service = AgentJobService()

    assert type(service._store).__name__ == "MemoryJobStore"
