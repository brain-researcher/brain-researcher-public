"""Standard result types for unified tools.

This module provides consistent result types used across all tools.
"""
from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


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
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

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
    artifact_path: Optional[str] = None
    run_dir: Optional[str] = None
    provenance: Optional[Dict[str, Any]] = None

    model_config = {"extra": "allow"}


__all__ = ["ToolResult", "ExecutionResult"]
