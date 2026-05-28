"""Artifact-time invariant checks for the review layer."""

from __future__ import annotations

from brain_researcher.core.contracts.code_review import CodeReviewBundle, ReviewFinding


def _stat(bundle: CodeReviewBundle, key: str) -> float | None:
    val = bundle.stats_metrics.get(key)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _score(bundle: CodeReviewBundle, key: str) -> float | None:
    val = bundle.scorecard_snapshot.get(key)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def row_count_preserved(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Flag if output row count dropped by more than 20% vs input."""
    input_rows = _stat(bundle, "input_row_count")
    output_rows = _stat(bundle, "output_row_count")
    if input_rows is None or output_rows is None or input_rows <= 0:
        return None
    drop_fraction = (input_rows - output_rows) / input_rows
    if drop_fraction > 0.20:
        return ReviewFinding(
            rule_id="REVIEW_ROW_COUNT_DROP",
            severity="error",
            message=(
                f"Output row count dropped by {drop_fraction:.0%} "
                f"({int(input_rows)} → {int(output_rows)}); "
                "unexpected subject/volume exclusion."
            ),
            suggested_fix="Inspect pipeline for unexpected exclusion or filtering steps.",
        )
    return None


def mean_fd_high(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Flag if mean framewise displacement exceeds 0.5mm."""
    fd = _stat(bundle, "mean_fd")
    if fd is None:
        return None
    if fd > 0.5:
        return ReviewFinding(
            rule_id="REVIEW_MEAN_FD_HIGH",
            severity="warn",
            message=f"Mean framewise displacement {fd:.3f}mm > 0.5mm.",
            suggested_fix="Consider stricter motion exclusion or scrubbing.",
        )
    return None


def scrubbing_rate_high(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Flag if more than 20% of volumes were scrubbed."""
    rate = _stat(bundle, "scrubbing_fraction")
    if rate is None:
        return None
    if rate > 0.20:
        return ReviewFinding(
            rule_id="REVIEW_SCRUBBING_RATE_HIGH",
            severity="error",
            message=f"Scrubbing rate {rate:.0%} > 20%; analysis validity is compromised.",
            suggested_fix="Review motion parameters; consider subject exclusion.",
        )
    return None


def model_fit_adequate(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Flag if R² is below 0.10."""
    r2 = _stat(bundle, "r_squared")
    if r2 is None:
        return None
    if r2 < 0.10:
        return ReviewFinding(
            rule_id="REVIEW_R2_TOO_LOW",
            severity="warn",
            message=f"GLM R² = {r2:.3f} < 0.10; model may be poorly specified.",
            suggested_fix="Review confound selection, HRF choice, and design matrix.",
        )
    return None


def effect_size_sane(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Flag if max Cohen's d exceeds 3.0."""
    d = _stat(bundle, "cohens_d_max")
    if d is None:
        return None
    if abs(d) > 3.0:
        return ReviewFinding(
            rule_id="REVIEW_EFFECT_SIZE_OOB",
            severity="warn",
            message=f"Max Cohen's d = {d:.2f}; suspiciously large for fMRI.",
            suggested_fix="Inspect for outlier subjects or signal scaling issues.",
        )
    return None


def qc_flag_rate_sane(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Flag if QC flag rate is exactly 0 (QC may not have run)."""
    rate = _stat(bundle, "flag_rate")
    if rate is None:
        return None
    if rate == 0.0:
        return ReviewFinding(
            rule_id="REVIEW_QC_FLAG_RATE_ZERO",
            severity="warn",
            message="QC flag rate is exactly 0% — QC may not have run or thresholds are too lenient.",
            suggested_fix="Verify QC pipeline executed and inspect flag thresholds.",
        )
    return None


def step_success_rate_adequate(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Flag if not all pipeline steps succeeded."""
    rate = _score(bundle, "step_success_rate")
    if rate is None:
        return None
    if rate < 1.0:
        return ReviewFinding(
            rule_id="REVIEW_STEP_SUCCESS_RATE_LOW",
            severity="error",
            message=f"Step success rate {rate:.0%} < 100%; pipeline did not fully complete.",
            suggested_fix="Inspect failed steps in the run log.",
        )
    return None


def artifact_completeness_adequate(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Flag if artifact completeness ratio is below 60%."""
    ratio = _score(bundle, "artifact_completeness_ratio")
    if ratio is None:
        return None
    if ratio < 0.60:
        return ReviewFinding(
            rule_id="REVIEW_ARTIFACT_COMPLETENESS_LOW",
            severity="error",
            message=f"Artifact completeness ratio {ratio:.0%} < 60%; pipeline likely did not complete.",
            suggested_fix="Check run logs for errors; re-run failed steps.",
        )
    return None
