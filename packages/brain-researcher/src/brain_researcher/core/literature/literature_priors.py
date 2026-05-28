"""Infer weak GLM priors from literature evidence (File Search)."""

from __future__ import annotations

import functools
import logging
import os
import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from brain_researcher.core.literature.gfs_store import search_gfs_auto

logger = logging.getLogger(__name__)

_HPF_DEFAULTS = {"100": 0.25, "128": 0.5, "200": 0.25}
_SMOOTH_DEFAULTS = {"4": 0.25, "6": 0.5, "8": 0.25}
_EFFECT_SIZE_DEFAULTS = {
    "median_abs_d": 0.5,
    "p90_abs_d": 0.8,
    "max_abs_d": 1.2,
}

_HPF_RANGE = (20, 400)
_SMOOTH_RANGE = (1, 20)

_HPF_PATTERNS = [
    re.compile(r"high[- ]pass[^\d]{0,20}(\d{2,3})", re.IGNORECASE),
    re.compile(r"(\d{2,3})\s*(?:s|sec|secs|second|seconds)\b", re.IGNORECASE),
]
_SMOOTH_PATTERNS = [
    re.compile(r"fwhm\s*[:=]?\s*(\d{1,2})\s*mm", re.IGNORECASE),
    re.compile(r"(\d{1,2})\s*mm\s*(?:fwhm|smoothing)", re.IGNORECASE),
    re.compile(r"smoothing[^\d]{0,20}(\d{1,2})\s*mm", re.IGNORECASE),
]
_EFFECT_SIZE_PATTERNS = [
    re.compile(
        r"(?:cohen'?s\s*d|cohens?\s*d|effect\s+size|standardized\s+effect)"
        r"[^\d+-]{0,24}([+-]?\d+(?:\.\d+)?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:cohen'?s\s*d|cohens?\s*d|effect\s+size|standardized\s+effect)"
        r"[^\d+-]{0,24}([+-]?\d+(?:\.\d+)?)\s*(?:-|to)\s*([+-]?\d+(?:\.\d+)?)",
        re.IGNORECASE,
    ),
]


def _normalize_counts(counts: dict[int, int]) -> dict[str, float]:
    total = float(sum(counts.values()))
    if total <= 0:
        return {}
    return {str(k): v / total for k, v in sorted(counts.items(), key=lambda kv: kv[0])}


def _collect_candidates(
    text: str, patterns: Iterable[re.Pattern], value_range: tuple[int, int]
) -> list[int]:
    values: list[int] = []
    if not text:
        return values
    for pat in patterns:
        for match in pat.findall(text):
            try:
                val = int(match)
            except ValueError:
                continue
            if value_range[0] <= val <= value_range[1]:
                values.append(val)
    return values


def _extract_axis_counts(hits: Iterable[dict[str, Any]], axis: str) -> dict[int, int]:
    counts: dict[int, int] = {}
    patterns = _HPF_PATTERNS if axis == "high_pass" else _SMOOTH_PATTERNS
    value_range = _HPF_RANGE if axis == "high_pass" else _SMOOTH_RANGE
    for hit in hits:
        text = f"{hit.get('title', '')}\n{hit.get('text', '')}"
        for val in _collect_candidates(text, patterns, value_range):
            counts[val] = counts.get(val, 0) + 1
    return counts


def _top_papers(hits: list[dict[str, Any]], top_k: int = 5) -> list[dict[str, Any]]:
    dedup: dict[str, dict[str, Any]] = {}
    for hit in hits:
        key = (
            hit.get("pmcid")
            or hit.get("doi")
            or hit.get("title")
            or hit.get("doc_id")
            or hit.get("snippet")
        )
        if not key:
            continue
        if key in dedup:
            continue
        dedup[key] = {
            "pmcid": hit.get("pmcid"),
            "pmid": hit.get("pmid"),
            "doi": hit.get("doi"),
            "title": hit.get("title"),
            "score": hit.get("score"),
            "snippet": hit.get("snippet"),
        }
    return list(dedup.values())[:top_k]


def _build_query(axis: str, task: str | None, contrast: str | None) -> str:
    parts = [p for p in [task, contrast, "fMRI"] if p]
    if axis == "high_pass":
        parts.extend(["high-pass filter", "cutoff", "seconds"])
    else:
        parts.extend(["spatial smoothing", "FWHM", "mm"])
    return " ".join(parts).strip()


def _build_effect_size_query(task: str | None, contrast: str | None) -> str:
    parts = [p for p in [task, contrast, "fMRI"] if p]
    parts.extend(["Cohen's d", "effect size", "group comparison"])
    return " ".join(parts).strip()


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if pct <= 0:
        return float(sorted_values[0])
    if pct >= 1:
        return float(sorted_values[-1])
    pos = (len(sorted_values) - 1) * pct
    lower = int(pos)
    upper = min(lower + 1, len(sorted_values) - 1)
    frac = pos - lower
    return float(sorted_values[lower] * (1 - frac) + sorted_values[upper] * frac)


def _extract_effect_size_candidates(hits: Iterable[dict[str, Any]]) -> list[float]:
    values: list[float] = []
    for hit in hits:
        text = (
            f"{hit.get('title', '')}\n{hit.get('text', '')}\n{hit.get('snippet', '')}"
        )
        for pattern in _EFFECT_SIZE_PATTERNS:
            for match in pattern.findall(text):
                if isinstance(match, tuple):
                    candidates = match
                else:
                    candidates = (match,)
                nums: list[float] = []
                for value in candidates:
                    try:
                        parsed = abs(float(value))
                    except (TypeError, ValueError):
                        continue
                    if 0.0 < parsed <= 10.0:
                        nums.append(parsed)
                if not nums:
                    continue
                values.append(sum(nums) / len(nums))
    return values


def _effect_size_meta_details(studies_data: list[dict[str, Any]]) -> dict[str, Any]:
    effect_sizes: list[float] = []
    weights: list[float] = []
    p_values: list[float] = []
    for study in studies_data:
        try:
            effect_size = float(study.get("effect_size", 0.0))
        except (TypeError, ValueError):
            continue
        if abs(effect_size) < 1e-9:
            continue
        try:
            p_value = float(study.get("p_value", 1.0))
        except (TypeError, ValueError):
            p_value = 1.0
        try:
            sample_size = float(study.get("sample_size", 20))
        except (TypeError, ValueError):
            sample_size = 20.0
        effect_sizes.append(effect_size)
        weights.append(max(sample_size, 0.0) * (1 - min(max(p_value, 0.0), 0.99)))
        p_values.append(p_value)

    if not effect_sizes:
        return {"error": "no_valid_effect_sizes"}
    weight_sum = sum(weights)
    weighted_mean = (
        sum(
            effect * weight
            for effect, weight in zip(effect_sizes, weights, strict=False)
        )
        / weight_sum
        if weight_sum > 0
        else sum(effect_sizes) / len(effect_sizes)
    )
    significant_studies = sum(1 for p_value in p_values if p_value < 0.05)
    return {
        "n_studies": len(effect_sizes),
        "n_significant": significant_studies,
        "weighted_mean_effect": round(weighted_mean, 3),
        "consistency": (
            round(significant_studies / len(p_values), 3) if p_values else 0.0
        ),
        "evidence": "effect_sizes",
        "method": "meta_analysis",
    }


@functools.lru_cache(maxsize=64)
def _cached_infer(
    *,
    task: str | None = None,
    contrast: str | None = None,
    store: str | None = None,
    model: str | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """Infer weak priors from literature evidence using File Search."""
    enable = os.environ.get("BR_ENABLE_LITERATURE_PRIORS", "true").lower()
    if enable in {"0", "false", "no"}:
        return {"status": "disabled", "priors": {}, "support": {}}

    axes = ["high_pass", "smoothing_fwhm"]
    priors: dict[str, dict[str, float]] = {}
    support: dict[str, Any] = {}
    statuses: set[str] = set()

    for axis in axes:
        query = _build_query(axis, task, contrast)
        result = search_gfs_auto(
            query,
            top_k=top_k,
            store=store,
            model=model,
            weak_evidence=True,
            max_calls=2,
        )
        statuses.add(result.get("status", "error"))
        hits = result.get("hits") or []
        support[axis] = {
            "status": result.get("status"),
            "query": query,
            "store": result.get("store"),
            "model": result.get("model"),
            "n_docs_hit": len(hits),
            "top_papers": _top_papers(hits, top_k=top_k),
        }

        if result.get("status") != "ok":
            continue

        counts = _extract_axis_counts(
            hits, "high_pass" if axis == "high_pass" else "smoothing"
        )
        axis_priors = _normalize_counts(counts)
        if not axis_priors:
            axis_priors = _HPF_DEFAULTS if axis == "high_pass" else _SMOOTH_DEFAULTS
        priors[axis] = axis_priors

    if priors:
        status = "ok"
    elif statuses == {"disabled"}:
        status = "disabled"
    elif statuses and statuses.issubset({"unconfigured", "unsupported_model"}):
        status = "unconfigured"
    else:
        status = "error"

    return {
        "status": status,
        "priors": priors,
        "support": support,
        "source": "literature",
    }


def infer_literature_priors(
    *,
    task: str | None = None,
    contrast: str | None = None,
    store: str | None = None,
    model: str | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """Cached wrapper for literature priors inference."""
    return _cached_infer(
        task=task,
        contrast=contrast,
        store=store,
        model=model,
        top_k=top_k,
    )


@functools.lru_cache(maxsize=64)
def _cached_effect_size_priors(
    *,
    task: str | None = None,
    contrast: str | None = None,
    store: str | None = None,
    model: str | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """Infer weak effect-size priors from literature evidence using File Search."""
    enable = os.environ.get("BR_ENABLE_LITERATURE_PRIORS", "true").lower()
    if enable in {"0", "false", "no"}:
        return {"status": "disabled", "priors": {}, "support": {}}

    query = _build_effect_size_query(task, contrast)
    result = search_gfs_auto(
        query,
        top_k=top_k,
        store=store,
        model=model,
        weak_evidence=True,
        max_calls=2,
    )
    hits = result.get("hits") or []
    support = {
        "status": result.get("status"),
        "query": query,
        "store": result.get("store"),
        "model": result.get("model"),
        "n_docs_hit": len(hits),
        "top_papers": _top_papers(hits, top_k=top_k),
    }

    if result.get("status") != "ok":
        status = result.get("status") or "error"
        return {
            "status": status,
            "priors": {},
            "support": support,
            "source": "literature",
        }

    values = _extract_effect_size_candidates(hits)
    values = sorted(values)
    if values:
        summary = {
            "median_abs_d": round(_percentile(values, 0.5), 3),
            "p90_abs_d": round(_percentile(values, 0.9), 3),
            "max_abs_d": round(values[-1], 3),
            "n_mentions": len(values),
        }
    else:
        summary = dict(_EFFECT_SIZE_DEFAULTS)
        summary["n_mentions"] = 0

    return {
        "status": "ok",
        "source": "literature",
        "task": task,
        "contrast": contrast,
        "priors": {"cohens_d": summary},
        "support": support,
    }


def infer_effect_size_priors(
    *,
    task: str | None = None,
    contrast: str | None = None,
    store: str | None = None,
    model: str | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """Cached wrapper for weak effect-size prior inference."""
    return _cached_effect_size_priors(
        task=task,
        contrast=contrast,
        store=store,
        model=model,
        top_k=top_k,
    )


def infer_effect_size_priors_from_kg(
    *,
    task: str | None = None,
    contrast: str | None = None,
    region: str | None = None,
    effect_size_records: Iterable[Mapping[str, Any]] | None = None,
    strength_from_effect_sizes: (
        Callable[[list[dict[str, Any]]], tuple[float, dict[str, Any]]] | None
    ) = None,
) -> dict[str, Any]:
    """Infer effect-size priors from supplied KG-like study records.

    Core owns the filtering/summary contract but not the concrete NeuroKG
    service. Runtime services can pass graph-derived records and, when needed,
    a service-owned strength calculator callback.
    """
    if effect_size_records is None:
        return {
            "status": "unavailable",
            "source": "kg_meta_analysis",
            "priors": {},
            "support": {},
        }

    studies_data: list[dict[str, Any]] = []
    for record in effect_size_records:
        attrs = dict(record)
        effect_size = (
            attrs.get("effect_size")
            or attrs.get("cohens_d")
            or attrs.get("statistic_value")
        )
        if effect_size is None:
            continue
        try:
            effect_size_value = float(effect_size)
        except (TypeError, ValueError):
            continue
        if abs(effect_size_value) < 1e-9:
            continue
        if task and not _text_matches(task, attrs):
            continue
        if contrast and not _text_matches(contrast, attrs):
            continue
        if region and not _text_matches(region, attrs):
            continue
        try:
            p_value = float(attrs.get("p_value", 0.05))
        except (TypeError, ValueError):
            p_value = 0.05
        try:
            sample_size = int(attrs.get("sample_size", attrs.get("n_subjects", 20)))
        except (TypeError, ValueError):
            sample_size = 20
        studies_data.append(
            {
                "effect_size": effect_size_value,
                "p_value": p_value,
                "sample_size": sample_size,
            }
        )

    if len(studies_data) < 3:
        return {
            "status": "no_data",
            "source": "kg_meta_analysis",
            "priors": {},
            "support": {"n_studies": len(studies_data)},
        }

    if strength_from_effect_sizes is not None:
        _, details = strength_from_effect_sizes(studies_data)
    else:
        details = _effect_size_meta_details(studies_data)
    effect_sizes = sorted(abs(s["effect_size"]) for s in studies_data)
    summary = {
        "median_abs_d": round(_percentile(effect_sizes, 0.5), 3),
        "p90_abs_d": round(_percentile(effect_sizes, 0.9), 3),
        "max_abs_d": round(effect_sizes[-1], 3),
        "n_mentions": len(studies_data),
        "i_squared": details.get("i_squared"),
        "weighted_mean_effect": details.get("weighted_mean_effect"),
    }
    return {
        "status": "ok",
        "source": "kg_meta_analysis",
        "priors": {"cohens_d": summary},
        "support": {"n_studies": len(studies_data), **details},
    }


def _text_matches(needle: str, attrs: dict[str, Any]) -> bool:
    """Check if *needle* appears in any string attribute of *attrs*."""
    needle_lower = needle.lower()
    for val in attrs.values():
        if isinstance(val, str) and needle_lower in val.lower():
            return True
    return False


def infer_effect_size_priors_from_enigma(
    *,
    region: str | None = None,
    working_group: str | None = None,
    measure_type: str | None = None,
) -> dict[str, Any]:
    """Infer effect-size priors from ENIGMA meta-analysis results.

    Best for subcortical/cortical morphometry comparisons (case-control).
    Falls back to demo data if no real ENIGMA data directory is configured.
    """
    try:
        from brain_researcher.core.ingestion.loaders.enigma_unified import (
            ENIGMAUnifiedLoader,
        )
    except Exception:
        return {
            "status": "unavailable",
            "source": "enigma_meta_analysis",
            "priors": {},
            "support": {},
        }

    try:
        loader = ENIGMAUnifiedLoader()
        results = loader.load_meta_analysis_results(demo_mode=True)
    except Exception:
        return {
            "status": "unavailable",
            "source": "enigma_meta_analysis",
            "priors": {},
            "support": {},
        }

    # Collect Cohen's d values from matching results.
    cohens_d_values: list[float] = []
    i_squared_values: list[float] = []
    n_cohorts = 0

    for key, df in results.items():
        if working_group and working_group.lower() not in key.lower():
            continue
        try:
            import pandas as pd

            if not isinstance(df, pd.DataFrame):
                continue
            for _, row in df.iterrows():
                row_region = str(row.get("region", "")).lower()
                if region and region.lower() not in row_region:
                    continue
                d = row.get("cohens_d")
                if d is not None and not (
                    isinstance(d, float) and (d != d)
                ):  # NaN check
                    cohens_d_values.append(abs(float(d)))
                i2 = row.get("i2_heterogeneity")
                if i2 is not None and not (isinstance(i2, float) and (i2 != i2)):
                    i_squared_values.append(float(i2))
                n_cohorts += int(row.get("n_cases", 0)) + int(row.get("n_controls", 0))
        except Exception:
            continue

    if not cohens_d_values:
        return {
            "status": "no_data",
            "source": "enigma_meta_analysis",
            "priors": {},
            "support": {},
        }

    cohens_d_values = sorted(cohens_d_values)
    mean_i2 = (
        round(sum(i_squared_values) / len(i_squared_values), 1)
        if i_squared_values
        else None
    )
    summary = {
        "median_abs_d": round(_percentile(cohens_d_values, 0.5), 3),
        "p90_abs_d": round(_percentile(cohens_d_values, 0.9), 3),
        "max_abs_d": round(cohens_d_values[-1], 3),
        "n_mentions": len(cohens_d_values),
        "i_squared": mean_i2,
    }
    return {
        "status": "ok",
        "source": "enigma_meta_analysis",
        "priors": {"cohens_d": summary},
        "support": {
            "n_regions": len(cohens_d_values),
            "n_cohorts": n_cohorts,
            "mean_i_squared": mean_i2,
        },
    }


def infer_effect_size_priors_multi(
    *,
    task: str | None = None,
    contrast: str | None = None,
    region: str | None = None,
    working_group: str | None = None,
    store: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Multi-source effect-size prior dispatcher.

    Tries sources in priority order (strongest → weakest):
    1. KG meta-analysis (graph-stored study effect sizes)
    2. ENIGMA meta-analysis (subcortical/cortical morphometry)
    3. Literature text mining (regex on paper abstracts)

    Returns the best-available prior with ``source`` and ``confidence_tier`` tags.
    """
    # 1. KG meta-analysis.
    kg_result = infer_effect_size_priors_from_kg(
        task=task, contrast=contrast, region=region
    )
    if kg_result.get("status") == "ok":
        kg_result["confidence_tier"] = "kg_meta"
        return kg_result

    # 2. ENIGMA meta-analysis (best for morphometry).
    enigma_result = infer_effect_size_priors_from_enigma(
        region=region,
        working_group=working_group,
    )
    if enigma_result.get("status") == "ok":
        enigma_result["confidence_tier"] = "enigma_meta"
        return enigma_result

    # 3. Literature text mining (weakest but always available).
    lit_result = infer_effect_size_priors(
        task=task, contrast=contrast, store=store, model=model
    )
    lit_result["confidence_tier"] = "literature_text_mining"
    return lit_result


def merge_priors(
    base: dict[str, dict[str, float]],
    literature: dict[str, dict[str, float]],
    *,
    weight: float = 0.2,
) -> dict[str, dict[str, float]]:
    """Merge literature priors into base priors with a small weight."""
    if not literature:
        return base
    merged: dict[str, dict[str, float]] = {}
    for axis in set(base) | set(literature):
        base_axis = base.get(axis, {})
        lit_axis = literature.get(axis, {})
        if not base_axis:
            merged[axis] = lit_axis
            continue
        if not lit_axis:
            merged[axis] = base_axis
            continue
        combined: dict[str, float] = {}
        for key in set(base_axis) | set(lit_axis):
            combined[key] = (1 - weight) * base_axis.get(
                key, 0.0
            ) + weight * lit_axis.get(key, 0.0)
        total = sum(combined.values())
        if total > 0:
            combined = {k: v / total for k, v in combined.items()}
        merged[axis] = combined
    return merged


__all__ = [
    "infer_effect_size_priors",
    "infer_effect_size_priors_from_enigma",
    "infer_effect_size_priors_from_kg",
    "infer_effect_size_priors_multi",
    "infer_literature_priors",
    "merge_priors",
]
