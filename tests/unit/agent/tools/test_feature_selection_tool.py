from __future__ import annotations

import numpy as np

from brain_researcher.services.tools.feature_selection_tool import FeatureSelectionTool


def test_agent_feature_selection(tmp_path):
    tool = FeatureSelectionTool()
    X = np.random.randn(30, 6)
    y = np.random.randint(0, 2, size=30)
    data_file = tmp_path / "features.npy"
    labels_file = tmp_path / "labels.npy"
    np.save(data_file, X)
    np.save(labels_file, y)

    result = tool._run(
        data_file=str(data_file),
        labels_file=str(labels_file),
        output_dir=str(tmp_path / "fs"),
        method="univariate",
        n_features=4,
    )

    assert result.status == "success"
