from __future__ import annotations

import numpy as np

from brain_researcher.services.tools.params import (
    FeatureSelectionParameters,
    run_feature_selection,
)


def test_run_feature_selection(tmp_path):
    X = np.random.randn(40, 10)
    y = np.random.randint(0, 2, size=40)
    data_file = tmp_path / "features.npy"
    labels_file = tmp_path / "labels.npy"
    np.save(data_file, X)
    np.save(labels_file, y)

    params = FeatureSelectionParameters(
        data_file=str(data_file),
        labels_file=str(labels_file),
        output_dir=str(tmp_path / "fs"),
        method="univariate",
        task_type="classification",
        n_features=5,
        percentile=None,
        random_state=0,
        save_indices=True,
        save_scores=True,
        save_reduced_data=True,
    )

    result = run_feature_selection(params)
    assert len(result["selected_indices"]) == 5
