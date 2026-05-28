from __future__ import annotations

import numpy as np
from pathlib import Path

from brain_researcher.services.tools.runner import execute_tool


def test_nbs_engine_two_group(tmp_path: Path):
    rng = np.random.default_rng(0)
    n_subj, n_roi = 8, 6
    mats = rng.standard_normal((n_subj, n_roi, n_roi))
    # inject group difference
    mats[:4, 0, 1] += 1.5
    mats[:4, 1, 0] += 1.5
    mats_file = tmp_path / "conn.npy"
    np.save(mats_file, mats)
    labels = [0] * 4 + [1] * 4
    out_dir = tmp_path / "nbs"
    res = execute_tool(
        "nbs_engine",
        {
            "connectivity_matrices": str(mats_file),
            "labels": labels,
            "threshold": 1.0,
            "n_permutations": 50,
            "output_file": str(out_dir / "nbs_out"),
        },
    )
    assert res.status == "success", res.error
    out = res.data
    assert out["pvalue"] <= 1.0
    assert out["component_size"] >= 0
    # files written
    assert "components_file" in out
    assert Path(out["components_file"]).exists()
