"""Review-gate detector for recorded value-domain contract violations.

Complements the matrix-specific ``REVIEW_MATRIX_PARTIAL_SINGULAR`` detector in
``correlation_validity`` by surfacing violations from the general value-domain
contracts (``core.analysis.value_domain_contracts``) when a tool records them
into ``review_context.value_domain_diagnostics`` instead of raising on the hot
path. This closes the "detection without propagation" gap for the
finite / probability / positivity / conditioning domains.

Expected ``review_context.value_domain_diagnostics`` shape: a list of entries
::

    {"name": "mahalanobis_covariance", "contract": "well_conditioned",
     "ok": false, "severity": "critical", "detail": "condition number=..."}

Entries with ``ok`` falsy (or ``status`` in {"violation", "raised", "failed"})
are treated as violations.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from brain_researcher.core.contracts.code_review import CodeReviewBundle, ReviewFinding

_VALUE_DOMAIN_DIAGNOSTICS_KEYS = (
    "value_domain_diagnostics",
    "value_domain_violations",
    "value_domain_contract_diagnostics",
)
_VIOLATION_STATUS_TOKENS = frozenset({"violation", "raised", "failed", "violated"})
_VALUE_DOMAIN_REASON_TAGS = ("value_domain", "data_contract")


def _review_contexts(bundle: CodeReviewBundle) -> list[Mapping[str, Any]]:
    contexts: list[Mapping[str, Any]] = []
    direct = getattr(bundle, "review_context", None)
    if isinstance(direct, Mapping):
        contexts.append(direct)
    artifacts = getattr(bundle, "artifacts", None)
    if isinstance(artifacts, Mapping):
        for key in ("review_context", "analysis_bundle"):
            nested = artifacts.get(key)
            if isinstance(nested, Mapping):
                inner = nested.get("review_context", nested)
                if isinstance(inner, Mapping):
                    contexts.append(inner)
    return contexts


def _collect_diagnostics(bundle: CodeReviewBundle) -> list[Mapping[str, Any]]:
    entries: list[Mapping[str, Any]] = []
    for context in _review_contexts(bundle):
        for key in _VALUE_DOMAIN_DIAGNOSTICS_KEYS:
            value = context.get(key)
            if isinstance(value, list):
                entries.extend(item for item in value if isinstance(item, Mapping))
    return entries


def _is_violation(entry: Mapping[str, Any]) -> bool:
    if "ok" in entry:
        return not bool(entry.get("ok"))
    status = str(entry.get("status") or "").strip().lower()
    return status in _VIOLATION_STATUS_TOKENS


def value_domain_contract_violation_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Block on any recorded value-domain contract violation.

    Fires only on explicit recorded diagnostics; never infers from prose. A
    ``critical`` entry yields a critical finding (which blocks regardless of
    claim mode); otherwise the finding is ``error``/block.
    """

    violations = [entry for entry in _collect_diagnostics(bundle) if _is_violation(entry)]
    if not violations:
        return None

    severities = {str(v.get("severity") or "error").strip().lower() for v in violations}
    severity = "critical" if "critical" in severities else "error"

    evidence: list[str] = []
    for v in violations:
        name = str(v.get("name") or "value")
        contract = str(v.get("contract") or "value_domain")
        detail = str(v.get("detail") or v.get("message") or "violation")
        evidence.append(f"{contract}:{name} -> {detail}")

    return ReviewFinding(
        rule_id="REVIEW_VALUEDOMAIN_CONTRACT_VIOLATION",
        severity=severity,
        action="block",
        message=(
            f"{len(violations)} value-domain contract violation(s) recorded "
            "(non-finite, out-of-domain, or near-singular input). The affected "
            "result is invalid; do not interpret it."
        ),
        suggested_fix=(
            "Fix the upstream value-domain violation rather than repairing it "
            "silently: regularize/condition the matrix, restrict inputs to the "
            "valid domain (e.g. probabilities in [0, 1], positive values before "
            "log), or remove non-finite values at the source."
        ),
        kg_evidence=evidence,
        reason_tags=list(_VALUE_DOMAIN_REASON_TAGS),
    )
