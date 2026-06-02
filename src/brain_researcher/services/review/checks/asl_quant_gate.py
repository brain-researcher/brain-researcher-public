"""Review-gate adapter for the ASL quantification critic.

The ASL critic (``asl_quant_critic.review_asl_quant``) produces a full verdict
with multiple findings, and was retired from the public MCP tool surface. This
adapter runs it inside the scientific-review gate when an ASL quantification
contract is present in the bundle's ``review_context``, folding its findings
into the correctness findings (it is not a single-finding ``check_fn``).

Expected ``review_context.asl_quant`` (or ``asl_quantification``) shape::

    {
      "task_profile": "asl_cbf_quantification",
      "method_contract": { ... },          # required
      "subject_summaries": [ { ... }, ... ] # required, non-empty
    }

Missing/ill-formed inputs cause the adapter to skip silently (no findings),
matching the gate's "fire only on explicit provenance" policy.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from brain_researcher.core.contracts.code_review import CodeReviewBundle, ReviewFinding

_ASL_CONTRACT_KEYS = ("asl_quant", "asl_quantification")


def _review_contexts(bundle: CodeReviewBundle) -> list[Mapping[str, Any]]:
    contexts: list[Mapping[str, Any]] = []
    direct = getattr(bundle, "review_context", None)
    if isinstance(direct, Mapping):
        contexts.append(direct)
    artifacts = getattr(bundle, "observed_artifacts", None)
    if isinstance(artifacts, Mapping):
        for key in ("review_context", "analysis_bundle"):
            nested = artifacts.get(key)
            if isinstance(nested, Mapping):
                inner = nested.get("review_context", nested)
                if isinstance(inner, Mapping):
                    contexts.append(inner)
    return contexts


def _asl_contract(bundle: CodeReviewBundle) -> Mapping[str, Any] | None:
    for context in _review_contexts(bundle):
        for key in _ASL_CONTRACT_KEYS:
            candidate = context.get(key)
            if isinstance(candidate, Mapping):
                return candidate
    return None


def asl_quantification_findings(bundle: CodeReviewBundle) -> list[ReviewFinding]:
    """Run the ASL critic from review_context; return its findings (or [])."""

    contract = _asl_contract(bundle)
    if contract is None:
        return []

    method_contract = contract.get("method_contract")
    subject_summaries = contract.get("subject_summaries")
    task_profile = contract.get("task_profile") or "asl_quantification"
    if not isinstance(method_contract, dict):
        return []
    if not isinstance(subject_summaries, list) or not subject_summaries:
        return []

    try:
        from brain_researcher.services.review.asl_quant_critic import review_asl_quant

        verdict = review_asl_quant(
            task_profile=str(task_profile),
            method_contract=method_contract,
            subject_summaries=subject_summaries,
            cohort_summary=(
                contract.get("cohort_summary")
                if isinstance(contract.get("cohort_summary"), dict)
                else None
            ),
        )
    except Exception:
        return []
    return list(verdict.findings)
