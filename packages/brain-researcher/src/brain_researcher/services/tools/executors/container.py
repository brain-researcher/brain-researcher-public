"""Container execution helpers for neuroimaging tools.

This module centralises how we invoke containerised neuroimaging toolchains
so both LangGraph and the MCP layer share the same hardened execution path.

The helper focuses on a small, composable surface:

* `ContainerRequest` describes what to run (image/runtime/command/env/mounts).
* `run_container` executes the request locally via Docker or Apptainer.
* Optional `SlurmConfig` enables future submission to cluster schedulers
  without changing callers.

At this stage we explicitly avoid any heavy orchestration logic; the goal is to
standardise argument handling, logging, and error reporting so higher level
modules (FitLins, fMRIPrep, FSL, etc.) can build on a consistent contract.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Optional


Runtime = Literal["docker", "apptainer", "wrapper", "neurodesk_module"]
"""Runtime execution modes:
- docker: Run in Docker container (default for CI/cloud)
- apptainer: Run in Apptainer/Singularity container (default for HPC/Neurodesk)
- wrapper: Direct host execution (dev/debug fallback, requires tools installed locally)
- neurodesk_module: Host execution via Lmod module system (Neurodesk/CVMFS tools).
  Uses no sandbox isolation so the host conda env and module system are preserved.
  Commands are wrapped in: bash -c "source lmod_init && <command>"
"""


@dataclass
class BindMount:
    """A bind mount mapping for container execution."""

    host_path: str
    container_path: str
    read_only: bool = False

    def to_runtime_args(self, runtime: Runtime) -> List[str]:
        if runtime == "docker":
            mode = "ro" if self.read_only else "rw"
            return ["-v", f"{self.host_path}:{self.container_path}:{mode}"]
        if runtime == "apptainer":
            prefix = "--bind"
            mode = ",ro" if self.read_only else ""
            return [prefix, f"{self.host_path}:{self.container_path}{mode}"]
        raise ValueError(f"Unsupported runtime: {runtime}")


@dataclass
class SlurmConfig:
    """Optional Slurm submission configuration."""

    partition: Optional[str] = None
    time: Optional[str] = None
    gpus: Optional[int] = None
    cpus_per_task: Optional[int] = None
    mem_gb: Optional[int] = None
    additional_args: List[str] = field(default_factory=list)


@dataclass
class ContainerRequest:
    """Description of a container execution."""

    image: str | None = None
    command: List[str] = field(default_factory=list)
    runtime: Runtime = "apptainer"
    workdir: Optional[str] = None
    env: Dict[str, str] = field(default_factory=dict)
    mounts: List[BindMount] = field(default_factory=list)
    network_disabled: bool = False
    gpu_enabled: bool = False
    slurm: Optional[SlurmConfig] = None
    extra_run_args: List[str] = field(default_factory=list)

    # Sandbox isolation fields (P3.8)
    sandbox_enabled: bool = True  # Master switch for sandbox isolation
    clean_env: bool = True  # Use --cleanenv to clear host environment
    writable_tmpfs: bool = True  # Use --writable-tmpfs for temp space
    no_home: bool = True  # Use --no-home to prevent home dir access
    containall: bool = True  # Use --containall for full isolation

    def ensure_paths_exist(self) -> None:
        for mount in self.mounts:
            host = Path(mount.host_path)
            if not host.exists():
                raise FileNotFoundError(f"Mount path does not exist: {host}")
        if self.runtime != "wrapper" and not self.command:
            raise ValueError("ContainerRequest.command cannot be empty")


class ContainerExecutionError(RuntimeError):
    """Raised when container execution fails."""

    def __init__(self, message: str, *, stdout: str = "", stderr: str = "", exit_code: int | None = None):
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code


def _deduplicate_mounts(mounts: List[BindMount]) -> List[BindMount]:
    """Deduplicate bind mounts, keeping the last occurrence of each unique path pair.

    This ensures user-specified mounts override package defaults.

    Args:
        mounts: List of BindMount objects potentially containing duplicates

    Returns:
        List of deduplicated BindMount objects
    """
    seen: Dict[tuple[str, str], BindMount] = {}
    for mount in mounts:
        # Key by (host_path, container_path) pair
        key = (mount.host_path, mount.container_path)
        seen[key] = mount  # Last occurrence wins (allows overrides)

    return list(seen.values())


def _build_local_command(request: ContainerRequest) -> List[str]:
    request.ensure_paths_exist()

    # Deduplicate mounts before processing
    deduplicated_mounts = _deduplicate_mounts(request.mounts)

    if request.runtime == "docker":
        cmd: List[str] = ["docker", "run", "--rm"]
        if request.workdir:
            cmd += ["-w", request.workdir]
        if request.network_disabled:
            cmd += ["--network", "none"]
        if request.gpu_enabled:
            cmd += ["--gpus", "all"]
        for mount in deduplicated_mounts:
            cmd += mount.to_runtime_args("docker")
        for key, value in request.env.items():
            cmd += ["-e", f"{key}={value}"]
        cmd += request.extra_run_args
        if not request.image:
            raise ValueError("Docker runtime requires an image")
        cmd.append(request.image)
        cmd += request.command
        return cmd

    if request.runtime in ("apptainer", "singularity"):
        binary = "apptainer" if request.runtime == "apptainer" else "singularity"
        cmd = [binary]
        if request.runtime == "singularity":
            cmd.append("--silent")
            cmd.append("exec")
            cmd.append("--cleanenv")
        else:
            cmd.append("exec")

            # P3.8: Sandbox isolation flags for apptainer
            if request.sandbox_enabled:
                if request.no_home:
                    cmd.append("--no-home")
                if request.containall:
                    cmd.append("--containall")
                if request.clean_env:
                    cmd.append("--cleanenv")
                if request.writable_tmpfs:
                    cmd.append("--writable-tmpfs")

        if request.gpu_enabled:
            cmd.append("--nv")
        for mount in deduplicated_mounts:
            cmd += mount.to_runtime_args("apptainer")
        if request.network_disabled:
            if request.runtime == "apptainer":
                cmd.append("--net")
            cmd += ["--network", "none"]
        if request.workdir:
            cmd += ["--pwd", request.workdir]
        for key, value in request.env.items():
            cmd += ["--env", f"{key}={value}"]
        cmd += request.extra_run_args
        if not request.image:
            raise ValueError(f"{request.runtime} runtime requires an image")
        cmd.append(request.image)
        cmd += request.command
        return cmd

    if request.runtime == "wrapper":
        if not request.command:
            raise ValueError("Wrapper runtime requires command to execute")
        return request.command

    if request.runtime == "neurodesk_module":
        if not request.command:
            raise ValueError("neurodesk_module runtime requires command to execute")
        # Initialize Lmod (multiple fallback paths for different distros), then run the command.
        # No sandbox: host env vars and conda env must be preserved.
        lmod_init = (
            "source /etc/profile.d/lmod.sh 2>/dev/null"
            " || source /usr/share/lmod/lmod/init/bash 2>/dev/null"
            " || true"
        )
        inner = " ".join(shlex.quote(p) for p in request.command)
        return ["bash", "-c", f"{lmod_init} && {inner}"]

    raise ValueError(f"Unsupported runtime: {request.runtime}")


def _run_subprocess(cmd: List[str], *, env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        raise ContainerExecutionError(
            f"Command failed with exit code {proc.returncode}",
            stdout=proc.stdout,
            stderr=proc.stderr,
            exit_code=proc.returncode,
        )
    return proc


def _build_slurm_command(request: ContainerRequest) -> List[str]:
    assert request.slurm is not None
    sbatch = ["sbatch", "--parsable", "--export=ALL"]
    if request.slurm.partition:
        sbatch += ["--partition", request.slurm.partition]
    if request.slurm.time:
        sbatch += ["--time", request.slurm.time]
    if request.slurm.cpus_per_task:
        sbatch += ["--cpus-per-task", str(request.slurm.cpus_per_task)]
    if request.slurm.mem_gb:
        sbatch += ["--mem", f"{request.slurm.mem_gb}G"]
    if request.slurm.gpus:
        sbatch += ["--gpus", str(request.slurm.gpus)]
    sbatch += request.slurm.additional_args

    local_cmd = _build_local_command(request)
    # Join the inner command for sbatch --wrap
    wrapped = " ".join(shlex.quote(part) for part in local_cmd)
    sbatch += ["--wrap", wrapped]
    return sbatch


def run_container(request: ContainerRequest) -> Dict[str, Any]:
    """Execute the request either locally or via Slurm.

    Returns a dictionary with stdout, stderr, exit_code, and, when Slurm is used,
    a submission id.
    """
    if request.slurm:
        cmd = _build_slurm_command(request)
        proc = _run_subprocess(cmd)
        submission_id = proc.stdout.strip()
        return {
            "exit_code": 0,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "submission_id": submission_id,
            "mode": "slurm",
            "command": cmd,
        }

    cmd = _build_local_command(request)
    if request.runtime in ("wrapper", "neurodesk_module"):
        env = os.environ.copy()
        env.update(request.env)
        proc = _run_subprocess(cmd, env=env)
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "mode": request.runtime,
            "command": cmd,
        }

    proc = _run_subprocess(cmd)
    return {
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "mode": "local",
        "command": cmd,
    }


def make_neurodesk_module_request(
    command: List[str],
    *,
    env: Optional[Dict[str, str]] = None,
    workdir: Optional[str] = None,
) -> "ContainerRequest":
    """Factory for neurodesk_module ContainerRequest with correct sandbox-off defaults.

    The neurodesk_module runtime must NOT use sandbox isolation: the host conda
    env and Lmod module system must remain accessible inside the subprocess.
    """
    return ContainerRequest(
        image=None,
        command=command,
        runtime="neurodesk_module",
        workdir=workdir,
        env=env or {},
        mounts=[],
        sandbox_enabled=False,
        clean_env=False,
        writable_tmpfs=False,
        no_home=False,
        containall=False,
    )


def describe_request(request: ContainerRequest) -> Dict[str, Any]:
    """Serialize a container request for logging/debugging.

    Note: This shows deduplicated mounts to reflect what will actually be executed.
    """
    deduplicated_mounts = _deduplicate_mounts(request.mounts)

    return {
        "image": request.image,
        "runtime": request.runtime,
        "command": request.command,
        "workdir": request.workdir,
        "mounts": [
            {
                "host_path": mount.host_path,
                "container_path": mount.container_path,
                "read_only": mount.read_only,
            }
            for mount in deduplicated_mounts
        ],
        "mounts_original_count": len(request.mounts),
        "mounts_deduplicated_count": len(deduplicated_mounts),
        "env": request.env,
        "network_disabled": request.network_disabled,
        "gpu_enabled": request.gpu_enabled,
        "extra_run_args": request.extra_run_args,
        "slurm": request.slurm.__dict__ if request.slurm else None,
    }
