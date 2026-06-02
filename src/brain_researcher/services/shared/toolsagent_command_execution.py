"""Command execution helpers for long-running neuroimaging tools.

This module provides a light abstraction for running shell commands with
streamed logging, filesystem bindings, and timeout handling, plus a
``JobLogEmitter`` that posts log lines to the orchestrator's job log endpoint.
It is intentionally minimal so it can be reused both in the CLI (brainr) and
orchestrator jobs.

Relocated from ``services/agent/execution`` (``runners`` + ``logging``) into the
shared layer so that the lower ``services/tools`` layer (e.g. fmriprep_tool) can
depend on these primitives without a tools -> agent back-edge. The original
``services/agent/execution`` submodules re-export everything here for callers.
"""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


DatastreamCallback = Callable[[dict[str, str]], None]


@dataclass
class CommandSpec:
    """Specification for launching a command."""

    cmd: list[str]
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    timeout: int | None = None  # seconds
    stdout_path: str | None = None
    stderr_path: str | None = None
    name: str = "command"


@dataclass
class CommandResult:
    """Result metadata for an executed command."""

    exit_code: int
    duration_s: float
    stdout_path: str | None
    stderr_path: str | None
    was_timeout: bool = False


class CommandExecutionError(RuntimeError):
    """Raised when command execution fails."""

    def __init__(self, message: str, result: CommandResult | None = None):
        super().__init__(message)
        self.result = result


def _ensure_parent(path: str | None) -> Path | None:
    if not path:
        return None
    dest = Path(path).expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest


def run_command(
    spec: CommandSpec,
    *,
    progress_callback: DatastreamCallback | None = None,
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


class JobLogEmitter:
    """Send command output lines to the orchestrator job log endpoint."""

    def __init__(
        self,
        base_url: str | None,
        job_id: str | None,
        *,
        step_id: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 1.5,
    ) -> None:
        base_url = (base_url or "").strip()
        self._base_url = base_url.rstrip("/") if base_url else None
        self._job_id = job_id
        self._step_id = step_id
        self._timeout = timeout
        self._lock = threading.Lock()
        self._sequence = 0
        self._active = bool(self._base_url and self._job_id)
        self._client = client or (
            httpx.Client(timeout=self._timeout) if self._active else None
        )
        self._owns_client = client is None and self._client is not None

    @property
    def enabled(self) -> bool:
        return self._active

    @classmethod
    def from_env(
        cls, job_id: str | None, *, step_id: str | None = None
    ) -> JobLogEmitter:
        """Build an emitter using environment defaults."""
        orchestrator_url = os.environ.get("ORCHESTRATOR_URL")
        return cls(orchestrator_url, job_id, step_id=step_id)

    def emit(self, message: str, *, stream: str = "stdout") -> None:
        """Emit a single log line to the orchestrator."""
        if not self._active or self._client is None:
            return

        text = (message or "").rstrip()
        if not text:
            return
        if len(text) > 2000:
            text = text[-2000:]

        with self._lock:
            self._sequence += 1
            sequence = self._sequence

        payload = {
            "message": text,
            "stream": stream,
            "sequence": sequence,
            "step_id": self._step_id,
            "timestamp": datetime.utcnow().isoformat(),
        }

        try:
            self._client.post(
                f"{self._base_url}/jobs/{self._job_id}/logs",
                json=payload,
                timeout=self._timeout,
            )
        except Exception as exc:  # pragma: no cover - telemetry best-effort
            logger.debug("Failed to emit job log: %s", exc)

    def close(self) -> None:
        """Close the underlying HTTP client if we own it."""
        if self._owns_client and self._client is not None:
            try:
                self._client.close()
            except Exception as exc:  # pragma: no cover - cleanup best-effort
                logger.debug("Failed to close log emitter client: %s", exc)

    def __enter__(self) -> JobLogEmitter:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


__all__ = [
    "CommandSpec",
    "CommandResult",
    "CommandExecutionError",
    "run_command",
    "JobLogEmitter",
]
