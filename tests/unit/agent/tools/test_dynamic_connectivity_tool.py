from __future__ import annotations

from pathlib import Path

import numpy as np

from brain_researcher.services.tools.dynamic_connectivity_tool import (
    DynamicConnectivityTool,
)


def test_agent_dynamic_connectivity(tmp_path):
    tool = DynamicConnectivityTool()
    ts = np.random.randn(50, 4)
    ts_file = tmp_path / "timeseries.npy"
    np.save(ts_file, ts)

    result = tool._run(
        timeseries_file=str(ts_file),
        output_dir=str(tmp_path / "dyn"),
        n_states=2,
    )

    assert result.status == "success"
    assert Path(result.data["outputs"]["feature_contract"]).exists()
