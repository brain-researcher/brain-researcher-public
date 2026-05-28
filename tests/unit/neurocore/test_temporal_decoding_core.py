from __future__ import annotations

import numpy as np
import pytest

from brain_researcher.services.tools.params import (
    TemporalDecodingParameters,
    run_temporal_decoding,
)


def test_run_temporal_decoding_deterministic_classifier(tmp_path):
    rng = np.random.default_rng(0)
    n_trials = 40
    labels = np.array([0] * (n_trials // 2) + [1] * (n_trials // 2), dtype=int)

    # time x features x trials
    data = np.zeros((6, 3, n_trials), dtype=float)
    for i in range(n_trials):
        center = -2.0 if labels[i] == 0 else 2.0
        data[:, :, i] = center + rng.normal(scale=0.05, size=(6, 3))

    data_file = tmp_path / "data.npy"
    labels_file = tmp_path / "labels.npy"
    np.save(data_file, data)
    np.save(labels_file, labels)

    params_a = TemporalDecodingParameters(
        data_file=str(data_file),
        labels_file=str(labels_file),
        output_dir=str(tmp_path / "decoding_a"),
        method="sliding_window",
        classifier="logreg",
        window_size=3,
        window_step=1,
        n_folds=5,
        random_state=0,
        save_accuracies=True,
        save_patterns=True,
    )
    params_b = TemporalDecodingParameters(
        data_file=str(data_file),
        labels_file=str(labels_file),
        output_dir=str(tmp_path / "decoding_b"),
        method="sliding_window",
        classifier="logreg",
        window_size=3,
        window_step=1,
        n_folds=5,
        random_state=0,
        save_accuracies=True,
        save_patterns=True,
    )

    result_a = run_temporal_decoding(params_a)
    result_b = run_temporal_decoding(params_b)

    assert "mean_accuracy" in result_a["summary"]
    assert result_a["accuracies"] == result_b["accuracies"]
    assert result_a["summary"]["mean_accuracy"] == result_b["summary"]["mean_accuracy"]
    assert result_a["summary"]["mean_accuracy"] > 0.95
    assert result_a["summary"]["backend_name"] in {
        "sklearn_cv",
        "numpy_nearest_centroid_cv",
    }


def test_run_temporal_decoding_handles_single_class_labels(tmp_path):
    rng = np.random.default_rng(0)
    data = rng.normal(size=(12, 4))
    labels = np.zeros(12, dtype=int)
    data_file = tmp_path / "data.npy"
    labels_file = tmp_path / "labels.npy"
    np.save(data_file, data)
    np.save(labels_file, labels)

    params = TemporalDecodingParameters(
        data_file=str(data_file),
        labels_file=str(labels_file),
        output_dir=str(tmp_path / "decoding"),
        method="sliding_window",
        classifier="lda",
        window_size=1,
        window_step=1,
        n_folds=5,
        random_state=0,
        save_accuracies=False,
        save_patterns=False,
    )

    result = run_temporal_decoding(params)
    assert result["summary"]["used_full_backend"] is False
    assert result["summary"]["backend_name"] == "insufficient_classes"
    assert result["summary"]["mean_accuracy"] == 0.0


def test_run_temporal_decoding_raises_for_too_few_labels(tmp_path):
    data = np.random.randn(8, 2, 5)  # trials=5
    labels = np.array([0, 1, 0, 1], dtype=int)  # fewer than trials
    data_file = tmp_path / "data.npy"
    labels_file = tmp_path / "labels.npy"
    np.save(data_file, data)
    np.save(labels_file, labels)

    params = TemporalDecodingParameters(
        data_file=str(data_file),
        labels_file=str(labels_file),
        output_dir=str(tmp_path / "decoding"),
        method="sliding_window",
        classifier="lda",
        window_size=2,
        window_step=1,
        n_folds=3,
        random_state=0,
        save_accuracies=False,
        save_patterns=False,
    )

    with pytest.raises(ValueError, match="at least one label per trial"):
        run_temporal_decoding(params)
