"""Shared data structures for the coding agent subgraph.

These types are intentionally lightweight and free of LangGraph dependencies
so they can be reused by the tool wrapper and unit tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FileSnippet:
    """Lightweight code excerpt paired with source metadata."""

    path: str
    snippet: str
    language: str | None = None
    start_line: int | None = None
    end_line: int | None = None


@dataclass
class CodegenContext:
    """Aggregated context passed into the prompt builder / codegen loop."""

    user_query: str
    instruction: str
    code_context: str | None = None
    plan_steps: list[dict[str, Any]] | None = None
    pipeline_context: dict[str, Any] | None = None
    datasets: list[str] | None = None
    kg_info: str | None = None
    tool_outputs: list[dict[str, Any]] | None = None
    file_paths: list[str] | None = None
    # Preferred structured snippets. Keep legacy dict for backward compat.
    files: list[FileSnippet] | None = None
    file_snippets: dict[str, str] | None = None
    error_trace: str | None = None
    prior_errors: list[str] | None = None
    iteration: int = 0
    constraints: dict[str, Any] | None = None
    test_command: str | None = None
    model_hint: str | None = None
    provider_lock: str | None = None
    ctx_tokens: int | None = None
    budget_id: str | None = None
    credential_name: str | None = None
    repo_root: str | None = None


@dataclass
class ExecutionResult:
    """Result returned by the local execution sandbox."""

    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    duration_ms: int | None = None


@dataclass
class CodegenResult:
    """Final structured outcome of the codegen loop."""

    status: str
    iterations: int
    response_text: str
    patches: list[str] = field(default_factory=list)
    files_touched: list[str] = field(default_factory=list)
    exec_result: ExecutionResult | None = None
    errors: str | None = None
    provider: str | None = None
    model: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    fallback_reason: str | None = None
