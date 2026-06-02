"""Tool selection and scoring system for catalog-driven planner.

This module integrates synonym matching, preflight checks, and metadata scoring
to select and rank the most appropriate tools for a given query.

Selection Flow (3-Stage Pipeline - Phase 1.4):
1. Extract intent operators from query text (synonyms_loader)
2. Search catalog for tools matching those operators
3. Run preflight checks on candidates (preflight)
4. **Stage 1: Constraint Filtering** (apply_constraints)
   - Filter by hard constraints (preflight, capability match, container availability)
5. **Stage 2: Scoring** (existing logic with hierarchical overrides)
   - Score each candidate based on configurable factors
6. **Stage 3: Strategy Selection** (apply_strategy)
   - Apply selection strategy (top1, diverse_topk, budget_aware)
7. Return ranked list of SelectionCandidate objects

Phase 1.4 Enhancements:
- 3-stage pipeline with constraint → scoring → strategy
- Hierarchical override loading (modality → operator → environment → env vars)
- Selection strategies (top1, diverse_topk)
- Configurable scoring weights (YAML + env override)
- Resource fit scoring
- Enhanced explanations with narrative
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

from brain_researcher.core.contracts import Violation, ViolationLocation
from brain_researcher.services.agent.planner.catalog_loader import (
    ToolCapability,
    get_capability_index,
    search_by_capability,
    search_by_intent,
    search_by_modality,
)
from brain_researcher.services.agent.planner.config_loader import (
    load_capability_crosswalk,
)
from brain_researcher.services.agent.planner.config_loader import (
    load_scoring_weights as load_scoring_config,
)
from brain_researcher.services.agent.planner.implementation_router import (
    EnvContext,
    choose_tool_for_operation,
    choose_tool_for_operation_debug,
)
from brain_researcher.services.agent.planner.kg_bridge import (
    get_tool_ids_for_constraints,
)
from brain_researcher.services.agent.planner.operation_router import plan_operations
from brain_researcher.services.agent.planner.preflight import (
    PreflightReport,
    PreflightStatus,
    preflight_batch,
)
from brain_researcher.services.agent.planner.synonyms_loader import match_intents
from brain_researcher.services.tools.catalog_loader import (
    resolve_primary_runtime_tool_id,
)


@lru_cache(maxsize=1)
def _get_constraint_metric_recorder():
    try:
        from brain_researcher.services.agent.monitoring import metrics_collector as mc
    except Exception:
        return None
    if callable(getattr(mc, "record", None)):
        return mc.record
    fallback = getattr(mc, "metrics_collector", None)
    if fallback and callable(getattr(fallback, "record", None)):
        return fallback.record
    return None


def _canonical_tool_id(raw_tool_id: str | None) -> str:
    normalized = str(raw_tool_id or "").strip()
    return resolve_primary_runtime_tool_id(normalized) or normalized


_SCORING_WEIGHT_CACHE: Optional[Dict[str, float]] = None


def clear_scoring_weights_cache() -> None:
    """Clear the cached scoring weights so env-var overrides take effect immediately.

    Phase 1.4: This helper ensures test isolation and runtime env-var changes are
    properly picked up by load_scoring_weights().

    When to call:
        - **Before modifying BR_SCORE_WEIGHT_* env vars**: Ensures old cache is cleared
        - **After modifying BR_SCORE_WEIGHT_* env vars**: Forces reload on next call
        - **In test teardown**: Prevents cache pollution across test cases
        - **Service restart**: Not needed (cache is process-scoped)

    Usage pattern in tests:
        >>> import os
        >>> from brain_researcher.services.agent.planner.selection import (
        ...     load_scoring_weights, clear_scoring_weights_cache
        ... )
        >>> clear_scoring_weights_cache()  # Clear before modifying
        >>> try:
        ...     os.environ["BR_SCORE_WEIGHT_LATENCY_PRED"] = "0.8"
        ...     weights = load_scoring_weights()  # Picks up new value
        ...     assert weights["latency_pred"] == 0.8
        ... finally:
        ...     del os.environ["BR_SCORE_WEIGHT_LATENCY_PRED"]
        ...     clear_scoring_weights_cache()  # Clear after cleanup

    See also:
        - load_scoring_weights(): The function that uses this cache
        - load_hierarchical_config(): Merges modality/operator/environment overrides
        - docs/issues/09_move_planning_into_agent.md: Phase 1.4 cache semantics
        - tests/unit/planner/test_selection.py: Examples of proper usage
    """
    global _SCORING_WEIGHT_CACHE
    _SCORING_WEIGHT_CACHE = None


def load_scoring_weights(force_reload: bool = False) -> Dict[str, float]:
    """Load scoring weights from config with env var override support.

    Uses new v0.2 config format with backward compatibility for v0.1.

    Priority:
    1. Environment variables (BR_SCORE_WEIGHT_<FACTOR>=<value>)
    2. YAML config file (v0.2 or auto-converted v0.1)
    3. Hardcoded defaults

    Returns:
        Dict mapping factor names to weights
    """
    global _SCORING_WEIGHT_CACHE

    if _SCORING_WEIGHT_CACHE is not None and not force_reload:
        return _SCORING_WEIGHT_CACHE.copy()

    # Load config (handles v0.1 → v0.2 conversion automatically)
    config = load_scoring_config()

    # Extract weights from v0.2 structure
    weights = config.get("policy", {}).get("scoring", {}).get("weights", {})

    # Default weights if config is empty
    if not weights:
        weights = {
            "intent_match": 0.30,
            "preflight": 0.00,
            "description": 0.20,
            "metadata": 0.10,
            "resource_fit": 0.15,
            "historical_quality": 0.15,
            "latency_pred": 0.10,
        }

    # Apply environment variable overrides
    for factor in list(weights.keys()):
        env_key = f"BR_SCORE_WEIGHT_{factor.upper()}"
        env_value = os.getenv(env_key)
        if env_value is not None:
            try:
                weights[factor] = float(env_value)
                logger.info(f"Weight override from {env_key}: {weights[factor]}")
            except ValueError:
                logger.warning(f"Invalid weight value in {env_key}: {env_value}")

    # Validate weights sum to ~1.0 (allow small tolerance)
    total = sum(weights.values())
    if not (0.95 <= total <= 1.05):
        logger.warning(f"Scoring weights sum to {total:.3f}, expected ~1.0")

    _SCORING_WEIGHT_CACHE = weights.copy()
    return weights


def load_hierarchical_config(
    modality: Optional[str] = None,
    operator: Optional[str] = None,
    environment: Optional[str] = None,
) -> Dict[str, Any]:
    """Load config with hierarchical overrides applied.

    Phase 1.4: Implements hierarchical override system:
    1. Load base config from YAML
    2. Apply modality-specific overrides (if modality specified)
    3. Apply operator-specific overrides (if operator specified)
    4. Apply environment-specific overrides (if environment specified)
    5. Apply environment variable overrides
    6. Renormalize scoring weights to sum to 1.0

    Priority order (later overrides win):
    base → modality → operator → environment → env vars

    Args:
        modality: Optional modality (e.g., "fmri", "smri")
        operator: Optional operator (e.g., "skull_strip", "connectivity")
        environment: Optional environment (e.g., "local", "cloud", "hpc")

    Returns:
        Merged config dict with overrides applied

    Examples:
        >>> config = load_hierarchical_config(modality="fmri", operator="connectivity")
        >>> weights = config["policy"]["scoring"]["weights"]
        >>> weights["intent_match"]
        0.35  # fMRI override applied
    """
    # Load base config
    config = load_scoring_config()

    # Get overrides section
    overrides = config.get("overrides", {})

    # Helper to apply dotted path overrides
    def apply_override(cfg: Dict, path: str, value: Any) -> None:
        """Apply override at dotted path (auto-anchoring under policy when needed)."""

        if not path:
            return

        root_keys = {"policy", "strategy", "experiments", "telemetry"}
        first = path.split(".", 1)[0]
        if first not in root_keys:
            normalized_path = f"policy.{path}"
        else:
            normalized_path = path

        parts = normalized_path.split(".")
        current = cfg

        # Navigate to parent dict
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]

        # Set value
        current[parts[-1]] = value

    # Apply modality overrides
    if modality and modality in overrides.get("modality", {}):
        modality_overrides = overrides["modality"][modality]
        for path, value in modality_overrides.items():
            apply_override(config, path, value)
            logger.debug(f"Applied modality override ({modality}): {path} = {value}")

    # Apply operator overrides
    if operator and operator in overrides.get("operator", {}):
        operator_overrides = overrides["operator"][operator]
        for path, value in operator_overrides.items():
            apply_override(config, path, value)
            logger.debug(f"Applied operator override ({operator}): {path} = {value}")

    # Apply environment overrides
    if environment and environment in overrides.get("environment", {}):
        env_overrides = overrides["environment"][environment]
        for path, value in env_overrides.items():
            apply_override(config, path, value)
            logger.debug(
                f"Applied environment override ({environment}): {path} = {value}"
            )

    # Apply environment variable overrides
    weights = config.get("policy", {}).get("scoring", {}).get("weights", {})
    for factor in list(weights.keys()):
        env_key = f"BR_SCORE_WEIGHT_{factor.upper()}"
        env_value = os.getenv(env_key)
        if env_value is not None:
            try:
                weights[factor] = float(env_value)
                logger.info(f"Weight override from {env_key}: {weights[factor]}")
            except ValueError:
                logger.warning(f"Invalid weight value in {env_key}: {env_value}")

    # Renormalize weights to sum to 1.0
    total = sum(weights.values())
    if total > 0 and not (0.95 <= total <= 1.05):
        logger.info(f"Renormalizing weights (sum was {total:.3f})")
        for factor in weights:
            weights[factor] /= total
        logger.debug(f"Weights after renormalization: {weights}")

    return config


def apply_constraints(
    candidates: List[SelectionCandidate],
    config: Dict[str, Any],
    matched_operators: List[str],
    modality: Optional[str] = None,
    *,
    return_unavailable: bool = False,
) -> (
    List[SelectionCandidate]
    | tuple[
        List[SelectionCandidate],
        List[SelectionCandidate],
        List[Violation],
    ]
):
    """Stage 1: Apply hard constraints to filter candidates.

    Phase 1.4: Constraint filtering before scoring:
    - require_preflight: Drop tools that fail preflight checks
    - require_capability_match: Drop tools with weak capability match
    - require_container_availability: Drop containers not available
    - gpu_required_if: Drop non-GPU tools for operators requiring GPU
    - use_kg_constraints: Drop tools that don't satisfy KG modality/resource links

    Args:
        candidates: List of selection candidates
        config: Config dict with constraints from hierarchical loading
        matched_operators: List of operators from intent matching

    Returns:
        Filtered list of candidates passing all constraints

    Examples:
        >>> config = load_hierarchical_config()
        >>> filtered = apply_constraints(candidates, config, ["skull_strip"])
        >>> # Only candidates passing preflight and having container images
    """
    constraints = config.get("policy", {}).get("constraints", {})
    mask_reasons: List[Violation] = []

    # Track filter statistics
    initial_count = len(candidates)
    filtered = candidates.copy()
    removed: List[SelectionCandidate] = []

    def _mark_unavailable(
        candidate: SelectionCandidate,
        code: str,
        summary: str,
        detail: Optional[str] = None,
        *,
        severity: str = "warn",
        blocking: bool = True,
    ) -> None:
        candidate.available = False
        candidate.unavailable_reason = {
            "code": code,
            "detail": detail or summary,
        }
        candidate.reasons.append(
            {
                "code": code,
                "summary": summary,
                "detail": detail,
                "severity": severity,
                "blocking": blocking,
            }
        )
        mask_reasons.append(
            Violation(
                code=code,
                message=summary,
                severity=severity,
                blocking=blocking,
                where=ViolationLocation(component="planner", stage="preflight"),
                details={
                    "detail": detail or summary,
                    "tool_id": getattr(candidate.tool, "id", None),
                },
            )
        )

    def _filter_with_reason(
        current: List[SelectionCandidate],
        predicate,
        *,
        code: str,
        summary: str,
        detail_fn: Optional[Callable[[SelectionCandidate], Optional[str]]] = None,
        severity: str = "warn",
        blocking: bool = False,
    ) -> List[SelectionCandidate]:
        kept: List[SelectionCandidate] = []
        for cand in current:
            if predicate(cand):
                kept.append(cand)
            else:
                if return_unavailable:
                    detail = detail_fn(cand) if detail_fn else None
                    _mark_unavailable(
                        cand,
                        code,
                        summary,
                        detail,
                        severity=severity,
                        blocking=blocking,
                    )
                    removed.append(cand)
        return kept

    # Constraint 1: require_preflight
    if constraints.get("require_preflight", True):
        before = len(filtered)
        if return_unavailable:
            filtered = _filter_with_reason(
                filtered,
                lambda c: c.preflight_passed,
                code="DEPENDENCY_MISSING",
                summary="Preflight failed",
                detail_fn=lambda c: "; ".join(
                    f"{k}: {v}" for k, v in (c.preflight_detail or {}).items()
                ),
            )
        else:
            filtered = [c for c in filtered if c.preflight_passed]
        after = len(filtered)
        if before != after:
            logger.debug(f"Preflight constraint removed {before - after} candidates")

    # Constraint 2: require_capability_match (strict vs relaxed)
    match_mode = constraints.get("require_capability_match", "strict")
    if match_mode == "strict":
        # Strict: Only tools with exact capability match
        before = len(filtered)
        if return_unavailable:
            filtered = _filter_with_reason(
                filtered,
                lambda c: c.intent_match_score >= 0.8,
                code="INTENT_MATCH",
                summary="Intent match below threshold",
                detail_fn=lambda c: f"intent_match_score={c.intent_match_score:.2f}",
            )
        else:
            filtered = [c for c in filtered if c.intent_match_score >= 0.8]
        after = len(filtered)
        if before != after:
            logger.debug(
                f"Capability match constraint removed {before - after} candidates"
            )

    # Constraint 3: require_container_availability
    if constraints.get("require_container_availability", False):
        before = len(filtered)
        if return_unavailable:
            filtered = _filter_with_reason(
                filtered,
                lambda c: c.tool.runtime_kind != "container"
                or c.resource_fit_score >= 0.5,
                code="RESOURCE_UNAVAILABLE",
                summary="Container runtime unavailable",
                detail_fn=lambda c: "resource_fit_score<0.5 for container",
                severity="warn",
                blocking=False,
            )
        else:
            filtered = [
                c
                for c in filtered
                if c.tool.runtime_kind != "container" or c.resource_fit_score >= 0.5
            ]
        after = len(filtered)
        if before != after:
            logger.debug(
                f"Container availability constraint removed {before - after} candidates"
            )

    # Constraint 4: gpu_required_if
    gpu_required_ops = constraints.get("gpu_required_if", [])
    if gpu_required_ops and any(op in matched_operators for op in gpu_required_ops):
        # Filter to only GPU-capable tools
        before = len(filtered)
        if return_unavailable:
            filtered = _filter_with_reason(
                filtered,
                lambda c: getattr(getattr(c.tool, "resources", None), "gpu", False),
                code="RESOURCE_REQUIRED",
                summary="GPU required",
                detail_fn=lambda c: "requires_gpu",
                severity="error",
                blocking=True,
            )
        else:
            filtered = [
                c
                for c in filtered
                if getattr(getattr(c.tool, "resources", None), "gpu", False)
            ]
        after = len(filtered)
        if before != after:
            logger.debug(
                f"GPU requirement constraint removed {before - after} candidates"
            )

    # Constraint 5: KG-backed modality/resource filter (opt-in)
    use_kg_constraints = constraints.get("use_kg_constraints")
    if use_kg_constraints is None:
        use_kg_constraints = os.environ.get(
            "BR_PLANNER_USE_KG_CONSTRAINTS", ""
        ).lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    if use_kg_constraints:
        kg_modalities = constraints.get("kg_modalities") or []
        if not kg_modalities and modality:
            kg_modalities = [modality]

        kg_consumes = (
            constraints.get("kg_required_consumes")
            or constraints.get("kg_consumes")
            or []
        )
        kg_produces = (
            constraints.get("kg_required_produces")
            or constraints.get("kg_produces")
            or []
        )

        if kg_modalities or kg_consumes or kg_produces:
            kg_tool_ids = get_tool_ids_for_constraints(
                modalities=kg_modalities,
                consumes=kg_consumes,
                produces=kg_produces,
            )
            if kg_tool_ids is None:
                logger.debug("KG constraints skipped: KG unavailable")
            elif not kg_tool_ids:
                mode = constraints.get("kg_constraint_mode", "relaxed")
                if mode == "strict":
                    filtered = []
                    logger.debug("KG constraints strict mode removed all candidates")
                else:
                    logger.debug("KG constraints returned no matches; skipping filter")
            else:
                before = len(filtered)
                if return_unavailable:
                    filtered = _filter_with_reason(
                        filtered,
                        lambda c: c.tool.id in kg_tool_ids,
                        code="POLICY_BLOCKED",
                        summary="Filtered by KG constraints",
                        detail_fn=lambda c: "kg_constraints",
                    )
                else:
                    filtered = [c for c in filtered if c.tool.id in kg_tool_ids]
                after = len(filtered)
                if before != after:
                    logger.debug(f"KG constraint removed {before - after} candidates")

    # Constraint 6: budget / cost (conservative)
    max_cost_usd = constraints.get("max_cost_usd")
    if max_cost_usd is None:
        try:
            env_cost = float(os.getenv("BR_PLANNER_MAX_COST_USD", "nan"))
            max_cost_usd = env_cost if env_cost == env_cost else None  # NaN check
        except Exception:
            max_cost_usd = None

    if max_cost_usd is not None:
        before = len(filtered)
        if return_unavailable:
            filtered = _filter_with_reason(
                filtered,
                lambda c: getattr(
                    getattr(c.tool, "pricing", None), "estimated_cost_usd", None
                )
                in (None, 0.0)
                or getattr(getattr(c.tool, "pricing", None), "estimated_cost_usd", 0.0)
                <= max_cost_usd,
                code="BUDGET_EXCEEDED",
                summary="Estimated cost exceeds budget",
                detail_fn=lambda c: f"cost={getattr(getattr(c.tool, 'pricing', None), 'estimated_cost_usd', 'unknown')}usd > {max_cost_usd}",
                severity="warn",
                blocking=False,
            )
        else:
            filtered = [
                c
                for c in filtered
                if getattr(getattr(c.tool, "pricing", None), "estimated_cost_usd", None)
                in (None, 0.0)
                or getattr(getattr(c.tool, "pricing", None), "estimated_cost_usd", 0.0)
                <= max_cost_usd
            ]
        after = len(filtered)
        if before != after:
            logger.debug(f"Budget constraint removed {before - after} candidates")

    # Constraint 7: artifact size limit (conservative; skips tools producing large outputs)
    max_artifact_mb = constraints.get("max_artifact_mb")
    if max_artifact_mb is not None:
        before = len(filtered)
        if return_unavailable:
            filtered = _filter_with_reason(
                filtered,
                lambda c: getattr(
                    getattr(c.tool, "constraints", {}), "max_artifact_mb", 0
                )
                <= max_artifact_mb,
                code="ARTIFACT_TOO_LARGE",
                summary="Expected artifact size exceeds limit",
                detail_fn=lambda c: f"expected_mb={getattr(getattr(c.tool, 'constraints', {}), 'max_artifact_mb', 'unknown')} > {max_artifact_mb}",
                severity="warn",
                blocking=False,
            )
        else:
            filtered = [
                c
                for c in filtered
                if getattr(getattr(c.tool, "constraints", {}), "max_artifact_mb", 0)
                <= max_artifact_mb
            ]
        after = len(filtered)
        if before != after:
            logger.debug(
                f"Artifact-size constraint removed {before - after} candidates"
            )

    # Constraint 8: license allowlist
    allowed_licenses = constraints.get("allowed_licenses") or []
    if allowed_licenses:
        allowed_set = {str(x).lower() for x in allowed_licenses}
        before = len(filtered)
        if return_unavailable:
            filtered = _filter_with_reason(
                filtered,
                lambda c: str(getattr(c.tool, "license", "")).lower() in allowed_set,
                code="LICENSE_BLOCKED",
                summary="Tool license not permitted",
                detail_fn=lambda c: getattr(c.tool, "license", None),
                severity="warn",
                blocking=False,
            )
        else:
            filtered = [
                c
                for c in filtered
                if str(getattr(c.tool, "license", "")).lower() in allowed_set
            ]
        after = len(filtered)
        if before != after:
            logger.debug(f"License constraint removed {before - after} candidates")

    # Constraint 9: network usage (optional disallow)
    if constraints.get("disallow_network", False):
        before = len(filtered)
        if return_unavailable:
            filtered = _filter_with_reason(
                filtered,
                lambda c: not getattr(
                    getattr(c.tool, "constraints", {}), "requires_network", False
                ),
                code="NETWORK_BLOCKED",
                summary="Tool requires network but network use is disallowed",
                detail_fn=lambda c: getattr(
                    getattr(c.tool, "constraints", {}), "requires_network", None
                ),
                severity="warn",
                blocking=True,
            )
        else:
            filtered = [
                c
                for c in filtered
                if not getattr(
                    getattr(c.tool, "constraints", {}), "requires_network", False
                )
            ]
        after = len(filtered)
        if before != after:
            logger.debug(f"Network constraint removed {before - after} candidates")

    logger.info(
        f"Constraints filtered {initial_count} → {len(filtered)} candidates "
        f"({initial_count - len(filtered)} removed)"
    )
    if initial_count > 0:
        filter_rate = (initial_count - len(filtered)) / initial_count
    else:
        filter_rate = 0.0
    recorder = _get_constraint_metric_recorder()
    if recorder:
        recorder("planner_constraint_filter_rate", filter_rate)

    if return_unavailable:
        return filtered, removed, mask_reasons

    return filtered


def apply_strategy(
    candidates: List[SelectionCandidate],
    config: Dict[str, Any],
    max_results: int = 10,
) -> List[SelectionCandidate]:
    """Stage 3: Apply selection strategy to ranked candidates.

    Phase 1.4: Selection strategies:
    - top1: Return single best candidate
    - diverse_topk: Return top K with diversity penalty for same package
    - budget_aware: Filter by latency/cost constraints

    Strategy is controlled by:
    1. config["strategy"]["default"]
    2. BR_PLANNER_STRATEGY environment variable (overrides config)

    Args:
        candidates: List of scored and ranked candidates
        config: Config dict with strategy settings
        max_results: Maximum number of results to return

    Returns:
        Filtered candidates according to strategy

    Examples:
        >>> config = load_hierarchical_config()
        >>> selected = apply_strategy(candidates, config, max_results=3)
        >>> # Returns top 3 tools with diversity penalty applied
    """
    # Get strategy from config or env var
    strategy_config = config.get("strategy", {})
    strategy = os.getenv("BR_PLANNER_STRATEGY", strategy_config.get("default", "top1"))

    if strategy == "top1":
        # Return only the top candidate
        return candidates[:1] if candidates else []

    elif strategy == "diverse_topk":
        # Return top K with diversity penalty for same package
        k = strategy_config.get("diverse_topk", {}).get("k", 3)
        diversity_penalty = strategy_config.get("diverse_topk", {}).get(
            "diversity_penalty", 0.1
        )

        # Group candidates by package/namespace
        selected = []
        package_counts = {}

        for candidate in candidates:
            if len(selected) >= k:
                break

            package = str(getattr(candidate.tool, "package", "") or "").strip()
            if not package:
                tool_id = str(candidate.tool.id or "")
                package = tool_id.split(".")[0] if "." in tool_id else tool_id

            # Apply diversity penalty
            count = package_counts.get(package, 0)
            penalty = count * diversity_penalty
            adjusted_score = candidate.final_score * (1.0 - penalty)

            # Check if still worth including
            if not selected or adjusted_score >= selected[-1].final_score * 0.7:
                selected.append(candidate)
                package_counts[package] = count + 1

        logger.debug(
            f"diverse_topk strategy selected {len(selected)}/{len(candidates)} candidates"
        )
        return selected

    elif strategy == "budget_aware":
        # Filter by latency and cost constraints
        max_latency_min = strategy_config.get("budget_aware", {}).get(
            "max_latency_min", 60
        )
        max_cost_usd = strategy_config.get("budget_aware", {}).get("max_cost_usd", 10.0)

        # Filter candidates meeting budget constraints
        filtered = []
        for candidate in candidates:
            # Check latency (stub: use tool defaults if available)
            tool_latency = getattr(candidate.tool, "estimated_latency_min", 0)
            if tool_latency > max_latency_min:
                logger.debug(
                    f"Skipping {candidate.tool.id}: latency {tool_latency} > {max_latency_min}"
                )
                continue

            # Check cost (stub: not implemented yet)
            # tool_cost = getattr(candidate.tool, "estimated_cost_usd", 0.0)
            # if tool_cost > max_cost_usd:
            #     continue

            filtered.append(candidate)

            if len(filtered) >= max_results:
                break

        logger.debug(
            f"budget_aware strategy selected {len(filtered)}/{len(candidates)} candidates"
        )
        return filtered

    else:
        logger.warning(f"Unknown strategy '{strategy}', falling back to top1")
        return candidates[:1] if candidates else []


@dataclass
class SelectionCandidate:
    """A tool candidate with selection metadata.

    Attributes:
        tool: The tool capability object
        intent_match_score: Score from intent matching (0.0-1.0)
        preflight_passed: Whether preflight checks passed
        preflight_detail: Detail messages from preflight checks
        description_score: Score from description relevance (0.0-1.0)
        metadata_score: Score from tool metadata (0.0-1.0)
        resource_fit_score: Score from resource availability (0.0-1.0) [PR-3]
        final_score: Combined score (0.0-1.0)
        explanation: Human-readable explanation [PR-3]
    """

    tool: ToolCapability
    scoring_weights: Dict[
        str, float
    ]  # Required - must be from load_hierarchical_config
    intent_match_score: float = 0.0
    preflight_passed: bool = False
    preflight_detail: Dict[str, str] = field(default_factory=dict)
    description_score: float = 0.0
    metadata_score: float = 0.0
    resource_fit_score: float = 0.0
    historical_quality_score: float = 0.5
    latency_score: float = 0.5
    final_score: float = 0.0
    explanation: str = ""
    source: str = "catalog"  # catalog | br_kg
    available: bool = True
    unavailable_reason: Optional[Dict[str, Any]] = None
    reasons: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        """Calculate final score and generate explanation after initialization.

        Phase 1.4 fix: scoring_weights is now required and must be passed from
        load_hierarchical_config() to ensure modality/operator/environment
        overrides are applied.
        """
        if not self.scoring_weights:
            raise ValueError(
                "scoring_weights must be provided (from load_hierarchical_config). "
                "This ensures modality/operator/environment overrides are applied."
            )
        self.final_score = self._calculate_final_score()
        self.explanation = self._generate_explanation()

    def _calculate_final_score(self) -> float:
        """Calculate weighted final score using configurable weights.

        Phase 1.4: Uses weights from hierarchical config (passed at construction)
        to ensure modality/operator/environment overrides affect ranking.

        PR-3: Now uses 7-factor scoring:
        - Intent match: 30% (default)
        - Preflight pass: 0% (binary filter, not weighted)
        - Description relevance: 20%
        - Metadata quality: 10%
        - Resource fit: 15%
        - Historical quality: 15%
        - Latency prediction: 10%

        Returns:
            Final score between 0.0 and 1.0
        """
        weights = self.scoring_weights  # No fallback - must be provided
        preflight_score = 1.0 if self.preflight_passed else 0.0

        score = (
            weights.get("intent_match", 0.3) * self.intent_match_score
            + weights.get("preflight", 0.0) * preflight_score
            + weights.get("description", 0.2) * self.description_score
            + weights.get("metadata", 0.1) * self.metadata_score
            + weights.get("resource_fit", 0.15) * self.resource_fit_score
            + weights.get("historical_quality", 0.15) * self.historical_quality_score
            + weights.get("latency_pred", 0.1) * self.latency_score
        )

        return max(0.0, min(1.0, score))  # Clamp to [0, 1]

    def _generate_explanation(self) -> str:
        """Generate brief narrative explanation of scoring.

        Returns:
            Brief explanation string
        """
        parts = []

        # Intent match
        if self.intent_match_score >= 0.8:
            parts.append("Excellent match for query")
        elif self.intent_match_score >= 0.5:
            parts.append("Good capability match")
        else:
            parts.append("Partial match")

        # Preflight
        if self.preflight_passed:
            parts.append("ready to use")
        else:
            parts.append("setup required")

        # Resource fit
        if self.resource_fit_score >= 0.8:
            parts.append("all resources available")
        elif self.resource_fit_score >= 0.5:
            parts.append("minor setup needed")

        return "; ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize candidate for Plan.candidates field.

        P0-1: Returns dict representation suitable for JSON serialization
        in Plan.candidates list.

        Returns:
            Dict with tool metadata and scoring details
        """
        canonical_tool_id = (
            resolve_primary_runtime_tool_id(self.tool.id) or self.tool.id
        )
        payload = {
            "tool_id": canonical_tool_id,
            "tool_name": self.tool.name,
            "final_score": self.final_score,
            "intent_match_score": self.intent_match_score,
            "preflight_passed": self.preflight_passed,
            "preflight_detail": self.preflight_detail,
            "description_score": self.description_score,
            "metadata_score": self.metadata_score,
            "resource_fit_score": self.resource_fit_score,
            "historical_quality_score": self.historical_quality_score,
            "latency_score": self.latency_score,
            "explanation": self.explanation,
            "source": self.source,
            "available": self.available,
        }
        if self.unavailable_reason is not None:
            payload["unavailable_reason"] = self.unavailable_reason
        if self.reasons:
            payload["reasons"] = self.reasons
        if canonical_tool_id != self.tool.id:
            payload["tool_id_raw"] = self.tool.id
        return payload


def _score_intent_match(
    tool: ToolCapability,
    matched_operators: List[str],
    operator_weights: Dict[str, float],
) -> float:
    """Score how well tool matches intent operators.

    Args:
        tool: Tool to score
        matched_operators: List of operators from intent matching
        operator_weights: Dict mapping operator → confidence weight (0.0-1.0)

    Returns:
        Score between 0.0 and 1.0
    """
    if not matched_operators:
        return 0.0

    best = 0.0
    for tool_capability in tool.capabilities or []:
        # Check exact match
        if tool_capability in matched_operators:
            idx = matched_operators.index(tool_capability)
            # Earlier matches get higher weight (rank 0 = 1.0, rank 1 = 0.9, etc.)
            rank_weight = max(0.5, 1.0 - (idx * 0.1))
            best = max(best, operator_weights.get(tool_capability, 1.0) * rank_weight)
            continue

        # Check partial match (capability contains operator or vice versa)
        for idx, operator in enumerate(matched_operators):
            if operator in tool_capability or tool_capability in operator:
                rank_weight = max(0.3, 0.8 - (idx * 0.1))
                best = max(best, operator_weights.get(operator, 0.7) * rank_weight)

    return best


def _score_description_relevance(tool: ToolCapability, query: str) -> float:
    """Score description relevance to query.

    Simple keyword-based scoring:
    - Extract significant words from query (length > 3)
    - Count how many appear in tool name + description
    - Normalize by query word count

    Args:
        tool: Tool to score
        query: Original query text

    Returns:
        Score between 0.0 and 1.0
    """
    # Extract significant words from query (lowercase, length > 3)
    query_words = set(
        word.lower() for word in re.findall(r"\b\w+\b", query) if len(word) > 3
    )

    if not query_words:
        return 0.5  # Neutral score for very short queries

    # Build searchable text from tool (fallback to metadata.description)
    desc = getattr(tool, "description", None)
    if not desc and getattr(tool, "metadata", None):
        desc = getattr(tool.metadata, "description", "") or ""

    tool_text = (f"{tool.name} {desc} {' '.join(tool.capabilities)}").lower()

    # Count matches
    matches = sum(1 for word in query_words if word in tool_text)

    # Normalize
    return min(1.0, matches / len(query_words))


def _score_metadata(tool: ToolCapability) -> float:
    """Score tool based on metadata quality.

    Factors:
    - Has description: +0.3
    - Has documentation: +0.3
    - Runtime kind preference: container=0.2, python=0.4 (Python preferred for speed)

    Args:
        tool: Tool to score

    Returns:
        Score between 0.0 and 1.0
    """
    score = 0.0

    # Has description
    desc = getattr(tool, "description", None)
    if not desc and getattr(tool, "metadata", None):
        desc = getattr(tool.metadata, "description", None)
    if desc and len(desc) > 20:
        score += 0.3

    # Has documentation
    if hasattr(tool, "documentation") and tool.documentation:
        score += 0.3

    # Runtime preference (Python is faster to execute)
    if tool.runtime_kind == "python":
        score += 0.4
    elif tool.runtime_kind == "container":
        score += 0.2

    return min(1.0, score)


def _score_resource_fit(
    tool: ToolCapability,
    preflight_report: PreflightReport,
) -> float:
    """Score tool based on resource availability and fit.

    PR-3: New scoring factor considering:
    - Container image accessibility (0.5 weight)
    - CVMFS mount status (0.3 weight)
    - Python dependencies (0.2 weight)

    PR-3 Polish: Now uses structured PreflightStatus codes instead of string matching.

    Args:
        tool: Tool to score
        preflight_report: Preflight check results

    Returns:
        Score between 0.0 and 1.0
    """
    score = 0.0

    # Check container image status using structured codes
    if "container_image" in preflight_report.checks:
        check = preflight_report.checks["container_image"]
        status = check.status_code

        if status == PreflightStatus.CVMFS_AVAILABLE:
            # CVMFS-based container gets full score
            score += 0.5
        elif status == PreflightStatus.LOCAL_AVAILABLE:
            # Local container available
            score += 0.4
        elif status == PreflightStatus.NOT_REQUIRED:
            # Not a container tool, neutral score
            score += 0.25
        elif status == PreflightStatus.NOT_AVAILABLE:
            # Container not available
            score += 0.0
        else:
            # Fallback for legacy checks without status_code
            if check.passed:
                score += 0.4
            else:
                score += 0.0

    # Check CVMFS mount (relevant for container tools)
    if tool.runtime_kind == "container":
        image = getattr(tool.container, "image", None) if tool.container else None
        if tool.container and isinstance(image, str) and "/cvmfs/" in image:
            # CVMFS tool - check if mounted
            container_check = preflight_report.checks.get("container_image")
            if (
                container_check
                and container_check.status_code == PreflightStatus.CVMFS_AVAILABLE
            ):
                score += 0.3
            else:
                score += 0.0
        else:
            # Local container, assume available if preflight passed
            score += 0.3 if preflight_report.passed else 0.0

    # Check Python dependencies using structured codes
    if "python_import" in preflight_report.checks:
        check = preflight_report.checks["python_import"]
        status = check.status_code

        if status == PreflightStatus.IMPORT_SUCCESS:
            score += 0.2
        elif status == PreflightStatus.NOT_REQUIRED:
            # Not a Python tool, neutral score
            score += 0.1
        elif status == PreflightStatus.IMPORT_FAILED:
            score += 0.0
        else:
            # Fallback for legacy checks without status_code
            if check.passed:
                score += 0.2
            else:
                score += 0.0

    return min(1.0, score)


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    """Clamp helper."""
    return max(minimum, min(maximum, value))


def _dedupe_preserve_order(items: List[str]) -> List[str]:
    out: List[str] = []
    seen: Set[str] = set()
    for item in items:
        if not item:
            continue
        if item in seen:
            continue
        out.append(item)
        seen.add(item)
    return out


def _extract_expected_capabilities_hint(query: str) -> List[str]:
    """Parse optional benchmark hint injected into query by the benchmark runner.

    Format:
        [BR_EXPECTED_CAPABILITIES]: cap_a, cap_b, ...
    """
    if not query:
        return []

    out: List[str] = []
    for line in str(query).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.lower().startswith("[br_expected_capabilities]"):
            continue
        _, _, rest = stripped.partition(":")
        rest = rest.strip()
        if not rest:
            continue
        for cap in rest.split(","):
            cap = cap.strip()
            if cap:
                out.append(cap)
    return out


def _apply_capability_crosswalk(
    query: str, matched_operators: List[str]
) -> tuple[List[str], List[str]]:
    """Augment matched operators with crosswalk-derived operators/intents.

    The crosswalk helps map higher-level labels (benchmarks, UI tags) and common
    phrases to existing catalog capability tags and intent ids.

    Returns:
        (expanded_operators, matched_crosswalk_keys)
    """
    cfg = load_capability_crosswalk()
    mappings = cfg.get("mappings", {}) if isinstance(cfg, dict) else {}
    if not isinstance(mappings, dict) or not mappings:
        return matched_operators, []

    expected_caps = _extract_expected_capabilities_hint(query)
    expected_caps_lower = {c.lower() for c in expected_caps}
    q_lower = (query or "").lower()

    extra_ops: List[str] = []
    extra_intents: List[str] = []
    matched_keys: List[str] = []

    for key, spec in mappings.items():
        if not key or not isinstance(spec, dict):
            continue

        key_lower = str(key).lower()
        triggered = key_lower in expected_caps_lower

        if not triggered:
            triggers = [key] + list(spec.get("aliases") or [])
            for trig in triggers:
                if not trig:
                    continue
                trig_lower = str(trig).lower()
                if len(trig_lower) <= 3 and re.fullmatch(r"[a-z0-9_]+", trig_lower):
                    # Short triggers should be matched on word boundary to reduce false positives.
                    if re.search(rf"\\b{re.escape(trig_lower)}\\b", q_lower):
                        triggered = True
                        break
                elif trig_lower in q_lower:
                    triggered = True
                    break

        if not triggered:
            continue

        matched_keys.append(str(key))
        extra_ops.extend([str(x) for x in (spec.get("to_operators") or []) if x])
        extra_intents.extend([str(x) for x in (spec.get("to_intents") or []) if x])

    expanded = _dedupe_preserve_order(matched_operators + extra_ops + extra_intents)
    return expanded, matched_keys


def _score_historical_quality(tool: ToolCapability) -> float:
    """Estimate historical quality / success rate.

    Uses explicit constraint hints when available, otherwise falls back to metadata-based
    heuristics so the weight slot is never ignored.
    """
    constraints = getattr(tool, "constraints", {}) or {}
    if "historical_success_rate" in constraints:
        try:
            return _clamp(float(constraints["historical_success_rate"]))
        except (TypeError, ValueError):
            pass

    # Heuristic: published/literature-backed tools score higher than legacy ones.
    score = 0.5
    metadata = tool.metadata
    if metadata:
        if metadata.literature:
            score += 0.2
        if metadata.urls:
            score += 0.1
    if tool.source == "catalog":
        score += 0.1

    return _clamp(score)


def _score_latency_pred(tool: ToolCapability) -> float:
    """Estimate latency preference (higher score = faster execution)."""
    resources = getattr(tool, "resources", None)
    if not resources:
        return 0.5

    latency = getattr(resources, "time_min_default", None)
    if latency is None:
        return 0.5

    fast_threshold = 5.0
    slow_threshold = 60.0

    if latency <= fast_threshold:
        return 1.0
    if latency >= slow_threshold:
        return 0.0

    normalized = 1.0 - (latency - fast_threshold) / (slow_threshold - fast_threshold)
    return _clamp(normalized)


def select_tools(
    query: str,
    modality: Optional[str] = None,
    max_results: int = 10,
    require_preflight_pass: bool = True,
    environment: Optional[str] = None,
    *,
    apply_selection_strategy: bool = True,
    include_unavailable: bool = False,
    max_unavailable: Optional[int] = None,
    mask_reasons_out: Optional[List[Violation]] = None,
    allowed_tool_ids: Optional[Set[str]] = None,
    include_local_first: bool = False,
) -> List[SelectionCandidate]:
    """Select and rank tools for the given query.

    Phase 1.4: Refactored into 3-stage pipeline:
    1. Extract intent operators from query
    2. Search catalog for matching tools
    3. Run preflight checks
    4. Score all candidates
    5. **Stage 1: Apply hard constraints** (apply_constraints)
    6. **Stage 2: Sort by score**
    7. **Stage 3: Apply selection strategy** (apply_strategy)

    Args:
        query: Natural language query describing desired operation
        modality: Optional modality filter (e.g., "fmri", "smri", "dmri")
        max_results: Maximum number of results to return
        require_preflight_pass: DEPRECATED - use config constraints instead
        environment: Optional environment (e.g., "local", "cloud", "hpc")

    Returns:
        List of SelectionCandidate objects, sorted by final_score (descending)

    Examples:
        >>> candidates = select_tools("skull strip T1 image")
        >>> if candidates:
        ...     best_tool = candidates[0].tool
        ...     print(f"Selected: {best_tool.name} (score: {candidates[0].final_score:.2f})")

        >>> candidates = select_tools(
        ...     "functional connectivity analysis",
        ...     modality="fmri",
        ...     max_results=5,
        ...     environment="cloud"
        ... )
    """
    # Step 1: Extract intent operators from query
    matched_operators = match_intents(query, modality=modality)

    semantic_fallback = (environment or "").strip().lower() == "benchmark"

    matched_operators, crosswalk_keys = _apply_capability_crosswalk(
        query, matched_operators
    )
    if crosswalk_keys:
        logger.debug("Capability crosswalk matched: %s", ",".join(crosswalk_keys))

    if not matched_operators and not semantic_fallback:
        # No intent matches - return empty list (default production behavior)
        return []

    # Primary operator (first match)
    primary_operator = matched_operators[0] if matched_operators else None

    # Load hierarchical config with overrides
    config = load_hierarchical_config(
        modality=modality,
        operator=primary_operator,
        environment=environment,
    )
    scoring_config = config.get("policy", {}).get("scoring", {})
    scoring_weights = scoring_config.get("weights", {}).copy()
    if not scoring_weights:
        scoring_weights = load_scoring_weights()
    features_config = scoring_config.get("features", {}) or {}

    # Create operator weights (decreasing by rank)
    operator_weights = {
        op: max(0.5, 1.0 - (idx * 0.1)) for idx, op in enumerate(matched_operators)
    }

    # Step 2: Search catalog for tools
    # Use an ID-keyed dict to avoid hashability issues and to enforce precedence.
    candidate_map: Dict[str, ToolCapability] = {}

    def _merge(tools: List[ToolCapability]) -> None:
        for t in tools:
            candidate_map[t.id] = t  # later inserts overwrite by id (if needed)

    # Search by each matched operator (capability tags + intent ids).
    for operator in matched_operators:
        cap_hits = search_by_capability(
            operator,
            include_local_first=include_local_first,
        )
        _merge(cap_hits)
        if not cap_hits:
            # Some operators are intent-level (e.g., fmriprep_preprocessing) rather than
            # capability tags; include intent matches as well.
            _merge(
                search_by_intent(
                    operator,
                    include_local_first=include_local_first,
                )
            )

    # Also search by modality if specified
    if modality:
        modality_tools = search_by_modality(
            modality,
            include_local_first=include_local_first,
        )
        if candidate_map:
            # Intersect by id to keep only tools matching both capability and modality
            modality_ids = {t.id for t in modality_tools}
            candidate_map = {
                tid: t for tid, t in candidate_map.items() if tid in modality_ids
            }
        else:
            _merge(modality_tools)

    if not candidate_map:
        if not semantic_fallback:
            return []
        # Benchmark-only: allow semantic scoring even when the intent classifier fails
        # or the catalog has no direct capability/intent hits.
        idx = get_capability_index(include_local_first=include_local_first)
        _merge(list(idx.by_id.values()))

    if allowed_tool_ids is not None:
        allowed = {
            str(tool_id).strip() for tool_id in allowed_tool_ids if str(tool_id).strip()
        }
        if allowed:
            candidate_map = {
                tool_id: tool
                for tool_id, tool in candidate_map.items()
                if tool_id in allowed
            }
        else:
            candidate_map = {}

    candidate_tools = list(candidate_map.values())

    # Step 3: Run preflight checks on all candidates
    if semantic_fallback:
        # Semantic benchmark mode: infra readiness is not part of scoring/constraints.
        preflight_reports = {
            tool.id: PreflightReport(tool_id=tool.id, passed=True)
            for tool in candidate_tools
        }
    else:
        preflight_reports = preflight_batch(candidate_tools)

    # Step 4: Score each candidate
    candidates: List[SelectionCandidate] = []

    for tool in candidate_tools:
        preflight_report = preflight_reports.get(tool.id)

        if not preflight_report:
            # Should not happen, but handle gracefully
            continue

        # Extract preflight detail messages
        preflight_detail = {
            name: check.detail or "passed" if check.passed else check.detail or "failed"
            for name, check in preflight_report.checks.items()
        }

        # Calculate component scores
        intent_score = _score_intent_match(tool, matched_operators, operator_weights)
        description_score = _score_description_relevance(tool, query)
        metadata_score = _score_metadata(tool)
        resource_fit_score = _score_resource_fit(tool, preflight_report)
        historical_quality_score = (
            _score_historical_quality(tool)
            if features_config.get("historical_quality", False)
            else 0.0
        )
        latency_score = (
            _score_latency_pred(tool)
            if features_config.get("latency_pred", False)
            else 0.0
        )

        candidate = SelectionCandidate(
            tool=tool,
            intent_match_score=intent_score,
            preflight_passed=preflight_report.passed,
            preflight_detail=preflight_detail,
            description_score=description_score,
            metadata_score=metadata_score,
            resource_fit_score=resource_fit_score,
            historical_quality_score=historical_quality_score,
            latency_score=latency_score,
            scoring_weights=scoring_weights,
            source="catalog",
            available=True,
        )

        candidates.append(candidate)

    # **STAGE 1: Apply hard constraints**
    if include_unavailable or mask_reasons_out is not None:
        candidates, unavailable, mask_reasons = apply_constraints(
            candidates,
            config,
            matched_operators,
            modality=modality,
            return_unavailable=True,
        )
        if mask_reasons_out is not None:
            mask_reasons_out.extend(mask_reasons)
    else:
        candidates = apply_constraints(
            candidates, config, matched_operators, modality=modality
        )

    if not candidates:
        logger.warning(f"No candidates passed constraints for query: {query}")
        if include_unavailable:
            # Return unavailable-only list (useful for blocked result explainability)
            if max_unavailable is not None:
                unavailable.sort(key=lambda c: c.final_score, reverse=True)
                unavailable = unavailable[:max_unavailable]
            return unavailable
        return []

    # **STAGE 2: Sort by final score (descending)**
    candidates.sort(key=lambda c: c.final_score, reverse=True)

    # **STAGE 3: Apply selection strategy**
    if apply_selection_strategy:
        candidates = apply_strategy(candidates, config, max_results=max_results)
    else:
        candidates = candidates[:max_results]

    if include_unavailable:
        if max_unavailable is not None:
            unavailable.sort(key=lambda c: c.final_score, reverse=True)
            unavailable = unavailable[:max_unavailable]
        return candidates + unavailable

    return candidates


def choose_tool(
    request: "PlanRequest",
    max_candidates: int = 5,
    require_preflight_pass: bool = True,
    *,
    allowed_tool_ids: Optional[Set[str]] = None,
    include_local_first: bool = False,
) -> "Plan":
    """
    Choose best tool for PlanRequest and return Plan with selection reasoning.

    P0-1: Main entry point for catalog-driven planner. Integrates intent matching,
    tool search, preflight checks, and scoring to produce a Plan with:
    - Selected tool in chosen_tool field
    - Ranked candidates in candidates field
    - Explanation in selection_reason field
    - Intent operators in intent field

    Args:
        request: PlanRequest with pipeline (query), domain, modality, constraints
        max_candidates: Max candidates to include in response (default: 5)
        require_preflight_pass: Filter failed preflight checks (default: True)

    Returns:
        Plan with selection reasoning and single-step DAG

    Examples:
        >>> from brain_researcher.services.shared.planner.models import PlanRequest
        >>> req = PlanRequest(pipeline="skull strip T1", domain="neuroimaging", modality=["smri"])
        >>> plan = choose_tool(req)
        >>> print(plan.chosen_tool, plan.selection_reason)
        fsl_bet Selected BET (score: 0.92). Excellent match for query; ready to use; all resources available. Preflight: passed.
    """
    import time
    import uuid
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from brain_researcher.services.shared.planner.models import Plan, PlanRequest

    # Import here to avoid circular dependency
    from brain_researcher.services.shared.planner.models import (
        Plan,
        PlanDAG,
        StepSpec,
    )

    # 1. Extract query and modality from request
    query = request.pipeline
    modality = request.modality[0] if request.modality else None

    # 2. Extract intent operators
    matched_intents = match_intents(query, modality=modality)

    # 3. Run selection
    mask_reasons: List[Violation] = []
    candidates = select_tools(
        query=query,
        modality=modality,
        max_results=max_candidates,
        require_preflight_pass=require_preflight_pass,
        mask_reasons_out=mask_reasons,
        allowed_tool_ids=allowed_tool_ids,
        include_local_first=include_local_first,
    )

    if not candidates:
        # No tools found - return unresolvable plan
        logger.warning(f"No tools found for query: {query} (modality: {modality})")
        return Plan(
            plan_id=str(uuid.uuid4()),
            domain=request.domain,
            modality=request.modality,
            resolvable=False,
            dag=PlanDAG(steps=[], artifacts=[]),
            warnings=[f"No suitable tools found for query: {query}"],
            intent=matched_intents,
            candidates=[],
            mask_reasons=mask_reasons or None,
            allowlist_mode=getattr(request, "allowlist_mode", None),
            timestamp=int(time.time()),
        )

    # 4. Choose top candidate
    chosen = candidates[0]

    # 5. Build DAG (single-step by default; optional branch fallback when enabled)
    try:
        branch_top_k = int(os.getenv("BR_PLANNER_BRANCH_TOP_K", "1"))
    except ValueError:
        branch_top_k = 1
    branch_top_k = max(1, min(branch_top_k, len(candidates)))

    plan_id = str(uuid.uuid4())
    steps: List[StepSpec] = []
    if branch_top_k > 1:
        branch_group_id = f"bg:{plan_id}"
        for idx, candidate in enumerate(candidates[:branch_top_k]):
            step = StepSpec(
                id=f"step-branch-{idx+1:03d}",
                tool=_canonical_tool_id(candidate.tool.id),
                params=request.inputs,  # Use inputs from request as initial params
                runtime_kind=candidate.tool.runtime_kind,  # Propagate backend type from catalog
                metadata={
                    "branch_group_id": branch_group_id,
                    "branch_rank": idx,
                    "branch_reason": candidate.explanation,
                },
            )
            steps.append(step)
    else:
        step = StepSpec(
            id="001-main",
            tool=_canonical_tool_id(chosen.tool.id),
            params=request.inputs,  # Use inputs from request as initial params
            runtime_kind=chosen.tool.runtime_kind,  # Propagate backend type from catalog
        )
        steps.append(step)

    # 6. Generate selection reason
    reason = (
        f"Selected {chosen.tool.name} (score: {chosen.final_score:.2f}). "
        f"{chosen.explanation}. "
        f"Preflight: {'passed' if chosen.preflight_passed else 'failed'}."
    )

    # 7. Build Plan with selection reasoning
    plan = Plan(
        plan_id=plan_id,
        domain=request.domain,
        modality=request.modality,
        resolvable=True,
        dag=PlanDAG(steps=steps, artifacts=[]),
        constraints=request.constraints,
        allowlist_mode=getattr(request, "allowlist_mode", None),
        # P0-1: Add selection reasoning
        intent=matched_intents,
        candidates=[c.to_dict() for c in candidates],
        chosen_tool=_canonical_tool_id(chosen.tool.id),
        selection_reason=reason,
        mask_reasons=mask_reasons or None,
        timestamp=int(time.time()),
    )

    logger.info(
        f"Generated plan {plan.plan_id} for query '{query}': "
        f"chosen {_canonical_tool_id(chosen.tool.id)} (score: {chosen.final_score:.2f})"
    )

    return plan


def choose_tool_intent_router(
    request: "PlanRequest",
    max_candidates: int = 5,  # kept for potential future use
    return_debug: bool = False,
    tool_retriever: "Any | None" = None,
    mask_reasons_out: Optional[List[Violation]] = None,
    allowed_tool_ids: Optional[Set[str]] = None,
) -> Optional["Plan"]:
    """Intent/operation + implementation router path.

    Returns a Plan if an intent and implementation are found; otherwise None to
    let callers fall back to legacy/catalog selection.
    """
    import time
    import uuid

    from brain_researcher.services.shared.planner.models import Plan, PlanDAG, StepSpec

    operations = plan_operations(request)
    if not operations:
        if mask_reasons_out is not None:
            mask_reasons_out.append(
                Violation(
                    code="INTENT_UNMAPPED",
                    message="No intent matched for request",
                    severity="warn",
                    blocking=False,
                    where=ViolationLocation(component="planner", stage="preflight"),
                    details={
                        "query": request.pipeline,
                        "domain": request.domain,
                        "modality": request.modality,
                    },
                )
            )
        return None

    env = EnvContext(tool_retriever=tool_retriever)
    steps: List[StepSpec] = []
    warnings: List[str] = []

    debug_rows: List[Dict[str, Any]] = []
    for idx, op in enumerate(operations):
        if return_debug:
            tool, rows = choose_tool_for_operation_debug(op, env)
            sorted_rows = sorted(rows, key=lambda x: -x[0])[:5]
            debug_rows = [
                {
                    "tool": _canonical_tool_id(t.id),
                    "score": float(f"{s:.6f}"),
                    "reasons": r,
                }
                for s, t, r in sorted_rows
            ]
        else:
            tool = choose_tool_for_operation(op, env)
        if not tool:
            warnings.append(f"No tool found for intent {op.intent.id}")
            if mask_reasons_out is not None:
                mask_reasons_out.append(
                    Violation(
                        code="INTENT_NO_TOOL",
                        message=f"No tool found for intent {op.intent.id}",
                        severity="warn",
                        blocking=False,
                        where=ViolationLocation(component="planner", stage="preflight"),
                        details={"intent": op.intent.id},
                    )
                )
            return None
        canonical_tool_name = _canonical_tool_id(tool.id)
        if allowed_tool_ids is not None and canonical_tool_name not in allowed_tool_ids:
            warnings.append(f"Tool {tool.id} is not permitted by the active allowlist")
            if mask_reasons_out is not None:
                mask_reasons_out.append(
                    Violation(
                        code="TOOL_NOT_ALLOWED",
                        message="Tool is not permitted by the active allowlist",
                        severity="error",
                        blocking=True,
                        where=ViolationLocation(component="planner", stage="preflight"),
                        details={
                            "tool_id": canonical_tool_name,
                            "intent": op.intent.id,
                        },
                    )
                )
            return None

        runtime = getattr(tool, "runtime_kind", "container")
        if runtime not in {"container", "python", "api"}:
            if runtime == "mcp":
                warnings.append("runtime_kind 'mcp' mapped to 'api' for StepSpec")
                runtime = "api"
            else:
                runtime = "api"
            if mask_reasons_out is not None:
                mask_reasons_out.append(
                    Violation(
                        code="RUNTIME_KIND_MAPPED",
                        message="Runtime kind mapped to supported value",
                        severity="warn",
                        blocking=False,
                        where=ViolationLocation(component="planner", stage="preflight"),
                        details={
                            "original": getattr(tool, "runtime_kind", None),
                            "mapped": runtime,
                        },
                    )
                )

        step = StepSpec(
            id=f"step-{idx+1:03d}",
            tool=canonical_tool_name,
            params=request.inputs or {},
            consumes={},
            produces={},
            metadata={"intent": op.intent.id},
            runtime_kind=runtime,
        )
        steps.append(step)

    plan = Plan(
        plan_id=str(uuid.uuid4()),
        domain=request.domain,
        modality=request.modality,
        resolvable=True,
        dag=PlanDAG(steps=steps, artifacts=[]),
        warnings=warnings,
        intent=[op.intent.id for op in operations],
        candidates=None,
        chosen_tool=steps[0].tool if steps else None,
        selection_reason="Selected via intent/implementation router",
        selection_reasons=debug_rows if return_debug else None,
        mask_reasons=mask_reasons_out or None,
        timestamp=int(time.time()),
        mode="catalog",
    )
    return plan


def explain_selection(candidate: SelectionCandidate, verbose: bool = False) -> str:
    """Generate human-readable explanation of selection scoring.

    PR-3: Enhanced with resource fit scoring and brief explanation.

    Args:
        candidate: SelectionCandidate to explain
        verbose: If True, include detailed preflight checks

    Returns:
        Multi-line explanation string

    Examples:
        >>> candidate = select_tools("skull strip")[0]
        >>> print(explain_selection(candidate))
        Tool: fsl_bet (BET - Brain Extraction Tool)
        Final Score: 0.85
        Explanation: Excellent match for query; ready to use; all resources available

        Component Scores:
        - Intent Match: 0.90
        - Preflight: PASSED
        - Description Relevance: 0.80
        - Metadata Quality: 0.70
        - Resource Fit: 0.95
    """
    lines = [
        f"Tool: {candidate.tool.id} ({candidate.tool.name})",
        f"Final Score: {candidate.final_score:.2f}",
        f"Explanation: {candidate.explanation}",
        "",
        "Component Scores:",
        f"- Intent Match: {candidate.intent_match_score:.2f}",
        f"- Preflight: {'PASSED' if candidate.preflight_passed else 'FAILED'}",
        f"- Description Relevance: {candidate.description_score:.2f}",
        f"- Metadata Quality: {candidate.metadata_score:.2f}",
        f"- Resource Fit: {candidate.resource_fit_score:.2f}",  # PR-3
    ]

    if verbose:
        lines.append("")
        lines.append("Preflight Checks:")
        for check_name, detail in candidate.preflight_detail.items():
            detail_lower = detail.lower() if detail else ""
            status = (
                "✓"
                if "passed" in detail_lower or "not-required" in detail_lower
                else "✗"
            )
            lines.append(f"{status} {check_name}: {detail}")

    return "\n".join(lines)
