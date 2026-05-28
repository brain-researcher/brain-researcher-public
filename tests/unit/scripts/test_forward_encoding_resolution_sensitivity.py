"""Unit tests for resolved/unresolved sensitivity helpers in full runner."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.analysis.run_forward_encoding_full import (
    resolution_lookup_from_kg_map,
    summarize_from_rows,
)


def test_resolution_lookup_from_kg_map(tmp_path: Path) -> None:
    p = tmp_path / "kg_map.json"
    payload = {
        "items": [
            {
                "task_raw": "taskA",
                "contrast": "xVy",
                "kg_feature_ids": ["tsk_1"],
                "onvoc_ids": [],
                "quality": {"task_resolved": True, "n_features": 1},
            },
            {
                "task_raw": "taskB",
                "contrast": "mVn",
                "kg_feature_ids": [],
                "onvoc_ids": [],
                "quality": {"task_resolved": False, "n_features": 0},
            },
        ]
    }
    p.write_text(json.dumps(payload), encoding="utf-8")

    lookup = resolution_lookup_from_kg_map(p)
    assert lookup[("taskA", "xVy")] is True
    assert lookup[("taskB", "mVn")] is False


def test_summarize_from_rows_per_mode() -> None:
    df = pd.DataFrame(
        {
            "y_mode": ["residual_voxel", "residual_voxel", "residual_lowrank32"],
            "r_model": [0.20, 0.10, 0.30],
            "r_baseline": [0.10, 0.10, 0.20],
            "delta_r": [0.10, 0.00, 0.10],
        }
    )

    out = summarize_from_rows(df, ["residual_voxel", "residual_lowrank32", "abs_voxel"])
    assert out["residual_voxel"].n_eval == 2
    assert out["residual_voxel"].mean_delta == 0.05
    assert out["residual_lowrank32"].n_eval == 1
    assert out["abs_voxel"].n_eval == 0
