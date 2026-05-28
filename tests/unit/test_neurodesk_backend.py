"""Unit tests for NeurodeskBackend (local mode, mocked subprocess)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from brain_researcher.services.agent.backends.base_backend import (
    JobSpecification,
    JobState,
    JobStatus,
    ResourceRequirements,
)
from brain_researcher.services.agent.backends.neurodesk_backend import NeurodeskBackend
from brain_researcher.services.agent.backends.slurm_helpers import (
    parse_sacct_output,
    parse_squeue_output,
)


# ---------------------------------------------------------------------------
# slurm_helpers pure-function tests
# ---------------------------------------------------------------------------

class TestParseSqueueOutput:
    def test_running_job(self):
        stdout = "12345,RUNNING,2026-01-01T10:00:00,5:00\n"
        state, started_at = parse_squeue_output("12345", stdout)
        assert state == JobState.RUNNING
        assert started_at is not None
        assert started_at.hour == 10

    def test_pending_job(self):
        state, _ = parse_squeue_output("12345", "12345,PENDING,,\n")
        assert state == JobState.PENDING

    def test_completing_job(self):
        state, _ = parse_squeue_output("12345", "12345,COMPLETING,,\n")
        assert state == JobState.RUNNING

    def test_failed_job(self):
        state, _ = parse_squeue_output("12345", "12345,FAILED,,\n")
        assert state == JobState.FAILED

    def test_cancelled_job(self):
        state, _ = parse_squeue_output("12345", "12345,CANCELLED,,\n")
        assert state == JobState.FAILED

    def test_not_found(self):
        state, started_at = parse_squeue_output("12345", "")
        assert state is None
        assert started_at is None

    def test_wrong_job_id(self):
        state, _ = parse_squeue_output("99999", "12345,RUNNING,2026-01-01T10:00:00,5:00\n")
        assert state is None


class TestParseSacctOutput:
    def test_completed(self):
        stdout = "12345|COMPLETED|2026-01-01T10:00:00|2026-01-01T11:00:00|0:0\n"
        state, started, completed, exit_code = parse_sacct_output("12345", stdout)
        assert state == JobState.COMPLETED
        assert exit_code == 0
        assert started is not None
        assert completed is not None

    def test_failed(self):
        stdout = "12345|FAILED|2026-01-01T10:00:00|2026-01-01T10:05:00|1:0\n"
        state, _, _, exit_code = parse_sacct_output("12345", stdout)
        assert state == JobState.FAILED
        assert exit_code == 1

    def test_not_found(self):
        state, _, _, _ = parse_sacct_output("12345", "")
        assert state is None

    def test_timeout_state(self):
        stdout = "12345|TIMEOUT|2026-01-01T10:00:00|2026-01-01T12:00:00|0:0\n"
        state, _, _, _ = parse_sacct_output("12345", stdout)
        assert state == JobState.FAILED


# ---------------------------------------------------------------------------
# NeurodeskBackend local mode
# ---------------------------------------------------------------------------

@pytest.fixture()
def backend(tmp_path):
    return NeurodeskBackend("neurodesk_test", {"mode": "local", "run_dir": str(tmp_path)})


def _make_spec(tmp_path: Path) -> JobSpecification:
    script = tmp_path / "analysis_01_fsl_bet.sh"
    script.write_text("#!/bin/bash\necho hello\n")
    spec = JobSpecification(
        name="br-01-fsl-bet",
        command=f"bash {script}",
        image="",
        environment={},
        resources=ResourceRequirements(cpu=4, memory_gb=16, walltime_minutes=60),
    )
    return spec


class TestNeurodeskBackendLocal:
    @pytest.mark.asyncio
    async def test_submit_job_returns_nd_prefix(self, backend, tmp_path):
        spec = _make_spec(tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="12345\n", stderr="")
            job_id = await backend.submit_job(spec)
        assert job_id == "nd-12345"
        assert "nd-12345" in backend._job_map

    @pytest.mark.asyncio
    async def test_submit_job_raises_on_sbatch_failure(self, backend, tmp_path):
        from brain_researcher.services.agent.backends.base_backend import BackendSubmissionError

        spec = _make_spec(tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Permission denied")
            with pytest.raises(BackendSubmissionError, match="sbatch failed"):
                await backend.submit_job(spec)

    @pytest.mark.asyncio
    async def test_get_job_status_running(self, backend, tmp_path):
        backend._job_map["nd-12345"] = "12345"
        backend._jobs["nd-12345"] = JobStatus(
            job_id="nd-12345", backend="neurodesk_test",
            state=JobState.PENDING, submitted_at=datetime.utcnow()
        )
        squeue_out = "12345,RUNNING,2026-01-01T10:00:00,5:00\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=squeue_out, stderr="")
            status = await backend.get_job_status("nd-12345")
        assert status.state == JobState.RUNNING

    @pytest.mark.asyncio
    async def test_get_job_status_completed_via_sacct(self, backend, tmp_path):
        """When squeue returns empty (job done), fall back to sacct."""
        backend._job_map["nd-12345"] = "12345"
        backend._jobs["nd-12345"] = JobStatus(
            job_id="nd-12345", backend="neurodesk_test",
            state=JobState.PENDING, submitted_at=datetime.utcnow()
        )
        sacct_out = "12345|COMPLETED|2026-01-01T10:00:00|2026-01-01T11:00:00|0:0\n"

        call_count = {"n": 0}

        def fake_run(cmd, **kwargs):
            call_count["n"] += 1
            if "squeue" in cmd:
                return MagicMock(returncode=0, stdout="", stderr="")
            if "sacct" in cmd:
                return MagicMock(returncode=0, stdout=sacct_out, stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            status = await backend.get_job_status("nd-12345")
        assert status.state == JobState.COMPLETED

    @pytest.mark.asyncio
    async def test_cancel_job(self, backend, tmp_path):
        backend._job_map["nd-12345"] = "12345"
        backend._jobs["nd-12345"] = JobStatus(
            job_id="nd-12345", backend="neurodesk_test",
            state=JobState.RUNNING, submitted_at=datetime.utcnow()
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = await backend.cancel_job("nd-12345")
        assert result is True
        assert backend._jobs["nd-12345"].state == JobState.CANCELLED

    @pytest.mark.asyncio
    async def test_check_health_local(self, backend):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert await backend.check_health() is True

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            assert await backend.check_health() is False

    def test_supports_requirements(self, backend):
        assert backend.supports_requirements(ResourceRequirements(cpu=16, memory_gb=64)) is True
        assert backend.supports_requirements(ResourceRequirements(cpu=512, memory_gb=64)) is False
