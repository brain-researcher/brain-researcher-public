"""Pure helpers for the fitlins-multiverse adapter cluster.

These functions handle path discovery, variant normalisation, summary/
robustness statistics, and sensitivity-package assembly for the
``_fitlins_multiverse_payload`` adapter.  They were extracted from
``external_artifact_adapters`` to keep that module's size manageable.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def _fitlins_multiverse_paths(source_dir: Path) -> dict[str, Path | None] | None:
    if not source_dir.is_dir():
        return None

    run_manifest = source_dir / "run_manifest.json"
    spec_manifest = source_dir / "specs" / "multiverse_manifest.json"
    if not spec_manifest.exists():
        alt_spec_manifest = source_dir / "multiverse_manifest.json"
        if alt_spec_manifest.exists():
            spec_manifest = alt_spec_manifest

    fitlins_dir = source_dir / "fitlins"
    summary_csv = fitlins_dir / "yeo17_summary.csv"
    robustness_json = fitlins_dir / "robustness_yeo17.json"
    robustness_md = fitlins_dir / "robustness_yeo17.md"
    if not summary_csv.exists():
        alt_summary_csv = source_dir / "yeo17_summary.csv"
        if alt_summary_csv.exists():
            summary_csv = alt_summary_csv
    if not robustness_json.exists():
        alt_robustness_json = source_dir / "robustness_yeo17.json"
        if alt_robustness_json.exists():
            robustness_json = alt_robustness_json
    if not robustness_md.exists():
        alt_robustness_md = source_dir / "robustness_yeo17.md"
        if alt_robustness_md.exists():
            robustness_md = alt_robustness_md

    has_manifest = run_manifest.exists() or spec_manifest.exists()
    has_yeo17_outputs = (
        summary_csv.exists() or robustness_json.exists() or robustness_md.exists()
    )
    if not has_manifest and not has_yeo17_outputs:
        return None

    return {
        "run_manifest": run_manifest if run_manifest.exists() else None,
        "spec_manifest": spec_manifest if spec_manifest.exists() else None,
        "summary_csv": summary_csv if summary_csv.exists() else None,
        "robustness_json": robustness_json if robustness_json.exists() else None,
        "robustness_md": robustness_md if robustness_md.exists() else None,
    }


def _stable_unique(values: Iterable[Any]) -> list[Any]:
    unique: list[Any] = []
    seen: set[str] = set()
    for value in values:
        if value in (None, "", [], {}, ()):
            continue
        marker = json.dumps(value, sort_keys=True, default=str)
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(value)
    try:
        return sorted(unique, key=lambda value: str(value))
    except Exception:
        return unique


def _fitlins_multiverse_variants(
    *payloads: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    from brain_researcher.services.review.external_artifact_adapters import (
        _clone_value,
        _first_nonempty_string,
    )

    merged: dict[str, dict[str, Any]] = {}
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        variants = payload.get("variants")
        if not isinstance(variants, list):
            continue
        for idx, raw_variant in enumerate(variants, start=1):
            if not isinstance(raw_variant, dict):
                continue
            decision_points = (
                raw_variant.get("decision_points")
                if isinstance(raw_variant.get("decision_points"), dict)
                else {}
            )
            normalized = {
                "model_id": raw_variant.get("model_id"),
                "variant_id": raw_variant.get("variant_id"),
                "hrf": raw_variant.get("hrf") or decision_points.get("hrf"),
                "hrf_basis": raw_variant.get("hrf_basis")
                or decision_points.get("hrf_basis"),
                "confounds": raw_variant.get("confounds")
                or decision_points.get("confounds"),
                "high_pass": raw_variant.get("high_pass")
                or decision_points.get("high_pass"),
                "confounds_families": raw_variant.get("confounds_families")
                or decision_points.get("confounds_families"),
                "contrast": raw_variant.get("contrast"),
                "selection_reason": raw_variant.get("selection_reason"),
                "status": raw_variant.get("status"),
            }
            key = (
                _first_nonempty_string(
                    normalized,
                    "model_id",
                    "variant_id",
                )
                or f"variant-{idx}"
            )
            current = merged.setdefault(key, {})
            for field_name, field_value in normalized.items():
                if field_value not in (None, "", [], {}, ()):
                    current[field_name] = _clone_value(field_value)
    return list(merged.values())


def _fitlins_multiverse_summary_stats(path: Path | None) -> dict[str, Any]:
    stats = {
        "n_rows": None,
        "n_contrasts": 0,
        "contrast_names": [],
        "n_rois": 0,
        "summary_model_ids": [],
        "summary_variant_ids": [],
        "top_contrast": None,
    }
    if path is None or not path.exists():
        return stats

    row_count = 0
    contrast_counts: dict[str, int] = {}
    regions: set[str] = set()
    model_ids: set[str] = set()
    variant_ids: set[str] = set()
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                row_count += 1
                contrast = str(row.get("contrast") or "").strip()
                region_id = str(row.get("region_id") or "").strip()
                model_id = str(row.get("model_id") or "").strip()
                variant_id = str(row.get("variant_id") or "").strip()
                if contrast:
                    contrast_counts[contrast] = contrast_counts.get(contrast, 0) + 1
                if region_id:
                    regions.add(region_id)
                if model_id:
                    model_ids.add(model_id)
                if variant_id:
                    variant_ids.add(variant_id)
    except Exception:
        return stats

    top_contrast = None
    if contrast_counts:
        top_contrast = max(
            contrast_counts.items(),
            key=lambda item: (item[1], item[0]),
        )[0]
    stats.update(
        {
            "n_rows": row_count,
            "n_contrasts": len(contrast_counts),
            "contrast_names": sorted(contrast_counts),
            "n_rois": len(regions),
            "summary_model_ids": sorted(model_ids),
            "summary_variant_ids": sorted(variant_ids),
            "top_contrast": top_contrast,
        }
    )
    return stats


def _fitlins_multiverse_robustness_stats(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    from brain_researcher.services.review.external_artifact_adapters import (
        _as_float,
        _as_int,
    )

    stats = {
        "top_contrast": None,
        "top_contrast_score": None,
        "robustness_checks": [],
    }
    if not isinstance(payload, dict):
        return stats

    contrasts = payload.get("contrasts")
    if not isinstance(contrasts, dict):
        return stats

    best_name: str | None = None
    best_n_variants = -1
    best_score = float("-inf")
    robustness_checks: list[str] = []
    for contrast_name, raw_meta in contrasts.items():
        if not isinstance(raw_meta, dict):
            continue
        n_variants = _as_int(raw_meta.get("n_variants")) or 0
        pairwise_corr_mean = _as_float(raw_meta.get("pairwise_corr_mean"))
        if pairwise_corr_mean is not None:
            robustness_checks.append(
                f"{contrast_name}: pairwise_corr_mean={pairwise_corr_mean:.3f}"
            )
        else:
            robustness_checks.append(f"{contrast_name}: yeo17 robustness summary")
        ranking_score = (
            pairwise_corr_mean if pairwise_corr_mean is not None else float("-inf")
        )
        if n_variants > best_n_variants or (
            n_variants == best_n_variants and ranking_score > best_score
        ):
            best_name = str(contrast_name).strip() or None
            best_n_variants = n_variants
            best_score = ranking_score

    stats["top_contrast"] = best_name
    stats["top_contrast_score"] = (
        None if best_score == float("-inf") else round(best_score, 4)
    )
    stats["robustness_checks"] = robustness_checks
    return stats


def _fitlins_multiverse_sensitivity_package(
    variants: list[dict[str, Any]],
    *,
    has_robustness_summary: bool,
) -> tuple[list[str], list[str]]:
    controversial_choices: list[str] = []
    sensitivity_requirements: list[str] = []
    if not variants:
        return controversial_choices, sensitivity_requirements

    axis_levels = {
        "hrf": _stable_unique(variant.get("hrf") for variant in variants),
        "hrf_basis": _stable_unique(variant.get("hrf_basis") for variant in variants),
        "confounds": _stable_unique(variant.get("confounds") for variant in variants),
        "high_pass": _stable_unique(variant.get("high_pass") for variant in variants),
    }
    if len(axis_levels["hrf"]) > 1 or len(axis_levels["hrf_basis"]) > 1:
        controversial_choices.append("hrf")
        if has_robustness_summary:
            sensitivity_requirements.append("hrf robustness")

    if len(axis_levels["high_pass"]) > 1:
        controversial_choices.append("high_pass")
        if has_robustness_summary:
            sensitivity_requirements.append("high-pass sensitivity")

    if len(axis_levels["confounds"]) > 1:
        controversial_choices.append("confounds")
        confound_text = " ".join(
            str(level).lower() for level in axis_levels["confounds"]
        )
        if "gsr" in confound_text or "global signal" in confound_text:
            controversial_choices.append("gsr")
            if has_robustness_summary:
                sensitivity_requirements.append("gsr_on_off")
        elif has_robustness_summary:
            sensitivity_requirements.append("confound robustness")

    return _stable_unique(controversial_choices), _stable_unique(
        sensitivity_requirements
    )
