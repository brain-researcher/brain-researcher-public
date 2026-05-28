"""Tests for realtime connectivity feature-contract emission."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from brain_researcher.services.tools.realtime_fmri_tool import RealtimeConnectivityTool


def test_realtime_connectivity_emits_feature_contract(tmp_path: Path):
    tool = RealtimeConnectivityTool()
    rng = np.random.default_rng(0)
    roi_timeseries = rng.normal(size=(40, 4))

    result = tool._run(
        roi_timeseries=roi_timeseries,
        method="correlation",
        window_size=20,
        output_dir=str(tmp_path),
    )

    assert result.status == "success"
    outputs = result.data["outputs"]
    assert Path(outputs["connectivity_matrix"]).exists()
    assert Path(outputs["feature_contract"]).exists()
