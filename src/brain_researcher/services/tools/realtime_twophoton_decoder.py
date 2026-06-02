"""Decoder training and inference utilities for realtime two-photon replay."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

try:
    import joblib
except ImportError:  # pragma: no cover
    joblib = None


@dataclass
class DecoderBundle:
    """Serializable linear decoder bundle."""

    estimator: Any
    decoder_type: str
    decode_window_frames: int
    n_state_bins: int
    n_features: int


def _require_sklearn():
    try:
        from sklearn.linear_model import LogisticRegression, RidgeClassifier
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "scikit-learn is required for realtime two-photon decoder training."
        ) from exc
    return LogisticRegression, RidgeClassifier


def build_causal_feature_matrix(
    traces: np.ndarray, decode_window_frames: int
) -> np.ndarray:
    """Flatten a causal window of traces into per-frame features."""

    if traces.ndim != 2:
        raise ValueError("Expected traces with shape [n_frames, n_rois]")
    if decode_window_frames < 1:
        raise ValueError("decode_window_frames must be >= 1")

    n_frames, n_rois = traces.shape
    features = np.zeros((n_frames, n_rois * decode_window_frames), dtype=np.float32)
    for frame_index in range(n_frames):
        window = []
        start = max(0, frame_index - decode_window_frames + 1)
        actual = traces[start : frame_index + 1]
        if len(actual) < decode_window_frames:
            padding = np.repeat(actual[:1], decode_window_frames - len(actual), axis=0)
            actual = np.concatenate([padding, actual], axis=0)
        window.extend(actual)
        features[frame_index] = np.concatenate(window, axis=0)
    return features


def train_decoder_bundle(
    traces: np.ndarray,
    labels: np.ndarray,
    decode_window_frames: int = 4,
    decoder_type: str = "ridge",
) -> DecoderBundle:
    """Train a simple per-session decoder bundle."""

    LogisticRegression, RidgeClassifier = _require_sklearn()
    labels = np.asarray(labels).astype(int)
    features = build_causal_feature_matrix(
        np.asarray(traces, dtype=np.float32), decode_window_frames
    )
    if decoder_type == "logistic":
        estimator = LogisticRegression(max_iter=1000, multi_class="auto")
    elif decoder_type == "ridge":
        estimator = RidgeClassifier()
    else:
        raise ValueError(f"Unsupported decoder type: {decoder_type}")
    estimator.fit(features, labels)
    return DecoderBundle(
        estimator=estimator,
        decoder_type=decoder_type,
        decode_window_frames=int(decode_window_frames),
        n_state_bins=int(np.max(labels)) + 1,
        n_features=int(features.shape[1]),
    )


def predict_decoder_bundle(
    bundle: DecoderBundle, traces: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Predict discrete states and confidence scores from traces."""

    features = build_causal_feature_matrix(
        np.asarray(traces, dtype=np.float32), bundle.decode_window_frames
    )
    predictions = bundle.estimator.predict(features)
    if hasattr(bundle.estimator, "decision_function"):
        raw = bundle.estimator.decision_function(features)
        raw = np.asarray(raw)
        if raw.ndim == 1:
            confidence = 1.0 / (1.0 + np.exp(-np.abs(raw)))
        else:
            confidence = np.max(raw, axis=1)
            confidence = 1.0 / (1.0 + np.exp(-confidence))
    elif hasattr(bundle.estimator, "predict_proba"):
        confidence = np.max(bundle.estimator.predict_proba(features), axis=1)
    else:
        confidence = np.ones(len(predictions), dtype=np.float32)
    return np.asarray(predictions).astype(int), np.asarray(confidence, dtype=np.float32)


def save_decoder_bundle(bundle: DecoderBundle, output_path: str | Path) -> Path:
    """Persist a decoder bundle."""

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if joblib is not None:
        joblib.dump(bundle, output)
    else:  # pragma: no cover
        import pickle

        with open(output, "wb") as f:
            pickle.dump(bundle, f)
    return output


def load_decoder_bundle(path: str | Path) -> DecoderBundle:
    """Load a decoder bundle."""

    input_path = Path(path)
    if joblib is not None:
        return joblib.load(input_path)
    import pickle  # pragma: no cover

    with open(input_path, "rb") as f:
        return pickle.load(f)
