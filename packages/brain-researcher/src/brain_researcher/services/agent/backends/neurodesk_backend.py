"""NeurodeskBackend — BaseBackend implementation for Neurodesk/SLURM environments.

Compiles WorkflowSteps into Neurodesk-style shell scripts and submits them via
sbatch.  Supports two execution modes:

* ``local``  — sbatch is available on the current host (login node with CVMFS).
  Uses ``subprocess.run(["sbatch", ...])`` directly.

* ``remote`` — sbatch is on a remote host; uses paramiko SSH (same approach as
  SLURMBackend) to transfer the script via SFTP and submit remotely.

The ``NeurodeskCompiler`` is used to produce the script; the ``NeurodeskBackend``
is only responsible for submit / poll / cancel.
"""
from __future__ import annotations

import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .base_backend import (
    BackendCapacity,
    BackendConfigError,
    BackendSubmissionError,
    BackendUnavailableError,
    BaseBackend,
    JobNotFoundError,
    JobSpecification,
    JobState,
    JobStatus,
    ResourceRequirements,
)
from .slurm_helpers import parse_sacct_output, parse_squeue_output

logger = logging.getLogger(__name__)


class NeurodeskBackend(BaseBackend):
    """SLURM-based backend for Neurodesk scientific runtime environments.

    Config keys
    -----------
    mode : "local" | "remote"   (default: "local")
    run_dir : str               Base directory for scripts and logs
    partition : str | None
    account : str | None
    qos : str | None
    # Remote-only (requires paramiko):
    host : str
    username : str
    key_file : str | None
    password : str | None
    scratch_dir : str           Remote scratch directory (default: /tmp)
    """

    def __init__(self, name: str, config: Dict[str, Any]) -> None:
        super().__init__(name, config)
        self.mode: str = config.get("mode", "local")
        if self.mode not in ("local", "remote"):
            raise BackendConfigError(f"NeurodeskBackend mode must be 'local' or 'remote', got {self.mode!r}")

        self.run_dir = Path(config.get("run_dir", "/tmp/brain_researcher_neurodesk"))
        self.partition: Optional[str] = config.get("partition")
        self.account: Optional[str]   = config.get("account")
        self.qos: Optional[str]       = config.get("qos")

        # Map our job IDs to SLURM job IDs
        self._job_map: Dict[str, str] = {}

        # Remote mode setup
        if self.mode == "remote":
            try:
                import paramiko  # noqa: F401
            except ImportError:
                raise BackendConfigError(
                    "paramiko is required for NeurodeskBackend remote mode: pip install paramiko"
                )
            self.host: str     = config.get("host", "")
            self.username: str = config.get("username", "")
            self.key_file: Optional[str]  = config.get("key_file")
            self.password: Optional[str]  = config.get("password")
            self.scratch_dir: str = config.get("scratch_dir", "/tmp")
            if not self.host or not self.username:
                raise BackendConfigError("Remote NeurodeskBackend requires 'host' and 'username'")
            if not self.key_file and not self.password:
                raise BackendConfigError("Remote mode requires 'key_file' or 'password'")
            self._ssh_client = None

    # ------------------------------------------------------------------
    # BaseBackend implementation
    # ------------------------------------------------------------------

    async def submit_job(self, job_spec: JobSpecification) -> str:
        """Submit a pre-compiled script via sbatch and return our job ID."""
        # The NeurodeskToolExecutor attaches the pack to job_spec._pack.
        # Fall back to job_spec.command (which is "bash /path/to/script.sh").
        pack = getattr(job_spec, "_pack", None)
        if pack is not None:
            script_path = pack.script_path
        else:
            # Attempt to extract script path from command string
            parts = job_spec.command.split()
            if len(parts) >= 2 and parts[0] == "bash":
                script_path = Path(parts[1])
            else:
                raise BackendSubmissionError(
                    f"NeurodeskBackend: cannot determine script path from command: {job_spec.command!r}"
                )

        if self.mode == "local":
            return await self._submit_local(job_spec.name, script_path)
        else:
            return await self._submit_remote(job_spec.name, script_path)

    async def get_job_status(self, job_id: str) -> JobStatus:
        if job_id not in self._job_map:
            raise JobNotFoundError(f"Job {job_id} not found in NeurodeskBackend")

        slurm_id = self._job_map[job_id]

        if self.mode == "local":
            state, started_at = await self._squeue_local(slurm_id)
        else:
            state, started_at = await self._squeue_remote(slurm_id)

        completed_at: Optional[datetime] = None
        exit_code_val: Optional[int]     = None

        if state is None:
            # Job not in queue — check sacct
            if self.mode == "local":
                sacct_out = await self._sacct_local(slurm_id)
            else:
                sacct_out = await self._sacct_remote(slurm_id)
            state, started_at, completed_at, exit_code_val = parse_sacct_output(slurm_id, sacct_out)
            if state is None:
                state = JobState.PENDING  # unknown, treat as still pending

        stored = self._jobs.get(job_id)
        submitted_at = stored.submitted_at if stored else datetime.utcnow()

        status = JobStatus(
            job_id=job_id,
            backend=self.name,
            state=state,
            submitted_at=submitted_at,
            started_at=started_at,
            completed_at=completed_at,
            exit_code=exit_code_val,
        )
        self._jobs[job_id] = status
        return status

    async def cancel_job(self, job_id: str) -> bool:
        if job_id not in self._job_map:
            raise JobNotFoundError(f"Job {job_id} not found")
        slurm_id = self._job_map[job_id]
        cmd = ["scancel", slurm_id]
        try:
            if self.mode == "local":
                proc = subprocess.run(cmd, capture_output=True, text=True)
                ok = proc.returncode == 0
            else:
                _, _, rc = await self._ssh_exec(" ".join(cmd))
                ok = rc == 0
        except Exception as exc:
            logger.error("NeurodeskBackend cancel_job failed: %s", exc)
            return False
        if ok and job_id in self._jobs:
            self._jobs[job_id].state = JobState.CANCELLED
        return ok

    async def get_logs(self, job_id: str) -> str:
        if job_id not in self._job_map:
            raise JobNotFoundError(f"Job {job_id} not found")
        # Attempt to read log files written by the compiler
        pack = None
        for js in self._jobs.values():
            if js.job_id == job_id:
                break
        # Best effort: glob logs dir for matching files
        logs_dir = self.run_dir / "logs"
        pattern = f"*{self._job_map[job_id]}*"
        logs: list[str] = []
        for log_file in sorted(logs_dir.glob(pattern)):
            try:
                logs.append(f"=== {log_file.name} ===\n{log_file.read_text()}")
            except OSError:
                pass
        return "\n".join(logs) if logs else f"No log files found for job {job_id}"

    async def check_health(self) -> bool:
        try:
            if self.mode == "local":
                proc = subprocess.run(["sinfo", "--version"], capture_output=True, timeout=10)
                return proc.returncode == 0
            else:
                _, _, rc = await self._ssh_exec("sinfo --version")
                return rc == 0
        except Exception:
            return False

    async def get_capacity(self) -> BackendCapacity:
        # Lightweight: return zeros — capacity querying is best-effort
        return BackendCapacity(
            total_cpu=0, available_cpu=0,
            total_memory_gb=0, available_memory_gb=0,
            total_gpu=0, available_gpu=0,
            queue_depth=0,
        )

    def supports_requirements(self, requirements: ResourceRequirements) -> bool:
        return (
            requirements.cpu <= 256
            and requirements.memory_gb <= 1024
            and requirements.walltime_minutes <= 7 * 24 * 60
        )

    def estimate_queue_time(self, requirements: ResourceRequirements) -> int:
        return 10  # minutes (optimistic default)

    def get_cost_estimate(self, requirements: ResourceRequirements) -> float:
        return 0.0  # HPC/Neurodesk is typically free for academic use

    # ------------------------------------------------------------------
    # Local-mode helpers
    # ------------------------------------------------------------------

    async def _submit_local(self, job_name: str, script_path: Path) -> str:
        cmd = ["sbatch", "--parsable", str(script_path)]
        if self.partition:
            cmd += ["--partition", self.partition]
        if self.account:
            cmd += ["--account", self.account]
        if self.qos:
            cmd += ["--qos", self.qos]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired as exc:
            raise BackendSubmissionError(f"sbatch timed out: {exc}") from exc

        if proc.returncode != 0:
            raise BackendSubmissionError(
                f"sbatch failed (exit {proc.returncode}): {proc.stderr.strip()}"
            )

        slurm_id = proc.stdout.strip().split(";")[0]
        if not slurm_id.isdigit():
            raise BackendSubmissionError(f"Unexpected sbatch output: {proc.stdout!r}")

        job_id = f"nd-{slurm_id}"
        self._job_map[job_id] = slurm_id
        self._jobs[job_id] = JobStatus(
            job_id=job_id,
            backend=self.name,
            state=JobState.PENDING,
            submitted_at=datetime.utcnow(),
        )
        logger.info("NeurodeskBackend: submitted %s → SLURM %s", job_id, slurm_id)
        return job_id

    async def _squeue_local(self, slurm_id: str):
        cmd = ["squeue", "-j", slurm_id, "--format=%i,%T,%S,%M", "--noheader"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if proc.returncode == 0 and proc.stdout.strip():
                return parse_squeue_output(slurm_id, proc.stdout)
        except Exception as exc:
            logger.debug("squeue error: %s", exc)
        return None, None

    async def _sacct_local(self, slurm_id: str) -> str:
        cmd = [
            "sacct", "-j", slurm_id,
            "--format=JobID,State,Start,End,ExitCode",
            "--noheader", "--parsable2",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return proc.stdout
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Remote-mode helpers (SSH via paramiko)
    # ------------------------------------------------------------------

    async def _get_ssh(self):
        import paramiko
        if self._ssh_client is None or not self._ssh_client.get_transport():
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            kwargs: Dict[str, Any] = dict(hostname=self.host, username=self.username, timeout=30)
            if self.key_file:
                kwargs["key_filename"] = self.key_file
            else:
                kwargs["password"] = self.password
            try:
                client.connect(**kwargs)
            except Exception as exc:
                raise BackendUnavailableError(f"SSH connect failed: {exc}") from exc
            self._ssh_client = client
        return self._ssh_client

    async def _ssh_exec(self, command: str):
        ssh = await self._get_ssh()
        _, stdout, stderr = ssh.exec_command(command, timeout=60)
        rc = stdout.channel.recv_exit_status()
        return stdout.read().decode(), stderr.read().decode(), rc

    async def _submit_remote(self, job_name: str, script_path: Path) -> str:
        import paramiko
        ssh = await self._get_ssh()
        sftp = ssh.open_sftp()
        remote_path = f"{self.scratch_dir}/{script_path.name}"
        try:
            sftp.put(str(script_path), remote_path)
            sftp.chmod(remote_path, 0o755)
        finally:
            sftp.close()

        sbatch_cmd = f"sbatch --parsable {remote_path}"
        if self.partition:
            sbatch_cmd += f" --partition {self.partition}"
        if self.account:
            sbatch_cmd += f" --account {self.account}"

        stdout, stderr, rc = await self._ssh_exec(sbatch_cmd)
        if rc != 0:
            raise BackendSubmissionError(f"Remote sbatch failed: {stderr.strip()}")

        slurm_id = stdout.strip().split(";")[0]
        job_id = f"nd-{slurm_id}"
        self._job_map[job_id] = slurm_id
        self._jobs[job_id] = JobStatus(
            job_id=job_id, backend=self.name,
            state=JobState.PENDING, submitted_at=datetime.utcnow(),
        )
        return job_id

    async def _squeue_remote(self, slurm_id: str):
        cmd = f"squeue -j {slurm_id} --format='%i,%T,%S,%M' --noheader"
        stdout, _, rc = await self._ssh_exec(cmd)
        if rc == 0 and stdout.strip():
            return parse_squeue_output(slurm_id, stdout)
        return None, None

    async def _sacct_remote(self, slurm_id: str) -> str:
        cmd = (
            f"sacct -j {slurm_id}"
            " --format='JobID,State,Start,End,ExitCode'"
            " --noheader --parsable2"
        )
        stdout, _, _ = await self._ssh_exec(cmd)
        return stdout
