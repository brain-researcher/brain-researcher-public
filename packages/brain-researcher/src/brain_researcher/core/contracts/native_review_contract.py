"""Shared native review-contract synthesis for review consumers."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from brain_researcher.core.artifact_validator import artifact_contract_for_profile

PREDICTIVE_REVIEW_PROFILE = "predictive_model_review"
PREDICTIVE_COMPLETENESS_CHECKS = [
    "random_seed_pinned",
    "target_declared",
    "evaluation_protocol_declared",
    "subject_alignment_declared",
    "split_metadata_declared",
    "null_model_declared",
    "preprocessing_choices_declared",
]
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
_PREDICTIVE_TARGET_KEYS = (
    "target",
    "target_name",
    "target_column",
    "target_variable",
)
_PREDICTIVE_ANALYSIS_MANIFEST_KEYS = (
    *_PREDICTIVE_TARGET_KEYS,
    "classifier",
    "feature_strategy",
    "reference_subject_count",
    "fold_results",
)
_PREDICTIVE_EVALUATION_KEYS = (
    "n_folds",
    "fold_count",
    "cv_folds",
    "cross_validation",
    "evaluation_protocol",
    "evaluation_strategy",
    "split_strategy",
    "holdout_fraction",
)


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _has_present_value(mapping: dict[str, Any], keys: tuple[str, ...]) -> bool:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return True
        if value not in (None, "", [], {}):
            return True
    return False


def _predictive_review_context() -> dict[str, Any]:
    return {
        "schema_version": REVIEW_CONTEXT_SCHEMA_VERSION,
        "split": {
            "split_unit": None,
            "split_strategy_detail": None,
            "grouped_split_keys": [],
            "required_group_keys": [],
            "grouping_required": None,
            "train_test_independence": None,
        },
        "selection": {
            "selection_on_test": None,
            "selection_scope": None,
            "selection_phase": None,
            "winner_selection_scope": None,
            "winner_selection_phase": None,
            "winner": None,
            "best_candidate": None,
            "selected_candidate": None,
            "best_model": None,
            "best_layer": None,
            "best_roi": None,
            "best_prompt": None,
            "model_candidates": [],
            "layer_candidates": [],
            "roi_candidates": [],
            "prompt_candidates": [],
            "candidate_count": None,
            "n_models": None,
            "n_layers": None,
            "n_rois": None,
            "n_prompts": None,
            "selection_accounting": None,
            "multiplicity_accounting": None,
            "multiple_comparison_correction": None,
            "multiple_testing_correction": None,
            "winner_selection_method": None,
            "winner_selection_criterion": None,
            "winner_selection_protocol": None,
            "nested_cv": None,
            "selection_holdout": None,
            "independent_validation": None,
        },
        "provenance": {
            "provenance_tier": None,
            "evidence_provenance": None,
        },
        "null_model": {
            "null_model_spec": None,
            "permutation_baseline_spec": None,
            "spatial_null_spec": None,
        },
        "review_probes": {
            "label_permutation_null": None,
        },
        "preprocessing": {
            "feature_selection_scope": None,
            "standardization_scope": None,
            "harmonization_fit_scope": None,
            "confound_regression_scope": None,
        },
        "cv_contract": {
            "fit_scope_by_step": None,
        },
        "feature_contract": {
            "matrix_kind": None,
            "source_level": None,
            "n_rois": None,
            "n_timepoints": None,
            "effective_n_timepoints": None,
            "covariance_estimator": None,
            "precision_estimator": None,
            "regularization": None,
            "covariance_rank": None,
            "precision_rank": None,
            "covariance_condition_number": None,
            "precision_condition_number": None,
            "min_eig": None,
            "transform_state": None,
        },
        "statistical_inference": {
            "correction_summary_path": None,
            "multiple_comparison_correction": None,
            "multiple_testing_correction": None,
            "correction_scope": None,
            "correction_alpha": None,
            "height_control": None,
            "voxelwise_threshold": None,
            "cluster_forming_threshold": None,
            "cluster_alpha": None,
            "threshold_summary_path": None,
            "thresholded_map_path": None,
            "contrast_table_path": None,
            "cluster_table_path": None,
            "peak_table_path": None,
        },
        "design_model": {
            "design_matrix_path": None,
            "hrf_model": None,
            "basis_set": None,
            "temporal_derivative": None,
            "dispersion_derivative": None,
            "fir_delays": [],
            "drift_model": None,
            "high_pass_cutoff": None,
            "autocorrelation_model": None,
            "serial_correlation_correction": None,
            "prewhitening_method": None,
            "prewhitening_enabled": None,
            "tr": None,
        },
        "sensitivity": {
            "controversial_choices": [],
            "sensitivity_requirements": [],
            "robustness_checks": [],
        },
        "construct_validity": {
            "behavioral_imbalance": {},
            "alternative_explanations": [],
            "control_strategy": None,
            "controlled_covariates": [],
        },
    }


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


def _mapping_value(source: object) -> dict[str, Any]:
    return source if isinstance(source, dict) else {}


def _first_present(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if _value_present(value):
            return _clone_value(value)
    return None


def _first_list(mapping: dict[str, Any], *keys: str) -> list[Any] | None:
    value = _first_present(mapping, *keys)
    if isinstance(value, list):
        return value
    if value is None:
        return None
    return [value]


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


def _extract_review_context(
    bundle: dict[str, Any],
    *,
    observation: dict[str, Any] | None = None,
    execution_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = _predictive_review_context()
    evidence_sources: list[str] = []

    bundle_analysis = _mapping_value(bundle.get("analysis_manifest"))
    bundle_run_card = _mapping_value(bundle.get("run_card"))
    bundle_run_params = _mapping_value(bundle_run_card.get("parameters"))
    bundle_provenance = _mapping_value(bundle.get("provenance"))
    bundle_provenance_request = _mapping_value(bundle_provenance.get("request"))
    observation_mapping = _mapping_value(observation)
    observation_run_card = _mapping_value(observation_mapping.get("run_card"))
    observation_run_params = _mapping_value(observation_run_card.get("parameters"))
    observation_provenance = _mapping_value(observation_mapping.get("provenance"))
    observation_provenance_params = _mapping_value(
        observation_provenance.get("parameters")
    )
    execution = _mapping_value(execution_manifest)
    execution_params = _mapping_value(execution.get("parameters"))

    sources: list[tuple[str, dict[str, Any]]] = [
        ("bundle.analysis_manifest", bundle_analysis),
        ("observation.run_card.parameters", observation_run_params),
        ("bundle.run_card.parameters", bundle_run_params),
        ("bundle.provenance.request", bundle_provenance_request),
        ("observation.provenance.parameters", observation_provenance_params),
        ("execution_manifest.parameters", execution_params),
    ]

    split_aliases = {
        "split_unit": ("split_unit", "cv_unit"),
        "split_strategy_detail": (
            "split_strategy",
            "split_strategy_detail",
            "cross_validation",
            "evaluation_protocol",
            "evaluation_strategy",
        ),
        "grouped_split_keys": ("grouped_split_keys", "group_keys", "split_keys"),
        "required_group_keys": (
            "required_group_keys",
            "required_grouping_keys",
            "grouping_required_keys",
            "mandatory_group_keys",
            "required_split_groups",
        ),
        "grouping_required": ("grouping_required",),
        "train_test_independence": (
            "train_test_independence",
            "subject_alignment_status",
            "no_leakage",
        ),
        "split_manifest_path": ("split_manifest_path",),
        "cv_manifest_path": ("cv_manifest_path",),
        "subject_manifest_path": ("subject_manifest_path",),
        "fold_manifest_path": ("fold_manifest_path",),
        "target_manifest_path": ("target_manifest_path",),
        "covariate_manifest_path": ("covariate_manifest_path",),
        "subject_intersection_manifest_path": ("subject_intersection_manifest_path",),
        "subject_selection_source": ("subject_selection_source",),
        "label_shuffle_seed": ("label_shuffle_seed",),
        "reference_subject_count": ("reference_subject_count",),
        "n_folds": ("n_folds", "fold_count", "cv_folds"),
    }
    preprocessing_aliases = {
        "feature_selection_scope": (
            "feature_selection_scope",
            "feature_strategy",
            "feature_selection",
        ),
        "standardization_scope": (
            "standardization_scope",
            "standardize_confounds",
            "standardize",
            "normalize",
        ),
        "harmonization_fit_scope": (
            "harmonization_fit_scope",
            "harmonization",
            "harmonization_strategy",
            "combat",
        ),
        "confound_regression_scope": (
            "confound_regression_scope",
            "confounds",
            "confound_strategy",
            "confound_columns",
        ),
        "confounds": ("confounds",),
        "confound_strategy": ("confound_strategy",),
        "confound_columns": ("confound_columns",),
    }
    cv_contract_aliases = {
        "fit_scope_by_step": (
            "fit_scope_by_step",
            "fit_scopes",
            "preprocessing_fit_scope",
            "preprocessing_fit_scope_by_step",
        ),
    }
    selection_aliases = {
        "selection_on_test": (
            "selection_on_test",
            "selected_on_test",
            "winner_selected_on_test",
            "heldout_selection",
            "held_out_selection",
            "test_set_selection",
        ),
        "selection_scope": ("selection_scope", "selection_phase"),
        "selection_phase": ("selection_phase",),
        "winner_selection_scope": ("winner_selection_scope", "winner_selection_phase"),
        "winner_selection_phase": ("winner_selection_phase",),
        "winner": ("winner",),
        "best_candidate": ("best_candidate", "selected_candidate", "winner_candidate"),
        "selected_candidate": ("selected_candidate",),
        "best_model": ("best_model", "selected_model", "winner_model", "top_model"),
        "best_layer": ("best_layer", "selected_layer", "winner_layer", "top_layer"),
        "best_roi": ("best_roi", "selected_roi", "winner_roi", "top_roi"),
        "best_prompt": (
            "best_prompt",
            "selected_prompt",
            "winner_prompt",
            "top_prompt",
        ),
        "model_candidates": (
            "model_candidates",
            "candidate_models",
            "models",
            "model_grid",
        ),
        "layer_candidates": (
            "layer_candidates",
            "candidate_layers",
            "layers",
            "layer_grid",
        ),
        "roi_candidates": ("roi_candidates", "candidate_rois", "rois", "roi_grid"),
        "prompt_candidates": (
            "prompt_candidates",
            "candidate_prompts",
            "prompts",
            "prompt_grid",
        ),
        "candidates": ("candidates", "comparison_candidates", "winner_candidates"),
        "candidate_count": ("candidate_count", "n_candidates", "search_space_size"),
        "n_models": ("n_models", "model_count", "candidate_model_count"),
        "n_layers": ("n_layers", "layer_count", "candidate_layer_count"),
        "n_rois": ("n_rois", "roi_count", "candidate_roi_count"),
        "n_prompts": ("n_prompts", "prompt_count", "candidate_prompt_count"),
        "selection_accounting": ("selection_accounting",),
        "multiplicity_accounting": ("multiplicity_accounting",),
        "multiple_comparison_correction": (
            "multiple_comparison_correction",
            "multiple_testing_correction",
        ),
        "multiple_testing_correction": ("multiple_testing_correction",),
        "winner_selection_method": ("winner_selection_method",),
        "winner_selection_criterion": ("winner_selection_criterion",),
        "winner_selection_protocol": ("winner_selection_protocol",),
        "nested_cv": ("nested_cv",),
        "selection_holdout": ("selection_holdout",),
        "independent_validation": ("independent_validation",),
    }
    null_model_aliases = {
        "resampling_method": ("resampling_method",),
        "permutation_test": ("permutation_test",),
        "n_permutations": ("n_permutations",),
        "permutation_seed": ("permutation_seed",),
        "exchangeability_blocks": ("exchangeability_blocks", "exchangeability_block"),
    }
    review_probe_aliases = {
        "label_permutation_null": (
            "label_permutation_null",
            "permutation_null",
            "full_pipeline_permutation_null",
        ),
    }
    feature_contract_aliases = {
        "matrix_kind": (
            "matrix_kind",
            "corr_matrix_kind",
            "correlation_matrix_kind",
            "connectivity_matrix_kind",
            "feature_matrix_kind",
        ),
        "source_level": (
            "source_level",
            "connectivity_source_level",
            "matrix_source_level",
        ),
        "n_rois": ("n_rois", "n_regions", "corr_n_rois", "corr_n_regions"),
        "n_timepoints": (
            "n_timepoints",
            "corr_n_timepoints",
            "connectivity_n_timepoints",
        ),
        "effective_n_timepoints": (
            "effective_n_timepoints",
            "corr_effective_n_timepoints",
        ),
        "covariance_estimator": (
            "covariance_estimator",
            "corr_covariance_estimator",
        ),
        "precision_estimator": (
            "precision_estimator",
            "partial_correlation_estimator",
            "corr_precision_estimator",
        ),
        "regularization": (
            "regularization",
            "regularized",
            "precision_regularization",
            "covariance_regularization",
            "shrinkage",
        ),
        "covariance_rank": ("covariance_rank", "corr_covariance_rank"),
        "precision_rank": ("precision_rank", "corr_precision_rank"),
        "covariance_condition_number": (
            "covariance_condition_number",
            "corr_covariance_condition_number",
            "fc_covariance_condition_number",
        ),
        "precision_condition_number": (
            "precision_condition_number",
            "partial_correlation_condition_number",
            "corr_precision_condition_number",
            "fc_precision_condition_number",
        ),
        "min_eig": (
            "min_eig",
            "corr_min_eig",
            "covariance_min_eig",
            "precision_min_eig",
        ),
        "transform_state": (
            "transform_state",
            "corr_transform_state",
            "connectivity_transform_state",
        ),
    }
    sensitivity_aliases = {
        "controversial_choices": ("controversial_choices",),
        "sensitivity_requirements": (
            "sensitivity_requirements",
            "validation_missing",
        ),
        "robustness_checks": (
            "robustness_checks",
            "sensitivity_checks",
            "sensitivity_analysis",
            "validation_evidence",
        ),
    }
    construct_validity_aliases = {
        "behavioral_imbalance": ("behavioral_imbalance",),
        "alternative_explanations": (
            "alternative_explanations",
            "construct_validity_alternatives",
        ),
        "control_strategy": ("control_strategy", "behavioral_control_strategy"),
        "controlled_covariates": (
            "controlled_covariates",
            "behavioral_covariates",
            "control_variables",
        ),
    }
    statistical_inference_aliases = {
        "correction_summary_path": (
            "correction_summary_path",
            "multiple_comparison_summary_path",
            "threshold_summary_path",
        ),
        "multiple_comparison_correction": (
            "multiple_comparison_correction",
            "multiple_testing_correction",
            "correction_method",
        ),
        "multiple_testing_correction": ("multiple_testing_correction",),
        "correction_scope": (
            "correction_scope",
            "correction_domain",
            "multiple_comparison_scope",
            "analysis_scope",
            "family_key",
        ),
        "correction_alpha": ("correction_alpha", "alpha", "fdr_alpha", "fwe_alpha"),
        "height_control": ("height_control",),
        "voxelwise_threshold": (
            "voxelwise_threshold",
            "voxel_threshold",
            "height_threshold",
            "map_threshold",
        ),
        "cluster_forming_threshold": (
            "cluster_forming_threshold",
            "cluster_defining_threshold",
            "cluster_threshold",
        ),
        "cluster_alpha": ("cluster_alpha", "cluster_p_threshold"),
        "threshold_summary_path": (
            "threshold_summary_path",
            "multiple_comparison_summary_path",
            "correction_summary_path",
        ),
        "thresholded_map_path": (
            "thresholded_map_path",
            "significance_mask_path",
            "corrected_map_path",
        ),
        "contrast_table_path": (
            "contrast_table_path",
            "contrasts_path",
            "contrast_matrix_path",
            "contrast_csv",
        ),
        "cluster_table_path": ("cluster_table_path",),
        "peak_table_path": ("peak_table_path",),
    }
    design_model_aliases = {
        "design_matrix_path": (
            "design_matrix_path",
            "design_matrix",
            "design_path",
        ),
        "hrf_model": ("hrf_model", "hemodynamic_model"),
        "basis_set": ("basis_set", "basis_function", "hrf_basis"),
        "temporal_derivative": (
            "temporal_derivative",
            "use_temporal_derivative",
            "add_temporal_derivatives",
            "time_derivative",
            "hrf_derivative",
        ),
        "dispersion_derivative": (
            "dispersion_derivative",
            "use_dispersion_derivative",
            "add_dispersion_derivative",
            "hrf_dispersion",
        ),
        "fir_delays": ("fir_delays", "fir_lags"),
        "drift_model": ("drift_model",),
        "high_pass_cutoff": ("high_pass_cutoff", "high_pass"),
        "autocorrelation_model": (
            "autocorrelation_model",
            "noise_model",
            "autocorrelation_correction",
        ),
        "serial_correlation_correction": (
            "serial_correlation_correction",
            "serial_correlation_model",
            "serial_correlation_method",
            "serial_autocorrelation_correction",
        ),
        "prewhitening_method": ("prewhitening_method", "prewhitening"),
        "prewhitening_enabled": (
            "prewhitening_enabled",
            "prewhiten_yn",
            "film_prewhitening",
        ),
        "tr": ("tr", "t_r"),
    }
    spatial_null_aliases = {
        "spatial_null_method": ("spatial_null_method", "spatial_null"),
        "spin_test": ("spin_test",),
        "spin_permutations": ("spin_permutations",),
        "spin_seed": ("spin_seed",),
        "brain_smash": ("brain_smash",),
    }

    for source_label, mapping in sources:
        split = context["split"]
        selection = context["selection"]
        preprocessing = context["preprocessing"]
        cv_contract = context["cv_contract"]
        feature_contract = context["feature_contract"]
        null_model = context["null_model"]
        review_probes = context["review_probes"]
        statistical_inference = context["statistical_inference"]
        design_model = context["design_model"]
        sensitivity = context["sensitivity"]
        construct_validity = context["construct_validity"]

        if _populate_section(split, mapping, split_aliases):
            evidence_sources.append(source_label)
        if _populate_section(selection, mapping, selection_aliases):
            evidence_sources.append(source_label)
        if _populate_section(preprocessing, mapping, preprocessing_aliases):
            evidence_sources.append(source_label)
        if _populate_section(cv_contract, mapping, cv_contract_aliases):
            evidence_sources.append(source_label)
        if _populate_section(feature_contract, mapping, feature_contract_aliases):
            evidence_sources.append(source_label)
        if _populate_section(null_model, mapping, null_model_aliases):
            evidence_sources.append(source_label)
        if _populate_section(review_probes, mapping, review_probe_aliases):
            evidence_sources.append(source_label)
        if _populate_section(
            statistical_inference,
            mapping,
            statistical_inference_aliases,
        ):
            evidence_sources.append(source_label)
        if _populate_section(design_model, mapping, design_model_aliases):
            evidence_sources.append(source_label)
        if _populate_section(sensitivity, mapping, sensitivity_aliases):
            evidence_sources.append(source_label)
        if _populate_section(
            construct_validity,
            mapping,
            construct_validity_aliases,
        ):
            evidence_sources.append(source_label)

        spatial_null_value = _first_present(
            mapping, *spatial_null_aliases["spatial_null_method"]
        )
        if spatial_null_value is not None:
            null_model["spatial_null_spec"] = spatial_null_value
            evidence_sources.append(source_label)
        else:
            spatial_null_fields = {
                key: _first_present(mapping, *aliases)
                for key, aliases in spatial_null_aliases.items()
                if key != "spatial_null_method"
            }
            spatial_null_fields = {
                key: value
                for key, value in spatial_null_fields.items()
                if value is not None
            }
            if spatial_null_fields:
                null_model["spatial_null_spec"] = spatial_null_fields
                evidence_sources.append(source_label)

        behavioral_imbalance = _collect_behavioral_imbalance(mapping)
        if behavioral_imbalance:
            existing = construct_validity.get("behavioral_imbalance")
            merged_imbalance = dict(existing) if isinstance(existing, dict) else {}
            merged_imbalance.update(behavioral_imbalance)
            construct_validity["behavioral_imbalance"] = merged_imbalance
            evidence_sources.append(source_label)

    explicit_null_model = _first_present(
        bundle_analysis, "null_model_spec", "null_model"
    )
    if explicit_null_model is not None:
        context["null_model"]["null_model_spec"] = explicit_null_model
        evidence_sources.append("bundle.analysis_manifest")

    explicit_baseline = _first_present(
        bundle_analysis,
        "permutation_baseline_spec",
        "permutation_baseline",
        "permutation_manifest",
        "baseline_spec",
    )
    if explicit_baseline is not None:
        context["null_model"]["permutation_baseline_spec"] = explicit_baseline
        evidence_sources.append("bundle.analysis_manifest")

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
        if not null_model_spec_fields:
            null_model_spec_fields = {
                key: value
                for key, value in (
                    (
                        "resampling_method",
                        _first_present(execution_params, "resampling_method"),
                    ),
                    (
                        "permutation_test",
                        _first_present(execution_params, "permutation_test"),
                    ),
                    (
                        "n_permutations",
                        _first_present(execution_params, "n_permutations"),
                    ),
                    (
                        "permutation_seed",
                        _first_present(execution_params, "permutation_seed"),
                    ),
                    (
                        "exchangeability_blocks",
                        _first_present(execution_params, "exchangeability_blocks"),
                    ),
                )
                if value is not None
            }
        if null_model_spec_fields:
            context["null_model"]["null_model_spec"] = null_model_spec_fields
            evidence_sources.append("execution_manifest.parameters")

    if context["null_model"]["permutation_baseline_spec"] is None:
        baseline_fields = {
            key: value
            for key, value in (
                (
                    "permutation_baseline",
                    context["null_model"].get("permutation_baseline_spec"),
                ),
                (
                    "permutation_manifest",
                    context["null_model"].get("permutation_baseline_spec"),
                ),
                (
                    "baseline_spec",
                    context["null_model"].get("permutation_baseline_spec"),
                ),
            )
            if value is not None
        }
        if not baseline_fields:
            baseline_fields = {
                key: value
                for key, value in (
                    (
                        "permutation_baseline",
                        _first_present(execution_params, "permutation_baseline"),
                    ),
                    (
                        "permutation_manifest",
                        _first_present(execution_params, "permutation_manifest"),
                    ),
                    (
                        "baseline_spec",
                        _first_present(execution_params, "baseline_spec"),
                    ),
                )
                if value is not None
            }
        if baseline_fields:
            context["null_model"]["permutation_baseline_spec"] = baseline_fields
            evidence_sources.append("execution_manifest.parameters")

    for label_source, mapping in (
        ("bundle.feature_contract", bundle_analysis.get("feature_contract")),
        ("observation.feature_contract", observation_mapping.get("feature_contract")),
        ("bundle.top.feature_contract", bundle.get("feature_contract")),
    ):
        if isinstance(mapping, dict) and mapping:
            merged_feature = dict(context.get("feature_contract") or {})
            for key, value in mapping.items():
                if value is not None:
                    merged_feature[key] = value
            context["feature_contract"] = merged_feature
            evidence_sources.append(label_source)

    for label_source, mapping in (
        ("bundle.review_probes", bundle_analysis.get("review_probes")),
        ("observation.review_probes", observation_mapping.get("review_probes")),
        ("bundle.top.review_probes", bundle.get("review_probes")),
    ):
        if isinstance(mapping, dict) and mapping:
            merged_probes = dict(context.get("review_probes") or {})
            for key, value in mapping.items():
                if value is not None:
                    merged_probes[key] = value
            context["review_probes"] = merged_probes
            label_probe = merged_probes.get("label_permutation_null")
            if isinstance(label_probe, dict) and label_probe:
                context["null_model"].setdefault("permutation_null", label_probe)
            evidence_sources.append(label_source)

    if evidence_sources:
        seen: set[str] = set()
        ordered_sources = []
        for source_label in evidence_sources:
            if source_label in seen:
                continue
            seen.add(source_label)
            ordered_sources.append(source_label)
        context["provenance"]["evidence_provenance"] = ordered_sources
        context["provenance"]["provenance_tier"] = (
            "multi_source" if len(ordered_sources) > 1 else "single_source"
        )

    return context


def is_predictive_native_bundle(
    bundle: dict[str, Any],
    *,
    observation: dict[str, Any] | None = None,
    execution_manifest: dict[str, Any] | None = None,
) -> bool:
    policy_snapshot = _mapping(bundle.get("policy_snapshot"))
    if (
        str(policy_snapshot.get("source") or "").strip().lower()
        == "predictive_loop_controller"
    ):
        return True

    analysis_manifest = _mapping(bundle.get("analysis_manifest"))
    if _has_present_value(analysis_manifest, _PREDICTIVE_ANALYSIS_MANIFEST_KEYS):
        return True

    parameters = _mapping(_mapping(execution_manifest).get("parameters"))
    if _has_present_value(parameters, _PREDICTIVE_TARGET_KEYS) and _has_present_value(
        parameters,
        _PREDICTIVE_EVALUATION_KEYS,
    ):
        return True

    bundle_run_card_inputs = _mapping(_mapping(bundle.get("run_card")).get("inputs"))
    if _has_present_value(bundle_run_card_inputs, _PREDICTIVE_TARGET_KEYS):
        return True

    observation_run_card_inputs = _mapping(
        _mapping(_mapping(observation).get("run_card")).get("inputs")
    )
    return _has_present_value(observation_run_card_inputs, _PREDICTIVE_TARGET_KEYS)


def build_native_review_contract(
    bundle: dict[str, Any],
    *,
    observation: dict[str, Any] | None = None,
    execution_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    files = bundle.get("files") if isinstance(bundle.get("files"), dict) else {}
    artifact_contract = artifact_contract_for_profile("run_bundle")
    required = ["analysis_bundle.json"]
    for key in ("observation_json", "execution_manifest_json"):
        rel = files.get(key)
        if isinstance(rel, str) and rel.strip():
            required.append(rel.strip())

    recommended = []
    for key in ("trace_jsonl", "provenance_json", "trajectory_json"):
        rel = files.get(key)
        if isinstance(rel, str) and rel.strip():
            recommended.append(rel.strip())
    for key in (
        "research_episode_json",
        "option_set_json",
        "evidence_gate_json",
        "commitment_json",
        "claim_report_json",
        "claim_update_json",
        "correction_summary_json",
        "threshold_summary_json",
        "thresholded_map",
        "design_matrix",
        "contrast_table",
        "cluster_table",
        "peak_table",
    ):
        rel = files.get(key)
        if isinstance(rel, str) and rel.strip():
            recommended.append(rel.strip())

    contract = {
        "schema_version": "native-review-contract-v1",
        "contract_mode": "native_review_bundle",
        "required_root_artifacts": list(dict.fromkeys(required)),
        "recommended_root_artifacts": list(dict.fromkeys(recommended)),
        "run_artifact_contract": {
            "schema_version": "run-artifact-contract-v1",
            "profile": "run_bundle",
            "required_artifacts": [
                spec.filename for spec in artifact_contract if spec.required
            ],
            "optional_artifacts": [
                spec.filename for spec in artifact_contract if not spec.required
            ],
            "missing_policy": {
                spec.filename: spec.missing_policy for spec in artifact_contract
            },
            "artifacts": [asdict(spec) for spec in artifact_contract],
        },
        "native_bundle_schema": bundle.get("schema_version"),
        "review_context": _extract_review_context(
            bundle,
            observation=observation,
            execution_manifest=execution_manifest,
        ),
    }
    if is_predictive_native_bundle(
        bundle,
        observation=observation,
        execution_manifest=execution_manifest,
    ):
        contract["scientific_review_profile"] = PREDICTIVE_REVIEW_PROFILE
        contract["scientific_completeness_checks"] = list(
            PREDICTIVE_COMPLETENESS_CHECKS
        )
    return contract


def build_native_review_context(
    bundle: dict[str, Any],
    *,
    observation: dict[str, Any] | None = None,
    execution_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the structured review_context for a native bundle."""

    return _extract_review_context(
        bundle,
        observation=observation,
        execution_manifest=execution_manifest,
    )


__all__ = [
    "build_native_review_context",
    "PREDICTIVE_COMPLETENESS_CHECKS",
    "PREDICTIVE_REVIEW_PROFILE",
    "build_native_review_contract",
    "is_predictive_native_bundle",
]
