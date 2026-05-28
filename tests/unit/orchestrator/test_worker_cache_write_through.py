"""Unit tests for worker cache write-through hooks."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
from brain_researcher.services.orchestrator.worker import JobWorker


class JobStoreStub:
    """Minimal JobStore stub that auto-creates async mocks for unknown attrs."""

    def __init__(self, job_record: JobRecord):
        self._job_record = job_record
        self._mocks: dict[str, AsyncMock] = {}

    async def get(self, job_id: str) -> JobRecord:  # pragma: no cover - trivial accessor
        return self._job_record

    def __getattr__(self, item: str):  # pragma: no cover - dynamic mocks
        if item.startswith("__"):
            raise AttributeError(item)
        if item not in self._mocks:
            self._mocks[item] = AsyncMock()
        return self._mocks[item]


def _make_job_record(job_id: str, metadata: dict[str, object]) -> JobRecord:
    payload = {"metadata": metadata}
    return JobRecord(
        job_id=job_id,
        kind="tool",
        payload_json=json.dumps(payload),
        state=JobState.RUNNING.value,
        priority=0,
    )


def _patch_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyMetrics:
        def record_job_final_state(self, *args, **kwargs):
            return None

        def record_job_duration(self, *args, **kwargs):
            return None

    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.worker.get_metrics_collector",
        lambda: DummyMetrics(),
        raising=False,
    )


def _disable_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    class _NoRetryDecision:
        should_retry = False
        reason = "disabled"
        max_attempts = 1
        delay_seconds = 0
        next_retry_at = None

    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.retry.should_retry",
        lambda *args, **kwargs: _NoRetryDecision(),
        raising=False,
    )
    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.retry.format_retry_summary",
        lambda decision: "",
        raising=False,
    )
    monkeypatch.setattr(
        "brain_researcher.config.retry_settings.get_retry_settings",
        lambda: {},
        raising=False,
    )


@pytest.mark.asyncio
async def test_finalize_job_marks_cache_on_success(monkeypatch, tmp_path):
    metadata = {"cache_key": "sha256:test_success"}
    job_record = _make_job_record("job_success", metadata)
    job_store = JobStoreStub(job_record)

    worker = JobWorker(job_store, worker_id="worker-cache-success", tool_executor=MagicMock())
    worker._annotate_cache_metadata = AsyncMock()
    worker._emit_cache_event = AsyncMock()

    _patch_metrics(monkeypatch)
    _disable_retries(monkeypatch)

    mock_cache = AsyncMock()
    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.main_enhanced.cache_store",
        mock_cache,
        raising=False,
    )

    run_dir = tmp_path / "job_success"
    run_dir.mkdir()
    artifact = run_dir / "result.txt"
    artifact.write_text("hello cache")

    await worker._finalize_job(
        job_id="job_success",
        exit_code=0,
        run_id="job_success",
        run_dir=str(run_dir),
    )

    mock_cache.mark_completed.assert_awaited_once()
    kwargs = mock_cache.mark_completed.await_args.kwargs
    assert kwargs["cache_key"] == "sha256:test_success"
    assert kwargs["run_id"] == "job_success"
    assert kwargs["run_dir"] == str(run_dir)
    assert kwargs["size_bytes"] > 0

    worker._annotate_cache_metadata.assert_awaited()
    worker._emit_cache_event.assert_awaited()


@pytest.mark.asyncio
async def test_finalize_job_marks_cache_on_failure(monkeypatch):
    metadata = {"cache_key": "sha256:test_failure"}
    job_record = _make_job_record("job_failure", metadata)
    job_store = JobStoreStub(job_record)

    worker = JobWorker(job_store, worker_id="worker-cache-failure", tool_executor=MagicMock())
    worker._annotate_cache_metadata = AsyncMock()
    worker._emit_cache_event = AsyncMock()

    _patch_metrics(monkeypatch)
    _disable_retries(monkeypatch)

    mock_cache = AsyncMock()
    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.main_enhanced.cache_store",
        mock_cache,
        raising=False,
    )

    await worker._finalize_job(
        job_id="job_failure",
        exit_code=1,
        error_message="boom",
        run_id="job_failure",
    )

    mock_cache.mark_failed.assert_awaited_once()
    kwargs = mock_cache.mark_failed.await_args.kwargs
    assert kwargs["cache_key"] == "sha256:test_failure"
    assert kwargs["run_id"] == "job_failure"
    assert kwargs["error"] == "boom"

    worker._annotate_cache_metadata.assert_awaited()
    worker._emit_cache_event.assert_awaited()
