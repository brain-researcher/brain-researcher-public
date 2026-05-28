from __future__ import annotations

import numpy as np

from brain_researcher.services.tools.params import (
    MVPADecodingParameters,
    run_mvpa_decoding,
)


def test_run_mvpa_decoding(tmp_path):
    data = np.random.randn(20, 5)
    labels = np.random.randint(0, 2, size=20)
    data_file = tmp_path / "data.npy"
    labels_file = tmp_path / "labels.npy"
    np.save(data_file, data)
    np.save(labels_file, labels)

    params = MVPADecodingParameters(
        img=str(data_file),
        labels=labels,
        mask_img=None,
        classifier="svc",
        cv_folds=4,
        standardize=True,
        smoothing_fwhm=None,
        feature_selection=None,
        n_features=None,
        permutations=0,
        n_jobs=-1,
        output_dir=str(tmp_path / "mvpa"),
        seed=123,
    )

    result = run_mvpa_decoding(params)
    assert result["summary"]["folds"] == 4
    assert len(result["scores"]) == 4
