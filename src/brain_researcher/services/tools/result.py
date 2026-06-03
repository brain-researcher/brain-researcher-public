"""Standard result types for unified tools.

This module provides consistent result types used across all tools.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class ToolResult(BaseModel):
    """Standard result returned by all tools.

    Attributes:
        status: "success" or "error"
        data: Result data (tool-specific structure)
        error: Error message if status is "error"
        metadata: Optional metadata (execution time, provenance, etc.)

    Example:
        >>> result = ToolResult(status="success", data={"output_file": "/tmp/out.nii"})
        >>> result = ToolResult(status="error", error="File not found")
    """

    status: Literal["success", "error"]
    data: dict[str, Any] | None = None
    error: str | None = None
    metadata: dict[str, Any] | None = None

    model_config = {"extra": "allow"}


class ExecutionResult(BaseModel):
    """Result from containerized or subprocess execution.

    Attributes:
        exit_code: Process exit code (0 = success)
        stdout: Standard output
        stderr: Standard error
        command: Command that was executed
        execution_time: Time in seconds
        mode: Execution mode (container, subprocess, etc.)
        artifact_path: Path to execution artifacts
        run_dir: Working directory for the run
        provenance: Version/container resolution info
    """

    exit_code: int
    stdout: str = ""
    stderr: str = ""
    command: str = ""
    execution_time: float = 0.0
    mode: str = "unknown"
    artifact_path: str | None = None
    run_dir: str | None = None
    provenance: dict[str, Any] | None = None

    model_config = {"extra": "allow"}


__all__ = ["ToolResult", "ExecutionResult"]
