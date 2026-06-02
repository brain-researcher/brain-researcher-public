"""
Tool execution data models for the Brain Researcher Agent.

Defines the enumerations, request/response dataclasses, and shared constants
used throughout the tool execution pipeline:

  - ExecutionMode   – how a tool is dispatched (command-gen, direct, API, batch)
  - ExecutionBackend – physical backend (container, python, api)
  - ToolCategory    – domain bucket for strategy selection
  - ToolExecutionRequest – typed input to ToolExecutor.execute()
  - ToolExecutionResult  – typed output from ToolExecutor.execute()
  - _env_flag, _OUTPUT_PATH_PARAM_KEYS, _MAX_DISCOVERED_OUTPUT_FILES – helpers
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Union
from uuid import uuid4

from brain_researcher.services.agent.resources.resource_manager import Priority
from brain_researcher.services.tools.neurodesk_tools import NEURODESK_TOOLS
from brain_researcher.services.tools.tool_base import ToolResult

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_OUTPUT_PATH_PARAM_KEYS = {
    "output_dir",
    "out_dir",
    "result_dir",
    "results_dir",
    "output_file",
    "out_file",
    "output_csv",
    "output_tsv",
    "output_json",
    "output_html",
    "output_pdf",
    "report_file",
    "report_path",
    "figure_file",
    "figure_path",
    "qc_tsv",
}
_MAX_DISCOVERED_OUTPUT_FILES = 256


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ExecutionMode(Enum):
    """Tool execution modes."""

    COMMAND_GENERATION = "command_generation"  # Generate commands for user execution
    DIRECT_EXECUTION = "direct_execution"  # Execute directly via subprocess
    API_CALL = "api_call"  # API/service calls
    BATCH = "batch"  # Batch processing


class ExecutionBackend(Enum):
    """Physical backend that will execute the tool."""

    CONTAINER = "container"
    PYTHON = "python"
    API = "api"


class ToolCategory(Enum):
    """Tool categories for execution strategy."""

    NEUROIMAGING = "neuroimaging"  # FSL, SPM, MRtrix3, etc.
    DATA_PROCESSING = "data_processing"  # Safe data operations
    API_SERVICE = "api_service"  # API calls
    ANALYSIS = "analysis"  # Statistical analysis
    KNOWLEDGE_GRAPH = "knowledge_graph"  # BR-KG operations


# ---------------------------------------------------------------------------
# Request / Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ToolExecutionRequest:
    """Request for tool execution."""

    tool_name: str
    parameters: dict[str, Any]
    mode: ExecutionMode | None = None  # Auto-detect if not specified
    category: ToolCategory | None = None  # Auto-detect if not specified
    priority: Priority = Priority.NORMAL
    timeout: float | None = None
    execution_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    callback: Callable | None = None
    retry_on_failure: bool = True
    max_retries: int = 3
    execute_directly: bool = False  # Force direct execution (use with caution)
    runtime_kind: str | None = (
        None  # container | python | api (mcp/external_api aliases supported)
    )

    def __post_init__(self):
        """Generate execution ID and auto-detect mode/category if needed."""
        if not self.execution_id:
            self.execution_id = f"exec_{uuid4().hex[:8]}"

        # Auto-detect category based on tool name
        if not self.category:
            self.category = self._detect_category()

        # Auto-detect mode based on category
        if not self.mode:
            self.mode = self._detect_mode()

    def _detect_category(self) -> ToolCategory:
        """Detect tool category from tool name."""
        tool_lower = self.tool_name.lower()

        # Check if it's a neuroimaging tool
        if any(name in tool_lower for name in NEURODESK_TOOLS.keys()):
            return ToolCategory.NEUROIMAGING

        # Check for specific tool patterns
        if "command" in tool_lower or "neurodesk" in tool_lower:
            return ToolCategory.NEUROIMAGING
        elif (
            "glm" in tool_lower or "encoding" in tool_lower or "contrast" in tool_lower
        ):
            return ToolCategory.ANALYSIS
        elif (
            "graph" in tool_lower
            or "concept" in tool_lower
            or "coordinate" in tool_lower
        ):
            return ToolCategory.KNOWLEDGE_GRAPH
        elif "api" in tool_lower or "fetch" in tool_lower or "query" in tool_lower:
            return ToolCategory.API_SERVICE
        else:
            return ToolCategory.DATA_PROCESSING

    def _detect_mode(self) -> ExecutionMode:
        """Detect execution mode based on category."""
        if self.execute_directly:
            return ExecutionMode.DIRECT_EXECUTION

        # Neuroimaging tools should generate commands
        if self.category == ToolCategory.NEUROIMAGING:
            return ExecutionMode.COMMAND_GENERATION

        # API and KG operations can execute directly
        elif self.category in [ToolCategory.API_SERVICE, ToolCategory.KNOWLEDGE_GRAPH]:
            return ExecutionMode.API_CALL

        # Analysis tools depend on implementation
        elif self.category == ToolCategory.ANALYSIS:
            # If tool returns commands, use command generation
            if "command" in self.tool_name.lower():
                return ExecutionMode.COMMAND_GENERATION
            else:
                return ExecutionMode.API_CALL

        # Default to API call for safety
        else:
            return ExecutionMode.API_CALL


@dataclass
class ToolExecutionResult:
    """Result of tool execution."""

    execution_id: str
    tool_name: str
    status: str  # success, error, timeout, cancelled
    result: Union[ToolResult, dict[str, Any]] | None = None
    command: str | None = None  # Generated command if applicable
    error: str | None = None
    execution_time: float = 0.0
    retries: int = 0
    resource_usage: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    # TODO-2: Structured failure taxonomy (durable + UI-friendly)
    error_category: str | None = None  # infra|tool|data|stats|concept|user_input
    is_retryable: bool | None = None
    recovery_strategy: str | None = (
        None  # retry_backoff|tool_substitute|relax_constraint|ask_user|abort
    )
    recovery_suggestions: list[str] = field(default_factory=list)
