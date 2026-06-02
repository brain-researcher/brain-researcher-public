"""Statistical method appropriateness checks for plan-time review.

B2.5: General-purpose design↔method compatibility check.  Any (design, method)
pair is looked up via KG graph edges first, then the curated YAML seed.  The
check is data-driven — adding new rules only requires editing the seed file.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import Any

import yaml

from brain_researcher.core.contracts.code_review import CodeReviewBundle, ReviewFinding

logger = logging.getLogger(__name__)

from brain_researcher.config.paths import get_config_root

_SEED_PATH = get_config_root() / "br-kg" / "method_compatibility_seed.yaml"


# ---------------------------------------------------------------------------
# Seed loading (cached)
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def _load_seed() -> dict[str, Any]:
    try:
        return yaml.safe_load(_SEED_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        logger.warning("Could not load method compatibility seed from %s", _SEED_PATH)
        return {}


@functools.lru_cache(maxsize=1)
def _load_design_aliases() -> dict[str, list[str]]:
    """Return {canonical_design: [alias, ...]} from seed."""
    seed = _load_seed()
    raw = seed.get("design_aliases") or {}
    result: dict[str, list[str]] = {}
    for canonical, aliases in raw.items():
        canonical = str(canonical).strip().lower()
        result[canonical] = [str(a).strip().lower() for a in (aliases or [])]
    return result


@functools.lru_cache(maxsize=1)
def _load_method_aliases() -> dict[str, list[str]]:
    """Return {canonical_method: [alias, ...]} from seed."""
    seed = _load_seed()
    raw = seed.get("method_aliases") or {}
    result: dict[str, list[str]] = {}
    for canonical, aliases in raw.items():
        canonical = str(canonical).strip().lower()
        result[canonical] = [str(a).strip().lower() for a in (aliases or [])]
    return result


def _resolve_canonical(text: str, alias_map: dict[str, list[str]]) -> str | None:
    """Resolve *text* to a canonical key using *alias_map*."""
    text_lower = text.strip().lower()
    # Direct match on canonical key.
    if text_lower in alias_map:
        return text_lower
    # Search aliases.
    for canonical, aliases in alias_map.items():
        if text_lower in aliases or text_lower == canonical:
            return canonical
    return None


# ---------------------------------------------------------------------------
# Inference helpers
# ---------------------------------------------------------------------------


def _collect_text_hints(bundle: CodeReviewBundle) -> list[str]:
    hints: list[str] = []
    for step in bundle.plan_steps:
        tool = str(step.get("tool") or "").strip()
        if tool:
            hints.append(tool)
        params = step.get("params") if isinstance(step.get("params"), dict) else {}
        for value in params.values():
            if isinstance(value, str) and value.strip():
                hints.append(value.strip())
            elif isinstance(value, bool):
                hints.append("true" if value else "false")
    for value in bundle.kg_context.values():
        if isinstance(value, str) and value.strip():
            hints.append(value.strip())
    return hints


_DESIGN_PARAM_KEYS: dict[str, str] = {
    "within_subject": "repeated_measures",
    "within_subjects": "repeated_measures",
    "repeated_measures": "repeated_measures",
    "between_subject": "independent_groups",
    "between_subjects": "independent_groups",
    "independent_groups": "independent_groups",
    "one_sample": "one_sample",
    "factorial": "factorial",
    "mixed_design": "mixed_design",
    "longitudinal": "longitudinal",
    "correlation": "correlation",
}


def _infer_design_type(bundle: CodeReviewBundle) -> tuple[str | None, list[str]]:
    hints = _collect_text_hints(bundle)
    design_aliases = _load_design_aliases()

    # 1. Explicit boolean params.
    for step in bundle.plan_steps:
        params = step.get("params") if isinstance(step.get("params"), dict) else {}
        for param_key, canonical in _DESIGN_PARAM_KEYS.items():
            if bool(params.get(param_key)):
                return canonical, hints

    # 2. Explicit design_type param.
    for step in bundle.plan_steps:
        params = step.get("params") if isinstance(step.get("params"), dict) else {}
        explicit = params.get("design_type") or params.get("design")
        if isinstance(explicit, str) and explicit.strip():
            resolved = _resolve_canonical(explicit, design_aliases)
            if resolved:
                return resolved, hints

    # 3. Text matching against all aliases.
    joined = " ".join(hints).lower()
    for canonical, aliases in design_aliases.items():
        if canonical in joined:
            return canonical, hints
        for alias in aliases:
            if alias in joined:
                return canonical, hints
    return None, hints


def _infer_method_type(bundle: CodeReviewBundle) -> tuple[str | None, list[str]]:
    hints = _collect_text_hints(bundle)
    method_aliases = _load_method_aliases()

    # 1. Explicit statistical_method / test_type / method param.
    for step in bundle.plan_steps:
        params = step.get("params") if isinstance(step.get("params"), dict) else {}
        explicit = (
            params.get("statistical_method")
            or params.get("test_type")
            or params.get("method")
        )
        if isinstance(explicit, str) and explicit.strip():
            resolved = _resolve_canonical(explicit, method_aliases)
            if resolved:
                return resolved, hints

    # 2. Tool name matching.
    for step in bundle.plan_steps:
        tool = str(step.get("tool") or "").strip().lower()
        if not tool:
            continue
        resolved = _resolve_canonical(tool, method_aliases)
        if resolved:
            return resolved, hints

    # 3. Text matching against all aliases.
    joined = " ".join(hints).lower()
    for canonical, aliases in method_aliases.items():
        if canonical in joined:
            return canonical, hints
        for alias in aliases:
            if alias in joined:
                return canonical, hints
    return None, hints


# ---------------------------------------------------------------------------
# KG helper (optional, lazy import)
# ---------------------------------------------------------------------------


def _lookup_optional_kg_helper() -> Callable[..., Any] | None:
    try:
        query_service = import_module("brain_researcher.services.br_kg.query_service")
    except Exception:
        return None

    for attr_name in (
        "get_method_compatibility",
        "get_method_compatibility_priors",
        "get_method_compatibility_seed",
        "get_statistical_method_compatibility",
    ):
        helper = getattr(query_service, attr_name, None)
        if callable(helper):
            return helper
    return None


def _lookup_optional_kg_db() -> Any | None:
    try:
        query_service = import_module("brain_researcher.services.br_kg.query_service")
    except Exception:
        return None

    get_default_db = getattr(query_service, "get_default_db", None)
    if not callable(get_default_db):
        return None

    try:
        return get_default_db()
    except Exception:
        return None


def _query_kg_helper(
    bundle: CodeReviewBundle,
    design_type: str,
    method_type: str,
) -> dict[str, Any] | None:
    helper = _lookup_optional_kg_helper()
    if helper is None:
        return None

    db = _lookup_optional_kg_db()
    task = str(bundle.kg_context.get("task") or "").strip() or None
    study_id = str(bundle.kg_context.get("study_id") or "").strip() or None
    analysis_family = (
        str(bundle.kg_context.get("analysis_family") or "").strip() or None
    )
    design_label = str(bundle.kg_context.get("design_type") or design_type)
    method_label = str(bundle.kg_context.get("statistical_method") or method_type)

    call_variants: list[dict[str, Any]] = []
    if db is not None:
        call_variants.extend(
            [
                {
                    "task": task,
                    "study_id": study_id,
                    "analysis_family": analysis_family,
                    "design_type": design_label,
                    "statistical_method": method_label,
                    "db": db,
                },
                {
                    "design_type": design_label,
                    "statistical_method": method_label,
                    "db": db,
                },
                {
                    "design": design_label,
                    "method": method_label,
                    "db": db,
                },
            ]
        )
    call_variants.extend(
        [
            {
                "task": task,
                "study_id": study_id,
                "analysis_family": analysis_family,
                "design_type": design_label,
                "statistical_method": method_label,
            },
            {
                "design_type": design_label,
                "statistical_method": method_label,
            },
            {
                "design": design_label,
                "method": method_label,
            },
        ]
    )

    for kwargs in call_variants:
        try:
            payload = helper(**{k: v for k, v in kwargs.items() if v is not None})
        except TypeError:
            continue
        except Exception:
            return None
        if isinstance(payload, dict) and payload:
            return payload
    return None


# ---------------------------------------------------------------------------
# Seed-based compatibility lookup
# ---------------------------------------------------------------------------


def _query_seed_compatibility(
    design_type: str,
    method_type: str,
) -> dict[str, Any] | None:
    """Look up (design, method) in the curated seed rules."""
    seed = _load_seed()
    rules = seed.get("rules") or []
    design_aliases = _load_design_aliases()
    method_aliases = _load_method_aliases()

    canonical_design = _resolve_canonical(design_type, design_aliases) or design_type
    canonical_method = _resolve_canonical(method_type, method_aliases) or method_type

    for rule in rules:
        rule_design = _resolve_canonical(str(rule.get("design") or ""), design_aliases)
        rule_method = _resolve_canonical(str(rule.get("method") or ""), method_aliases)
        if rule_design == canonical_design and rule_method == canonical_method:
            return {
                "rule_id": rule.get("id", f"{canonical_design}_vs_{canonical_method}"),
                "compatible": rule.get("compatible"),
                "severity": rule.get("severity", "error"),
                "rationale": rule.get("rationale"),
                "evidence": rule.get("evidence"),
                "message": rule.get("rationale"),
                "suggested_fix": rule.get("suggested_fix"),
                "source": "seed",
            }
    return None


# ---------------------------------------------------------------------------
# Incompatibility detection
# ---------------------------------------------------------------------------


def _is_incompatible(payload: dict[str, Any]) -> bool:
    if payload.get("compatible") is False:
        return True
    status = (
        str(payload.get("status") or payload.get("compatibility") or "").strip().lower()
    )
    return status in {"incompatible", "mismatch", "disallowed", "invalid"}


# ---------------------------------------------------------------------------
# Evidence + finding builders
# ---------------------------------------------------------------------------


def _build_finding(
    payload: dict[str, Any],
    design_type: str,
    method_type: str,
    design_hints: list[str],
    method_hints: list[str],
) -> ReviewFinding:
    raw_evidence = payload.get("kg_evidence") or []
    if isinstance(raw_evidence, list):
        kg_evidence = [str(item) for item in raw_evidence if item]
    elif isinstance(raw_evidence, str) and raw_evidence.strip():
        kg_evidence = [raw_evidence.strip()]
    else:
        kg_evidence = []
    rationale = payload.get("rationale")
    if isinstance(rationale, str) and rationale.strip():
        kg_evidence.append(rationale.strip())
    structured_evidence = payload.get("evidence")
    if isinstance(structured_evidence, dict):
        for key, value in structured_evidence.items():
            if value is not None:
                kg_evidence.append(f"{key}={value}")

    rule_id = str(
        payload.get("rule_id") or f"REVIEW_{design_type}_{method_type}_MISMATCH"
    ).upper()
    source_rule_id = payload.get("rule_id")
    if source_rule_id and str(source_rule_id).upper() != rule_id:
        kg_evidence.append(f"source_rule_id={source_rule_id}")

    source = str(payload.get("source") or "curated method compatibility seed")
    confidence = payload.get("confidence")
    if confidence is not None:
        try:
            kg_evidence.append(f"{source} confidence={float(confidence):.2f}.")
        except (TypeError, ValueError):
            kg_evidence.append(f"{source} confidence={confidence}.")
    else:
        kg_evidence.append(source)
    if design_hints:
        kg_evidence.append(f"Design hints: {', '.join(sorted(set(design_hints[:8])))}.")
    if method_hints:
        kg_evidence.append(f"Method hints: {', '.join(sorted(set(method_hints[:8])))}.")

    default_message = (
        f"Design '{design_type}' is incompatible with method '{method_type}'."
    )
    default_fix = (
        "Choose a statistical method that matches the study design's "
        "independence/dependence structure."
    )

    return ReviewFinding(
        rule_id=rule_id,
        severity=str(payload.get("severity") or "error"),
        action=str(payload.get("action") or "block"),
        message=str(payload.get("message") or default_message),
        suggested_fix=str(payload.get("suggested_fix") or default_fix),
        kg_evidence=kg_evidence,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def method_appropriateness_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Flag design-method mismatches using KG edges or curated seed rules."""
    design_type, design_hints = _infer_design_type(bundle)
    method_type, method_hints = _infer_method_type(bundle)

    if design_type is None or method_type is None:
        return None

    kg_payload = _query_kg_helper(bundle, design_type, method_type)
    if kg_payload is None:
        kg_payload = _query_seed_compatibility(design_type, method_type)
    if not kg_payload or not _is_incompatible(kg_payload):
        return None

    return _build_finding(
        kg_payload, design_type, method_type, design_hints, method_hints
    )


__all__ = ["method_appropriateness_check"]
