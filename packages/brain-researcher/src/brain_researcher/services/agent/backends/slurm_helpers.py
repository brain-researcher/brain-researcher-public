"""Pure SLURM output parsing helpers shared by SLURMBackend and NeurodeskBackend."""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Tuple

from .base_backend import JobState


def parse_squeue_output(
    slurm_job_id: str, stdout: str
) -> Tuple[Optional[JobState], Optional[datetime]]:
    """Parse squeue --format='%i,%T,%S,%M' --noheader output.

    Returns (state, started_at).  Returns (None, None) when the job is not
    found in the queue (e.g. already finished).
    """
    for line in stdout.strip().splitlines():
        parts = line.strip().split(",")
        if len(parts) < 2:
            continue
        if parts[0].strip() != slurm_job_id:
            continue
        slurm_state = parts[1].strip()
        started_at: Optional[datetime] = None

        if slurm_state in ("PENDING", "PD"):
            return JobState.PENDING, None
        if slurm_state in ("RUNNING", "R"):
            if len(parts) >= 3 and parts[2].strip():
                try:
                    started_at = datetime.strptime(parts[2].strip(), "%Y-%m-%dT%H:%M:%S")
                except ValueError:
                    pass
            return JobState.RUNNING, started_at
        if slurm_state in ("COMPLETING", "CG"):
            return JobState.RUNNING, None
        if slurm_state in ("COMPLETED", "CD"):
            return JobState.COMPLETED, None
        if slurm_state in ("FAILED", "F", "TIMEOUT", "TO", "CANCELLED", "CA", "NODE_FAIL"):
            return JobState.FAILED, None

    return None, None  # not found in queue


def parse_sacct_output(
    slurm_job_id: str, stdout: str
) -> Tuple[Optional[JobState], Optional[datetime], Optional[datetime], Optional[int]]:
    """Parse sacct --format='JobID,State,Start,End,ExitCode' --noheader --parsable2 output.

    Returns (state, started_at, completed_at, exit_code).
    Returns (None, None, None, None) when the job is not found.
    """
    for line in stdout.strip().splitlines():
        parts = line.split("|")
        if len(parts) < 5:
            continue
        if parts[0].strip() != slurm_job_id:
            continue

        slurm_state = parts[1].strip()
        start_raw   = parts[2].strip()
        end_raw     = parts[3].strip()
        ec_raw      = parts[4].strip()

        state: Optional[JobState] = None
        if slurm_state == "COMPLETED":
            state = JobState.COMPLETED
        elif slurm_state in ("FAILED", "TIMEOUT", "CANCELLED", "NODE_FAIL"):
            state = JobState.FAILED

        started_at: Optional[datetime] = None
        completed_at: Optional[datetime] = None
        try:
            if start_raw and start_raw != "Unknown":
                started_at = datetime.strptime(start_raw, "%Y-%m-%dT%H:%M:%S")
            if end_raw and end_raw != "Unknown":
                completed_at = datetime.strptime(end_raw, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            pass

        exit_code: Optional[int] = None
        if ec_raw and ":" in ec_raw:
            try:
                exit_code = int(ec_raw.split(":")[0])
            except ValueError:
                pass

        return state, started_at, completed_at, exit_code

    return None, None, None, None
