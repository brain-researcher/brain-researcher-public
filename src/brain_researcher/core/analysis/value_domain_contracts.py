"""General value-domain execution contracts.

These mirror the ``connectivity_contracts.safe_fisher_z`` pattern: each
``validate_*`` asserts a value-domain invariant and **raises** on violation
(no silent repair), returning a diagnostics dict on success; each ``safe_*``
validates and then applies the transform. Diagnostics dicts share the shape
consumed by the scientific-review gate so a detector can surface a blocking
finding even when the contract is not on the hot path.

Each contract backs a declared ``value_domain`` rule in
``configs/br-kg/scientific_review_failure_mode_registry.yaml``:

- ``validate_probability_domain`` / ``safe_logit`` -> REVIEW_VALUEDOMAIN_LOGIT_OUT_OF_01,
  REVIEW_VALUEDOMAIN_PVAL_TYPE_CONFUSION
- ``validate_positive_for_log`` / ``safe_log`` -> REVIEW_VALUEDOMAIN_LOG_NONPOSITIVE,
  REVIEW_VALUEDOMAIN_SQRT_BOXCOX_NEGATIVE
- ``validate_finite`` -> REVIEW_VALUEDOMAIN_NONFINITE_PROPAGATION
- ``validate_well_conditioned`` -> REVIEW_VALUEDOMAIN_DIV_BY_NEAR_ZERO,
  REVIEW_VALUEDOMAIN_NEGATIVE_VARIANCE_EIG
"""

from __future__ import annotations

from typing import Any

import numpy as np


def _as_float_array(values: Any) -> np.ndarray:
    return np.asarray(values, dtype=float)


def validate_finite(values: Any, name: str) -> dict[str, float | int | str]:
    """Assert that ``values`` are all finite (no NaN / Inf).

    Backs REVIEW_VALUEDOMAIN_NONFINITE_PROPAGATION. Use at stage boundaries to
    stop a single NaN/Inf from silently propagating through downstream math.
    """

    array = _as_float_array(values)
    n_values = int(array.size)
    if n_values == 0:
        raise ValueError(f"{name} is empty; refusing to treat as finite data.")
    finite = np.isfinite(array)
    n_finite = int(finite.sum())
    n_nan = int(np.isnan(array).sum())
    n_inf = int(np.isinf(array).sum())
    if n_finite != n_values:
        raise ValueError(
            f"{name} contains {n_values - n_finite} non-finite values "
            f"({n_nan} NaN, {n_inf} Inf); refusing to propagate."
        )
    return {
        "name": str(name),
        "n_values": n_values,
        "n_finite": n_finite,
        "n_nan": n_nan,
        "n_inf": n_inf,
    }


def validate_probability_domain(
    values: Any,
    name: str,
    *,
    tolerance: float = 1e-9,
    max_outside_fraction: float = 0.0,
) -> dict[str, float | int | str]:
    """Assert that ``values`` lie in the closed unit interval ``[0, 1]``.

    Backs REVIEW_VALUEDOMAIN_LOGIT_OUT_OF_01 and the value-domain half of
    REVIEW_VALUEDOMAIN_PVAL_TYPE_CONFUSION. A p-value, probability, proportion,
    AUC or accuracy outside ``[0, 1]`` is almost always a sign of the wrong
    quantity being passed (e.g. ``1 - p``, ``-log10(p)``, or an unnormalised
    score) rather than data to clip.
    """

    array = _as_float_array(values)
    n_values = int(array.size)
    if n_values == 0:
        raise ValueError(f"{name} is empty; refusing to treat as probabilities.")
    if int(np.isfinite(array).sum()) != n_values:
        raise ValueError(
            f"{name} contains non-finite values; not a valid probability domain."
        )

    tol = float(tolerance)
    below = array < (0.0 - tol)
    above = array > (1.0 + tol)
    outside = below | above
    outside_count = int(outside.sum())
    outside_fraction = outside_count / n_values
    min_value = float(array.min())
    max_value = float(array.max())

    if outside_fraction > float(max_outside_fraction):
        raise ValueError(
            f"{name} has {outside_count} value(s) outside [0, 1] "
            f"(min={min_value:.6g}, max={max_value:.6g}). This does not look "
            "like probabilities/p-values; refusing to proceed. Check for "
            "1-p / -log10(p) / unnormalised-score confusion."
        )
    return {
        "name": str(name),
        "n_values": n_values,
        "min": min_value,
        "max": max_value,
        "outside_unit_interval_count": outside_count,
        "outside_unit_interval_fraction": outside_fraction,
        "tolerance": tol,
        "max_outside_fraction": float(max_outside_fraction),
    }


def safe_logit(
    values: Any,
    name: str,
    *,
    eps: float = 1e-6,
    tolerance: float = 1e-9,
    return_diagnostics: bool = False,
) -> np.ndarray | tuple[np.ndarray, dict[str, float | int | str]]:
    """Apply the logit after validating the probability domain.

    Values are clamped to ``[eps, 1 - eps]`` only to keep the logit finite at
    the exact boundaries; values genuinely outside ``[0, 1]`` raise.
    """

    if not 0.0 < float(eps) < 0.5:
        raise ValueError("eps must be in (0, 0.5) for a stable logit.")
    diagnostics = validate_probability_domain(values, name, tolerance=tolerance)
    array = _as_float_array(values)
    clamped = np.clip(array, float(eps), 1.0 - float(eps))
    diagnostics = {
        **diagnostics,
        "boundary_clamp_count": int(
            ((array < float(eps)) | (array > 1.0 - float(eps))).sum()
        ),
        "boundary_clamp_eps": float(eps),
    }
    transformed = np.log(clamped / (1.0 - clamped))
    if return_diagnostics:
        return transformed, diagnostics
    return transformed


def validate_positive_for_log(
    values: Any,
    name: str,
    *,
    allow_zero: bool = False,
) -> dict[str, float | int | str]:
    """Assert that ``values`` are strictly positive (or non-negative).

    Backs REVIEW_VALUEDOMAIN_LOG_NONPOSITIVE and
    REVIEW_VALUEDOMAIN_SQRT_BOXCOX_NEGATIVE. ``log``/``Box-Cox`` require
    strictly positive inputs; ``sqrt`` requires non-negative (``allow_zero``).
    """

    array = _as_float_array(values)
    n_values = int(array.size)
    if n_values == 0:
        raise ValueError(f"{name} is empty; refusing to apply a log/sqrt transform.")
    if int(np.isfinite(array).sum()) != n_values:
        raise ValueError(f"{name} contains non-finite values before log/sqrt.")

    threshold = 0.0
    invalid = array < threshold if allow_zero else array <= threshold
    invalid_count = int(invalid.sum())
    min_value = float(array.min())
    if invalid_count:
        bound = "negative" if allow_zero else "non-positive"
        raise ValueError(
            f"{name} has {invalid_count} {bound} value(s) (min={min_value:.6g}); "
            "refusing to apply a log/sqrt/Box-Cox transform."
        )
    return {
        "name": str(name),
        "n_values": n_values,
        "min": min_value,
        "allow_zero": bool(allow_zero),
        "nonpositive_count": invalid_count,
    }


def safe_log(
    values: Any,
    name: str,
    *,
    return_diagnostics: bool = False,
) -> np.ndarray | tuple[np.ndarray, dict[str, float | int | str]]:
    """Apply the natural log after validating strict positivity."""

    diagnostics = validate_positive_for_log(values, name, allow_zero=False)
    transformed = np.log(_as_float_array(values))
    if return_diagnostics:
        return transformed, diagnostics
    return transformed


def validate_well_conditioned(
    matrix: Any,
    name: str,
    *,
    max_condition_number: float = 1e10,
    min_eig: float = -1e-8,
    require_symmetric: bool = True,
) -> dict[str, float | int | str | bool]:
    """Assert that a square matrix is safe to invert / treat as a covariance.

    Backs REVIEW_VALUEDOMAIN_DIV_BY_NEAR_ZERO (near-singular condition number)
    and REVIEW_VALUEDOMAIN_NEGATIVE_VARIANCE_EIG (negative eigenvalue in a
    matrix that should be positive semi-definite). Call before
    ``np.linalg.inv`` / ``pinv`` or before treating a matrix as a covariance.
    """

    array = _as_float_array(matrix)
    if array.ndim != 2 or array.shape[0] != array.shape[1] or array.size == 0:
        raise ValueError(
            f"{name} is not a non-empty square matrix; cannot check conditioning."
        )
    if int(np.isfinite(array).sum()) != array.size:
        raise ValueError(f"{name} contains non-finite entries; refusing to invert.")

    target = 0.5 * (array + array.T) if require_symmetric else array
    try:
        condition_number = float(np.linalg.cond(target))
    except np.linalg.LinAlgError:
        condition_number = float("inf")
    if not np.isfinite(condition_number) or condition_number > float(
        max_condition_number
    ):
        raise ValueError(
            f"{name} is near-singular (condition number={condition_number:.6g} "
            f"> {float(max_condition_number):.6g}); refusing to invert. Add "
            "regularization or use a pseudo-inverse with explicit rationale."
        )

    smallest_eig: float | None = None
    if require_symmetric:
        try:
            smallest_eig = float(np.linalg.eigvalsh(target).min())
        except np.linalg.LinAlgError:
            smallest_eig = None
        if smallest_eig is not None and smallest_eig < float(min_eig):
            raise ValueError(
                f"{name} has a negative eigenvalue ({smallest_eig:.6g} < "
                f"{float(min_eig):.6g}); not positive semi-definite. A variance "
                "or covariance must not have negative eigenvalues."
            )
    return {
        "name": str(name),
        "n_rows": int(array.shape[0]),
        "condition_number": condition_number,
        "min_eig": smallest_eig if smallest_eig is not None else float("nan"),
        "max_condition_number": float(max_condition_number),
        "min_eig_threshold": float(min_eig),
        "symmetrized": bool(require_symmetric),
    }
