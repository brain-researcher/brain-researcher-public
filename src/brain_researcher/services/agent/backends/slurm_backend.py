"""SLURM backend for job execution."""

import asyncio
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import paramiko

    PARAMIKO_AVAILABLE = True
except ImportError:
    PARAMIKO_AVAILABLE = False

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

logger = logging.getLogger(__name__)


class SLURMBackend(BaseBackend):
    """SLURM backend for executing jobs via SLURM batch system."""

    def __init__(self, name: str, config: Dict[str, Any]):
        """Initialize SLURM backend.

        Args:
            name: Backend name
            config: Configuration containing:
                - host: SLURM head node hostname
                - username: SSH username
                - key_file: Path to SSH private key (optional)
                - password: SSH password (optional)
                - partition: SLURM partition (optional)
                - account: SLURM account (optional)
                - qos: Quality of Service (optional)
                - modules: Environment modules to load (optional)
                - container_runtime: singularity or podman (default: singularity)
                - scratch_dir: Scratch directory path (default: /tmp)
        """
        super().__init__(name, config)

        if not PARAMIKO_AVAILABLE:
            raise BackendConfigError("paramiko library not available")

        self.host = config.get("host")
        if not self.host:
            raise BackendConfigError("SLURM host not specified")

        self.username = config.get("username")
        if not self.username:
            raise BackendConfigError("SLURM username not specified")

        self.key_file = config.get("key_file")
        self.password = config.get("password")
        self.partition = config.get("partition")
        self.account = config.get("account")
        self.qos = config.get("qos")
        self.modules = config.get("modules", [])
        self.container_runtime = config.get("container_runtime", "singularity")
        self.scratch_dir = config.get("scratch_dir", "/tmp")

        if not self.key_file and not self.password:
            raise BackendConfigError("Either key_file or password must be specified")

        self.ssh_client = None
        self._job_ids: Dict[str, str] = {}  # Map our job IDs to SLURM job IDs

    async def _get_ssh_client(self):
        """Get or create SSH client connection."""
        if not PARAMIKO_AVAILABLE:
            raise BackendUnavailableError("paramiko library not available")

        if self.ssh_client is None or not self.ssh_client.get_transport():
            import paramiko

            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            try:
                if self.key_file:
                    self.ssh_client.connect(
                        hostname=self.host,
                        username=self.username,
                        key_filename=self.key_file,
                        timeout=30,
                    )
                else:
                    self.ssh_client.connect(
                        hostname=self.host,
                        username=self.username,
                        password=self.password,
                        timeout=30,
                    )
            except Exception as e:
                raise BackendUnavailableError(f"Failed to connect to SLURM host: {e}")

        return self.ssh_client

    async def _execute_command(self, command: str) -> tuple[str, str, int]:
        """Execute command via SSH and return stdout, stderr, exit code."""
        ssh = await self._get_ssh_client()

        try:
            stdin, stdout, stderr = ssh.exec_command(command, timeout=60)
            exit_code = stdout.channel.recv_exit_status()
            stdout_text = stdout.read().decode("utf-8")
            stderr_text = stderr.read().decode("utf-8")

            return stdout_text, stderr_text, exit_code
        except Exception as e:
            raise BackendSubmissionError(f"Command execution failed: {e}")

    def _create_slurm_script(self, job_spec: JobSpecification) -> str:
        """Create SLURM batch script from job specification."""
        script_lines = [
            "#!/bin/bash",
            f"#SBATCH --job-name={job_spec.name}",
            f"#SBATCH --time={job_spec.resources.walltime_minutes}",
            f"#SBATCH --mem={int(job_spec.resources.memory_gb * 1024)}M",
            f"#SBATCH --cpus-per-task={int(job_spec.resources.cpu)}",
        ]

        # Add optional SLURM directives
        if self.partition:
            script_lines.append(f"#SBATCH --partition={self.partition}")

        if self.account:
            script_lines.append(f"#SBATCH --account={self.account}")

        if self.qos:
            script_lines.append(f"#SBATCH --qos={self.qos}")

        if job_spec.resources.gpu > 0:
            script_lines.append(f"#SBATCH --gres=gpu:{job_spec.resources.gpu}")

        if job_spec.resources.node_count > 1:
            script_lines.append(f"#SBATCH --nodes={job_spec.resources.node_count}")

        # Output and error files
        job_dir = f"{self.scratch_dir}/brain_researcher_{job_spec.name}"
        script_lines.extend(
            [
                f"#SBATCH --output={job_dir}/output.log",
                f"#SBATCH --error={job_dir}/error.log",
                "",
                "# Setup job environment",
                f"mkdir -p {job_dir}",
                f"cd {job_dir}",
                "",
            ]
        )

        # Load modules
        if self.modules:
            for module in self.modules:
                script_lines.append(f"module load {module}")
            script_lines.append("")

        # Set environment variables
        if job_spec.environment:
            for key, value in job_spec.environment.items():
                script_lines.append(f"export {key}={value}")
            script_lines.append("")

        # Container execution
        if self.container_runtime == "singularity":
            script_lines.extend(
                [
                    "# Execute job in container",
                    f"singularity exec \\",
                    f"  --bind {job_dir}:{job_spec.working_dir} \\",
                    f"  --bind {job_dir}:{job_spec.output_path} \\",
                    f"  --workdir {job_spec.working_dir} \\",
                ]
            )

            # Add environment variables to singularity
            if job_spec.environment:
                for key, value in job_spec.environment.items():
                    script_lines.append(f"  --env {key}={value} \\")

            script_lines.extend(
                [
                    f"  {job_spec.image} \\",
                    f"  /bin/bash -c '{job_spec.command}'",
                    "",
                    "# Capture exit code",
                    "exit_code=$?",
                    f'echo "Job completed with exit code: $exit_code" >> {job_dir}/status.log',
                    "exit $exit_code",
                ]
            )

        elif self.container_runtime == "podman":
            script_lines.extend(
                [
                    "# Execute job in container",
                    "podman run --rm \\",
                    f"  -v {job_dir}:{job_spec.working_dir} \\",
                    f"  -v {job_dir}:{job_spec.output_path} \\",
                    f"  -w {job_spec.working_dir} \\",
                ]
            )

            # Add environment variables to podman
            if job_spec.environment:
                for key, value in job_spec.environment.items():
                    script_lines.append(f"  -e {key}={value} \\")

            script_lines.extend(
                [
                    f"  {job_spec.image} \\",
                    f"  /bin/bash -c '{job_spec.command}'",
                    "",
                    "exit_code=$?",
                    f'echo "Job completed with exit code: $exit_code" >> {job_dir}/status.log',
                    "exit $exit_code",
                ]
            )

        else:
            # Direct execution (no container)
            script_lines.extend(
                [
                    "# Execute job directly",
                    f"cd {job_spec.working_dir}",
                    job_spec.command,
                    "",
                    "exit_code=$?",
                    f'echo "Job completed with exit code: $exit_code" >> {job_dir}/status.log',
                    "exit $exit_code",
                ]
            )

        return "\n".join(script_lines)

    async def submit_job(self, job_spec: JobSpecification) -> str:
        """Submit job to SLURM."""
        try:
            # Create SLURM script
            script_content = self._create_slurm_script(job_spec)

            # Create temporary script file on remote host
            script_path = f"{self.scratch_dir}/slurm_script_{job_spec.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sh"

            # Write script to remote host
            ssh = await self._get_ssh_client()
            sftp = ssh.open_sftp()

            try:
                with sftp.file(script_path, "w") as f:
                    f.write(script_content)
                sftp.chmod(script_path, 0o755)
            finally:
                sftp.close()

            # Submit job using sbatch
            submit_cmd = f"sbatch {script_path}"
            stdout, stderr, exit_code = await self._execute_command(submit_cmd)

            if exit_code != 0:
                raise BackendSubmissionError(f"sbatch failed: {stderr}")

            # Parse SLURM job ID from output
            # Typical output: "Submitted batch job 12345"
            match = re.search(r"Submitted batch job (\d+)", stdout)
            if not match:
                raise BackendSubmissionError(f"Could not parse job ID from: {stdout}")

            slurm_job_id = match.group(1)
            job_id = f"slurm-{slurm_job_id}"

            # Store job mapping
            self._job_ids[job_id] = slurm_job_id

            # Store job status
            self._jobs[job_id] = JobStatus(
                job_id=job_id,
                backend=self.name,
                state=JobState.PENDING,
                submitted_at=datetime.utcnow(),
            )

            logger.info(f"Submitted SLURM job {job_id} (SLURM ID: {slurm_job_id})")
            return job_id

        except Exception as e:
            if isinstance(e, BackendSubmissionError):
                raise
            error_msg = f"Failed to submit SLURM job: {e}"
            logger.error(error_msg)
            raise BackendSubmissionError(error_msg)

    async def get_job_status(self, job_id: str) -> JobStatus:
        """Get status of SLURM job."""
        try:
            if job_id not in self._job_ids:
                raise JobNotFoundError(f"Job {job_id} not found")

            slurm_job_id = self._job_ids[job_id]

            # Query job status using squeue and sacct
            squeue_cmd = f"squeue -j {slurm_job_id} --format='%i,%T,%S,%M' --noheader"
            stdout, stderr, exit_code = await self._execute_command(squeue_cmd)

            state = JobState.PENDING
            started_at = None
            completed_at = None
            exit_code_val = None

            if exit_code == 0 and stdout.strip():
                # Job is currently in queue
                parts = stdout.strip().split(",")
                if len(parts) >= 2:
                    slurm_state = parts[1].strip()

                    if slurm_state in ["PENDING", "PD"]:
                        state = JobState.PENDING
                    elif slurm_state in ["RUNNING", "R"]:
                        state = JobState.RUNNING
                        # Parse start time if available
                        if len(parts) >= 3 and parts[2].strip():
                            try:
                                started_at = datetime.strptime(
                                    parts[2].strip(), "%Y-%m-%dT%H:%M:%S"
                                )
                            except ValueError:
                                pass
                    elif slurm_state in ["COMPLETING", "CG"]:
                        state = JobState.RUNNING
                    elif slurm_state in ["COMPLETED", "CD"]:
                        state = JobState.COMPLETED
                        exit_code_val = 0
                    elif slurm_state in [
                        "FAILED",
                        "F",
                        "TIMEOUT",
                        "TO",
                        "CANCELLED",
                        "CA",
                    ]:
                        state = JobState.FAILED
                        exit_code_val = 1
            else:
                # Job not in queue, check sacct for completed jobs
                sacct_cmd = f"sacct -j {slurm_job_id} --format='JobID,State,Start,End,ExitCode' --noheader --parsable2"
                stdout, stderr, exit_code = await self._execute_command(sacct_cmd)

                if exit_code == 0 and stdout.strip():
                    for line in stdout.strip().split("\n"):
                        parts = line.split("|")
                        if len(parts) >= 5 and parts[0] == slurm_job_id:
                            slurm_state = parts[1].strip()
                            start_time = parts[2].strip()
                            end_time = parts[3].strip()
                            exit_code_str = parts[4].strip()

                            if slurm_state == "COMPLETED":
                                state = JobState.COMPLETED
                                exit_code_val = 0
                            elif slurm_state in ["FAILED", "TIMEOUT", "CANCELLED"]:
                                state = JobState.FAILED
                                exit_code_val = 1

                            # Parse timestamps
                            try:
                                if start_time and start_time != "Unknown":
                                    started_at = datetime.strptime(
                                        start_time, "%Y-%m-%dT%H:%M:%S"
                                    )
                                if end_time and end_time != "Unknown":
                                    completed_at = datetime.strptime(
                                        end_time, "%Y-%m-%dT%H:%M:%S"
                                    )
                            except ValueError:
                                pass

                            # Parse exit code
                            if exit_code_str and ":" in exit_code_str:
                                try:
                                    exit_code_val = int(exit_code_str.split(":")[0])
                                except ValueError:
                                    pass

                            break

            # Update stored status
            job_status = JobStatus(
                job_id=job_id,
                backend=self.name,
                state=state,
                submitted_at=self._jobs.get(
                    job_id,
                    JobStatus(
                        job_id=job_id,
                        backend=self.name,
                        state=state,
                        submitted_at=datetime.utcnow(),
                    ),
                ).submitted_at,
                started_at=started_at,
                completed_at=completed_at,
                exit_code=exit_code_val,
            )

            self._jobs[job_id] = job_status
            return job_status

        except JobNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to get SLURM job status: {e}")
            raise BackendSubmissionError(f"Failed to get job status: {e}")

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel SLURM job."""
        try:
            if job_id not in self._job_ids:
                raise JobNotFoundError(f"Job {job_id} not found")

            slurm_job_id = self._job_ids[job_id]

            # Cancel job using scancel
            cancel_cmd = f"scancel {slurm_job_id}"
            stdout, stderr, exit_code = await self._execute_command(cancel_cmd)

            if exit_code == 0:
                # Update status
                if job_id in self._jobs:
                    self._jobs[job_id].state = JobState.CANCELLED

                logger.info(f"Cancelled SLURM job {job_id}")
                return True
            else:
                logger.error(f"Failed to cancel SLURM job {job_id}: {stderr}")
                return False

        except JobNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error cancelling SLURM job {job_id}: {e}")
            return False

    async def get_logs(self, job_id: str) -> str:
        """Get logs from SLURM job."""
        try:
            if job_id not in self._job_ids:
                raise JobNotFoundError(f"Job {job_id} not found")

            slurm_job_id = self._job_ids[job_id]

            # Try to find the job's log files
            # First, get job info to find the output files
            scontrol_cmd = f"scontrol show job {slurm_job_id}"
            stdout, stderr, exit_code = await self._execute_command(scontrol_cmd)

            log_content = []

            if exit_code == 0:
                # Parse output to find log file paths
                output_file = None
                error_file = None

                for line in stdout.split("\n"):
                    if "StdOut=" in line:
                        output_file = line.split("StdOut=")[1].split()[0]
                    elif "StdErr=" in line:
                        error_file = line.split("StdErr=")[1].split()[0]

                # Read log files
                for log_file, log_type in [
                    (output_file, "STDOUT"),
                    (error_file, "STDERR"),
                ]:
                    if log_file and log_file != "/dev/null":
                        cat_cmd = f"cat {log_file} 2>/dev/null || echo 'Log file not found: {log_file}'"
                        log_stdout, log_stderr, log_exit = await self._execute_command(
                            cat_cmd
                        )

                        if log_stdout.strip():
                            log_content.append(f"=== {log_type} ===")
                            log_content.append(log_stdout)
                            log_content.append("")

            if not log_content:
                return f"No logs available for job {job_id}"

            return "\n".join(log_content)

        except JobNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error getting SLURM job logs: {e}")
            return f"Error retrieving logs: {e}"

    async def check_health(self) -> bool:
        """Check if SLURM cluster is accessible."""
        try:
            # Try to run sinfo to check cluster status
            stdout, stderr, exit_code = await self._execute_command("sinfo --version")
            return exit_code == 0
        except Exception as e:
            logger.error(f"SLURM health check failed: {e}")
            return False

    async def get_capacity(self) -> BackendCapacity:
        """Get SLURM cluster capacity information."""
        try:
            # Get partition info
            sinfo_cmd = "sinfo --format='%P,%C,%m,%G' --noheader"
            if self.partition:
                sinfo_cmd += f" --partition={self.partition}"

            stdout, stderr, exit_code = await self._execute_command(sinfo_cmd)

            total_cpu = 0.0
            available_cpu = 0.0
            total_memory_gb = 0.0
            available_memory_gb = 0.0
            total_gpu = 0
            available_gpu = 0

            if exit_code == 0:
                for line in stdout.strip().split("\n"):
                    if not line.strip():
                        continue

                    parts = line.split(",")
                    if len(parts) >= 3:
                        # Parse CPU info (format: allocated/idle/other/total)
                        cpu_info = parts[1].strip()
                        if "/" in cpu_info:
                            cpu_parts = cpu_info.split("/")
                            if len(cpu_parts) >= 4:
                                allocated = int(cpu_parts[0])
                                idle = int(cpu_parts[1])
                                total = int(cpu_parts[3])
                                total_cpu += total
                                available_cpu += idle

                        # Parse memory info
                        memory_info = parts[2].strip()
                        if memory_info and memory_info != "N/A":
                            # Memory is typically in MB
                            try:
                                memory_mb = float(memory_info)
                                total_memory_gb += memory_mb / 1024
                                available_memory_gb += (
                                    memory_mb / 1024 * 0.8
                                )  # Estimate
                            except ValueError:
                                pass

                        # Parse GPU info if available
                        if len(parts) >= 4:
                            gpu_info = parts[3].strip()
                            if gpu_info and gpu_info != "N/A":
                                # Parse GPU format (varies by SLURM version)
                                gpu_match = re.search(r"gpu:(\d+)", gpu_info)
                                if gpu_match:
                                    gpu_count = int(gpu_match.group(1))
                                    total_gpu += gpu_count
                                    available_gpu += gpu_count  # Simplified estimate

            # Get queue depth
            squeue_cmd = "squeue --noheader | wc -l"
            stdout, stderr, exit_code = await self._execute_command(squeue_cmd)
            queue_depth = 0
            if exit_code == 0:
                try:
                    queue_depth = int(stdout.strip())
                except ValueError:
                    pass

            return BackendCapacity(
                total_cpu=total_cpu,
                available_cpu=available_cpu,
                total_memory_gb=total_memory_gb,
                available_memory_gb=available_memory_gb,
                total_gpu=total_gpu,
                available_gpu=available_gpu,
                queue_depth=queue_depth,
            )

        except Exception as e:
            logger.error(f"Failed to get SLURM capacity: {e}")
            return BackendCapacity(
                total_cpu=0,
                available_cpu=0,
                total_memory_gb=0,
                available_memory_gb=0,
                total_gpu=0,
                available_gpu=0,
                queue_depth=0,
            )

    def supports_requirements(self, requirements: ResourceRequirements) -> bool:
        """Check if SLURM can satisfy requirements."""
        # Basic validation - could be enhanced with actual cluster limits
        return (
            requirements.cpu <= 128
            and requirements.memory_gb <= 1024
            and requirements.walltime_minutes <= 7 * 24 * 60
        )  # 7 days max

    def estimate_queue_time(self, requirements: ResourceRequirements) -> int:
        """Estimate queue time based on SLURM queue."""
        try:
            # Get queue information
            squeue_cmd = "squeue --format='%T' --noheader"
            if self.partition:
                squeue_cmd += f" --partition={self.partition}"

            asyncio.create_task(self._execute_command(squeue_cmd))
            # This is a simplified estimation
            return 10  # Default 10 minutes
        except Exception:
            return 15  # Default estimate

    def get_cost_estimate(self, requirements: ResourceRequirements) -> float:
        """Estimate cost for SLURM job (typically free for academic use)."""
        # SLURM is typically free for academic clusters
        # Could implement allocation unit tracking here
        return 0.0
