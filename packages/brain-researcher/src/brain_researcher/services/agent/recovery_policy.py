"""Recovery policy helpers for systematic failure->strategy mapping.

Keeps mapping logic centralized and provides a lightweight fallback
tool selection routine for smarter branch switching after failures.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from brain_researcher.config.mapping_resolver import resolve_mapping_path
from brain_researcher.config.paths import resolve_from_config

try:  # Optional dependency; recovery map loading is best-effort.
    import yaml
except Exception:  # pragma: no cover - optional dependency
    yaml = None  # type: ignore

from brain_researcher.services.agent.error_taxonomy import (
    ErrorTaxonomyCategory,
    ErrorTaxonomyResult,
    RecoveryAction,
)

try:  # Optional import; keep module usable without tool router
    from brain_researcher.services.agent.tool_router import ToolRouter
except Exception:  # pragma: no cover - defensive fallback
    ToolRouter = None  # type: ignore

_ROUTER_UNSET = object()
_MULTIAGENT_ROUTER: Any = _ROUTER_UNSET


@dataclass(frozen=True)
class RecoveryPolicy:
    category: ErrorTaxonomyCategory
    action: RecoveryAction
    allow_tool_substitute: bool = False
    allow_param_adjustment: bool = False
    allow_retry: bool = False
    allow_router_suggestions: bool = False


@dataclass
class RecoveryDecision:
    action: RecoveryAction
    reason: str
    fallback_tools: List[str] = field(default_factory=list)
    adjusted_params: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RecoveryMapRule:
    category: ErrorTaxonomyCategory
    action: Optional[RecoveryAction] = None
    allow_tool_substitute: Optional[bool] = None
    allow_param_adjustment: Optional[bool] = None
    allow_retry: Optional[bool] = None
    allow_router_suggestions: Optional[bool] = None
    tool_family: Optional[str] = None
    step_role: Optional[str] = None


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _canonical_runtime_tool_id(tool_id: Any) -> Optional[str]:
    normalized = str(tool_id or "").strip()
    if not normalized:
        return None
    try:
        from brain_researcher.services.tools.catalog_loader import (
            resolve_primary_runtime_tool_id,
        )
    except Exception:
        return normalized
    return resolve_primary_runtime_tool_id(normalized) or normalized


def _get_multiagent_router():
    global _MULTIAGENT_ROUTER
    if _MULTIAGENT_ROUTER is _ROUTER_UNSET:
        try:
            from brain_researcher.services.agent.subagents.router import (
                MultiAgentRouter,
            )

            _MULTIAGENT_ROUTER = MultiAgentRouter.from_env()
        except Exception:
            _MULTIAGENT_ROUTER = None
    return _MULTIAGENT_ROUTER


DEFAULT_POLICIES: Dict[ErrorTaxonomyCategory, RecoveryPolicy] = {
    ErrorTaxonomyCategory.INFRA: RecoveryPolicy(
        category=ErrorTaxonomyCategory.INFRA,
        action=RecoveryAction.RETRY_BACKOFF,
        allow_tool_substitute=True,
        allow_param_adjustment=True,
        allow_retry=True,
        allow_router_suggestions=True,
    ),
    ErrorTaxonomyCategory.TOOL: RecoveryPolicy(
        category=ErrorTaxonomyCategory.TOOL,
        action=RecoveryAction.TOOL_SUBSTITUTE,
        allow_tool_substitute=True,
        allow_param_adjustment=False,
        allow_retry=False,
        allow_router_suggestions=True,
    ),
    ErrorTaxonomyCategory.DATA: RecoveryPolicy(
        category=ErrorTaxonomyCategory.DATA,
        action=RecoveryAction.ASK_USER,
        allow_tool_substitute=False,
        allow_param_adjustment=False,
        allow_retry=False,
        allow_router_suggestions=False,
    ),
    ErrorTaxonomyCategory.STATS: RecoveryPolicy(
        category=ErrorTaxonomyCategory.STATS,
        action=RecoveryAction.RELAX_CONSTRAINT,
        allow_tool_substitute=True,
        allow_param_adjustment=True,
        allow_retry=False,
        allow_router_suggestions=True,
    ),
    ErrorTaxonomyCategory.CONCEPT: RecoveryPolicy(
        category=ErrorTaxonomyCategory.CONCEPT,
        action=RecoveryAction.ASK_USER,
        allow_tool_substitute=False,
        allow_param_adjustment=False,
        allow_retry=False,
        allow_router_suggestions=False,
    ),
    ErrorTaxonomyCategory.USER_INPUT: RecoveryPolicy(
        category=ErrorTaxonomyCategory.USER_INPUT,
        action=RecoveryAction.ASK_USER,
        allow_tool_substitute=False,
        allow_param_adjustment=False,
        allow_retry=False,
        allow_router_suggestions=False,
    ),
}


def _load_recovery_map() -> List[RecoveryMapRule]:
    """Load optional recovery map overrides from YAML (best-effort)."""
    if yaml is None:
        return []
    configured = os.getenv("BR_RECOVERY_MAP_PATH")
    path = resolve_mapping_path(
        "recovery_map",
        requested_path=Path(configured) if configured else None,
        fallback=resolve_from_config("recovery_map.yaml"),
        must_exist=False,
    )
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        return []
    rules: List[RecoveryMapRule] = []
    for raw in data.get("rules", []) or []:
        if not isinstance(raw, dict):
            continue
        try:
            category = ErrorTaxonomyCategory(str(raw.get("category")))
        except Exception:
            continue
        action = raw.get("action")
        try:
            action_val = RecoveryAction(action) if action else None
        except Exception:
            action_val = None
        rules.append(
            RecoveryMapRule(
                category=category,
                action=action_val,
                allow_tool_substitute=raw.get("allow_tool_substitute"),
                allow_param_adjustment=raw.get("allow_param_adjustment"),
                allow_retry=raw.get("allow_retry"),
                allow_router_suggestions=raw.get("allow_router_suggestions"),
                tool_family=raw.get("tool_family"),
                step_role=raw.get("step_role"),
            )
        )
    return rules


def _step_role_from_metadata(metadata: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(metadata, dict):
        return None
    return (
        metadata.get("step_role")
        or metadata.get("role")
        or metadata.get("step_type")
    )


def _tool_family_from_metadata(metadata: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(metadata, dict):
        return None
    return metadata.get("tool_family") or metadata.get("family")


def _match_rule(
    rule: RecoveryMapRule,
    *,
    taxonomy: ErrorTaxonomyResult,
    step_metadata: Optional[Dict[str, Any]],
) -> bool:
    if rule.category != taxonomy.category:
        return False
    if rule.tool_family:
        if rule.tool_family != _tool_family_from_metadata(step_metadata):
            return False
    if rule.step_role:
        if rule.step_role != _step_role_from_metadata(step_metadata):
            return False
    return True


def _resolve_recovery_rule(
    *,
    taxonomy: ErrorTaxonomyResult,
    step_metadata: Optional[Dict[str, Any]],
) -> Optional[RecoveryMapRule]:
    for rule in _load_recovery_map():
        if _match_rule(rule, taxonomy=taxonomy, step_metadata=step_metadata):
            return rule
    return None


def _dedupe_preserve_order(items: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    ordered: List[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _safe_adjust_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """Apply conservative parameter adjustments for recovery."""
    tuned = dict(params or {})
    for key in ("n_jobs", "num_workers", "threads"):
        if key in tuned:
            try:
                tuned[key] = max(1, int(tuned[key] or 1))
            except Exception:
                tuned[key] = 1
    if "batch_size" in tuned:
        try:
            tuned["batch_size"] = max(1, int(tuned["batch_size"] or 1) // 2)
        except Exception:
            tuned["batch_size"] = 1
    if "timeout" in tuned:
        try:
            tuned["timeout"] = int(tuned["timeout"] or 0) * 2 or 600
        except Exception:
            tuned["timeout"] = 600
    if "low_mem" in tuned or os.getenv("BR_RECOVERY_FORCE_LOW_MEM", "").lower() in {"1", "true", "yes"}:
        tuned["low_mem"] = True
    return tuned


def policy_for_taxonomy(
    taxonomy: ErrorTaxonomyResult,
    *,
    step_metadata: Optional[Dict[str, Any]] = None,
) -> RecoveryPolicy:
    base = DEFAULT_POLICIES.get(
        taxonomy.category,
        RecoveryPolicy(
            category=taxonomy.category,
            action=taxonomy.recovery_action,
            allow_tool_substitute=False,
            allow_param_adjustment=False,
            allow_retry=False,
            allow_router_suggestions=False,
        ),
    )
    rule = _resolve_recovery_rule(taxonomy=taxonomy, step_metadata=step_metadata)
    if not rule:
        return RecoveryPolicy(
            category=taxonomy.category,
            action=taxonomy.recovery_action or base.action,
            allow_tool_substitute=base.allow_tool_substitute,
            allow_param_adjustment=base.allow_param_adjustment,
            allow_retry=base.allow_retry,
            allow_router_suggestions=base.allow_router_suggestions,
        )
    return RecoveryPolicy(
        category=taxonomy.category,
        action=rule.action or taxonomy.recovery_action or base.action,
        allow_tool_substitute=(
            rule.allow_tool_substitute
            if rule.allow_tool_substitute is not None
            else base.allow_tool_substitute
        ),
        allow_param_adjustment=(
            rule.allow_param_adjustment
            if rule.allow_param_adjustment is not None
            else base.allow_param_adjustment
        ),
        allow_retry=(
            rule.allow_retry if rule.allow_retry is not None else base.allow_retry
        ),
        allow_router_suggestions=(
            rule.allow_router_suggestions
            if rule.allow_router_suggestions is not None
            else base.allow_router_suggestions
        ),
    )


def select_recovery_decision(
    *,
    taxonomy: ErrorTaxonomyResult,
    tool_id: str,
    step_metadata: Optional[Dict[str, Any]] = None,
    step_idx: int | None = None,
    plan_candidates: Optional[Sequence[Dict[str, Any]]] = None,
    query: Optional[str] = None,
    router: Optional["ToolRouter"] = None,
    failed_tools: Optional[Set[str]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> RecoveryDecision:
    """Select recovery action and fallback tools based on taxonomy + context."""
    policy = policy_for_taxonomy(taxonomy, step_metadata=step_metadata)
    decision = RecoveryDecision(
        action=policy.action,
        reason=f"{taxonomy.category.value}:{policy.action.value}",
    )

    if policy.allow_param_adjustment and params:
        decision.adjusted_params = _safe_adjust_params(params)

    if not policy.allow_tool_substitute:
        return _apply_multiagent_recovery_overlay(
            decision=decision,
            taxonomy=taxonomy,
            policy=policy,
            tool_id=tool_id,
            failed_tools=failed_tools,
            context={"query": query, "step_metadata": step_metadata},
        )

    fallbacks: List[str] = []
    metadata = step_metadata or {}
    if isinstance(metadata, dict):
        if metadata.get("fallback_tool"):
            fallbacks.append(str(metadata.get("fallback_tool")))
        if metadata.get("fallback_tools"):
            fallbacks.extend([str(t) for t in metadata.get("fallback_tools", [])])

    if step_idx == 0 and plan_candidates:
        for cand in plan_candidates:
            cand_tool = cand.get("tool_id") or cand.get("tool")
            if cand_tool:
                fallbacks.append(str(cand_tool))

    if policy.allow_router_suggestions and router and query:
        try:
            limit = int(os.getenv("BR_RECOVERY_ROUTER_LIMIT", "5"))
        except Exception:
            limit = 5
        try:
            candidates = router.get_candidates(query) if limit != 0 else []
        except Exception:
            candidates = []
        for cand in candidates[: max(limit, 0)]:
            if hasattr(cand, "is_family") and cand.is_family():
                continue
            runtime_id = getattr(cand, "runtime_id", None)
            if runtime_id:
                fallbacks.append(str(runtime_id))

    fallbacks = _dedupe_preserve_order(
        [resolved for resolved in (_canonical_runtime_tool_id(tool) for tool in fallbacks) if resolved]
    )
    failed = {
        resolved
        for resolved in (_canonical_runtime_tool_id(tool) for tool in (failed_tools or set()))
        if resolved
    }
    current_tool = _canonical_runtime_tool_id(tool_id) or tool_id
    fallbacks = [t for t in fallbacks if t != current_tool and t not in failed]

    try:
        limit = int(os.getenv("BR_FALLBACK_TOOL_LIMIT", "2"))
    except Exception:
        limit = 2
    if limit > 0:
        fallbacks = fallbacks[:limit]

    decision.fallback_tools = fallbacks
    return _apply_multiagent_recovery_overlay(
        decision=decision,
        taxonomy=taxonomy,
        policy=policy,
        tool_id=tool_id,
        failed_tools=failed_tools,
        context={"query": query, "step_metadata": step_metadata},
    )


def _apply_multiagent_recovery_overlay(
    *,
    decision: RecoveryDecision,
    taxonomy: ErrorTaxonomyResult,
    policy: RecoveryPolicy,
    tool_id: str,
    failed_tools: Optional[Set[str]],
    context: Optional[Dict[str, Any]],
) -> RecoveryDecision:
    if not (
        _env_flag("BR_AGENT_MULTIAGENT_ENABLED", False)
        and _env_flag("BR_AGENT_RECOVERY_AGENT", False)
    ):
        return decision

    router = _get_multiagent_router()
    if router is None:
        return decision

    proposal = router.propose_recovery(
        taxonomy_category=taxonomy.category.value,
        policy_action=policy.action.value,
        fallback_tools=decision.fallback_tools,
        adjusted_params=decision.adjusted_params,
        failed_tools=failed_tools,
        context=context,
    )
    if proposal is None:
        return decision

    if proposal.adjusted_params and not decision.adjusted_params:
        decision.adjusted_params = dict(proposal.adjusted_params)

    if proposal.fallback_tools:
        merged = _dedupe_preserve_order(
            [
                resolved
                for resolved in (
                    _canonical_runtime_tool_id(tool)
                    for tool in list(proposal.fallback_tools) + decision.fallback_tools
                )
                if resolved
            ]
        )
        failed = {
            resolved
            for resolved in (
                _canonical_runtime_tool_id(tool) for tool in (failed_tools or set())
            )
            if resolved
        }
        current_tool = _canonical_runtime_tool_id(tool_id) or tool_id
        merged = [tool for tool in merged if tool != current_tool and tool not in failed]
        try:
            limit = int(os.getenv("BR_FALLBACK_TOOL_LIMIT", "2"))
        except Exception:
            limit = 2
        if limit > 0:
            merged = merged[:limit]
        decision.fallback_tools = merged

    action_map = {
        "retry": RecoveryAction.RETRY_BACKOFF,
        "fallback_tool": RecoveryAction.TOOL_SUBSTITUTE,
        "degrade_mode": RecoveryAction.RELAX_CONSTRAINT,
        "ask_user": RecoveryAction.ASK_USER,
    }
    mapped_action = action_map.get(proposal.action_type)
    if (
        mapped_action is not None
        and decision.action == RecoveryAction.RETRY_BACKOFF
        and mapped_action in {
            RecoveryAction.TOOL_SUBSTITUTE,
            RecoveryAction.RELAX_CONSTRAINT,
            RecoveryAction.ASK_USER,
        }
    ):
        decision.action = mapped_action

    if proposal.reason:
        decision.reason = f"{decision.reason}|multiagent:{proposal.reason}"

    return decision


__all__ = [
    "RecoveryPolicy",
    "RecoveryDecision",
    "policy_for_taxonomy",
    "select_recovery_decision",
]
