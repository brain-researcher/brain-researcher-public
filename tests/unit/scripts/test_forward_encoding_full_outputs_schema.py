"""Unit tests for helper outputs in run_forward_encoding_full."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from scripts.analysis.run_forward_encoding_full import build_figure_manifest, combo_aggregate


def test_build_figure_manifest_contains_expected_entries(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = build_figure_manifest(out_dir)

    assert "generated_at" in manifest
    assert "figures" in manifest
    assert isinstance(manifest["figures"], list)
    ids = {fig["id"] for fig in manifest["figures"]}
    assert "fig_main_delta_win" in ids
    assert "fig_per_task_delta" in ids
    assert "fig_dataset_shift" in ids
    assert "fig_feature_collapse" in ids
    assert "fig_rdoc_projection" in ids
    assert "fig_resolution_sensitivity" in ids


def test_combo_aggregate_groups_and_averages_vectors() -> None:
    df = pd.DataFrame(
        {
            "canonical_task": ["taskA", "taskA", "taskB"],
            "task_raw": ["a", "a", "b"],
            "contrast": ["xVy", "xVy", "mVn"],
            "dataset": ["ds1", "ds1", "ds2"],
        }
    )
    X = np.asarray(
        [
            [1.0, 0.0],
            [3.0, 2.0],
            [5.0, 4.0],
        ],
        dtype=float,
    )
    Y = np.asarray(
        [
            [10.0, 20.0],
            [30.0, 40.0],
            [50.0, 60.0],
        ],
        dtype=float,
    )

    agg = combo_aggregate(df, X, Y)

    assert len(agg) == 2
    row_a = agg[(agg["canonical_task"] == "taskA") & (agg["contrast"] == "xVy")].iloc[0]
    assert int(row_a["n_maps"]) == 2
    assert np.allclose(row_a["x"], np.asarray([2.0, 1.0]))
    assert np.allclose(row_a["y"], np.asarray([20.0, 30.0]))
