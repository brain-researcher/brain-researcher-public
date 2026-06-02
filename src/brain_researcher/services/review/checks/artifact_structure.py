"""Deterministic structural correctness checks (no LLM) for Phase 3."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from brain_researcher.core.contracts.code_review import CodeReviewBundle, ReviewFinding

_CONFOUND_ALIAS_TOKENS: dict[str, tuple[str, ...]] = {
    "motion": ("motion", "trans_", "rot_", "framewise_displacement"),
    "age": ("age",),
    "site": ("site", "scanner"),
    "gsr": ("global_signal", "gsr"),
    "white_matter": ("white_matter",),
    "csf": ("csf",),
    "wm_csf": ("white_matter", "csf", "wm_csf"),
    "reaction_time": ("reaction_time", "rt"),
    "accuracy": ("accuracy",),
    "dvars": ("dvars",),
    "sex": ("sex", "gender"),
}
_MULTIPLE_COMPARISON_NORMALIZATION = {
    "fdr": "fdr",
    "fdr_bh": "fdr",
    "bh_fdr": "fdr",
    "benjamini_hochberg": "fdr",
    "fwe": "fwe",
    "bonferroni": "bonferroni",
    "fwe_bonferroni": "bonferroni",
    "tfce": "tfce",
    "cluster_fwe": "cluster_fwe",
}
_AUTOCORRELATION_NORMALIZATION = {
    "ar1": "ar1",
    "ar_1": "ar1",
    "ar_1_": "ar1",
    "fast": "fast",
    "ols": "ols",
}


def _stat(bundle: CodeReviewBundle, key: str) -> float | None:
    val = bundle.stats_metrics.get(key)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _floatish(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _review_context(bundle: CodeReviewBundle) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    candidates = [
        _mapping(getattr(bundle, "review_context", {})),
        _mapping(bundle.observed_artifacts.get("review_context")),
        _mapping(
            _mapping(bundle.observed_artifacts.get("review_contract")).get(
                "review_context"
            )
        ),
        _mapping(
            _mapping(bundle.observed_artifacts.get("analysis_bundle")).get(
                "review_context"
            )
        ),
        _mapping(
            _mapping(bundle.observed_artifacts.get("source_summary")).get(
                "review_context"
            )
        ),
        _mapping(bundle.stats_metrics.get("review_context")),
        _mapping(bundle.kg_context.get("review_context")),
    ]
    for candidate in candidates:
        if candidate:
            merged.update(candidate)
    return merged


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, Iterable):
        values = list(value)
    else:
        return []
    cleaned: list[str] = []
    for item in values:
        text = str(item).strip()
        if text:
            cleaned.append(text)
    return cleaned


def _int_list(value: object) -> list[int]:
    if not isinstance(value, Iterable) or isinstance(value, str):
        return []
    cleaned: list[int] = []
    for item in value:
        try:
            if item is None or isinstance(item, bool):
                continue
            cleaned.append(int(item))
        except (TypeError, ValueError):
            continue
    return cleaned


def _normalize_name(value: object) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _normalize_method(value: object) -> str:
    normalized = _normalize_name(value)
    normalized = normalized.replace("(", "_").replace(")", "_")
    normalized = "_".join(part for part in normalized.split("_") if part)
    return normalized


def _normalize_multiple_comparison(value: object) -> str:
    normalized = _normalize_method(value)
    return _MULTIPLE_COMPARISON_NORMALIZATION.get(normalized, normalized)


def _normalize_autocorrelation_model(value: object) -> str:
    normalized = _normalize_method(value)
    return _AUTOCORRELATION_NORMALIZATION.get(normalized, normalized)


def _boolish(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "on"}:
            return True
        if normalized in {"false", "no", "0", "off"}:
            return False
    return None


def _design_matrix_columns(bundle: CodeReviewBundle) -> list[str]:
    value = bundle.stats_metrics.get("design_matrix_columns")
    columns = _string_list(value)
    return [_normalize_name(column) for column in columns if _normalize_name(column)]


def design_matrix_rank_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Flag if design matrix is rank-deficient (collinear regressors)."""
    rank = _stat(bundle, "design_matrix_rank")
    ncols = _stat(bundle, "design_matrix_ncols")
    if rank is None or ncols is None or ncols <= 0:
        return None
    if rank < ncols:
        return ReviewFinding(
            rule_id="REVIEW_DESIGN_MATRIX_RANK_DEFICIENT",
            severity="error",
            message=(
                f"Design matrix is rank-deficient (rank={int(rank)}, ncols={int(ncols)}); "
                "GLM is unidentifiable due to collinear regressors."
            ),
            suggested_fix=(
                "Remove redundant or collinear regressors from the design matrix."
            ),
        )
    return None


def contrast_vector_dim_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Flag if contrast vector dimension does not match design matrix columns."""
    contrast_dims = _stat(bundle, "contrast_dims")
    ncols = _stat(bundle, "design_matrix_ncols")
    if contrast_dims is None or ncols is None:
        return None
    if int(contrast_dims) != int(ncols):
        return ReviewFinding(
            rule_id="REVIEW_CONTRAST_DIM_MISMATCH",
            severity="error",
            message=(
                f"Contrast vector dimension ({int(contrast_dims)}) does not match "
                f"design matrix columns ({int(ncols)})."
            ),
            suggested_fix="Ensure contrast vector length equals number of design matrix columns.",
        )
    return None


def cross_file_n_subjects_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Flag if metadata n_subjects differs from output CSV row count."""
    meta_n = _stat(bundle, "metadata_n_subjects") or _stat(bundle, "n_subjects")
    csv_n = _stat(bundle, "csv_n_rows")
    if meta_n is None or csv_n is None:
        return None
    if int(meta_n) != int(csv_n):
        return ReviewFinding(
            rule_id="REVIEW_CROSS_FILE_N_SUBJECTS",
            severity="error",
            message=(
                f"Cross-file inconsistency: metadata reports {int(meta_n)} subjects "
                f"but output CSV has {int(csv_n)} rows."
            ),
            suggested_fix="Check for subject exclusion or mismatched files.",
        )
    return None


def condition_number_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Flag if design matrix condition number indicates numerical instability.

    Full-rank but ill-conditioned matrices can produce wildly unstable betas.
    Thresholds: >10000 error (near-singular), >1000 warn (borderline).
    """
    cond = _stat(bundle, "design_matrix_condition_number")
    if cond is None:
        return None
    if cond > 10000:
        return ReviewFinding(
            rule_id="REVIEW_CONDITION_NUMBER_CRITICAL",
            severity="error",
            message=(
                f"Design matrix condition number is {cond:.0f} (>10000); "
                "matrix is near-singular and beta estimates are numerically unstable."
            ),
            suggested_fix=(
                "Check for highly correlated regressors, constant columns, "
                "or extreme scaling differences between columns."
            ),
        )
    if cond > 1000:
        return ReviewFinding(
            rule_id="REVIEW_CONDITION_NUMBER_HIGH",
            severity="warn",
            message=(
                f"Design matrix condition number is {cond:.0f} (>1000); "
                "potential numerical instability in beta estimation."
            ),
            suggested_fix=(
                "Consider centering/scaling regressors or removing "
                "near-collinear columns to improve conditioning."
            ),
        )
    return None


def contrast_estimability_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Flag if any contrast vector is not estimable given the design matrix.

    A contrast is estimable iff C lies in the column space of X.
    """
    val = bundle.stats_metrics.get("contrast_estimable")
    if val is None:
        return None
    if val is False:
        return ReviewFinding(
            rule_id="REVIEW_CONTRAST_NOT_ESTIMABLE",
            severity="error",
            message=(
                "One or more contrast vectors are not estimable given the design matrix "
                "(C ∉ column space of X)."
            ),
            suggested_fix=(
                "Verify contrast vector is in the column space of the design matrix. "
                "This often means a condition is missing from the design or the "
                "contrast references columns that were dropped due to rank deficiency."
            ),
        )
    return None


def effect_tstat_shape_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Flag if effect map and t-stat map shapes disagree."""
    effect_shape = bundle.stats_metrics.get("effect_map_shape")
    tstat_shape = bundle.stats_metrics.get("tstat_map_shape")
    if effect_shape is None or tstat_shape is None:
        return None
    if effect_shape != tstat_shape:
        return ReviewFinding(
            rule_id="REVIEW_EFFECT_TSTAT_SHAPE_MISMATCH",
            severity="error",
            message=(
                f"Effect map shape {effect_shape} does not match "
                f"t-stat map shape {tstat_shape}."
            ),
            suggested_fix="Verify both maps are in the same space and generated from the same GLM.",
        )
    return None


def design_matrix_confound_column_consistency_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Block when declared confound regressors are absent from the design-matrix header."""

    context = _review_context(bundle)
    preprocessing = _mapping(context.get("preprocessing"))
    if not preprocessing:
        return None

    design_columns = _design_matrix_columns(bundle)
    if not design_columns:
        return None

    observed_columns = set(design_columns)

    declared_exact = {
        _normalize_name(value)
        for value in _string_list(preprocessing.get("confound_columns"))
        if _normalize_name(value)
    }
    missing_exact = sorted(
        value for value in declared_exact if value not in observed_columns
    )

    missing_aliases: list[str] = []
    for label in _string_list(preprocessing.get("confounds")):
        normalized = _normalize_name(label)
        tokens = _CONFOUND_ALIAS_TOKENS.get(normalized)
        if not tokens:
            continue
        if not any(
            any(token in column for token in tokens) for column in observed_columns
        ):
            missing_aliases.append(normalized)

    if not missing_exact and not missing_aliases:
        return None

    evidence = [f"design_matrix_columns={design_columns[:30]}"]
    if missing_exact:
        evidence.append(f"missing_declared_confound_columns={missing_exact}")
    if missing_aliases:
        evidence.append(f"missing_declared_confound_aliases={sorted(missing_aliases)}")

    return ReviewFinding(
        rule_id="REVIEW_DESIGN_MATRIX_CONFOUND_COLUMNS_MISMATCH",
        severity="error",
        action="block",
        message=(
            "Declared confound regressors are missing from the observed design-matrix "
            "columns."
        ),
        suggested_fix=(
            "Regenerate the design matrix so the declared confounds are included, or "
            "update review_context preprocessing metadata to match the actual design."
        ),
        kg_evidence=evidence,
        reason_tags=["confound", "null_mismatch"],
    )


def multiple_comparison_metadata_consistency_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Block when declared thresholding metadata contradicts observed threshold summaries."""

    context = _review_context(bundle)
    statistical_inference = _mapping(context.get("statistical_inference"))
    if not statistical_inference:
        return None

    mismatches: list[str] = []
    evidence: list[str] = []

    declared_correction = statistical_inference.get("multiple_comparison_correction")
    observed_correction = bundle.stats_metrics.get(
        "observed_multiple_comparison_correction"
    )
    if declared_correction is not None and observed_correction is not None:
        declared_norm = _normalize_multiple_comparison(declared_correction)
        observed_norm = _normalize_multiple_comparison(observed_correction)
        if declared_norm != observed_norm:
            mismatches.append(
                "multiple_comparison_correction="
                f"{declared_correction!r} vs observed {observed_correction!r}"
            )

    declared_alpha = _floatish(statistical_inference.get("correction_alpha"))
    observed_alpha = _stat(bundle, "observed_multiple_comparison_alpha")
    if declared_alpha is not None and observed_alpha is not None:
        if abs(declared_alpha - observed_alpha) > 1e-9:
            mismatches.append(
                f"correction_alpha={declared_alpha:g} vs observed {observed_alpha:g}"
            )

    declared_height_control = statistical_inference.get("height_control")
    observed_height_control = bundle.stats_metrics.get("observed_height_control")
    if declared_height_control is not None and observed_height_control is not None:
        if _normalize_method(declared_height_control) != _normalize_method(
            observed_height_control
        ):
            mismatches.append(
                f"height_control={declared_height_control!r} vs observed {observed_height_control!r}"
            )

    declared_voxel_threshold = _floatish(
        statistical_inference.get("voxelwise_threshold")
    )
    observed_voxel_threshold = _stat(bundle, "observed_voxelwise_threshold")
    if declared_voxel_threshold is not None and observed_voxel_threshold is not None:
        if abs(declared_voxel_threshold - observed_voxel_threshold) > 1e-9:
            mismatches.append(
                "voxelwise_threshold="
                f"{declared_voxel_threshold:g} vs observed {observed_voxel_threshold:g}"
            )

    declared_cluster_threshold = _floatish(
        statistical_inference.get("cluster_forming_threshold")
    )
    observed_cluster_threshold = _stat(bundle, "observed_cluster_forming_threshold")
    if (
        declared_cluster_threshold is not None
        and observed_cluster_threshold is not None
    ):
        if abs(declared_cluster_threshold - observed_cluster_threshold) > 1e-9:
            mismatches.append(
                "cluster_forming_threshold="
                f"{declared_cluster_threshold:g} vs observed {observed_cluster_threshold:g}"
            )

    if not mismatches:
        return None

    if declared_correction is not None:
        evidence.append(f"declared_correction={declared_correction!r}")
    if observed_correction is not None:
        evidence.append(f"observed_correction={observed_correction!r}")
    if declared_alpha is not None or observed_alpha is not None:
        evidence.append(
            f"declared_alpha={declared_alpha!r}; observed_alpha={observed_alpha!r}"
        )
    if declared_height_control is not None or observed_height_control is not None:
        evidence.append(
            "declared_height_control="
            f"{declared_height_control!r}; observed_height_control={observed_height_control!r}"
        )

    return ReviewFinding(
        rule_id="REVIEW_MULTIPLE_COMPARISON_METADATA_MISMATCH",
        severity="error",
        action="block",
        message=(
            "Declared multiple-comparison metadata contradicts the observed threshold "
            "summary artifacts."
        ),
        suggested_fix=(
            "Regenerate the threshold summary artifacts or update review_context "
            "statistical_inference metadata so the declared correction method and "
            "threshold parameters match the observed outputs."
        ),
        kg_evidence=evidence + mismatches,
        reason_tags=["null_mismatch"],
    )


def correction_summary_numeric_consistency_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Block when observed correction-summary arithmetic is internally impossible."""

    n_tests = _stat(bundle, "observed_multiple_comparison_n_tests")
    rejected = _stat(bundle, "observed_multiple_comparison_rejected_count")
    fraction = _stat(bundle, "observed_multiple_comparison_fraction_significant")
    alpha = _stat(bundle, "observed_multiple_comparison_alpha")
    n_found = _stat(bundle, "observed_n_clusters_found")
    n_surviving = _stat(bundle, "observed_n_clusters_surviving")

    mismatches: list[str] = []
    if alpha is not None and not (0.0 <= alpha <= 1.0):
        mismatches.append(
            f"observed_multiple_comparison_alpha={alpha:g} is outside [0, 1]"
        )
    if fraction is not None and not (0.0 <= fraction <= 1.0):
        mismatches.append(
            "observed_multiple_comparison_fraction_significant="
            f"{fraction:g} is outside [0, 1]"
        )
    if n_tests is not None and n_tests < 0:
        mismatches.append(
            f"observed_multiple_comparison_n_tests={int(n_tests)} is negative"
        )
    if rejected is not None and rejected < 0:
        mismatches.append(
            f"observed_multiple_comparison_rejected_count={int(rejected)} is negative"
        )
    if n_found is not None and n_found < 0:
        mismatches.append(f"observed_n_clusters_found={int(n_found)} is negative")
    if n_surviving is not None and n_surviving < 0:
        mismatches.append(
            f"observed_n_clusters_surviving={int(n_surviving)} is negative"
        )
    if n_tests is not None and rejected is not None and rejected > n_tests:
        mismatches.append(
            "observed_multiple_comparison_rejected_count="
            f"{int(rejected)} exceeds observed_multiple_comparison_n_tests={int(n_tests)}"
        )
    if n_tests is not None and rejected is not None and n_tests == 0 and rejected > 0:
        mismatches.append(
            "observed_multiple_comparison_n_tests=0 with rejected_count>0 is impossible"
        )
    if (
        n_tests is not None
        and rejected is not None
        and fraction is not None
        and n_tests > 0
    ):
        expected_fraction = rejected / n_tests
        if abs(fraction - expected_fraction) > 1e-9:
            mismatches.append(
                "observed_multiple_comparison_fraction_significant="
                f"{fraction:g} vs rejected_count/n_tests={expected_fraction:g}"
            )
    if n_found is not None and n_surviving is not None and n_surviving > n_found:
        mismatches.append(
            f"observed_n_clusters_surviving={int(n_surviving)} exceeds observed_n_clusters_found={int(n_found)}"
        )

    if not mismatches:
        return None

    return ReviewFinding(
        rule_id="REVIEW_CORRECTION_SUMMARY_NUMERIC_MISMATCH",
        severity="error",
        action="block",
        message=("Observed correction-summary metrics are internally inconsistent."),
        suggested_fix=(
            "Regenerate the correction or threshold summary so alpha, rejection counts, "
            "fractions, and cluster counts are numerically self-consistent."
        ),
        kg_evidence=mismatches,
        reason_tags=["null_mismatch"],
    )


def contrast_table_semantics_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Block when a declared contrast table is missing names or contradicts the design."""

    context = _review_context(bundle)
    statistical_inference = _mapping(context.get("statistical_inference"))
    declared_path = statistical_inference.get("contrast_table_path")
    observed_rows = _stat(bundle, "observed_contrast_table_rows")
    if declared_path in (None, "") and observed_rows is None:
        return None

    if declared_path not in (None, "") and observed_rows is None:
        return ReviewFinding(
            rule_id="REVIEW_CONTRAST_TABLE_SEMANTICS_INVALID",
            severity="error",
            action="block",
            message=(
                "Declared contrast-table artifact is missing or could not be parsed into "
                "a structured contrast table."
            ),
            suggested_fix=(
                "Write a parseable contrast table at the declared path or update "
                "review_context statistical_inference contrast_table_path."
            ),
            kg_evidence=[f"contrast_table_path={declared_path!r}"],
            reason_tags=["null_mismatch"],
        )

    if observed_rows is None or observed_rows <= 0:
        return None

    has_contrast_name = _boolish(
        bundle.stats_metrics.get("observed_contrast_table_has_contrast_name")
    )
    missing_names = _stat(bundle, "observed_contrast_table_rows_missing_contrast_name")
    if has_contrast_name is not True or (
        missing_names is not None and missing_names > 0
    ):
        return ReviewFinding(
            rule_id="REVIEW_CONTRAST_TABLE_SEMANTICS_INVALID",
            severity="error",
            action="block",
            message=(
                "Contrast-table artifact lacks explicit contrast names for one or more rows."
            ),
            suggested_fix=(
                "Regenerate the contrast table with a contrast_name or equivalent label "
                "column for every contrast row."
            ),
            kg_evidence=[
                f"contrast_table_path={declared_path!r}",
                f"observed_contrast_table_rows={int(observed_rows)}",
                f"observed_contrast_table_rows_missing_contrast_name={int(missing_names or 0)}",
            ],
            reason_tags=["null_mismatch"],
        )

    expected_contrast = bundle.kg_context.get("contrast")
    observed_names = _string_list(
        bundle.stats_metrics.get("observed_contrast_table_names")
    )
    if expected_contrast and observed_names:
        expected_norm = _normalize_name(expected_contrast)
        observed_norm = {_normalize_name(name) for name in observed_names}
        if expected_norm not in observed_norm:
            return ReviewFinding(
                rule_id="REVIEW_CONTRAST_TABLE_SEMANTICS_INVALID",
                severity="error",
                action="block",
                message=(
                    "The requested contrast is absent from the structured contrast table."
                ),
                suggested_fix=(
                    "Regenerate the contrast table so it includes the reviewed contrast, "
                    "or align the declared contrast metadata with the actual result artifact."
                ),
                kg_evidence=[
                    f"expected_contrast={expected_contrast!r}",
                    f"observed_contrast_table_names={observed_names[:20]!r}",
                ],
                reason_tags=["null_mismatch"],
            )

    design_ncols = _stat(bundle, "design_matrix_ncols")
    vector_lengths = _int_list(
        bundle.stats_metrics.get("observed_contrast_table_vector_lengths")
    )
    if design_ncols is not None and vector_lengths:
        mismatched_lengths = sorted(
            {length for length in vector_lengths if int(length) != int(design_ncols)}
        )
        if mismatched_lengths:
            return ReviewFinding(
                rule_id="REVIEW_CONTRAST_TABLE_SEMANTICS_INVALID",
                severity="error",
                action="block",
                message=(
                    "Contrast-table vector dimensionality contradicts the observed design "
                    "matrix column count."
                ),
                suggested_fix=(
                    "Regenerate the contrast table so every contrast vector has one weight "
                    "per design-matrix column."
                ),
                kg_evidence=[
                    f"design_matrix_ncols={int(design_ncols)}",
                    f"observed_contrast_table_vector_lengths={vector_lengths}",
                ],
                reason_tags=["null_mismatch"],
            )
    return None


def cluster_table_semantics_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Block when a declared cluster table is missing or lacks cluster-level semantics."""

    context = _review_context(bundle)
    statistical_inference = _mapping(context.get("statistical_inference"))
    declared_path = statistical_inference.get("cluster_table_path")
    observed_rows = _stat(bundle, "observed_cluster_table_rows")
    if declared_path in (None, "") and observed_rows is None:
        return None

    if declared_path not in (None, "") and observed_rows is None:
        return ReviewFinding(
            rule_id="REVIEW_CLUSTER_TABLE_SEMANTICS_INVALID",
            severity="error",
            action="block",
            message=(
                "Declared cluster-table artifact is missing or could not be parsed into "
                "a structured cluster table."
            ),
            suggested_fix=(
                "Write a parseable cluster table at the declared path or update "
                "review_context statistical_inference cluster_table_path."
            ),
            kg_evidence=[f"cluster_table_path={declared_path!r}"],
            reason_tags=["null_mismatch"],
        )

    has_size = _boolish(
        bundle.stats_metrics.get("observed_cluster_table_has_cluster_size")
    )
    has_significance = _boolish(
        bundle.stats_metrics.get("observed_cluster_table_has_significance")
    )
    has_stat = _boolish(bundle.stats_metrics.get("observed_cluster_table_has_stat"))
    if observed_rows is not None and observed_rows > 0:
        if not any(flag is True for flag in (has_size, has_significance, has_stat)):
            return ReviewFinding(
                rule_id="REVIEW_CLUSTER_TABLE_SEMANTICS_INVALID",
                severity="error",
                action="block",
                message=(
                    "Cluster-table artifact lacks structured cluster-level semantics "
                    "(size, significance, or cluster statistic columns)."
                ),
                suggested_fix=(
                    "Regenerate the cluster table with explicit cluster extent and/or "
                    "cluster significance/statistic columns."
                ),
                kg_evidence=[
                    f"cluster_table_path={declared_path!r}",
                    f"observed_cluster_table_rows={int(observed_rows)}",
                    f"has_cluster_size={has_size!r}",
                    f"has_significance={has_significance!r}",
                    f"has_stat={has_stat!r}",
                ],
                reason_tags=["null_mismatch"],
            )
    return None


def cluster_table_count_consistency_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Block when structured cluster counts contradict the cluster-table row count."""

    rows = _stat(bundle, "observed_cluster_table_rows")
    n_found = _stat(bundle, "observed_n_clusters_found")
    n_surviving = _stat(bundle, "observed_n_clusters_surviving")

    mismatches: list[str] = []
    if n_found is not None and n_surviving is not None and n_surviving > n_found:
        mismatches.append(
            f"n_clusters_surviving={int(n_surviving)} exceeds n_clusters_found={int(n_found)}"
        )
    if rows is not None and n_surviving is not None and int(rows) != int(n_surviving):
        mismatches.append(
            f"cluster_table_rows={int(rows)} vs n_clusters_surviving={int(n_surviving)}"
        )
    if rows is not None and n_found is not None and rows > n_found:
        mismatches.append(
            f"cluster_table_rows={int(rows)} exceeds n_clusters_found={int(n_found)}"
        )

    if not mismatches:
        return None

    return ReviewFinding(
        rule_id="REVIEW_CLUSTER_TABLE_COUNT_MISMATCH",
        severity="error",
        action="block",
        message=(
            "Structured cluster-count metadata contradicts the observed cluster-table "
            "row count."
        ),
        suggested_fix=(
            "Regenerate the threshold summary or cluster table so surviving/found "
            "cluster counts agree with the structured cluster-table artifact."
        ),
        kg_evidence=mismatches,
        reason_tags=["null_mismatch"],
    )


def cluster_peak_cardinality_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Block when some cluster rows have no corresponding peak-table membership."""

    cluster_ids = set(
        _string_list(bundle.stats_metrics.get("observed_cluster_table_cluster_ids"))
    )
    peak_cluster_ids = set(
        _string_list(bundle.stats_metrics.get("observed_peak_table_cluster_ids"))
    )
    if not cluster_ids or not peak_cluster_ids:
        return None

    missing_peak_clusters = sorted(cluster_ids - peak_cluster_ids)
    if not missing_peak_clusters:
        return None

    return ReviewFinding(
        rule_id="REVIEW_CLUSTER_PEAK_CARDINALITY_MISMATCH",
        severity="error",
        action="block",
        message=(
            "One or more cluster-table rows have no corresponding peak-table membership."
        ),
        suggested_fix=(
            "Regenerate the cluster and peak tables so every surviving cluster has at least "
            "one associated peak row."
        ),
        kg_evidence=[
            f"missing_peak_clusters={missing_peak_clusters[:20]}",
            f"cluster_ids={sorted(cluster_ids)[:20]}",
            f"peak_cluster_ids={sorted(peak_cluster_ids)[:20]}",
        ],
        reason_tags=["null_mismatch"],
    )


def peak_cluster_membership_consistency_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Block when peak-table cluster membership contradicts the cluster table."""

    peak_has_cluster_id = _boolish(
        bundle.stats_metrics.get("observed_peak_table_has_cluster_id")
    )
    if peak_has_cluster_id is not True:
        return None

    cluster_rows = _stat(bundle, "observed_cluster_table_rows")
    if cluster_rows is None or cluster_rows <= 0:
        return None

    cluster_has_cluster_id = _boolish(
        bundle.stats_metrics.get("observed_cluster_table_has_cluster_id")
    )
    if cluster_has_cluster_id is not True:
        return ReviewFinding(
            rule_id="REVIEW_PEAK_CLUSTER_MEMBERSHIP_INVALID",
            severity="error",
            action="block",
            message=(
                "Peak table reports cluster membership, but the corresponding cluster "
                "table does not expose explicit cluster identifiers."
            ),
            suggested_fix=(
                "Regenerate the cluster table with a cluster_id column or remove "
                "unsupported cluster references from the peak table."
            ),
            kg_evidence=[
                f"observed_peak_table_has_cluster_id={peak_has_cluster_id!r}",
                f"observed_cluster_table_has_cluster_id={cluster_has_cluster_id!r}",
            ],
            reason_tags=["null_mismatch"],
        )

    if (
        _boolish(
            bundle.stats_metrics.get("observed_cluster_table_duplicate_cluster_ids")
        )
        is True
    ):
        return ReviewFinding(
            rule_id="REVIEW_PEAK_CLUSTER_MEMBERSHIP_INVALID",
            severity="error",
            action="block",
            message="Cluster table contains duplicate cluster identifiers.",
            suggested_fix=(
                "Ensure the cluster table contains exactly one row per cluster_id."
            ),
            kg_evidence=[
                "observed_cluster_table_duplicate_cluster_ids=True",
                f"cluster_ids={_string_list(bundle.stats_metrics.get('observed_cluster_table_cluster_ids'))[:20]}",
            ],
            reason_tags=["null_mismatch"],
        )

    missing_peak_cluster_ids = _stat(
        bundle, "observed_peak_table_rows_missing_cluster_id"
    )
    peak_rows = _stat(bundle, "observed_peak_table_rows")
    if (
        missing_peak_cluster_ids is not None
        and peak_rows is not None
        and missing_peak_cluster_ids > 0
        and peak_rows > 0
    ):
        return ReviewFinding(
            rule_id="REVIEW_PEAK_CLUSTER_MEMBERSHIP_INVALID",
            severity="error",
            action="block",
            message=(
                "Peak table has a cluster_id column, but some peak rows are missing "
                "cluster membership assignments."
            ),
            suggested_fix=(
                "Populate cluster_id for every peak row or remove the incomplete "
                "cluster-membership column."
            ),
            kg_evidence=[
                f"observed_peak_table_rows={int(peak_rows)}",
                f"observed_peak_table_rows_missing_cluster_id={int(missing_peak_cluster_ids)}",
            ],
            reason_tags=["null_mismatch"],
        )

    cluster_ids = set(
        _string_list(bundle.stats_metrics.get("observed_cluster_table_cluster_ids"))
    )
    peak_cluster_ids = set(
        _string_list(bundle.stats_metrics.get("observed_peak_table_cluster_ids"))
    )
    if peak_cluster_ids and cluster_ids:
        missing = sorted(peak_cluster_ids - cluster_ids)
        if missing:
            return ReviewFinding(
                rule_id="REVIEW_PEAK_CLUSTER_MEMBERSHIP_INVALID",
                severity="error",
                action="block",
                message=(
                    "Peak table references cluster IDs that are absent from the "
                    "cluster table."
                ),
                suggested_fix=(
                    "Regenerate the peak/cluster tables so peak cluster_id values map "
                    "to declared cluster rows."
                ),
                kg_evidence=[
                    f"missing_peak_cluster_ids={missing[:20]}",
                    f"cluster_ids={sorted(cluster_ids)[:20]}",
                ],
                reason_tags=["null_mismatch"],
            )
    return None


def peak_table_semantics_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Block when a declared peak table is missing coordinates or peak statistics."""

    context = _review_context(bundle)
    statistical_inference = _mapping(context.get("statistical_inference"))
    declared_path = statistical_inference.get("peak_table_path")
    observed_rows = _stat(bundle, "observed_peak_table_rows")
    if declared_path in (None, "") and observed_rows is None:
        return None

    if declared_path not in (None, "") and observed_rows is None:
        return ReviewFinding(
            rule_id="REVIEW_PEAK_TABLE_SEMANTICS_INVALID",
            severity="error",
            action="block",
            message=(
                "Declared peak-table artifact is missing or could not be parsed into "
                "a structured peak table."
            ),
            suggested_fix=(
                "Write a parseable peak table at the declared path or update "
                "review_context statistical_inference peak_table_path."
            ),
            kg_evidence=[f"peak_table_path={declared_path!r}"],
            reason_tags=["null_mismatch"],
        )

    has_coordinates = _boolish(
        bundle.stats_metrics.get("observed_peak_table_has_coordinates")
    )
    has_stat = _boolish(bundle.stats_metrics.get("observed_peak_table_has_stat"))
    if observed_rows is not None and observed_rows > 0:
        if has_coordinates is not True or has_stat is not True:
            return ReviewFinding(
                rule_id="REVIEW_PEAK_TABLE_SEMANTICS_INVALID",
                severity="error",
                action="block",
                message=(
                    "Peak-table artifact lacks structured peak coordinates or peak "
                    "statistic columns."
                ),
                suggested_fix=(
                    "Regenerate the peak table with explicit coordinates (x/y/z or "
                    "equivalent) and a peak statistic column."
                ),
                kg_evidence=[
                    f"peak_table_path={declared_path!r}",
                    f"observed_peak_table_rows={int(observed_rows)}",
                    f"has_coordinates={has_coordinates!r}",
                    f"has_stat={has_stat!r}",
                ],
                reason_tags=["null_mismatch"],
            )
    return None


def design_model_metadata_consistency_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Block when declared HRF/autocorrelation metadata contradicts observed model summaries."""

    context = _review_context(bundle)
    design_model = _mapping(context.get("design_model"))
    if not design_model:
        return None

    mismatches: list[str] = []
    evidence: list[str] = []

    declared_hrf = design_model.get("hrf_model")
    observed_hrf = bundle.stats_metrics.get("observed_hrf_model")
    if declared_hrf is not None and observed_hrf is not None:
        if _normalize_method(declared_hrf) != _normalize_method(observed_hrf):
            mismatches.append(
                f"hrf_model={declared_hrf!r} vs observed {observed_hrf!r}"
            )

    declared_basis = design_model.get("basis_set")
    observed_basis = bundle.stats_metrics.get("observed_basis_set")
    if declared_basis is not None and observed_basis is not None:
        if _normalize_method(declared_basis) != _normalize_method(observed_basis):
            mismatches.append(
                f"basis_set={declared_basis!r} vs observed {observed_basis!r}"
            )

    declared_autocorrelation = design_model.get("autocorrelation_model")
    observed_autocorrelation = bundle.stats_metrics.get(
        "observed_autocorrelation_model"
    )
    if declared_autocorrelation is not None and observed_autocorrelation is not None:
        if _normalize_autocorrelation_model(
            declared_autocorrelation
        ) != _normalize_autocorrelation_model(observed_autocorrelation):
            mismatches.append(
                "autocorrelation_model="
                f"{declared_autocorrelation!r} vs observed {observed_autocorrelation!r}"
            )

    declared_serial_correlation = design_model.get("serial_correlation_correction")
    observed_serial_correlation = bundle.stats_metrics.get(
        "observed_serial_correlation_correction"
    )
    if (
        declared_serial_correlation is not None
        and observed_serial_correlation is not None
    ):
        if _normalize_method(declared_serial_correlation) != _normalize_method(
            observed_serial_correlation
        ):
            mismatches.append(
                "serial_correlation_correction="
                f"{declared_serial_correlation!r} vs observed {observed_serial_correlation!r}"
            )

    declared_prewhitening_method = design_model.get("prewhitening_method")
    observed_prewhitening_method = bundle.stats_metrics.get(
        "observed_prewhitening_method"
    )
    if (
        declared_prewhitening_method is not None
        and observed_prewhitening_method is not None
    ):
        if _normalize_method(declared_prewhitening_method) != _normalize_method(
            observed_prewhitening_method
        ):
            mismatches.append(
                "prewhitening_method="
                f"{declared_prewhitening_method!r} vs observed {observed_prewhitening_method!r}"
            )

    declared_prewhitening_enabled = _boolish(design_model.get("prewhitening_enabled"))
    observed_prewhitening_enabled = _boolish(
        bundle.stats_metrics.get("observed_prewhitening_enabled")
    )
    if (
        declared_prewhitening_enabled is not None
        and observed_prewhitening_enabled is not None
        and declared_prewhitening_enabled != observed_prewhitening_enabled
    ):
        mismatches.append(
            "prewhitening_enabled="
            f"{declared_prewhitening_enabled!r} vs observed {observed_prewhitening_enabled!r}"
        )

    declared_temporal_derivative = _boolish(design_model.get("temporal_derivative"))
    observed_temporal_derivative = _boolish(
        bundle.stats_metrics.get("observed_temporal_derivative")
    )
    temporal_derivative_count = _stat(bundle, "design_matrix_temporal_derivative_count")
    if declared_temporal_derivative is not None:
        if observed_temporal_derivative is not None:
            if declared_temporal_derivative != observed_temporal_derivative:
                mismatches.append(
                    "temporal_derivative="
                    f"{declared_temporal_derivative!r} vs observed {observed_temporal_derivative!r}"
                )
        elif temporal_derivative_count is not None:
            has_temporal_derivative = temporal_derivative_count > 0
            if declared_temporal_derivative != has_temporal_derivative:
                mismatches.append(
                    "temporal_derivative="
                    f"{declared_temporal_derivative!r} vs design_matrix count {int(temporal_derivative_count)}"
                )

    declared_dispersion_derivative = _boolish(design_model.get("dispersion_derivative"))
    observed_dispersion_derivative = _boolish(
        bundle.stats_metrics.get("observed_dispersion_derivative")
    )
    dispersion_derivative_count = _stat(
        bundle, "design_matrix_dispersion_derivative_count"
    )
    if declared_dispersion_derivative is not None:
        if observed_dispersion_derivative is not None:
            if declared_dispersion_derivative != observed_dispersion_derivative:
                mismatches.append(
                    "dispersion_derivative="
                    f"{declared_dispersion_derivative!r} vs observed {observed_dispersion_derivative!r}"
                )
        elif dispersion_derivative_count is not None:
            has_dispersion_derivative = dispersion_derivative_count > 0
            if declared_dispersion_derivative != has_dispersion_derivative:
                mismatches.append(
                    "dispersion_derivative="
                    f"{declared_dispersion_derivative!r} vs design_matrix count {int(dispersion_derivative_count)}"
                )

    if not mismatches:
        return None

    if declared_hrf is not None or observed_hrf is not None:
        evidence.append(f"declared_hrf={declared_hrf!r}; observed_hrf={observed_hrf!r}")
    if declared_autocorrelation is not None or observed_autocorrelation is not None:
        evidence.append(
            "declared_autocorrelation="
            f"{declared_autocorrelation!r}; observed_autocorrelation={observed_autocorrelation!r}"
        )
    if (
        declared_serial_correlation is not None
        or observed_serial_correlation is not None
    ):
        evidence.append(
            "declared_serial_correlation="
            f"{declared_serial_correlation!r}; observed_serial_correlation={observed_serial_correlation!r}"
        )
    if (
        declared_prewhitening_method is not None
        or observed_prewhitening_method is not None
    ):
        evidence.append(
            "declared_prewhitening_method="
            f"{declared_prewhitening_method!r}; observed_prewhitening_method={observed_prewhitening_method!r}"
        )
    if (
        declared_prewhitening_enabled is not None
        or observed_prewhitening_enabled is not None
    ):
        evidence.append(
            "declared_prewhitening_enabled="
            f"{declared_prewhitening_enabled!r}; observed_prewhitening_enabled={observed_prewhitening_enabled!r}"
        )
    if temporal_derivative_count is not None:
        evidence.append(
            f"design_matrix_temporal_derivative_count={int(temporal_derivative_count)}"
        )
    if dispersion_derivative_count is not None:
        evidence.append(
            f"design_matrix_dispersion_derivative_count={int(dispersion_derivative_count)}"
        )

    return ReviewFinding(
        rule_id="REVIEW_DESIGN_MODEL_METADATA_MISMATCH",
        severity="error",
        action="block",
        message=(
            "Declared HRF or autocorrelation design-model metadata contradicts the "
            "observed GLM/design-matrix summaries."
        ),
        suggested_fix=(
            "Regenerate the GLM summary/design artifacts or update review_context "
            "design_model metadata so the declared HRF, derivative, and "
            "autocorrelation settings match the observed model."
        ),
        kg_evidence=evidence + mismatches,
        reason_tags=["null_mismatch"],
    )
