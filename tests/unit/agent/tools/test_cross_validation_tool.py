from __future__ import annotations

import numpy as np

from brain_researcher.services.tools.cross_validation_tool import CrossValidationTool


def test_agent_cross_validation(tmp_path):
    tool = CrossValidationTool()
    X = np.random.randn(20, 3)
    y = np.random.randint(0, 2, size=20)
    data_file = tmp_path / "features.npy"
    labels_file = tmp_path / "labels.npy"
    np.save(data_file, X)
    np.save(labels_file, y)

    result = tool._run(
        data_file=str(data_file),
        labels_file=str(labels_file),
        output_dir=str(tmp_path / "cv"),
        cv_type="kfold",
        n_splits=4,
        metrics=["accuracy"],
        save_importance=True,
    )

    assert result.status == "success"
