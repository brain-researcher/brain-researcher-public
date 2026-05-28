import asyncio
from pathlib import Path

import pytest

from brain_researcher.config.run_artifacts import reset_recorder_config
from brain_researcher.services.orchestrator.job_store import JobRecord, LogChunk
from brain_researcher.services.orchestrator import job_management_endpoints as jme


def _make_job(**overrides) -> JobRecord:
    data = {
        'job_id': 'job-1',
        'kind': 'dag',
        'payload_json': '{}',
        'state': 'running',
        'run_dir': None,
        'provenance_path': None,
    }
    data.update(overrides)
    return JobRecord(**data)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _reset_run_artifact_config():
    reset_recorder_config()
    yield
    reset_recorder_config()


def test_normalize_streams_defaults():
    assert jme._normalize_streams(None) == ['stdout', 'stderr']


def test_normalize_streams_single():
    assert jme._normalize_streams('stdout') == ['stdout']


def test_normalize_streams_invalid():
    with pytest.raises(ValueError):
        jme._normalize_streams('logs')


def test_resolve_step_log_path_absolute(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BR_RUN_STORE_ROOT", str(tmp_path))
    run_dir = tmp_path / 'run'
    job = _make_job(run_dir=str(tmp_path))
    resolved = jme._resolve_step_log_path(job, str(run_dir))
    assert resolved == run_dir


def test_resolve_step_log_path_relative(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BR_RUN_STORE_ROOT", str(tmp_path))
    job = _make_job(run_dir=str(tmp_path))
    resolved = jme._resolve_step_log_path(job, 'step-1')
    assert resolved == tmp_path / 'step-1'


def test_resolve_step_log_path_with_legacy_run_root_alias(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    canonical_root = tmp_path / "shared" / "runs"
    legacy_root = tmp_path / "data" / "runs"
    job_root = canonical_root / "20260223" / "job-1"
    job = _make_job(run_dir=str(legacy_root / "20260223" / "job-1"))
    monkeypatch.setenv("BR_RUN_STORE_ROOT", str(canonical_root))
    monkeypatch.setenv("BR_RUN_STORE_ROOT_ALIASES", str(legacy_root))
    reset_recorder_config()
    resolved = jme._resolve_step_log_path(job, "step-1")
    assert resolved == job_root / "step-1"


def test_resolve_step_log_path_outside(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BR_RUN_STORE_ROOT", str(tmp_path))
    job = _make_job(run_dir=str(tmp_path))
    with pytest.raises(PermissionError):
        jme._resolve_step_log_path(job, '../etc')


def test_resolve_step_log_path_requires_run_dir(tmp_path):
    job = _make_job(run_dir=None)
    with pytest.raises(ValueError):
        jme._resolve_step_log_path(job, 'step-2')


def test_collect_file_chunks_reads_new_data(tmp_path):
    run_dir = tmp_path / 'step'
    run_dir.mkdir()
    stdout = run_dir / 'stdout.txt'
    stdout.write_text('hello')
    offsets = {'stdout': 0}
    chunks = jme._collect_file_chunks('job-1', run_dir, ['stdout'], offsets)
    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.stream == 'stdout'
    assert chunk.offset == 0
    assert chunk.data == b'hello'
    assert offsets['stdout'] == 5

    # No new data second time
    assert jme._collect_file_chunks('job-1', run_dir, ['stdout'], offsets) == []

    stdout.write_text('hello world')
    offsets['stdout'] = 5
    chunks = jme._collect_file_chunks('job-1', run_dir, ['stdout'], offsets)
    assert len(chunks) == 1
    assert chunks[0].offset == 5
    assert chunks[0].data == b' world'


def test_collect_store_chunks_filters_offsets():
    class DummyStore:
        async def iter_logs(self, job_id, start_offset=0, stream=None):
            return [
                LogChunk(job_id=job_id, stream='stdout', offset=0, data=b'hello', created_at=0),
                LogChunk(job_id=job_id, stream='stderr', offset=0, data=b'err', created_at=0),
            ]

    offsets = {'stdout': 2, 'stderr': 0}
    chunks = asyncio.run(jme._collect_store_chunks(DummyStore(), 'job-1', None, offsets))
    assert len(chunks) == 2
    stdout_chunk = next(c for c in chunks if c.stream == 'stdout')
    assert stdout_chunk.offset == 2
    assert stdout_chunk.data == b'llo'


def test_max_offset_aggregates():
    store_offsets = {'stdout': 10}
    file_offsets = {'stderr': 4}
    assert jme._max_offset(['stdout', 'stderr'], store_offsets, file_offsets) == 10


def test_job_is_terminal():
    assert jme._job_is_terminal('completed')
    assert not jme._job_is_terminal('running')
