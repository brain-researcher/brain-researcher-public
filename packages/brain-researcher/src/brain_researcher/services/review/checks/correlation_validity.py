"""Correlation / FC matrix validity checks.

FC analysis is BR's highest-frequency task type. These checks catch
mathematical invalidity in connectivity matrices — errors that silently
corrupt downstream graph-theoretic or statistical analyses.
"""

from __future__ import annotations

import math
from typing import Any

from brain_researcher.core.contracts.code_review import CodeReviewBundle, ReviewFinding

_PARTIAL_KIND_KEYS = (
    "matrix_kind",
    "corr_matrix_kind",
    "correlation_matrix_kind",
    "connectivity_matrix_kind",
    "feature_matrix_kind",
    "correlation_kind",
)
_MATRIX_KIND_KEYS = _PARTIAL_KIND_KEYS
_PARTIAL_ESTIMATOR_KEYS = (
    "partial_correlation_estimator",
    "precision_estimator",
    "covariance_estimator",
    "corr_precision_estimator",
    "corr_covariance_estimator",
    "corr_estimator",
    "estimator",
)
_PARTIAL_REGULARIZATION_KEYS = (
    "regularization",
    "regularized",
    "covariance_regularization",
    "precision_regularization",
    "shrinkage",
)
_PARTIAL_SOURCE_LEVEL_KEYS = (
    "source_level",
    "connectivity_source_level",
    "matrix_source_level",
)
_TRANSFORM_STATE_KEYS = (
    "transform_state",
    "corr_transform_state",
    "connectivity_transform_state",
    "feature_transform_state",
)
_N_TIMEPOINT_KEYS = (
    "effective_n_timepoints",
    "corr_effective_n_timepoints",
    "n_timepoints",
    "corr_n_timepoints",
    "connectivity_n_timepoints",
    "n_samples",
    "n_observations",
    "timepoints",
)
_N_ROI_KEYS = (
    "n_rois",
    "n_regions",
    "corr_n_rois",
    "corr_n_regions",
    "connectivity_n_rois",
    "n_features",
)
_RANK_KEYS = (
    "corr_covariance_rank",
    "corr_precision_rank",
    "covariance_rank",
    "precision_rank",
    "estimator_rank",
    "cov_rank",
)
_CONDITION_KEYS = (
    "corr_covariance_condition_number",
    "corr_precision_condition_number",
    "fc_covariance_condition_number",
    "fc_precision_condition_number",
    "covariance_condition_number",
    "precision_condition_number",
    "partial_correlation_condition_number",
    "estimator_condition_number",
    "corr_condition_number",
)
_MIN_EIG_KEYS = (
    "corr_min_eig",
    "covariance_min_eig",
    "precision_min_eig",
    "min_eig",
)
_STABILITY_DIAGNOSTIC_KEYS = _RANK_KEYS + _CONDITION_KEYS + _MIN_EIG_KEYS
_ILL_CONDITIONED_THRESHOLD = 1e8
_MIN_EIG_THRESHOLD = 1e-10
_NON_CORRELATION_KIND_TOKENS = (
    "structural",
    "tract",
    "tractography",
    "streamline",
    "dwi",
    "dmri",
    "adjacency",
    "graph",
    "distance",
    "dissimilarity",
    "covariance",
    "coherence",
    "coh",
    "plv",
    "pli",
    "wpli",
    "aec",
    "granger",
    "causal",
)


def _corr_stat(bundle: CodeReviewBundle, key: str) -> Any:
    return bundle.stats_metrics.get(key)


def _value_present(value: Any) -> bool:
    return value not in (None, "", [], {}, ())


def _nested_mapping(mapping: dict[str, Any], key: str) -> dict[str, Any]:
    value = mapping.get(key)
    return value if isinstance(value, dict) else {}


def _review_metric_mappings(bundle: CodeReviewBundle) -> list[dict[str, Any]]:
    mappings: list[dict[str, Any]] = []

    def add_mapping(value: Any) -> None:
        if isinstance(value, dict) and value:
            mappings.append(value)
            for key in (
                "review_context",
                "feature_diagnostics",
                "connectivity",
                "correlation",
                "correlation_matrix",
                "partial_correlation",
                "feature_contract",
                "matrix",
                "estimator",
                "preprocessing",
            ):
                nested = _nested_mapping(value, key)
                if nested:
                    mappings.append(nested)

    add_mapping(bundle.stats_metrics)
    add_mapping(bundle.review_context)
    add_mapping(bundle.kg_context)

    for artifact_key in (
        "review_context",
        "source_summary",
        "analysis_bundle",
        "observation",
    ):
        artifact = bundle.observed_artifacts.get(artifact_key)
        add_mapping(artifact)
        if isinstance(artifact, dict):
            add_mapping(artifact.get("review_context"))
            add_mapping(_nested_mapping(artifact, "run_card").get("review_context"))

    deduped: list[dict[str, Any]] = []
    seen: set[int] = set()
    for mapping in mappings:
        ident = id(mapping)
        if ident in seen:
            continue
        seen.add(ident)
        deduped.append(mapping)
    return deduped


def _first_value(
    bundle: CodeReviewBundle, keys: tuple[str, ...]
) -> tuple[str, Any] | None:
    for mapping in _review_metric_mappings(bundle):
        for key in keys:
            value = mapping.get(key)
            if _value_present(value):
                return key, value
    return None


def _first_number(
    bundle: CodeReviewBundle, keys: tuple[str, ...]
) -> tuple[str, float] | None:
    raw = _first_value(bundle, keys)
    if raw is None:
        return None
    key, value = raw
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return key, number


def _first_int(
    bundle: CodeReviewBundle, keys: tuple[str, ...]
) -> tuple[str, int] | None:
    raw = _first_number(bundle, keys)
    if raw is None:
        return None
    key, value = raw
    return key, int(value)


def _looks_like_partial_correlation(value: Any) -> bool:
    text = str(value).strip().lower().replace("-", "_")
    return (
        ("partial" in text and ("corr" in text or "correlation" in text))
        or text in {"partial", "partial_corr", "partial_correlation"}
        or ("precision" in text and ("derived" in text or "matrix" in text))
    )


def _text(value: Any) -> str:
    return str(value).strip().lower().replace("-", "_")


def _is_regularized_estimator(value: Any) -> bool:
    text = _text(value)
    return any(
        token in text
        for token in (
            "graphicallasso",
            "graphical_lasso",
            "glasso",
            "ledoitwolf",
            "ledoit",
            "oas",
            "oracle_approximating",
            "shrink",
            "regularized",
            "ridge",
            "tikhonov",
        )
    )


def _is_unregularized_estimator(value: Any) -> bool:
    text = _text(value)
    return any(
        token in text
        for token in (
            "empiricalcovariance",
            "empirical_covariance",
            "empirical",
            "sample_covariance",
            "sample",
            "unregularized",
            "maximum_likelihood",
            "mle",
        )
    )


def _regularization_disabled(value: Any) -> bool:
    if value is False:
        return True
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value) == 0.0
    if isinstance(value, str):
        return value.strip().lower() in {
            "false",
            "no",
            "none",
            "0",
            "off",
            "unregularized",
        }
    return False


def _regularization_enabled(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value) > 0.0
    if isinstance(value, str):
        text = _text(value)
        return text not in {"false", "no", "none", "0", "off", "unregularized", ""}
    return False


def _partial_correlation_declared(bundle: CodeReviewBundle) -> tuple[str, Any] | None:
    kind = _first_value(bundle, _PARTIAL_KIND_KEYS)
    if kind is not None and _looks_like_partial_correlation(kind[1]):
        return kind

    estimator = _first_value(bundle, _PARTIAL_ESTIMATOR_KEYS)
    if estimator is not None and "partial" in estimator[0]:
        return estimator
    return None


def _non_correlation_matrix_declared(bundle: CodeReviewBundle) -> bool:
    kind = _first_value(bundle, _MATRIX_KIND_KEYS)
    if kind is None:
        return False
    text = _text(kind[1])
    if _looks_like_partial_correlation(text):
        return False
    if "corr" in text or "correlation" in text or "pearson" in text:
        return False
    return any(token in text for token in _NON_CORRELATION_KIND_TOKENS)


def corr_has_nan_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Error if connectivity matrix contains NaN or Inf values."""
    val = _corr_stat(bundle, "corr_has_nan")
    if val is True:
        return ReviewFinding(
            rule_id="REVIEW_CORR_HAS_NAN",
            severity="error",
            message="Connectivity matrix contains NaN/Inf values.",
            suggested_fix=(
                "Check for missing ROI timeseries, zero-variance regions, "
                "or division-by-zero in Fisher-z transform."
            ),
        )
    return None


def corr_symmetric_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Error if connectivity matrix is not symmetric."""
    if _non_correlation_matrix_declared(bundle):
        return None
    val = _corr_stat(bundle, "corr_symmetric")
    if val is False:
        return ReviewFinding(
            rule_id="REVIEW_CORR_NOT_SYMMETRIC",
            severity="error",
            message="Connectivity matrix is not symmetric (M ≠ M^T).",
            suggested_fix=(
                "A Pearson/partial correlation matrix must be symmetric. "
                "Check for directed connectivity measures or computation errors."
            ),
        )
    return None


def corr_diag_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Warn if diagonal of correlation matrix is not all ones.

    Partial correlation and tangent-space measures can legitimately have
    non-unit diagonals, so this is a warning, not an error.
    """
    if _non_correlation_matrix_declared(bundle):
        return None
    val = _corr_stat(bundle, "corr_diag_all_ones")
    if val is False:
        return ReviewFinding(
            rule_id="REVIEW_CORR_DIAG_NOT_ONES",
            severity="warn",
            message=(
                "Diagonal of correlation matrix is not all ones — "
                "may indicate partial correlation, tangent-space, or computation error."
            ),
            suggested_fix=(
                "If using Pearson correlation, diagonal must be 1.0. "
                "For partial correlation or tangent-space, non-unit diagonal is expected."
            ),
        )
    return None


def corr_range_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Error if off-diagonal values fall outside [-1, 1].

    This catches Fisher-z transformed matrices that were not bounded,
    or distance matrices mistakenly treated as correlations.
    """
    if _non_correlation_matrix_declared(bundle):
        return None
    val = _corr_stat(bundle, "corr_range_valid")
    if val is False:
        transform_state = _first_value(bundle, _TRANSFORM_STATE_KEYS)
        if transform_state is not None and "fisher" in _text(transform_state[1]):
            return None
        return ReviewFinding(
            rule_id="REVIEW_CORR_OUT_OF_RANGE",
            severity="error",
            message=(
                "Off-diagonal values outside [-1, 1] — "
                "matrix is not a valid correlation matrix."
            ),
            suggested_fix=(
                "Check whether Fisher-z transform was applied without inverse transform, "
                "or whether a distance/covariance matrix was used instead of correlation."
            ),
        )
    return None


def corr_positive_semidefinite_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Warn if correlation matrix has negative eigenvalues (not PSD)."""
    if _non_correlation_matrix_declared(bundle):
        return None
    val = _corr_stat(bundle, "corr_positive_semidefinite")
    if val is False:
        return ReviewFinding(
            rule_id="REVIEW_CORR_NOT_PSD",
            severity="warn",
            message=(
                "Correlation matrix has negative eigenvalues — "
                "not positive semidefinite."
            ),
            suggested_fix=(
                "Non-PSD correlation matrices can arise from pairwise deletion "
                "of missing data, or from combining correlation estimates. "
                "Consider nearest-PSD projection (e.g. Higham algorithm)."
            ),
        )
    return None


def corr_region_count_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Check that region count is in a plausible range."""
    n = _corr_stat(bundle, "corr_n_regions")
    if n is None:
        return None
    try:
        n = int(n)
    except (TypeError, ValueError):
        return None

    if n < 2:
        return ReviewFinding(
            rule_id="REVIEW_CORR_TOO_FEW_REGIONS",
            severity="error",
            message=f"Connectivity matrix has only {n} region(s) — need at least 2.",
            suggested_fix="Check atlas parcellation and ROI extraction.",
        )
    if n > 1000:
        return ReviewFinding(
            rule_id="REVIEW_CORR_MANY_REGIONS",
            severity="warn",
            message=(
                f"Connectivity matrix has {n} regions (>1000) — "
                "verify this is parcellation-level, not voxel-level."
            ),
            suggested_fix=(
                "Standard atlases have 100–400 regions. "
                ">1000 may indicate voxel-level connectivity was computed by mistake."
            ),
        )
    return None


def partial_correlation_required_diagnostics_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Block partial-correlation claims when required numerical diagnostics are absent."""

    partial_decl = _partial_correlation_declared(bundle)
    if partial_decl is None:
        return None

    missing: list[str] = []
    if _first_value(bundle, _PARTIAL_ESTIMATOR_KEYS) is None:
        missing.append("precision_or_covariance_estimator")
    if _first_int(bundle, _N_ROI_KEYS) is None:
        missing.append("n_rois")
    if _first_value(bundle, _STABILITY_DIAGNOSTIC_KEYS) is None:
        missing.append("rank_or_condition_or_min_eig")

    estimator = _first_value(bundle, _PARTIAL_ESTIMATOR_KEYS)
    source_level = _first_value(bundle, _PARTIAL_SOURCE_LEVEL_KEYS)
    needs_sample_size = (
        estimator is None
        or _is_unregularized_estimator(estimator[1])
        or (source_level is not None and _text(source_level[1]) == "raw_timeseries")
    )
    if needs_sample_size and _first_int(bundle, _N_TIMEPOINT_KEYS) is None:
        missing.append("effective_n_timepoints")

    if not missing:
        return None

    evidence = [
        f"{partial_decl[0]}={partial_decl[1]}",
        f"missing_required_diagnostics={missing}",
    ]
    if estimator is not None:
        evidence.append(f"{estimator[0]}={estimator[1]}")
    if source_level is not None:
        evidence.append(f"{source_level[0]}={source_level[1]}")

    return ReviewFinding(
        rule_id="REVIEW_MATRIX_PARTIAL_MISSING_DIAGNOSTIC",
        severity="error",
        action="block",
        message=(
            "Partial-correlation artifact is missing required estimator or "
            f"numerical stability diagnostics: {', '.join(missing)}."
        ),
        suggested_fix=(
            "Emit a connectivity/feature contract with matrix_kind, estimator, "
            "n_rois, effective_n_timepoints when applicable, and at least one "
            "rank / condition-number / min-eigenvalue diagnostic before allowing "
            "the partial-correlation result to support a claim."
        ),
        kg_evidence=evidence,
        reason_tags=["matrix", "partial_correlation", "coverage"],
    )


def partial_correlation_estimator_hazard_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Block partial-correlation estimates with singular or ill-conditioned support."""

    partial_decl = _partial_correlation_declared(bundle)
    if partial_decl is None:
        return None

    n_timepoints = _first_int(bundle, _N_TIMEPOINT_KEYS)
    n_rois = _first_int(bundle, _N_ROI_KEYS)
    rank = _first_int(bundle, _RANK_KEYS)
    condition = _first_number(bundle, _CONDITION_KEYS)
    min_eig = _first_number(bundle, _MIN_EIG_KEYS)
    estimator = _first_value(bundle, _PARTIAL_ESTIMATOR_KEYS)
    regularization = _first_value(bundle, _PARTIAL_REGULARIZATION_KEYS)
    source_level = _first_value(bundle, _PARTIAL_SOURCE_LEVEL_KEYS)

    hazards: list[str] = []
    severe = False
    estimator_is_regularized = estimator is not None and _is_regularized_estimator(
        estimator[1]
    )
    estimator_is_unregularized = estimator is not None and _is_unregularized_estimator(
        estimator[1]
    )
    regularization_is_enabled = regularization is not None and _regularization_enabled(
        regularization[1]
    )
    regularization_is_disabled = (
        regularization is not None and _regularization_disabled(regularization[1])
    )
    raw_timeseries_source = (
        source_level is not None and _text(source_level[1]) == "raw_timeseries"
    )
    underdetermined_empirical_precision = (
        n_timepoints is not None
        and n_rois is not None
        and n_timepoints[1] <= n_rois[1]
        and not estimator_is_regularized
        and not regularization_is_enabled
        and (
            estimator_is_unregularized
            or regularization_is_disabled
            or raw_timeseries_source
        )
    )

    if underdetermined_empirical_precision:
        hazards.append(
            f"{n_timepoints[0]}={n_timepoints[1]} <= {n_rois[0]}={n_rois[1]}"
        )
        severe = True
    if rank is not None and n_rois is not None and rank[1] < n_rois[1]:
        hazards.append(f"{rank[0]}={rank[1]} < {n_rois[0]}={n_rois[1]}")
        severe = True
    if condition is not None and condition[1] > _ILL_CONDITIONED_THRESHOLD:
        hazards.append(
            f"{condition[0]}={condition[1]:.3g} > {_ILL_CONDITIONED_THRESHOLD:.1g}"
        )
    if min_eig is not None and min_eig[1] <= _MIN_EIG_THRESHOLD:
        hazards.append(f"{min_eig[0]}={min_eig[1]:.3g} <= {_MIN_EIG_THRESHOLD:.1g}")
        severe = True

    if not hazards:
        return None

    evidence = [
        f"{partial_decl[0]}={partial_decl[1]}",
        f"hazards={hazards}",
    ]
    if estimator is not None:
        evidence.append(f"{estimator[0]}={estimator[1]}")
    if regularization is not None:
        evidence.append(f"{regularization[0]}={regularization[1]}")
    if source_level is not None:
        evidence.append(f"{source_level[0]}={source_level[1]}")

    return ReviewFinding(
        rule_id="REVIEW_MATRIX_PARTIAL_SINGULAR",
        severity="critical" if severe else "error",
        action="block",
        message=(
            "Partial-correlation estimator appears singular or ill-conditioned: "
            f"{'; '.join(hazards)}."
        ),
        suggested_fix=(
            "Do not interpret this partial-correlation matrix as valid. Use enough "
            "timepoints for the ROI dimension, a regularized covariance/precision "
            "estimator, or emit estimator rank and condition diagnostics showing the "
            "matrix is well-conditioned."
        ),
        kg_evidence=evidence,
        reason_tags=["matrix", "partial_correlation", "numerical_validity"],
    )
