"""Utilities for patching the orchestrator JobStore in agent unit tests."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from brain_researcher.services.orchestrator.job_store import JobRecord
from brain_researcher.services.shared import job_store_registry


class StubJobStore:
    """Lightweight in-memory JobStore used by tests."""

    def __init__(self) -> None:
        self.enqueued_jobs: list[JobRecord] = []
        self.state_updates: list[tuple[str, Any, dict[str, Any]]] = []

    async def enqueue(self, job: JobRecord) -> str:
        self.enqueued_jobs.append(job)
        return job.job_id

    async def update_state(
        self, job_id: str, new_state: Any = None, **fields: Any
    ) -> bool:
        self.state_updates.append((job_id, new_state, fields))
        for record in self.enqueued_jobs:
            if record.job_id == job_id:
                if new_state is not None:
                    record.state = new_state
                for key, value in fields.items():
                    setattr(record, key, value)
                break
        return True

    async def cancel(self, job_id: str, reason: str | None = None) -> bool:
        self.state_updates.append((job_id, "cancelled", {"reason": reason}))
        return True


@contextmanager
def patched_job_store(monkeypatch):
    """Patch orchestrator.job_store with a StubJobStore for the duration of a test."""
    from brain_researcher.services.orchestrator import main_enhanced

    store = StubJobStore()
    previous_store = job_store_registry.peek_initialized_job_store()
    monkeypatch.setattr(main_enhanced, "job_store", store, raising=False)
    monkeypatch.setattr(job_store_registry, "_job_store_instance", store)

    try:
        yield store
    finally:
        job_store_registry._job_store_instance = previous_store
        # Clean up any SSE queues created for the stub jobs
        for job in list(store.enqueued_jobs):
            main_enhanced.job_updates.pop(job.job_id, None)
