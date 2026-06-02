"""Temporal decoding helpers with deterministic fallbacks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np


@dataclass(frozen=True)
class TemporalDecodingParameters:
    """Configuration for temporal decoding."""

    data_file: str
    labels_file: str
    output_dir: str
    method: str
    classifier: str
    window_size: Optional[int]
    window_step: int
    n_folds: int
    random_state: Optional[int]
    save_accuracies: bool
    save_patterns: bool


def temporal_decoding_from_payload(
    payload: Dict[str, object],
) -> TemporalDecodingParameters:
    """Create parameters from payload."""

    return TemporalDecodingParameters(
        data_file=str(payload["data_file"]),
        labels_file=str(payload["labels_file"]),
        output_dir=str(payload.get("output_dir", Path.cwd() / "temporal_decoding")),
        method=str(payload.get("method", "sliding_window")),
        classifier=str(payload.get("classifier", "lda")),
        window_size=payload.get("window_size"),
        window_step=int(payload.get("window_step", 1)),
        n_folds=int(payload.get("cv_folds", 5)),
        random_state=payload.get("random_state"),
        save_accuracies=bool(payload.get("save_accuracies", True)),
        save_patterns=bool(payload.get("save_patterns", True)),
    )


def _load_timeseries(path: str) -> np.ndarray:
    ts_path = Path(path)
    if ts_path.suffix == ".npy":
        return np.load(ts_path)
    if ts_path.suffix == ".npz":
        npz = np.load(ts_path)
        return npz[npz.files[0]]
    raise ValueError(f"Unsupported data format: {path}")


def _load_labels(path: str) -> np.ndarray:
    labels_path = Path(path)
    if labels_path.suffix == ".npy":
        return np.load(labels_path)
    if labels_path.suffix == ".npz":
        npz = np.load(labels_path)
        return npz[npz.files[0]]
    raise ValueError(f"Unsupported labels format: {path}")


def _standardize(data: np.ndarray) -> np.ndarray:
    mean = np.mean(data, axis=0, keepdims=True)
    std = np.std(data, axis=0, keepdims=True) + 1e-6
    return (data - mean) / std


def _generate_windows(data: np.ndarray, window_size: int, step: int) -> np.ndarray:
    windows = []
    for start in range(0, data.shape[0] - window_size + 1, step):
        end = start + window_size
        windows.append(data[start:end])
    if not windows:
        windows.append(data)
    return np.stack(windows)


def _compute_cv_folds(labels: np.ndarray, requested_folds: int) -> int:
    _, counts = np.unique(labels, return_counts=True)
    if counts.size < 2:
        return 0
    max_folds = int(min(max(2, requested_folds), np.min(counts)))
    return max_folds if max_folds >= 2 else 0


def _majority_accuracy(labels: np.ndarray) -> float:
    if labels.size == 0:
        return 0.0
    _, counts = np.unique(labels, return_counts=True)
    return float(np.max(counts) / labels.size)


def _deterministic_stratified_folds(
    labels: np.ndarray, n_splits: int
) -> List[np.ndarray]:
    folds: List[List[int]] = [[] for _ in range(n_splits)]
    for cls in np.unique(labels):
        cls_idx = np.where(labels == cls)[0]
        for i, idx in enumerate(cls_idx):
            folds[i % n_splits].append(int(idx))
    return [np.asarray(sorted(fold), dtype=int) for fold in folds if fold]


def _nearest_centroid_predict(
    train_x: np.ndarray,
    train_y: np.ndarray,
    test_x: np.ndarray,
) -> np.ndarray:
    classes = np.unique(train_y)
    centroids = np.vstack([train_x[train_y == cls].mean(axis=0) for cls in classes])
    dists = np.sum((test_x[:, None, :] - centroids[None, :, :]) ** 2, axis=2)
    return classes[np.argmin(dists, axis=1)]


def _nearest_centroid_cv_accuracy(
    data: np.ndarray, labels: np.ndarray, n_splits: int
) -> float:
    fold_indices = _deterministic_stratified_folds(labels, n_splits)
    all_idx = np.arange(labels.size)
    fold_accuracies: List[float] = []

    for test_idx in fold_indices:
        train_idx = np.setdiff1d(all_idx, test_idx)
        train_labels = labels[train_idx]
        if np.unique(train_labels).size < 2:
            continue
        predictions = _nearest_centroid_predict(
            data[train_idx], train_labels, data[test_idx]
        )
        fold_accuracies.append(float(np.mean(predictions == labels[test_idx])))

    if not fold_accuracies:
        return _majority_accuracy(labels)
    return float(np.mean(fold_accuracies))


def _run_sklearn_cv(
    data: np.ndarray,
    labels: np.ndarray,
    classifier_name: str,
    n_splits: int,
    random_state: Optional[int],
) -> Tuple[float, str]:
    try:
        from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
        from sklearn.linear_model import LogisticRegression, RidgeClassifier
        from sklearn.model_selection import StratifiedKFold, cross_val_score
        from sklearn.svm import LinearSVC
    except Exception as exc:
        raise RuntimeError("sklearn_unavailable") from exc

    clf_name = classifier_name.lower()
    if clf_name == "lda":
        classifier = LinearDiscriminantAnalysis()
    elif clf_name in {"svm", "svc", "linearsvc"}:
        classifier = LinearSVC(random_state=random_state)
    elif clf_name in {"ridge", "ridge_classifier"}:
        classifier = RidgeClassifier()
    else:
        # Default to robust deterministic linear classifier.
        classifier = LogisticRegression(
            max_iter=1000,
            random_state=random_state,
            solver="liblinear",
        )

    cv = StratifiedKFold(
        n_splits=n_splits,
        shuffle=True,
        random_state=0 if random_state is None else int(random_state),
    )
    scores = cross_val_score(classifier, data, labels, cv=cv, scoring="accuracy")
    return float(np.mean(scores)), "sklearn_cv"


def _decode_window(
    window_data: np.ndarray,
    labels: np.ndarray,
    classifier_name: str,
    requested_folds: int,
    random_state: Optional[int],
) -> Tuple[float, str, str]:
    n_splits = _compute_cv_folds(labels, requested_folds)
    if labels.size < 2:
        return 0.0, "insufficient_trials", "not_enough_trials"
    if np.unique(labels).size < 2:
        return 0.0, "insufficient_classes", "single_class_labels"
    if n_splits < 2:
        return (
            _majority_accuracy(labels),
            "insufficient_cv_folds",
            "class_counts_too_small_for_cv",
        )

    try:
        score, backend = _run_sklearn_cv(
            window_data,
            labels,
            classifier_name=classifier_name,
            n_splits=n_splits,
            random_state=random_state,
        )
        return score, backend, "ok"
    except Exception:
        score = _nearest_centroid_cv_accuracy(window_data, labels, n_splits=n_splits)
        return score, "numpy_nearest_centroid_cv", "sklearn_failed_or_unavailable"


def run_temporal_decoding(params: TemporalDecodingParameters) -> Dict[str, object]:
    """Execute temporal decoding analysis with deterministic classifiers."""

    data = _load_timeseries(params.data_file)
    labels = np.asarray(_load_labels(params.labels_file)).astype(int).reshape(-1)

    if data.ndim == 3:
        # time x features x trials -> reshape to trials x time x features
        time, _, _ = data.shape
        timeseries = np.transpose(data, (2, 0, 1))
    elif data.ndim == 2:
        # If labels match first dim, treat as trials x features (single timepoint).
        if labels.size == data.shape[0] and labels.size >= 2:
            _, _ = data.shape
            time = 1
            timeseries = data[:, np.newaxis, :]
        else:
            # time x features -> single trial
            time, _ = data.shape
            timeseries = data[np.newaxis, ...]
    else:
        raise ValueError(
            "Data must be either (time x features) or (time x features x trials)."
        )

    n_trials = timeseries.shape[0]
    if labels.size < n_trials:
        raise ValueError("Labels must contain at least one label per trial.")
    labels = labels[:n_trials]

    window_size = params.window_size or max(1, time // 10)
    windows = _generate_windows(np.arange(time), window_size, params.window_step)
    accuracies: List[float] = []
    patterns: List[np.ndarray] = []
    window_backends: List[str] = []
    backend_reasons: List[str] = []

    for window in windows:
        start, end = int(window[0]), int(window[-1] + 1)
        window_data = timeseries[:, start:end, :].reshape(n_trials, -1)
        window_data = _standardize(window_data)

        accuracy, backend_name, backend_reason = _decode_window(
            window_data,
            labels,
            classifier_name=params.classifier,
            requested_folds=params.n_folds,
            random_state=params.random_state,
        )
        accuracies.append(accuracy)
        window_backends.append(backend_name)
        backend_reasons.append(backend_reason)
        patterns.append(window_data.mean(axis=0))

    mean_accuracy = float(np.mean(accuracies))
    std_accuracy = float(np.std(accuracies))
    n_classes = int(np.unique(labels).size)
    effective_cv_folds = _compute_cv_folds(labels, params.n_folds)
    used_full_backend = any(name == "sklearn_cv" for name in window_backends)
    backend_name = (
        window_backends[0] if len(set(window_backends)) == 1 else "mixed_backends"
    )
    backend_reason = (
        backend_reasons[0] if len(set(backend_reasons)) == 1 else "mixed_reasons"
    )

    out_dir = Path(params.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    outputs: Dict[str, Optional[str]] = {
        "summary": None,
        "accuracies": None,
        "patterns": None,
    }

    summary = {
        "method": params.method,
        "classifier": params.classifier,
        "n_trials": int(n_trials),
        "window_size": int(window_size),
        "n_windows": len(windows),
        "mean_accuracy": mean_accuracy,
        "std_accuracy": std_accuracy,
        "n_classes": n_classes,
        "effective_cv_folds": int(effective_cv_folds),
        "used_full_backend": bool(used_full_backend),
        "backend_name": backend_name,
        "backend_reason": backend_reason,
    }

    summary_path = out_dir / "temporal_decoding_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    outputs["summary"] = str(summary_path)

    if params.save_accuracies:
        acc_path = out_dir / "temporal_accuracies.npy"
        np.save(acc_path, np.asarray(accuracies))
        outputs["accuracies"] = str(acc_path)

    if params.save_patterns:
        patterns_path = out_dir / "temporal_patterns.npy"
        np.save(patterns_path, np.asarray(patterns))
        outputs["patterns"] = str(patterns_path)

    return {
        "outputs": outputs,
        "summary": summary,
        "accuracies": accuracies,
        "message": f"Temporal decoding completed ({backend_name}).",
    }


__all__ = [
    "TemporalDecodingParameters",
    "temporal_decoding_from_payload",
    "run_temporal_decoding",
]
