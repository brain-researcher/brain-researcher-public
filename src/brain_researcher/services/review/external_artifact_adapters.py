"""Legacy-only adapters for importing free-form external artifact folders.

These adapters are part of the external import compatibility path. Native BR
review should prefer canonical bundle contracts written by the run itself.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from statistics import fmean
from typing import Any

from brain_researcher.services.review.fitlins_multiverse_helpers import (  # noqa: F401
    _fitlins_multiverse_paths,
    _fitlins_multiverse_robustness_stats,
    _fitlins_multiverse_sensitivity_package,
    _fitlins_multiverse_summary_stats,
    _fitlins_multiverse_variants,
    _stable_unique,
)
from brain_researcher.services.review.source_io_helpers import (  # noqa: F401
    _append_context_sidecar_file,
    _collect_generic_indexed_files,
    _find_ancestor_file,
    _load_experiment_registry_entry,
    _resolve_sidecar_path,
    _should_stage_sidecar_file,
    _source_artifact_rel,
    _source_primary_json,
)

_TASK_HINTS: tuple[tuple[str, str], ...] = (
    ("theoryofmind", "theory of mind"),
    ("theory_of_mind", "theory of mind"),
    ("tom", "theory of mind"),
    ("nback", "working memory"),
    ("working_memory", "working memory"),
    ("working-memory", "working memory"),
    ("go_nogo", "response inhibition"),
    ("go-no-go", "response inhibition"),
    ("stroop", "cognitive control"),
    ("language", "language"),
    ("reading", "reading"),
    ("emotion", "emotion"),
    ("social", "social cognition"),
    ("motor", "motor"),
    ("reward", "reward"),
    ("attention", "attention"),
    ("memory", "memory"),
    ("pmat24", "fluid intelligence"),
    ("cardsort", "cognitive flexibility"),
    ("listsort", "working memory"),
    ("picseq", "episodic memory"),
    ("readeng", "reading"),
)
_TASK_STOPWORDS = frozenset(
    {
        "ibc",
        "task",
        "tasks",
        "round",
        "targeted",
        "pilot",
        "wave",
        "story",
        "question",
        "block",
        "analysis",
        "run",
        "summary",
        "prediction",
        "predictions",
        "autoresearch",
        "embedding",
        "embeddings",
        "project",
    }
)
REVIEW_CONTEXT_SCHEMA_VERSION = "review-context-v1"
_LIST_REVIEW_CONTEXT_KEYS = frozenset(
    {
        "grouped_split_keys",
        "required_group_keys",
        "controversial_choices",
        "sensitivity_requirements",
        "robustness_checks",
        "alternative_explanations",
        "controlled_covariates",
        "model_candidates",
        "layer_candidates",
        "roi_candidates",
        "prompt_candidates",
        "candidates",
        "fir_delays",
    }
)


@dataclass(slots=True)
class ExternalArtifactAdapterPayload:
    adapter_name: str
    source_kind: str
    spec_overrides: dict[str, Any] = field(default_factory=dict)
    run_record_updates: dict[str, Any] = field(default_factory=dict)
    provenance_request_updates: dict[str, Any] = field(default_factory=dict)
    run_card: dict[str, Any] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    extra_source_files: list[dict[str, str]] = field(default_factory=list)
    diagnostics_summary: dict[str, Any] = field(default_factory=dict)
    source_summary: dict[str, Any] = field(default_factory=dict)
    extraction_report: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExternalArtifactAdapterDefinition:
    name: str
    description: str
    builder: Callable[[Path], ExternalArtifactAdapterPayload | None]


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _iter_jsonl(path: Path):
    if not path.exists():
        return
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                if isinstance(payload, dict):
                    yield payload
    except Exception:
        return


def _artifact(path: str, role: str, **metadata: Any) -> dict[str, Any]:
    payload = {"path": path, "role": role}
    payload.update({k: v for k, v in metadata.items() if v is not None})
    return payload


def _normalize_token(text: str) -> str:
    return text.strip().lower().replace("-", "_").replace(" ", "_")


def _first_nonempty_string(mapping: dict[str, Any] | None, *keys: str) -> str | None:
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


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


def _humanize_task_candidate(text: str | None) -> str | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    if "/" in raw or "\\" in raw:
        raw = Path(raw).name
    normalized = _normalize_token(raw)
    for token, label in _TASK_HINTS:
        if token in normalized:
            return label

    pieces = [token for token in re.split(r"[^a-z0-9]+", normalized) if token]
    cleaned: list[str] = []
    for token in pieces:
        if token.isdigit() or re.fullmatch(r"round\d+", token):
            continue
        if token in _TASK_STOPWORDS:
            continue
        cleaned.append(token)
    if not cleaned:
        return None
    return " ".join(cleaned[:4]).strip() or None


def _infer_task_label(*candidates: Any) -> str | None:
    flat: list[str] = []
    for candidate in candidates:
        if isinstance(candidate, str):
            flat.append(candidate)
        elif isinstance(candidate, list):
            flat.extend(str(item) for item in candidate if isinstance(item, str))
        elif isinstance(candidate, dict):
            for key in (
                "task",
                "task_label",
                "paradigm",
                "label",
                "task_id",
                "target",
                "target_name",
                "target_column",
                "behavior",
                "phenotype",
                "measure",
                "outcome",
                "term_name",
            ):
                value = candidate.get(key)
                if isinstance(value, str):
                    flat.append(value)
    for text in flat:
        inferred = _humanize_task_candidate(text)
        if inferred:
            return inferred
    return None


def _value_present(value: Any) -> bool:
    return value not in (None, "", [], {}, ())


def _clone_value(value: Any) -> Any:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return value


def _first_present(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if _value_present(value):
            return _clone_value(value)
    return None


def _first_nonempty_string_from_mappings(
    mappings: Iterable[dict[str, Any] | None], *keys: str
) -> str | None:
    for mapping in mappings:
        value = _first_nonempty_string(mapping, *keys)
        if value is not None:
            return value
    return None


def _first_present_from_mappings(
    mappings: Iterable[dict[str, Any] | None], *keys: str
) -> Any:
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        value = _first_present(mapping, *keys)
        if value is not None:
            return value
    return None


def _populate_section(
    section: dict[str, Any],
    mapping: dict[str, Any],
    aliases: dict[str, tuple[str, ...]],
) -> bool:
    updated = False
    for target_key, source_keys in aliases.items():
        value = _first_present(mapping, *source_keys)
        if value is None:
            continue
        if target_key in _LIST_REVIEW_CONTEXT_KEYS and not isinstance(value, list):
            value = [value]
        section[target_key] = value
        updated = True
    return updated


def _collect_behavioral_imbalance(mapping: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        "reaction_time": ("reaction_time_difference", "rt_difference"),
        "accuracy": ("accuracy_difference",),
        "difficulty": ("difficulty_difference", "task_difficulty_difference"),
        "eye_movement": ("eye_movement_difference", "eye_tracking_difference"),
    }
    payload: dict[str, Any] = {}
    for target_key, source_keys in aliases.items():
        value = _first_present(mapping, *source_keys)
        if value is not None:
            payload[target_key] = value
    return payload


def _normalize_review_context_list_fields(context: dict[str, Any]) -> None:
    for section_name in (
        "split",
        "selection",
        "design_model",
        "sensitivity",
        "construct_validity",
    ):
        section = context.get(section_name)
        if not isinstance(section, dict):
            continue
        for key in _LIST_REVIEW_CONTEXT_KEYS:
            value = section.get(key)
            if value is None or isinstance(value, list):
                continue
            section[key] = [value]


def _review_context(
    *,
    source_summary: dict[str, Any] | None = None,
    provenance_updates: dict[str, Any] | None = None,
    extra_run_record_updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_summary = source_summary or {}
    provenance_updates = provenance_updates or {}
    extra_run_record_updates = extra_run_record_updates or {}
    context = {
        "schema_version": REVIEW_CONTEXT_SCHEMA_VERSION,
        "split": {
            "split_unit": _first_present(source_summary, "split_unit", "cv_unit"),
            "split_strategy_detail": _first_present(
                source_summary,
                "split_strategy",
                "split_strategy_detail",
                "cross_validation",
                "evaluation_protocol",
                "evaluation_strategy",
            ),
            "grouped_split_keys": _first_present(
                source_summary,
                "grouped_split_keys",
                "group_keys",
                "split_keys",
            )
            or [],
            "required_group_keys": _first_present(
                source_summary,
                "required_group_keys",
                "required_grouping_keys",
                "grouping_required_keys",
                "mandatory_group_keys",
                "required_split_groups",
            )
            or [],
            "grouping_required": _first_present(source_summary, "grouping_required"),
            "train_test_independence": _first_present(
                source_summary,
                "train_test_independence",
                "subject_alignment_status",
                "no_leakage",
            ),
            "split_manifest_path": _first_present(
                source_summary, "split_manifest_path"
            ),
            "cv_manifest_path": _first_present(source_summary, "cv_manifest_path"),
            "subject_manifest_path": _first_present(
                source_summary, "subject_manifest_path"
            ),
            "fold_manifest_path": _first_present(source_summary, "fold_manifest_path"),
            "target_manifest_path": _first_present(
                source_summary, "target_manifest_path"
            ),
            "covariate_manifest_path": _first_present(
                source_summary, "covariate_manifest_path"
            ),
            "subject_intersection_manifest_path": _first_present(
                source_summary, "subject_intersection_manifest_path"
            ),
            "subject_selection_source": _first_present(
                source_summary, "subject_selection_source"
            ),
            "label_shuffle_seed": _first_present(source_summary, "label_shuffle_seed"),
            "reference_subject_count": _first_present(
                source_summary, "reference_subject_count"
            ),
            "n_folds": _first_present(
                source_summary, "n_folds", "fold_count", "cv_folds"
            ),
        },
        "selection": {
            "selection_on_test": _first_present(
                source_summary,
                "selection_on_test",
                "selected_on_test",
                "winner_selected_on_test",
                "heldout_selection",
                "held_out_selection",
                "test_set_selection",
            ),
            "selection_scope": _first_present(
                source_summary,
                "selection_scope",
                "selection_phase",
            ),
            "selection_phase": _first_present(source_summary, "selection_phase"),
            "winner_selection_scope": _first_present(
                source_summary,
                "winner_selection_scope",
                "winner_selection_phase",
            ),
            "winner_selection_phase": _first_present(
                source_summary,
                "winner_selection_phase",
            ),
            "winner": _first_present(source_summary, "winner"),
            "best_candidate": _first_present(
                source_summary,
                "best_candidate",
                "selected_candidate",
                "winner_candidate",
            ),
            "selected_candidate": _first_present(source_summary, "selected_candidate"),
            "best_model": _first_present(
                source_summary,
                "best_model",
                "selected_model",
                "winner_model",
                "top_model",
            ),
            "best_layer": _first_present(
                source_summary,
                "best_layer",
                "selected_layer",
                "winner_layer",
                "top_layer",
            ),
            "best_roi": _first_present(
                source_summary,
                "best_roi",
                "selected_roi",
                "winner_roi",
                "top_roi",
            ),
            "best_prompt": _first_present(
                source_summary,
                "best_prompt",
                "selected_prompt",
                "winner_prompt",
                "top_prompt",
            ),
            "model_candidates": _first_present(
                source_summary,
                "model_candidates",
                "candidate_models",
                "models",
                "model_grid",
            )
            or [],
            "layer_candidates": _first_present(
                source_summary,
                "layer_candidates",
                "candidate_layers",
                "layers",
                "layer_grid",
            )
            or [],
            "roi_candidates": _first_present(
                source_summary,
                "roi_candidates",
                "candidate_rois",
                "rois",
                "roi_grid",
            )
            or [],
            "prompt_candidates": _first_present(
                source_summary,
                "prompt_candidates",
                "candidate_prompts",
                "prompts",
                "prompt_grid",
            )
            or [],
            "candidates": _first_present(
                source_summary,
                "candidates",
                "comparison_candidates",
                "winner_candidates",
            )
            or [],
            "candidate_count": _first_present(
                source_summary,
                "candidate_count",
                "n_candidates",
                "search_space_size",
            ),
            "n_models": _first_present(
                source_summary,
                "n_models",
                "model_count",
                "candidate_model_count",
            ),
            "n_layers": _first_present(
                source_summary,
                "n_layers",
                "layer_count",
                "candidate_layer_count",
            ),
            "n_rois": _first_present(
                source_summary,
                "n_rois",
                "roi_count",
                "candidate_roi_count",
            ),
            "n_prompts": _first_present(
                source_summary,
                "n_prompts",
                "prompt_count",
                "candidate_prompt_count",
            ),
            "selection_accounting": _first_present(
                source_summary, "selection_accounting"
            ),
            "multiplicity_accounting": _first_present(
                source_summary,
                "multiplicity_accounting",
            ),
            "multiple_comparison_correction": _first_present(
                source_summary,
                "multiple_comparison_correction",
                "multiple_testing_correction",
            ),
            "multiple_testing_correction": _first_present(
                source_summary,
                "multiple_testing_correction",
            ),
            "winner_selection_method": _first_present(
                source_summary, "winner_selection_method"
            ),
            "winner_selection_criterion": _first_present(
                source_summary, "winner_selection_criterion"
            ),
            "winner_selection_protocol": _first_present(
                source_summary, "winner_selection_protocol"
            ),
            "nested_cv": _first_present(source_summary, "nested_cv"),
            "selection_holdout": _first_present(source_summary, "selection_holdout"),
            "independent_validation": _first_present(
                source_summary, "independent_validation"
            ),
        },
        "provenance": {
            "provenance_tier": None,
            "evidence_provenance": None,
        },
        "null_model": {
            "null_model_spec": _first_present(
                source_summary,
                "null_model_spec",
                "null_model",
            ),
            "permutation_baseline_spec": _first_present(
                source_summary,
                "permutation_baseline_spec",
                "permutation_baseline",
                "permutation_manifest",
                "baseline_spec",
            ),
            "spatial_null_spec": _first_present(
                source_summary,
                "spatial_null_spec",
                "spatial_null",
                "spin_test",
                "spin_permutations",
                "brain_smash",
            ),
            "resampling_method": _first_present(source_summary, "resampling_method"),
            "permutation_test": _first_present(source_summary, "permutation_test"),
            "n_permutations": _first_present(source_summary, "n_permutations"),
            "permutation_seed": _first_present(source_summary, "permutation_seed"),
            "exchangeability_blocks": _first_present(
                source_summary, "exchangeability_blocks", "exchangeability_block"
            ),
        },
        "review_probes": {
            "label_permutation_null": _first_present(
                source_summary,
                "label_permutation_null",
                "permutation_null",
                "full_pipeline_permutation_null",
            ),
        },
        "preprocessing": {
            "feature_selection_scope": _first_present(
                source_summary,
                "feature_selection_scope",
                "feature_strategy",
                "feature_selection",
            ),
            "standardization_scope": _first_present(
                source_summary,
                "standardization_scope",
                "standardize_confounds",
                "standardize",
                "normalize",
            ),
            "harmonization_fit_scope": _first_present(
                source_summary,
                "harmonization_fit_scope",
                "harmonization",
                "harmonization_strategy",
                "combat",
            ),
            "confound_regression_scope": _first_present(
                source_summary,
                "confound_regression_scope",
                "confounds",
                "confound_strategy",
                "confound_columns",
            ),
            "confounds": _first_present(source_summary, "confounds"),
            "confound_strategy": _first_present(source_summary, "confound_strategy"),
            "confound_columns": _first_present(source_summary, "confound_columns"),
        },
        "cv_contract": {
            "fit_scope_by_step": _first_present(
                source_summary,
                "fit_scope_by_step",
                "fit_scopes",
                "preprocessing_fit_scope",
                "preprocessing_fit_scope_by_step",
            ),
        },
        "feature_contract": {
            "matrix_kind": _first_present(
                source_summary,
                "matrix_kind",
                "corr_matrix_kind",
                "correlation_matrix_kind",
                "connectivity_matrix_kind",
                "feature_matrix_kind",
            ),
            "source_level": _first_present(
                source_summary,
                "source_level",
                "connectivity_source_level",
                "matrix_source_level",
            ),
            "n_rois": _first_present(
                source_summary,
                "n_rois",
                "n_regions",
                "corr_n_rois",
                "corr_n_regions",
            ),
            "n_timepoints": _first_present(
                source_summary,
                "n_timepoints",
                "corr_n_timepoints",
                "connectivity_n_timepoints",
            ),
            "effective_n_timepoints": _first_present(
                source_summary,
                "effective_n_timepoints",
                "corr_effective_n_timepoints",
            ),
            "covariance_estimator": _first_present(
                source_summary,
                "covariance_estimator",
                "corr_covariance_estimator",
            ),
            "precision_estimator": _first_present(
                source_summary,
                "precision_estimator",
                "partial_correlation_estimator",
                "corr_precision_estimator",
            ),
            "regularization": _first_present(
                source_summary,
                "regularization",
                "regularized",
                "precision_regularization",
                "covariance_regularization",
                "shrinkage",
            ),
            "covariance_rank": _first_present(
                source_summary,
                "covariance_rank",
                "corr_covariance_rank",
            ),
            "precision_rank": _first_present(
                source_summary,
                "precision_rank",
                "corr_precision_rank",
            ),
            "covariance_condition_number": _first_present(
                source_summary,
                "covariance_condition_number",
                "corr_covariance_condition_number",
                "fc_covariance_condition_number",
            ),
            "precision_condition_number": _first_present(
                source_summary,
                "precision_condition_number",
                "partial_correlation_condition_number",
                "corr_precision_condition_number",
                "fc_precision_condition_number",
            ),
            "min_eig": _first_present(
                source_summary,
                "min_eig",
                "corr_min_eig",
                "covariance_min_eig",
                "precision_min_eig",
            ),
            "transform_state": _first_present(
                source_summary,
                "transform_state",
                "corr_transform_state",
                "connectivity_transform_state",
            ),
        },
        "statistical_inference": {
            "correction_summary_path": _first_present(
                source_summary,
                "correction_summary_path",
                "multiple_comparison_summary_path",
                "threshold_summary_path",
            ),
            "multiple_comparison_correction": _first_present(
                source_summary,
                "multiple_comparison_correction",
                "multiple_testing_correction",
                "correction_method",
            ),
            "multiple_testing_correction": _first_present(
                source_summary,
                "multiple_testing_correction",
            ),
            "correction_scope": _first_present(
                source_summary,
                "correction_scope",
                "correction_domain",
                "multiple_comparison_scope",
                "analysis_scope",
                "family_key",
            ),
            "correction_alpha": _first_present(
                source_summary,
                "correction_alpha",
                "alpha",
                "fdr_alpha",
                "fwe_alpha",
            ),
            "height_control": _first_present(source_summary, "height_control"),
            "voxelwise_threshold": _first_present(
                source_summary,
                "voxelwise_threshold",
                "voxel_threshold",
                "height_threshold",
                "map_threshold",
            ),
            "cluster_forming_threshold": _first_present(
                source_summary,
                "cluster_forming_threshold",
                "cluster_defining_threshold",
                "cluster_threshold",
            ),
            "cluster_alpha": _first_present(
                source_summary,
                "cluster_alpha",
                "cluster_p_threshold",
            ),
            "threshold_summary_path": _first_present(
                source_summary,
                "threshold_summary_path",
                "multiple_comparison_summary_path",
                "correction_summary_path",
            ),
            "thresholded_map_path": _first_present(
                source_summary,
                "thresholded_map_path",
                "significance_mask_path",
                "corrected_map_path",
            ),
            "contrast_table_path": _first_present(
                source_summary,
                "contrast_table_path",
                "contrasts_path",
                "contrast_matrix_path",
                "contrast_csv",
            ),
            "cluster_table_path": _first_present(source_summary, "cluster_table_path"),
            "peak_table_path": _first_present(source_summary, "peak_table_path"),
        },
        "design_model": {
            "design_matrix_path": _first_present(
                source_summary,
                "design_matrix_path",
                "design_matrix",
                "design_path",
            ),
            "hrf_model": _first_present(
                source_summary,
                "hrf_model",
                "hemodynamic_model",
            ),
            "basis_set": _first_present(
                source_summary,
                "basis_set",
                "basis_function",
                "hrf_basis",
            ),
            "temporal_derivative": _first_present(
                source_summary,
                "temporal_derivative",
                "use_temporal_derivative",
                "add_temporal_derivatives",
                "time_derivative",
                "hrf_derivative",
            ),
            "dispersion_derivative": _first_present(
                source_summary,
                "dispersion_derivative",
                "use_dispersion_derivative",
                "add_dispersion_derivative",
                "hrf_dispersion",
            ),
            "fir_delays": _first_present(source_summary, "fir_delays", "fir_lags")
            or [],
            "drift_model": _first_present(source_summary, "drift_model"),
            "high_pass_cutoff": _first_present(
                source_summary,
                "high_pass_cutoff",
                "high_pass",
            ),
            "autocorrelation_model": _first_present(
                source_summary,
                "autocorrelation_model",
                "noise_model",
                "autocorrelation_correction",
            ),
            "serial_correlation_correction": _first_present(
                source_summary,
                "serial_correlation_correction",
                "serial_correlation_model",
                "serial_correlation_method",
                "serial_autocorrelation_correction",
            ),
            "prewhitening_method": _first_present(
                source_summary,
                "prewhitening_method",
                "prewhitening",
            ),
            "prewhitening_enabled": _first_present(
                source_summary,
                "prewhitening_enabled",
                "prewhiten_yn",
                "film_prewhitening",
            ),
            "tr": _first_present(source_summary, "tr", "t_r"),
        },
        "sensitivity": {
            "controversial_choices": _first_present(
                source_summary, "controversial_choices"
            )
            or [],
            "sensitivity_requirements": _first_present(
                source_summary,
                "sensitivity_requirements",
                "validation_missing",
            )
            or [],
            "robustness_checks": _first_present(
                source_summary,
                "robustness_checks",
                "sensitivity_checks",
                "sensitivity_analysis",
                "validation_evidence",
            )
            or [],
        },
        "construct_validity": {
            "behavioral_imbalance": _first_present(
                source_summary, "behavioral_imbalance"
            )
            or {},
            "alternative_explanations": _first_present(
                source_summary,
                "alternative_explanations",
                "construct_validity_alternatives",
            )
            or [],
            "control_strategy": _first_present(
                source_summary,
                "control_strategy",
                "behavioral_control_strategy",
            ),
            "controlled_covariates": _first_present(
                source_summary,
                "controlled_covariates",
                "behavioral_covariates",
                "control_variables",
            )
            or [],
        },
    }
    _normalize_review_context_list_fields(context)
    behavioral_imbalance = _collect_behavioral_imbalance(source_summary)
    if behavioral_imbalance:
        existing = context["construct_validity"].get("behavioral_imbalance")
        merged_imbalance = dict(existing) if isinstance(existing, dict) else {}
        merged_imbalance.update(behavioral_imbalance)
        context["construct_validity"]["behavioral_imbalance"] = merged_imbalance
    if context["null_model"]["null_model_spec"] is None:
        null_model_spec_fields = {
            key: value
            for key, value in (
                ("resampling_method", context["null_model"].get("resampling_method")),
                ("permutation_test", context["null_model"].get("permutation_test")),
                ("n_permutations", context["null_model"].get("n_permutations")),
                ("permutation_seed", context["null_model"].get("permutation_seed")),
                (
                    "exchangeability_blocks",
                    context["null_model"].get("exchangeability_blocks"),
                ),
            )
            if value is not None
        }
        if null_model_spec_fields:
            context["null_model"]["null_model_spec"] = null_model_spec_fields

    if context["null_model"]["permutation_baseline_spec"] is None:
        baseline_fields = {
            key: value
            for key, value in (
                (
                    "permutation_baseline",
                    _first_present(source_summary, "permutation_baseline"),
                ),
                (
                    "permutation_manifest",
                    _first_present(source_summary, "permutation_manifest"),
                ),
                ("baseline_spec", _first_present(source_summary, "baseline_spec")),
            )
            if value is not None
        }
        if baseline_fields:
            context["null_model"]["permutation_baseline_spec"] = baseline_fields

    evidence_sources: list[str] = []
    if any(
        _value_present(context["split"].get(key))
        for key in (
            "split_unit",
            "split_strategy_detail",
            "grouped_split_keys",
            "required_group_keys",
            "grouping_required",
            "train_test_independence",
            "split_manifest_path",
            "cv_manifest_path",
            "subject_manifest_path",
            "fold_manifest_path",
            "target_manifest_path",
            "covariate_manifest_path",
            "subject_intersection_manifest_path",
            "subject_selection_source",
            "label_shuffle_seed",
            "reference_subject_count",
            "n_folds",
        )
    ):
        evidence_sources.append("source_summary")
    if any(
        _value_present(context["selection"].get(key))
        for key in (
            "selection_on_test",
            "selection_scope",
            "selection_phase",
            "winner_selection_scope",
            "winner_selection_phase",
            "winner",
            "best_candidate",
            "selected_candidate",
            "best_model",
            "best_layer",
            "best_roi",
            "best_prompt",
            "model_candidates",
            "layer_candidates",
            "roi_candidates",
            "prompt_candidates",
            "candidates",
            "candidate_count",
            "n_models",
            "n_layers",
            "n_rois",
            "n_prompts",
            "selection_accounting",
            "multiplicity_accounting",
            "multiple_comparison_correction",
            "multiple_testing_correction",
            "winner_selection_method",
            "winner_selection_criterion",
            "winner_selection_protocol",
            "nested_cv",
            "selection_holdout",
            "independent_validation",
        )
    ):
        evidence_sources.append("source_summary")
    if any(
        _value_present(context["preprocessing"].get(key))
        for key in (
            "feature_selection_scope",
            "standardization_scope",
            "harmonization_fit_scope",
            "confound_regression_scope",
            "confounds",
            "confound_strategy",
            "confound_columns",
        )
    ):
        evidence_sources.append("source_summary")
    if any(
        _value_present(context["cv_contract"].get(key))
        for key in ("fit_scope_by_step",)
    ):
        evidence_sources.append("source_summary")
    if any(
        _value_present(context["feature_contract"].get(key))
        for key in (
            "matrix_kind",
            "source_level",
            "n_rois",
            "n_timepoints",
            "effective_n_timepoints",
            "covariance_estimator",
            "precision_estimator",
            "regularization",
            "covariance_rank",
            "precision_rank",
            "covariance_condition_number",
            "precision_condition_number",
            "min_eig",
        )
    ):
        evidence_sources.append("source_summary")
    if any(
        _value_present(context["statistical_inference"].get(key))
        for key in (
            "multiple_comparison_correction",
            "multiple_testing_correction",
            "correction_scope",
            "correction_alpha",
            "height_control",
            "voxelwise_threshold",
            "cluster_forming_threshold",
            "cluster_alpha",
            "correction_summary_path",
            "threshold_summary_path",
            "thresholded_map_path",
            "contrast_table_path",
            "cluster_table_path",
            "peak_table_path",
        )
    ):
        evidence_sources.append("source_summary")
    if any(
        _value_present(context["design_model"].get(key))
        for key in (
            "hrf_model",
            "basis_set",
            "temporal_derivative",
            "dispersion_derivative",
            "fir_delays",
            "drift_model",
            "high_pass_cutoff",
            "autocorrelation_model",
            "serial_correlation_correction",
            "prewhitening_method",
            "prewhitening_enabled",
            "tr",
        )
    ):
        evidence_sources.append("source_summary")
    if any(
        _value_present(context["sensitivity"].get(key))
        for key in (
            "controversial_choices",
            "sensitivity_requirements",
            "robustness_checks",
        )
    ):
        evidence_sources.append("source_summary")
    if any(
        _value_present(context["construct_validity"].get(key))
        for key in (
            "behavioral_imbalance",
            "alternative_explanations",
            "control_strategy",
            "controlled_covariates",
        )
    ):
        evidence_sources.append("source_summary")
    if any(
        _value_present(context["null_model"].get(key))
        for key in (
            "null_model_spec",
            "permutation_baseline_spec",
            "spatial_null_spec",
            "resampling_method",
            "permutation_test",
            "n_permutations",
            "permutation_seed",
            "exchangeability_blocks",
        )
    ):
        evidence_sources.append("source_summary")
    if any(
        _value_present(context["review_probes"].get(key))
        for key in ("label_permutation_null",)
    ):
        evidence_sources.append("source_summary")
    if any(_value_present(value) for value in provenance_updates.values()):
        evidence_sources.append("provenance_updates")
    if any(_value_present(value) for value in extra_run_record_updates.values()):
        evidence_sources.append("extra_run_record_updates")

    if evidence_sources:
        ordered = list(dict.fromkeys(evidence_sources))
        context["provenance"]["evidence_provenance"] = ordered
        context["provenance"]["provenance_tier"] = (
            "multi_source" if len(ordered) > 1 else "single_source"
        )
    return context


def _source_statistical_inference_fields(
    review_context_sources: Iterable[dict[str, Any] | None],
) -> dict[str, Any]:
    return {
        "multiple_comparison_correction": _first_present_from_mappings(
            review_context_sources,
            "multiple_comparison_correction",
            "multiple_testing_correction",
            "correction_method",
        ),
        "multiple_testing_correction": _first_present_from_mappings(
            review_context_sources,
            "multiple_testing_correction",
        ),
        "correction_scope": _first_present_from_mappings(
            review_context_sources,
            "correction_scope",
            "correction_domain",
            "multiple_comparison_scope",
            "analysis_scope",
            "family_key",
        ),
        "correction_alpha": _first_present_from_mappings(
            review_context_sources,
            "correction_alpha",
            "alpha",
            "fdr_alpha",
            "fwe_alpha",
        ),
        "height_control": _first_present_from_mappings(
            review_context_sources,
            "height_control",
        ),
        "voxelwise_threshold": _first_present_from_mappings(
            review_context_sources,
            "voxelwise_threshold",
            "voxel_threshold",
            "height_threshold",
            "map_threshold",
        ),
        "cluster_forming_threshold": _first_present_from_mappings(
            review_context_sources,
            "cluster_forming_threshold",
            "cluster_defining_threshold",
            "cluster_threshold",
        ),
        "cluster_alpha": _first_present_from_mappings(
            review_context_sources,
            "cluster_alpha",
            "cluster_p_threshold",
        ),
        "threshold_summary_path": _first_present_from_mappings(
            review_context_sources,
            "threshold_summary_path",
            "multiple_comparison_summary_path",
            "correction_summary_path",
        ),
        "correction_summary_path": _first_present_from_mappings(
            review_context_sources,
            "correction_summary_path",
            "multiple_comparison_summary_path",
            "threshold_summary_path",
        ),
        "thresholded_map_path": _first_present_from_mappings(
            review_context_sources,
            "thresholded_map_path",
            "significance_mask_path",
            "corrected_map_path",
        ),
        "contrast_table_path": _first_present_from_mappings(
            review_context_sources,
            "contrast_table_path",
            "contrasts_path",
            "contrast_matrix_path",
            "contrast_csv",
        ),
        "cluster_table_path": _first_present_from_mappings(
            review_context_sources,
            "cluster_table_path",
        ),
        "peak_table_path": _first_present_from_mappings(
            review_context_sources,
            "peak_table_path",
        ),
    }


def _source_design_model_fields(
    review_context_sources: Iterable[dict[str, Any] | None],
) -> dict[str, Any]:
    return {
        "design_matrix_path": _first_present_from_mappings(
            review_context_sources,
            "design_matrix_path",
            "design_matrix",
            "design_path",
        ),
        "hrf_model": _first_present_from_mappings(
            review_context_sources,
            "hrf_model",
            "hemodynamic_model",
        ),
        "basis_set": _first_present_from_mappings(
            review_context_sources,
            "basis_set",
            "basis_function",
            "hrf_basis",
        ),
        "temporal_derivative": _first_present_from_mappings(
            review_context_sources,
            "temporal_derivative",
            "use_temporal_derivative",
            "add_temporal_derivatives",
            "time_derivative",
            "hrf_derivative",
        ),
        "dispersion_derivative": _first_present_from_mappings(
            review_context_sources,
            "dispersion_derivative",
            "use_dispersion_derivative",
            "add_dispersion_derivative",
            "hrf_dispersion",
        ),
        "fir_delays": _first_present_from_mappings(
            review_context_sources,
            "fir_delays",
            "fir_lags",
        ),
        "drift_model": _first_present_from_mappings(
            review_context_sources,
            "drift_model",
        ),
        "high_pass_cutoff": _first_present_from_mappings(
            review_context_sources,
            "high_pass_cutoff",
            "high_pass",
        ),
        "autocorrelation_model": _first_present_from_mappings(
            review_context_sources,
            "autocorrelation_model",
            "noise_model",
            "autocorrelation_correction",
        ),
        "serial_correlation_correction": _first_present_from_mappings(
            review_context_sources,
            "serial_correlation_correction",
            "serial_correlation_model",
            "serial_correlation_method",
            "serial_autocorrelation_correction",
        ),
        "prewhitening_method": _first_present_from_mappings(
            review_context_sources,
            "prewhitening_method",
            "prewhitening",
        ),
        "prewhitening_enabled": _first_present_from_mappings(
            review_context_sources,
            "prewhitening_enabled",
            "prewhiten_yn",
            "film_prewhitening",
        ),
        "tr": _first_present_from_mappings(review_context_sources, "tr", "t_r"),
    }


def _review_contract(
    adapter_name: str,
    source_kind: str,
    *,
    scientific_completeness_checks: list[str] | None = None,
    scientific_review_profile: str | None = None,
    review_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "schema_version": "external-review-contract-v1",
        "contract_mode": "external_review_bundle",
        "adapter_name": adapter_name,
        "source_kind": source_kind,
        "required_root_artifacts": [
            "run.json",
            "provenance.json",
            "observation.json",
            "analysis_bundle.json",
        ],
        "recommended_root_artifacts": [
            "artifact_manifest.json",
            "source_summary.json",
            "extraction_report.json",
            "trace.jsonl",
        ],
    }
    if scientific_completeness_checks:
        payload["scientific_completeness_checks"] = scientific_completeness_checks
    if scientific_review_profile:
        payload["scientific_review_profile"] = scientific_review_profile
    payload["review_context"] = review_context or _review_context()
    return payload


def _prefixed_adapter_payload(
    *,
    adapter_name: str,
    source_kind: str,
    tool_id: str,
    task: str | None,
    contrast_name: str | None,
    modality: str | None,
    statistical_method: str | None,
    title: str,
    description: str,
    execution: dict[str, Any],
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    artifacts: list[dict[str, Any]],
    extra_source_files: list[dict[str, str]] | None = None,
    diagnostics_summary: dict[str, Any],
    source_summary: dict[str, Any],
    extraction_report: dict[str, Any],
    provenance_updates: dict[str, Any] | None = None,
    extra_run_record_updates: dict[str, Any] | None = None,
) -> ExternalArtifactAdapterPayload:
    review_context = _review_context(
        source_summary=source_summary,
        provenance_updates=provenance_updates,
        extra_run_record_updates=extra_run_record_updates,
    )
    extraction_report = dict(extraction_report)
    review_contract = extraction_report.get("review_contract")
    if isinstance(review_contract, dict):
        review_contract["review_context"] = review_context
    return ExternalArtifactAdapterPayload(
        adapter_name=adapter_name,
        source_kind=source_kind,
        spec_overrides={
            "tool_id": tool_id,
            "task": task,
            "contrast_name": contrast_name,
            "modality": modality,
            "statistical_method": statistical_method,
        },
        run_record_updates={
            "external_adapter": {
                "name": adapter_name,
                "source_kind": source_kind,
            },
            "review_context": review_context,
            "review_contract": _review_contract(
                adapter_name,
                source_kind,
                review_context=review_context,
            ),
            **(extra_run_record_updates or {}),
        },
        provenance_request_updates={
            "adapter_name": adapter_name,
            "source_kind": source_kind,
            "review_context": review_context,
            **(provenance_updates or {}),
        },
        run_card={
            "schema_version": "run-card-v1",
            "title": title,
            "description": description,
            "execution": execution,
            "inputs": inputs,
            "outputs": outputs,
            "tools": [{"tool_id": tool_id}],
            "parameters": {
                "task": task,
                "contrast_name": contrast_name,
                "modality": modality,
                "statistical_method": statistical_method,
            },
            "review_context": review_context,
        },
        artifacts=artifacts,
        extra_source_files=list(extra_source_files or []),
        diagnostics_summary=diagnostics_summary,
        source_summary=source_summary,
        extraction_report=extraction_report,
    )


def _top_contrast_from_candidates(
    summary: dict[str, Any],
) -> tuple[str | None, float | None]:
    explicit = _first_nonempty_string(
        summary, "contrast_name", "contrast", "contrast_label", "top_contrast"
    )
    if explicit:
        return explicit, _as_float(
            summary.get("top_contrast_score") or summary.get("score")
        )
    ranked_candidates = summary.get("ranked_candidate_ids") or []
    if not isinstance(ranked_candidates, list):
        return None, None
    for candidate in ranked_candidates:
        if not isinstance(candidate, dict):
            continue
        if str(candidate.get("candidate_type") or "") != "contrast":
            continue
        label = candidate.get("label")
        if not isinstance(label, str) or not label.strip():
            continue
        return label.strip(), _as_float(candidate.get("score"))
    return None, None


def _tribe_prediction_payload(
    source_dir: Path,
) -> ExternalArtifactAdapterPayload | None:
    run_summary = _load_json(source_dir / "run_summary.json")
    manifest_index = _load_json(source_dir / "manifest_index.json")
    if run_summary is None or manifest_index is None:
        return None

    task_ids: list[str] = []
    preferred_inputs: list[str] = []
    for task in manifest_index.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        task_id = task.get("task_id")
        if isinstance(task_id, str) and task_id.strip():
            task_ids.append(task_id.strip())
        preferred = task.get("preferred_tribe_input")
        if isinstance(preferred, str) and preferred.strip():
            preferred_inputs.append(preferred.strip())

    row_count = 0
    condition_counts: dict[str, int] = {}
    segment_counts: list[float] = []
    n_vertices: list[int] = []
    surface_spaces: set[str] = set()
    sample_item_ids: list[str] = []
    for row in _iter_jsonl(source_dir / "embedding_rows.jsonl") or []:
        row_count += 1
        condition = row.get("condition")
        if isinstance(condition, str) and condition.strip():
            condition_counts[condition.strip()] = (
                condition_counts.get(condition.strip(), 0) + 1
            )
        item_id = row.get("item_id")
        if isinstance(item_id, str) and len(sample_item_ids) < 5:
            sample_item_ids.append(item_id)
        seg = _as_float(row.get("segment_count"))
        if seg is not None:
            segment_counts.append(seg)
        vertices = _as_int(row.get("n_vertices"))
        if vertices is not None:
            n_vertices.append(vertices)
        surface_space = row.get("surface_space")
        if isinstance(surface_space, str) and surface_space.strip():
            surface_spaces.add(surface_space.strip())

    wave = _first_nonempty_string(manifest_index, "wave")
    task_label = _infer_task_label(wave, task_ids, source_dir.name)
    n_success = _as_int(run_summary.get("n_success")) or row_count or 0
    n_failures = _as_int(run_summary.get("n_failures")) or 0
    total = n_success + n_failures
    failure_rate = (n_failures / total) if total > 0 else 0.0
    dominant_vertices = (
        max(set(n_vertices), key=n_vertices.count) if n_vertices else None
    )
    dominant_surface = sorted(surface_spaces)[0] if surface_spaces else None
    segment_mean = round(fmean(segment_counts), 3) if segment_counts else None
    review_context_sources = (run_summary, manifest_index)

    source_summary = {
        "schema_version": "external-source-summary-v1",
        "adapter_name": "tribe_prediction",
        "source_kind": "tribe_prediction",
        "source_dir": str(source_dir),
        "wave": wave,
        "task_label": task_label,
        "task_ids": task_ids,
        "preferred_tribe_inputs": sorted(set(preferred_inputs)),
        "n_items": row_count or n_success,
        "n_success": n_success,
        "n_failures": n_failures,
        "failure_rate": round(failure_rate, 4),
        "condition_counts": condition_counts,
        "mean_segment_count": segment_mean,
        "n_vertices": dominant_vertices,
        "surface_space": dominant_surface,
        "split_unit": _first_nonempty_string_from_mappings(
            review_context_sources, "split_unit", "cv_unit"
        ),
        "split_strategy": _first_nonempty_string_from_mappings(
            review_context_sources,
            "split_strategy",
            "split_strategy_detail",
            "evaluation_strategy",
            "evaluation_protocol",
            "cross_validation",
        ),
        "grouped_split_keys": _first_present_from_mappings(
            review_context_sources,
            "grouped_split_keys",
            "group_keys",
            "split_keys",
        ),
        "required_group_keys": _first_present_from_mappings(
            review_context_sources,
            "required_group_keys",
            "required_grouping_keys",
            "grouping_required_keys",
            "mandatory_group_keys",
            "required_split_groups",
        ),
        "grouping_required": _first_present_from_mappings(
            review_context_sources, "grouping_required"
        ),
        "selection_on_test": _first_present_from_mappings(
            review_context_sources,
            "selection_on_test",
            "selected_on_test",
            "winner_selected_on_test",
            "heldout_selection",
            "held_out_selection",
            "test_set_selection",
        ),
        "selection_scope": _first_nonempty_string_from_mappings(
            review_context_sources, "selection_scope", "selection_phase"
        ),
        "winner_selection_scope": _first_nonempty_string_from_mappings(
            review_context_sources,
            "winner_selection_scope",
            "winner_selection_phase",
        ),
        "best_candidate": _first_present_from_mappings(
            review_context_sources,
            "best_candidate",
            "selected_candidate",
            "winner_candidate",
            "winner",
        ),
        "best_model": _first_present_from_mappings(
            review_context_sources,
            "best_model",
            "selected_model",
            "winner_model",
            "top_model",
        ),
        "best_layer": _first_present_from_mappings(
            review_context_sources,
            "best_layer",
            "selected_layer",
            "winner_layer",
            "top_layer",
        ),
        "best_roi": _first_present_from_mappings(
            review_context_sources,
            "best_roi",
            "selected_roi",
            "winner_roi",
            "top_roi",
        ),
        "best_prompt": _first_present_from_mappings(
            review_context_sources,
            "best_prompt",
            "selected_prompt",
            "winner_prompt",
            "top_prompt",
        ),
        "model_candidates": _first_present_from_mappings(
            review_context_sources,
            "model_candidates",
            "candidate_models",
            "models",
            "model_grid",
        ),
        "layer_candidates": _first_present_from_mappings(
            review_context_sources,
            "layer_candidates",
            "candidate_layers",
            "layers",
            "layer_grid",
        ),
        "roi_candidates": _first_present_from_mappings(
            review_context_sources,
            "roi_candidates",
            "candidate_rois",
            "rois",
            "roi_grid",
        ),
        "prompt_candidates": _first_present_from_mappings(
            review_context_sources,
            "prompt_candidates",
            "candidate_prompts",
            "prompts",
            "prompt_grid",
        ),
        "candidate_count": _first_present_from_mappings(
            review_context_sources,
            "candidate_count",
            "n_candidates",
            "search_space_size",
        ),
        "n_models": _first_present_from_mappings(
            review_context_sources,
            "n_models",
            "model_count",
            "candidate_model_count",
        ),
        "n_layers": _first_present_from_mappings(
            review_context_sources,
            "n_layers",
            "layer_count",
            "candidate_layer_count",
        ),
        "n_rois": _first_present_from_mappings(
            review_context_sources,
            "n_rois",
            "roi_count",
            "candidate_roi_count",
        ),
        "n_prompts": _first_present_from_mappings(
            review_context_sources,
            "n_prompts",
            "prompt_count",
            "candidate_prompt_count",
        ),
        "selection_accounting": _first_present_from_mappings(
            review_context_sources, "selection_accounting"
        ),
        "multiplicity_accounting": _first_present_from_mappings(
            review_context_sources, "multiplicity_accounting"
        ),
        "multiple_comparison_correction": _first_present_from_mappings(
            review_context_sources,
            "multiple_comparison_correction",
            "multiple_testing_correction",
        ),
        "winner_selection_method": _first_present_from_mappings(
            review_context_sources, "winner_selection_method"
        ),
        "winner_selection_criterion": _first_present_from_mappings(
            review_context_sources, "winner_selection_criterion"
        ),
        "winner_selection_protocol": _first_present_from_mappings(
            review_context_sources, "winner_selection_protocol"
        ),
        "nested_cv": _first_present_from_mappings(review_context_sources, "nested_cv"),
        "selection_holdout": _first_present_from_mappings(
            review_context_sources, "selection_holdout"
        ),
        "independent_validation": _first_present_from_mappings(
            review_context_sources, "independent_validation"
        ),
        **_source_statistical_inference_fields(review_context_sources),
        **_source_design_model_fields(review_context_sources),
        "checkpoint_dir": run_summary.get("checkpoint_dir"),
        "checkpoint_name": run_summary.get("checkpoint_name"),
        "device": run_summary.get("device"),
        "analysis_command": run_summary.get("analysis_command"),
        "sample_item_ids": sample_item_ids,
    }
    extraction_report = {
        "schema_version": "external-extraction-report-v1",
        "adapter_name": "tribe_prediction",
        "source_kind": "tribe_prediction",
        "inferred_fields": [
            {
                "field": "tool_id",
                "value": "tribe_predict",
                "confidence": "high",
                "evidence_path": "run_summary.json",
            },
            {
                "field": "task",
                "value": task_label,
                "confidence": "medium" if task_label else "low",
                "evidence_path": "manifest_index.json",
            },
            {
                "field": "modality",
                "value": "fmri",
                "confidence": "medium",
                "evidence_path": "embedding_rows.jsonl",
            },
            {
                "field": "statistical_method",
                "value": "neural_encoding_prediction",
                "confidence": "medium",
                "evidence_path": "run_summary.json",
            },
        ],
        "indexed_artifacts": _collect_generic_indexed_files(
            source_dir,
            "run_summary.json",
            "manifest_index.json",
            "embedding_rows.jsonl",
            "failures.jsonl",
            "embeddings_matrix.npy",
        ),
        "review_contract": _review_contract("tribe_prediction", "tribe_prediction"),
    }

    return _prefixed_adapter_payload(
        adapter_name="tribe_prediction",
        source_kind="tribe_prediction",
        tool_id="tribe_predict",
        task=task_label,
        contrast_name=None,
        modality="fmri",
        statistical_method="neural_encoding_prediction",
        title=f"TRIBE prediction import: {wave or source_dir.name}",
        description=f"Imported TRIBE prediction artifacts with {n_success} successful items and {n_failures} failures.",
        execution={
            "source_kind": "tribe_prediction",
            "device": run_summary.get("device"),
            "checkpoint_dir": run_summary.get("checkpoint_dir"),
            "checkpoint_name": run_summary.get("checkpoint_name"),
            "n_success": n_success,
            "n_failures": n_failures,
        },
        inputs={
            "wave": wave,
            "task_ids": task_ids,
            "preferred_tribe_inputs": sorted(set(preferred_inputs)),
        },
        outputs={
            "surface_space": dominant_surface,
            "n_vertices": dominant_vertices,
            "n_items": row_count or n_success,
            "condition_counts": condition_counts,
        },
        artifacts=[
            _artifact("artifacts/source/run_summary.json", "tribe_run_summary"),
            _artifact("artifacts/source/manifest_index.json", "tribe_manifest_index"),
            _artifact("artifacts/source/embedding_rows.jsonl", "tribe_embedding_rows"),
            _artifact("artifacts/source/failures.jsonl", "tribe_failures"),
            _artifact(
                "artifacts/source/embeddings_matrix.npy", "tribe_embedding_matrix"
            ),
            _artifact("source_summary.json", "external_source_summary"),
            _artifact("extraction_report.json", "external_extraction_report"),
        ],
        diagnostics_summary={
            "adapter_name": "tribe_prediction",
            "source_kind": "tribe_prediction",
            "n_items": row_count or n_success,
            "n_success": n_success,
            "n_failures": n_failures,
            "failure_rate": round(failure_rate, 4),
            "task_ids": task_ids,
            "condition_counts": condition_counts,
            "mean_segment_count": segment_mean,
            "surface_space": dominant_surface,
            "n_vertices": dominant_vertices,
        },
        source_summary=source_summary,
        extraction_report=extraction_report,
        provenance_updates={
            "wave": wave,
            "task_ids": task_ids,
            "checkpoint_dir": run_summary.get("checkpoint_dir"),
            "checkpoint_name": run_summary.get("checkpoint_name"),
        },
        extra_run_record_updates={
            "external_adapter": {
                "name": "tribe_prediction",
                "source_kind": "tribe_prediction",
                "wave": wave,
            }
        },
    )


def _tribe_analysis_payload(source_dir: Path) -> ExternalArtifactAdapterPayload | None:
    summary = _load_json(source_dir / "summary.json")
    if summary is None or "embedding_shape" not in summary:
        return None

    source_run_summary = summary.get("source_run_summary")
    source_run_summary = (
        source_run_summary if isinstance(source_run_summary, dict) else {}
    )
    source_task_ids = sorted(
        str(key)
        for key in (
            source_run_summary.get("per_task_requested_item_count") or {}
        ).keys()
        if str(key).strip()
    )
    task_label = _infer_task_label(
        source_task_ids,
        summary.get("analysis_dir"),
        summary.get("run_root"),
    )
    top_contrast, top_score = _top_contrast_from_candidates(summary)

    roi_summary = _load_json(source_dir / "roi_atlas_summary.json") or {}
    pca_summary = _load_json(source_dir / "pca_summary.json") or {}
    embedding_shape = (
        summary.get("embedding_shape")
        if isinstance(summary.get("embedding_shape"), list)
        else []
    )
    n_rows = (
        _as_int(summary.get("n_rows"))
        or (embedding_shape[0] if len(embedding_shape) >= 1 else 0)
        or 0
    )
    embedding_dim = _as_int(embedding_shape[1]) if len(embedding_shape) >= 2 else None
    n_rois = _as_int(roi_summary.get("n_rois"))
    top_pca_var = None
    if isinstance(pca_summary.get("explained_variance_ratio"), list):
        top_pca_var = _as_float(
            (pca_summary.get("explained_variance_ratio") or [None])[0]
        )

    source_summary = {
        "schema_version": "external-source-summary-v1",
        "adapter_name": "tribe_embedding_analysis",
        "source_kind": "tribe_analysis",
        "source_dir": str(source_dir),
        "task_label": task_label,
        "task_ids": source_task_ids,
        "top_contrast": top_contrast,
        "top_contrast_score": top_score,
        "n_rows": n_rows,
        "embedding_dim": embedding_dim,
        "pca_components": pca_summary.get("n_components"),
        "pca_top1_variance": top_pca_var,
        "atlas_name": roi_summary.get("atlas_name"),
        "template": roi_summary.get("template"),
        "n_rois": n_rois,
        "split_unit": _first_nonempty_string(summary, "split_unit", "cv_unit"),
        "split_strategy": _first_nonempty_string(
            summary,
            "split_strategy",
            "split_strategy_detail",
            "evaluation_strategy",
            "evaluation_protocol",
            "cross_validation",
        ),
        "grouped_split_keys": _first_present(
            summary,
            "grouped_split_keys",
            "group_keys",
            "split_keys",
        ),
        "required_group_keys": _first_present(
            summary,
            "required_group_keys",
            "required_grouping_keys",
            "grouping_required_keys",
            "mandatory_group_keys",
            "required_split_groups",
        ),
        "grouping_required": _first_present(summary, "grouping_required"),
        "selection_on_test": _first_present(
            summary,
            "selection_on_test",
            "selected_on_test",
            "winner_selected_on_test",
            "heldout_selection",
            "held_out_selection",
            "test_set_selection",
        ),
        "selection_scope": _first_nonempty_string(
            summary, "selection_scope", "selection_phase"
        ),
        "winner_selection_scope": _first_nonempty_string(
            summary, "winner_selection_scope", "winner_selection_phase"
        ),
        "best_candidate": _first_present(
            summary,
            "best_candidate",
            "selected_candidate",
            "winner_candidate",
            "winner",
        ),
        "best_model": _first_present(
            summary,
            "best_model",
            "selected_model",
            "winner_model",
            "top_model",
        ),
        "best_layer": _first_present(
            summary,
            "best_layer",
            "selected_layer",
            "winner_layer",
            "top_layer",
        ),
        "best_roi": _first_present(
            summary,
            "best_roi",
            "selected_roi",
            "winner_roi",
            "top_roi",
        ),
        "best_prompt": _first_present(
            summary,
            "best_prompt",
            "selected_prompt",
            "winner_prompt",
            "top_prompt",
        ),
        "model_candidates": _first_present(
            summary,
            "model_candidates",
            "candidate_models",
            "models",
            "model_grid",
        ),
        "layer_candidates": _first_present(
            summary,
            "layer_candidates",
            "candidate_layers",
            "layers",
            "layer_grid",
        ),
        "roi_candidates": _first_present(
            summary,
            "roi_candidates",
            "candidate_rois",
            "rois",
            "roi_grid",
        ),
        "prompt_candidates": _first_present(
            summary,
            "prompt_candidates",
            "candidate_prompts",
            "prompts",
            "prompt_grid",
        ),
        "candidate_count": _first_present(
            summary,
            "candidate_count",
            "n_candidates",
            "search_space_size",
        ),
        "selection_accounting": _first_present(summary, "selection_accounting"),
        "multiplicity_accounting": _first_present(summary, "multiplicity_accounting"),
        "multiple_comparison_correction": _first_present(
            summary,
            "multiple_comparison_correction",
            "multiple_testing_correction",
        ),
        "winner_selection_method": _first_present(summary, "winner_selection_method"),
        "winner_selection_criterion": _first_present(
            summary, "winner_selection_criterion"
        ),
        "winner_selection_protocol": _first_present(
            summary, "winner_selection_protocol"
        ),
        "nested_cv": _first_present(summary, "nested_cv"),
        "selection_holdout": _first_present(summary, "selection_holdout"),
        "independent_validation": _first_present(summary, "independent_validation"),
        **_source_statistical_inference_fields((summary,)),
        **_source_design_model_fields((summary,)),
        "n_contrast_findings": summary.get("n_contrast_findings"),
        "n_cross_task_findings": summary.get("n_cross_task_findings"),
        "n_nearest_neighbor_findings": summary.get("n_nearest_neighbor_findings"),
        "n_kg_followups": summary.get("n_kg_followups"),
        "source_run_root": summary.get("run_root"),
    }
    extraction_report = {
        "schema_version": "external-extraction-report-v1",
        "adapter_name": "tribe_embedding_analysis",
        "source_kind": "tribe_analysis",
        "inferred_fields": [
            {
                "field": "tool_id",
                "value": "embedding_autoresearch",
                "confidence": "high",
                "evidence_path": "summary.json",
            },
            {
                "field": "task",
                "value": task_label,
                "confidence": "medium" if task_label else "low",
                "evidence_path": "summary.json",
            },
            {
                "field": "contrast_name",
                "value": top_contrast,
                "confidence": "medium" if top_contrast else "low",
                "evidence_path": "summary.json",
            },
            {
                "field": "statistical_method",
                "value": "embedding_autoresearch",
                "confidence": "high",
                "evidence_path": "summary.json",
            },
        ],
        "indexed_artifacts": _collect_generic_indexed_files(
            source_dir,
            "summary.json",
            "pca_summary.json",
            "roi_atlas_summary.json",
            "ranked_candidates.jsonl",
            "contrast_findings.jsonl",
        ),
        "review_contract": _review_contract(
            "tribe_embedding_analysis", "tribe_analysis"
        ),
    }

    return _prefixed_adapter_payload(
        adapter_name="tribe_embedding_analysis",
        source_kind="tribe_analysis",
        tool_id="embedding_autoresearch",
        task=task_label,
        contrast_name=top_contrast,
        modality="fmri",
        statistical_method="embedding_autoresearch",
        title=f"TRIBE embedding analysis import: {source_dir.name}",
        description=f"Imported embedding analysis artifacts with {n_rows} rows and {summary.get('n_contrast_findings') or 0} contrast findings.",
        execution={
            "source_kind": "tribe_analysis",
            "analysis_dir": summary.get("analysis_dir"),
            "source_run_root": summary.get("run_root"),
        },
        inputs={"task_ids": source_task_ids, "task": task_label},
        outputs={
            "top_contrast": top_contrast,
            "top_contrast_score": top_score,
            "n_rows": n_rows,
            "embedding_dim": embedding_dim,
            "atlas_name": roi_summary.get("atlas_name"),
            "n_rois": n_rois,
        },
        artifacts=[
            _artifact("artifacts/source/summary.json", "tribe_analysis_summary"),
            _artifact("artifacts/source/pca_summary.json", "tribe_pca_summary"),
            _artifact(
                "artifacts/source/roi_atlas_summary.json", "tribe_roi_atlas_summary"
            ),
            _artifact(
                "artifacts/source/ranked_candidates.jsonl", "tribe_ranked_candidates"
            ),
            _artifact(
                "artifacts/source/contrast_findings.jsonl", "tribe_contrast_findings"
            ),
            _artifact("source_summary.json", "external_source_summary"),
            _artifact("extraction_report.json", "external_extraction_report"),
        ],
        diagnostics_summary={
            "adapter_name": "tribe_embedding_analysis",
            "source_kind": "tribe_analysis",
            "n_rows": n_rows,
            "embedding_dim": embedding_dim,
            "top_contrast": top_contrast,
            "top_contrast_score": top_score,
            "pca_top1_variance": top_pca_var,
            "n_rois": n_rois,
            "n_contrast_findings": summary.get("n_contrast_findings"),
            "n_cross_task_findings": summary.get("n_cross_task_findings"),
        },
        source_summary=source_summary,
        extraction_report=extraction_report,
        provenance_updates={
            "source_run_root": summary.get("run_root"),
            "task_ids": source_task_ids,
            "top_contrast": top_contrast,
        },
    )


def _generic_prediction_summary_payload(
    source_dir: Path,
) -> ExternalArtifactAdapterPayload | None:
    run_summary, evidence_name, artifact_rel = _source_primary_json(
        source_dir, "run_summary.json"
    )
    if run_summary is None or evidence_name is None or artifact_rel is None:
        return None
    if source_dir.is_file() and not any(
        key in run_summary
        for key in (
            "n_success",
            "n_failures",
            "n_items",
            "per_task_requested_item_count",
        )
    ):
        return None

    n_success = _as_int(run_summary.get("n_success"))
    n_failures = _as_int(run_summary.get("n_failures")) or 0
    n_items = _as_int(run_summary.get("n_items")) or _as_int(run_summary.get("n_rows"))
    if n_success is not None:
        n_items = n_items or (n_success + n_failures)
    task = _infer_task_label(
        run_summary,
        _first_nonempty_string(run_summary, "task", "task_label", "paradigm"),
        source_dir.name,
    )
    modality = _first_nonempty_string(run_summary, "modality")
    if modality is None and any(
        key in run_summary for key in ("surface_space", "embedding_matrix_path")
    ):
        modality = "fmri"
    tool_id = (
        _first_nonempty_string(run_summary, "tool_id") or "external_prediction_summary"
    )
    method = (
        _first_nonempty_string(
            run_summary, "statistical_method", "analysis_method", "method"
        )
        or tool_id
    )
    total = n_items or (n_success + n_failures if n_success is not None else None) or 0
    failure_rate = (n_failures / total) if total else None
    review_context_sources = (run_summary,)

    source_summary = {
        "schema_version": "external-source-summary-v1",
        "adapter_name": "generic_prediction_summary",
        "source_kind": "generic_prediction_summary",
        "source_dir": str(source_dir),
        "task_label": task,
        "n_items": n_items,
        "n_success": n_success,
        "n_failures": n_failures,
        "failure_rate": round(failure_rate, 4) if failure_rate is not None else None,
        "tool_id": tool_id,
        "modality": modality,
        "statistical_method": method,
        "split_unit": _first_nonempty_string_from_mappings(
            review_context_sources, "split_unit", "cv_unit"
        ),
        "split_strategy": _first_nonempty_string_from_mappings(
            review_context_sources,
            "split_strategy",
            "split_strategy_detail",
            "evaluation_strategy",
            "evaluation_protocol",
            "cross_validation",
        ),
        "grouped_split_keys": _first_present_from_mappings(
            review_context_sources,
            "grouped_split_keys",
            "group_keys",
            "split_keys",
        ),
        "required_group_keys": _first_present_from_mappings(
            review_context_sources,
            "required_group_keys",
            "required_grouping_keys",
            "grouping_required_keys",
            "mandatory_group_keys",
            "required_split_groups",
        ),
        "grouping_required": _first_present_from_mappings(
            review_context_sources, "grouping_required"
        ),
        "selection_on_test": _first_present_from_mappings(
            review_context_sources,
            "selection_on_test",
            "selected_on_test",
            "winner_selected_on_test",
            "heldout_selection",
            "held_out_selection",
            "test_set_selection",
        ),
        "selection_scope": _first_nonempty_string_from_mappings(
            review_context_sources, "selection_scope", "selection_phase"
        ),
        "winner_selection_scope": _first_nonempty_string_from_mappings(
            review_context_sources,
            "winner_selection_scope",
            "winner_selection_phase",
        ),
        "best_candidate": _first_present_from_mappings(
            review_context_sources,
            "best_candidate",
            "selected_candidate",
            "winner_candidate",
            "winner",
        ),
        "best_model": _first_present_from_mappings(
            review_context_sources,
            "best_model",
            "selected_model",
            "winner_model",
            "top_model",
        ),
        "best_layer": _first_present_from_mappings(
            review_context_sources,
            "best_layer",
            "selected_layer",
            "winner_layer",
            "top_layer",
        ),
        "best_roi": _first_present_from_mappings(
            review_context_sources,
            "best_roi",
            "selected_roi",
            "winner_roi",
            "top_roi",
        ),
        "best_prompt": _first_present_from_mappings(
            review_context_sources,
            "best_prompt",
            "selected_prompt",
            "winner_prompt",
            "top_prompt",
        ),
        "model_candidates": _first_present_from_mappings(
            review_context_sources,
            "model_candidates",
            "candidate_models",
            "models",
            "model_grid",
        ),
        "layer_candidates": _first_present_from_mappings(
            review_context_sources,
            "layer_candidates",
            "candidate_layers",
            "layers",
            "layer_grid",
        ),
        "roi_candidates": _first_present_from_mappings(
            review_context_sources,
            "roi_candidates",
            "candidate_rois",
            "rois",
            "roi_grid",
        ),
        "prompt_candidates": _first_present_from_mappings(
            review_context_sources,
            "prompt_candidates",
            "candidate_prompts",
            "prompts",
            "prompt_grid",
        ),
        "candidate_count": _first_present_from_mappings(
            review_context_sources,
            "candidate_count",
            "n_candidates",
            "search_space_size",
        ),
        "n_models": _first_present_from_mappings(
            review_context_sources,
            "n_models",
            "model_count",
            "candidate_model_count",
        ),
        "n_layers": _first_present_from_mappings(
            review_context_sources,
            "n_layers",
            "layer_count",
            "candidate_layer_count",
        ),
        "n_rois": _first_present_from_mappings(
            review_context_sources,
            "n_rois",
            "roi_count",
            "candidate_roi_count",
        ),
        "n_prompts": _first_present_from_mappings(
            review_context_sources,
            "n_prompts",
            "prompt_count",
            "candidate_prompt_count",
        ),
        "selection_accounting": _first_present_from_mappings(
            review_context_sources, "selection_accounting"
        ),
        "multiplicity_accounting": _first_present_from_mappings(
            review_context_sources, "multiplicity_accounting"
        ),
        "multiple_comparison_correction": _first_present_from_mappings(
            review_context_sources,
            "multiple_comparison_correction",
            "multiple_testing_correction",
        ),
        "winner_selection_method": _first_present_from_mappings(
            review_context_sources, "winner_selection_method"
        ),
        "winner_selection_criterion": _first_present_from_mappings(
            review_context_sources, "winner_selection_criterion"
        ),
        "winner_selection_protocol": _first_present_from_mappings(
            review_context_sources, "winner_selection_protocol"
        ),
        "nested_cv": _first_present_from_mappings(review_context_sources, "nested_cv"),
        "selection_holdout": _first_present_from_mappings(
            review_context_sources, "selection_holdout"
        ),
        "independent_validation": _first_present_from_mappings(
            review_context_sources, "independent_validation"
        ),
        **_source_statistical_inference_fields(review_context_sources),
        **_source_design_model_fields(review_context_sources),
        "summary_fields": sorted(run_summary.keys()),
    }
    extraction_report = {
        "schema_version": "external-extraction-report-v1",
        "adapter_name": "generic_prediction_summary",
        "source_kind": "generic_prediction_summary",
        "inferred_fields": [
            {
                "field": "tool_id",
                "value": tool_id,
                "confidence": "medium",
                "evidence_path": evidence_name,
            },
            {
                "field": "task",
                "value": task,
                "confidence": "medium" if task else "low",
                "evidence_path": evidence_name,
            },
            {
                "field": "modality",
                "value": modality,
                "confidence": "low" if modality is None else "medium",
                "evidence_path": evidence_name,
            },
            {
                "field": "statistical_method",
                "value": method,
                "confidence": "medium",
                "evidence_path": evidence_name,
            },
        ],
        "indexed_artifacts": _collect_generic_indexed_files(
            source_dir, "run_summary.json"
        ),
        "review_contract": _review_contract(
            "generic_prediction_summary", "generic_prediction_summary"
        ),
    }
    return _prefixed_adapter_payload(
        adapter_name="generic_prediction_summary",
        source_kind="generic_prediction_summary",
        tool_id=tool_id,
        task=task,
        contrast_name=None,
        modality=modality,
        statistical_method=method,
        title=f"External prediction import: {source_dir.name}",
        description=f"Imported external prediction summary from {source_dir.name}.",
        execution={
            "source_kind": "generic_prediction_summary",
            "tool_id": tool_id,
        },
        inputs={"task": task},
        outputs={"n_items": n_items, "n_success": n_success, "n_failures": n_failures},
        artifacts=[
            _artifact(artifact_rel, "external_run_summary"),
            _artifact("source_summary.json", "external_source_summary"),
            _artifact("extraction_report.json", "external_extraction_report"),
        ],
        diagnostics_summary={
            "adapter_name": "generic_prediction_summary",
            "source_kind": "generic_prediction_summary",
            "n_items": n_items,
            "n_success": n_success,
            "n_failures": n_failures,
            "failure_rate": (
                round(failure_rate, 4) if failure_rate is not None else None
            ),
        },
        source_summary=source_summary,
        extraction_report=extraction_report,
    )


def _fitlins_multiverse_payload(
    source_dir: Path,
) -> ExternalArtifactAdapterPayload | None:
    paths = _fitlins_multiverse_paths(source_dir)
    if paths is None:
        return None

    run_manifest = (
        _load_json(paths["run_manifest"]) if paths["run_manifest"] is not None else None
    )
    spec_manifest = (
        _load_json(paths["spec_manifest"])
        if paths["spec_manifest"] is not None
        else None
    )
    robustness_payload = (
        _load_json(paths["robustness_json"])
        if paths["robustness_json"] is not None
        else None
    )
    variants = _fitlins_multiverse_variants(
        run_manifest,
        spec_manifest,
        robustness_payload,
    )
    if not variants and not any(
        path is not None
        for field_name, path in paths.items()
        if field_name
        in {"run_manifest", "spec_manifest", "summary_csv", "robustness_json"}
    ):
        return None

    summary_stats = _fitlins_multiverse_summary_stats(paths["summary_csv"])
    robustness_stats = _fitlins_multiverse_robustness_stats(robustness_payload)
    raw_task = _first_nonempty_string(run_manifest, "task") or _first_nonempty_string(
        spec_manifest, "task"
    )
    task = raw_task or _infer_task_label(source_dir.name)
    dataset_id = _first_nonempty_string(
        run_manifest, "dataset_id", "study_id"
    ) or _first_nonempty_string(spec_manifest, "dataset_id", "study_id")
    source_run_id = _first_nonempty_string(run_manifest, "run_id")
    n_variants = len(variants) or _as_int(
        run_manifest.get("k") if isinstance(run_manifest, dict) else None
    )
    model_candidates = _stable_unique(variant.get("model_id") for variant in variants)
    candidate_variants = _stable_unique(
        variant.get("variant_id") or variant.get("model_id") for variant in variants
    )
    hrf_levels = _stable_unique(variant.get("hrf") for variant in variants)
    hrf_basis_levels = _stable_unique(variant.get("hrf_basis") for variant in variants)
    confounds_levels = _stable_unique(variant.get("confounds") for variant in variants)
    high_pass_levels = _stable_unique(variant.get("high_pass") for variant in variants)
    controversial_choices, sensitivity_requirements = (
        _fitlins_multiverse_sensitivity_package(
            variants,
            has_robustness_summary=bool(robustness_stats["robustness_checks"]),
        )
    )
    top_contrast = robustness_stats["top_contrast"] or summary_stats["top_contrast"]
    top_contrast_score = robustness_stats["top_contrast_score"]

    source_summary = {
        "schema_version": "external-source-summary-v1",
        "adapter_name": "fitlins_multiverse",
        "source_kind": "fitlins_multiverse",
        "source_dir": str(source_dir),
        "task_label": task,
        "task": raw_task or task,
        "dataset_id": dataset_id,
        "source_run_id": source_run_id,
        "tool_id": "fitlins_multiverse_external",
        "modality": "fmri",
        "statistical_method": "fitlins_multiverse",
        "analysis_level": _first_nonempty_string(run_manifest, "analysis_level"),
        "runtime": _first_nonempty_string(run_manifest, "runtime"),
        "execute": (
            run_manifest.get("execute") if isinstance(run_manifest, dict) else None
        ),
        "seed": _as_int(
            run_manifest.get("seed") if isinstance(run_manifest, dict) else None
        ),
        "n_items": n_variants,
        "n_variants": n_variants,
        "candidate_count": n_variants,
        "n_models": len(model_candidates),
        "model_candidates": model_candidates,
        "candidates": candidate_variants,
        "n_rows": summary_stats["n_rows"],
        "n_contrasts": summary_stats["n_contrasts"],
        "contrast_names": summary_stats["contrast_names"],
        "n_rois": summary_stats["n_rois"],
        "top_contrast": top_contrast,
        "top_contrast_score": top_contrast_score,
        "selection_accounting": (
            {
                "selection_origin": "precomputed_multiverse_variants",
                "variant_count": n_variants,
            }
            if n_variants
            else None
        ),
        "best_candidate": top_contrast,
        "hrf_model": hrf_levels[0] if len(hrf_levels) == 1 else None,
        "basis_set": hrf_basis_levels[0] if len(hrf_basis_levels) == 1 else None,
        "high_pass": high_pass_levels[0] if len(high_pass_levels) == 1 else None,
        "confounds": (
            confounds_levels[0] if len(confounds_levels) == 1 else confounds_levels
        ),
        "multiverse_axes": {
            "hrf": hrf_levels,
            "hrf_basis": hrf_basis_levels,
            "confounds": confounds_levels,
            "high_pass": high_pass_levels,
        },
        "controversial_choices": controversial_choices,
        "sensitivity_requirements": sensitivity_requirements,
        "robustness_checks": robustness_stats["robustness_checks"],
        "run_manifest_path": (
            paths["run_manifest"].name if paths["run_manifest"] is not None else None
        ),
        "spec_manifest_path": (
            paths["spec_manifest"].relative_to(source_dir).as_posix()
            if paths["spec_manifest"] is not None
            else None
        ),
        "yeo17_summary_path": (
            paths["summary_csv"].relative_to(source_dir).as_posix()
            if paths["summary_csv"] is not None
            else None
        ),
        "robustness_json_path": (
            paths["robustness_json"].relative_to(source_dir).as_posix()
            if paths["robustness_json"] is not None
            else None
        ),
        "robustness_markdown_path": (
            paths["robustness_md"].relative_to(source_dir).as_posix()
            if paths["robustness_md"] is not None
            else None
        ),
    }
    review_contract = _review_contract(
        "fitlins_multiverse",
        "fitlins_multiverse",
        scientific_completeness_checks=[
            "random_seed_pinned",
            "atlas_version_pinned",
            "sensitivity_package_declared",
        ],
    )
    artifacts: list[dict[str, Any]] = []
    for field_name, role in (
        ("run_manifest", "external_fitlins_multiverse_run_manifest"),
        ("spec_manifest", "external_fitlins_multiverse_spec_manifest"),
        ("summary_csv", "external_fitlins_multiverse_yeo17_summary"),
        ("robustness_json", "external_fitlins_multiverse_robustness_json"),
        ("robustness_md", "external_fitlins_multiverse_robustness_markdown"),
    ):
        path = paths[field_name]
        if path is None:
            continue
        artifacts.append(_artifact(_source_artifact_rel(source_dir, path), role))
    artifacts.extend(
        [
            _artifact("source_summary.json", "external_source_summary"),
            _artifact("extraction_report.json", "external_extraction_report"),
        ]
    )
    extraction_report = {
        "schema_version": "external-extraction-report-v1",
        "adapter_name": "fitlins_multiverse",
        "source_kind": "fitlins_multiverse",
        "inferred_fields": [
            {
                "field": "tool_id",
                "value": "fitlins_multiverse_external",
                "confidence": "high",
                "evidence_path": (
                    paths["run_manifest"].name
                    if paths["run_manifest"] is not None
                    else (
                        paths["spec_manifest"].relative_to(source_dir).as_posix()
                        if paths["spec_manifest"] is not None
                        else source_dir.name
                    )
                ),
            },
            {
                "field": "task",
                "value": task,
                "confidence": "high" if raw_task else "medium",
                "evidence_path": (
                    paths["run_manifest"].name
                    if raw_task and paths["run_manifest"] is not None
                    else (
                        paths["spec_manifest"].relative_to(source_dir).as_posix()
                        if raw_task and paths["spec_manifest"] is not None
                        else source_dir.name
                    )
                ),
            },
            {
                "field": "contrast_name",
                "value": top_contrast,
                "confidence": "medium" if top_contrast else "low",
                "evidence_path": (
                    paths["robustness_json"].relative_to(source_dir).as_posix()
                    if top_contrast and paths["robustness_json"] is not None
                    else (
                        paths["summary_csv"].relative_to(source_dir).as_posix()
                        if top_contrast and paths["summary_csv"] is not None
                        else None
                    )
                ),
            },
            {
                "field": "statistical_method",
                "value": "fitlins_multiverse",
                "confidence": "high",
                "evidence_path": (
                    paths["run_manifest"].name
                    if paths["run_manifest"] is not None
                    else source_dir.name
                ),
            },
            {
                "field": "n_variants",
                "value": n_variants,
                "confidence": "high" if n_variants else "low",
                "evidence_path": (
                    paths["run_manifest"].name
                    if paths["run_manifest"] is not None
                    else (
                        paths["spec_manifest"].relative_to(source_dir).as_posix()
                        if paths["spec_manifest"] is not None
                        else None
                    )
                ),
            },
        ],
        "indexed_artifacts": [
            path.relative_to(source_dir).as_posix()
            for path in (
                paths["run_manifest"],
                paths["spec_manifest"],
                paths["summary_csv"],
                paths["robustness_json"],
                paths["robustness_md"],
            )
            if path is not None
        ],
        "review_contract": review_contract,
    }

    return _prefixed_adapter_payload(
        adapter_name="fitlins_multiverse",
        source_kind="fitlins_multiverse",
        tool_id="fitlins_multiverse_external",
        task=task,
        contrast_name=top_contrast,
        modality="fmri",
        statistical_method="fitlins_multiverse",
        title=f"External FitLins multiverse import: {dataset_id or source_dir.name}",
        description=f"Imported external FitLins multiverse artifacts from {source_dir.name}.",
        execution={
            "source_kind": "fitlins_multiverse",
            "source_run_id": source_run_id,
            "analysis_level": source_summary["analysis_level"],
            "runtime": source_summary["runtime"],
            "execute": source_summary["execute"],
        },
        inputs={
            "dataset_id": dataset_id,
            "task": task,
        },
        outputs={
            "n_variants": n_variants,
            "n_contrasts": summary_stats["n_contrasts"],
            "n_rois": summary_stats["n_rois"],
            "top_contrast": top_contrast,
            "top_contrast_score": top_contrast_score,
        },
        artifacts=artifacts,
        diagnostics_summary={
            "adapter_name": "fitlins_multiverse",
            "source_kind": "fitlins_multiverse",
            "dataset_id": dataset_id,
            "n_variants": n_variants,
            "n_contrasts": summary_stats["n_contrasts"],
            "n_rois": summary_stats["n_rois"],
            "top_contrast": top_contrast,
            "top_contrast_score": top_contrast_score,
        },
        source_summary=source_summary,
        extraction_report=extraction_report,
        provenance_updates={
            "dataset_id": dataset_id,
            "source_run_id": source_run_id,
        },
        extra_run_record_updates={"review_contract": review_contract},
    )


def _generic_analysis_summary_payload(
    source_dir: Path,
) -> ExternalArtifactAdapterPayload | None:
    summary, evidence_name, artifact_rel = _source_primary_json(
        source_dir, "summary.json"
    )
    if summary is None or evidence_name is None or artifact_rel is None:
        return None
    if source_dir.is_file() and not any(
        key in summary
        for key in (
            "run_id",
            "fold_results",
            "embedding_shape",
            "target_column",
            "classifier",
            "n_rows",
            "n_items",
        )
    ):
        return None

    top_contrast, top_score = _top_contrast_from_candidates(summary)
    run_id = _first_nonempty_string(summary, "run_id") or (
        source_dir.stem if source_dir.is_file() else None
    )
    registry_entry, registry_path = _load_experiment_registry_entry(source_dir, run_id)
    registry_entry = registry_entry if isinstance(registry_entry, dict) else {}
    registry_config = (
        registry_entry.get("config")
        if isinstance(registry_entry.get("config"), dict)
        else {}
    )
    registry_hyperparameters = (
        registry_config.get("hyperparameters")
        if isinstance(registry_config.get("hyperparameters"), dict)
        else {}
    )
    registry_frozen_spec = (
        registry_entry.get("frozen_spec")
        if isinstance(registry_entry.get("frozen_spec"), dict)
        else {}
    )
    registry_scores = (
        registry_entry.get("scores")
        if isinstance(registry_entry.get("scores"), dict)
        else {}
    )
    registry_secondary_scores = (
        registry_scores.get("secondary_scores")
        if isinstance(registry_scores.get("secondary_scores"), dict)
        else {}
    )
    registry_data_diagnostics = (
        registry_entry.get("data_diagnostics")
        if isinstance(registry_entry.get("data_diagnostics"), dict)
        else {}
    )
    task = _infer_task_label(
        summary,
        _first_nonempty_string(summary, "task", "task_label", "paradigm"),
        _first_nonempty_string(registry_config, "target"),
        _first_nonempty_string(summary, "target_column", "target_name"),
        summary.get("run_root"),
        source_dir.name,
    )
    tool_id = _first_nonempty_string(summary, "tool_id") or "external_analysis_summary"
    method = (
        _first_nonempty_string(
            summary, "statistical_method", "analysis_method", "method", "classifier"
        )
        or tool_id
    )
    modality = _first_nonempty_string(summary, "modality")
    if modality is None and any(
        key in summary
        for key in (
            "embedding_shape",
            "surface_space",
            "atlas_name",
            "feature_strategy",
            "target_column",
            "kg_model_networks",
        )
    ):
        modality = "fmri"

    n_rows = (
        _as_int(summary.get("n_rows"))
        or _as_int(summary.get("n_items"))
        or _as_int(summary.get("reference_subject_count"))
        or _as_int(registry_secondary_scores.get("reference_subject_count"))
        or _as_int(registry_hyperparameters.get("reference_subject_count"))
        or _as_int(registry_data_diagnostics.get("subject_count"))
    )
    embedding_shape = (
        summary.get("embedding_shape")
        if isinstance(summary.get("embedding_shape"), list)
        else []
    )
    embedding_dim = _as_int(embedding_shape[1]) if len(embedding_shape) >= 2 else None
    fold_results = (
        summary.get("fold_results")
        if isinstance(summary.get("fold_results"), list)
        else []
    )
    proxy_fold_scores = [
        value
        for value in (
            _as_float(v)
            for v in (
                summary.get("proxy_fold_scores")
                if isinstance(summary.get("proxy_fold_scores"), list)
                else registry_secondary_scores.get("proxy_fold_scores") or []
            )
        )
        if value is not None
    ]
    distance_correlation_scores = [
        value
        for value in (
            _as_float(v)
            for v in (
                summary.get("distance_correlation_fold_scores")
                if isinstance(summary.get("distance_correlation_fold_scores"), list)
                else registry_secondary_scores.get("distance_correlation_fold_scores")
                or []
            )
        )
        if value is not None
    ]
    train_r2_values = [
        value
        for value in (
            _as_float(row.get("train_r2"))
            for row in fold_results
            if isinstance(row, dict)
        )
        if value is not None
    ]
    test_r2_values = [
        value
        for value in (
            _as_float(row.get("test_r2"))
            for row in fold_results
            if isinstance(row, dict)
        )
        if value is not None
    ]
    test_r_values = [
        value
        for value in (
            _as_float(row.get("test_pearson_r"))
            for row in fold_results
            if isinstance(row, dict)
        )
        if value is not None
    ]
    if not train_r2_values:
        train_r2_values = [
            value
            for value in (_as_float(v) for v in (summary.get("train_r2_scores") or []))
            if value is not None
        ]
    if not test_r2_values:
        test_r2_values = [
            value
            for value in (_as_float(v) for v in (summary.get("test_r2_scores") or []))
            if value is not None
        ]
    if not test_r_values:
        test_r_values = [
            value
            for value in (_as_float(v) for v in (summary.get("test_r_scores") or []))
            if value is not None
        ]

    mean_train_r2 = round(fmean(train_r2_values), 4) if train_r2_values else None
    mean_test_r2 = round(fmean(test_r2_values), 4) if test_r2_values else None
    mean_test_r = round(fmean(test_r_values), 4) if test_r_values else None
    proxy_mean_score = (
        _as_float(summary.get("proxy_mean_score"))
        or _as_float(registry_scores.get("gold_r"))
        or _as_float(registry_secondary_scores.get("proxy_mean_score"))
    )
    proxy_score_std = _as_float(summary.get("proxy_score_std")) or _as_float(
        registry_secondary_scores.get("proxy_score_std")
    )
    n_folds = (
        len(fold_results)
        if fold_results
        else max(
            len(train_r2_values),
            len(test_r2_values),
            len(test_r_values),
            len(proxy_fold_scores),
            len(distance_correlation_scores),
            _as_int(registry_hyperparameters.get("fold_count")) or 0,
            0,
        )
    )
    is_predictive_review = any(
        key in summary
        for key in (
            "classifier",
            "fold_results",
            "target_column",
            "target_name",
            "feature_strategy",
            "reference_subject_count",
        )
    )
    review_contract = _review_contract(
        "generic_analysis_summary",
        "generic_analysis_summary",
        scientific_review_profile=(
            "predictive_model_review"
            if is_predictive_review
            else "generic_analysis_review"
        ),
        scientific_completeness_checks=(
            [
                "random_seed_pinned",
                "target_declared",
                "evaluation_protocol_declared",
                "subject_alignment_declared",
                "split_metadata_declared",
                "null_model_declared",
                "preprocessing_choices_declared",
            ]
            if is_predictive_review
            else None
        ),
    )
    review_context_sources = (
        summary,
        registry_secondary_scores,
        registry_hyperparameters,
        registry_config,
    )
    extra_source_files: list[dict[str, str]] = []
    indexed_artifacts = _collect_generic_indexed_files(source_dir, "summary.json")
    _append_context_sidecar_file(
        source=source_dir,
        indexed_artifacts=indexed_artifacts,
        extra_source_files=extra_source_files,
        raw_path=str(registry_path) if registry_path is not None else None,
        role="external_experiment_registry",
    )
    source_summary = {
        "schema_version": "external-source-summary-v1",
        "adapter_name": "generic_analysis_summary",
        "source_kind": "generic_analysis_summary",
        "source_dir": str(source_dir),
        "task_label": task,
        "top_contrast": top_contrast,
        "top_contrast_score": top_score,
        "n_rows": n_rows,
        "embedding_dim": embedding_dim,
        "tool_id": tool_id,
        "modality": modality,
        "statistical_method": method,
        "classifier": _first_nonempty_string(summary, "classifier"),
        "target_column": _first_nonempty_string(
            summary, "target_column", "target", "target_name"
        ),
        "target_name": _first_nonempty_string(
            summary,
            "target_name",
        )
        or _first_nonempty_string(registry_config, "target"),
        "term_name": _first_nonempty_string(summary, "term_name", "feature_name"),
        "feature_strategy": _first_nonempty_string(summary, "feature_strategy")
        or _first_nonempty_string(registry_config, "feature_strategy"),
        "split_unit": _first_nonempty_string_from_mappings(
            review_context_sources, "split_unit", "cv_unit"
        ),
        "split_strategy": _first_nonempty_string_from_mappings(
            review_context_sources,
            "split_strategy",
            "split_strategy_detail",
            "evaluation_strategy",
            "evaluation_protocol",
            "cross_validation",
        ),
        "grouped_split_keys": _first_present_from_mappings(
            review_context_sources,
            "grouped_split_keys",
            "group_keys",
            "split_keys",
        ),
        "required_group_keys": _first_present_from_mappings(
            review_context_sources,
            "required_group_keys",
            "required_grouping_keys",
            "grouping_required_keys",
            "mandatory_group_keys",
            "required_split_groups",
        ),
        "grouping_required": _first_present_from_mappings(
            review_context_sources, "grouping_required"
        ),
        "confounds": _first_present(summary, "confounds"),
        "confound_strategy": _first_present(summary, "confound_strategy"),
        "confound_columns": _first_present(summary, "confound_columns"),
        "selection_on_test": _first_present_from_mappings(
            review_context_sources,
            "selection_on_test",
            "selected_on_test",
            "winner_selected_on_test",
            "heldout_selection",
            "held_out_selection",
            "test_set_selection",
        ),
        "selection_scope": _first_nonempty_string_from_mappings(
            review_context_sources, "selection_scope", "selection_phase"
        ),
        "winner_selection_scope": _first_nonempty_string_from_mappings(
            review_context_sources,
            "winner_selection_scope",
            "winner_selection_phase",
        ),
        "best_candidate": _first_present_from_mappings(
            review_context_sources,
            "best_candidate",
            "selected_candidate",
            "winner_candidate",
            "winner",
        ),
        "best_model": _first_present_from_mappings(
            review_context_sources,
            "best_model",
            "selected_model",
            "winner_model",
            "top_model",
        ),
        "best_layer": _first_present_from_mappings(
            review_context_sources,
            "best_layer",
            "selected_layer",
            "winner_layer",
            "top_layer",
        ),
        "best_roi": _first_present_from_mappings(
            review_context_sources,
            "best_roi",
            "selected_roi",
            "winner_roi",
            "top_roi",
        ),
        "best_prompt": _first_present_from_mappings(
            review_context_sources,
            "best_prompt",
            "selected_prompt",
            "winner_prompt",
            "top_prompt",
        ),
        "model_candidates": _first_present_from_mappings(
            review_context_sources,
            "model_candidates",
            "candidate_models",
            "models",
            "model_grid",
        ),
        "layer_candidates": _first_present_from_mappings(
            review_context_sources,
            "layer_candidates",
            "candidate_layers",
            "layers",
            "layer_grid",
        ),
        "roi_candidates": _first_present_from_mappings(
            review_context_sources,
            "roi_candidates",
            "candidate_rois",
            "rois",
            "roi_grid",
        ),
        "prompt_candidates": _first_present_from_mappings(
            review_context_sources,
            "prompt_candidates",
            "candidate_prompts",
            "prompts",
            "prompt_grid",
        ),
        "candidate_count": _first_present_from_mappings(
            review_context_sources,
            "candidate_count",
            "n_candidates",
            "search_space_size",
        ),
        "n_models": _first_present_from_mappings(
            review_context_sources,
            "n_models",
            "model_count",
            "candidate_model_count",
        ),
        "n_layers": _first_present_from_mappings(
            review_context_sources,
            "n_layers",
            "layer_count",
            "candidate_layer_count",
        ),
        "n_rois": _first_present_from_mappings(
            review_context_sources,
            "n_rois",
            "roi_count",
            "candidate_roi_count",
        ),
        "n_prompts": _first_present_from_mappings(
            review_context_sources,
            "n_prompts",
            "prompt_count",
            "candidate_prompt_count",
        ),
        "selection_accounting": _first_present_from_mappings(
            review_context_sources, "selection_accounting"
        ),
        "multiplicity_accounting": _first_present_from_mappings(
            review_context_sources, "multiplicity_accounting"
        ),
        "multiple_comparison_correction": _first_present_from_mappings(
            review_context_sources,
            "multiple_comparison_correction",
            "multiple_testing_correction",
        ),
        "winner_selection_method": _first_present_from_mappings(
            review_context_sources, "winner_selection_method"
        ),
        "winner_selection_criterion": _first_present_from_mappings(
            review_context_sources, "winner_selection_criterion"
        ),
        "winner_selection_protocol": _first_present_from_mappings(
            review_context_sources, "winner_selection_protocol"
        ),
        "nested_cv": _first_present_from_mappings(review_context_sources, "nested_cv"),
        "selection_holdout": _first_present_from_mappings(
            review_context_sources, "selection_holdout"
        ),
        "independent_validation": _first_present_from_mappings(
            review_context_sources, "independent_validation"
        ),
        **_source_statistical_inference_fields(review_context_sources),
        **_source_design_model_fields(review_context_sources),
        "sensitivity_requirements": _first_present(
            summary,
            "sensitivity_requirements",
            "validation_missing",
        ),
        "robustness_checks": _first_present(
            summary,
            "robustness_checks",
            "sensitivity_checks",
            "sensitivity_analysis",
            "validation_evidence",
        ),
        "behavioral_imbalance": _first_present(summary, "behavioral_imbalance"),
        "reaction_time_difference": _first_present(
            summary,
            "reaction_time_difference",
            "rt_difference",
        ),
        "accuracy_difference": _first_present(summary, "accuracy_difference"),
        "difficulty_difference": _first_present(
            summary,
            "difficulty_difference",
            "task_difficulty_difference",
        ),
        "eye_movement_difference": _first_present(
            summary,
            "eye_movement_difference",
            "eye_tracking_difference",
        ),
        "controlled_covariates": _first_present(
            summary,
            "controlled_covariates",
            "behavioral_covariates",
            "control_variables",
        ),
        "control_strategy": _first_present(
            summary,
            "control_strategy",
            "behavioral_control_strategy",
        ),
        "subject_alignment_status": _first_nonempty_string(
            summary, "subject_alignment_status"
        )
        or _first_nonempty_string(
            registry_secondary_scores,
            "subject_alignment_status",
        )
        or _first_nonempty_string(registry_hyperparameters, "subject_alignment_status"),
        "subject_intersection_manifest_path": _first_nonempty_string(
            summary, "subject_intersection_manifest_path"
        )
        or _first_nonempty_string(
            registry_hyperparameters, "subject_intersection_manifest_path"
        ),
        "subject_manifest_path": _first_nonempty_string(
            registry_frozen_spec, "subject_manifest_path"
        ),
        "fold_manifest_path": _first_nonempty_string(
            registry_frozen_spec, "fold_manifest_path"
        ),
        "target_manifest_path": _first_nonempty_string(
            registry_frozen_spec, "target_manifest_path"
        ),
        "covariate_manifest_path": _first_nonempty_string(
            registry_frozen_spec, "covariate_manifest_path"
        ),
        "data_manifest_path": _first_nonempty_string(
            registry_frozen_spec, "data_manifest_path"
        ),
        "subject_ids_file": _first_nonempty_string(
            summary,
            "subject_ids_file",
        )
        or _first_nonempty_string(registry_hyperparameters, "subject_ids_file"),
        "subject_selection_source": _first_nonempty_string(
            registry_hyperparameters, "subject_selection_source"
        ),
        "label_shuffle_seed": summary.get("label_shuffle_seed")
        or _as_int(registry_hyperparameters.get("label_shuffle_seed")),
        "permutation_test": summary.get("permutation_test"),
        "n_permutations": _as_int(summary.get("n_permutations")),
        "permutation_seed": _as_int(summary.get("permutation_seed")),
        "resampling_method": _first_nonempty_string(summary, "resampling_method"),
        "replicate_id": _first_nonempty_string(summary, "replicate_id"),
        "reference_subject_count": _as_int(summary.get("reference_subject_count"))
        or _as_int(registry_secondary_scores.get("reference_subject_count"))
        or _as_int(registry_hyperparameters.get("reference_subject_count"))
        or _as_int(registry_data_diagnostics.get("subject_count")),
        "n_folds": n_folds or None,
        "mean_train_r2": mean_train_r2,
        "mean_test_r2": mean_test_r2,
        "mean_test_pearson_r": mean_test_r,
        "mean_proxy_score": proxy_mean_score,
        "proxy_score_std": proxy_score_std,
        "proxy_metric_name": _first_nonempty_string(
            registry_scores, "primary_metric_name"
        ),
        "registry_entry_path": (
            str(registry_path) if registry_path is not None else None
        ),
        "summary_fields": sorted(summary.keys()),
    }
    for raw_path, role in (
        (source_summary.get("subject_manifest_path"), "external_subject_manifest"),
        (source_summary.get("fold_manifest_path"), "external_fold_manifest"),
        (source_summary.get("target_manifest_path"), "external_target_manifest"),
        (source_summary.get("covariate_manifest_path"), "external_covariate_manifest"),
        (
            source_summary.get("subject_intersection_manifest_path"),
            "external_subject_intersection_manifest",
        ),
        (source_summary.get("data_manifest_path"), "external_data_manifest"),
        (source_summary.get("subject_ids_file"), "external_subject_ids_file"),
    ):
        _append_context_sidecar_file(
            source=source_dir,
            indexed_artifacts=indexed_artifacts,
            extra_source_files=extra_source_files,
            raw_path=raw_path,
            role=role,
        )
    extraction_report = {
        "schema_version": "external-extraction-report-v1",
        "adapter_name": "generic_analysis_summary",
        "source_kind": "generic_analysis_summary",
        "inferred_fields": [
            {
                "field": "tool_id",
                "value": tool_id,
                "confidence": "medium",
                "evidence_path": evidence_name,
            },
            {
                "field": "task",
                "value": task,
                "confidence": "medium" if task else "low",
                "evidence_path": evidence_name,
            },
            {
                "field": "contrast_name",
                "value": top_contrast,
                "confidence": "medium" if top_contrast else "low",
                "evidence_path": evidence_name,
            },
            {
                "field": "statistical_method",
                "value": method,
                "confidence": "medium",
                "evidence_path": evidence_name,
            },
            {
                "field": "n_folds",
                "value": n_folds or None,
                "confidence": "medium" if n_folds else "low",
                "evidence_path": (
                    evidence_name
                    if len(proxy_fold_scores) or len(fold_results)
                    else (
                        f"{registry_path.name}:run_id={run_id}"
                        if registry_path is not None and run_id
                        else evidence_name
                    )
                ),
            },
            {
                "field": "subject_alignment_status",
                "value": source_summary.get("subject_alignment_status"),
                "confidence": (
                    "medium"
                    if source_summary.get("subject_alignment_status")
                    else "low"
                ),
                "evidence_path": (
                    evidence_name
                    if _first_nonempty_string(summary, "subject_alignment_status")
                    else (
                        f"{registry_path.name}:run_id={run_id}"
                        if registry_path is not None and run_id
                        else evidence_name
                    )
                ),
            },
        ],
        "indexed_artifacts": indexed_artifacts,
        "review_contract": review_contract,
    }
    return _prefixed_adapter_payload(
        adapter_name="generic_analysis_summary",
        source_kind="generic_analysis_summary",
        tool_id=tool_id,
        task=task,
        contrast_name=top_contrast,
        modality=modality,
        statistical_method=method,
        title=f"External analysis import: {source_dir.name}",
        description=f"Imported external analysis summary from {source_dir.name}.",
        execution={
            "source_kind": "generic_analysis_summary",
            "tool_id": tool_id,
            "analysis_dir": summary.get("analysis_dir"),
            "run_root": summary.get("run_root"),
        },
        inputs={"task": task},
        outputs={
            "n_rows": n_rows,
            "embedding_dim": embedding_dim,
            "top_contrast": top_contrast,
            "top_contrast_score": top_score,
            "n_folds": n_folds or None,
            "mean_test_r2": mean_test_r2,
            "mean_test_pearson_r": mean_test_r,
        },
        artifacts=[
            _artifact(artifact_rel, "external_analysis_summary"),
            *[
                _artifact(extra_file["artifact_rel"], extra_file["role"])
                for extra_file in extra_source_files
            ],
            _artifact("source_summary.json", "external_source_summary"),
            _artifact("extraction_report.json", "external_extraction_report"),
        ],
        extra_source_files=extra_source_files,
        diagnostics_summary={
            "adapter_name": "generic_analysis_summary",
            "source_kind": "generic_analysis_summary",
            "n_rows": n_rows,
            "embedding_dim": embedding_dim,
            "top_contrast": top_contrast,
            "top_contrast_score": top_score,
            "n_folds": n_folds or None,
            "mean_train_r2": mean_train_r2,
            "mean_test_r2": mean_test_r2,
            "mean_test_pearson_r": mean_test_r,
            "mean_proxy_score": proxy_mean_score,
            "reference_subject_count": source_summary.get("reference_subject_count"),
        },
        source_summary=source_summary,
        extraction_report=extraction_report,
        provenance_updates={
            "top_contrast": top_contrast,
            "registry_entry_path": (
                str(registry_path) if registry_path is not None else None
            ),
            "registry_run_id": run_id,
        },
        extra_run_record_updates={"review_contract": review_contract},
    )


_ADAPTER_DEFINITIONS: tuple[ExternalArtifactAdapterDefinition, ...] = (
    ExternalArtifactAdapterDefinition(
        name="fitlins_multiverse",
        description="FitLins multiverse output roots with manifests and optional Yeo17 robustness summaries.",
        builder=_fitlins_multiverse_payload,
    ),
    ExternalArtifactAdapterDefinition(
        name="tribe_prediction",
        description="TRIBE prediction artifact directories with run_summary + manifest_index + embedding rows.",
        builder=_tribe_prediction_payload,
    ),
    ExternalArtifactAdapterDefinition(
        name="tribe_embedding_analysis",
        description="TRIBE embedding analysis directories with summary.json and ranked candidates.",
        builder=_tribe_analysis_payload,
    ),
    ExternalArtifactAdapterDefinition(
        name="generic_prediction_summary",
        description="Generic prediction directories with run_summary.json.",
        builder=_generic_prediction_summary_payload,
    ),
    ExternalArtifactAdapterDefinition(
        name="generic_analysis_summary",
        description="Generic analysis directories with summary.json.",
        builder=_generic_analysis_summary_payload,
    ),
)


def available_external_artifact_adapters() -> list[dict[str, str]]:
    return [
        {
            "name": definition.name,
            "description": definition.description,
            "lifecycle": "legacy_external_import_only",
        }
        for definition in _ADAPTER_DEFINITIONS
    ]


def detect_external_artifact_adapter(
    source_dir: Path | str,
    *,
    preferred: str = "auto",
) -> ExternalArtifactAdapterPayload | None:
    source = Path(source_dir).expanduser().resolve()
    if preferred == "none":
        return None

    if preferred != "auto":
        for definition in _ADAPTER_DEFINITIONS:
            if definition.name == preferred:
                return definition.builder(source)
        raise ValueError(f"unknown external artifact adapter: {preferred}")

    for definition in _ADAPTER_DEFINITIONS:
        payload = definition.builder(source)
        if payload is not None:
            return payload
    return None


__all__ = [
    "ExternalArtifactAdapterDefinition",
    "ExternalArtifactAdapterPayload",
    "available_external_artifact_adapters",
    "detect_external_artifact_adapter",
]
