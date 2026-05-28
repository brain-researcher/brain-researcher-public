"""Unit tests for realtime two-photon decoder helpers."""

from __future__ import annotations

import numpy as np

from brain_researcher.services.tools.realtime_twophoton_decoder import (
    build_causal_feature_matrix,
    predict_decoder_bundle,
    train_decoder_bundle,
)


def test_train_and_predict_decoder_bundle_round_trip():
    rng = np.random.default_rng(3)
    labels = np.repeat(np.arange(4), 25)
    traces = rng.normal(0, 0.05, size=(100, 8)).astype(np.float32)
    for idx, label in enumerate(labels):
        traces[idx, label * 2 : label * 2 + 2] += 1.0

    bundle = train_decoder_bundle(
        traces=traces,
        labels=labels,
        decode_window_frames=3,
        decoder_type="ridge",
    )
    predictions, confidence = predict_decoder_bundle(bundle, traces)

    assert predictions.shape == labels.shape
    assert confidence.shape == labels.shape
    assert float(np.mean(predictions == labels)) > 0.9


def test_causal_feature_matrix_has_expected_shape():
    traces = np.ones((10, 5), dtype=np.float32)
    features = build_causal_feature_matrix(traces, decode_window_frames=4)
    assert features.shape == (10, 20)
