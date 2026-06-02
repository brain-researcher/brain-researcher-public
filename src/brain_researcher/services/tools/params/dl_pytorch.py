"""PyTorch deep-learning helpers with deterministic fallbacks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np


@dataclass(frozen=True)
class DLPyTorchParameters:
    """Configuration for lightweight PyTorch simulations."""

    data_file: str
    output_dir: str
    model_type: str
    task: str
    n_classes: Optional[int]
    mode: str
    epochs: int
    batch_size: int
    learning_rate: float
    use_pretrained: bool
    seed: Optional[int]
    labels_file: Optional[str]
    save_model: bool
    save_predictions: bool
    save_features: bool


def dl_pytorch_from_payload(payload: Dict[str, Any]) -> DLPyTorchParameters:
    """Construct parameters from payload."""

    return DLPyTorchParameters(
        data_file=str(payload["data_file"]),
        output_dir=str(payload.get("output_dir", Path.cwd() / "dl_pytorch")),
        model_type=str(payload.get("model_type", "3dcnn")),
        task=str(payload.get("task", "classification")),
        n_classes=payload.get("n_classes"),
        mode=str(payload.get("mode", "train")),
        epochs=int(payload.get("epochs", 10)),
        batch_size=int(payload.get("batch_size", 32)),
        learning_rate=float(payload.get("learning_rate", 0.001)),
        use_pretrained=bool(payload.get("use_pretrained", False)),
        seed=payload.get("seed"),
        labels_file=payload.get("labels_file"),
        save_model=bool(payload.get("save_model", True)),
        save_predictions=bool(payload.get("save_predictions", True)),
        save_features=bool(payload.get("save_features", False)),
    )


def _load_array(path: Path) -> np.ndarray:
    if path.suffix == ".npy":
        return np.load(path)
    if path.suffix == ".npz":
        npz = np.load(path)
        return npz[npz.files[0]]
    raise ValueError(f"Unsupported data format: {path}")


def _load_labels(path: Optional[str]) -> Optional[np.ndarray]:
    if not path:
        return None
    arr_path = Path(path)
    if arr_path.suffix == ".npy":
        return np.load(arr_path)
    if arr_path.suffix == ".npz":
        npz = np.load(arr_path)
        return npz[npz.files[0]]
    return None


def run_dl_pytorch(params: DLPyTorchParameters) -> Dict[str, Any]:
    """Execute placeholder PyTorch training/inference."""

    data_array = _load_array(Path(params.data_file))
    labels_array = _load_labels(params.labels_file)

    rng = np.random.default_rng(params.seed)

    outputs_dir = Path(params.output_dir)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    n_samples = data_array.shape[0] if data_array.ndim >= 1 else 1
    n_features = int(np.prod(data_array.shape[1:])) if data_array.ndim > 1 else 1

    # Generate synthetic metrics
    training_loss = max(0.0, 1.0 - 0.1 * params.epochs + rng.normal(0, 0.02))
    validation_loss = training_loss + rng.normal(0, 0.01)
    accuracy = float(np.clip(0.5 + rng.normal(0.2, 0.05), 0.0, 1.0))
    predictions = rng.random(n_samples)

    if params.task == "regression":
        metric_primary = float(np.clip(rng.normal(0.1, 0.02), 0.0, None))
        metric_name = "rmse"
    else:
        metric_primary = accuracy
        metric_name = "accuracy"

    metrics = {
        "training_loss": training_loss,
        "validation_loss": validation_loss,
        metric_name: metric_primary,
        "epochs": params.epochs,
    }

    summary = {
        "model_type": params.model_type,
        "task": params.task,
        "mode": params.mode,
        "n_samples": n_samples,
        "input_dimensions": list(data_array.shape[1:]),
        "use_pretrained": params.use_pretrained,
        "metrics": metrics,
        "used_full_backend": False,
    }

    summary_path = outputs_dir / "dl_pytorch_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    outputs: Dict[str, Optional[str]] = {
        "summary": str(summary_path),
        "model": None,
        "predictions": None,
        "features": None,
    }

    if params.save_model:
        model_path = outputs_dir / "model.pt"
        model_path.write_bytes(b"placeholder-model")
        outputs["model"] = str(model_path)

    if params.save_predictions:
        predictions_path = outputs_dir / "predictions.npy"
        np.save(predictions_path, predictions)
        outputs["predictions"] = str(predictions_path)

    if params.save_features:
        features = rng.normal(size=(n_samples, min(n_features, 128)))
        features_path = outputs_dir / "features.npy"
        np.save(features_path, features)
        outputs["features"] = str(features_path)

    return {
        "outputs": outputs,
        "summary": summary,
        "metrics": metrics,
        "message": "PyTorch simulation completed (fallback).",
    }


__all__ = [
    "DLPyTorchParameters",
    "dl_pytorch_from_payload",
    "run_dl_pytorch",
]
