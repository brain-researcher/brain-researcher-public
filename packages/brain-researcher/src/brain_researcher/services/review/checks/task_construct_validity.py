"""Deterministic task and construct-validity checks for scientific review.

These checks are intentionally narrow and only fire on explicit metadata:
- stimulus-class generalization without stimulus-randomization support
- explicit RT/accuracy/difficulty/eye-movement imbalance without controls
- task-FC/PPI claims with insufficient mean-evoked-response removal
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from brain_researcher.core.contracts.code_review import CodeReviewBundle, ReviewFinding

_FALSEY_STRINGS = frozenset(
    {
        "",
        "0",
        "absent",
        "false",
        "missing",
        "none",
        "no",
        "not",
        "not_available",
        "not_declared",
        "not_recorded",
        "null",
        "off",
    }
)
_STIMULUS_GENERALIZATION_KEYS = (
    "stimulus_generalization",
    "stimulus_class_generalization",
    "stimulus_generalization_scope",
    "generalization_scope",
)
_STIMULUS_RANDOMIZATION_SUPPORT_KEYS = (
    "stimulus_randomization",
    "stimulus_randomization_support",
    "stimulus_randomized",
    "stimulus_as_random_factor",
    "stimulus_random_factor",
    "independent_stimulus_set",
    "randomized_stimuli",
    "stimulus_sampling",
)
_TASK_CONNECTIVITY_FAMILIES = frozenset(
    {
        "task_fc",
        "task connectivity",
        "task_connectivity",
        "ppi",
        "psychophysiological interaction",
        "psychophysiological_interaction",
        "beta_series",
        "beta-series",
        "beta series",
        "task functional connectivity",
    }
)
_EVOKED_RESPONSE_STATUS_KEYS = (
    "mean_evoked_response_control",
    "mean_evoked_response_removed",
    "mean_evoked_response_regressed",
    "mean_evoked_response_residualized",
    "evoked_response_control",
    "evoked_response_removed",
    "evoked_response_regressed",
    "evoked_response_residualized",
    "task_evoked_response_removed",
    "task_evoked_response_control",
    "evoked_response_removal_status",
    "mean_evoked_response_status",
    "task_evoked_response_status",
)
_BAD_STATUS_TOKENS = frozenset(
    {
        "absent",
        "incomplete",
        "insufficient",
        "missing",
        "none",
        "not_removed",
        "not_regressed",
        "not_residualized",
        "partial",
        "uncontrolled",
        "unmodeled",
        "unsupported",
        "failed",
    }
)
_CONFOUND_FIELDS = {
    "reaction_time": ("reaction_time", "rt"),
    "accuracy": ("accuracy",),
    "difficulty": ("difficulty",),
    "eye_movement": ("eye_movement", "eye_tracking"),
}


def _artifact_dict(bundle: CodeReviewBundle, key: str) -> dict[str, Any]:
    artifact = bundle.observed_artifacts.get(key)
    return artifact if isinstance(artifact, dict) else {}


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _value_present(value: object) -> bool:
    return value not in (None, "", [], {}, ())


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, Iterable):
        values = list(value)
    else:
        return []
    cleaned: list[str] = []
    for item in values:
        text = str(item).strip()
        if text:
            cleaned.append(text)
    return cleaned


def _iter_strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        text = value.strip()
        if text:
            yield text
        return
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key).strip()
            if key_text:
                yield key_text
            yield from _iter_strings(nested)
        return
    if isinstance(value, Iterable):
        for item in value:
            yield from _iter_strings(item)


def _normalize_text(value: object) -> str:
    return " ".join(_iter_strings(value)).strip().lower()


def _context_reason_tags(context: Mapping[str, object]) -> set[str]:
    return {tag.lower() for tag in _string_list(context.get("reason_tags"))}


def _review_context(bundle: CodeReviewBundle) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    candidates = [
        _mapping(getattr(bundle, "review_context", {})),
        _mapping(_artifact_dict(bundle, "review_context")),
        _mapping(_artifact_dict(bundle, "review_contract").get("review_context")),
        _mapping(_artifact_dict(bundle, "analysis_bundle").get("review_context")),
        _mapping(_artifact_dict(bundle, "source_summary").get("review_context")),
    ]
    for candidate in candidates:
        if candidate:
            merged.update(candidate)
    return merged


def _nested_mapping(context: Mapping[str, object], key: str) -> dict[str, Any]:
    value = context.get(key)
    return value if isinstance(value, dict) else {}


def _task_validity_context(context: Mapping[str, object]) -> dict[str, Any]:
    task_validity = _nested_mapping(context, "task_validity")
    if task_validity:
        return task_validity
    return _nested_mapping(context, "construct_validity")


def _has_truthy_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in _FALSEY_STRINGS
    if isinstance(value, Mapping):
        return any(_has_truthy_value(nested) for nested in value.values())
    if isinstance(value, Iterable):
        return any(_has_truthy_value(item) for item in value)
    return _value_present(value)


def _explicit_confound_value(context: Mapping[str, object], label: str) -> object | None:
    construct_validity = _nested_mapping(context, "construct_validity")
    task_validity = _nested_mapping(context, "task_validity")
    imbalance = construct_validity.get("behavioral_imbalance")
    imbalance_mapping = imbalance if isinstance(imbalance, Mapping) else {}

    if label in imbalance_mapping:
        return imbalance_mapping.get(label)

    for section in (construct_validity, task_validity, context):
        for token in _CONFOUND_FIELDS[label]:
            if token in section:
                return section.get(token)
    return None


def _controlled_covariates(context: Mapping[str, object]) -> set[str]:
    construct_validity = _nested_mapping(context, "construct_validity")
    task_validity = _nested_mapping(context, "task_validity")
    preprocessing = _nested_mapping(context, "preprocessing")

    covariates: set[str] = set()
    for section in (
        construct_validity,
        task_validity,
        preprocessing,
    ):
        for key in (
            "controlled_covariates",
            "behavioral_covariates",
            "control_variables",
            "confounds",
            "confound_columns",
            "confound_regression_scope",
        ):
            covariates.update(
                token.lower() for token in _string_list(section.get(key))
            )

    control_strategy = _normalize_text(construct_validity.get("control_strategy"))
    if control_strategy:
        for label, tokens in _CONFOUND_FIELDS.items():
            if any(token in control_strategy for token in tokens):
                covariates.add(label)
                covariates.update(tokens)

    return covariates


def _generalization_scope_text(value: object) -> str:
    if isinstance(value, Mapping):
        for key in ("scope", "generalization_scope", "claim", "description", "text"):
            nested = value.get(key)
            if nested is not None:
                text = _normalize_text(nested)
                if text:
                    return text
        return _normalize_text(value)
    return _normalize_text(value)


def _stimulus_generalization_request(context: Mapping[str, object]) -> tuple[str, object] | None:
    task_validity = _nested_mapping(context, "task_validity")
    construct_validity = _nested_mapping(context, "construct_validity")
    for source_name, source in (
        ("review_context.task_validity", task_validity),
        ("review_context.construct_validity", construct_validity),
        ("review_context", context),
    ):
        for key in _STIMULUS_GENERALIZATION_KEYS:
            value = source.get(key)
            if _value_present(value):
                return f"{source_name}.{key}", value
    return None


def _stimulus_randomization_support(context: Mapping[str, object]) -> tuple[str, object] | None:
    task_validity = _nested_mapping(context, "task_validity")
    construct_validity = _nested_mapping(context, "construct_validity")
    for source_name, source in (
        ("review_context.task_validity", task_validity),
        ("review_context.construct_validity", construct_validity),
        ("review_context", context),
    ):
        for key in _STIMULUS_RANDOMIZATION_SUPPORT_KEYS:
            value = source.get(key)
            if _value_present(value):
                return f"{source_name}.{key}", value

    randomization_sections = (
        _nested_mapping(task_validity, "stimulus_randomization"),
        _nested_mapping(construct_validity, "stimulus_randomization"),
        _nested_mapping(context, "stimulus_randomization"),
    )
    for section_name, section in zip(
        (
            "review_context.task_validity.stimulus_randomization",
            "review_context.construct_validity.stimulus_randomization",
            "review_context.stimulus_randomization",
        ),
        randomization_sections,
        strict=True,
    ):
        for key in (
            "randomized",
            "randomized_items",
            "random_factor",
            "as_random_factor",
            "independent_stimulus_set",
            "support",
            "status",
            "design",
        ):
            value = section.get(key)
            if _value_present(value):
                return f"{section_name}.{key}", value
    return None


def _stimulus_generalization_is_broad(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = _generalization_scope_text(value)
    if not text:
        return False
    return any(
        token in text
        for token in (
            "stimulus general",
            "stimulus-class",
            "stimulus_class",
            "stimuli general",
            "class general",
            "broad stimulus",
            "across stimuli",
            "across stimulus",
            "item general",
            "generalization",
            "generalisation",
        )
    )


def _generalization_claim_sources(context: Mapping[str, object]) -> list[str]:
    tags = _context_reason_tags(context)
    return sorted(tags)


def stimulus_fixed_effect_risk_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Warn when broad stimulus-class generalization lacks random-factor support."""

    context = _review_context(bundle)
    request = _stimulus_generalization_request(context)
    if request is None:
        return None

    request_path, request_value = request
    if not _stimulus_generalization_is_broad(request_value):
        return None

    support = _stimulus_randomization_support(context)
    if support is not None:
        support_path, support_value = support
        if _has_truthy_value(support_value):
            return None

    return ReviewFinding(
        rule_id="REVIEW_STIMULUS_FIXED_EFFECT_RISK",
        severity="warn",
        action="warn",
        message=(
            "Broad stimulus-class generalization is recorded without explicit "
            "stimulus-randomization or random-factor support."
        ),
        suggested_fix=(
            "Record the stimulus randomization / random-factor design or downgrade "
            "the claim from broad stimulus-class generalization to the specific "
            "stimulus set used."
        ),
        kg_evidence=[
            f"{request_path}={request_value}",
            f"stimulus_randomization_support={support[0] if support else 'missing'}",
            f"reason_tags={_generalization_claim_sources(context)}",
        ],
        reason_tags=["construct_validity", "stimulus_fixed_effect"],
    )


def behavioral_imbalance_not_modeled_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Warn when explicit RT/accuracy/difficulty/eye-movement imbalance lacks controls."""

    context = _review_context(bundle)
    construct_validity = _nested_mapping(context, "construct_validity")
    task_validity = _nested_mapping(context, "task_validity")
    explicit_confounds: list[str] = []
    for label in _CONFOUND_FIELDS:
        value = _explicit_confound_value(context, label)
        if _has_truthy_value(value):
            explicit_confounds.append(label)

    if not explicit_confounds:
        return None

    controlled_covariates = _controlled_covariates(context)
    unresolved_confounds = [
        confound
        for confound in explicit_confounds
        if not any(token in controlled_covariates for token in _CONFOUND_FIELDS[confound])
    ]
    if not unresolved_confounds:
        return None

    evidence = [f"explicit_behavioral_imbalance={sorted(explicit_confounds)}"]
    if controlled_covariates:
        evidence.append(f"controlled_covariates={sorted(controlled_covariates)}")
    if construct_validity:
        evidence.append(
            f"review_context.construct_validity_keys={sorted(construct_validity)}"
        )
    if task_validity:
        evidence.append(f"review_context.task_validity_keys={sorted(task_validity)}")

    return ReviewFinding(
        rule_id="REVIEW_BEHAVIORAL_IMBALANCE_NOT_MODELED",
        severity="warn",
        action="warn",
        message=(
            "Explicit RT/accuracy/difficulty/eye-movement imbalance is recorded but "
            "the affected constructs are not clearly modeled or controlled."
        ),
        suggested_fix=(
            "Model the recorded behavioral imbalances as covariates, matching, or "
            "stratification variables before making construct-level interpretations."
        ),
        kg_evidence=evidence,
        reason_tags=["construct_validity", "confound"],
    )


def _analysis_family(bundle: CodeReviewBundle, context: Mapping[str, object]) -> str:
    task_connectivity = _nested_mapping(context, "task_connectivity")
    connectivity = _nested_mapping(context, "connectivity")
    for candidate in (
        bundle.kg_context.get("analysis_family"),
        context.get("analysis_family"),
        task_connectivity.get("analysis_family"),
        task_connectivity.get("analysis_type"),
        connectivity.get("analysis_family"),
        connectivity.get("analysis_type"),
    ):
        text = str(candidate or "").strip().lower()
        if text:
            return text
    return ""


def _evoked_response_statuses(context: Mapping[str, object]) -> list[tuple[str, object]]:
    task_connectivity = _nested_mapping(context, "task_connectivity")
    connectivity = _nested_mapping(context, "connectivity")
    preprocessing = _nested_mapping(context, "preprocessing")
    statuses: list[tuple[str, object]] = []
    for source_name, source in (
        ("review_context.task_connectivity", task_connectivity),
        ("review_context.connectivity", connectivity),
        ("review_context.preprocessing", preprocessing),
        ("review_context", context),
    ):
        for key in _EVOKED_RESPONSE_STATUS_KEYS:
            if key in source:
                statuses.append((f"{source_name}.{key}", source.get(key)))
    return statuses


def _evoked_response_is_insufficient(value: object) -> bool:
    if isinstance(value, bool):
        return value is False
    if isinstance(value, str):
        text = value.strip().lower()
        if not text:
            return False
        return any(token in text for token in _BAD_STATUS_TOKENS)
    if isinstance(value, Mapping):
        for key in ("status", "value", "removal_status", "control_status", "removed"):
            nested = value.get(key)
            if _evoked_response_is_insufficient(nested):
                return True
        return False
    if isinstance(value, Iterable):
        return any(_evoked_response_is_insufficient(item) for item in value)
    return False


def task_fc_ppi_evoked_response_control_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Warn when task-FC/PPI claims lack explicit mean-evoked-response control."""

    context = _review_context(bundle)
    family = _analysis_family(bundle, context)
    if family not in _TASK_CONNECTIVITY_FAMILIES:
        return None

    statuses = _evoked_response_statuses(context)
    insufficient = [
        (path, value) for path, value in statuses if _evoked_response_is_insufficient(value)
    ]
    if not insufficient:
        return None

    evidence = [f"analysis_family={family}"]
    evidence.extend(f"{path}={value}" for path, value in insufficient[:4])

    return ReviewFinding(
        rule_id="REVIEW_TASK_FC_PPI_EVOKED_RESPONSE_CONTROL_MISSING",
        severity="warn",
        action="warn",
        message=(
            "Task-FC/PPI connectivity claims are paired with insufficient explicit "
            "mean-evoked-response removal or control."
        ),
        suggested_fix=(
            "Record mean-evoked-response regression/residualization or downgrade the "
            "connectivity claim until evoked-response confounding is handled explicitly."
        ),
        kg_evidence=evidence,
        reason_tags=["construct_validity", "connectivity"],
    )


__all__ = [
    "behavioral_imbalance_not_modeled_check",
    "stimulus_fixed_effect_risk_check",
    "task_fc_ppi_evoked_response_control_check",
]
