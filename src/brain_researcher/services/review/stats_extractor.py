"""Extract domain scalar metrics from a completed run directory.

All file reads are graceful — missing files or parse errors produce None values,
never exceptions. The caller (build_artifact_review_bundle) decides what to do
with missing values.
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

from brain_researcher.services.review.native_bundle_resolver import (
    find_first_with_native_hints as _find_first_with_native_hints,
)
from brain_researcher.services.review.native_bundle_resolver import (
    load_json_artifact as _load_json_safe,
)
from brain_researcher.services.review.native_bundle_resolver import (
    native_analysis_bundle as _native_analysis_bundle,
)
from brain_researcher.services.review.native_bundle_resolver import (
    native_analysis_manifest as _native_analysis_manifest,
)
from brain_researcher.services.review.native_bundle_resolver import (
    native_execution_manifest as _native_execution_manifest,
)
from brain_researcher.services.review.native_bundle_resolver import (
    native_observation as _native_observation,
)
from brain_researcher.services.review.native_bundle_resolver import (
    native_steps as _native_steps,
)
from brain_researcher.services.review.native_bundle_resolver import (
    resolve_ref_path as _resolve_ref_path,
)
from brain_researcher.services.review.native_review_contract import (
    build_native_review_contract,
)

logger = logging.getLogger(__name__)

_TASK_KEYS = ("task", "task_name", "task_label", "paradigm")
_META_ANALYTIC_TASK_ALIASES = {
    "nback": "working memory",
    "working_memory": "working memory",
    "working-memory": "working memory",
    "go_nogo": "response inhibition",
    "go-no-go": "response inhibition",
    "linebisection": "attention",
}
_DEFAULT_REQUIRED_ROOT_ARTIFACTS = (
    "run.json",
    "observation.json",
    "analysis_bundle.json",
    "provenance.json",
    "trace.jsonl",
    "trajectory.json",
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_jsonl_safe(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
    except Exception:
        return []
    return rows


def _as_int(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _boolish(value: Any) -> bool | None:
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


def _normalize_name(value: Any) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _read_csv_column(path: Path, column: str) -> list[float]:
    """Return all numeric values from a named column in a TSV/CSV file."""
    try:
        text = path.read_text(encoding="utf-8")
        # detect delimiter
        delimiter = "\t" if "\t" in text[:256] else ","
        reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
        values: list[float] = []
        for row in reader:
            raw = row.get(column, "").strip()
            try:
                values.append(float(raw))
            except (ValueError, TypeError):
                pass
        return values
    except Exception:
        return []


def _first_present_from_mappings(
    mappings: list[dict[str, Any] | None],
    *keys: str,
) -> Any:
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        for key in keys:
            value = mapping.get(key)
            if value not in (None, "", [], {}, ()):
                return value
    return None


def _first_present_nested(
    mappings: list[dict[str, Any] | None],
    sections: tuple[str, ...],
    *keys: str,
) -> Any:
    sources: list[dict[str, Any] | None] = []
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        sources.append(mapping)
        for section in sections:
            nested = mapping.get(section)
            if isinstance(nested, dict):
                sources.append(nested)
    return _first_present_from_mappings(sources, *keys)


def _run_steps(run_dir: Path) -> list[dict[str, Any]]:
    bundle = _native_analysis_bundle(run_dir)
    normalized = _native_steps(run_dir, bundle)
    if normalized:
        return normalized
    run_payload = _load_json_safe(run_dir / "run.json")
    if not isinstance(run_payload, dict):
        return []
    raw_steps = (
        run_payload.get("steps") if isinstance(run_payload.get("steps"), list) else []
    )
    return [step for step in raw_steps if isinstance(step, dict)]


def _native_review_context(run_dir: Path) -> dict[str, Any]:
    bundle = _native_analysis_bundle(run_dir)
    observation = _native_observation(run_dir, bundle)
    execution_manifest = _native_execution_manifest(run_dir, bundle)
    try:
        contract = build_native_review_contract(
            bundle,
            observation=observation,
            execution_manifest=execution_manifest,
        )
    except Exception:
        return {}
    review_context = contract.get("review_context")
    return review_context if isinstance(review_context, dict) else {}


def _resolve_declared_artifact_path(
    run_dir: Path,
    *keys: str,
) -> Path | None:
    return _resolve_declared_review_context_path(
        run_dir, "statistical_inference", *keys
    )


def _resolve_declared_review_context_path(
    run_dir: Path,
    section: str,
    *keys: str,
) -> Path | None:
    review_context = _native_review_context(run_dir)
    section_mapping = (
        review_context.get(section)
        if isinstance(review_context.get(section), dict)
        else {}
    )
    raw_ref = _first_present_from_mappings([section_mapping], *keys)
    return _resolve_ref_path(run_dir, raw_ref)


def _first_string_from_run_steps(
    run_dir: Path,
    keys: tuple[str, ...],
) -> str | None:
    for step in _run_steps(run_dir):
        params = step.get("params") if isinstance(step.get("params"), dict) else {}
        for key in keys:
            value = params.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _meta_analytic_term_for_task(task: str | None) -> str | None:
    raw = str(task or "").strip()
    if not raw:
        return None
    slug = raw.lower().replace("-", "_").replace(" ", "_")
    return _META_ANALYTIC_TASK_ALIASES.get(slug, raw)


def _extract_3d_map_data(path: Path) -> tuple[Any, Any] | tuple[None, None]:
    try:
        import nibabel as nib
        import numpy as np

        img = nib.load(str(path))
        data = np.asarray(img.get_fdata(), dtype=float)
        if data.ndim == 4:
            data = data[..., 0]
        if data.ndim != 3:
            return None, None
        return img, data
    except Exception:
        return None, None


def _extract_meta_analytic_spatial_metrics(run_dir: Path) -> dict[str, Any]:
    """Compare an observed stat/effect map to a task-conditioned Neurosynth prior."""
    task = _first_string_from_run_steps(run_dir, _TASK_KEYS)
    term = _meta_analytic_term_for_task(task)
    defaults = {
        "meta_analytic_term": term,
        "meta_analytic_spatial_corr": None,
        "meta_analytic_voxels_compared": None,
    }
    if term is None:
        return defaults

    result_map_path = _find_first_with_native_hints(
        run_dir,
        [
            "**/*z_map.nii*",
            "**/*zstat*.nii*",
            "**/*stat-z*.nii*",
            "**/*t_map.nii*",
            "**/*tstat*.nii*",
            "**/*stat-t*.nii*",
            "**/*effect_map.nii*",
            "**/*effect*.nii*",
            "**/*beta_map.nii*",
            "**/*beta*.nii*",
            "**/*cope*.nii*",
        ],
    )
    if result_map_path is None:
        return defaults

    result_img, result_data = _extract_3d_map_data(result_map_path)
    if result_img is None or result_data is None:
        return defaults

    try:
        import numpy as np
        from nilearn import image

        from brain_researcher.core.analysis.neurosynth_integration import (
            get_neurosynth_mapping,
        )

        payload = get_neurosynth_mapping(term)
        activation_maps = (
            payload.get("activation_maps") if isinstance(payload, dict) else None
        )
        if not activation_maps:
            return defaults
        reference_img = activation_maps[0]
        reference_resampled = image.resample_to_img(
            reference_img,
            result_img,
            interpolation="continuous",
            force_resample=True,
            copy_header=True,
        )
        reference_data = np.asarray(reference_resampled.get_fdata(), dtype=float)
        if reference_data.ndim == 4:
            reference_data = reference_data[..., 0]

        x = result_data.ravel()
        y = reference_data.ravel()
        mask = np.isfinite(x) & np.isfinite(y) & ((x != 0) | (y != 0))
        n_voxels = int(mask.sum())
        if n_voxels < 20:
            return defaults
        x = x[mask]
        y = y[mask]
        if float(np.std(x)) == 0.0 or float(np.std(y)) == 0.0:
            return defaults
        corr = float(np.corrcoef(x, y)[0, 1])
        if not np.isfinite(corr):
            return defaults
        return {
            "meta_analytic_term": term,
            "meta_analytic_spatial_corr": round(corr, 4),
            "meta_analytic_voxels_compared": n_voxels,
        }
    except Exception:
        return defaults


def _extract_tribe_metrics(run_dir: Path) -> dict[str, Any]:
    """Extract review-friendly metrics from TRIBE prediction / analysis folders."""
    prediction_summary_path = _find_first_with_native_hints(
        run_dir,
        ["run_summary.json", "**/run_summary.json"],
    )
    prediction_summary = (
        _load_json_safe(prediction_summary_path)
        if prediction_summary_path is not None
        else None
    )
    analysis_summary_path = _find_first_with_native_hints(
        run_dir,
        ["summary.json", "**/summary.json"],
    )
    analysis_summary = (
        _load_json_safe(analysis_summary_path)
        if analysis_summary_path is not None
        else None
    )

    metrics: dict[str, Any] = {
        "tribe_item_count": None,
        "tribe_failure_rate": None,
        "tribe_task_count": None,
        "tribe_mean_segment_count": None,
        "tribe_embedding_dim": None,
        "tribe_surface_vertices": None,
        "tribe_pca_top1_variance": None,
        "tribe_roi_count": None,
        "tribe_candidate_count": None,
    }

    rows_path = _find_first_with_native_hints(
        run_dir,
        ["embedding_rows.jsonl", "**/embedding_rows.jsonl"],
    )
    if rows_path is not None and rows_path.exists():
        rows = _load_jsonl_safe(rows_path)
        if rows:
            metrics["tribe_item_count"] = len(rows)
            segment_counts = [
                float(row["segment_count"])
                for row in rows
                if isinstance(row.get("segment_count"), int | float)
            ]
            if segment_counts:
                metrics["tribe_mean_segment_count"] = round(
                    sum(segment_counts) / len(segment_counts), 4
                )
            n_vertices = [
                int(row["n_vertices"])
                for row in rows
                if isinstance(row.get("n_vertices"), int)
            ]
            if n_vertices:
                metrics["tribe_surface_vertices"] = max(
                    set(n_vertices), key=n_vertices.count
                )
                metrics["tribe_embedding_dim"] = metrics["tribe_surface_vertices"]
            task_ids = {
                str(row.get("task_id")).strip()
                for row in rows
                if isinstance(row.get("task_id"), str)
                and str(row.get("task_id")).strip()
            }
            if task_ids:
                metrics["tribe_task_count"] = len(task_ids)

    if prediction_summary is not None:
        n_success = int(prediction_summary.get("n_success") or 0)
        n_failures = int(prediction_summary.get("n_failures") or 0)
        total = n_success + n_failures
        if metrics["tribe_item_count"] is None and total > 0:
            metrics["tribe_item_count"] = total
        if total > 0:
            metrics["tribe_failure_rate"] = round(n_failures / total, 4)
        task_counts = prediction_summary.get("per_task_requested_item_count")
        if isinstance(task_counts, dict) and task_counts:
            metrics["tribe_task_count"] = len(task_counts)

    if analysis_summary is not None:
        n_rows = analysis_summary.get("n_rows")
        if metrics["tribe_item_count"] is None and isinstance(n_rows, int | float):
            metrics["tribe_item_count"] = int(n_rows)
        embedding_shape = analysis_summary.get("embedding_shape")
        if isinstance(embedding_shape, list) and len(embedding_shape) >= 2:
            try:
                metrics["tribe_embedding_dim"] = int(embedding_shape[1])
            except (TypeError, ValueError):
                pass
        ranked_candidates = analysis_summary.get("ranked_candidate_ids")
        if isinstance(ranked_candidates, list):
            metrics["tribe_candidate_count"] = len(ranked_candidates)
        if isinstance(analysis_summary.get("pca_explained_variance_ratio"), list):
            try:
                metrics["tribe_pca_top1_variance"] = round(
                    float(analysis_summary["pca_explained_variance_ratio"][0]), 4
                )
            except (IndexError, TypeError, ValueError):
                pass

    roi_summary_path = _find_first_with_native_hints(
        run_dir,
        ["roi_atlas_summary.json", "**/roi_atlas_summary.json"],
    )
    roi_summary = (
        _load_json_safe(roi_summary_path) if roi_summary_path is not None else None
    )
    if roi_summary is not None and isinstance(roi_summary.get("n_rois"), int):
        metrics["tribe_roi_count"] = roi_summary["n_rois"]

    pca_summary_path = _find_first_with_native_hints(
        run_dir,
        ["pca_summary.json", "**/pca_summary.json"],
    )
    pca_summary = (
        _load_json_safe(pca_summary_path) if pca_summary_path is not None else None
    )
    if pca_summary is not None and metrics["tribe_pca_top1_variance"] is None:
        ratios = pca_summary.get("explained_variance_ratio")
        if isinstance(ratios, list):
            try:
                metrics["tribe_pca_top1_variance"] = round(float(ratios[0]), 4)
            except (IndexError, TypeError, ValueError):
                pass

    return metrics


def _extract_external_summary_metrics(run_dir: Path) -> dict[str, Any]:
    """Extract generic metrics from synthesized external source summaries."""
    defaults = {
        "external_item_count": None,
        "external_failure_rate": None,
        "external_embedding_dim": None,
        "external_roi_count": None,
        "external_top_score": None,
        "external_n_folds": None,
        "external_mean_train_r2": None,
        "external_mean_test_r2": None,
        "external_mean_test_pearson_r": None,
    }
    data = _native_analysis_manifest(run_dir)
    if not data:
        return defaults

    return {
        "external_item_count": _as_int(
            data.get("n_items")
            if data.get("n_items") is not None
            else data.get("n_rows")
        ),
        "external_failure_rate": _as_float(data.get("failure_rate")),
        "external_embedding_dim": _as_int(data.get("embedding_dim")),
        "external_roi_count": _as_int(data.get("n_rois")),
        "external_top_score": _as_float(data.get("top_contrast_score")),
        "external_n_folds": _as_int(data.get("n_folds")),
        "external_mean_train_r2": _as_float(data.get("mean_train_r2")),
        "external_mean_test_r2": _as_float(data.get("mean_test_r2")),
        "external_mean_test_pearson_r": _as_float(data.get("mean_test_pearson_r")),
    }


# ---------------------------------------------------------------------------
# Per-domain extractors
# ---------------------------------------------------------------------------


def _extract_motion_metrics(run_dir: Path) -> dict[str, float | None]:
    """Extract mean FD and scrubbing fraction from confounds file."""
    confounds_path = _find_first_with_native_hints(
        run_dir,
        [
            "**/*desc-confounds_timeseries.tsv",
            "**/*confounds_timeseries.tsv",
            "**/*confounds.tsv",
            "**/*motion_params.tsv",
        ],
    )
    if confounds_path is None:
        return {"mean_fd": None, "scrubbing_fraction": None, "max_fd": None}

    fd_values = _read_csv_column(confounds_path, "framewise_displacement")
    if not fd_values:
        return {"mean_fd": None, "scrubbing_fraction": None, "max_fd": None}

    mean_fd = sum(fd_values) / len(fd_values)
    max_fd = max(fd_values)
    scrubbing_fraction = sum(1 for v in fd_values if v > 0.5) / len(fd_values)
    return {
        "mean_fd": round(mean_fd, 4),
        "scrubbing_fraction": round(scrubbing_fraction, 4),
        "max_fd": round(max_fd, 4),
    }


def _extract_glm_metrics(run_dir: Path) -> dict[str, float | None]:
    """Extract R², Cohen's d, n_subjects from GLM summary files."""
    summary_path = _find_first_with_native_hints(
        run_dir,
        [
            "**/*glm_summary.json",
            "**/*model_report.json",
            "**/*model_summary.json",
            "**/*first_level_summary.json",
            "**/*group_level_summary.json",
        ],
    )
    if summary_path is None:
        return {"r_squared": None, "cohens_d_max": None, "n_subjects": None}

    data = _load_json_safe(summary_path)
    if data is None:
        return {"r_squared": None, "cohens_d_max": None, "n_subjects": None}

    def _get_float(d: dict, *keys: str) -> float | None:
        for k in keys:
            v = d.get(k)
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
        return None

    result: dict[str, float | None] = {
        "r_squared": _get_float(data, "r_squared", "r2", "explained_variance"),
        "cohens_d_max": _get_float(
            data, "cohens_d_max", "cohen_d_max", "effect_size_max"
        ),
        "n_subjects": _get_float(data, "n_subjects", "n_subs", "num_subjects"),
    }
    # B3.5: Richer effect-size metrics.
    cohens_d_median = _get_float(
        data, "cohens_d_median", "cohen_d_median", "effect_size_median"
    )
    if cohens_d_median is not None:
        result["cohens_d_median"] = cohens_d_median
    n_contrasts = _get_float(data, "n_contrasts", "num_contrasts")
    if n_contrasts is not None:
        result["n_contrasts"] = n_contrasts

    # Extract per-region/per-contrast distribution if available.
    dist = data.get("cohens_d_distribution") or data.get("effect_size_distribution")
    if isinstance(dist, list) and dist:
        try:
            values = sorted(abs(float(v)) for v in dist if v is not None)
            if values:
                n = len(values)
                result["cohens_d_median"] = result.get("cohens_d_median") or round(
                    values[n // 2], 3
                )
                result["cohens_d_q1"] = round(values[max(0, n // 4)], 3)
                result["cohens_d_q3"] = round(values[min(n - 1, 3 * n // 4)], 3)
        except (TypeError, ValueError):
            pass

    return result


def _extract_qc_metrics(run_dir: Path) -> dict[str, float | None]:
    """Extract flag_rate and total_subjects from QC report files."""
    qc_path = _find_first_with_native_hints(
        run_dir,
        [
            "**/*qc_report.json",
            "**/*qc_summary.json",
            "**/*qc_flags.json",
        ],
    )
    if qc_path is not None:
        data = _load_json_safe(qc_path)
        if data is not None:
            total = (
                data.get("total_subjects") or data.get("n_total") or data.get("total")
            )
            flagged = (
                data.get("flagged") or data.get("n_flagged") or data.get("excluded")
            )
            try:
                total_f = float(total)
                flagged_f = float(flagged)
                flag_rate = flagged_f / total_f if total_f > 0 else None
            except (TypeError, ValueError):
                flag_rate = None
            return {
                "flag_rate": round(flag_rate, 4) if flag_rate is not None else None,
                "total_subjects": float(total) if total is not None else None,
                "flagged_subjects": float(flagged) if flagged is not None else None,
            }

    # Fallback: CSV-based QC flags
    csv_path = _find_first_with_native_hints(
        run_dir,
        [
            "**/*qc_flags.csv",
            "**/*qc_flags.tsv",
        ],
    )
    if csv_path is not None:
        try:
            text = csv_path.read_text(encoding="utf-8")
            delimiter = "\t" if "\t" in text[:256] else ","
            reader = list(csv.DictReader(text.splitlines(), delimiter=delimiter))
            total = len(reader)
            flagged_col = next(
                (
                    c
                    for c in (reader[0].keys() if reader else [])
                    if "flag" in c.lower()
                ),
                None,
            )
            if flagged_col and total > 0:
                n_flagged = sum(
                    1
                    for row in reader
                    if str(row.get(flagged_col, "")).strip().lower()
                    in ("1", "true", "yes", "flagged")
                )
                return {
                    "flag_rate": round(n_flagged / total, 4),
                    "total_subjects": float(total),
                    "flagged_subjects": float(n_flagged),
                }
        except Exception:
            pass

    return {"flag_rate": None, "total_subjects": None, "flagged_subjects": None}


def _extract_design_matrix_metrics(run_dir: Path) -> dict[str, Any]:
    """Extract design matrix dimensionality and rank from tabular files."""
    design_path = _resolve_declared_review_context_path(
        run_dir,
        "design_model",
        "design_matrix_path",
    )
    if design_path is None:
        design_path = _find_first_with_native_hints(
            run_dir,
            [
                "**/*design_matrix.tsv",
                "**/*design_matrix.csv",
                "**/*design.tsv",
                "**/*design.csv",
            ],
        )
    if design_path is None:
        return {
            "design_matrix_ncols": None,
            "design_matrix_rank": None,
            "design_matrix_columns": None,
        }
    try:
        import numpy as np

        text = design_path.read_text(encoding="utf-8")
        delimiter = "\t" if "\t" in text[:256] else ","
        reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
        columns = [
            str(name).strip() for name in (reader.fieldnames or []) if str(name).strip()
        ]
        rows: list[list[float]] = []
        for row in reader:
            numeric_row: list[float] = []
            for value in row.values():
                try:
                    numeric_row.append(float(value))
                except (TypeError, ValueError):
                    numeric_row = []
                    break
            if numeric_row:
                rows.append(numeric_row)
        if not rows:
            return {
                "design_matrix_ncols": None,
                "design_matrix_rank": None,
                "design_matrix_columns": columns or None,
            }

        matrix = np.asarray(rows, dtype=float)
        return {
            "design_matrix_ncols": int(matrix.shape[1]),
            "design_matrix_rank": int(np.linalg.matrix_rank(matrix)),
            "design_matrix_columns": columns or None,
        }
    except Exception:
        return {
            "design_matrix_ncols": None,
            "design_matrix_rank": None,
            "design_matrix_columns": None,
        }


_CLUSTER_ID_KEYS = {
    "cluster",
    "cluster_id",
    "cluster_index",
    "clust_id",
}
_CLUSTER_SIZE_KEYS = {
    "cluster_size",
    "size",
    "extent",
    "n_voxels",
    "voxels",
    "k",
    "volume",
    "volume_mm3",
}
_SIGNIFICANCE_KEYS = {
    "p",
    "p_value",
    "pval",
    "cluster_p",
    "cluster_p_value",
    "p_fwe",
    "p_fdr",
    "q",
    "alpha",
}
_STAT_KEYS = {
    "z",
    "t",
    "stat",
    "score",
    "max_z",
    "peak_z",
    "z_max",
    "max_t",
    "t_max",
}
_CONTRAST_NAME_KEYS = {
    "contrast_name",
    "contrast",
    "contrast_label",
    "contrast_id",
    "name",
    "label",
}
_CONTRAST_VECTOR_KEYS = {
    "contrast_vector",
    "vector",
    "weights",
    "contrast_weights",
    "weight_vector",
}
_CONTRAST_NON_WEIGHT_KEYS = (
    _CONTRAST_NAME_KEYS
    | _CONTRAST_VECTOR_KEYS
    | {
        "description",
        "notes",
        "contrast_type",
        "type",
        "stat",
        "score",
        "p",
        "p_value",
        "pval",
        "z",
        "t",
        "effect",
        "beta",
        "estimate",
    }
)
_COORDINATE_KEY_GROUPS = (
    ("x", "y", "z"),
    ("mni_x", "mni_y", "mni_z"),
    ("coord_x", "coord_y", "coord_z"),
    ("i", "j", "k"),
)


def _normalize_columns(values: list[str]) -> list[str]:
    return [_normalize_name(value) for value in values if _normalize_name(value)]


def _has_coordinate_columns(columns: list[str]) -> bool:
    column_set = set(columns)
    return any(
        all(axis in column_set for axis in group) for group in _COORDINATE_KEY_GROUPS
    )


def _table_semantics_from_records(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    columns: list[str] = []
    for record in records:
        for key in record.keys():
            normalized = _normalize_name(key)
            if normalized and normalized not in columns:
                columns.append(normalized)
    column_set = set(columns)
    return {
        "rows": len(records),
        "columns": columns or None,
        "has_cluster_id": bool(column_set & _CLUSTER_ID_KEYS),
        "has_cluster_size": bool(column_set & _CLUSTER_SIZE_KEYS),
        "has_significance": bool(column_set & _SIGNIFICANCE_KEYS),
        "has_stat": bool(column_set & _STAT_KEYS),
        "has_coordinates": _has_coordinate_columns(columns),
    }


def _normalize_identifier(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        numeric = float(text)
    except (TypeError, ValueError):
        return text
    return str(int(numeric)) if numeric.is_integer() else text


def _cluster_id_metadata_from_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    cluster_ids: list[str] = []
    rows_missing_cluster_id = 0
    for record in records:
        cluster_id = None
        for key, value in record.items():
            if _normalize_name(key) in _CLUSTER_ID_KEYS:
                cluster_id = _normalize_identifier(value)
                break
        if cluster_id is None:
            rows_missing_cluster_id += 1
            continue
        cluster_ids.append(cluster_id)
    unique_cluster_ids = sorted(set(cluster_ids))
    return {
        "cluster_ids": unique_cluster_ids or None,
        "cluster_id_count": len(unique_cluster_ids) if unique_cluster_ids else 0,
        "rows_with_cluster_id": len(cluster_ids),
        "rows_missing_cluster_id": rows_missing_cluster_id,
        "duplicate_cluster_ids": (
            len(cluster_ids) > len(set(cluster_ids)) if cluster_ids else False
        ),
    }


def _contrast_name_metadata_from_records(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    contrast_names: list[str] = []
    rows_missing_contrast_name = 0
    for record in records:
        contrast_name = None
        for key, value in record.items():
            if _normalize_name(key) in _CONTRAST_NAME_KEYS:
                text = str(value).strip() if value is not None else ""
                if text:
                    contrast_name = text
                    break
        if contrast_name is None:
            rows_missing_contrast_name += 1
            continue
        contrast_names.append(contrast_name)
    unique_names = sorted(set(contrast_names))
    return {
        "contrast_names": unique_names or None,
        "has_contrast_name": bool(unique_names),
        "rows_missing_contrast_name": rows_missing_contrast_name,
    }


def _vector_length_from_value(value: Any) -> int | None:
    if isinstance(value, list | tuple):
        cleaned = [
            item for item in value if item is not None and str(item).strip() != ""
        ]
        return len(cleaned) if cleaned else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = None
            if isinstance(parsed, list):
                cleaned = [
                    item
                    for item in parsed
                    if item is not None and str(item).strip() != ""
                ]
                return len(cleaned) if cleaned else None
        delimiter = "," if "," in text else "\t" if "\t" in text else None
        if delimiter is not None:
            parts = [part.strip() for part in text.split(delimiter) if part.strip()]
            if parts:
                return len(parts)
    return None


def _contrast_vector_metadata_from_records(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    vector_lengths: list[int] = []
    normalized_columns: list[str] = []
    for record in records:
        for key in record.keys():
            normalized = _normalize_name(key)
            if normalized and normalized not in normalized_columns:
                normalized_columns.append(normalized)

    candidate_weight_columns = [
        column
        for column in normalized_columns
        if column not in _CONTRAST_NON_WEIGHT_KEYS
    ]
    numeric_weight_columns: list[str] = []
    if candidate_weight_columns:
        for column in candidate_weight_columns:
            saw_value = False
            all_numeric = True
            for record in records:
                raw_value = None
                for key, value in record.items():
                    if _normalize_name(key) == column:
                        raw_value = value
                        break
                if raw_value is None or str(raw_value).strip() == "":
                    continue
                saw_value = True
                if _as_float(raw_value) is None:
                    all_numeric = False
                    break
            if saw_value and all_numeric:
                numeric_weight_columns.append(column)

    for record in records:
        vector_length = None
        for key, value in record.items():
            if _normalize_name(key) in _CONTRAST_VECTOR_KEYS:
                vector_length = _vector_length_from_value(value)
                if vector_length is not None:
                    break
        if vector_length is None and numeric_weight_columns:
            numeric_values = 0
            for column in numeric_weight_columns:
                raw_value = None
                for key, value in record.items():
                    if _normalize_name(key) == column:
                        raw_value = value
                        break
                if raw_value is not None and str(raw_value).strip() != "":
                    numeric_values += 1
            if numeric_values > 0:
                vector_length = len(numeric_weight_columns)
        if vector_length is not None:
            vector_lengths.append(vector_length)

    unique_lengths = sorted(set(vector_lengths))
    return {
        "vector_lengths": unique_lengths or None,
        "rows_with_vector": len(vector_lengths),
        "weight_column_count": (
            len(numeric_weight_columns) if numeric_weight_columns else None
        ),
    }


def _load_records_from_table_path(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        suffix = path.suffix.lower()
        if suffix in {".csv", ".tsv"}:
            text = path.read_text(encoding="utf-8")
            delimiter = "\t" if suffix == ".tsv" or "\t" in text[:256] else ","
            reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
            columns = _normalize_columns(list(reader.fieldnames or []))
            records = [row for row in reader if isinstance(row, dict)]
            semantics = _table_semantics_from_records(records)
            semantics.update(_cluster_id_metadata_from_records(records))
            if columns and semantics.get("columns") is None:
                semantics["columns"] = columns
                semantics["has_coordinates"] = _has_coordinate_columns(columns)
                semantics["has_cluster_id"] = bool(set(columns) & _CLUSTER_ID_KEYS)
                semantics["has_cluster_size"] = bool(set(columns) & _CLUSTER_SIZE_KEYS)
                semantics["has_significance"] = bool(set(columns) & _SIGNIFICANCE_KEYS)
                semantics["has_stat"] = bool(set(columns) & _STAT_KEYS)
            return semantics
        if suffix == ".json":
            payload = _load_json_safe(path)
            if isinstance(payload, list):
                records = [row for row in payload if isinstance(row, dict)]
                semantics = _table_semantics_from_records(records)
                semantics.update(_cluster_id_metadata_from_records(records))
                return semantics
            if isinstance(payload, dict):
                if isinstance(payload.get("cluster_table"), list):
                    flat_records = [
                        row
                        for group in payload["cluster_table"]
                        if isinstance(group, list)
                        for row in group
                        if isinstance(row, dict)
                    ]
                    semantics = _table_semantics_from_records(flat_records)
                    semantics.update(_cluster_id_metadata_from_records(flat_records))
                    return semantics
                for key in ("clusters", "peaks"):
                    if isinstance(payload.get(key), list):
                        records = [row for row in payload[key] if isinstance(row, dict)]
                        if records:
                            semantics = _table_semantics_from_records(records)
                            semantics.update(_cluster_id_metadata_from_records(records))
                            return semantics
                if isinstance(payload.get("peak_coordinates"), list):
                    coords = payload["peak_coordinates"]
                    if coords and all(
                        isinstance(item, list | tuple) and len(item) == 3
                        for item in coords
                    ):
                        return {
                            "rows": len(coords),
                            "columns": ["x", "y", "z"],
                            "has_cluster_id": False,
                            "has_cluster_size": False,
                            "has_significance": False,
                            "has_stat": False,
                            "has_coordinates": True,
                        }
    except Exception:
        return {}
    return {}


def _extract_cluster_peak_table_metrics(run_dir: Path) -> dict[str, Any]:
    cluster_path = _resolve_declared_artifact_path(run_dir, "cluster_table_path")
    if cluster_path is None:
        cluster_path = _find_first_with_native_hints(
            run_dir,
            [
                "**/cluster_table.csv",
                "**/*cluster*table*.tsv",
                "**/*clusters.json",
            ],
        )

    peak_path = _resolve_declared_artifact_path(run_dir, "peak_table_path")
    if peak_path is None:
        peak_path = _find_first_with_native_hints(
            run_dir,
            [
                "**/peak_table.csv",
                "**/*peak*table*.tsv",
                "**/*peaks.json",
            ],
        )

    cluster_metrics = (
        _load_records_from_table_path(cluster_path) if cluster_path is not None else {}
    )
    peak_metrics = (
        _load_records_from_table_path(peak_path) if peak_path is not None else {}
    )

    return {
        "observed_cluster_table_rows": _as_int(cluster_metrics.get("rows")),
        "observed_cluster_table_has_cluster_id": _boolish(
            cluster_metrics.get("has_cluster_id")
        ),
        "observed_cluster_table_has_cluster_size": _boolish(
            cluster_metrics.get("has_cluster_size")
        ),
        "observed_cluster_table_has_significance": _boolish(
            cluster_metrics.get("has_significance")
        ),
        "observed_cluster_table_has_stat": _boolish(cluster_metrics.get("has_stat")),
        "observed_cluster_table_has_coordinates": _boolish(
            cluster_metrics.get("has_coordinates")
        ),
        "observed_cluster_table_cluster_ids": cluster_metrics.get("cluster_ids"),
        "observed_cluster_table_unique_cluster_id_count": _as_int(
            cluster_metrics.get("cluster_id_count")
        ),
        "observed_cluster_table_duplicate_cluster_ids": _boolish(
            cluster_metrics.get("duplicate_cluster_ids")
        ),
        "observed_peak_table_rows": _as_int(peak_metrics.get("rows")),
        "observed_peak_table_has_coordinates": _boolish(
            peak_metrics.get("has_coordinates")
        ),
        "observed_peak_table_has_stat": _boolish(peak_metrics.get("has_stat")),
        "observed_peak_table_has_cluster_id": _boolish(
            peak_metrics.get("has_cluster_id")
        ),
        "observed_peak_table_cluster_ids": peak_metrics.get("cluster_ids"),
        "observed_peak_table_unique_cluster_id_count": _as_int(
            peak_metrics.get("cluster_id_count")
        ),
        "observed_peak_table_rows_with_cluster_id": _as_int(
            peak_metrics.get("rows_with_cluster_id")
        ),
        "observed_peak_table_rows_missing_cluster_id": _as_int(
            peak_metrics.get("rows_missing_cluster_id")
        ),
    }


def _extract_contrast_table_metrics(run_dir: Path) -> dict[str, Any]:
    contrast_path = _resolve_declared_artifact_path(run_dir, "contrast_table_path")
    if contrast_path is None:
        contrast_path = _find_first_with_native_hints(
            run_dir,
            [
                "**/contrast_table.csv",
                "**/*contrast*table*.tsv",
                "**/*contrast*matrix*.csv",
                "**/*contrasts.json",
            ],
        )

    contrast_metrics: dict[str, Any] = {}
    records: list[dict[str, Any]] = []
    if contrast_path is not None and contrast_path.exists() and contrast_path.is_file():
        suffix = contrast_path.suffix.lower()
        if suffix in {".csv", ".tsv"}:
            try:
                text = contrast_path.read_text(encoding="utf-8")
                delimiter = "\t" if suffix == ".tsv" or "\t" in text[:256] else ","
                reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
                records = [row for row in reader if isinstance(row, dict)]
            except Exception:
                records = []
        elif suffix == ".json":
            payload = _load_json_safe(contrast_path)
            if isinstance(payload, list):
                records = [row for row in payload if isinstance(row, dict)]
            elif isinstance(payload, dict):
                for key in ("contrasts", "contrast_table"):
                    if isinstance(payload.get(key), list):
                        records = [row for row in payload[key] if isinstance(row, dict)]
                        if records:
                            break
        if records:
            contrast_metrics["rows"] = len(records)
            contrast_metrics.update(_contrast_name_metadata_from_records(records))
            contrast_metrics.update(_contrast_vector_metadata_from_records(records))

    return {
        "observed_contrast_table_rows": _as_int(contrast_metrics.get("rows")),
        "observed_contrast_table_has_contrast_name": _boolish(
            contrast_metrics.get("has_contrast_name")
        ),
        "observed_contrast_table_rows_missing_contrast_name": _as_int(
            contrast_metrics.get("rows_missing_contrast_name")
        ),
        "observed_contrast_table_names": contrast_metrics.get("contrast_names"),
        "observed_contrast_table_vector_lengths": contrast_metrics.get(
            "vector_lengths"
        ),
        "observed_contrast_table_rows_with_vector": _as_int(
            contrast_metrics.get("rows_with_vector")
        ),
        "observed_contrast_table_weight_column_count": _as_int(
            contrast_metrics.get("weight_column_count")
        ),
    }


def _extract_thresholding_metrics(run_dir: Path) -> dict[str, Any]:
    """Extract structured multiple-comparison metadata from summary artifacts."""

    summary_path = _resolve_declared_artifact_path(
        run_dir,
        "correction_summary_path",
        "threshold_summary_path",
    )
    if summary_path is None:
        summary_path = _find_first_with_native_hints(
            run_dir,
            [
                "**/multiple_comparison_summary.json",
                "**/threshold_summary.json",
                "**/statistical_critic_report.json",
                "**/statistical_critic.json",
            ],
        )
    if summary_path is not None:
        payload = _load_json_safe(summary_path)
        if isinstance(payload, dict):
            nested_summary = payload.get("summary")
            critic_checks = payload.get("checks")
            critic_multiple = (
                critic_checks.get("multiple_comparisons")
                if isinstance(critic_checks, dict)
                and isinstance(critic_checks.get("multiple_comparisons"), dict)
                else None
            )
            source = (
                critic_multiple
                if critic_multiple is not None
                else nested_summary if isinstance(nested_summary, dict) else payload
            )
            correction = _first_present_from_mappings(
                [source],
                "method",
                "correction_method",
                "multiple_comparison_correction",
            )
            height_control = _first_present_from_mappings([source], "height_control")
            return {
                "observed_multiple_comparison_correction": (
                    str(correction).strip() if correction is not None else None
                ),
                "observed_multiple_comparison_alpha": _as_float(
                    _first_present_from_mappings([source], "alpha", "correction_alpha")
                ),
                "observed_multiple_comparison_n_tests": _as_int(
                    _first_present_from_mappings([source], "n_tests")
                ),
                "observed_multiple_comparison_rejected_count": _as_int(
                    _first_present_from_mappings(
                        [source],
                        "rejected_count",
                        "significant_voxels",
                        "n_significant",
                    )
                ),
                "observed_multiple_comparison_fraction_significant": _as_float(
                    _first_present_from_mappings([source], "fraction_significant")
                ),
                "observed_height_control": (
                    str(height_control).strip() if height_control is not None else None
                ),
                "observed_voxelwise_threshold": _as_float(
                    _first_present_from_mappings(
                        [source],
                        "voxelwise_threshold",
                        "voxel_threshold",
                        "height_threshold",
                        "map_threshold",
                    )
                ),
                "observed_cluster_forming_threshold": _as_float(
                    _first_present_from_mappings(
                        [source],
                        "cluster_forming_threshold",
                        "cluster_defining_threshold",
                        "cluster_threshold",
                    )
                ),
                "observed_n_clusters_found": _as_int(
                    _first_present_from_mappings(
                        [source],
                        "n_clusters_found",
                        "n_clusters",
                        "cluster_count",
                    )
                ),
                "observed_n_clusters_surviving": _as_int(
                    _first_present_from_mappings(
                        [source],
                        "n_clusters_surviving",
                        "surviving_cluster_count",
                        "clusters_surviving",
                    )
                ),
            }

    analysis_manifest = _native_analysis_manifest(run_dir)
    execution_manifest = _native_execution_manifest(run_dir)
    execution_params = (
        execution_manifest.get("parameters")
        if isinstance(execution_manifest.get("parameters"), dict)
        else {}
    )
    observation = _native_observation(run_dir)
    provenance = observation.get("provenance")
    provenance_params = (
        provenance.get("parameters")
        if isinstance(provenance, dict)
        and isinstance(provenance.get("parameters"), dict)
        else {}
    )
    sources = [analysis_manifest, execution_params, provenance_params]
    correction = _first_present_from_mappings(
        sources,
        "multiple_comparison_correction",
        "multiple_testing_correction",
        "correction_method",
    )
    height_control = _first_present_from_mappings(sources, "height_control")
    return {
        "observed_multiple_comparison_correction": (
            str(correction).strip() if correction is not None else None
        ),
        "observed_multiple_comparison_alpha": _as_float(
            _first_present_from_mappings(
                sources,
                "correction_alpha",
                "alpha",
                "fdr_alpha",
                "fwe_alpha",
            )
        ),
        "observed_multiple_comparison_n_tests": None,
        "observed_multiple_comparison_rejected_count": None,
        "observed_multiple_comparison_fraction_significant": None,
        "observed_height_control": (
            str(height_control).strip() if height_control is not None else None
        ),
        "observed_voxelwise_threshold": _as_float(
            _first_present_from_mappings(
                sources,
                "voxelwise_threshold",
                "voxel_threshold",
                "height_threshold",
                "map_threshold",
            )
        ),
        "observed_cluster_forming_threshold": _as_float(
            _first_present_from_mappings(
                sources,
                "cluster_forming_threshold",
                "cluster_defining_threshold",
                "cluster_threshold",
            )
        ),
        "observed_n_clusters_found": _as_int(
            _first_present_from_mappings(
                sources,
                "n_clusters_found",
                "n_clusters",
                "cluster_count",
            )
        ),
        "observed_n_clusters_surviving": _as_int(
            _first_present_from_mappings(
                sources,
                "n_clusters_surviving",
                "surviving_cluster_count",
                "clusters_surviving",
            )
        ),
    }


def _extract_design_model_metrics(run_dir: Path) -> dict[str, Any]:
    """Extract observed HRF and autocorrelation metadata from task-GLM artifacts."""

    summary_path = _find_first_with_native_hints(
        run_dir,
        [
            "**/*glm_summary.json",
            "**/*model_report.json",
            "**/*first_level_summary.json",
        ],
    )
    summary = _load_json_safe(summary_path) if summary_path is not None else None
    analysis_manifest = _native_analysis_manifest(run_dir)
    execution_manifest = _native_execution_manifest(run_dir)
    execution_params = (
        execution_manifest.get("parameters")
        if isinstance(execution_manifest.get("parameters"), dict)
        else {}
    )
    observation = _native_observation(run_dir)
    provenance = observation.get("provenance")
    provenance_params = (
        provenance.get("parameters")
        if isinstance(provenance, dict)
        and isinstance(provenance.get("parameters"), dict)
        else {}
    )
    sources = [summary, analysis_manifest, execution_params, provenance_params]
    fsf_path = _find_first_with_native_hints(
        run_dir,
        [
            "**/design.fsf",
            "**/*.fsf",
        ],
    )
    fsf_text = (
        fsf_path.read_text(encoding="utf-8", errors="ignore")
        if fsf_path is not None and fsf_path.exists()
        else ""
    )

    design_columns = (
        _extract_design_matrix_metrics(run_dir).get("design_matrix_columns") or []
    )
    normalized_columns = [str(column).strip().lower() for column in design_columns]
    temporal_derivative_count = sum(
        1
        for column in normalized_columns
        if (
            "temporal_derivative" in column
            or "time_derivative" in column
            or ("deriv" in column and "dispersion" not in column)
        )
    )
    dispersion_derivative_count = sum(
        1 for column in normalized_columns if "dispersion" in column
    )
    fir_count = sum(
        1
        for column in normalized_columns
        if "fir" in column or "delay_" in column or "lag_" in column
    )

    hrf_model = _first_present_from_mappings(sources, "hrf_model", "hemodynamic_model")
    basis_set = _first_present_from_mappings(
        sources, "basis_set", "basis_function", "hrf_basis"
    )
    drift_model = _first_present_from_mappings(sources, "drift_model")
    autocorrelation_model = _first_present_from_mappings(
        sources,
        "autocorrelation_model",
        "noise_model",
        "autocorrelation_correction",
    )
    serial_correlation_correction = _first_present_from_mappings(
        sources,
        "serial_correlation_correction",
        "serial_correlation_model",
        "serial_correlation_method",
        "serial_autocorrelation_correction",
    )
    prewhitening_method = _first_present_from_mappings(
        sources,
        "prewhitening_method",
        "prewhitening",
    )
    prewhitening_enabled = _first_present_from_mappings(
        sources,
        "prewhitening_enabled",
        "prewhiten_yn",
        "film_prewhitening",
    )
    if prewhitening_enabled is None and fsf_text:
        for line in fsf_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("set fmri(prewhiten_yn)"):
                parts = stripped.split()
                if parts:
                    prewhitening_enabled = _boolish(parts[-1].strip('"'))
                    if prewhitening_enabled is True and prewhitening_method in (
                        None,
                        "",
                    ):
                        prewhitening_method = "film"
                    if (
                        prewhitening_enabled is True
                        and serial_correlation_correction in (None, "")
                    ):
                        serial_correlation_correction = "film"
                break

    return {
        "observed_hrf_model": str(hrf_model).strip() if hrf_model is not None else None,
        "observed_basis_set": str(basis_set).strip() if basis_set is not None else None,
        "observed_temporal_derivative": _first_present_from_mappings(
            sources,
            "temporal_derivative",
            "use_temporal_derivative",
            "add_temporal_derivatives",
            "time_derivative",
            "hrf_derivative",
        ),
        "observed_dispersion_derivative": _first_present_from_mappings(
            sources,
            "dispersion_derivative",
            "use_dispersion_derivative",
            "add_dispersion_derivative",
            "hrf_dispersion",
        ),
        "observed_fir_delays": _first_present_from_mappings(
            sources,
            "fir_delays",
            "fir_lags",
        ),
        "observed_drift_model": (
            str(drift_model).strip() if drift_model is not None else None
        ),
        "observed_high_pass_cutoff": _as_float(
            _first_present_from_mappings(sources, "high_pass_cutoff", "high_pass")
        ),
        "observed_autocorrelation_model": (
            str(autocorrelation_model).strip()
            if autocorrelation_model is not None
            else None
        ),
        "observed_serial_correlation_correction": (
            str(serial_correlation_correction).strip()
            if serial_correlation_correction is not None
            else None
        ),
        "observed_prewhitening_method": (
            str(prewhitening_method).strip()
            if prewhitening_method is not None
            else None
        ),
        "observed_prewhitening_enabled": _boolish(prewhitening_enabled),
        "observed_tr": _as_float(_first_present_from_mappings(sources, "tr", "t_r")),
        "design_matrix_temporal_derivative_count": (
            temporal_derivative_count if normalized_columns else None
        ),
        "design_matrix_dispersion_derivative_count": (
            dispersion_derivative_count if normalized_columns else None
        ),
        "design_matrix_fir_count": fir_count if normalized_columns else None,
    }


def _extract_contrast_metrics(run_dir: Path) -> dict[str, int | None]:
    """Extract first contrast vector dimensionality from run metadata."""
    for step in _run_steps(run_dir):
        params = step.get("params") if isinstance(step.get("params"), dict) else {}
        contrast_defs = params.get("contrasts")
        if isinstance(contrast_defs, dict):
            for value in contrast_defs.values():
                if isinstance(value, list) and value:
                    return {"contrast_dims": len(value)}
        if isinstance(params.get("contrast"), list):
            return {"contrast_dims": len(params["contrast"])}
        if isinstance(params.get("contrast_vector"), list):
            return {"contrast_dims": len(params["contrast_vector"])}
    return {"contrast_dims": None}


def _extract_output_table_metrics(run_dir: Path) -> dict[str, int | None]:
    """Extract row count from a likely result table, excluding bookkeeping TSVs."""
    patterns = [
        "**/*results.csv",
        "**/*results.tsv",
        "**/*subject*.csv",
        "**/*subject*.tsv",
        "**/*group*.csv",
        "**/*group*.tsv",
        "**/*summary_table.csv",
        "**/*summary_table.tsv",
    ]
    for pattern in patterns:
        for path in sorted(run_dir.glob(pattern)):
            lowered = path.name.lower()
            if "confounds" in lowered or "qc_flags" in lowered:
                continue
            try:
                text = path.read_text(encoding="utf-8")
                delimiter = "\t" if "\t" in text[:256] else ","
                reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
                return {"csv_n_rows": sum(1 for _ in reader)}
            except Exception:
                continue
    return {"csv_n_rows": None}


def _extract_map_shape_metrics(run_dir: Path) -> dict[str, list[int] | None]:
    """Extract spatial shapes for effect and t-stat maps from NIfTI outputs."""
    effect_path = _find_first_with_native_hints(
        run_dir,
        [
            "**/*effect_map.nii*",
            "**/*effect*.nii*",
            "**/*beta_map.nii*",
            "**/*beta*.nii*",
            "**/*cope*.nii*",
        ],
    )
    tstat_path = _find_first_with_native_hints(
        run_dir,
        [
            "**/*t_map.nii*",
            "**/*tstat*.nii*",
            "**/*stat-t*.nii*",
        ],
    )
    if effect_path is None and tstat_path is None:
        return {"effect_map_shape": None, "tstat_map_shape": None}

    try:
        import nibabel as nib

        def _shape(path: Path | None) -> list[int] | None:
            if path is None:
                return None
            return list(nib.load(str(path)).shape[:3])

        return {
            "effect_map_shape": _shape(effect_path),
            "tstat_map_shape": _shape(tstat_path),
        }
    except Exception:
        return {"effect_map_shape": None, "tstat_map_shape": None}


def _extract_condition_number_metrics(run_dir: Path) -> dict[str, float | None]:
    """Extract design matrix condition number — continuous measure of numerical stability."""
    # First try: compute from design matrix file (most accurate)
    design_path = _resolve_declared_review_context_path(
        run_dir,
        "design_model",
        "design_matrix_path",
    )
    if design_path is None:
        design_path = _find_first_with_native_hints(
            run_dir,
            [
                "**/*design_matrix.tsv",
                "**/*design_matrix.csv",
                "**/*design.tsv",
                "**/*design.csv",
            ],
        )
    if design_path is not None:
        try:
            import numpy as np

            text = design_path.read_text(encoding="utf-8")
            delimiter = "\t" if "\t" in text[:256] else ","
            reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
            rows: list[list[float]] = []
            for row in reader:
                numeric = []
                for v in row.values():
                    try:
                        numeric.append(float(v))
                    except (TypeError, ValueError):
                        numeric = []
                        break
                if numeric:
                    rows.append(numeric)
            if rows:
                matrix = np.asarray(rows, dtype=float)
                cond = float(np.linalg.cond(matrix))
                return {"design_matrix_condition_number": round(cond, 2)}
        except Exception:
            pass

    # Also try .npy format
    npy_path = _find_first_with_native_hints(
        run_dir, ["**/*design_matrix.npy", "**/*design.npy"]
    )
    if npy_path is not None:
        try:
            import numpy as np

            matrix = np.load(str(npy_path))
            if matrix.ndim == 2 and matrix.shape[0] > 0 and matrix.shape[1] > 0:
                cond = float(np.linalg.cond(matrix))
                return {"design_matrix_condition_number": round(cond, 2)}
        except Exception:
            pass

    # Fallback: pre-computed value in GLM summary JSON
    summary_path = _find_first_with_native_hints(
        run_dir,
        [
            "**/*glm_summary.json",
            "**/*model_report.json",
            "**/*first_level_summary.json",
        ],
    )
    if summary_path is not None:
        data = _load_json_safe(summary_path)
        if data:
            for key in (
                "condition_number",
                "design_matrix_condition_number",
                "cond_number",
            ):
                val = data.get(key)
                if val is not None:
                    try:
                        return {"design_matrix_condition_number": round(float(val), 2)}
                    except (TypeError, ValueError):
                        pass

    return {"design_matrix_condition_number": None}


def _extract_contrast_estimability_metrics(run_dir: Path) -> dict[str, bool | None]:
    """Check whether all declared contrasts are estimable given the design matrix.

    Uses the standard linear-algebra test: C @ pinv(X'X) @ X'X ≈ C.
    """
    # Need both design matrix and contrast definitions
    design_path = _resolve_declared_review_context_path(
        run_dir,
        "design_model",
        "design_matrix_path",
    )
    if design_path is None:
        design_path = _find_first_with_native_hints(
            run_dir,
            [
                "**/*design_matrix.tsv",
                "**/*design_matrix.csv",
                "**/*design.tsv",
                "**/*design.csv",
            ],
        )
    summary_path = _find_first_with_native_hints(
        run_dir,
        [
            "**/*glm_summary.json",
            "**/*model_report.json",
            "**/*first_level_summary.json",
        ],
    )

    if design_path is None or summary_path is None:
        return {"contrast_estimable": None}

    try:
        import numpy as np

        # Load design matrix
        text = design_path.read_text(encoding="utf-8")
        delimiter = "\t" if "\t" in text[:256] else ","
        reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
        rows: list[list[float]] = []
        for row in reader:
            numeric = []
            for v in row.values():
                try:
                    numeric.append(float(v))
                except (TypeError, ValueError):
                    numeric = []
                    break
            if numeric:
                rows.append(numeric)
        if not rows:
            return {"contrast_estimable": None}
        X = np.asarray(rows, dtype=float)

        # Load contrast vectors from summary
        data = _load_json_safe(summary_path)
        if not data:
            return {"contrast_estimable": None}

        contrasts = data.get("contrasts")
        if not isinstance(contrasts, dict):
            return {"contrast_estimable": None}

        # Check each contrast: C @ pinv(X'X) @ X'X ≈ C
        XtX = X.T @ X
        XtX_pinv = np.linalg.pinv(XtX)
        proj = XtX_pinv @ XtX  # Projection matrix

        for _name, cvec in contrasts.items():
            if not isinstance(cvec, list):
                continue
            try:
                C = np.asarray(cvec, dtype=float)
            except (TypeError, ValueError):
                continue
            if C.shape[0] != X.shape[1]:
                continue
            reconstructed = C @ proj
            if not np.allclose(C, reconstructed, atol=1e-6):
                return {"contrast_estimable": False}

        return {"contrast_estimable": True}
    except Exception:
        return {"contrast_estimable": None}


def _extract_correlation_matrix_metrics(run_dir: Path) -> dict[str, Any]:
    """Extract validity metrics from a connectivity/correlation matrix (.npy)."""
    corr_path = _find_first_with_native_hints(
        run_dir,
        [
            "**/*connectivity_matrix.npy",
            "**/*corr_matrix.npy",
            "**/*fc_matrix.npy",
            "**/*correlation_matrix.npy",
        ],
    )
    defaults: dict[str, Any] = {
        "corr_n_regions": None,
        "corr_symmetric": None,
        "corr_diag_all_ones": None,
        "corr_range_valid": None,
        "corr_positive_semidefinite": None,
        "corr_has_nan": None,
        "corr_condition_number": None,
        "corr_min_eig": None,
    }
    if corr_path is None:
        return defaults

    try:
        import numpy as np

        matrix = np.load(str(corr_path))
        if matrix.ndim == 2 and matrix.shape[0] == matrix.shape[1]:
            stack = matrix[np.newaxis, ...]
        elif matrix.ndim == 3 and matrix.shape[-2] == matrix.shape[-1]:
            stack = matrix.reshape((-1, matrix.shape[-2], matrix.shape[-1]))
        else:
            return defaults
        n = stack.shape[-1]

        has_nan = bool(np.any(~np.isfinite(stack)))
        # If NaN present, other checks are unreliable
        if has_nan:
            return {
                "corr_n_regions": int(n),
                "corr_symmetric": None,
                "corr_diag_all_ones": None,
                "corr_range_valid": None,
                "corr_positive_semidefinite": None,
                "corr_has_nan": True,
                "corr_condition_number": None,
                "corr_min_eig": None,
            }

        symmetric = bool(all(np.allclose(item, item.T, atol=1e-6) for item in stack))
        diag_ones = bool(
            all(np.allclose(np.diag(item), 1.0, atol=1e-4) for item in stack)
        )

        # Off-diagonal range check
        mask = ~np.eye(n, dtype=bool)
        offdiag = stack[:, mask]
        range_valid = bool(
            np.all(offdiag >= -1.0 - 1e-6) and np.all(offdiag <= 1.0 + 1e-6)
        )

        # PSD check (only meaningful for symmetric matrices)
        if symmetric:
            eigvals = [np.linalg.eigvalsh(item) for item in stack]
            min_eig = float(min(np.min(item) for item in eigvals))
            psd = bool(min_eig >= -1e-6)
        else:
            min_eig = None
            psd = None

        try:
            condition_number = max(float(np.linalg.cond(item)) for item in stack)
        except Exception:
            condition_number = None

        return {
            "corr_n_regions": int(n),
            "corr_symmetric": symmetric,
            "corr_diag_all_ones": diag_ones,
            "corr_range_valid": range_valid,
            "corr_positive_semidefinite": psd,
            "corr_has_nan": False,
            "corr_condition_number": (
                round(condition_number, 6)
                if condition_number is not None and np.isfinite(condition_number)
                else None
            ),
            "corr_min_eig": (
                round(min_eig, 12)
                if min_eig is not None and np.isfinite(min_eig)
                else None
            ),
        }
    except Exception:
        return defaults


def _extract_connectivity_contract_metrics(run_dir: Path) -> dict[str, Any]:
    """Extract declared FC/partial-correlation contract fields from sidecars."""

    candidates: list[dict[str, Any] | None] = []
    for pattern in (
        "**/*connectivity_contract.json",
        "**/*feature_contract.json",
        "**/*connectivity_metadata.json",
        "**/*correlation_metadata.json",
        "**/*matrix_metadata.json",
    ):
        path = _find_first_with_native_hints(run_dir, [pattern])
        if path is not None:
            payload = _load_json_safe(path)
            if isinstance(payload, dict):
                candidates.append(payload)

    review_context = _native_review_context(run_dir)
    if review_context:
        candidates.append(review_context)

    if not candidates:
        return {}

    sections = (
        "connectivity",
        "feature_contract",
        "correlation",
        "correlation_matrix",
        "partial_correlation",
        "matrix",
        "estimator",
    )
    metrics: dict[str, Any] = {}
    alias_map = {
        "corr_matrix_kind": (
            "matrix_kind",
            "corr_matrix_kind",
            "correlation_matrix_kind",
            "connectivity_matrix_kind",
            "feature_matrix_kind",
        ),
        "connectivity_source_level": (
            "source_level",
            "connectivity_source_level",
            "matrix_source_level",
        ),
        "corr_precision_estimator": (
            "precision_estimator",
            "partial_correlation_estimator",
            "corr_precision_estimator",
        ),
        "corr_covariance_estimator": (
            "covariance_estimator",
            "corr_covariance_estimator",
        ),
        "regularization": (
            "regularization",
            "regularized",
            "precision_regularization",
            "covariance_regularization",
            "shrinkage",
        ),
        "corr_n_timepoints": (
            "n_timepoints",
            "corr_n_timepoints",
            "connectivity_n_timepoints",
        ),
        "corr_effective_n_timepoints": (
            "effective_n_timepoints",
            "corr_effective_n_timepoints",
        ),
        "corr_n_regions": (
            "n_rois",
            "n_regions",
            "corr_n_rois",
            "corr_n_regions",
            "connectivity_n_rois",
        ),
        "corr_covariance_rank": (
            "covariance_rank",
            "corr_covariance_rank",
        ),
        "corr_precision_rank": (
            "precision_rank",
            "corr_precision_rank",
        ),
        "corr_covariance_condition_number": (
            "covariance_condition_number",
            "corr_covariance_condition_number",
            "fc_covariance_condition_number",
        ),
        "corr_precision_condition_number": (
            "precision_condition_number",
            "partial_correlation_condition_number",
            "corr_precision_condition_number",
            "fc_precision_condition_number",
        ),
        "corr_min_eig": (
            "min_eig",
            "corr_min_eig",
            "covariance_min_eig",
            "precision_min_eig",
        ),
        "corr_transform_state": (
            "transform_state",
            "corr_transform_state",
            "connectivity_transform_state",
        ),
    }
    for target, aliases in alias_map.items():
        value = _first_present_nested(candidates, sections, *aliases)
        if value is not None:
            metrics[target] = value
    return metrics


def _extract_scorecard_snapshot(run_dir: Path) -> dict[str, Any]:
    """Extract infra-level signals directly from run.json (no scorecard rebuild needed)."""
    bundle = _native_analysis_bundle(run_dir)
    data = _load_json_safe(run_dir / "run.json") or {}
    if not bundle and not data:
        return {}
    steps = _run_steps(run_dir)
    total = len(steps)
    succeeded = sum(
        1 for s in steps if isinstance(s, dict) and s.get("status") == "succeeded"
    )
    failed = sum(
        1 for s in steps if isinstance(s, dict) and s.get("status") == "failed"
    )
    step_success_rate = (succeeded / total) if total > 0 else None

    if bundle:
        review_contract = build_native_review_contract(
            bundle,
            observation=_native_observation(run_dir, bundle),
            execution_manifest=_native_execution_manifest(run_dir, bundle),
        )
    else:
        review_contract = (
            data.get("review_contract")
            if isinstance(data.get("review_contract"), dict)
            else {}
        )
    required_artifacts = review_contract.get("required_root_artifacts")
    if not isinstance(required_artifacts, list) or not required_artifacts:
        required_artifacts = list(_DEFAULT_REQUIRED_ROOT_ARTIFACTS)
    required_artifacts = [
        str(name).strip()
        for name in required_artifacts
        if isinstance(name, str) and str(name).strip()
    ]

    recommended_artifacts = review_contract.get("recommended_root_artifacts")
    if not isinstance(recommended_artifacts, list):
        recommended_artifacts = []
    recommended_artifacts = [
        str(name).strip()
        for name in recommended_artifacts
        if isinstance(name, str) and str(name).strip()
    ]

    required_present = sum(
        1 for name in required_artifacts if (run_dir / name).exists()
    )
    recommended_present = sum(
        1 for name in recommended_artifacts if (run_dir / name).exists()
    )
    completeness = (
        required_present / len(required_artifacts) if required_artifacts else None
    )
    recommended_ratio = (
        recommended_present / len(recommended_artifacts)
        if recommended_artifacts
        else None
    )
    minimal_reviewable = bool(required_artifacts) and required_present == len(
        required_artifacts
    )
    if (
        minimal_reviewable
        and recommended_artifacts
        and recommended_present == len(recommended_artifacts)
    ):
        review_tier = "trace_complete"
    elif minimal_reviewable and recommended_present > 0:
        review_tier = "review_bundle_ready"
    elif minimal_reviewable:
        review_tier = "minimal_reviewable"
    else:
        review_tier = "partial_import"

    return {
        "step_success_rate": (
            round(step_success_rate, 4) if step_success_rate is not None else None
        ),
        "steps_total": total,
        "steps_succeeded": succeeded,
        "steps_failed": failed,
        "artifact_completeness_ratio": (
            round(completeness, 4) if completeness is not None else None
        ),
        "artifact_recommended_coverage_ratio": (
            round(recommended_ratio, 4) if recommended_ratio is not None else None
        ),
        "artifact_required_present": required_present,
        "artifact_required_total": len(required_artifacts),
        "artifact_recommended_present": recommended_present,
        "artifact_recommended_total": len(recommended_artifacts),
        "artifact_minimal_reviewable": minimal_reviewable,
        "artifact_review_tier": review_tier,
        "artifact_contract_mode": (
            str(review_contract.get("contract_mode") or "native_run_bundle")
        ),
        "artifact_scientific_review_profile": (
            str(review_contract.get("scientific_review_profile") or "").strip() or None
        ),
        "artifact_scientific_completeness_checks": (
            [
                str(item)
                for item in review_contract.get("scientific_completeness_checks")
                if isinstance(item, str) and str(item).strip()
            ]
            if isinstance(review_contract.get("scientific_completeness_checks"), list)
            else None
        ),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_stats_from_run_dir(run_dir: Path) -> dict[str, Any]:
    """Walk run_dir and extract domain scalar metrics.

    Returns a flat dict with float | int | None values. Never raises.

    Keys produced (None if not found):
        mean_fd, max_fd, scrubbing_fraction  — motion
        r_squared, cohens_d_max, n_subjects  — GLM model fit
        flag_rate, total_subjects, flagged_subjects  — QC
    """
    try:
        run_dir = Path(run_dir).expanduser().resolve()
        metrics: dict[str, Any] = {}
        metrics.update(_extract_motion_metrics(run_dir))
        metrics.update(_extract_glm_metrics(run_dir))
        metrics.update(_extract_qc_metrics(run_dir))
        metrics.update(_extract_design_matrix_metrics(run_dir))
        metrics.update(_extract_contrast_metrics(run_dir))
        metrics.update(_extract_output_table_metrics(run_dir))
        metrics.update(_extract_map_shape_metrics(run_dir))
        metrics.update(_extract_condition_number_metrics(run_dir))
        metrics.update(_extract_contrast_estimability_metrics(run_dir))
        metrics.update(_extract_thresholding_metrics(run_dir))
        metrics.update(_extract_cluster_peak_table_metrics(run_dir))
        metrics.update(_extract_contrast_table_metrics(run_dir))
        metrics.update(_extract_design_model_metrics(run_dir))
        metrics.update(_extract_correlation_matrix_metrics(run_dir))
        for key, value in _extract_connectivity_contract_metrics(run_dir).items():
            if metrics.get(key) in (None, "", [], {}, ()):
                metrics[key] = value
        metrics.update(_extract_meta_analytic_spatial_metrics(run_dir))
        metrics.update(_extract_tribe_metrics(run_dir))
        metrics.update(_extract_external_summary_metrics(run_dir))
        if (
            metrics.get("r_squared") is None
            and metrics.get("external_mean_test_r2") is not None
        ):
            metrics["r_squared"] = metrics["external_mean_test_r2"]
        if (
            metrics.get("n_subjects") is None
            and metrics.get("external_item_count") is not None
        ):
            metrics["n_subjects"] = metrics["external_item_count"]
        metrics["metadata_n_subjects"] = metrics.get("n_subjects")
        return metrics
    except Exception as exc:
        logger.warning("stats_extractor: unexpected error for %s: %s", run_dir, exc)
        return {}
