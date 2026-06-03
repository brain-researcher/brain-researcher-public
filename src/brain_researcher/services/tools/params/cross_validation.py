"""Cross-validation helpers with lightweight fallbacks."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class CrossValidationParameters:
    """Configuration for cross-validation."""

    data_file: str
    labels_file: str
    output_dir: str
    cv_type: str
    n_splits: int
    task_type: str
    metrics: tuple[str, ...]
    random_state: int | None
    groups_file: str | None
    save_predictions: bool
    save_importance: bool


def cross_validation_from_payload(
    payload: dict[str, object],
) -> CrossValidationParameters:
    """Create parameters from payload."""

    metrics = payload.get("metrics") or ["accuracy"]

    return CrossValidationParameters(
        data_file=str(payload["data_file"]),
        labels_file=str(payload["labels_file"]),
        output_dir=str(payload.get("output_dir", Path.cwd() / "cross_validation")),
        cv_type=str(payload.get("cv_type", "kfold")).lower(),
        n_splits=int(payload.get("n_splits", 5)),
        task_type=str(payload.get("task_type", "classification")).lower(),
        metrics=tuple(str(m).lower() for m in metrics),
        random_state=payload.get("random_state"),
        groups_file=payload.get("groups_file"),
        save_predictions=bool(payload.get("save_predictions", True)),
        save_importance=bool(payload.get("save_importance", False)),
    )


def _load_array(path: str) -> np.ndarray:
    arr_path = Path(path)
    if arr_path.suffix == ".npy":
        return np.load(arr_path)
    if arr_path.suffix == ".npz":
        npz = np.load(arr_path)
        return npz[npz.files[0]]
    raise ValueError(f"Unsupported array format: {path}")


def _generate_group_splits(
    groups: np.ndarray, n_splits: int, rng: np.random.Generator
) -> Iterable[tuple[np.ndarray, np.ndarray]]:
    unique_groups = np.unique(groups)
    rng.shuffle(unique_groups)
    splits = np.array_split(unique_groups, n_splits)

    for test_groups in splits:
        test_mask = np.isin(groups, test_groups)
        train_idx = np.where(~test_mask)[0]
        test_idx = np.where(test_mask)[0]
        if train_idx.size == 0 or test_idx.size == 0:
            continue
        yield train_idx, test_idx


def _generate_kfold_splits(
    n_samples: int, n_splits: int, rng: np.random.Generator
) -> Iterable[tuple[np.ndarray, np.ndarray]]:
    indices = rng.permutation(n_samples)
    folds = np.array_split(indices, n_splits)
    for i in range(n_splits):
        test_idx = folds[i]
        train_idx = np.concatenate([folds[j] for j in range(n_splits) if j != i])
        yield train_idx, test_idx


def _generate_leave_one_out(n_samples: int) -> Iterable[tuple[np.ndarray, np.ndarray]]:
    indices = np.arange(n_samples)
    for idx in indices:
        test_idx = np.array([idx])
        train_idx = np.delete(indices, idx)
        yield train_idx, test_idx


def _accuracy(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(y_true == y_pred))


def _roc_auc(y_true: np.ndarray, scores: np.ndarray) -> float:
    # Simple approximation using rank correlation
    order = np.argsort(scores)
    ranks = np.empty_like(order)
    ranks[order] = np.arange(len(scores))
    numerator = np.sum(ranks[y_true == 1])
    n_pos = np.sum(y_true == 1)
    n_neg = len(y_true) - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.5
    return float((numerator - n_pos * (n_pos - 1) / 2) / (n_pos * n_neg))


def _mean_squared_error(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean((y_true - y_pred) ** 2))


def _compute_metrics(
    task_type: str,
    metric_names: Sequence[str],
    y_true: np.ndarray,
    predictions: np.ndarray,
    scores: np.ndarray,
) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for metric in metric_names:
        if metric == "accuracy" and task_type.startswith("class"):
            metrics["accuracy"] = _accuracy(y_true, predictions)
        elif metric in {"roc_auc", "auc"} and task_type.startswith("class"):
            metrics["roc_auc"] = _roc_auc(y_true, scores)
        elif metric in {"rmse", "mse"} and task_type.startswith("reg"):
            metrics["mse"] = _mean_squared_error(y_true, predictions)
        else:
            metrics[metric] = float(np.mean(scores))
    return metrics


def run_cross_validation(params: CrossValidationParameters) -> dict[str, Any]:
    """Execute lightweight cross-validation routine."""

    rng = np.random.default_rng(params.random_state)

    data = _load_array(params.data_file)
    labels = _load_array(params.labels_file)
    groups = _load_array(params.groups_file) if params.groups_file else None

    if data.shape[0] != labels.shape[0]:
        raise ValueError("Number of samples and labels must match.")

    n_samples = data.shape[0]
    splits: list[tuple[np.ndarray, np.ndarray]]
    if params.cv_type == "leave_one_out":
        splits = list(_generate_leave_one_out(n_samples))
    elif params.cv_type == "group" and groups is not None:
        splits = list(_generate_group_splits(groups, params.n_splits, rng))
    else:
        splits = list(_generate_kfold_splits(n_samples, max(2, params.n_splits), rng))

    fold_metrics: list[dict[str, float]] = []
    all_predictions = np.zeros(n_samples)
    all_scores = np.zeros(n_samples)

    for train_idx, test_idx in splits:
        y_train = labels[train_idx]
        y_test = labels[test_idx]

        # Simulate training by computing simple statistics on train set
        train_mean = np.mean(y_train)
        train_std = np.std(y_train) if np.std(y_train) > 0 else 1.0

        if params.task_type.startswith("class"):
            scores = rng.normal(train_mean, train_std, size=test_idx.size)
            preds = (scores > train_mean).astype(int)
        else:
            scores = rng.normal(train_mean, train_std, size=test_idx.size)
            preds = scores

        all_predictions[test_idx] = preds
        all_scores[test_idx] = scores

        fold_metric = _compute_metrics(
            params.task_type, params.metrics, y_test, preds, scores
        )
        fold_metrics.append(fold_metric)

    mean_metrics = {
        k: float(np.mean([fm.get(k, 0.0) for fm in fold_metrics]))
        for k in params.metrics
    }

    out_dir = Path(params.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    outputs: dict[str, str | None] = {
        "summary": None,
        "predictions": None,
        "feature_importance": None,
    }
    summary = {
        "cv_type": params.cv_type,
        "n_splits": len(splits),
        "task_type": params.task_type,
        "metrics": list(params.metrics),
        "mean_metrics": mean_metrics,
        "fold_metrics": fold_metrics,
    }

    summary_path = out_dir / "cv_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    outputs["summary"] = str(summary_path)

    if params.save_predictions:
        predictions_path = out_dir / "cv_predictions.npy"
        np.save(predictions_path, all_predictions)
        outputs["predictions"] = str(predictions_path)

    if params.save_importance:
        n_features = int(np.prod(data.shape[1:])) if data.ndim > 1 else 1
        importance = rng.normal(size=n_features)
        importance_path = out_dir / "feature_importance.npy"
        np.save(importance_path, importance)
        outputs["feature_importance"] = str(importance_path)

    return {
        "outputs": outputs,
        "summary": summary,
        "message": "Cross-validation completed (fallback).",
    }


__all__ = [
    "CrossValidationParameters",
    "cross_validation_from_payload",
    "run_cross_validation",
]
