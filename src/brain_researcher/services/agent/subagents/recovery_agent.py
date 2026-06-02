"""Recovery helper agent for conservative fallback recommendations."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Sequence

from .contracts import RecoveryProposal


class RecoveryAgent:
    """Generate low-risk recovery suggestions from failure context."""

    def propose(
        self,
        *,
        taxonomy_category: str,
        policy_action: str,
        fallback_tools: Sequence[str] | None,
        adjusted_params: Dict[str, Any] | None,
        failed_tools: Iterable[str] | None = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> RecoveryProposal:
        failed = set(failed_tools or [])
        clean_fallbacks = [
            tool for tool in (fallback_tools or []) if tool and tool not in failed
        ]

        if adjusted_params:
            return RecoveryProposal(
                action_type="retry",
                confidence=0.78,
                reason="retry_with_adjusted_params",
                adjusted_params=dict(adjusted_params),
                fallback_tools=clean_fallbacks,
            )

        if clean_fallbacks:
            return RecoveryProposal(
                action_type="fallback_tool",
                confidence=0.82,
                reason="switch_to_fallback_tool",
                fallback_tools=clean_fallbacks,
            )

        category = (taxonomy_category or "").strip().lower()
        if category in {"data", "user_input", "concept"}:
            return RecoveryProposal(
                action_type="ask_user",
                confidence=0.86,
                reason="needs_user_clarification",
            )
        if category in {"infra", "tool", "stats"}:
            return RecoveryProposal(
                action_type="retry",
                confidence=0.64,
                reason="transient_or_recoverable_failure",
            )

        # Keep parity with existing policy naming when unsure.
        if policy_action in {"retry_backoff", "tool_substitute"}:
            mapped = "retry" if policy_action == "retry_backoff" else "fallback_tool"
            return RecoveryProposal(
                action_type=mapped,  # type: ignore[arg-type]
                confidence=0.51,
                reason="align_with_policy_action",
            )

        return RecoveryProposal(
            action_type="degrade_mode",
            confidence=0.45,
            reason="default_safe_degrade",
        )
