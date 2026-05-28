"""Tests for SPD tool wrappers (NeuroToolWrapper subclasses)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from brain_researcher.services.tools.spd_tools import (
    CovarianceEstimateTool,
    SPDBiMapTool,
    SPDDistanceTool,
    SPDLogmTool,
    SPDNetTrainTool,
    SPDProjectTool,
    SPDTools,
)


def _make_spd(n: int = 10, rng=None) -> np.ndarray:
    if rng is None:
        rng = np.random.default_rng(42)
    A = rng.standard_normal((n, n))
    return A @ A.T + np.eye(n) * 0.1


def _save(arr: np.ndarray, path: Path) -> Path:
    np.save(path, arr)
    return path


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestSPDToolsRegistry:
    def test_get_all_tools_returns_six(self):
        tools = SPDTools.get_all_tools()
        assert len(tools) == 6

    def test_tool_names(self):
        names = {t.get_tool_name() for t in SPDTools.get_all_tools()}
        expected = {
            "repr_spd_covariance_estimate",
            "repr_spd_project",
            "geom_spd_logm",
            "geom_spd_geodesic_distance",
            "nn_spd_bimap",
            "nn_spd_train_spdnet",
        }
        assert names == expected

    def test_as_langchain_tool(self):
        tools = SPDTools.get_all_tools()
        for t in tools:
            lc_tool = t.as_langchain_tool()
            assert hasattr(lc_tool, "name")
            assert hasattr(lc_tool, "description")


# ---------------------------------------------------------------------------
# Tool Wrappers
# ---------------------------------------------------------------------------


class TestCovarianceEstimateTool:
    def test_run_success(self, tmp_path):
        ts = np.random.randn(100, 15)
        ts_path = _save(ts, tmp_path / "ts.npy")
        out_path = tmp_path / "cov.npz"

        tool = CovarianceEstimateTool()
        result = tool._run(
            data_file=str(ts_path),
            output_file=str(out_path),
            method="empirical",
        )
        assert result.status == "success"
        assert result.data["shape"] == [15, 15]
        assert out_path.exists()

    def test_run_error_missing_file(self, tmp_path):
        tool = CovarianceEstimateTool()
        result = tool._run(
            data_file="/nonexistent.npy",
            output_file=str(tmp_path / "cov.npz"),
        )
        assert result.status == "error"


class TestSPDProjectTool:
    def test_run_success(self, tmp_path):
        rng = np.random.default_rng(42)
        mat = rng.standard_normal((8, 8))
        mat = mat + mat.T
        mat_path = _save(mat, tmp_path / "mat.npy")
        out_path = tmp_path / "spd.npz"

        tool = SPDProjectTool()
        result = tool._run(
            matrix_file=str(mat_path),
            output_file=str(out_path),
        )
        assert result.status == "success"
        assert result.data["is_spd"] is True


class TestSPDLogmTool:
    def test_run_success(self, tmp_path):
        spd = _make_spd(8)
        spd_path = _save(spd, tmp_path / "spd.npy")
        out_path = tmp_path / "logm.npz"

        tool = SPDLogmTool()
        result = tool._run(
            spd_matrix_file=str(spd_path),
            output_file=str(out_path),
        )
        assert result.status == "success"
        assert result.data["shape"] == [8, 8]


class TestSPDDistanceTool:
    def test_same_matrix(self, tmp_path):
        spd = _make_spd(6)
        a_path = _save(spd, tmp_path / "a.npy")

        tool = SPDDistanceTool()
        result = tool._run(
            matrix_a_file=str(a_path),
            matrix_b_file=str(a_path),
            metric="log_euclidean",
        )
        assert result.status == "success"
        assert result.data["distances"][0] < 1e-6


class TestSPDBiMapTool:
    def test_run_success(self, tmp_path):
        matrices = [_make_spd(10) for _ in range(5)]
        paths = [str(_save(m, tmp_path / f"spd_{i}.npy")) for i, m in enumerate(matrices)]
        out_dir = tmp_path / "bimap"

        tool = SPDBiMapTool()
        result = tool._run(
            data_files=paths,
            output_dim=4,
            output_dir=str(out_dir),
            epochs=3,
        )
        assert result.status == "success"
        assert Path(result.data["projected_path"]).exists()


class TestSPDNetTrainTool:
    def test_run_success(self, tmp_path):
        rng = np.random.default_rng(42)
        matrices = [_make_spd(8, rng) for _ in range(15)]
        paths = [str(_save(m, tmp_path / f"spd_{i}.npy")) for i, m in enumerate(matrices)]
        labels = rng.integers(0, 2, size=15)
        labels_path = _save(labels, tmp_path / "labels.npy")
        out_dir = tmp_path / "spdnet"

        tool = SPDNetTrainTool()
        result = tool._run(
            data_files=paths,
            output_dir=str(out_dir),
            n_classes=2,
            epochs=3,
            labels_file=str(labels_path),
        )
        assert result.status == "success"
        assert "metrics" in result.data
