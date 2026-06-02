"""Tests for the rapidtide canonical-method critic (P1.4b)."""

from __future__ import annotations

import pytest

from brain_researcher.services.review.rapidtide_critic import (
    review_rapidtide_implementation,
)


def _canonical_contract() -> dict:
    """A method contract that matches the canonical rapidtide method."""
    return {
        "cross_correlation_lag_search": True,
        "lag_search_range_s": [-10.0, 10.0],
        "refinement_passes": 3,
        "regressor_source": "refined_sLFO",
        "temporal_filter_band_hz": [0.009, 0.15],
        "oversample_factor": 4,
        "tr_s": 2.0,
        "lag_map_despeckle": True,
    }


def _rule_ids(verdict) -> set[str]:
    return {f.rule_id for f in verdict.findings}


@pytest.mark.unit
def test_canonical_contract_approves():
    verdict = review_rapidtide_implementation(
        task_profile="sLFO_delay_mapping", method_contract=_canonical_contract()
    )
    assert verdict.decision == "approve"
    assert verdict.findings == []


@pytest.mark.unit
def test_static_zero_lag_blocks():
    contract = _canonical_contract()
    contract["cross_correlation_lag_search"] = False
    verdict = review_rapidtide_implementation(
        task_profile="sLFO_delay_mapping", method_contract=contract
    )
    assert verdict.decision == "block"
    assert verdict.risk_level == "critical"
    assert "RAPIDTIDE_STATIC_ZERO_LAG_CORRELATION" in _rule_ids(verdict)


@pytest.mark.unit
def test_narrow_lag_range_blocks():
    contract = _canonical_contract()
    contract["lag_search_range_s"] = [-2.0, 2.0]  # 4 s span < 8 s
    verdict = review_rapidtide_implementation(
        task_profile="sLFO_delay_mapping", method_contract=contract
    )
    assert verdict.decision == "block"
    assert "RAPIDTIDE_LAG_SEARCH_RANGE_TOO_NARROW" in _rule_ids(verdict)


@pytest.mark.unit
def test_missing_lag_range_blocks():
    contract = _canonical_contract()
    del contract["lag_search_range_s"]
    verdict = review_rapidtide_implementation(
        task_profile="sLFO_delay_mapping", method_contract=contract
    )
    assert "RAPIDTIDE_LAG_SEARCH_RANGE_MISSING" in _rule_ids(verdict)
    assert verdict.decision == "block"


@pytest.mark.unit
def test_no_refinement_is_revise():
    contract = _canonical_contract()
    contract["refinement_passes"] = 1
    verdict = review_rapidtide_implementation(
        task_profile="sLFO_delay_mapping", method_contract=contract
    )
    assert "RAPIDTIDE_NO_REGRESSOR_REFINEMENT" in _rule_ids(verdict)
    assert verdict.decision == "revise"


@pytest.mark.unit
def test_naive_global_regressor_warns():
    contract = _canonical_contract()
    contract["regressor_source"] = "global_mean"
    contract["refinement_passes"] = 1
    verdict = review_rapidtide_implementation(
        task_profile="sLFO_delay_mapping", method_contract=contract
    )
    assert "RAPIDTIDE_NAIVE_GLOBAL_REGRESSOR" in _rule_ids(verdict)


@pytest.mark.unit
def test_wide_filter_band_and_oversampling_warn():
    contract = _canonical_contract()
    contract["temporal_filter_band_hz"] = [0.01, 0.5]  # includes cardiac/resp
    contract["tr_s"] = 3.0
    contract["oversample_factor"] = 1
    verdict = review_rapidtide_implementation(
        task_profile="sLFO_delay_mapping", method_contract=contract
    )
    ids = _rule_ids(verdict)
    assert "RAPIDTIDE_FILTER_BAND_OUTSIDE_LFO" in ids
    assert "RAPIDTIDE_INSUFFICIENT_OVERSAMPLING" in ids
    assert verdict.decision == "approve_with_warnings"


@pytest.mark.unit
def test_observable_boundary_railing_blocks():
    verdict = review_rapidtide_implementation(
        task_profile="sLFO_delay_mapping",
        method_contract=_canonical_contract(),
        subject_summaries=[{"subject": "sub-01", "lag_boundary_fraction": 0.3}],
    )
    finding = next(
        f for f in verdict.findings if f.rule_id == "RAPIDTIDE_LAG_RAILING_AT_BOUNDARY"
    )
    assert finding.artifact_name == "sub-01"
    assert verdict.decision == "block"


@pytest.mark.unit
def test_requires_task_profile_and_object_contract():
    with pytest.raises(ValueError):
        review_rapidtide_implementation(task_profile="", method_contract={})
    with pytest.raises(ValueError):
        review_rapidtide_implementation(task_profile="x", method_contract=None)
