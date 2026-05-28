"""
Command execution helpers for long-running neuroimaging tools.

This module provides a light abstraction for running shell commands with
streamed logging, filesystem bindings, and timeout handling. It is intentionally
minimal so it can be reused both in the CLI (brainr) and orchestrator jobs.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

import logging

logger = logging.getLogger(__name__)


DatastreamCallback = Callable[[Dict[str, str]], None]


@dataclass
class CommandSpec:
    """Specification for launching a command."""

    cmd: List[str]
    env: Dict[str, str] = field(default_factory=dict)
    cwd: Optional[str] = None
    timeout: Optional[int] = None  # seconds
    stdout_path: Optional[str] = None
    stderr_path: Optional[str] = None
    name: str = "command"


@dataclass
class CommandResult:
    """Result metadata for an executed command."""

    exit_code: int
    duration_s: float
    stdout_path: Optional[str]
    stderr_path: Optional[str]
    was_timeout: bool = False


class CommandExecutionError(RuntimeError):
    """Raised when command execution fails."""

    def __init__(self, message: str, result: Optional[CommandResult] = None):
        super().__init__(message)
        self.result = result


def _ensure_parent(path: Optional[str]) -> Optional[Path]:
    if not path:
        return None
    dest = Path(path).expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest


def run_command(
    spec: CommandSpec,
    *,
    progress_callback: Optional[DatastreamCallback] = None,
) -> CommandResult:
    """
    Execute a command synchronously with streamed logging.

    Args:
        spec: Command specification.
        progress_callback: Optional callback invoked with log lines
            {'stream': 'stdout' | 'stderr', 'line': '<text>'}.

    Returns:
        CommandResult with exit code and log locations.
    """

    if not spec.cmd:
        raise ValueError("CommandSpec.cmd must be non-empty")

    stdout_file = _ensure_parent(spec.stdout_path)
    stderr_file = _ensure_parent(spec.stderr_path)

    stdout_fp = open(stdout_file, "w", buffering=1) if stdout_file else None
    stderr_fp = open(stderr_file, "w", buffering=1) if stderr_file else None

    def _close_files():
        for handle in (stdout_fp, stderr_fp):
            if handle:
                handle.close()

    env = os.environ.copy()
    env.update(spec.env or {})

    start = time.time()
    process = subprocess.Popen(
        spec.cmd,
        cwd=spec.cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    def _pump(stream, stream_name: str, file_handle):
        try:
            for line in iter(stream.readline, ""):
                if file_handle:
                    file_handle.write(line)
                    file_handle.flush()
                if progress_callback:
                    progress_callback({"stream": stream_name, "line": line})
        finally:
            stream.close()

    stdout_thread = threading.Thread(
        target=_pump, args=(process.stdout, "stdout", stdout_fp), daemon=True
    )
    stderr_thread = threading.Thread(
        target=_pump, args=(process.stderr, "stderr", stderr_fp), daemon=True
    )
    stdout_thread.start()
    stderr_thread.start()

    was_timeout = False
    try:
        process.wait(timeout=spec.timeout)
    except subprocess.TimeoutExpired:
        was_timeout = True
        process.kill()
        stdout_thread.join(timeout=1)
        stderr_thread.join(timeout=1)
        _close_files()
        duration = time.time() - start
        result = CommandResult(
            exit_code=-1,
            duration_s=duration,
            stdout_path=str(stdout_file) if stdout_file else None,
            stderr_path=str(stderr_file) if stderr_file else None,
            was_timeout=True,
        )
        raise CommandExecutionError(
            f"{spec.name} exceeded timeout of {spec.timeout}s", result
        )

    stdout_thread.join()
    stderr_thread.join()
    exit_code = process.returncode
    duration = time.time() - start
    _close_files()

    result = CommandResult(
        exit_code=exit_code,
        duration_s=duration,
        stdout_path=str(stdout_file) if stdout_file else None,
        stderr_path=str(stderr_file) if stderr_file else None,
        was_timeout=was_timeout,
    )

    if exit_code != 0:
        cmd_str = " ".join(shlex.quote(part) for part in spec.cmd)
        raise CommandExecutionError(
            f"{spec.name} failed with exit code {exit_code}: {cmd_str}", result
        )

    return result


__all__ = [
    "CommandSpec",
    "CommandResult",
    "CommandExecutionError",
    "run_command",
]
