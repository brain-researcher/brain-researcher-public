"""Shared utilities for agent tools."""

import subprocess


def run_subprocess(
    cmd: list[str], env: dict | None = None, cwd: str | None = None
) -> subprocess.CompletedProcess:
    """
    Run a command and raise if it fails.

    Shared utility for all tools that need to execute subprocess commands.

    Args:
        cmd: Command and arguments as a list
        env: Optional environment variables
        cwd: Optional working directory for the subprocess

    Returns:
        CompletedProcess instance

    Raises:
        RuntimeError: If the command fails (non-zero exit code)
    """
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=cwd,
    )
    if proc.returncode != 0:
        error_msg = proc.stderr or proc.stdout or "command failed"
        raise RuntimeError(f"Command {' '.join(cmd)} failed: {error_msg}")
    return proc
