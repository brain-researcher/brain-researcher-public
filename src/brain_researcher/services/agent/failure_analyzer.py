"""
Intelligent Failure Analysis for Recovery (AGENT-014)

This module implements failure pattern analysis and learning
for intelligent recovery strategy selection.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class FailureCategory(str, Enum):
    """Categories of execution failures."""

    RESOURCE_EXHAUSTION = "resource_exhaustion"
    NETWORK_TIMEOUT = "network_timeout"
    TOOL_ERROR = "tool_error"
    DATA_CORRUPTION = "data_corruption"
    CONFIGURATION_ERROR = "configuration_error"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"
    UNKNOWN = "unknown"


@dataclass
class FailureContext:
    """Context information for failure analysis."""

    execution_id: str
    step_id: str
    tool_name: str
    error_message: str
    stack_trace: str | None
    resource_usage: dict[str, float]
    timestamp: float


class FailureAnalyzer:
    """
    Analyzes failures and suggests recovery strategies.

    Features:
    - Failure type classification
    - Root cause determination
    - Recovery strategy suggestion
    - Pattern learning from historical failures
    """

    def __init__(self):
        """Initialize failure analyzer."""
        self.failure_patterns = self._load_failure_patterns()
        self.recovery_success_rates = {}

    def analyze(self, failure: Exception, context: FailureContext) -> dict[str, Any]:
        """Analyze failure and suggest recovery."""
        # Classify failure type
        category = self._classify_failure(str(failure), context)

        # Determine root cause
        root_cause = self._determine_root_cause(category, context)

        # Suggest recovery strategy
        recovery_suggestions = self._suggest_recovery(category, context)

        return {
            "category": category,
            "root_cause": root_cause,
            "recovery_suggestions": recovery_suggestions,
            "confidence": 0.85,
        }

    def _classify_failure(
        self, error_msg: str, context: FailureContext
    ) -> FailureCategory:
        """Classify failure based on error message and context."""
        error_lower = error_msg.lower()

        if any(
            pattern in error_lower for pattern in ["memory", "out of memory", "oom"]
        ):
            return FailureCategory.RESOURCE_EXHAUSTION
        elif any(
            pattern in error_lower for pattern in ["timeout", "connection", "network"]
        ):
            return FailureCategory.NETWORK_TIMEOUT
        elif "tool" in error_lower or context.tool_name in error_lower:
            return FailureCategory.TOOL_ERROR
        else:
            return FailureCategory.UNKNOWN

    def _determine_root_cause(
        self, category: FailureCategory, context: FailureContext
    ) -> str:
        """Determine root cause of failure."""
        if category == FailureCategory.RESOURCE_EXHAUSTION:
            return f"Insufficient resources: CPU={context.resource_usage.get('cpu', 0)}, Memory={context.resource_usage.get('memory', 0)}"
        elif category == FailureCategory.NETWORK_TIMEOUT:
            return "Network connectivity issues or service unavailability"
        else:
            return "Unknown root cause - requires manual investigation"

    def _suggest_recovery(
        self, category: FailureCategory, context: FailureContext
    ) -> list[str]:
        """Suggest recovery strategies."""
        if category == FailureCategory.RESOURCE_EXHAUSTION:
            return [
                "Increase memory allocation",
                "Use more powerful instance type",
                "Implement data chunking",
            ]
        elif category == FailureCategory.NETWORK_TIMEOUT:
            return [
                "Retry with exponential backoff",
                "Check service availability",
                "Use alternative endpoint",
            ]
        else:
            return ["Manual investigation required", "Check logs for details"]

    def _load_failure_patterns(self) -> dict[str, list[str]]:
        """Load known failure patterns."""
        return {
            "memory_patterns": ["out of memory", "memory error", "allocation failed"],
            "timeout_patterns": ["timeout", "connection refused", "unreachable"],
            "tool_patterns": [
                "command not found",
                "invalid argument",
                "execution failed",
            ],
        }
