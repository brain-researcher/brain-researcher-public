"""Deterministic checks for missing sensitivity packages around controversial choices."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from brain_researcher.core.contracts.code_review import CodeReviewBundle, ReviewFinding

_GSR_TOKENS = (
    "gsr",
    "global signal regression",
    "global_signal_regression",
)
_DYNAMIC_FC_TOKENS = (
    "dynamic fc",
    "dynamic_fc",
    "dynamic connectivity",
    "sliding window",
    "sliding_window",
    "tvfc",
    "time varying fc",
    "time-varying fc",
)
_GRAPH_THRESHOLD_TOKENS = (
    "graph threshold",
    "graph_threshold",
    "threshold sweep",
    "threshold_sweep",
    "density sweep",
    "density_sweep",
    "graph density",
    "threshold density",
    "proportional threshold",
    "binarize",
)
_ATLAS_TOKENS = (
    "atlas",
    "atlas roi",
    "roi atlas",
    "parcellation",
    "parcellation roi",
)
_HRF_TOKENS = (
    "hrf",
    "hemodynamic response",
    "hemodynamic basis",
    "canonical hrf",
    "fir basis",
    "basis function",
)
_GSR_SENSITIVITY_TOKENS = (
    "gsr_on_off",
    "gsr on off",
    "global_signal_regression_on_off",
    "global signal regression on/off",
    "global signal regression sensitivity",
)
_DYNAMIC_FC_NULL_TOKENS = (
    "null model",
    "null_model",
    "permutation",
    "surrogate",
    "phase randomization",
    "phase_randomization",
    "exchangeability",
)
_DYNAMIC_FC_SENSITIVITY_TOKENS = (
    "window length sensitivity",
    "window_length_sensitivity",
    "window length sweep",
    "window_length_sweep",
    "parameter sensitivity",
    "parameter_sensitivity",
    "window sweep",
    "window_sweep",
)
_GRAPH_THRESHOLD_SENSITIVITY_TOKENS = (
    "threshold sweep",
    "threshold_sweep",
    "density sweep",
    "density_sweep",
    "graph threshold sensitivity",
    "graph_threshold_sensitivity",
    "graph density sensitivity",
    "graph_density_sensitivity",
)
_ATLAS_SENSITIVITY_TOKENS = (
    "atlas sensitivity",
    "atlas_sensitivity",
    "parcellation sensitivity",
    "parcellation_sensitivity",
    "atlas robustness",
    "atlas_robustness",
    "parcellation robustness",
    "parcellation_robustness",
    "atlas variant",
    "parcellation variant",
)
_HRF_SENSITIVITY_TOKENS = (
    "hrf sensitivity",
    "hrf_sensitivity",
    "hrf robustness",
    "hrf_robustness",
    "basis sensitivity",
    "basis_sensitivity",
    "canonical vs fir",
    "fir vs canonical",
    "hrf variant",
    "hrf_variant",
)


def _artifact_dict(bundle: CodeReviewBundle, key: str) -> dict[str, Any]:
    artifact = bundle.observed_artifacts.get(key)
    return artifact if isinstance(artifact, dict) else {}


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


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


def _review_context(bundle: CodeReviewBundle) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    candidates = [
        _mapping(getattr(bundle, "review_context", {})),
        _mapping(_artifact_dict(bundle, "review_context")),
        _mapping(_artifact_dict(bundle, "review_contract").get("review_context")),
        _mapping(_artifact_dict(bundle, "analysis_bundle").get("review_context")),
        _mapping(_artifact_dict(bundle, "source_summary").get("review_context")),
        _mapping(bundle.stats_metrics.get("review_context")),
        _mapping(bundle.kg_context.get("review_context")),
    ]
    for candidate in candidates:
        if candidate:
            merged.update(candidate)
    return merged


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

    _append_many(bundle.observed_artifacts.get("quote_grounded_claims"), source="quote_grounded_claims")

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


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _claim_text(bundle: CodeReviewBundle) -> str:
    values: list[object] = [bundle.kg_context, bundle.plan_steps]
    preprocessing = _mapping(_review_context(bundle).get("preprocessing"))
    if preprocessing:
        values.append(preprocessing)
    values.extend(entry["claim_text"] for entry in _claim_entries(bundle))
    return _normalize_text(values)


def _sensitivity_context(context: Mapping[str, object]) -> dict[str, Any]:
    sensitivity = _mapping(context.get("sensitivity"))
    null_model = _mapping(context.get("null_model"))
    merged: dict[str, Any] = {}
    for candidate in (sensitivity, null_model):
        if candidate:
            merged.update(candidate)
    return merged


def _sensitivity_text(context: Mapping[str, object]) -> str:
    sensitivity = _sensitivity_context(context)
    values: list[object] = [
        sensitivity.get("sensitivity_requirements"),
        sensitivity.get("robustness_checks"),
        sensitivity.get("robustness_results"),
    ]
    return _normalize_text(values)


def _choice_present(choice: str, text: str, sensitivity: Mapping[str, object]) -> bool:
    declared = [item.lower() for item in _string_list(sensitivity.get("controversial_choices"))]
    if choice in declared:
        return True
    if choice == "gsr":
        return _contains_any(text, _GSR_TOKENS)
    if choice == "dynamic_fc":
        return _contains_any(text, _DYNAMIC_FC_TOKENS)
    if choice == "graph_thresholding":
        return _contains_any(text, _GRAPH_THRESHOLD_TOKENS)
    if choice == "atlas":
        return _contains_any(text, _ATLAS_TOKENS)
    if choice == "hrf":
        return _contains_any(text, _HRF_TOKENS)
    return False


def _has_requirement(text: str, tokens: tuple[str, ...]) -> bool:
    return _contains_any(text, tokens)


def gsr_sensitivity_package_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Warn when GSR is used without an explicit on/off sensitivity package."""

    context = _review_context(bundle)
    preprocessing = _mapping(context.get("preprocessing"))
    sensitivity = _sensitivity_context(context)
    choice_text = _claim_text(bundle)
    preproc_text = _normalize_text(preprocessing)
    gsr_used = _choice_present("gsr", f"{choice_text} {preproc_text}", sensitivity)
    if not gsr_used:
        return None

    sensitivity_text = _sensitivity_text(context)
    if _has_requirement(sensitivity_text, _GSR_SENSITIVITY_TOKENS):
        return None

    return ReviewFinding(
        rule_id="REVIEW_GSR_SENSITIVITY_PACKAGE",
        severity="warn",
        action="warn",
        message=(
            "GSR is recorded in the bundle, but no explicit GSR on/off sensitivity "
            "package is attached."
        ),
        suggested_fix=(
            "Record an on/off GSR comparison or equivalent robustness result before "
            "treating the GSR choice as settled."
        ),
        kg_evidence=[
            f"preprocessing={sorted(preprocessing.keys())}",
            f"controversial_choices={_string_list(sensitivity.get('controversial_choices'))}",
            f"sensitivity_text={sensitivity_text or 'none'}",
        ],
        reason_tags=["controversial_choice", "gsr"],
    )


def dynamic_fc_sensitivity_package_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Warn when dynamic FC claims lack null-model and window/parameter sensitivity."""

    context = _review_context(bundle)
    sensitivity = _sensitivity_context(context)
    choice_text = _claim_text(bundle)
    kg_text = _normalize_text(bundle.kg_context)
    if not _choice_present("dynamic_fc", f"{choice_text} {kg_text}", sensitivity):
        return None

    sensitivity_text = _sensitivity_text(context)
    null_model = _mapping(context.get("null_model"))
    has_null_model = bool(null_model) or bool(_normalize_text(null_model))
    has_window_parameter_sensitivity = _has_requirement(
        sensitivity_text, _DYNAMIC_FC_SENSITIVITY_TOKENS
    )

    missing_bits: list[str] = []
    if not has_null_model:
        missing_bits.append("null model")
    if not has_window_parameter_sensitivity:
        missing_bits.append("window-length/parameter sensitivity")
    if not missing_bits:
        return None

    return ReviewFinding(
        rule_id="REVIEW_DYNAMIC_FC_SENSITIVITY_PACKAGE",
        severity="warn",
        action="warn",
        message=(
            "Dynamic FC is central to the claim, but the bundle is missing "
            f"{' and '.join(missing_bits)}."
        ),
        suggested_fix=(
            "Attach a null model plus a window-length/parameter sweep before "
            "presenting the dynamic FC result as robust."
        ),
        kg_evidence=[
            f"controversial_choices={_string_list(sensitivity.get('controversial_choices'))}",
            f"has_null_model={has_null_model}",
            f"has_window_parameter_sensitivity={has_window_parameter_sensitivity}",
            f"sensitivity_text={sensitivity_text or 'none'}",
        ],
        reason_tags=["controversial_choice", "dynamic_fc"] + [
            tag
            for tag, present in (
                ("null_mismatch", not has_null_model),
                ("sensitivity_package", not has_window_parameter_sensitivity),
            )
            if present
        ],
    )


def graph_atlas_hrf_sensitivity_package_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Warn when graph-threshold, atlas, or HRF choices lack sensitivity support."""

    context = _review_context(bundle)
    sensitivity = _sensitivity_context(context)
    choice_text = _claim_text(bundle)
    preprocessing = _mapping(context.get("preprocessing"))
    preproc_text = _normalize_text(preprocessing)
    bundle_text = f"{choice_text} {preproc_text}"

    choices: list[str] = []
    if _choice_present("graph_thresholding", bundle_text, sensitivity):
        choices.append("graph_thresholding")
    if _choice_present("atlas", bundle_text, sensitivity):
        choices.append("atlas")
    if _choice_present("hrf", bundle_text, sensitivity):
        choices.append("hrf")
    if not choices:
        return None

    sensitivity_text = _sensitivity_text(context)
    missing: list[str] = []
    for choice in choices:
        if choice == "graph_thresholding" and not _has_requirement(
            sensitivity_text, _GRAPH_THRESHOLD_SENSITIVITY_TOKENS
        ):
            missing.append(choice)
        elif choice == "atlas" and not _has_requirement(
            sensitivity_text, _ATLAS_SENSITIVITY_TOKENS
        ):
            missing.append(choice)
        elif choice == "hrf" and not _has_requirement(sensitivity_text, _HRF_SENSITIVITY_TOKENS):
            missing.append(choice)

    if not missing:
        return None

    return ReviewFinding(
        rule_id="REVIEW_GRAPH_ATLAS_HRF_SENSITIVITY_PACKAGE",
        severity="warn",
        action="warn",
        message=(
            "Graph-threshold, atlas, or HRF choices are central to the claim, but "
            f"no choice-specific sensitivity/robustness package is recorded for "
            f"{', '.join(missing)}."
        ),
        suggested_fix=(
            "Record threshold sweeps, atlas/parcellation variants, or HRF-basis "
            "sensitivity results for each controversial choice before treating the "
            "result as robust."
        ),
        kg_evidence=[
            f"controversial_choices={_string_list(sensitivity.get('controversial_choices'))}",
            f"detected_choices={choices}",
            f"missing_choices={missing}",
            f"sensitivity_text={sensitivity_text or 'none'}",
        ],
        reason_tags=["controversial_choice"] + missing,
    )


__all__ = [
    "dynamic_fc_sensitivity_package_check",
    "graph_atlas_hrf_sensitivity_package_check",
    "gsr_sensitivity_package_check",
]
