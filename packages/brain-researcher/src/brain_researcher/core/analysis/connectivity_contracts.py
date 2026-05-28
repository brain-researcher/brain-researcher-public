"""Contracts for functional-connectivity value domains."""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


def validate_for_fisher_z(
    values: Any,
    name: str,
    *,
    max_outside_fraction: float = 1e-6,
    tolerance: float = 1e-7,
) -> dict[str, float | int | str]:
    """Validate that input values are eligible for a Fisher z-transform."""

    array = np.asarray(values, dtype=float)
    finite = np.isfinite(array)
    n_values = int(array.size)
    n_finite = int(finite.sum())
    if n_values == 0:
        raise ValueError(f"{name} is empty; refusing to apply Fisher z-transform.")
    if n_finite != n_values:
        raise ValueError(
            f"{name} contains {n_values - n_finite} non-finite values; "
            "refusing to apply Fisher z-transform."
        )

    abs_values = np.abs(array)
    outside = abs_values > (1.0 + float(tolerance))
    outside_count = int(outside.sum())
    outside_fraction = outside_count / n_values
    max_abs = float(abs_values.max(initial=0.0))

    if outside_fraction > float(max_outside_fraction):
        raise ValueError(
            f"{name} has {outside_fraction:.6%} values outside [-1, 1] "
            f"(max abs={max_abs:.6g}). This does not look like raw Pearson "
            "correlation data. Refusing to apply Fisher z-transform."
        )

    return {
        "name": str(name),
        "n_values": n_values,
        "n_finite": n_finite,
        "max_abs": max_abs,
        "outside_unit_interval_count": outside_count,
        "outside_unit_interval_fraction": outside_fraction,
        "max_outside_fraction": float(max_outside_fraction),
        "tolerance": float(tolerance),
    }


def safe_fisher_z(
    values: Any,
    name: str,
    *,
    max_outside_fraction: float = 1e-6,
    tolerance: float = 1e-7,
    clip: float = 0.999999,
    return_diagnostics: bool = False,
) -> np.ndarray | tuple[np.ndarray, dict[str, float | int | str]]:
    """Apply Fisher z after validating the raw-correlation value domain."""

    if not 0.0 < float(clip) < 1.0:
        raise ValueError("clip must be strictly between 0 and 1 for Fisher z.")

    diagnostics = validate_for_fisher_z(
        values,
        name,
        max_outside_fraction=max_outside_fraction,
        tolerance=tolerance,
    )
    array = np.asarray(values, dtype=float)
    clipped = np.clip(array, -float(clip), float(clip))
    diagnostics = {
        **diagnostics,
        "boundary_clip_count": int((np.abs(array) > float(clip)).sum()),
        "boundary_clip_fraction": float((np.abs(array) > float(clip)).mean()),
        "boundary_clip_value": float(clip),
    }
    transformed = np.arctanh(clipped)
    if return_diagnostics:
        return transformed, diagnostics
    return transformed


@dataclass(frozen=True)
class FeatureContract:
    """Sidecar contract describing a functional-connectivity / feature matrix.

    Field names mirror the aliases consumed by
    ``services.review.checks.correlation_validity`` so the deterministic review
    gate can satisfy ``REVIEW_MATRIX_PARTIAL_SINGULAR`` without inference.
    """

    matrix_kind: str
    source_level: str
    n_rois: int
    n_timepoints: int | None = None
    effective_n_timepoints: int | None = None
    covariance_estimator: str | None = None
    precision_estimator: str | None = None
    regularization: str | bool | None = None
    regularization_alpha: float | None = None
    covariance_rank: int | None = None
    precision_rank: int | None = None
    covariance_condition_number: float | None = None
    precision_condition_number: float | None = None
    min_eig: float | None = None
    transform_state: str | None = None
    fisher_z_diagnostics: dict[str, Any] | None = None
    extras: dict[str, Any] = field(default_factory=dict)
    contract_sha256: str | None = None
    generated_at: str | None = None


def compute_estimator_diagnostics(matrix: Any) -> dict[str, float | int]:
    """Compute rank / condition number / minimum eigenvalue for a square matrix.

    Returns NaNs when the matrix is empty or non-square; callers should treat
    them as missing and not as a hazard.
    """

    array = np.asarray(matrix, dtype=float)
    if array.ndim != 2 or array.shape[0] != array.shape[1] or array.size == 0:
        return {
            "rank": 0,
            "condition_number": float("nan"),
            "min_eig": float("nan"),
        }

    symmetric = 0.5 * (array + array.T)
    try:
        rank = int(np.linalg.matrix_rank(symmetric))
    except np.linalg.LinAlgError:
        rank = 0
    try:
        cond = float(np.linalg.cond(symmetric))
    except np.linalg.LinAlgError:
        cond = float("inf")
    try:
        eigs = np.linalg.eigvalsh(symmetric)
        min_eig = float(eigs.min()) if eigs.size else float("nan")
    except np.linalg.LinAlgError:
        min_eig = float("nan")
    return {"rank": rank, "condition_number": cond, "min_eig": min_eig}


def _finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def aggregate_estimator_diagnostics(matrix: Any) -> dict[str, float | int | None]:
    """Conservatively aggregate diagnostics over a square matrix or matrix stack."""

    array = np.asarray(matrix, dtype=float)
    if array.ndim == 2 and array.shape[0] == array.shape[1]:
        stack = array[np.newaxis, ...]
    elif array.ndim == 3 and array.shape[-2] == array.shape[-1]:
        stack = array.reshape((-1, array.shape[-2], array.shape[-1]))
    else:
        return {"rank": None, "condition_number": None, "min_eig": None}

    diagnostics = [compute_estimator_diagnostics(item) for item in stack]
    ranks = [int(item["rank"]) for item in diagnostics if item.get("rank")]
    conditions = [
        value
        for value in (
            _finite_or_none(item.get("condition_number")) for item in diagnostics
        )
        if value is not None
    ]
    min_eigs = [
        value
        for value in (_finite_or_none(item.get("min_eig")) for item in diagnostics)
        if value is not None
    ]
    return {
        "rank": min(ranks) if ranks else None,
        "condition_number": max(conditions) if conditions else None,
        "min_eig": min(min_eigs) if min_eigs else None,
    }


def infer_regularization_from_estimator(estimator_name: Any) -> str | None:
    """Return a conservative regularization label for a covariance estimator."""

    if estimator_name is None:
        return None
    text = str(estimator_name).strip().lower().replace("-", "_")
    if not text:
        return None
    if any(
        token in text
        for token in (
            "empiricalcovariance",
            "empirical_covariance",
            "sample_covariance",
            "sample",
            "unregularized",
            "maximum_likelihood",
            "mle",
        )
    ):
        return "unregularized"
    if any(
        token in text
        for token in (
            "ledoitwolf",
            "ledoit",
            "oas",
            "oracle_approximating",
            "graphicallasso",
            "graphical_lasso",
            "glasso",
            "shrink",
            "regularized",
            "ridge",
            "tikhonov",
        )
    ):
        return "regularized"
    return None


def build_feature_contract(
    matrix: Any,
    *,
    matrix_kind: str,
    source_level: str,
    n_rois: int | None = None,
    n_timepoints: int | None = None,
    effective_n_timepoints: int | None = None,
    covariance_estimator: str | None = None,
    precision_estimator: str | None = None,
    regularization: str | bool | None = None,
    regularization_alpha: float | None = None,
    fisher_z_diagnostics: dict[str, Any] | None = None,
    extras: dict[str, Any] | None = None,
) -> FeatureContract:
    """Build a reviewable feature contract from an FC matrix artifact."""

    array = np.asarray(matrix)
    inferred_n_rois = n_rois
    if (
        inferred_n_rois is None
        and array.ndim >= 2
        and array.shape[-1] == array.shape[-2]
    ):
        inferred_n_rois = int(array.shape[-1])
    if inferred_n_rois is None:
        raise ValueError("n_rois is required when matrix is not square.")

    kind_text = str(matrix_kind).strip().lower().replace("-", "_")
    is_precision_like = (
        "partial" in kind_text
        or "precision" in kind_text
        or kind_text in {"partial_correlation", "partial_corr"}
    )
    if precision_estimator is None and is_precision_like:
        precision_estimator = covariance_estimator

    estimator_name = precision_estimator if is_precision_like else covariance_estimator
    regularization_label = (
        regularization
        if regularization is not None
        else infer_regularization_from_estimator(estimator_name)
    )
    diagnostics = aggregate_estimator_diagnostics(array)
    transform_state = (
        "fisher_z" if fisher_z_diagnostics is not None else "raw_connectivity"
    )

    return FeatureContract(
        matrix_kind=str(matrix_kind),
        source_level=str(source_level),
        n_rois=int(inferred_n_rois),
        n_timepoints=int(n_timepoints) if n_timepoints is not None else None,
        effective_n_timepoints=(
            int(effective_n_timepoints)
            if effective_n_timepoints is not None
            else (int(n_timepoints) if n_timepoints is not None else None)
        ),
        covariance_estimator=covariance_estimator,
        precision_estimator=precision_estimator,
        regularization=regularization_label,
        regularization_alpha=regularization_alpha,
        covariance_rank=diagnostics["rank"] if not is_precision_like else None,
        precision_rank=diagnostics["rank"] if is_precision_like else None,
        covariance_condition_number=(
            diagnostics["condition_number"] if not is_precision_like else None
        ),
        precision_condition_number=(
            diagnostics["condition_number"] if is_precision_like else None
        ),
        min_eig=diagnostics["min_eig"],
        transform_state=transform_state,
        fisher_z_diagnostics=fisher_z_diagnostics,
        extras=extras or {},
    )


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _serialize_contract(contract: FeatureContract) -> dict[str, Any]:
    payload = asdict(contract)
    payload.pop("contract_sha256", None)
    payload.pop("generated_at", None)
    return payload


def write_feature_contract(
    contract: FeatureContract,
    output_dir: str | Path,
    *,
    filename: str = "feature_contract.json",
) -> Path:
    """Write ``feature_contract.json`` and return its path.

    The on-disk file carries a ``contract_sha256`` hash of the canonical payload
    and a UTC ``generated_at`` timestamp so reviewers can detect tampering.
    """

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    canonical_payload = _serialize_contract(contract)
    sha = hashlib.sha256(_canonical_json(canonical_payload).encode("utf-8")).hexdigest()
    generated_at = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    stamped = {
        **canonical_payload,
        "contract_sha256": sha,
        "generated_at": generated_at,
    }
    target = target_dir / filename
    target.write_text(
        json.dumps(stamped, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return target
