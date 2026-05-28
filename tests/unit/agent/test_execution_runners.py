"""Unit tests for the command execution helpers."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List

import pytest

from brain_researcher.services.agent.execution import (
    CommandExecutionError,
    CommandSpec,
    run_command,
)


def _collecting_callback(events: List[Dict[str, str]]):
    """Return a callback that appends emitted events."""

    def _inner(event: Dict[str, str]) -> None:
        events.append(event)

    return _inner


def test_run_command_success(tmp_path: Path) -> None:
    """run_command executes the process and captures streams."""
    stdout_path = tmp_path / "stdout.log"
    stderr_path = tmp_path / "stderr.log"
    events: List[Dict[str, str]] = []

    spec = CommandSpec(
        cmd=[
            sys.executable,
            "-c",
            'import sys; print("hello from stdout"); sys.stderr.write("warn\\n")',
        ],
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        name="echo",
    )

    result = run_command(spec, progress_callback=_collecting_callback(events))

    assert result.exit_code == 0
    assert result.stdout_path == str(stdout_path)
    assert result.stderr_path == str(stderr_path)
    assert "hello from stdout" in stdout_path.read_text()
    assert "warn" in stderr_path.read_text()

    stdout_lines = [
        ev["line"].strip()
        for ev in events
        if ev.get("stream") == "stdout" and "line" in ev
    ]
    stderr_lines = [
        ev["line"].strip()
        for ev in events
        if ev.get("stream") == "stderr" and "line" in ev
    ]
    assert "hello from stdout" in stdout_lines
    assert "warn" in stderr_lines


def test_run_command_non_zero_exit(tmp_path: Path) -> None:
    """run_command raises CommandExecutionError on non-zero exit."""
    stdout_path = tmp_path / "stdout.log"
    stderr_path = tmp_path / "stderr.log"

    spec = CommandSpec(
        cmd=[sys.executable, "-c", "import sys; sys.stderr.write('boom\\n'); sys.exit(3)"],
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        name="fail",
    )

    with pytest.raises(CommandExecutionError) as excinfo:
        run_command(spec)

    error = excinfo.value
    assert error.result is not None
    assert error.result.exit_code == 3
    assert "boom" in stderr_path.read_text()
    assert not stdout_path.exists() or stdout_path.read_text() == ""


def test_run_command_timeout(tmp_path: Path) -> None:
    """run_command terminates processes that exceed timeout."""
    stdout_path = tmp_path / "stdout.log"
    stderr_path = tmp_path / "stderr.log"

    spec = CommandSpec(
        cmd=[sys.executable, "-c", "import time; time.sleep(2)"],
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        name="sleep",
        timeout=1,  # seconds
    )

    with pytest.raises(CommandExecutionError) as excinfo:
        run_command(spec)

    result = excinfo.value.result
    assert result is not None
    assert result.was_timeout is True
    assert result.exit_code == -1
    # Stderr may contain timeout notice or be empty; ensure files exist for completeness.
    assert stdout_path.exists()
    assert stderr_path.exists()

