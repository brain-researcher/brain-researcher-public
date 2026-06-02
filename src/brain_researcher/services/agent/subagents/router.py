"""Feature-flagged router for lightweight multi-agent cooperation."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Iterable, Optional, Sequence

from .contracts import CriticVerdict, RecoveryProposal
from .critic_agent import CriticAgent
from .recovery_agent import RecoveryAgent

logger = logging.getLogger(__name__)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class MultiAgentRouter:
    """Coordinates critic/recovery helpers under strict feature flags."""

    def __init__(
        self,
        *,
        enabled: bool,
        critic_plan_gate: bool,
        critic_tool_gate: bool,
        recovery_agent_enabled: bool,
        critic_fail_open: bool = True,
    ) -> None:
        self.enabled = enabled
        self.critic_plan_gate = critic_plan_gate
        self.critic_tool_gate = critic_tool_gate
        self.recovery_agent_enabled = recovery_agent_enabled
        self.critic_fail_open = critic_fail_open
        self._critic = CriticAgent()
        self._recovery = RecoveryAgent()

    @classmethod
    def from_env(cls) -> "MultiAgentRouter":
        enabled = _env_flag("BR_AGENT_MULTIAGENT_ENABLED", False)
        return cls(
            enabled=enabled,
            critic_plan_gate=_env_flag("BR_AGENT_CRITIC_PLAN_GATE", False),
            critic_tool_gate=_env_flag("BR_AGENT_CRITIC_TOOL_GATE", False),
            recovery_agent_enabled=_env_flag("BR_AGENT_RECOVERY_AGENT", False),
            critic_fail_open=_env_flag("BR_AGENT_CRITIC_FAIL_OPEN", True),
        )

    def _disabled_verdict(self, reason: str) -> CriticVerdict:
        return CriticVerdict(
            decision="approve",
            risk_level="low",
            reason=reason,
        )

    def review_plan(
        self,
        *,
        plan: Dict[str, Any],
        user_msg: str,
        structured_ctx: str,
        context: Optional[Dict[str, Any]],
        tool_candidates: Optional[Iterable[Dict[str, Any]]],
    ) -> CriticVerdict:
        if not (self.enabled and self.critic_plan_gate):
            return self._disabled_verdict("critic_plan_gate_disabled")
        try:
            return self._critic.review_plan(
                plan=plan,
                user_msg=user_msg,
                structured_ctx=structured_ctx,
                context=context,
                tool_candidates=tool_candidates,
            )
        except Exception as exc:
            logger.warning("Plan critic failed: %s", exc)
            if self.critic_fail_open:
                return self._disabled_verdict("critic_plan_fail_open")
            return CriticVerdict(
                decision="block",
                risk_level="high",
                reason=f"critic_plan_failure:{type(exc).__name__}",
            )

    def review_tool_call(
        self,
        *,
        tool_name: str,
        params: Dict[str, Any] | Any,
        context: Optional[Dict[str, Any]],
        tool_metadata: Optional[Dict[str, Any]],
    ) -> CriticVerdict:
        if not (self.enabled and self.critic_tool_gate):
            return self._disabled_verdict("critic_tool_gate_disabled")
        try:
            return self._critic.review_tool_call(
                tool_name=tool_name,
                params=params,
                context=context,
                tool_metadata=tool_metadata,
            )
        except Exception as exc:
            logger.warning("Tool critic failed: %s", exc)
            if self.critic_fail_open:
                return self._disabled_verdict("critic_tool_fail_open")
            return CriticVerdict(
                decision="block",
                risk_level="high",
                reason=f"critic_tool_failure:{type(exc).__name__}",
            )

    def propose_recovery(
        self,
        *,
        taxonomy_category: str,
        policy_action: str,
        fallback_tools: Sequence[str] | None,
        adjusted_params: Dict[str, Any] | None,
        failed_tools: Iterable[str] | None = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[RecoveryProposal]:
        if not (self.enabled and self.recovery_agent_enabled):
            return None
        try:
            return self._recovery.propose(
                taxonomy_category=taxonomy_category,
                policy_action=policy_action,
                fallback_tools=fallback_tools,
                adjusted_params=adjusted_params,
                failed_tools=failed_tools,
                context=context,
            )
        except Exception as exc:
            logger.warning("Recovery agent failed: %s", exc)
            return None
