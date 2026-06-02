"""P1.3: method->contract router + record-or-raise evaluation."""

from __future__ import annotations

import numpy as np
import pytest

from brain_researcher.core.analysis.value_domain_router import (
    contracts_for,
    evaluate_value_domain,
)

# --- router -----------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "tool,expected",
    [
        ("run_multimodal_fusion", ("well_conditioned",)),
        ("structural_equation_modeling", ("well_conditioned",)),
        ("sem", ("well_conditioned",)),
        ("qsm_tool", ("positive_for_log",)),
        ("rf_classifier", ("probability_domain",)),
        ("totally_unknown_tool", ()),
    ],
)
def test_contracts_for_routes_by_substring(tool, expected):
    assert contracts_for(tool) == expected


@pytest.mark.unit
def test_contracts_for_is_deduplicated_and_handles_empty():
    assert contracts_for("") == ()
    assert contracts_for(None) == ()
    # a name hitting two tokens for the same contract collapses to one entry
    assert contracts_for("mahalanobis_covariance") == ("well_conditioned",)


# --- record-or-raise --------------------------------------------------------


@pytest.mark.unit
def test_evaluate_strict_raises_and_records():
    sink: list[dict] = []
    with pytest.raises(ValueError):
        evaluate_value_domain(
            "probability_domain", [0.2, 1.5], "pvals", strict=True, sink=sink
        )
    assert sink and sink[0]["ok"] is False
    assert sink[0]["severity"] == "error"


@pytest.mark.unit
def test_evaluate_lenient_records_without_raising():
    sink: list[dict] = []
    ok = evaluate_value_domain(
        "well_conditioned",
        np.array([[1.0, 1.0], [1.0, 1.0 + 1e-15]]),
        "cov",
        strict=False,
        sink=sink,
    )
    assert ok is False
    assert sink[0]["ok"] is False
    assert sink[0]["severity"] == "critical"  # blocks regardless of claim mode


@pytest.mark.unit
def test_evaluate_success_records_ok_entry():
    sink: list[dict] = []
    assert evaluate_value_domain("finite", [1.0, 2.0], "x", sink=sink) is True
    assert sink[0]["ok"] is True
    assert "diagnostics" in sink[0]


@pytest.mark.unit
def test_evaluate_unknown_contract_raises_keyerror():
    with pytest.raises(KeyError):
        evaluate_value_domain("nonexistent", [1.0], "x")


# --- end-to-end: record-and-propagate to a succeeded-run blocked finding ----


@pytest.mark.unit
def test_recorded_violations_propagate_to_blocking_review_finding():
    from brain_researcher.core.contracts.code_review import CodeReviewBundle
    from brain_researcher.services.review.checks.value_domain import (
        value_domain_contract_violation_check,
    )

    sink: list[dict] = []
    # lenient: the run completes but the violation is recorded
    evaluate_value_domain(
        "well_conditioned",
        np.array([[1.0, 2.0], [2.0, 1.0]]),  # indefinite -> negative eigenvalue
        "sem_sample_covariance",
        strict=False,
        sink=sink,
    )

    bundle = CodeReviewBundle(
        plan_steps=[],
        declared_modalities=[],
        declared_spaces=[],
        review_context={"value_domain_diagnostics": sink},
    )
    finding = value_domain_contract_violation_check(bundle)

    assert finding is not None
    assert finding.rule_id == "REVIEW_VALUEDOMAIN_CONTRACT_VIOLATION"
    assert finding.severity == "critical"
    assert finding.action == "block"
    assert any("sem_sample_covariance" in item for item in finding.kg_evidence)
