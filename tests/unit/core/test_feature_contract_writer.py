"""Unit tests for the FeatureContract dataclass / writer / diagnostics."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from brain_researcher.core.analysis.connectivity_contracts import (
    build_feature_contract,
    compute_estimator_diagnostics,
    write_feature_contract,
)


@pytest.mark.unit
def test_compute_estimator_diagnostics_well_conditioned():
    matrix = np.eye(4)
    diag = compute_estimator_diagnostics(matrix)
    assert diag["rank"] == 4
    assert np.isfinite(diag["condition_number"])
    assert diag["min_eig"] == pytest.approx(1.0)


@pytest.mark.unit
def test_compute_estimator_diagnostics_singular_matrix():
    matrix = np.ones((3, 3))
    diag = compute_estimator_diagnostics(matrix)
    assert diag["rank"] < 3
    assert diag["min_eig"] < 1e-6


@pytest.mark.unit
def test_write_feature_contract_round_trip(tmp_path: Path):
    matrix = np.eye(8) * 0.9 + 0.1
    contract = build_feature_contract(
        matrix,
        matrix_kind="partial_correlation",
        source_level="roi_timeseries",
        n_timepoints=240,
        covariance_estimator="LedoitWolf",
    )
    path = write_feature_contract(contract, tmp_path)
    assert path.exists()
    payload = json.loads(path.read_text())
    assert payload["matrix_kind"] == "partial_correlation"
    assert payload["n_rois"] == 8
    assert payload["n_timepoints"] == 240
    assert payload["effective_n_timepoints"] == 240
    assert payload["precision_estimator"] == "LedoitWolf"
    assert payload["regularization"] == "regularized"
    assert payload["precision_rank"] == 8
    assert (
        isinstance(payload["contract_sha256"], str)
        and len(payload["contract_sha256"]) == 64
    )
    assert isinstance(payload["generated_at"], str)


@pytest.mark.unit
def test_build_feature_contract_correlation_uses_covariance_slot():
    matrix = np.eye(5)
    contract = build_feature_contract(
        matrix,
        matrix_kind="correlation",
        source_level="roi_timeseries",
        n_timepoints=200,
        covariance_estimator="EmpiricalCovariance",
    )
    assert contract.precision_estimator is None
    assert contract.covariance_estimator == "EmpiricalCovariance"
    assert contract.regularization == "unregularized"
    assert contract.covariance_rank == 5
    assert contract.precision_rank is None
