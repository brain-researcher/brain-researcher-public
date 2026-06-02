"""P1.2: execution-gate wiring + review-gate detector for value domains."""

from __future__ import annotations

import numpy as np
import pytest

from brain_researcher.core.contracts.code_review import CodeReviewBundle
from brain_researcher.services.review.checks.value_domain import (
    value_domain_contract_violation_check,
)


def _bundle(review_context: dict | None = None) -> CodeReviewBundle:
    return CodeReviewBundle(
        plan_steps=[],
        declared_modalities=[],
        declared_spaces=[],
        review_context=review_context or {},
    )


# --- review-gate detector ---------------------------------------------------


@pytest.mark.unit
def test_detector_blocks_on_recorded_violation():
    finding = value_domain_contract_violation_check(
        _bundle(
            {
                "value_domain_diagnostics": [
                    {"name": "cov", "contract": "well_conditioned", "ok": True},
                    {
                        "name": "mahalanobis_covariance",
                        "contract": "well_conditioned",
                        "ok": False,
                        "severity": "critical",
                        "detail": "condition number=1e12 > 1e10",
                    },
                ]
            }
        )
    )

    assert finding is not None
    assert finding.rule_id == "REVIEW_VALUEDOMAIN_CONTRACT_VIOLATION"
    assert finding.action == "block"
    # critical -> blocks regardless of claim mode (see P0.1)
    assert finding.severity == "critical"
    assert any("mahalanobis_covariance" in item for item in finding.kg_evidence)


@pytest.mark.unit
def test_detector_defaults_to_error_severity_without_critical():
    finding = value_domain_contract_violation_check(
        _bundle(
            {
                "value_domain_diagnostics": [
                    {"name": "p", "contract": "probability_domain", "status": "failed"}
                ]
            }
        )
    )
    assert finding is not None
    assert finding.severity == "error"


@pytest.mark.unit
def test_detector_silent_when_all_ok_or_absent():
    assert value_domain_contract_violation_check(_bundle({})) is None
    assert (
        value_domain_contract_violation_check(
            _bundle({"value_domain_diagnostics": [{"name": "x", "ok": True}]})
        )
        is None
    )


# --- execution-gate wiring (tools refuse near-singular covariance) ----------


@pytest.mark.unit
def test_mahalanobis_similarity_refuses_near_singular_covariance():
    from brain_researcher.services.tools.multimodal_fusion_tool import (
        MultimodalFusionTool,
        SimilarityMetric,
    )

    tool = MultimodalFusionTool()
    # rank-deficient: 3 samples, 5 features -> singular covariance
    fused = np.tile(np.array([1.0, 2.0, 3.0, 4.0, 5.0]), (3, 1))
    with pytest.raises(ValueError, match="near-singular|negative eigenvalue"):
        tool._compute_similarity(fused, SimilarityMetric.MAHALANOBIS)


@pytest.mark.unit
def test_mahalanobis_similarity_allows_well_conditioned_covariance():
    from brain_researcher.services.tools.multimodal_fusion_tool import (
        MultimodalFusionTool,
        SimilarityMetric,
    )

    tool = MultimodalFusionTool()
    rng = np.random.default_rng(0)
    fused = rng.normal(size=(40, 4))
    matrix, label = tool._compute_similarity(fused, SimilarityMetric.MAHALANOBIS)
    assert label == "mahalanobis_similarity"
    assert np.isfinite(matrix).all()
