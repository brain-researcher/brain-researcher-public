"""Method -> value-domain-contract routing and record-or-raise evaluation.

Two responsibilities, layered on the pure contracts in
``value_domain_contracts``:

1. ``contracts_for(tool_or_method)`` — declarative router mapping a tool id or
   method name to the value-domain contracts that apply to it, so a pipeline
   can auto-select the right checks instead of hard-coding them per call site.

2. ``evaluate_value_domain(...)`` — the record-or-raise primitive. In strict
   mode it raises (fail-fast execution gate, no silent repair). In lenient mode
   it records a diagnostics entry into a sink instead of raising, so the run can
   complete and the review-gate detector
   (``checks.value_domain.value_domain_contract_violation_check``) surfaces the
   violation as a blocking finding on a *succeeded* run. Either way the
   recorded entry shape matches ``review_context.value_domain_diagnostics``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from brain_researcher.core.analysis.value_domain_contracts import (
    validate_finite,
    validate_positive_for_log,
    validate_probability_domain,
    validate_well_conditioned,
)

# Contract name -> validator. Names match review_context diagnostics + registry.
CONTRACT_VALIDATORS: dict[str, Callable[..., dict[str, Any]]] = {
    "finite": validate_finite,
    "probability_domain": validate_probability_domain,
    "positive_for_log": validate_positive_for_log,
    "well_conditioned": validate_well_conditioned,
}

# A violation of these contracts invalidates the result itself (blocks
# regardless of claim mode via the P0.1 critical carve-out); others are errors.
_CRITICAL_CONTRACTS = frozenset({"well_conditioned", "finite"})

# Tool id / method-name token -> contracts that apply. Matched on a normalized
# substring so aliases ("sem", "structural_equation_modeling") resolve together.
_METHOD_CONTRACTS: dict[str, tuple[str, ...]] = {
    "multimodal_fusion": ("well_conditioned",),
    "mahalanobis": ("well_conditioned",),
    "structural_equation": ("well_conditioned",),
    "sem": ("well_conditioned",),
    "covariance": ("well_conditioned",),
    "precision": ("well_conditioned",),
    "graphical_lasso": ("well_conditioned",),
    "qsm": ("positive_for_log",),
    "log_transform": ("positive_for_log",),
    "boxcox": ("positive_for_log",),
    "classifier": ("probability_domain",),
    "classification": ("probability_domain",),
    "predict_proba": ("probability_domain",),
    "pvalue": ("probability_domain",),
    "fdr": ("probability_domain",),
}


def _normalize(token: Any) -> str:
    return str(token or "").strip().lower().replace("-", "_").replace(" ", "_")


def contracts_for(tool_or_method: Any) -> tuple[str, ...]:
    """Return the value-domain contracts that apply to a tool id / method name.

    Matching is by normalized substring so ``"run_structural_equation_modeling"``
    resolves to the ``structural_equation`` entry. Returns an order-preserving,
    de-duplicated tuple; empty when nothing matches.
    """

    key = _normalize(tool_or_method)
    if not key:
        return ()
    selected: list[str] = []
    for token, contracts in _METHOD_CONTRACTS.items():
        if token in key:
            for contract in contracts:
                if contract not in selected:
                    selected.append(contract)
    return tuple(selected)


def _severity_for(contract: str) -> str:
    return "critical" if contract in _CRITICAL_CONTRACTS else "error"


def evaluate_value_domain(
    contract: str,
    values: Any,
    name: str,
    *,
    strict: bool = True,
    sink: list[dict[str, Any]] | None = None,
    **kwargs: Any,
) -> bool:
    """Run a named contract, recording the outcome and optionally raising.

    - ``strict=True`` (default): re-raise the contract's ``ValueError`` after
      recording the violation (fail-fast execution gate).
    - ``strict=False``: record the violation into ``sink`` and return ``False``
      so the caller can continue; the review-gate detector will then block on a
      succeeded run.

    On success a ``{"ok": True}`` entry is recorded. Returns ``True`` on success.
    """

    if contract not in CONTRACT_VALIDATORS:
        raise KeyError(f"Unknown value-domain contract: {contract!r}")
    validator = CONTRACT_VALIDATORS[contract]

    try:
        diagnostics = validator(values, name, **kwargs)
    except ValueError as exc:
        if sink is not None:
            sink.append(
                {
                    "name": str(name),
                    "contract": contract,
                    "ok": False,
                    "severity": _severity_for(contract),
                    "detail": str(exc),
                }
            )
        if strict:
            raise
        return False

    if sink is not None:
        sink.append(
            {
                "name": str(name),
                "contract": contract,
                "ok": True,
                "diagnostics": diagnostics,
            }
        )
    return True


def write_value_domain_diagnostics(
    sink: list[dict[str, Any]],
    output_dir: str | Path,
    *,
    filename: str = "value_domain_diagnostics.json",
) -> Path:
    """Write the recorded diagnostics ``sink`` as a review sidecar.

    The bundle builder discovers ``value_domain_diagnostics.json`` under a run
    directory and merges it into ``review_context.value_domain_diagnostics``,
    where the review-gate detector reads it. Mirrors ``write_feature_contract``.
    """

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / filename
    target.write_text(
        json.dumps(list(sink), indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return target
