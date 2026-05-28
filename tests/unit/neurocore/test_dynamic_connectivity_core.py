from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from brain_researcher.services.tools.params import (
    DynamicConnectivityParameters,
    run_dynamic_connectivity,
)


def test_run_dynamic_connectivity(tmp_path):
    ts = np.random.randn(60, 10)
    ts_file = tmp_path / "timeseries.npy"
    np.save(ts_file, ts)

    params = DynamicConnectivityParameters(
        timeseries_file=str(ts_file),
        output_dir=str(tmp_path / "dyn"),
        connectivity_method="correlation",
        dynamic_method="sliding_window",
        window_length=15,
        window_overlap=0.5,
        n_states=4,
        random_state=0,
        save_matrices=True,
        save_states=True,
        save_metrics=True,
    )

    result = run_dynamic_connectivity(params)
    assert "n_windows" in result["summary"]
    outputs = result["outputs"]
    assert Path(outputs["matrices"]).exists()
    assert Path(outputs["feature_contract"]).exists()
    contract = json.loads(Path(outputs["feature_contract"]).read_text())
    assert contract["matrix_kind"] == "dynamic_correlation"
    assert contract["effective_n_timepoints"] == 15
