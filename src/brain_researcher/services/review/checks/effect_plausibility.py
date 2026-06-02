"""Deterministic effect plausibility checks for scientific review."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from brain_researcher.core.contracts.code_review import CodeReviewBundle, ReviewFinding
from brain_researcher.core.literature.literature_priors import (
    infer_effect_size_priors,
)
from brain_researcher.core.literature.literature_priors import (
    infer_effect_size_priors_multi as _infer_effect_size_priors_multi_from_core,
)


def infer_effect_size_priors_multi(**kwargs: Any) -> dict[str, Any]:
    """Fetch effect-size priors through the service layer before core fallback."""
    try:
        from brain_researcher.services.br_kg.query_service import (
            get_effect_size_priors,
        )

        payload = get_effect_size_priors(**kwargs)
        if payload is not None:
            return payload
    except Exception:
        pass
    return _infer_effect_size_priors_multi_from_core(**kwargs)


def _bundle_string_hint(bundle: CodeReviewBundle, keys: Iterable[str]) -> str | None:
    for container in (bundle.kg_context, bundle.stats_metrics):
        for key in keys:
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _bundle_float_metric(bundle: CodeReviewBundle, keys: Iterable[str]) -> float | None:
    for key in keys:
        value = bundle.stats_metrics.get(key)
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if parsed >= 0:
            return parsed
    return None


def _effect_size_summary(payload: dict[str, Any]) -> dict[str, float] | None:
    if payload.get("status") != "ok":
        return None
    priors = payload.get("priors")
    if not isinstance(priors, dict):
        return None
    summary = priors.get("cohens_d")
    if not isinstance(summary, dict):
        return None
    result: dict[str, float] = {}
    for key in ("median_abs_d", "p90_abs_d", "max_abs_d", "n_mentions", "i_squared"):
        try:
            result[key] = float(summary[key])
        except (TypeError, ValueError, KeyError):
            continue
    if not any(k in result for k in ("median_abs_d", "p90_abs_d", "max_abs_d")):
        return None
    return result


def meta_analytic_spatial_plausibility_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Flag very low spatial agreement with a task-conditioned meta-analytic prior.

    This is intentionally conservative: low agreement does not prove a result is
    wrong, but it is a useful review signal that the finding may be mislabeled,
    method-dependent, or genuinely novel.
    """

    corr = bundle.stats_metrics.get("meta_analytic_spatial_corr")
    term = str(bundle.stats_metrics.get("meta_analytic_term") or "task prior")
    voxels = bundle.stats_metrics.get("meta_analytic_voxels_compared")

    try:
        corr_f = float(corr)
    except (TypeError, ValueError):
        return None

    if corr_f >= 0.10:
        return None

    voxels_msg = ""
    try:
        voxels_n = int(voxels)
        if voxels_n > 0:
            voxels_msg = f" across {voxels_n} voxels"
    except (TypeError, ValueError):
        pass

    return ReviewFinding(
        rule_id="REVIEW_META_ANALYTIC_SPATIAL_PLAUSIBILITY_LOW",
        severity="warn",
        message=(
            f"Observed statistical map has low spatial correlation with the "
            f"meta-analytic prior for '{term}' (r={corr_f:.2f}){voxels_msg}."
        ),
        suggested_fix=(
            "Verify task labeling, contrast definition, and map orientation/space. "
            "If the result is intentionally novel or exploratory, report that the "
            "finding departs from the literature prior."
        ),
    )


def _compute_uncertainty_factor(
    payload: dict[str, Any],
    summary: dict[str, float],
) -> float:
    """Compute a multiplier that widens the threshold when the prior is weak.

    Returns a value >= 1.0 (wider) or slightly < 1.0 (tighter for strong sources).
    """
    factor = 1.0
    n_mentions = summary.get("n_mentions", 0)
    i_squared = summary.get("i_squared")
    source = payload.get("source", "literature")

    # Weak evidence → be lenient.
    if n_mentions < 3:
        factor *= 1.5
    elif n_mentions < 10:
        factor *= 1.2

    # High heterogeneity → field itself has wide spread.
    if i_squared is not None:
        try:
            if float(i_squared) > 75:
                factor *= 1.3
        except (TypeError, ValueError):
            pass

    # Source confidence: stronger priors → tighter threshold.
    if source == "kg_meta_analysis":
        factor *= 0.9
    elif source == "enigma_meta_analysis":
        factor *= 0.95

    return factor


def effect_size_plausibility_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Flag unusually large Cohen's d values relative to multi-source priors.

    B3.5: Uses multi-source prior dispatcher (KG meta → ENIGMA → literature)
    with uncertainty-modulated thresholds.
    """

    # Prefer median over max when available; fall back to max.
    observed = _bundle_float_metric(
        bundle,
        ("cohens_d_median", "cohens_d_max", "cohen_d_max", "effect_size_max"),
    )
    if observed is None:
        return None

    task = _bundle_string_hint(bundle, ("task", "task_name", "task_label", "paradigm"))
    contrast = _bundle_string_hint(
        bundle,
        ("contrast", "contrast_name", "contrast_label", "contrast_id"),
    )
    region = _bundle_string_hint(bundle, ("region", "roi", "brain_region"))

    try:
        payload = infer_effect_size_priors_multi(
            task=task,
            contrast=contrast,
            region=region,
        )
    except Exception:
        # Fall back to simple literature prior.
        try:
            payload = infer_effect_size_priors(task=task, contrast=contrast, top_k=5)
        except Exception:
            return None

    summary = _effect_size_summary(payload)
    if summary is None:
        return None

    median_abs_d = summary.get("median_abs_d")
    p90_abs_d = summary.get("p90_abs_d")
    max_abs_d = summary.get("max_abs_d")

    # Base thresholds (same as v0).
    base_thresholds = [1.8]
    if median_abs_d is not None:
        base_thresholds.append(median_abs_d * 3.0)
    if p90_abs_d is not None:
        base_thresholds.append(p90_abs_d * 1.5)
    if max_abs_d is not None:
        base_thresholds.append(max_abs_d * 1.1)

    # Uncertainty modulation.
    uncertainty_factor = _compute_uncertainty_factor(payload, summary)
    threshold = max(base_thresholds) * uncertainty_factor

    if observed <= threshold:
        return None

    source = payload.get("source", "literature")
    confidence_tier = payload.get("confidence_tier", "unknown")
    n_mentions = summary.get("n_mentions", 0)
    i_squared = summary.get("i_squared")

    support_bits = []
    if task:
        support_bits.append(f"task={task}")
    if contrast:
        support_bits.append(f"contrast={contrast}")
    if p90_abs_d is not None:
        support_bits.append(f"prior_p90={p90_abs_d:.2f}")
    if max_abs_d is not None:
        support_bits.append(f"prior_max={max_abs_d:.2f}")
    support_bits.append(f"source={source}")
    support_bits.append(f"n_studies={n_mentions}")
    if i_squared is not None:
        support_bits.append(f"I²={i_squared}")
    support_bits.append(f"uncertainty_factor={uncertainty_factor:.2f}")

    evidence = [
        f"Observed Cohen's d={observed:.2f} exceeds plausibility threshold {threshold:.2f} "
        f"(source={source}, tier={confidence_tier}, uncertainty_factor={uncertainty_factor:.2f}).",
    ]
    support_data = payload.get("support")
    if isinstance(support_data, dict):
        query = support_data.get("query")
        if isinstance(query, str) and query.strip():
            evidence.append(f"literature_query={query.strip()}")
        top_papers = support_data.get("top_papers")
        if isinstance(top_papers, list):
            titles = [
                str(paper.get("title")).strip()
                for paper in top_papers
                if isinstance(paper, dict)
                and isinstance(paper.get("title"), str)
                and paper.get("title")
            ]
            evidence.extend(title for title in titles[:3] if title)

    context = f" ({'; '.join(support_bits)})" if support_bits else ""
    return ReviewFinding(
        rule_id="REVIEW_EFFECT_SIZE_PLAUSIBILITY_HIGH",
        severity="warn",
        message=(
            f"Observed Cohen's d={observed:.2f} is implausibly large for the "
            f"available prior{context}."
        ),
        suggested_fix=(
            "Verify that the effect size is standardized correctly, the contrast is "
            "coded as intended, and the estimate is not inflated by scaling, outliers, "
            "or a mislabeled control condition."
        ),
        kg_evidence=evidence,
    )


__all__ = [
    "effect_size_plausibility_check",
    "meta_analytic_spatial_plausibility_check",
]
