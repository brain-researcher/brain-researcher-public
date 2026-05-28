from __future__ import annotations

from pathlib import Path

import numpy as np

from brain_researcher.services.tools.params import (
    StatisticalInferenceParameters,
    run_statistical_inference,
)


def test_run_statistical_inference(tmp_path):
    data = np.random.randn(12, 3)
    data_file = tmp_path / "data.npy"
    np.save(data_file, data)

    params = StatisticalInferenceParameters(
        data_file=str(data_file),
        output_dir=str(tmp_path / "stat"),
        n_bootstrap=128,
    )

    result = run_statistical_inference(params)
    summary_path = Path(result["outputs"]["summary"])
    assert summary_path.exists()
    assert result["summary"]["n_subjects"] == 12
