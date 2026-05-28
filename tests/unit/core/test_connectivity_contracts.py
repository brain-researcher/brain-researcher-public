from __future__ import annotations

import numpy as np
import pytest

from brain_researcher.core.analysis.connectivity_contracts import (
    aggregate_estimator_diagnostics,
    build_feature_contract,
    infer_regularization_from_estimator,
    safe_fisher_z,
    validate_for_fisher_z,
)


def test_validate_for_fisher_z_refuses_values_outside_unit_interval():
    x = np.array([[0.2, 1.4], [-0.3, -1.2]])

    with pytest.raises(ValueError, match="outside \\[-1, 1\\]"):
        validate_for_fisher_z(x, "netmats1")


def test_validate_for_fisher_z_refuses_non_trivial_clipping_rate():
    x = np.random.default_rng(0).normal(size=(100, 20))

    assert (np.abs(x) > 1.0).mean() > 0
    with pytest.raises(ValueError, match="raw Pearson correlation"):
        validate_for_fisher_z(x, "netmats1")


def test_safe_fisher_z_allows_exact_correlation_boundaries_with_diagnostics():
    x = np.array([[1.0, 0.2], [0.2, 1.0]])

    z, diagnostics = safe_fisher_z(
        x,
        "correlation_matrix",
        return_diagnostics=True,
    )

    assert np.isfinite(z).all()
    assert diagnostics["outside_unit_interval_count"] == 0
    assert diagnostics["boundary_clip_count"] == 2


def test_aggregate_estimator_diagnostics_handles_matrix_stack_conservatively():
    stack = np.stack([np.eye(3), np.diag([1.0, 1.0, 1e-4])])

    diagnostics = aggregate_estimator_diagnostics(stack)

    assert diagnostics["rank"] == 3
    assert diagnostics["condition_number"] == pytest.approx(1e4)
    assert diagnostics["min_eig"] == pytest.approx(1e-4)


def test_build_feature_contract_marks_empirical_partial_as_unregularized():
    matrix = np.eye(4)[np.newaxis, ...]

    contract = build_feature_contract(
        matrix,
        matrix_kind="partial correlation",
        source_level="roi_timeseries",
        n_timepoints=20,
        covariance_estimator="EmpiricalCovariance",
    )

    assert contract.precision_estimator == "EmpiricalCovariance"
    assert contract.regularization == "unregularized"
    assert contract.precision_rank == 4
    assert contract.precision_condition_number == pytest.approx(1.0)


def test_infer_regularization_from_estimator_distinguishes_shrinkage():
    assert infer_regularization_from_estimator("LedoitWolf") == "regularized"
    assert infer_regularization_from_estimator("EmpiricalCovariance") == "unregularized"
