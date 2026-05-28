"""Hard guardrails (P0) for agent tool calling.

This module implements a single, mandatory preflight gate for tool calls.
It is intentionally small: P0 focuses on enforceable allowlists/budget flags
and emitting structured violations for UI/benchmark consumption.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from brain_researcher.core.contracts.violation import Violation, ViolationLocation


def _is_networky_tool(tool_id: str) -> bool:
    tool = (tool_id or "").lower()
    tokens = (
        "http",
        "https",
        "web",
        "browser",
        "crawl",
        "download",
        "fetch",
        "scrape",
        "search",
    )
    return any(tok in tool for tok in tokens)


class GuardrailsSnapshotV1(BaseModel):
    schema_version: Literal["guardrails-snapshot-v1"] = "guardrails-snapshot-v1"

    frozen: bool = False
    no_network: bool = False

    budget_ms: int | None = None
    tool_allowlist: list[str] | None = None

    policy_id: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class GuardrailsDecisionV1(BaseModel):
    schema_version: Literal["guardrails-decision-v1"] = "guardrails-decision-v1"

    allowed: bool
    violations: list[Violation] = Field(default_factory=list)
    snapshot: GuardrailsSnapshotV1


class GuardrailsV1:
    """P0 guardrails: allowlist + frozen/no-network gates."""

    def __init__(self, snapshot: GuardrailsSnapshotV1):
        self.snapshot = snapshot

    def check_tool_call(self, tool_id: str, *, step_id: str | None = None) -> GuardrailsDecisionV1:
        violations: list[Violation] = []

        allowlist = self.snapshot.tool_allowlist
        if allowlist is not None and allowlist and tool_id not in allowlist:
            violations.append(
                Violation(
                    code="TOOL_NOT_ALLOWED",
                    message="Tool is not permitted by the active allowlist",
                    severity="error",
                    blocking=True,
                    where=ViolationLocation(
                        component="agent",
                        stage="preflight",
                        step_id=step_id,
                    ),
                    details={
                        "tool_id": tool_id,
                        "allowlist_size": len(allowlist),
                    },
                )
            )

        if (self.snapshot.no_network or self.snapshot.frozen) and _is_networky_tool(tool_id):
            violations.append(
                Violation(
                    code="NETWORK_DISABLED",
                    message="Network access is disabled for this run",
                    severity="error",
                    blocking=True,
                    where=ViolationLocation(
                        component="agent",
                        stage="preflight",
                        step_id=step_id,
                    ),
                    details={
                        "tool_id": tool_id,
                        "no_network": self.snapshot.no_network,
                        "frozen": self.snapshot.frozen,
                    },
                    suggested_fix="Run without frozen/no_network or use an offline tool.",
                )
            )

        allowed = not any(v.blocking for v in violations)
        return GuardrailsDecisionV1(
            allowed=allowed,
            violations=violations,
            snapshot=self.snapshot,
        )


__all__ = ["GuardrailsV1", "GuardrailsSnapshotV1", "GuardrailsDecisionV1"]

