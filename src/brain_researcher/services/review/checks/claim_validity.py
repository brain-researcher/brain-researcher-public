"""Deterministic claim, sensitivity, and construct-validity checks.

These checks stay intentionally conservative:
- claim inflation only fires on explicit strong claim language
- controversial-choice sensitivity only fires on explicit controversial choices
- construct-validity confound checks only fire on explicit imbalance metadata
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from brain_researcher.core.contracts.code_review import CodeReviewBundle, ReviewFinding

_PREDICTIVE_PROFILES = frozenset({"predictive_model_review"})
_PREDICTIVE_REASON_TAGS = frozenset(
    {
        "predictive",
        "prediction",
        "generalization",
        "generalisation",
        "out_of_sample",
        "cross_validation",
        "cv",
    }
)
_PREDICTIVE_NULL_KEYS = (
    "null_model",
    "null_model_spec",
    "permutation_manifest",
    "permutation_baseline",
    "permutation_baseline_spec",
    "baseline_spec",
    "spatial_null_spec",
)
_PREDICTIVE_SPLIT_KEYS = (
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
_PREDICTION_RE = re.compile(r"\b(predict|prediction|predictive|forecast)\w*\b", re.I)
_BIOMARKER_RE = re.compile(
    r"\b(biomarker|diagnostic|prognostic|clinical utility|clinical use|screening tool)\b",
    re.I,
)
_CAUSAL_RE = re.compile(
    r"\b(causal|causally|causation|causes|caused by|drives|driven by|mechanism|mechanistic|mediates)\b",
    re.I,
)
_CAUSAL_SUPPORT_TOKENS = (
    "causal",
    "intervention",
    "randomized",
    "randomised",
    "stimulation",
    "lesion",
    "perturbation",
    "tms",
    "dbs",
)
_COGNITIVE_PROCESS_TOKENS = (
    "mentalizing",
    "theory of mind",
    "attention",
    "working memory",
    "memory",
    "control",
    "cognitive control",
    "emotion",
    "valuation",
    "value",
    "social",
    "trust",
    "reward",
    "language",
    "semantic",
    "syntactic",
    "pain",
    "retrieval",
    "inhibition",
)
_EXTERNAL_VALIDATION_TOKENS = (
    "external validation",
    "external cohort",
    "heldout cohort",
    "held-out cohort",
    "replication cohort",
    "independent test set",
    "external replication",
)
_REVERSE_INFERENCE_SIGNAL_TOKENS = (
    "activation",
    "activity",
    "connectivity",
    "bold",
    "signal",
    "response",
    "pattern",
    "tpj",
    "vmpfc",
    "dmpfc",
    "dlpfc",
    "amygdala",
    "hippocampus",
    "insula",
    "pcc",
    "precuneus",
    "striatum",
)
_REVERSE_INFERENCE_VERB_RE = re.compile(
    r"\b(indicates|reflects|reveals|demonstrates|proves|means|implies|shows that|supports)\b",
    re.I,
)
_REVERSE_INFERENCE_SUPPORT_TOKENS = (
    "decoder",
    "decoding",
    "forward inference",
    "forward model",
    "meta-analytic decoder",
    "independent localizer",
    "neurosynth decoder",
    "neuroquery",
)
_MODEL_FIT_TOKENS = (
    "fit",
    "fits",
    "better fit",
    "best-fitting",
    "variance explained",
    "encoding score",
    "encoding performance",
    "decoding accuracy",
    "brain score",
    "rsa",
    "representational similarity",
    "prediction score",
    "predicts brain",
    "explains the data",
)
_MODEL_CONTEXT_TOKENS = (
    "model",
    "llm",
    "layer",
    "encoder",
    "network",
    "representation",
    "representational",
    "embedding",
    "transformer",
    "decoder",
)
_MODEL_EQUIVALENCE_TOKENS = (
    "same algorithm",
    "same mechanism",
    "same computation",
    "same representation",
    "representational equivalence",
    "mechanistic equivalence",
    "implements the same",
    "brain uses the same",
    "cortex uses the same",
    "proves the brain uses",
)
_CONTROVERSIAL_CHOICE_PATTERNS = {
    "gsr": ("gsr", "global_signal_regression", "global signal regression"),
    "dynamic_fc": (
        "dynamic_fc",
        "dynamic connectivity",
        "sliding_window",
        "time_varying_fc",
        "tvfc",
    ),
    "graph_thresholding": (
        "graph_threshold",
        "proportional_threshold",
        "threshold_density",
        "graph_density",
        "binarize",
    ),
}
_CONFOUND_FIELDS = {
    "reaction_time": ("reaction_time", "rt"),
    "accuracy": ("accuracy",),
    "difficulty": ("difficulty",),
    "eye_movement": ("eye_movement", "eye_tracking"),
}
_FALSEY_STRINGS = frozenset(
    {"", "none", "null", "false", "no", "absent", "missing", "0"}
)


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


def _review_contract(bundle: CodeReviewBundle) -> Mapping[str, object]:
    return _mapping(bundle.observed_artifacts.get("review_contract"))


def _review_context(bundle: CodeReviewBundle) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    candidates = [
        _mapping(getattr(bundle, "review_context", {})),
        _mapping(_artifact_dict(bundle, "review_context")),
        _mapping(_review_contract(bundle).get("review_context")),
        _mapping(_artifact_dict(bundle, "analysis_bundle").get("review_context")),
        _mapping(_artifact_dict(bundle, "source_summary").get("review_context")),
    ]
    for candidate in candidates:
        if candidate:
            merged.update(candidate)
    return merged


def _context_reason_tags(context: Mapping[str, object]) -> set[str]:
    tags = {tag.lower() for tag in _string_list(context.get("reason_tags"))}
    tags.update(tag.lower() for tag in _string_list(context.get("tags")))
    return tags


def _has_value(mapping: Mapping[str, object], keys: tuple[str, ...]) -> bool:
    return any(_value_present(mapping.get(key)) for key in keys)


def _is_predictive_context(
    bundle: CodeReviewBundle, context: Mapping[str, object]
) -> bool:
    profile = str(
        context.get("scientific_review_profile")
        or _review_contract(bundle).get("scientific_review_profile")
        or bundle.stats_metrics.get("artifact_scientific_review_profile")
        or ""
    ).strip()
    if profile in _PREDICTIVE_PROFILES:
        return True

    reason_tags = _context_reason_tags(context)
    if reason_tags & _PREDICTIVE_REASON_TAGS:
        return True

    split_context = _mapping(context.get("split"))
    null_context = _mapping(context.get("null_model"))
    return (
        _has_value(context, _PREDICTIVE_SPLIT_KEYS)
        or _has_value(split_context, _PREDICTIVE_SPLIT_KEYS)
        or _has_value(context, _PREDICTIVE_NULL_KEYS)
        or _has_value(null_context, _PREDICTIVE_NULL_KEYS)
    )


def _bundle_text(bundle: CodeReviewBundle, context: Mapping[str, object]) -> str:
    values: list[object] = [context, bundle.kg_context]
    for step in bundle.plan_steps:
        if isinstance(step, dict):
            values.append(step)
    values.append(_artifact_dict(bundle, "source_summary"))
    values.append(_artifact_dict(bundle, "execution_manifest"))
    return _normalize_text(values)


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _claim_entries(bundle: CodeReviewBundle) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _append_many(items: object, *, source: str) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            claim_text = str(item.get("claim_text") or "").strip()
            if not claim_text:
                continue
            claim_type = str(
                item.get("claim_type")
                or _mapping(item.get("extra")).get("claim_type")
                or ""
            ).strip()
            key = (source, claim_text)
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                {
                    "source": source,
                    "claim_text": claim_text,
                    "claim_type": claim_type,
                }
            )

    _append_many(
        bundle.observed_artifacts.get("quote_grounded_claims"),
        source="quote_grounded_claims",
    )

    claim_report = _artifact_dict(bundle, "claim_report")
    _append_many(claim_report.get("claims"), source="claim_report")

    claim_updates = bundle.observed_artifacts.get("claim_update")
    if isinstance(claim_updates, list):
        _append_many(claim_updates, source="claim_update")

    research_episode = _artifact_dict(bundle, "research_episode")
    _append_many(
        _mapping(research_episode.get("claim_report")).get("claims"),
        source="research_episode.claim_report",
    )
    _append_many(
        research_episode.get("claim_updates"),
        source="research_episode.claim_updates",
    )

    source_summary = _artifact_dict(bundle, "source_summary")
    claim_text = str(source_summary.get("claim_text") or "").strip()
    if claim_text:
        key = ("source_summary", claim_text)
        if key not in seen:
            seen.add(key)
            entries.append(
                {
                    "source": "source_summary",
                    "claim_text": claim_text,
                    "claim_type": str(source_summary.get("claim_type") or "").strip(),
                }
            )

    return entries


def claim_inflation_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Warn on explicit strong claim language that exceeds structured support."""

    context = _review_context(bundle)
    claim_entries = _claim_entries(bundle)
    if not claim_entries:
        return None

    predictive_context = _is_predictive_context(bundle, context)
    bundle_text = _bundle_text(bundle, context)
    causal_support = any(token in bundle_text for token in _CAUSAL_SUPPORT_TOKENS)
    external_validation_support = any(
        token in bundle_text for token in _EXTERNAL_VALIDATION_TOKENS
    )

    issues: list[str] = []
    evidence: list[str] = []
    for entry in claim_entries:
        claim_text = entry["claim_text"]
        claim_type = entry["claim_type"].lower()
        lowered = claim_text.lower()

        if (
            _PREDICTION_RE.search(lowered) or claim_type in {"prediction", "predictive"}
        ) and not predictive_context:
            issues.append(
                "prediction language without predictive evaluation provenance"
            )
            evidence.append(f"{entry['source']}: {claim_text}")
            continue

        if (
            _BIOMARKER_RE.search(lowered)
            or claim_type in {"biomarker", "clinical", "clinical_utility"}
        ) and not (predictive_context and external_validation_support):
            issues.append(
                "biomarker/clinical utility language without predictive validation plus explicit external validation support"
            )
            evidence.append(f"{entry['source']}: {claim_text}")
            continue

        if (
            _CAUSAL_RE.search(lowered)
            or claim_type in {"causal", "mechanism", "mechanistic"}
        ) and not causal_support:
            issues.append(
                "causal/mechanistic language without explicit intervention or causal-design support"
            )
            evidence.append(f"{entry['source']}: {claim_text}")

    if not issues:
        return None

    issue_summary = ", ".join(dict.fromkeys(issues))
    return ReviewFinding(
        rule_id="REVIEW_CLAIM_INFLATION",
        severity="warn",
        action="warn",
        message=(
            "Claim language exceeds the structured support available: "
            f"{issue_summary}."
        ),
        suggested_fix=(
            "Downgrade the wording to fit/association/consistency language unless the "
            "bundle explicitly records predictive validation, external validation, or "
            "causal/intervention support."
        ),
        kg_evidence=evidence[:5]
        + [
            f"predictive_context={predictive_context}",
            f"external_validation_support={external_validation_support}",
            f"causal_support={causal_support}",
        ],
        reason_tags=["claim_inflation"],
    )


def reverse_inference_risk_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Warn on explicit region/signal -> process inference without decoder support."""

    context = _review_context(bundle)
    bundle_text = _bundle_text(bundle, context)
    has_reverse_support = _contains_any(bundle_text, _REVERSE_INFERENCE_SUPPORT_TOKENS)
    evidence: list[str] = []

    for entry in _claim_entries(bundle):
        claim_text = entry["claim_text"]
        lowered = claim_text.lower()
        if not _contains_any(lowered, _REVERSE_INFERENCE_SIGNAL_TOKENS):
            continue
        if not _REVERSE_INFERENCE_VERB_RE.search(lowered):
            continue
        if not _contains_any(lowered, _COGNITIVE_PROCESS_TOKENS):
            continue
        if has_reverse_support:
            continue
        evidence.append(f"{entry['source']}: {claim_text}")

    if not evidence:
        return None

    return ReviewFinding(
        rule_id="REVIEW_REVERSE_INFERENCE_RISK",
        severity="warn",
        action="warn",
        message=(
            "Explicit region/signal-to-process claims look like reverse inference "
            "without recorded decoding or forward-inference support."
        ),
        suggested_fix=(
            "Rephrase the claim as a compatible interpretation, or attach explicit "
            "decoder / forward-inference support before treating the region pattern "
            "as evidence for a specific cognitive process."
        ),
        kg_evidence=evidence[:5] + [f"reverse_inference_support={has_reverse_support}"],
        reason_tags=["claim_inflation", "construct_validity"],
    )


def model_fit_mechanism_overreach_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Warn on fit/encoding evidence being framed as mechanism/equivalence."""

    context = _review_context(bundle)
    bundle_text = _bundle_text(bundle, context)
    analysis_family = (
        str(bundle.kg_context.get("analysis_family") or "").strip().lower()
    )
    evidence: list[str] = []

    for entry in _claim_entries(bundle):
        claim_text = entry["claim_text"]
        claim_type = entry["claim_type"].lower()
        lowered = claim_text.lower()
        has_fit_language = _contains_any(lowered, _MODEL_FIT_TOKENS)
        has_model_context = _contains_any(
            lowered, _MODEL_CONTEXT_TOKENS
        ) or _contains_any(bundle_text, _MODEL_CONTEXT_TOKENS)
        has_equivalence_language = _contains_any(lowered, _MODEL_EQUIVALENCE_TOKENS)
        if (
            claim_type in {"mechanism", "mechanistic"}
            and has_fit_language
            and has_model_context
        ):
            has_equivalence_language = True
        if (
            not has_fit_language
            or not has_model_context
            or not has_equivalence_language
        ):
            continue
        evidence.append(f"{entry['source']}: {claim_text}")

    if not evidence:
        return None

    return ReviewFinding(
        rule_id="REVIEW_MODEL_FIT_MECHANISM_OVERREACH",
        severity="warn",
        action="warn",
        message=(
            "Model-fit or encoding evidence is being framed as mechanistic or "
            "representational equivalence."
        ),
        suggested_fix=(
            "Downgrade the claim to consistency or predictive fit language unless "
            "additional causal or algorithm-disambiguating evidence is provided."
        ),
        kg_evidence=evidence[:5] + [f"analysis_family={analysis_family or 'unknown'}"],
        reason_tags=["claim_inflation"],
    )


def _detect_controversial_choices(
    bundle: CodeReviewBundle, context: Mapping[str, object]
) -> list[str]:
    sensitivity = _mapping(context.get("sensitivity"))
    explicit = [
        choice.lower()
        for choice in _string_list(sensitivity.get("controversial_choices"))
    ]
    detected: set[str] = set(explicit)
    text = _bundle_text(bundle, context)
    for choice, patterns in _CONTROVERSIAL_CHOICE_PATTERNS.items():
        if any(pattern in text for pattern in patterns):
            detected.add(choice)
    return sorted(detected)


def controversial_choice_sensitivity_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Warn when explicit controversial choices lack recorded sensitivity checks."""

    context = _review_context(bundle)
    sensitivity = _mapping(context.get("sensitivity"))
    null_model = _mapping(context.get("null_model"))
    controversial_choices = _detect_controversial_choices(bundle, context)
    if not controversial_choices:
        return None

    requirements = _string_list(
        sensitivity.get("sensitivity_requirements")
    ) or _string_list(null_model.get("sensitivity_requirements"))
    robustness_checks = _string_list(sensitivity.get("robustness_checks"))
    if robustness_checks:
        return None

    if requirements:
        message_tail = "requirements are recorded, but no robustness/sensitivity results are attached"
    else:
        message_tail = "no sensitivity requirement or robustness record is attached"

    return ReviewFinding(
        rule_id="REVIEW_CONTROVERSIAL_CHOICE_SENSITIVITY",
        severity="warn",
        action="warn",
        message=(
            "Explicit controversial methodological choices are present "
            f"({', '.join(controversial_choices)}), but {message_tail}."
        ),
        suggested_fix=(
            "Record the corresponding on/off, threshold-sweep, or robustness analysis "
            "before presenting the choice as settled."
        ),
        kg_evidence=[
            f"controversial_choices={controversial_choices}",
            f"sensitivity_requirements={requirements}",
        ],
        reason_tags=["controversial_choice"],
    )


def _is_explicit_imbalance(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() not in _FALSEY_STRINGS
    if isinstance(value, Mapping):
        return any(_is_explicit_imbalance(nested) for nested in value.values())
    if isinstance(value, Iterable):
        return any(_is_explicit_imbalance(item) for item in value)
    return False


def _construct_validity_context(context: Mapping[str, object]) -> Mapping[str, object]:
    value = context.get("construct_validity")
    return value if isinstance(value, Mapping) else {}


def _controlled_covariates(context: Mapping[str, object]) -> set[str]:
    construct_validity = _construct_validity_context(context)
    preprocessing = _mapping(context.get("preprocessing"))
    covariates: set[str] = {
        item.lower()
        for item in _string_list(construct_validity.get("controlled_covariates"))
    }
    for item in _string_list(preprocessing.get("confound_regression_scope")):
        covariates.add(item.lower())
    for item in _string_list(preprocessing.get("confounds")):
        covariates.add(item.lower())
    control_strategy = (
        str(construct_validity.get("control_strategy") or "").strip().lower()
    )
    if control_strategy:
        covariates.add(control_strategy)
    return covariates


def construct_validity_confound_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Warn on explicit behavioral/alternative confounds left uncontrolled."""

    context = _review_context(bundle)
    construct_validity = _construct_validity_context(context)
    imbalance = construct_validity.get("behavioral_imbalance")
    imbalance_mapping = imbalance if isinstance(imbalance, Mapping) else {}
    explicit_confounds: list[str] = []
    for label, tokens in _CONFOUND_FIELDS.items():
        value = imbalance_mapping.get(label)
        if value is None:
            value = next(
                (context.get(token) for token in tokens if token in context), None
            )
        if _is_explicit_imbalance(value):
            explicit_confounds.append(label)

    alternative_explanations = _string_list(
        construct_validity.get("alternative_explanations")
    )
    if not explicit_confounds and not alternative_explanations:
        return None

    controlled_covariates = _controlled_covariates(context)
    unresolved_confounds = [
        confound
        for confound in explicit_confounds
        if not any(
            token in controlled_covariates for token in _CONFOUND_FIELDS[confound]
        )
    ]
    if not unresolved_confounds and alternative_explanations and controlled_covariates:
        return None
    if not unresolved_confounds and not alternative_explanations:
        return None

    evidence = []
    if unresolved_confounds:
        evidence.append(f"explicit_behavioral_imbalance={sorted(unresolved_confounds)}")
    if alternative_explanations:
        evidence.append(f"alternative_explanations={alternative_explanations}")
    evidence.append(f"controlled_covariates={sorted(controlled_covariates)}")

    return ReviewFinding(
        rule_id="REVIEW_CONSTRUCT_VALIDITY_CONFOUND",
        severity="warn",
        action="warn",
        message=(
            "Construct-validity confounds are explicitly recorded but not clearly "
            "controlled before making cognitive or behavioral interpretations."
        ),
        suggested_fix=(
            "Model the recorded behavioral/alternative confounds as covariates or "
            "downgrade the interpretation to acknowledge the unresolved alternative explanation."
        ),
        kg_evidence=evidence,
        reason_tags=["construct_validity", "confound"],
    )


__all__ = [
    "claim_inflation_check",
    "controversial_choice_sensitivity_check",
    "construct_validity_confound_check",
    "model_fit_mechanism_overreach_check",
    "reverse_inference_risk_check",
]
