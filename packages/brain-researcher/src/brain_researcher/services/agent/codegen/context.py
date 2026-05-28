"""Shared data structures for the coding agent subgraph.

These types are intentionally lightweight and free of LangGraph dependencies
so they can be reused by the tool wrapper and unit tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class FileSnippet:
    """Lightweight code excerpt paired with source metadata."""

    path: str
    snippet: str
    language: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None


@dataclass
class CodegenContext:
    """Aggregated context passed into the prompt builder / codegen loop."""

    user_query: str
    instruction: str
    code_context: Optional[str] = None
    plan_steps: Optional[List[Dict[str, Any]]] = None
    pipeline_context: Optional[Dict[str, Any]] = None
    datasets: Optional[List[str]] = None
    kg_info: Optional[str] = None
    tool_outputs: Optional[List[Dict[str, Any]]] = None
    file_paths: Optional[List[str]] = None
    # Preferred structured snippets. Keep legacy dict for backward compat.
    files: Optional[List[FileSnippet]] = None
    file_snippets: Optional[Dict[str, str]] = None
    error_trace: Optional[str] = None
    prior_errors: Optional[List[str]] = None
    iteration: int = 0
    constraints: Optional[Dict[str, Any]] = None
    test_command: Optional[str] = None
    model_hint: Optional[str] = None
    provider_lock: Optional[str] = None
    ctx_tokens: Optional[int] = None
    budget_id: Optional[str] = None
    credential_name: Optional[str] = None
    repo_root: Optional[str] = None


@dataclass
class ExecutionResult:
    """Result returned by the local execution sandbox."""

    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    duration_ms: Optional[int] = None


@dataclass
class CodegenResult:
    """Final structured outcome of the codegen loop."""

    status: str
    iterations: int
    response_text: str
    patches: List[str] = field(default_factory=list)
    files_touched: List[str] = field(default_factory=list)
    exec_result: Optional[ExecutionResult] = None
    errors: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    usage: Dict[str, Any] = field(default_factory=dict)
    fallback_reason: Optional[str] = None
