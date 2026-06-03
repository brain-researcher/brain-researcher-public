"""Deterministic completeness checklist checks for Phase 3."""

from __future__ import annotations

from collections.abc import Mapping

from brain_researcher.core.contracts.code_review import CodeReviewBundle

_ATLAS_TOOLS = frozenset(
    [
        "parcellation_fetch",
        "atlas_parcellate",
        "parcellate",
        "dmri_parcellate_connectome",
        "nilearn_masker",
        "extract_roi",
    ]
)
_STOCHASTIC_TOOLS = frozenset(
    [
        "ica",
        "fastica",
        "melodic",
        "pca",
        "tsne",
        "umap",
        "cluster",
        "kmeans",
        "leiden",
        "louvain",
    ]
)
_ORDERING_KEYS = frozenset(
    ["sort_order", "subject_order", "participant_order", "ordered"]
)
_ORDER_SENSITIVE_TOKENS = frozenset(
    ["csv", "table", "summary", "group", "export", "report", "manifest"]
)
_DEFAULT_COMPLETENESS_CHECKS = (
    "random_seed_pinned",
    "atlas_version_pinned",
    "ordering_rule_declared",
)
_PREDICTIVE_COMPLETENESS_CHECKS = (
    "random_seed_pinned",
    "target_declared",
    "evaluation_protocol_declared",
    "subject_alignment_declared",
    "split_metadata_declared",
    "null_model_declared",
    "preprocessing_choices_declared",
    "nested_cv_structure_declared",
    "subject_manifest_declared",
    "sensitivity_package_declared",
)
_GLM_FMRI_COMPLETENESS_CHECKS = (
    "random_seed_pinned",
    "atlas_version_pinned",
    "subject_alignment_declared",
    "preprocessing_choices_declared",
    "confound_columns_declared",
    "hrf_model_declared",
    "autocorrelation_model_declared",
    "design_matrix_declared",
    "contrast_table_declared",
    "correction_summary_declared",
    "cluster_table_declared",
    "peak_table_declared",
    "sensitivity_package_declared",
)
_PROFILE_COMPLETENESS_CHECKS = {
    "predictive_model_review": _PREDICTIVE_COMPLETENESS_CHECKS,
    "glm_fmri_review": _GLM_FMRI_COMPLETENESS_CHECKS,
}
_TARGET_KEYS = (
    "target",
    "target_name",
    "target_column",
    "task",
    "task_label",
    "analysis_goal",
    "estimand",
)
_EVALUATION_KEYS = (
    "n_folds",
    "fold_count",
    "cv_folds",
    "cross_validation",
    "cv",
    "evaluation_protocol",
    "evaluation_strategy",
    "split_strategy",
    "holdout_fraction",
    "proxy_metric_name",
    "metric_name",
    "scoring",
)
_SUBJECT_ALIGNMENT_KEYS = (
    "subject_alignment_status",
    "subject_intersection_manifest_path",
    "subject_manifest_path",
    "fold_manifest_path",
    "target_manifest_path",
    "subject_selection_source",
)
_MANIFEST_ALIGNMENT_TOKENS = (
    "manifest",
    "subject",
    "participant",
    "fold",
    "target",
    "covariate",
    "alignment",
    "intersection",
)
_REVIEW_CONTEXT_SPLIT_KEYS = (
    "split_manifest",
    "split_manifest_path",
    "subject_manifest_path",
    "subject_intersection_manifest_path",
    "cv_manifest",
    "cv_manifest_path",
    "fold_manifest_path",
    "split_strategy",
    "split_strategy_detail",
    "split_unit",
    "train_test_independence",
    "grouped_split_keys",
)
_REVIEW_CONTEXT_NULL_KEYS = (
    "null_model",
    "null_model_spec",
    "permutation_manifest",
    "permutation_baseline",
    "permutation_baseline_spec",
    "baseline_spec",
    "spatial_null_spec",
    "sensitivity_requirements",
)
_REVIEW_CONTEXT_PREPROCESSING_KEYS = (
    "preprocessing_choices",
    "confounds",
    "feature_selection_scope",
    "standardization_scope",
    "harmonization_fit_scope",
    "confound_regression_scope",
)
_REVIEW_CONTEXT_DESIGN_MODEL_KEYS = (
    "design_matrix_path",
    "hrf_model",
    "basis_set",
    "autocorrelation_model",
    "noise_model",
    "prewhitening_method",
    "prewhitening_model",
    "serial_correlation_correction",
)
_REVIEW_CONTEXT_STATISTICAL_INFERENCE_KEYS = (
    "correction_summary_path",
    "threshold_summary_path",
    "contrast_table_path",
    "cluster_table_path",
    "peak_table_path",
    "thresholded_map_path",
)
_CONFOUND_COLUMN_KEYS = (
    "confound_columns",
    "confounds_included",
    "nuisance_regressors",
    "confound_regressors",
)
_AUTOCORRELATION_KEYS = (
    "autocorrelation_model",
    "noise_model",
    "prewhitening_model",
    "prewhitening_method",
    "serial_correlation_correction",
    "serial_correlation_model",
)
_NESTED_CV_STRUCTURE_KEYS = (
    "outer_cv",
    "inner_cv",
    "selection_holdout",
    "nested_cv_inner",
    "nested_cv_outer",
    "independent_validation",
)
_SUBJECT_MANIFEST_KEYS = (
    "subject_manifest_path",
    "subject_intersection_manifest_path",
    "subject_ids",
    "n_subjects_train",
    "n_subjects_test",
    "n_subjects_val",
    "n_subjects",
    "train_subjects",
    "test_subjects",
    "val_subjects",
)
_SENSITIVITY_KEYS = (
    "controversial_choices_evaluated",
    "sensitivity_requirements",
    "robustness_checks",
    "sensitivity_results",
    "sensitivity_analysis",
)


def _review_contract(bundle: CodeReviewBundle) -> dict:
    contract = bundle.observed_artifacts.get("review_contract")
    return contract if isinstance(contract, dict) else {}


def _source_summary(bundle: CodeReviewBundle) -> dict:
    summary = bundle.observed_artifacts.get("source_summary")
    return summary if isinstance(summary, dict) else {}


def _artifact_dict(bundle: CodeReviewBundle, key: str) -> dict:
    artifact = bundle.observed_artifacts.get(key)
    return artifact if isinstance(artifact, dict) else {}


def _analysis_bundle(bundle: CodeReviewBundle) -> dict:
    return _artifact_dict(bundle, "analysis_bundle")


def _observation(bundle: CodeReviewBundle) -> dict:
    return _artifact_dict(bundle, "observation")


def _execution_manifest(bundle: CodeReviewBundle) -> dict:
    return _artifact_dict(bundle, "execution_manifest")


def _research_episode(bundle: CodeReviewBundle) -> dict:
    return _artifact_dict(bundle, "research_episode")


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _review_context(bundle: CodeReviewBundle) -> Mapping[str, object]:
    candidates = [
        _mapping(getattr(bundle, "review_context", {})),
        _mapping(_artifact_dict(bundle, "review_context")),
        _mapping(_review_contract(bundle).get("review_context")),
        _mapping(_analysis_bundle(bundle).get("review_context")),
        _mapping(_source_summary(bundle).get("review_context")),
    ]
    merged: dict[str, object] = {}
    for candidate in candidates:
        if candidate:
            merged.update(candidate)
    return merged


def _string_present(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _value_present(value: object) -> bool:
    return value not in (None, "", [], {})


def _has_text(mapping: Mapping[str, object], keys: tuple[str, ...]) -> bool:
    return any(_string_present(mapping.get(key)) for key in keys)


def _has_value(mapping: Mapping[str, object], keys: tuple[str, ...]) -> bool:
    return any(_value_present(mapping.get(key)) for key in keys)


def _run_card_inputs(bundle: CodeReviewBundle) -> Mapping[str, object]:
    observation = _observation(bundle)
    run_card = _mapping(observation.get("run_card"))
    return _mapping(run_card.get("inputs"))


def _execution_parameters(bundle: CodeReviewBundle) -> Mapping[str, object]:
    manifest = _execution_manifest(bundle)
    return _mapping(manifest.get("parameters"))


def _iter_text_refs(bundle: CodeReviewBundle) -> list[str]:
    refs: list[str] = []
    observation = _observation(bundle)
    if _string_present(observation.get("inputs_manifest_ref")):
        refs.append(str(observation["inputs_manifest_ref"]).strip())

    analysis_bundle = _analysis_bundle(bundle)
    files = _mapping(analysis_bundle.get("files"))
    if _string_present(files.get("inputs_manifest_json")):
        refs.append(str(files["inputs_manifest_json"]).strip())
    for ref in analysis_bundle.get("source_manifests") or []:
        if _string_present(ref):
            refs.append(str(ref).strip())

    manifest = _execution_manifest(bundle)
    for item in manifest.get("inputs") or []:
        if not isinstance(item, dict):
            continue
        for key in ("name", "path", "description"):
            if _string_present(item.get(key)):
                refs.append(str(item[key]).strip())

    return refs


def _requested_checks(contract: Mapping[str, object]) -> list[str]:
    requested = contract.get("scientific_completeness_checks")
    if isinstance(requested, list) and requested:
        return [str(key) for key in requested]

    profile = str(contract.get("scientific_review_profile") or "").strip()
    if profile in _PROFILE_COMPLETENESS_CHECKS:
        return list(_PROFILE_COMPLETENESS_CHECKS[profile])

    return list(_DEFAULT_COMPLETENESS_CHECKS)


def random_seed_pinned(bundle: CodeReviewBundle) -> bool:
    """Return True if any stochastic step has a random seed pinned."""
    for step in bundle.plan_steps:
        if not isinstance(step, dict):
            continue
        tool = str(step.get("tool") or "").lower()
        if not any(t in tool for t in _STOCHASTIC_TOOLS):
            continue
        params = step.get("params") or {}
        if not isinstance(params, dict):
            continue
        if any(
            k in params for k in ("random_state", "seed", "random_seed", "rng_seed")
        ):
            return True
    # If no stochastic tools, the check is N/A (vacuously True).
    has_stochastic = any(
        any(t in str(s.get("tool") or "").lower() for t in _STOCHASTIC_TOOLS)
        for s in bundle.plan_steps
        if isinstance(s, dict)
    )
    return not has_stochastic


def atlas_version_pinned(bundle: CodeReviewBundle) -> bool:
    """Return True if all atlas-using steps pin atlas version or resolution."""
    atlas_steps = [
        step
        for step in bundle.plan_steps
        if isinstance(step, dict)
        and any(t in str(step.get("tool") or "").lower() for t in _ATLAS_TOOLS)
    ]
    if not atlas_steps:
        return True  # N/A
    for step in atlas_steps:
        params = step.get("params") or {}
        if not isinstance(params, dict):
            return False
        if not any(
            k in params
            for k in ("atlas_version", "atlas_resolution", "resolution", "version")
        ):
            return False
    return True


def _needs_ordering_rule(step: dict) -> bool:
    tool = str(step.get("tool") or "").lower()
    params = step.get("params") if isinstance(step.get("params"), dict) else {}
    if any(token in tool for token in _ORDER_SENSITIVE_TOKENS):
        return True
    return any(
        key in params
        for key in (
            "subject_ids",
            "participant_ids",
            "used_subject_ids",
            "used_file_paths",
            "output_csv",
            "output_tsv",
            "output_table",
        )
    )


def ordering_rule_declared(bundle: CodeReviewBundle) -> bool:
    """Return True if order-sensitive steps declare deterministic ordering."""
    for step in bundle.plan_steps:
        if not isinstance(step, dict):
            continue
        if not _needs_ordering_rule(step):
            continue
        params = step.get("params") or {}
        if not isinstance(params, dict):
            return False
        if not any(k in params for k in _ORDERING_KEYS):
            return False
    return True


def target_declared(bundle: CodeReviewBundle) -> bool:
    """Return True if a predictive target / estimand is declared in bundle contracts."""
    research_episode = _research_episode(bundle)
    if _has_text(research_episode, ("estimand", "objective", "research_question")):
        return True

    if _has_text(_run_card_inputs(bundle), _TARGET_KEYS):
        return True

    if _has_text(_execution_parameters(bundle), _TARGET_KEYS):
        return True

    summary = _source_summary(bundle)
    if _has_text(summary, ("target_column", "target_name", "task_label", "task")):
        return True

    if bundle.kg_context.get("task"):
        return True

    review_context = _review_context(bundle)
    if _has_text(review_context, _TARGET_KEYS):
        return True

    for step in bundle.plan_steps:
        if not isinstance(step, dict):
            continue
        params = step.get("params") if isinstance(step.get("params"), dict) else {}
        if _has_text(params, _TARGET_KEYS):
            return True
    return False


def evaluation_protocol_declared(bundle: CodeReviewBundle) -> bool:
    """Return True if predictive evaluation / CV protocol is declared in contracts."""
    if _has_value(_execution_parameters(bundle), _EVALUATION_KEYS):
        return True

    summary = _source_summary(bundle)
    if _has_value(
        summary,
        (
            "n_folds",
            "mean_test_r2",
            "mean_test_pearson_r",
            "mean_proxy_score",
            "proxy_metric_name",
        ),
    ):
        return True

    stats = bundle.stats_metrics
    if _has_value(
        stats,
        ("external_n_folds", "external_mean_test_r2", "external_mean_test_pearson_r"),
    ):
        return True
    review_context = _review_context(bundle)
    if _has_value(review_context, _EVALUATION_KEYS):
        return True
    if _has_value(_mapping(review_context.get("split")), _REVIEW_CONTEXT_SPLIT_KEYS):
        return True
    return False


def subject_alignment_declared(bundle: CodeReviewBundle) -> bool:
    """Return True if subject alignment / cohort provenance is declared in contracts."""
    analysis_bundle = _analysis_bundle(bundle)
    if analysis_bundle.get("inputs_manifest") not in (None, "", [], {}):
        return True

    if any(
        token in ref.lower()
        for ref in _iter_text_refs(bundle)
        for token in _MANIFEST_ALIGNMENT_TOKENS
    ):
        return True

    summary = _source_summary(bundle)
    if _has_text(summary, _SUBJECT_ALIGNMENT_KEYS):
        return True
    review_context = _review_context(bundle)
    if _has_text(review_context, _SUBJECT_ALIGNMENT_KEYS):
        return True
    return False


def split_metadata_declared(bundle: CodeReviewBundle) -> bool:
    """Return True if review_context declares split / CV provenance."""
    review_context = _review_context(bundle)
    if _has_value(review_context, _REVIEW_CONTEXT_SPLIT_KEYS):
        return True
    return _has_value(_mapping(review_context.get("split")), _REVIEW_CONTEXT_SPLIT_KEYS)


def null_model_declared(bundle: CodeReviewBundle) -> bool:
    """Return True if review_context declares predictive null-model metadata."""
    review_context = _review_context(bundle)
    if _has_value(review_context, _REVIEW_CONTEXT_NULL_KEYS):
        return True
    return _has_value(
        _mapping(review_context.get("null_model")), _REVIEW_CONTEXT_NULL_KEYS
    )


def preprocessing_choices_declared(bundle: CodeReviewBundle) -> bool:
    """Return True if review_context captures preprocessing/confound provenance."""
    review_context = _review_context(bundle)
    if _has_value(review_context, _REVIEW_CONTEXT_PREPROCESSING_KEYS):
        return True
    return _has_value(
        _mapping(review_context.get("preprocessing")),
        _REVIEW_CONTEXT_PREPROCESSING_KEYS,
    )


def _artifact_file_present(bundle: CodeReviewBundle, file_key: str) -> bool:
    """Return True if an artifact-bundle or observation exposes the file_key."""
    for artifact_key in ("analysis_bundle", "observation"):
        files = _mapping(_artifact_dict(bundle, artifact_key).get("files"))
        if _string_present(files.get(file_key)):
            return True
    return False


def hrf_model_declared(bundle: CodeReviewBundle) -> bool:
    """Return True if review_context declares an HRF model."""
    review_context = _review_context(bundle)
    if _string_present(review_context.get("hrf_model")):
        return True
    design_model = _mapping(review_context.get("design_model"))
    return _string_present(design_model.get("hrf_model")) or _string_present(
        design_model.get("basis_set")
    )


def autocorrelation_model_declared(bundle: CodeReviewBundle) -> bool:
    """Return True if review_context declares an autocorrelation / noise model."""
    review_context = _review_context(bundle)
    if _has_value(review_context, _AUTOCORRELATION_KEYS):
        return True
    return _has_value(
        _mapping(review_context.get("design_model")), _AUTOCORRELATION_KEYS
    )


def design_matrix_declared(bundle: CodeReviewBundle) -> bool:
    """Return True if a design matrix path/file is declared via any producer path."""
    review_context = _review_context(bundle)
    if _string_present(review_context.get("design_matrix_path")):
        return True
    design_model = _mapping(review_context.get("design_model"))
    if _string_present(design_model.get("design_matrix_path")):
        return True
    return _artifact_file_present(bundle, "design_matrix")


def contrast_table_declared(bundle: CodeReviewBundle) -> bool:
    """Return True if a contrast table path/file is declared via any producer path."""
    review_context = _review_context(bundle)
    if _string_present(review_context.get("contrast_table_path")):
        return True
    statistical_inference = _mapping(review_context.get("statistical_inference"))
    if _string_present(statistical_inference.get("contrast_table_path")):
        return True
    return _artifact_file_present(bundle, "contrast_table")


def correction_summary_declared(bundle: CodeReviewBundle) -> bool:
    """Return True if a multiple-comparison correction summary is declared."""
    review_context = _review_context(bundle)
    if _string_present(review_context.get("correction_summary_path")):
        return True
    statistical_inference = _mapping(review_context.get("statistical_inference"))
    if _string_present(statistical_inference.get("correction_summary_path")):
        return True
    if _string_present(statistical_inference.get("threshold_summary_path")):
        return True
    return _artifact_file_present(bundle, "correction_summary_json")


def cluster_table_declared(bundle: CodeReviewBundle) -> bool:
    """Return True if a cluster table path/file is declared via any producer path."""
    review_context = _review_context(bundle)
    if _string_present(review_context.get("cluster_table_path")):
        return True
    statistical_inference = _mapping(review_context.get("statistical_inference"))
    if _string_present(statistical_inference.get("cluster_table_path")):
        return True
    return _artifact_file_present(bundle, "cluster_table")


def peak_table_declared(bundle: CodeReviewBundle) -> bool:
    """Return True if a peak table path/file is declared via any producer path."""
    review_context = _review_context(bundle)
    if _string_present(review_context.get("peak_table_path")):
        return True
    statistical_inference = _mapping(review_context.get("statistical_inference"))
    if _string_present(statistical_inference.get("peak_table_path")):
        return True
    return _artifact_file_present(bundle, "peak_table")


def _nonempty_list_at(mapping: Mapping[str, object], keys: tuple[str, ...]) -> bool:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, list) and value:
            return True
    return False


def confound_columns_declared(bundle: CodeReviewBundle) -> bool:
    """Return True if a non-empty confound column list is declared."""
    review_context = _review_context(bundle)
    if _nonempty_list_at(review_context, _CONFOUND_COLUMN_KEYS):
        return True
    preprocessing = _mapping(review_context.get("preprocessing"))
    if _nonempty_list_at(preprocessing, _CONFOUND_COLUMN_KEYS):
        return True
    design_model = _mapping(review_context.get("design_model"))
    return _nonempty_list_at(design_model, _CONFOUND_COLUMN_KEYS)


def nested_cv_structure_declared(bundle: CodeReviewBundle) -> bool:
    """Return True if nested CV flag AND outer/inner fold metadata are both declared."""
    review_context = _review_context(bundle)
    selection = _mapping(review_context.get("selection"))

    nested_top = review_context.get("nested_cv")
    nested_section = selection.get("nested_cv")
    nested_flag_set = (
        nested_top in (True,)
        or nested_section in (True,)
        or isinstance(nested_top, dict)
        or isinstance(nested_section, dict)
    )
    if not nested_flag_set:
        return False

    # Need at least one outer/inner fold structure descriptor.
    if _has_value(selection, _NESTED_CV_STRUCTURE_KEYS):
        return True
    if _has_value(review_context, _NESTED_CV_STRUCTURE_KEYS):
        return True
    # Nested-cv dict payloads may carry the structure inline.
    for candidate in (nested_top, nested_section):
        if isinstance(candidate, dict) and _has_value(
            candidate, _NESTED_CV_STRUCTURE_KEYS + ("inner_folds", "outer_folds")
        ):
            return True
    return False


def subject_manifest_declared(bundle: CodeReviewBundle) -> bool:
    """Return True if review_context declares subject manifest metadata."""
    review_context = _review_context(bundle)
    if _has_value(review_context, _SUBJECT_MANIFEST_KEYS):
        return True
    split = _mapping(review_context.get("split"))
    return _has_value(split, _SUBJECT_MANIFEST_KEYS)


def sensitivity_package_declared(bundle: CodeReviewBundle) -> bool:
    """Return True if a non-empty sensitivity package is declared."""
    review_context = _review_context(bundle)
    if _nonempty_list_at(review_context, _SENSITIVITY_KEYS):
        return True
    sensitivity = _mapping(review_context.get("sensitivity"))
    return _nonempty_list_at(sensitivity, _SENSITIVITY_KEYS)


_CHECK_FUNCTIONS = {
    "random_seed_pinned": random_seed_pinned,
    "atlas_version_pinned": atlas_version_pinned,
    "ordering_rule_declared": ordering_rule_declared,
    "target_declared": target_declared,
    "evaluation_protocol_declared": evaluation_protocol_declared,
    "subject_alignment_declared": subject_alignment_declared,
    "split_metadata_declared": split_metadata_declared,
    "null_model_declared": null_model_declared,
    "preprocessing_choices_declared": preprocessing_choices_declared,
    "hrf_model_declared": hrf_model_declared,
    "autocorrelation_model_declared": autocorrelation_model_declared,
    "design_matrix_declared": design_matrix_declared,
    "contrast_table_declared": contrast_table_declared,
    "correction_summary_declared": correction_summary_declared,
    "cluster_table_declared": cluster_table_declared,
    "peak_table_declared": peak_table_declared,
    "confound_columns_declared": confound_columns_declared,
    "nested_cv_structure_declared": nested_cv_structure_declared,
    "subject_manifest_declared": subject_manifest_declared,
    "sensitivity_package_declared": sensitivity_package_declared,
}


def build_completeness_checklist(bundle: CodeReviewBundle) -> dict[str, bool]:
    """Build a completeness checklist for the bundle."""
    contract = _review_contract(bundle)
    requested = _requested_checks(contract)

    checklist: dict[str, bool] = {}
    for key in requested:
        check_fn = _CHECK_FUNCTIONS.get(str(key))
        if check_fn is None:
            continue
        checklist[str(key)] = check_fn(bundle)
    return checklist
