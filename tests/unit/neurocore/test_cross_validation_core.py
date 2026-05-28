from __future__ import annotations

import numpy as np

from brain_researcher.services.tools.params import (
    CrossValidationParameters,
    run_cross_validation,
)


def test_run_cross_validation(tmp_path):
    X = np.random.randn(20, 5)
    y = np.random.randint(0, 2, size=20)
    data_file = tmp_path / "features.npy"
    labels_file = tmp_path / "labels.npy"
    np.save(data_file, X)
    np.save(labels_file, y)

    params = CrossValidationParameters(
        data_file=str(data_file),
        labels_file=str(labels_file),
        output_dir=str(tmp_path / "cv"),
        cv_type="kfold",
        n_splits=4,
        task_type="classification",
        metrics=("accuracy",),
        random_state=123,
        groups_file=None,
        save_predictions=True,
        save_importance=True,
    )

    result = run_cross_validation(params)
    assert "mean_metrics" in result["summary"]
