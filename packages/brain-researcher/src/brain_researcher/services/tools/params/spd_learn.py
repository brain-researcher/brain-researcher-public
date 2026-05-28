"""SPD (Symmetric Positive Definite) matrix helpers with spd_learn / numpy fallbacks.

Provides 6 parameter sets + execution functions:
  1. CovarianceEstimate – timeseries → covariance matrix
  2. SPDProject – ensure SPD stability via eigenvalue clamping
  3. SPDLogm – matrix logarithm (tangent space map)
  4. SPDGeodesicDistance – pairwise SPD distance (AIRM / Log-Euclidean)
  5. SPDBiMap – learnable bilinear dimensionality reduction
  6. SPDNetTrain – train SPDNet classifier on SPD data
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy import helpers
# ---------------------------------------------------------------------------
_SPD_LEARN_AVAILABLE: Optional[bool] = None


def _has_spd_learn() -> bool:
    global _SPD_LEARN_AVAILABLE
    if _SPD_LEARN_AVAILABLE is None:
        try:
            import spd_learn  # noqa: F401
            _SPD_LEARN_AVAILABLE = True
        except ImportError:
            _SPD_LEARN_AVAILABLE = False
    return _SPD_LEARN_AVAILABLE


def _has_torch() -> bool:
    try:
        import torch  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Shared I/O helpers
# ---------------------------------------------------------------------------


def _load_matrix(path: Path) -> np.ndarray:
    """Load a matrix from .npy or .npz."""
    if path.suffix == ".npy":
        return np.load(path)
    if path.suffix == ".npz":
        npz = np.load(path)
        return npz[npz.files[0]]
    raise ValueError(f"Unsupported format: {path}")


def _save_matrix(arr: np.ndarray, path: Path) -> Path:
    """Save a matrix as .npz (default) or .npy based on extension."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".npy":
        np.save(path, arr)
    else:
        np.savez_compressed(path, matrix=arr)
    return path


# ============================================================================
# 1. Covariance Estimation
# ============================================================================


@dataclass(frozen=True)
class CovarianceEstimateParameters:
    """Convert raw timeseries to SPD covariance matrix."""

    data_file: str
    output_file: str
    method: str = "empirical"  # empirical, ledoit_wolf, oas, shrinkage
    standardize: bool = True
    diagonal: bool = False


def covariance_estimate_from_payload(payload: Dict[str, Any]) -> CovarianceEstimateParameters:
    return CovarianceEstimateParameters(
        data_file=str(payload["data_file"]),
        output_file=str(payload["output_file"]),
        method=str(payload.get("method", "empirical")),
        standardize=bool(payload.get("standardize", True)),
        diagonal=bool(payload.get("diagonal", False)),
    )


def run_covariance_estimate(params: CovarianceEstimateParameters) -> Dict[str, Any]:
    """Compute covariance matrix from timeseries data."""
    ts = _load_matrix(Path(params.data_file))

    if params.standardize:
        mean = ts.mean(axis=0, keepdims=True)
        std = ts.std(axis=0, keepdims=True)
        std[std < 1e-12] = 1.0
        ts = (ts - mean) / std

    fallback = False
    method = params.method

    if _has_spd_learn() and _has_torch() and method == "empirical":
        import torch
        from spd_learn.functional import sample_covariance

        # spd_learn covariance expects (B, C, T) and returns (B, C, C)
        ts_t = torch.tensor(ts, dtype=torch.float64).unsqueeze(0)  # (1, T, C)
        ts_t = ts_t.transpose(-1, -2)  # → (1, C, T)
        cov_t = sample_covariance(ts_t)
        cov = cov_t.squeeze(0).numpy()
    else:
        # Use sklearn for regularized methods, numpy for empirical
        fallback = True
        if method == "ledoit_wolf":
            try:
                from sklearn.covariance import LedoitWolf
                cov = LedoitWolf().fit(ts).covariance_
            except ImportError:
                cov = np.cov(ts, rowvar=False)
        elif method == "oas":
            try:
                from sklearn.covariance import OAS
                cov = OAS().fit(ts).covariance_
            except ImportError:
                cov = np.cov(ts, rowvar=False)
        elif method == "shrinkage":
            try:
                from sklearn.covariance import ShrunkCovariance
                cov = ShrunkCovariance().fit(ts).covariance_
            except ImportError:
                cov = np.cov(ts, rowvar=False)
        else:
            cov = np.cov(ts, rowvar=False)

    if params.diagonal:
        cov = np.diag(np.diag(cov))

    out_path = Path(params.output_file)
    _save_matrix(cov, out_path)

    return {
        "covariance_file": str(out_path),
        "shape": list(cov.shape),
        "method": method,
        "fallback": fallback,
        "message": f"Covariance ({method}) computed: {cov.shape}",
    }


# ============================================================================
# 2. SPD Projection
# ============================================================================


@dataclass(frozen=True)
class SPDProjectParameters:
    """Ensure matrix is SPD via eigenvalue clamping / regularization."""

    matrix_file: str
    output_file: str
    epsilon: float = 1e-6
    method: str = "eig_clamp"  # eig_clamp, add_epsilon, project


def spd_project_from_payload(payload: Dict[str, Any]) -> SPDProjectParameters:
    return SPDProjectParameters(
        matrix_file=str(payload["matrix_file"]),
        output_file=str(payload["output_file"]),
        epsilon=float(payload.get("epsilon", 1e-6)),
        method=str(payload.get("method", "eig_clamp")),
    )


def run_spd_project(params: SPDProjectParameters) -> Dict[str, Any]:
    """Project a matrix to SPD cone."""
    mat = _load_matrix(Path(params.matrix_file))
    eps = params.epsilon
    fallback = False

    if _has_spd_learn() and _has_torch():
        import torch
        from spd_learn.functional import clamp_eigvals, ensure_sym

        mat_t = torch.tensor(mat, dtype=torch.float64).unsqueeze(0)
        mat_t = ensure_sym(mat_t)
        if params.method == "eig_clamp":
            # clamp_eigvals is an autograd Function → use .apply()
            mat_t = clamp_eigvals.apply(mat_t, eps)
        else:
            mat_t = mat_t + eps * torch.eye(mat.shape[0], dtype=torch.float64)
        result_mat = mat_t.squeeze(0).detach().numpy()
    else:
        fallback = True
        # Symmetrize
        mat = (mat + mat.T) / 2.0
        eigvals, eigvecs = np.linalg.eigh(mat)
        if params.method == "eig_clamp":
            eigvals = np.maximum(eigvals, eps)
            result_mat = (eigvecs * eigvals) @ eigvecs.T
        else:
            result_mat = mat + eps * np.eye(mat.shape[0])

    # Verify SPD
    min_eig = float(np.linalg.eigvalsh(result_mat).min())
    is_spd = min_eig > 0

    out_path = Path(params.output_file)
    _save_matrix(result_mat, out_path)

    return {
        "spd_file": str(out_path),
        "is_spd": is_spd,
        "min_eig": min_eig,
        "method": params.method,
        "fallback": fallback,
        "message": f"SPD projection ({params.method}): min_eig={min_eig:.2e}, is_spd={is_spd}",
    }


# ============================================================================
# 3. Matrix Logarithm (tangent space)
# ============================================================================


@dataclass(frozen=True)
class SPDLogmParameters:
    """Matrix logarithm on SPD manifold."""

    spd_matrix_file: str
    output_file: str
    reference: str = "identity"  # identity, or file path to reference SPD


def spd_logm_from_payload(payload: Dict[str, Any]) -> SPDLogmParameters:
    return SPDLogmParameters(
        spd_matrix_file=str(payload["spd_matrix_file"]),
        output_file=str(payload["output_file"]),
        reference=str(payload.get("reference", "identity")),
    )


def run_spd_logm(params: SPDLogmParameters) -> Dict[str, Any]:
    """Compute matrix logarithm."""
    mat = _load_matrix(Path(params.spd_matrix_file))
    fallback = False

    if _has_spd_learn() and _has_torch():
        import torch
        from spd_learn.functional import log_map_airm, matrix_log

        mat_t = torch.tensor(mat, dtype=torch.float64).unsqueeze(0)
        if params.reference == "identity":
            # matrix_log is an autograd Function → use .apply()
            logm = matrix_log.apply(mat_t).squeeze(0).detach().numpy()
        else:
            ref = _load_matrix(Path(params.reference))
            ref_t = torch.tensor(ref, dtype=torch.float64).unsqueeze(0)
            logm = log_map_airm(mat_t, ref_t).squeeze(0).numpy()
    else:
        fallback = True
        from scipy.linalg import logm as scipy_logm

        if params.reference == "identity":
            logm = np.real(scipy_logm(mat))
        else:
            ref = _load_matrix(Path(params.reference))
            # Log map at reference: ref^{-1/2} @ logm(ref^{-1/2} @ mat @ ref^{-1/2}) @ ref^{1/2}
            eigvals, eigvecs = np.linalg.eigh(ref)
            ref_inv_sqrt = (eigvecs * (1.0 / np.sqrt(eigvals))) @ eigvecs.T
            ref_sqrt = (eigvecs * np.sqrt(eigvals)) @ eigvecs.T
            inner = ref_inv_sqrt @ mat @ ref_inv_sqrt
            logm = ref_sqrt @ np.real(scipy_logm(inner)) @ ref_sqrt

    out_path = Path(params.output_file)
    _save_matrix(logm, out_path)

    return {
        "logm_file": str(out_path),
        "shape": list(logm.shape),
        "reference": params.reference,
        "fallback": fallback,
        "message": f"Matrix log computed: {logm.shape}",
    }


# ============================================================================
# 4. Geodesic Distance
# ============================================================================


@dataclass(frozen=True)
class SPDGeodesicDistanceParameters:
    """Geodesic distance between SPD matrices."""

    matrix_a_file: str
    matrix_b_file: str
    metric: str = "log_euclidean"  # log_euclidean, airm, euclidean
    output_file: Optional[str] = None


def spd_geodesic_distance_from_payload(payload: Dict[str, Any]) -> SPDGeodesicDistanceParameters:
    return SPDGeodesicDistanceParameters(
        matrix_a_file=str(payload["matrix_a_file"]),
        matrix_b_file=str(payload["matrix_b_file"]),
        metric=str(payload.get("metric", "log_euclidean")),
        output_file=payload.get("output_file"),
    )


def run_spd_geodesic_distance(params: SPDGeodesicDistanceParameters) -> Dict[str, Any]:
    """Compute geodesic distance between two SPD matrices."""
    a = _load_matrix(Path(params.matrix_a_file))
    b = _load_matrix(Path(params.matrix_b_file))
    fallback = False

    if _has_spd_learn() and _has_torch():
        import torch

        a_t = torch.tensor(a, dtype=torch.float64).unsqueeze(0)
        b_t = torch.tensor(b, dtype=torch.float64).unsqueeze(0)

        if params.metric == "airm":
            from spd_learn.functional import airm_distance
            dist = float(airm_distance(a_t, b_t).item())
        elif params.metric == "log_euclidean":
            from spd_learn.functional import log_euclidean_distance
            dist = float(log_euclidean_distance(a_t, b_t).item())
        else:
            dist = float(np.linalg.norm(a - b, "fro"))
    else:
        fallback = True
        if params.metric == "airm":
            from scipy.linalg import logm as scipy_logm

            eigvals, eigvecs = np.linalg.eigh(a)
            a_inv_sqrt = (eigvecs * (1.0 / np.sqrt(eigvals))) @ eigvecs.T
            inner = a_inv_sqrt @ b @ a_inv_sqrt
            dist = float(np.linalg.norm(np.real(scipy_logm(inner)), "fro"))
        elif params.metric == "log_euclidean":
            from scipy.linalg import logm as scipy_logm

            log_a = np.real(scipy_logm(a))
            log_b = np.real(scipy_logm(b))
            dist = float(np.linalg.norm(log_a - log_b, "fro"))
        else:
            dist = float(np.linalg.norm(a - b, "fro"))

    result: Dict[str, Any] = {
        "distances": [dist],
        "mean_distance": dist,
        "metric": params.metric,
        "fallback": fallback,
        "message": f"Distance ({params.metric}): {dist:.6f}",
    }

    if params.output_file:
        out_path = Path(params.output_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        result["output_file"] = str(out_path)

    return result


# ============================================================================
# 5. BiMap (Learnable bilinear mapping)
# ============================================================================


@dataclass(frozen=True)
class SPDBiMapParameters:
    """Learnable bilinear mapping for SPD dimensionality reduction."""

    data_files: List[str] = field(default_factory=list)
    labels_file: Optional[str] = None
    output_dim: int = 10
    output_dir: str = "spd_bimap_output"
    epochs: int = 50
    learning_rate: float = 0.01


def spd_bimap_from_payload(payload: Dict[str, Any]) -> SPDBiMapParameters:
    data_files = payload.get("data_files", [])
    if isinstance(data_files, str):
        data_files = [data_files]
    return SPDBiMapParameters(
        data_files=[str(f) for f in data_files],
        labels_file=payload.get("labels_file"),
        output_dim=int(payload.get("output_dim", 10)),
        output_dir=str(payload.get("output_dir", "spd_bimap_output")),
        epochs=int(payload.get("epochs", 50)),
        learning_rate=float(payload.get("learning_rate", 0.01)),
    )


def run_spd_bimap(params: SPDBiMapParameters) -> Dict[str, Any]:
    """Apply BiMap dimensionality reduction to SPD matrices."""
    out_dir = Path(params.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load SPD matrices
    matrices = [_load_matrix(Path(f)) for f in params.data_files]
    if not matrices:
        raise ValueError("No data_files provided")

    input_dim = matrices[0].shape[0]
    output_dim = min(params.output_dim, input_dim)
    n_samples = len(matrices)

    if _has_spd_learn() and _has_torch():
        import torch
        from spd_learn import BiMap

        data = torch.tensor(np.stack(matrices), dtype=torch.float32)  # (N, C, C)
        layer = BiMap(input_dim, output_dim)
        optimizer = torch.optim.Adam(layer.parameters(), lr=params.learning_rate)

        # Simple reconstruction-based training loop
        losses: List[float] = []
        for epoch in range(params.epochs):
            projected = layer(data)  # (N, output_dim, output_dim)

            # Minimize negative log-det (proxy objective for preserving geometry)
            eigvals = torch.linalg.eigvalsh(projected)
            loss = -torch.log(eigvals.clamp(min=1e-8)).mean()

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            losses.append(float(loss.item()))

        # Save projected matrices
        projected_np = layer(data).detach().numpy()
        model_path = out_dir / "bimap_model.pt"
        torch.save(layer.state_dict(), model_path)
        fallback = False
    else:
        # Fallback: PCA-like reduction via eigendecomposition
        fallback = True
        stacked = np.stack(matrices)  # (N, C, C)
        mean_mat = stacked.mean(axis=0)
        eigvals, eigvecs = np.linalg.eigh(mean_mat)
        W = eigvecs[:, -output_dim:]  # top eigenvectors
        projected_np = np.array([W.T @ m @ W for m in matrices])  # (N, d, d)
        model_path = out_dir / "bimap_projection.npz"
        np.savez_compressed(model_path, W=W)
        losses = []

    projected_path = out_dir / "projected_matrices.npz"
    np.savez_compressed(projected_path, matrices=projected_np)

    summary = {
        "n_samples": n_samples,
        "input_dim": input_dim,
        "output_dim": output_dim,
        "epochs": params.epochs if not fallback else 0,
        "final_loss": losses[-1] if losses else None,
        "fallback": fallback,
    }
    summary_path = out_dir / "bimap_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return {
        "model_path": str(model_path),
        "projected_path": str(projected_path),
        "summary_path": str(summary_path),
        "shape": list(projected_np.shape),
        "fallback": fallback,
        "message": f"BiMap {input_dim}→{output_dim} on {n_samples} matrices.",
    }


# ============================================================================
# 6. SPDNet Training
# ============================================================================


@dataclass(frozen=True)
class SPDNetTrainParameters:
    """Train SPDNet classifier on SPD covariance data."""

    data_files: List[str] = field(default_factory=list)
    output_dir: str = "spdnet_output"
    architecture: str = "spdnet"  # spdnet, eeg_spdnet
    n_classes: int = 2
    epochs: int = 100
    batch_size: int = 32
    learning_rate: float = 0.001
    val_split: float = 0.2
    labels_file: Optional[str] = None


def spdnet_train_from_payload(payload: Dict[str, Any]) -> SPDNetTrainParameters:
    data_files = payload.get("data_files", [])
    if isinstance(data_files, str):
        data_files = [data_files]
    return SPDNetTrainParameters(
        data_files=[str(f) for f in data_files],
        output_dir=str(payload.get("output_dir", "spdnet_output")),
        architecture=str(payload.get("architecture", "spdnet")),
        n_classes=int(payload.get("n_classes", 2)),
        epochs=int(payload.get("epochs", 100)),
        batch_size=int(payload.get("batch_size", 32)),
        learning_rate=float(payload.get("learning_rate", 0.001)),
        val_split=float(payload.get("val_split", 0.2)),
        labels_file=payload.get("labels_file"),
    )


def _load_labels(path: Optional[str]) -> Optional[np.ndarray]:
    if not path:
        return None
    p = Path(path)
    if p.suffix == ".npy":
        return np.load(p)
    if p.suffix == ".npz":
        npz = np.load(p)
        return npz[npz.files[0]]
    return None


def run_spdnet_train(params: SPDNetTrainParameters) -> Dict[str, Any]:
    """Train SPDNet on SPD matrices."""
    out_dir = Path(params.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load data
    matrices = [_load_matrix(Path(f)) for f in params.data_files]
    if not matrices:
        raise ValueError("No data_files provided")

    data_np = np.stack(matrices)  # (N, C, C)
    n_samples, input_dim, _ = data_np.shape
    labels_np = _load_labels(params.labels_file)

    if labels_np is None:
        rng = np.random.default_rng(42)
        labels_np = rng.integers(0, params.n_classes, size=n_samples)

    if _has_spd_learn() and _has_torch():
        import torch
        import torch.nn as nn
        from spd_learn import SPDNet, EEGSPDNet

        data_t = torch.tensor(data_np, dtype=torch.float32)
        labels_t = torch.tensor(labels_np, dtype=torch.long)

        # Train/val split
        n_val = max(1, int(n_samples * params.val_split))
        n_train = n_samples - n_val
        indices = torch.randperm(n_samples)
        train_idx, val_idx = indices[:n_train], indices[n_train:]

        # Build model
        # SPDNet requires explicit keyword args + input_type='cov' since
        # we feed pre-computed covariance matrices.
        subspacedim = max(params.n_classes, input_dim // 2)
        if params.architecture == "eeg_spdnet":
            model = EEGSPDNet(
                n_chans=input_dim,
                n_outputs=params.n_classes,
                subspacedim=subspacedim,
                input_type="cov",
            )
        else:
            model = SPDNet(
                n_chans=input_dim,
                n_outputs=params.n_classes,
                subspacedim=subspacedim,
                input_type="cov",
            )

        optimizer = torch.optim.Adam(model.parameters(), lr=params.learning_rate)
        criterion = nn.CrossEntropyLoss()

        history: List[Dict[str, float]] = []
        for epoch in range(params.epochs):
            model.train()
            # Mini-batch (simplified: full batch if small)
            train_data = data_t[train_idx]
            train_labels = labels_t[train_idx]

            logits = model(train_data)
            loss = criterion(logits, train_labels)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            # Validation
            model.eval()
            with torch.no_grad():
                val_logits = model(data_t[val_idx])
                val_loss = criterion(val_logits, labels_t[val_idx])
                val_preds = val_logits.argmax(dim=1)
                val_acc = (val_preds == labels_t[val_idx]).float().mean().item()

            history.append({
                "epoch": epoch + 1,
                "train_loss": float(loss.item()),
                "val_loss": float(val_loss.item()),
                "val_accuracy": val_acc,
            })

        # Save model
        model_path = out_dir / "spdnet_model.pt"
        torch.save(model.state_dict(), model_path)

        # Final predictions
        model.eval()
        with torch.no_grad():
            all_logits = model(data_t)
            all_preds = all_logits.argmax(dim=1).numpy()

        final_metrics = history[-1] if history else {}
        fallback = False
    else:
        # Fallback: logistic regression on vectorized upper triangle
        fallback = True
        from sklearn.linear_model import LogisticRegression

        triu_idx = np.triu_indices(input_dim)
        features = np.array([m[triu_idx] for m in matrices])

        n_val = max(1, int(n_samples * params.val_split))
        n_train = n_samples - n_val
        rng = np.random.default_rng(42)
        indices = rng.permutation(n_samples)
        train_idx, val_idx = indices[:n_train], indices[n_train:]

        clf = LogisticRegression(max_iter=params.epochs, C=1.0)
        clf.fit(features[train_idx], labels_np[train_idx])

        val_acc = float(clf.score(features[val_idx], labels_np[val_idx]))
        all_preds = clf.predict(features)

        model_path = out_dir / "spdnet_fallback_model.npz"
        np.savez_compressed(model_path, coef=clf.coef_, intercept=clf.intercept_)

        final_metrics = {"val_accuracy": val_acc, "epochs": params.epochs}
        history = [final_metrics]

    # Save predictions
    preds_path = out_dir / "predictions.npy"
    np.save(preds_path, all_preds)

    summary = {
        "architecture": params.architecture,
        "n_samples": n_samples,
        "input_dim": input_dim,
        "n_classes": params.n_classes,
        "metrics": final_metrics,
        "fallback": fallback,
    }
    summary_path = out_dir / "spdnet_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return {
        "model_path": str(model_path),
        "predictions_path": str(preds_path),
        "summary_path": str(summary_path),
        "metrics": final_metrics,
        "fallback": fallback,
        "message": f"SPDNet ({params.architecture}) trained on {n_samples} samples, {input_dim}×{input_dim}.",
    }


__all__ = [
    "CovarianceEstimateParameters",
    "covariance_estimate_from_payload",
    "run_covariance_estimate",
    "SPDProjectParameters",
    "spd_project_from_payload",
    "run_spd_project",
    "SPDLogmParameters",
    "spd_logm_from_payload",
    "run_spd_logm",
    "SPDGeodesicDistanceParameters",
    "spd_geodesic_distance_from_payload",
    "run_spd_geodesic_distance",
    "SPDBiMapParameters",
    "spd_bimap_from_payload",
    "run_spd_bimap",
    "SPDNetTrainParameters",
    "spdnet_train_from_payload",
    "run_spdnet_train",
]
