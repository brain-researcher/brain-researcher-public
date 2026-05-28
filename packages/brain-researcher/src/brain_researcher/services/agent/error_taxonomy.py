"""Structured failure taxonomy + recovery hints for agent/tool execution.

TODO-2 (Planner State + Confidence + Failure Recovery):
- Provide a durable, low-cardinality error taxonomy for UI + analytics.
- Attach deterministic recovery hints to failures.

This module intentionally stays lightweight and rule-based (no external deps)
so it can be used in unit tests and offline environments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class ErrorTaxonomyCategory(str, Enum):
    """High-level error categories exposed to UI and logs."""

    INFRA = "infra"
    TOOL = "tool"
    DATA = "data"
    STATS = "stats"
    CONCEPT = "concept"
    USER_INPUT = "user_input"


class RecoveryAction(str, Enum):
    """Recommended recovery action (simple + explainable)."""

    RETRY_BACKOFF = "retry_backoff"
    TOOL_SUBSTITUTE = "tool_substitute"
    RELAX_CONSTRAINT = "relax_constraint"
    ASK_USER = "ask_user"
    ABORT = "abort"


@dataclass(frozen=True)
class ErrorTaxonomyResult:
    """Classification output attached to ToolExecutionResult and step results."""

    category: ErrorTaxonomyCategory
    is_retryable: bool
    recovery_action: RecoveryAction
    recovery_suggestions: list[str] = field(default_factory=list)
    debug: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category.value,
            "is_retryable": self.is_retryable,
            "recovery_action": self.recovery_action.value,
            "recovery_suggestions": list(self.recovery_suggestions),
            "debug": dict(self.debug),
        }


_PATTERNS = {
    "timeout": [
        "timeout",
        "timed out",
        "time limit",
        "deadline exceeded",
        "read timed out",
        "connecttimeout",
    ],
    "network": [
        "connection refused",
        "connection reset",
        "network is unreachable",
        "temporary failure",
        "service unavailable",
        "dns",
        "name or service not known",
    ],
    "missing_file": [
        "no such file",
        "file not found",
        "not a directory",
        "does not exist",
    ],
    "invalid_input": [
        "invalid json",
        "missing required",
        "required parameters",
        "validation error",
        "invalid input",
        "bad request",
        "type error",
        "value error",
    ],
    "stats": [
        "singular matrix",
        "non-invertible",
        "nan",
        "inf",
        "convergence",
        "did not converge",
        "rank deficient",
    ],
    "concept": [
        "concept",
        "ontology",
        "term not found",
        "unknown term",
        "no matching concept",
    ],
    "tool_unavailable": [
        "command not found",
        "module not found",
        "not installed",
        "permission denied",
    ],
}


def _contains_any(haystack: str, patterns: list[str]) -> bool:
    h = haystack.lower()
    return any(p in h for p in patterns)


def classify_failure(
    *,
    status: Optional[str] = None,
    error_message: Optional[str] = None,
    exception: Optional[BaseException] = None,
    returncode: Optional[int] = None,
    stderr: Optional[str] = None,
) -> ErrorTaxonomyResult:
    """Classify a failure into a durable taxonomy with recovery hints.

    Inputs are intentionally redundant; callers can provide what they have.
    The mapping is deterministic (rule + pattern based) for testability.
    """

    message = (error_message or "") + "\n" + (stderr or "")
    message = message.strip()
    debug: Dict[str, Any] = {}

    if status:
        debug["status"] = status
    if returncode is not None:
        debug["returncode"] = returncode
    if exception is not None:
        debug["exception_type"] = type(exception).__name__

    # Explicit status first.
    if status in {"cancelled"}:
        return ErrorTaxonomyResult(
            category=ErrorTaxonomyCategory.USER_INPUT,
            is_retryable=False,
            recovery_action=RecoveryAction.ABORT,
            recovery_suggestions=["Execution was cancelled; re-run when ready."],
            debug=debug,
        )

    # Deterministic exit code mapping (portable conventions).
    if returncode in {124}:
        debug["rule"] = "exit_code_124_timeout"
        return ErrorTaxonomyResult(
            category=ErrorTaxonomyCategory.INFRA,
            is_retryable=True,
            recovery_action=RecoveryAction.RETRY_BACKOFF,
            recovery_suggestions=[
                "Retry with exponential backoff.",
                "Increase the tool timeout.",
                "Check system load / queue latency.",
            ],
            debug=debug,
        )
    if returncode in {137}:
        debug["rule"] = "exit_code_137_oom"
        return ErrorTaxonomyResult(
            category=ErrorTaxonomyCategory.INFRA,
            is_retryable=True,
            recovery_action=RecoveryAction.RELAX_CONSTRAINT,
            recovery_suggestions=[
                "Reduce memory usage (smaller batch / fewer threads).",
                "Increase memory allocation if available.",
            ],
            debug=debug,
        )

    # Message-based classification.
    if status == "timeout" or _contains_any(message, _PATTERNS["timeout"]):
        debug["rule"] = "timeout_pattern"
        return ErrorTaxonomyResult(
            category=ErrorTaxonomyCategory.INFRA,
            is_retryable=True,
            recovery_action=RecoveryAction.RETRY_BACKOFF,
            recovery_suggestions=[
                "Retry with exponential backoff.",
                "Increase the tool timeout.",
                "Try a lighter configuration (fewer threads / smaller data).",
            ],
            debug=debug,
        )

    if _contains_any(message, _PATTERNS["network"]):
        debug["rule"] = "network_pattern"
        return ErrorTaxonomyResult(
            category=ErrorTaxonomyCategory.INFRA,
            is_retryable=True,
            recovery_action=RecoveryAction.RETRY_BACKOFF,
            recovery_suggestions=[
                "Retry with exponential backoff.",
                "Check service availability and DNS/network connectivity.",
            ],
            debug=debug,
        )

    if _contains_any(message, _PATTERNS["missing_file"]):
        debug["rule"] = "missing_file_pattern"
        return ErrorTaxonomyResult(
            category=ErrorTaxonomyCategory.DATA,
            is_retryable=False,
            recovery_action=RecoveryAction.ASK_USER,
            recovery_suggestions=[
                "Verify input paths/datasets exist and are mounted.",
                "Provide the missing dataset/file or update inputs.",
            ],
            debug=debug,
        )

    if _contains_any(message, _PATTERNS["invalid_input"]):
        debug["rule"] = "invalid_input_pattern"
        return ErrorTaxonomyResult(
            category=ErrorTaxonomyCategory.USER_INPUT,
            is_retryable=False,
            recovery_action=RecoveryAction.ASK_USER,
            recovery_suggestions=[
                "Fix the input parameters and re-run.",
                "If unsure, ask the user for missing/ambiguous inputs.",
            ],
            debug=debug,
        )

    if _contains_any(message, _PATTERNS["stats"]):
        debug["rule"] = "stats_pattern"
        return ErrorTaxonomyResult(
            category=ErrorTaxonomyCategory.STATS,
            is_retryable=True,
            recovery_action=RecoveryAction.RELAX_CONSTRAINT,
            recovery_suggestions=[
                "Relax statistical constraints (regularization, fewer covariates).",
                "Check for NaNs/infs and data scaling.",
            ],
            debug=debug,
        )

    if _contains_any(message, _PATTERNS["concept"]):
        debug["rule"] = "concept_pattern"
        return ErrorTaxonomyResult(
            category=ErrorTaxonomyCategory.CONCEPT,
            is_retryable=False,
            recovery_action=RecoveryAction.ASK_USER,
            recovery_suggestions=[
                "Clarify the concept/term and provide synonyms or IDs.",
                "Try a broader query or alternate ontology mapping.",
            ],
            debug=debug,
        )

    if _contains_any(message, _PATTERNS["tool_unavailable"]):
        debug["rule"] = "tool_unavailable_pattern"
        return ErrorTaxonomyResult(
            category=ErrorTaxonomyCategory.INFRA,
            is_retryable=True,
            recovery_action=RecoveryAction.TOOL_SUBSTITUTE,
            recovery_suggestions=[
                "Use an alternative tool implementation.",
                "Ensure required dependencies/modules are installed.",
            ],
            debug=debug,
        )

    # Fallback: treat as tool failure (safe default).
    debug["rule"] = "fallback_tool"
    return ErrorTaxonomyResult(
        category=ErrorTaxonomyCategory.TOOL,
        is_retryable=False,
        recovery_action=RecoveryAction.TOOL_SUBSTITUTE,
        recovery_suggestions=[
            "Try an alternative tool implementation.",
            "Inspect stderr/logs for tool-specific failure details.",
        ],
        debug=debug,
    )

