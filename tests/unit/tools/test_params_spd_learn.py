"""Tests for SPD learn parameter dataclasses and execution functions."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from brain_researcher.services.tools.params.spd_learn import (
    CovarianceEstimateParameters,
    SPDBiMapParameters,
    SPDGeodesicDistanceParameters,
    SPDLogmParameters,
    SPDNetTrainParameters,
    SPDProjectParameters,
    covariance_estimate_from_payload,
    run_covariance_estimate,
    run_spd_bimap,
    run_spd_geodesic_distance,
    run_spd_logm,
    run_spd_project,
    run_spdnet_train,
    spd_bimap_from_payload,
    spd_geodesic_distance_from_payload,
    spd_logm_from_payload,
    spd_project_from_payload,
    spdnet_train_from_payload,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_spd(n: int = 10, rng=None) -> np.ndarray:
    """Generate a random SPD matrix."""
    if rng is None:
        rng = np.random.default_rng(42)
    A = rng.standard_normal((n, n))
    return A @ A.T + np.eye(n) * 0.1


def _save(arr: np.ndarray, path: Path) -> Path:
    np.save(path, arr)
    return path


def _save_npz(arr: np.ndarray, path: Path) -> Path:
    np.savez_compressed(path, matrix=arr)
    return path


# ---------------------------------------------------------------------------
# 1. Covariance Estimation
# ---------------------------------------------------------------------------


class TestCovarianceEstimate:
    def test_from_payload_defaults(self):
        p = covariance_estimate_from_payload(
            {"data_file": "/tmp/ts.npy", "output_file": "/tmp/cov.npz"}
        )
        assert isinstance(p, CovarianceEstimateParameters)
        assert p.method == "empirical"
        assert p.standardize is True
        assert p.diagonal is False

    def test_from_payload_custom(self):
        p = covariance_estimate_from_payload(
            {
                "data_file": "/tmp/ts.npy",
                "output_file": "/tmp/cov.npz",
                "method": "ledoit_wolf",
                "standardize": False,
            }
        )
        assert p.method == "ledoit_wolf"
        assert p.standardize is False

    def test_run_empirical(self, tmp_path):
        ts = np.random.randn(100, 20)
        ts_path = _save(ts, tmp_path / "ts.npy")
        out_path = tmp_path / "cov.npz"

        params = CovarianceEstimateParameters(
            data_file=str(ts_path), output_file=str(out_path)
        )
        result = run_covariance_estimate(params)
        assert result["shape"] == [20, 20]
        assert out_path.exists()

    def test_run_diagonal(self, tmp_path):
        ts = np.random.randn(50, 10)
        ts_path = _save(ts, tmp_path / "ts.npy")
        out_path = tmp_path / "cov.npz"

        params = CovarianceEstimateParameters(
            data_file=str(ts_path),
            output_file=str(out_path),
            diagonal=True,
        )
        result = run_covariance_estimate(params)
        cov = np.load(out_path)["matrix"]
        # Off-diagonal should be zero
        np.testing.assert_array_equal(cov - np.diag(np.diag(cov)), 0)


# ---------------------------------------------------------------------------
# 2. SPD Projection
# ---------------------------------------------------------------------------


class TestSPDProject:
    def test_from_payload(self):
        p = spd_project_from_payload(
            {"matrix_file": "/tmp/m.npy", "output_file": "/tmp/spd.npz", "epsilon": 1e-4}
        )
        assert p.epsilon == 1e-4

    def test_run_makes_spd(self, tmp_path):
        # Create a matrix that is NOT SPD (has negative eigenvalues)
        rng = np.random.default_rng(42)
        A = rng.standard_normal((10, 10))
        mat = A + A.T  # symmetric but not necessarily PD
        mat_path = _save(mat, tmp_path / "mat.npy")
        out_path = tmp_path / "spd.npz"

        params = SPDProjectParameters(
            matrix_file=str(mat_path), output_file=str(out_path)
        )
        result = run_spd_project(params)
        assert result["is_spd"] is True
        assert result["min_eig"] > 0


# ---------------------------------------------------------------------------
# 3. Matrix Logarithm
# ---------------------------------------------------------------------------


class TestSPDLogm:
    def test_from_payload(self):
        p = spd_logm_from_payload(
            {"spd_matrix_file": "/tmp/spd.npz", "output_file": "/tmp/logm.npz"}
        )
        assert p.reference == "identity"

    def test_run_identity_reference(self, tmp_path):
        spd = _make_spd(8)
        spd_path = _save(spd, tmp_path / "spd.npy")
        out_path = tmp_path / "logm.npz"

        params = SPDLogmParameters(
            spd_matrix_file=str(spd_path), output_file=str(out_path)
        )
        result = run_spd_logm(params)
        assert result["shape"] == [8, 8]
        assert out_path.exists()

    def test_run_custom_reference(self, tmp_path):
        spd = _make_spd(6)
        ref = _make_spd(6)
        spd_path = _save(spd, tmp_path / "spd.npy")
        ref_path = _save(ref, tmp_path / "ref.npy")
        out_path = tmp_path / "logm.npz"

        params = SPDLogmParameters(
            spd_matrix_file=str(spd_path),
            output_file=str(out_path),
            reference=str(ref_path),
        )
        result = run_spd_logm(params)
        assert result["shape"] == [6, 6]


# ---------------------------------------------------------------------------
# 4. Geodesic Distance
# ---------------------------------------------------------------------------


class TestSPDGeodesicDistance:
    def test_from_payload(self):
        p = spd_geodesic_distance_from_payload(
            {"matrix_a_file": "/a.npy", "matrix_b_file": "/b.npy", "metric": "airm"}
        )
        assert p.metric == "airm"

    def test_same_matrix_zero_distance(self, tmp_path):
        spd = _make_spd(8)
        a_path = _save(spd, tmp_path / "a.npy")
        b_path = _save(spd, tmp_path / "b.npy")

        params = SPDGeodesicDistanceParameters(
            matrix_a_file=str(a_path), matrix_b_file=str(b_path)
        )
        result = run_spd_geodesic_distance(params)
        assert result["distances"][0] < 1e-6

    def test_different_matrices_positive_distance(self, tmp_path):
        rng = np.random.default_rng(42)
        a = _make_spd(8, rng)
        b = _make_spd(8, rng)
        a_path = _save(a, tmp_path / "a.npy")
        b_path = _save(b, tmp_path / "b.npy")

        params = SPDGeodesicDistanceParameters(
            matrix_a_file=str(a_path), matrix_b_file=str(b_path), metric="airm"
        )
        result = run_spd_geodesic_distance(params)
        assert result["distances"][0] > 0

    def test_output_file(self, tmp_path):
        spd = _make_spd(5)
        a_path = _save(spd, tmp_path / "a.npy")
        out_path = tmp_path / "dist.json"

        params = SPDGeodesicDistanceParameters(
            matrix_a_file=str(a_path),
            matrix_b_file=str(a_path),
            output_file=str(out_path),
        )
        result = run_spd_geodesic_distance(params)
        assert out_path.exists()
        assert "output_file" in result


# ---------------------------------------------------------------------------
# 5. BiMap
# ---------------------------------------------------------------------------


class TestSPDBiMap:
    def test_from_payload(self):
        p = spd_bimap_from_payload(
            {"data_files": ["/a.npy"], "output_dim": 5, "output_dir": "/tmp/bimap"}
        )
        assert p.output_dim == 5
        assert len(p.data_files) == 1

    def test_from_payload_string_data_files(self):
        p = spd_bimap_from_payload(
            {"data_files": "/a.npy", "output_dim": 5, "output_dir": "/tmp/bimap"}
        )
        assert p.data_files == ["/a.npy"]

    def test_run(self, tmp_path):
        matrices = [_make_spd(10) for _ in range(5)]
        paths = [str(_save(m, tmp_path / f"spd_{i}.npy")) for i, m in enumerate(matrices)]
        out_dir = tmp_path / "bimap_out"

        params = SPDBiMapParameters(
            data_files=paths,
            output_dim=4,
            output_dir=str(out_dir),
            epochs=5,
        )
        result = run_spd_bimap(params)
        assert Path(result["projected_path"]).exists()
        assert Path(result["model_path"]).exists()
        projected = np.load(result["projected_path"])["matrices"]
        assert projected.shape == (5, 4, 4)


# ---------------------------------------------------------------------------
# 6. SPDNet Training
# ---------------------------------------------------------------------------


class TestSPDNetTrain:
    def test_from_payload(self):
        p = spdnet_train_from_payload(
            {"data_files": ["/a.npy"], "n_classes": 3, "epochs": 10}
        )
        assert p.n_classes == 3
        assert p.epochs == 10

    def test_run(self, tmp_path):
        rng = np.random.default_rng(42)
        matrices = [_make_spd(8, rng) for _ in range(20)]
        paths = [str(_save(m, tmp_path / f"spd_{i}.npy")) for i, m in enumerate(matrices)]
        labels = rng.integers(0, 2, size=20)
        labels_path = _save(labels, tmp_path / "labels.npy")
        out_dir = tmp_path / "spdnet_out"

        params = SPDNetTrainParameters(
            data_files=paths,
            output_dir=str(out_dir),
            n_classes=2,
            epochs=3,
            labels_file=str(labels_path),
        )
        result = run_spdnet_train(params)
        assert Path(result["model_path"]).exists()
        assert Path(result["predictions_path"]).exists()
        preds = np.load(result["predictions_path"])
        assert preds.shape == (20,)
