"""Heuristic critic for low-risk multi-agent robustness checks.

The critic is conservative by design: only block when policy constraints are
clear, and only revise when a deterministic patch is available.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from .contracts import CriticIssue, CriticVerdict


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


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


class CriticAgent:
    """Review plans and tool calls before execution."""

    def review_plan(
        self,
        *,
        plan: Dict[str, Any],
        user_msg: str = "",
        structured_ctx: str = "",
        context: Optional[Dict[str, Any]] = None,
        tool_candidates: Optional[Iterable[Dict[str, Any]]] = None,
    ) -> CriticVerdict:
        tool = str(plan.get("leaf_runtime_id") or plan.get("tool") or "no_tool")
        params = plan.get("params")

        if tool == "no_tool":
            return CriticVerdict(
                decision="approve",
                risk_level="low",
                reason="no_tool_plan",
            )

        if not isinstance(params, dict):
            issue = CriticIssue(
                code="INVALID_PARAMS",
                message="Plan params must be a JSON object.",
                severity="medium",
                field="params",
            )
            return CriticVerdict(
                decision="revise",
                risk_level="medium",
                issues=[issue],
                suggested_patch={"params": {}},
                reason="normalize_plan_params",
            )

        context_dict = context if isinstance(context, dict) else {}
        no_network = _is_truthy(context_dict.get("no_network"))
        frozen = _is_truthy(context_dict.get("frozen"))
        if (no_network or frozen) and _is_networky_tool(tool):
            issue = CriticIssue(
                code="NETWORK_DISABLED",
                message="Network access is disabled for this run.",
                severity="high",
                field="tool",
            )
            return CriticVerdict(
                decision="block",
                risk_level="high",
                issues=[issue],
                reason="network_disabled",
            )

        allowlist = context_dict.get("tool_allowlist")
        if isinstance(allowlist, list) and allowlist and tool not in allowlist:
            issue = CriticIssue(
                code="TOOL_NOT_ALLOWLISTED",
                message="Tool is outside the active allowlist.",
                severity="high",
                field="tool",
            )
            return CriticVerdict(
                decision="block",
                risk_level="high",
                issues=[issue],
                reason="allowlist_block",
            )

        # Keep "dangerous" checks advisory to avoid unnecessary behavior change.
        candidate_map: Dict[str, Dict[str, Any]] = {}
        for candidate in tool_candidates or []:
            if isinstance(candidate, dict) and candidate.get("id"):
                candidate_map[str(candidate["id"])] = candidate
        candidate = candidate_map.get(tool) or candidate_map.get(str(plan.get("tool")))
        if candidate and _is_truthy(candidate.get("dangerous")):
            issue = CriticIssue(
                code="DANGEROUS_TOOL",
                message="Tool is marked dangerous; monitor output carefully.",
                severity="medium",
                field="tool",
            )
            return CriticVerdict(
                decision="approve",
                risk_level="medium",
                issues=[issue],
                reason="advisory_dangerous_tool",
            )

        return CriticVerdict(
            decision="approve",
            risk_level="low",
            reason="plan_ok",
        )

    def review_tool_call(
        self,
        *,
        tool_name: str,
        params: Dict[str, Any] | Any,
        context: Optional[Dict[str, Any]] = None,
        tool_metadata: Optional[Dict[str, Any]] = None,
    ) -> CriticVerdict:
        if not isinstance(params, dict):
            issue = CriticIssue(
                code="INVALID_PARAMS",
                message="Tool parameters must be an object.",
                severity="medium",
                field="params",
            )
            return CriticVerdict(
                decision="revise",
                risk_level="medium",
                issues=[issue],
                suggested_patch={"params": {}},
                reason="normalize_tool_params",
            )

        context_dict = context if isinstance(context, dict) else {}
        no_network = _is_truthy(context_dict.get("no_network"))
        frozen = _is_truthy(context_dict.get("frozen"))
        if (no_network or frozen) and _is_networky_tool(tool_name):
            issue = CriticIssue(
                code="NETWORK_DISABLED",
                message="Network access is disabled for this run.",
                severity="high",
                field="tool",
            )
            return CriticVerdict(
                decision="block",
                risk_level="high",
                issues=[issue],
                reason="network_disabled",
            )

        allowlist = context_dict.get("tool_allowlist")
        if isinstance(allowlist, list) and allowlist and tool_name not in allowlist:
            issue = CriticIssue(
                code="TOOL_NOT_ALLOWLISTED",
                message="Tool is outside the active allowlist.",
                severity="high",
                field="tool",
            )
            return CriticVerdict(
                decision="block",
                risk_level="high",
                issues=[issue],
                reason="allowlist_block",
            )

        if isinstance(tool_metadata, dict) and _is_truthy(tool_metadata.get("dangerous")):
            issue = CriticIssue(
                code="DANGEROUS_TOOL",
                message="Dangerous tool execution should be audited.",
                severity="medium",
                field="tool",
            )
            return CriticVerdict(
                decision="approve",
                risk_level="medium",
                issues=[issue],
                reason="advisory_dangerous_tool",
            )

        return CriticVerdict(
            decision="approve",
            risk_level="low",
            reason="tool_call_ok",
        )
