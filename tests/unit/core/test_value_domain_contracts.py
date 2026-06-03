"""Unit tests for general value-domain execution contracts (P1)."""

from __future__ import annotations

import numpy as np
import pytest

from brain_researcher.core.analysis.value_domain_contracts import (
    safe_log,
    safe_logit,
    validate_finite,
    validate_positive_for_log,
    validate_probability_domain,
    validate_well_conditioned,
)


# --- validate_finite --------------------------------------------------------


def test_validate_finite_passes_on_finite_data():
    diag = validate_finite([0.1, -3.0, 42.0], "scores")
    assert diag["n_finite"] == 3
    assert diag["n_nan"] == 0 and diag["n_inf"] == 0


def test_validate_finite_raises_on_nan_and_inf():
    with pytest.raises(ValueError, match="non-finite"):
        validate_finite([1.0, np.nan, np.inf], "scores")


def test_validate_finite_raises_on_empty():
    with pytest.raises(ValueError, match="empty"):
        validate_finite([], "scores")


# --- validate_probability_domain / safe_logit -------------------------------


def test_validate_probability_domain_allows_unit_interval_including_boundaries():
    diag = validate_probability_domain([0.0, 0.5, 1.0], "pvals")
    assert diag["min"] == 0.0 and diag["max"] == 1.0
    assert diag["outside_unit_interval_count"] == 0


def test_validate_probability_domain_raises_above_one():
    # classic p / 1-p / -log10(p) confusion
    with pytest.raises(ValueError, match=r"outside \[0, 1\]|1-p"):
        validate_probability_domain([0.2, 1.7, 0.4], "pvals")


def test_validate_probability_domain_raises_below_zero():
    with pytest.raises(ValueError, match=r"outside \[0, 1\]"):
        validate_probability_domain([-0.01, 0.3], "proportions")


def test_safe_logit_refuses_out_of_domain_but_clamps_boundaries():
    with pytest.raises(ValueError):
        safe_logit([0.5, 1.2], "p")

    z, diag = safe_logit([0.0, 0.5, 1.0], "p", return_diagnostics=True)
    assert np.isfinite(z).all()
    assert diag["boundary_clamp_count"] == 2


# --- validate_positive_for_log / safe_log -----------------------------------


def test_validate_positive_for_log_raises_on_nonpositive():
    with pytest.raises(ValueError, match="non-positive"):
        validate_positive_for_log([1.0, 0.0, 2.0], "signal")


def test_validate_positive_for_log_allow_zero_for_sqrt():
    diag = validate_positive_for_log([0.0, 1.0, 4.0], "signal", allow_zero=True)
    assert diag["nonpositive_count"] == 0
    with pytest.raises(ValueError, match="negative"):
        validate_positive_for_log([-0.1, 1.0], "signal", allow_zero=True)


def test_safe_log_matches_numpy_on_valid_input():
    x = [1.0, np.e, 10.0]
    np.testing.assert_allclose(safe_log(x, "signal"), np.log(x))
    with pytest.raises(ValueError):
        safe_log([1.0, -2.0], "signal")


# --- validate_well_conditioned ----------------------------------------------


def test_validate_well_conditioned_passes_on_identity():
    diag = validate_well_conditioned(np.eye(3), "cov")
    assert diag["condition_number"] == pytest.approx(1.0)
    assert diag["min_eig"] == pytest.approx(1.0)


def test_validate_well_conditioned_raises_on_near_singular():
    near_singular = np.array([[1.0, 1.0], [1.0, 1.0 + 1e-15]])
    with pytest.raises(ValueError, match="near-singular"):
        validate_well_conditioned(near_singular, "cov")


def test_validate_well_conditioned_raises_on_negative_eigenvalue():
    # symmetric but indefinite -> not a valid covariance
    indefinite = np.array([[1.0, 2.0], [2.0, 1.0]])
    with pytest.raises(ValueError, match="negative eigenvalue|positive semi"):
        validate_well_conditioned(indefinite, "cov")


def test_validate_well_conditioned_raises_on_non_square():
    with pytest.raises(ValueError, match="square"):
        validate_well_conditioned(np.ones((2, 3)), "cov")
