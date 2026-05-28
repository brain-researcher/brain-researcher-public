"""High-precision predictive integrity checks for scientific review.

These checks are intentionally narrow: they only fire on explicit provenance
or metadata that demonstrates CV leakage or train/test split violations.
They do not infer leakage from prose, heuristics, or weak suspicion.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from brain_researcher.core.contracts.code_review import CodeReviewBundle, ReviewFinding

_PREDICTIVE_REASON_TAGS = ("predictive", "generalization")
_LEAKAGE_REASON_TAGS = ("leakage",)
_SPLIT_INTEGRITY_REASON_TAGS = ("leakage", "generalization")
_FISHER_Z_INPUT_DOMAIN_REASON_TAGS = (
    "predictive",
    "preprocessing",
    "data_contract",
)
_FISHER_Z_APPLIED_KEYS = (
    "fisher_z_applied",
    "fisher_z",
    "apply_fisher_z",
    "fisher_z_transform",
    "fisher_z_enabled",
)
_FISHER_Z_STATE_KEYS = (
    "transform_state",
    "input_transform_state",
    "input_state",
    "feature_state",
)
_FISHER_Z_STATE_TOKENS = frozenset(
    {
        "alreadyfisherz",
        "fisherz",
        "correlationz",
    }
)
_OUTSIDE_UNIT_INTERVAL_FRACTION_KEYS = (
    "outside_unit_interval_fraction",
    "outside_unit_fraction",
    "out_of_unit_interval_fraction",
    "fraction_outside_unit_interval",
    "input_outside_unit_interval_fraction",
)

_TRAIN_KEYS = (
    "train_ids",
    "train_subject_ids",
    "train_participant_ids",
    "train_session_ids",
    "train_run_ids",
    "train_fold_ids",
    "train_entity_ids",
)
_TEST_KEYS = (
    "test_ids",
    "test_subject_ids",
    "test_participant_ids",
    "test_session_ids",
    "test_run_ids",
    "test_fold_ids",
    "test_entity_ids",
)
_VAL_KEYS = (
    "validation_ids",
    "val_ids",
    "validation_subject_ids",
    "validation_participant_ids",
    "validation_session_ids",
    "validation_run_ids",
    "validation_fold_ids",
)
_PREDICTIVE_CONTEXT_KEYS = (
    "split_manifest",
    "cv_manifest",
    "split_strategy",
    "split_strategy_detail",
    "split_unit",
    "train_test_independence",
    "grouped_split_keys",
)
_LEAKAGE_FLAG_KEYS = (
    "leakage",
    "circularity",
    "cv_leakage",
    "train_test_contamination",
    "test_contamination",
    "fit_on_full_data",
    "applied_to_test_set",
)
_PROVENANCE_SCOPE_KEYS = (
    "feature_selection_scope",
    "standardization_scope",
    "harmonization_fit_scope",
    "confound_regression_scope",
    "normalization_scope",
    "imputation_scope",
    "dimensionality_reduction_scope",
    "selection_scope",
    "fit_scope",
)
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
    }
)
_SAFE_SCOPES = frozenset(
    {
        "train_only",
        "training_only",
        "train_fold",
        "train_fold_only",
        "within_train_fold",
        "train_cv_fold",
        "fit_on_train_fold",
    }
)


def _artifact_dict(bundle: CodeReviewBundle, key: str) -> dict[str, Any]:
    value = bundle.observed_artifacts.get(key)
    return value if isinstance(value, dict) else {}


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _review_context(bundle: CodeReviewBundle) -> dict[str, Any]:
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


def _context_text(context: Mapping[str, object], key: str) -> str:
    value = context.get(key)
    return str(value).strip().lower() if value is not None else ""


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        raw_values = [value]
    elif isinstance(value, Iterable):
        raw_values = list(value)
    else:
        return []

    cleaned: list[str] = []
    for item in raw_values:
        text = str(item).strip()
        if text:
            cleaned.append(text)
    return cleaned


def _id_set(context: Mapping[str, object], keys: tuple[str, ...]) -> set[str]:
    values: set[str] = set()
    for key in keys:
        raw = context.get(key)
        if isinstance(raw, str):
            raw_items = [raw]
        elif isinstance(raw, Iterable):
            raw_items = list(raw)
        else:
            continue
        for item in raw_items:
            text = str(item).strip()
            if text:
                values.add(text)
    return values


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


def _float_value(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("%"):
            text = text[:-1].strip()
            try:
                return float(text) / 100.0
            except ValueError:
                return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _normalize_scope(value: object) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _normalize_transform_state(value: object) -> str:
    return "".join(char for char in str(value).strip().lower() if char.isalnum())


def _flatten_scalar_values(value: object) -> list[str]:
    if isinstance(value, Mapping):
        flattened: list[str] = []
        for nested_value in value.values():
            flattened.extend(_flatten_scalar_values(nested_value))
        return flattened
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        flattened = []
        for item in value:
            flattened.extend(_flatten_scalar_values(item))
        return flattened
    if value is None:
        return []
    return [str(value)]


def _fisher_z_applied_evidence(
    sections: list[tuple[str, Mapping[str, object]]],
) -> list[str]:
    evidence: list[str] = []
    for path, section in sections:
        for key in _FISHER_Z_APPLIED_KEYS:
            explicit = _explicit_bool(section.get(key))
            if explicit:
                evidence.append(f"{path}.{key}=True")
    return evidence


def _outside_unit_fraction_evidence(
    sections: list[tuple[str, Mapping[str, object]]],
) -> list[str]:
    evidence: list[str] = []
    for path, section in sections:
        for key in _OUTSIDE_UNIT_INTERVAL_FRACTION_KEYS:
            value = _float_value(section.get(key))
            if value is not None and value > 0.0:
                evidence.append(f"{path}.{key}={value:g}")
    return evidence


def _fisher_z_state_evidence(
    sections: list[tuple[str, Mapping[str, object]]],
) -> list[str]:
    evidence: list[str] = []
    for path, section in sections:
        for key in _FISHER_Z_STATE_KEYS:
            raw_value = section.get(key)
            if raw_value is None:
                continue
            for value in _flatten_scalar_values(raw_value):
                if _normalize_transform_state(value) in _FISHER_Z_STATE_TOKENS:
                    evidence.append(f"{path}.{key}={value}")
                    break
    return evidence


def _find_scope_violation(context: Mapping[str, object]) -> tuple[str, str] | None:
    for key in _PROVENANCE_SCOPE_KEYS:
        raw_value = context.get(key)
        if raw_value is None:
            continue
        if isinstance(raw_value, dict):
            raw_value = raw_value.get("scope") or raw_value.get("fit_scope")
        scope = _normalize_scope(raw_value)
        if not scope:
            continue
        if scope in _SAFE_SCOPES:
            continue
        if (
            scope in _DANGEROUS_SCOPES
            or "outside_cv" in scope
            or "full_dataset" in scope
        ):
            return key, scope
    return None


def _explicit_leakage_flags(context: Mapping[str, object]) -> list[str]:
    flags: list[str] = []
    for key in _LEAKAGE_FLAG_KEYS:
        explicit = _explicit_bool(context.get(key))
        if explicit:
            flags.append(key)
    return flags


def predictive_fisher_z_input_domain_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Flag Fisher-z transforms applied to non-correlation inputs.

    Fisher-z is only defined for raw correlation coefficients in [-1, 1].
    This check fires only on explicit review-context diagnostics showing
    non-correlation inputs or an already-Fisher-z-transformed input state.
    """

    context = _review_context(bundle)
    preprocessing_context = _mapping(context.get("preprocessing"))
    feature_diagnostics_context = _mapping(context.get("feature_diagnostics"))
    sections: list[tuple[str, Mapping[str, object]]] = [
        ("review_context", context),
        ("review_context.preprocessing", preprocessing_context),
        ("review_context.feature_diagnostics", feature_diagnostics_context),
    ]

    fisher_z_evidence = _fisher_z_applied_evidence(sections)
    if not fisher_z_evidence:
        return None

    outside_unit_evidence = _outside_unit_fraction_evidence(
        [
            ("review_context.preprocessing", preprocessing_context),
            ("review_context.feature_diagnostics", feature_diagnostics_context),
        ]
    )
    transform_state_evidence = _fisher_z_state_evidence(sections)

    if not outside_unit_evidence and not transform_state_evidence:
        return None

    return ReviewFinding(
        rule_id="REVIEW_PREDICTIVE_FISHER_Z_INPUT_DOMAIN",
        severity="error",
        action="block",
        message=(
            "Predictive preprocessing applies Fisher-z to inputs that are not "
            "valid raw correlations in [-1, 1]."
        ),
        suggested_fix=(
            "Apply Fisher-z only once to raw correlation coefficients. Skip the "
            "transform for already-z-scored features, inverse-transform them "
            "before Fisher-z, or regenerate features from bounded correlations "
            "with input-domain diagnostics recorded."
        ),
        kg_evidence=[
            *fisher_z_evidence,
            *outside_unit_evidence,
            *transform_state_evidence,
        ],
        reason_tags=list(_FISHER_Z_INPUT_DOMAIN_REASON_TAGS),
    )


def predictive_cv_leakage_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Flag explicit CV leakage provenance in predictive review contexts.

    This only fires when the bundle includes explicit provenance indicating
    leakage or test contamination, such as a `fit_on_full_data` flag or a
    provenance scope like `full_dataset` / `outside_cv`.
    """

    context = _review_context(bundle)
    split_context = _mapping(context.get("split"))
    preprocessing_context = _mapping(context.get("preprocessing"))
    provenance_context = _mapping(context.get("provenance"))

    explicit_flags = []
    explicit_flags.extend(_explicit_leakage_flags(context))
    explicit_flags.extend(_explicit_leakage_flags(split_context))
    explicit_flags.extend(_explicit_leakage_flags(preprocessing_context))
    explicit_flags.extend(_explicit_leakage_flags(provenance_context))

    scope_hit = _find_scope_violation(context)
    if scope_hit is None:
        scope_hit = _find_scope_violation(preprocessing_context)
    if scope_hit is None:
        scope_hit = _find_scope_violation(provenance_context)

    if not explicit_flags and scope_hit is None:
        return None

    evidence: list[str] = []
    finding_tags = list(_PREDICTIVE_REASON_TAGS)
    if explicit_flags:
        unique_flags = sorted(set(explicit_flags))
        evidence.append(f"review_context.explicit_flags={unique_flags}")
        finding_tags.extend(_LEAKAGE_REASON_TAGS)
    if scope_hit is not None:
        key, scope = scope_hit
        evidence.append(f"review_context.{key}={scope}")
        finding_tags.append("leakage")

    finding_tags = list(dict.fromkeys(finding_tags))
    return ReviewFinding(
        rule_id="REVIEW_PREDICTIVE_CV_LEAKAGE",
        severity="error",
        action="block",
        message=(
            "Predictive provenance explicitly indicates CV leakage or test "
            "contamination."
        ),
        suggested_fix=(
            "Move feature selection, normalization, harmonization, and similar "
            "data-dependent transforms inside the training fold only, and "
            "remove any explicit full-dataset or test-set fit provenance."
        ),
        kg_evidence=evidence,
        reason_tags=finding_tags,
    )


def predictive_split_integrity_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Flag explicit train/test split overlap in predictive review contexts."""

    context = _review_context(bundle)
    split_context = _mapping(context.get("split"))
    provenance_context = _mapping(context.get("provenance"))

    if _explicit_bool(context.get("train_test_independence")) is False:
        return ReviewFinding(
            rule_id="REVIEW_PREDICTIVE_SPLIT_INTEGRITY",
            severity="error",
            action="block",
            message=(
                "Predictive provenance explicitly marks train/test independence as false."
            ),
            suggested_fix=(
                "Use a subject-, session-, or group-aware split that keeps all "
                "dependent observations on one side of the partition."
            ),
            kg_evidence=["review_context.train_test_independence=False"],
            reason_tags=list(_SPLIT_INTEGRITY_REASON_TAGS),
        )

    explicit_splits = [
        ("train", _id_set(context, _TRAIN_KEYS) | _id_set(split_context, _TRAIN_KEYS)),
        ("test", _id_set(context, _TEST_KEYS) | _id_set(split_context, _TEST_KEYS)),
        ("validation", _id_set(context, _VAL_KEYS) | _id_set(split_context, _VAL_KEYS)),
    ]

    train_ids = explicit_splits[0][1]
    test_ids = explicit_splits[1][1]
    val_ids = explicit_splits[2][1]

    if not train_ids or not test_ids:
        # Only act when the bundle provides explicit train/test membership.
        return None

    overlap_train_test = sorted(train_ids & test_ids)
    overlap_train_val = sorted(train_ids & val_ids)
    overlap_test_val = sorted(test_ids & val_ids)

    if not overlap_train_test and not overlap_train_val and not overlap_test_val:
        return None

    overlaps: list[str] = []
    if overlap_train_test:
        overlaps.append(f"train/test overlap={overlap_train_test}")
    if overlap_train_val:
        overlaps.append(f"train/validation overlap={overlap_train_val}")
    if overlap_test_val:
        overlaps.append(f"test/validation overlap={overlap_test_val}")

    evidence: list[str] = [
        f"review_context.split_keys={sorted(_PREDICTIVE_CONTEXT_KEYS)}"
    ]
    if provenance_context:
        evidence.append(
            "review_context.provenance_keys="
            f"{sorted(k for k in provenance_context.keys() if isinstance(k, str))}"
        )
    evidence.extend(overlaps)

    return ReviewFinding(
        rule_id="REVIEW_PREDICTIVE_SPLIT_INTEGRITY",
        severity="error",
        action="block",
        message=(
            "Predictive split provenance shows overlapping train / test " "membership."
        ),
        suggested_fix=(
            "Regenerate the split manifest so the training, validation, and "
            "test partitions are mutually exclusive at the declared split unit."
        ),
        kg_evidence=evidence,
        reason_tags=list(_SPLIT_INTEGRITY_REASON_TAGS),
    )


__all__ = [
    "predictive_fisher_z_input_domain_check",
    "predictive_cv_leakage_check",
    "predictive_split_integrity_check",
]
