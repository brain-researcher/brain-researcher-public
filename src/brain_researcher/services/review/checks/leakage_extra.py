"""Additional deterministic leakage / non-independence checks.

These checks close gaps left by ``predictive_integrity.py`` and
``neuroai_validity.py``. They target failure modes from the scientific-review
failure-mode registry that have no dedicated named check yet:

- per-step preprocessing fit-scope leakage (STANDARDIZATION_OUTSIDE_CV,
  HARMONIZATION_OUTSIDE_CV, CONFOUND_REGRESSION_OUTSIDE_CV, and the rest of the
  ``REVIEW_LEAKAGE_*_FULL`` family), driven by the registry's canonical
  ``fit_scope_by_step`` mapping or a structured ``pipeline_steps[].fit_scope``
  provenance list;
- pseudoreplication / repeated-measures-as-independent
  (REVIEW_LEAKAGE_REPEATED_AS_INDEP);
- brain-map correspondence claims reported without a spatial-autocorrelation
  null (REVIEW_INFERENCE_NO_SPIN_TEST).

Like the sibling modules, every check is intentionally conservative: it only
fires on explicit review-context provenance (e.g. ``pipeline_steps[].fit_scope``
or ``fit_scope_by_step``), never on prose, heuristics, or weak suspicion.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from brain_researcher.core.contracts.code_review import CodeReviewBundle, ReviewFinding

# --------------------------------------------------------------------------- #
# Per-step fit-scope leakage
# --------------------------------------------------------------------------- #

# Canonical preprocessing step -> registry rule id. Step names are normalized
# (lower, underscores) and matched against several common aliases so that both
# the registry's `fit_scope_by_step.<step>` mapping and a structured
# `pipeline_steps[].fit_scope` list resolve to the right rule.
_STEP_RULE_IDS: dict[str, str] = {
    "feature_selection": "REVIEW_LEAKAGE_FEATURE_SELECT_FULL",
    "scaler": "REVIEW_LEAKAGE_SCALER_FULL",
    "standardization": "REVIEW_LEAKAGE_SCALER_FULL",
    "pca": "REVIEW_LEAKAGE_PCA_FULL",
    "dimensionality_reduction": "REVIEW_LEAKAGE_PCA_FULL",
    "residualizer": "REVIEW_LEAKAGE_RESIDUALIZER_FULL",
    "confound_regression": "REVIEW_LEAKAGE_RESIDUALIZER_FULL",
    "confound_residualization": "REVIEW_LEAKAGE_RESIDUALIZER_FULL",
    "harmonization": "REVIEW_LEAKAGE_HARMONIZATION_FULL",
    "combat": "REVIEW_LEAKAGE_HARMONIZATION_FULL",
    "variance_mask": "REVIEW_LEAKAGE_VARIANCE_MASK_FULL",
    "imputer": "REVIEW_LEAKAGE_IMPUTE_FULL",
    "imputation": "REVIEW_LEAKAGE_IMPUTE_FULL",
    "target_residualizer": "REVIEW_LEAKAGE_TARGET_RESIDUALIZER_FULL",
    "target_transformer": "REVIEW_LEAKAGE_TARGET_SCALER_FULL",
    "target_scaler": "REVIEW_LEAKAGE_TARGET_SCALER_FULL",
}

# Steps whose registry severity is `error` rather than `critical`.
_ERROR_SEVERITY_STEPS = frozenset({"variance_mask", "imputer", "imputation"})

# Mapping-shaped fit-scope provenance keys (registry canonical form first).
_FIT_SCOPE_MAP_KEYS = (
    "fit_scope_by_step",
    "fit_scopes",
    "preprocessing_fit_scope_by_step",
)
# Structured per-step list provenance keys.
_PIPELINE_STEPS_KEYS = (
    "pipeline_steps",
    "preprocessing_steps",
    "pipeline_step_provenance",
)
_STEP_NAME_KEYS = ("step", "name", "step_name", "id", "step_id")
_STEP_SCOPE_KEYS = ("fit_scope", "scope", "fit_on", "fitted_on")

# Scopes that are explicitly safe (fold-local). Anything else explicit that is
# not safe is treated as leakage.
_SAFE_SCOPES = frozenset(
    {
        "train_only",
        "training_only",
        "train_fold",
        "train_fold_only",
        "within_train_fold",
        "train_cv_fold",
        "fit_on_train_fold",
        "per_fold",
        "per_training_fold",
        "inner_train_fold",
    }
)
# Scopes that are unambiguously leaky.
_DANGEROUS_SCOPES = frozenset(
    {
        "all_data",
        "full_data",
        "full_dataset",
        "entire_dataset",
        "global",
        "global_fit",
        "outside_cv",
        "outside_cross_validation",
        "pre_cv",
        "before_cv",
        "test_set",
        "held_out_set",
        "held_out",
        "evaluation_set",
        "whole_sample",
        "full_sample",
    }
)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _artifact_dict(bundle: CodeReviewBundle, key: str) -> dict[str, Any]:
    value = bundle.observed_artifacts.get(key)
    return value if isinstance(value, dict) else {}


def _review_context(bundle: CodeReviewBundle) -> dict[str, Any]:
    """Merge every place review_context can live, last-writer-wins.

    Mirrors the discovery order used by predictive_integrity / neuroai_validity
    so that all leakage checks see the same provenance surface.
    """

    candidates: list[dict[str, Any]] = []

    if isinstance(getattr(bundle, "review_context", None), dict):
        candidates.append(dict(bundle.review_context))

    for key in ("review_context", "source_summary"):
        artifact = _artifact_dict(bundle, key)
        if key == "source_summary":
            nested = artifact.get("review_context")
            if isinstance(nested, dict):
                candidates.append(dict(nested))
        else:
            candidates.append(artifact)

    contract = _artifact_dict(bundle, "review_contract")
    contract_context = contract.get("review_context")
    if isinstance(contract_context, dict):
        candidates.append(dict(contract_context))

    analysis_bundle = _artifact_dict(bundle, "analysis_bundle")
    analysis_context = analysis_bundle.get("review_context")
    if isinstance(analysis_context, dict):
        candidates.append(dict(analysis_context))

    merged: dict[str, Any] = {}
    for candidate in candidates:
        merged.update(candidate)
    return merged


def _nested_mapping(context: Mapping[str, object], key: str) -> Mapping[str, object]:
    return _mapping(context.get(key))


def _normalize(value: object) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _explicit_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    return None


def _int_value(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return None
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
    return None


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        raw = [value]
    elif isinstance(value, Iterable):
        raw = list(value)
    else:
        return []
    cleaned: list[str] = []
    for item in raw:
        text = str(item).strip()
        if text:
            cleaned.append(text)
    return cleaned


def _resolve_step_rule(step_name: str) -> tuple[str, str] | None:
    """Return (canonical_step, rule_id) for a normalized step name, or None."""

    normalized = _normalize(step_name)
    if normalized in _STEP_RULE_IDS:
        return normalized, _STEP_RULE_IDS[normalized]
    # Allow suffixed/aliased names like "standard_scaler" or "combat_harmonize"
    # to resolve to the closest canonical step via substring containment.
    for canonical, rule_id in _STEP_RULE_IDS.items():
        if canonical in normalized:
            return canonical, rule_id
    return None


def _scope_is_leaky(scope_value: object) -> str | None:
    """Return the normalized scope string when it is explicitly leaky."""

    scope = _normalize(scope_value)
    if not scope or scope in _SAFE_SCOPES:
        return None
    if (
        scope in _DANGEROUS_SCOPES
        or "outside_cv" in scope
        or "full_data" in scope
        or "full_dataset" in scope
        or "test_set" in scope
        or "held_out" in scope
        or "all_data" in scope
    ):
        return scope
    return None


def _scope_value(raw_scope: object) -> object:
    if isinstance(raw_scope, Mapping):
        return raw_scope.get("scope") or raw_scope.get("fit_scope")
    return raw_scope


def _collect_fit_scope_violations(
    context: Mapping[str, object],
) -> list[tuple[str, str, str]]:
    """Collect (canonical_step, rule_id, scope) tuples for leaky steps.

    Reads both the canonical `fit_scope_by_step` mapping form and a structured
    `pipeline_steps[].fit_scope` list, in `review_context` and its
    `preprocessing` sub-section.
    """

    sections: list[Mapping[str, object]] = [
        context,
        _nested_mapping(context, "preprocessing"),
        _nested_mapping(context, "provenance"),
    ]

    violations: dict[str, tuple[str, str]] = {}

    # 1. Mapping form: {"standardization": "full_dataset", ...}
    for section in sections:
        for map_key in _FIT_SCOPE_MAP_KEYS:
            scope_map = _mapping(section.get(map_key))
            for step_name, raw_scope in scope_map.items():
                resolved = _resolve_step_rule(str(step_name))
                if resolved is None:
                    continue
                canonical, rule_id = resolved
                leaky = _scope_is_leaky(_scope_value(raw_scope))
                if leaky is not None:
                    violations[canonical] = (rule_id, leaky)

    # 2. Structured list form: [{"step": "standardization", "fit_scope": "..."}]
    for section in sections:
        for list_key in _PIPELINE_STEPS_KEYS:
            raw_list = section.get(list_key)
            if not isinstance(raw_list, Iterable) or isinstance(raw_list, str | bytes):
                continue
            for entry in raw_list:
                if not isinstance(entry, Mapping):
                    continue
                step_name = next(
                    (
                        str(entry[name_key])
                        for name_key in _STEP_NAME_KEYS
                        if entry.get(name_key) not in (None, "")
                    ),
                    "",
                )
                if not step_name:
                    continue
                resolved = _resolve_step_rule(step_name)
                if resolved is None:
                    continue
                canonical, rule_id = resolved
                raw_scope = next(
                    (
                        entry[scope_key]
                        for scope_key in _STEP_SCOPE_KEYS
                        if entry.get(scope_key) not in (None, "")
                    ),
                    None,
                )
                if raw_scope is None:
                    continue
                leaky = _scope_is_leaky(_scope_value(raw_scope))
                if leaky is not None:
                    violations[canonical] = (rule_id, leaky)

    return [
        (canonical, rule_id, scope)
        for canonical, (rule_id, scope) in sorted(violations.items())
    ]


def leakage_preprocessing_fit_scope_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Block per-step preprocessing fit-scope leakage from explicit provenance.

    Fires only when explicit step-level provenance (`fit_scope_by_step` mapping
    or `pipeline_steps[].fit_scope` list) shows a data-dependent transform
    (standardization, harmonization, confound regression, PCA, imputation,
    feature selection, ...) fitted outside the training fold.
    """

    context = _review_context(bundle)
    violations = _collect_fit_scope_violations(context)
    if not violations:
        return None

    rule_ids = sorted({rule_id for _, rule_id, _ in violations})
    leaky_steps = [canonical for canonical, _, _ in violations]
    is_critical = any(
        canonical not in _ERROR_SEVERITY_STEPS for canonical, _, _ in violations
    )

    evidence = [
        f"review_context.fit_scope[{canonical}]={scope} -> {rule_id}"
        for canonical, rule_id, scope in violations
    ]
    evidence.append(f"registry_rule_ids={rule_ids}")

    return ReviewFinding(
        rule_id="REVIEW_LEAKAGE_PREPROCESSING_FIT_SCOPE",
        severity="critical" if is_critical else "error",
        action="block",
        message=(
            "Explicit pipeline provenance shows data-dependent preprocessing "
            f"fitted outside the training fold for: {', '.join(leaky_steps)}. "
            "Fitting these transforms on full / held-out data leaks information "
            "into cross-validation and inflates performance."
        ),
        suggested_fix=(
            "Move each flagged step inside the cross-validation loop so it is fit "
            "on the training fold only (e.g. wrap it in an sklearn Pipeline that is "
            "fit per fold), then re-emit fit_scope_by_step with train_fold_only."
        ),
        kg_evidence=evidence,
        reason_tags=["leakage", "predictive", "generalization"],
    )


# --------------------------------------------------------------------------- #
# Pseudoreplication / repeated measures counted as independent
# --------------------------------------------------------------------------- #

_DECLARED_N_KEYS = (
    "declared_n",
    "n_observations",
    "n_samples",
    "n_rows",
    "sample_size",
    "n",
)
_UNIQUE_SUBJECT_KEYS = (
    "n_unique_subjects",
    "n_subjects",
    "unique_subject_count",
    "n_unique_participants",
    "n_participants",
)
_SUBJECT_ID_LIST_KEYS = (
    "subject_ids",
    "participant_ids",
    "subjects",
)
_INDEPENDENCE_UNIT_KEYS = (
    "independence_unit",
    "observation_unit",
    "inference_unit",
    "statistical_unit",
)


def _pseudoreplication_sections(
    context: Mapping[str, object],
) -> list[Mapping[str, object]]:
    return [
        context,
        _nested_mapping(context, "sample"),
        _nested_mapping(context, "design"),
        _nested_mapping(context, "statistics"),
        _nested_mapping(context, "construct_validity"),
    ]


def _first_int(
    sections: list[Mapping[str, object]], keys: tuple[str, ...]
) -> int | None:
    for section in sections:
        for key in keys:
            value = _int_value(section.get(key))
            if value is not None and value > 0:
                return value
    return None


def _unique_subject_count(sections: list[Mapping[str, object]]) -> int | None:
    direct = _first_int(sections, _UNIQUE_SUBJECT_KEYS)
    if direct is not None:
        return direct
    for section in sections:
        for key in _SUBJECT_ID_LIST_KEYS:
            ids = _string_list(section.get(key))
            if ids:
                return len({value.lower() for value in ids})
    return None


def leakage_pseudoreplication_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Flag repeated measurements counted as independent observations.

    Implements REVIEW_LEAKAGE_REPEATED_AS_INDEP. Fires only when explicit
    provenance gives a declared observation count that exceeds the number of
    unique subjects AND there is no explicit grouped / mixed-effects accounting
    declared for the repeated structure.
    """

    context = _review_context(bundle)
    sections = _pseudoreplication_sections(context)

    declared_n = _first_int(sections, _DECLARED_N_KEYS)
    unique_subjects = _unique_subject_count(sections)
    if declared_n is None or unique_subjects is None:
        return None
    if declared_n <= unique_subjects:
        return None

    # Respect explicit accounting for the repeated structure.
    for section in sections:
        if _explicit_bool(section.get("repeated_measures_modeled")) is True:
            return None
        if _explicit_bool(section.get("mixed_effects_model")) is True:
            return None
        unit = section.get("independence_unit") or section.get("inference_unit")
        if unit is not None and _normalize(unit) in {
            "subject",
            "participant",
            "subject_id",
            "participant_id",
        }:
            # Inference declared at the subject level already accounts for it.
            return None

    evidence = [
        f"review_context.declared_n={declared_n}",
        f"review_context.n_unique_subjects={unique_subjects}",
        "registry_rule_ids=['REVIEW_LEAKAGE_REPEATED_AS_INDEP']",
    ]
    for section in sections:
        for key in _INDEPENDENCE_UNIT_KEYS:
            if section.get(key) is not None:
                evidence.append(f"review_context.{key}={_normalize(section.get(key))}")
                break

    return ReviewFinding(
        rule_id="REVIEW_LEAKAGE_REPEATED_AS_INDEP",
        severity="error",
        action="block",
        message=(
            "Explicit provenance declares more observations "
            f"({declared_n}) than unique subjects ({unique_subjects}) without "
            "modeling the repeated structure, so dependent measurements are being "
            "counted as independent (pseudoreplication)."
        ),
        suggested_fix=(
            "Aggregate to one observation per subject, or model the repeated "
            "structure with a grouped / mixed-effects design, and report inference "
            "at the subject (independence) unit."
        ),
        kg_evidence=evidence,
        reason_tags=["leakage", "pseudoreplication", "generalization"],
    )


# --------------------------------------------------------------------------- #
# Brain-map correspondence without a spatial-autocorrelation null
# --------------------------------------------------------------------------- #

_BRAINMAP_CORR_FLAG_KEYS = (
    "map_map_correlation",
    "brainmap_correlation",
    "spatial_correlation_claim",
    "map_correspondence",
    "brainmap_correspondence",
)
_SPATIAL_NULL_PRESENT_KEYS = (
    "spatial_null",
    "spatial_null_method",
    "spin_test",
    "spin_permutation",
    "variogram_null",
    "moran_spectral_randomization",
    "burt_2020",
    "spatial_null_applied",
)
_SPATIAL_NULL_VALUE_PRESENT_TOKENS = frozenset(
    {
        "spin",
        "spin_test",
        "variogram",
        "moran",
        "burt",
        "alexander_bloch",
        "vasa",
        "brainsmash",
    }
)


def _brainmap_sections(context: Mapping[str, object]) -> list[Mapping[str, object]]:
    return [
        context,
        _nested_mapping(context, "inference"),
        _nested_mapping(context, "null_model"),
        _nested_mapping(context, "spatial"),
    ]


def _brainmap_claim_present(sections: list[Mapping[str, object]]) -> str | None:
    for section in sections:
        for key in _BRAINMAP_CORR_FLAG_KEYS:
            value = section.get(key)
            if _explicit_bool(value) is True:
                return key
            if isinstance(value, Mapping) and value:
                return key
            if isinstance(value, str) and value.strip():
                normalized = _normalize(value)
                if normalized not in {"false", "no", "none", "absent"}:
                    return key
    return None


def _spatial_null_present(sections: list[Mapping[str, object]]) -> bool:
    for section in sections:
        for key in _SPATIAL_NULL_PRESENT_KEYS:
            value = section.get(key)
            if _explicit_bool(value) is True:
                return True
            if isinstance(value, str):
                normalized = _normalize(value)
                if not normalized or normalized in {
                    "false",
                    "no",
                    "none",
                    "absent",
                    "missing",
                }:
                    continue
                return True
            if isinstance(value, Mapping) and value:
                return True
    return False


def brainmap_correlation_spatial_null_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Flag brain-map correspondence claims with no spatial-autocorrelation null.

    Implements REVIEW_INFERENCE_NO_SPIN_TEST as a coverage check. This is
    distinct from `spatial_null_validity_check`, which fires when a spatial null
    is present but marked invalid; here we fire when an explicit map-map
    correlation claim is recorded and no spatial null is present at all. To stay
    high-precision, the claim must be marked explicitly absent of spatial-null
    accounting (`spatial_null_required` / `spatial_null_present`).
    """

    context = _review_context(bundle)
    sections = _brainmap_sections(context)

    claim_key = _brainmap_claim_present(sections)
    if claim_key is None:
        return None

    if _spatial_null_present(sections):
        return None

    # Require an explicit absence marker so the check never fires on partial
    # provenance where the spatial null simply was not described.
    explicit_absent = False
    for section in sections:
        if _explicit_bool(section.get("spatial_null_present")) is False:
            explicit_absent = True
        if _explicit_bool(section.get("spatial_null_applied")) is False:
            explicit_absent = True
        if _explicit_bool(
            section.get("spatial_null_required")
        ) is True and not _spatial_null_present(sections):
            explicit_absent = True
    if not explicit_absent:
        return None

    evidence = [
        f"review_context.{claim_key}=present",
        "review_context.spatial_null_present=false",
        "registry_rule_ids=['REVIEW_INFERENCE_NO_SPIN_TEST']",
    ]

    return ReviewFinding(
        rule_id="REVIEW_INFERENCE_NO_SPIN_TEST",
        severity="error",
        action="block",
        message=(
            "An explicit brain-map correspondence / map-map correlation claim is "
            "recorded with no spatial-autocorrelation null. Spatial autocorrelation "
            "inflates map-map correlations, so significance cannot be established "
            "against a naive null."
        ),
        suggested_fix=(
            "Evaluate the map-map correlation against a spatial-autocorrelation "
            "preserving null (spin test, variogram / BrainSMASH, or Moran spectral "
            "randomization) and report the spin/variogram-based p-value."
        ),
        kg_evidence=evidence,
        reason_tags=["inference", "spatial_null", "generalization"],
    )


__all__ = [
    "leakage_preprocessing_fit_scope_check",
    "leakage_pseudoreplication_check",
    "brainmap_correlation_spatial_null_check",
]
