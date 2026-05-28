"""Deterministic review_context validity checks for scientific review."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
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
_LEAKAGE_REASON_TAGS = frozenset({"leakage", "circularity"})
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
_PREDICTIVE_NULL_MODEL_KEYS = (
    "null_model",
    "null_model_spec",
    "permutation_manifest",
    "permutation_manifest_path",
    "permutation_baseline",
    "permutation_baseline_spec",
    "baseline_spec",
    "spatial_null_spec",
    "sensitivity_requirements",
)
_PREDICTIVE_STRICT_SPLIT_KEYS = (
    "split_manifest",
    "split_manifest_path",
    "cv_manifest",
    "cv_manifest_path",
    "fold_manifest_path",
    "split_manifest_sha256",
    "train_ids_hash",
    "test_ids_hash",
)
_PREDICTIVE_FIT_SCOPE_KEYS = (
    "fit_scope_by_step",
    "fit_scopes",
    "preprocessing_fit_scope",
    "preprocessing_fit_scope_by_step",
)
_PREDICTIVE_PREPROCESSING_SCOPE_KEYS = (
    "feature_selection_scope",
    "feature_selection_fit_scope",
    "standardization_scope",
    "scaler_fit_scope",
    "residualizer_fit_scope",
    "confound_regression_scope",
    "confound_residualization_scope",
    "harmonization_fit_scope",
    "variance_mask_scope",
    "imputer_fit_scope",
    "target_transformer_fit_scope",
)
_PREDICTIVE_PERMUTATION_PROBE_KEYS = (
    "label_permutation_null",
    "permutation_null",
)
_FULL_PIPELINE_SCOPE_VALUES = frozenset(
    {
        "full_pipeline",
        "whole_pipeline",
        "end_to_end",
        "entire_pipeline",
        "pipeline",
    }
)
_TRUSTED_FULL_PIPELINE_PERMUTATION_GENERATORS = frozenset(
    {
        "br_full_pipeline_permutation_harness",
        "br.workflow.full_pipeline_permutation_harness",
    }
)
_TRUSTED_FULL_PIPELINE_INPUT_SCOPES = frozenset(
    {
        "raw_inputs",
        "workflow_invocation",
        "full_pipeline",
    }
)
_PIPELINE_INVOCATION_DIGEST_KEYS = (
    "pipeline_invocation_sha256",
    "workflow_invocation_sha256",
    "raw_input_manifest_sha256",
)
_MIRROR_CONTEXT_PATHS = (
    ("schema_version",),
    ("split", "split_unit"),
    ("split", "split_strategy_detail"),
    ("split", "grouped_split_keys"),
    ("split", "required_group_keys"),
    ("split", "grouping_required"),
    ("split", "train_test_independence"),
    ("split", "subject_manifest_path"),
    ("split", "fold_manifest_path"),
    ("split", "subject_intersection_manifest_path"),
    ("selection", "selection_on_test"),
    ("selection", "selection_scope"),
    ("selection", "best_model"),
    ("selection", "best_layer"),
    ("selection", "best_roi"),
    ("selection", "best_prompt"),
    ("selection", "model_candidates"),
    ("selection", "layer_candidates"),
    ("selection", "roi_candidates"),
    ("selection", "prompt_candidates"),
    ("selection", "selection_accounting"),
    ("selection", "multiplicity_accounting"),
    ("selection", "multiple_comparison_correction"),
    ("selection", "nested_cv"),
    ("selection", "selection_holdout"),
    ("selection", "independent_validation"),
    ("preprocessing", "feature_selection_scope"),
    ("preprocessing", "standardization_scope"),
    ("preprocessing", "harmonization_fit_scope"),
    ("preprocessing", "confound_regression_scope"),
    ("null_model", "null_model_spec"),
    ("null_model", "permutation_baseline_spec"),
    ("null_model", "spatial_null_spec"),
    ("sensitivity", "controversial_choices"),
    ("sensitivity", "sensitivity_requirements"),
    ("sensitivity", "robustness_checks"),
    ("construct_validity", "behavioral_imbalance"),
    ("construct_validity", "controlled_covariates"),
    ("provenance", "provenance_tier"),
    ("provenance", "evidence_provenance"),
)


def _artifact_dict(bundle: CodeReviewBundle, key: str) -> dict[str, Any]:
    artifact = bundle.observed_artifacts.get(key)
    return artifact if isinstance(artifact, dict) else {}


def _review_context(bundle: CodeReviewBundle) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    candidates: list[dict[str, Any]] = []

    if isinstance(getattr(bundle, "review_context", None), dict):
        candidates.append(dict(bundle.review_context))

    for artifact_key in ("review_context", "source_summary"):
        artifact = _artifact_dict(bundle, artifact_key)
        if artifact_key == "source_summary":
            nested = artifact.get("review_context")
            if isinstance(nested, dict):
                candidates.append(nested)
        else:
            candidates.append(artifact)

    stats_context = bundle.stats_metrics.get("review_context")
    if isinstance(stats_context, dict):
        candidates.append(stats_context)

    kg_context = bundle.kg_context.get("review_context")
    if isinstance(kg_context, dict):
        candidates.append(kg_context)

    for candidate in candidates:
        merged.update(candidate)
    return merged


def _context_sources(bundle: CodeReviewBundle) -> list[tuple[str, dict[str, Any]]]:
    sources: list[tuple[str, dict[str, Any]]] = []

    if (
        isinstance(getattr(bundle, "review_context", None), dict)
        and bundle.review_context
    ):
        sources.append(("bundle.review_context", dict(bundle.review_context)))

    observed_context = _artifact_dict(bundle, "review_context")
    if observed_context:
        sources.append(("observed.review_context", observed_context))

    analysis_bundle = _artifact_dict(bundle, "analysis_bundle")
    analysis_context = analysis_bundle.get("review_context")
    if isinstance(analysis_context, dict) and analysis_context:
        sources.append(("analysis_bundle.review_context", dict(analysis_context)))
    run_card = analysis_bundle.get("run_card")
    if isinstance(run_card, dict):
        run_card_context = run_card.get("review_context")
        if isinstance(run_card_context, dict) and run_card_context:
            sources.append(
                ("analysis_bundle.run_card.review_context", dict(run_card_context))
            )

    observation = _artifact_dict(bundle, "observation")
    observation_run_card = observation.get("run_card")
    if isinstance(observation_run_card, dict):
        observation_context = observation_run_card.get("review_context")
        if isinstance(observation_context, dict) and observation_context:
            sources.append(
                ("observation.run_card.review_context", dict(observation_context))
            )

    review_contract = _artifact_dict(bundle, "review_contract")
    contract_context = review_contract.get("review_context")
    if isinstance(contract_context, dict) and contract_context:
        sources.append(("review_contract.review_context", dict(contract_context)))

    source_summary = _artifact_dict(bundle, "source_summary")
    source_summary_context = source_summary.get("review_context")
    if isinstance(source_summary_context, dict) and source_summary_context:
        sources.append(("source_summary.review_context", dict(source_summary_context)))

    extraction_report = _artifact_dict(bundle, "extraction_report")
    extraction_report_context = extraction_report.get("review_context")
    if isinstance(extraction_report_context, dict) and extraction_report_context:
        sources.append(
            ("extraction_report.review_context", dict(extraction_report_context))
        )
    extraction_contract = extraction_report.get("review_contract")
    if isinstance(extraction_contract, dict):
        extraction_contract_context = extraction_contract.get("review_context")
        if (
            isinstance(extraction_contract_context, dict)
            and extraction_contract_context
        ):
            sources.append(
                (
                    "extraction_report.review_contract.review_context",
                    dict(extraction_contract_context),
                )
            )

    deduped: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for label, context in sources:
        key = f"{label}:{json.dumps(context, sort_keys=True, default=str)}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append((label, context))
    return deduped


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, Iterable):
        values = list(value)
    else:
        return []
    cleaned: list[str] = []
    for item in values:
        text = str(item).strip().lower()
        if text:
            cleaned.append(text)
    return cleaned


def _context_reason_tags(context: dict[str, Any]) -> set[str]:
    tags = set(_string_list(context.get("reason_tags")))
    tags.update(_string_list(context.get("tags")))
    return tags


def _value_present(value: Any) -> bool:
    return value not in (None, "", [], {}, ())


def _has_any_value(context: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return any(_value_present(context.get(key)) for key in keys)


def _nested_mapping(context: dict[str, Any], key: str) -> dict[str, Any]:
    value = context.get(key)
    return value if isinstance(value, dict) else {}


def _nested_value(context: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = context
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _has_any_path_value(
    context: dict[str, Any], paths: tuple[tuple[str, ...], ...]
) -> bool:
    return any(_value_present(_nested_value(context, path)) for path in paths)


def _has_any_section_value(
    context: dict[str, Any],
    keys: tuple[str, ...],
    sections: tuple[str, ...],
) -> bool:
    if _has_any_value(context, keys):
        return True
    return any(
        _has_any_value(_nested_mapping(context, section), keys) for section in sections
    )


def _is_predictive_context(
    context: dict[str, Any],
    bundle: CodeReviewBundle,
) -> bool:
    profile = str(
        context.get("scientific_review_profile")
        or bundle.stats_metrics.get("artifact_scientific_review_profile")
        or ""
    ).strip()
    reason_tags = _context_reason_tags(context)
    return (
        profile in _PREDICTIVE_PROFILES
        or bool(reason_tags & _PREDICTIVE_REASON_TAGS)
        or str(context.get("claim_type") or "").strip().lower()
        in {"prediction", "predictive", "fit"}
    )


def _is_confirmatory_claim(context: dict[str, Any]) -> bool:
    claim_contract = _nested_mapping(context, "claim_contract")
    mode = (
        str(
            claim_contract.get("confirmatory_or_exploratory")
            or context.get("confirmatory_or_exploratory")
            or context.get("analysis_mode")
            or context.get("claim_mode")
            or ""
        )
        .strip()
        .lower()
    )
    if mode in {"confirmatory", "confirmation", "final", "primary"}:
        return True

    explicit = context.get("confirmatory")
    if explicit is True:
        return True
    if isinstance(explicit, str) and explicit.strip().lower() in {"true", "yes", "1"}:
        return True

    claim_strength = (
        str(claim_contract.get("claim_strength") or context.get("claim_strength") or "")
        .strip()
        .lower()
    )
    return claim_strength in {
        "final",
        "strong",
        "confirmatory",
        "scientifically_convincing",
    }


def _is_full_pipeline_permutation_probe(value: Any, *, confirmatory: bool) -> bool:
    if not _value_present(value):
        return False
    if not isinstance(value, dict):
        return False
    pipeline_scope = str(value.get("pipeline_scope") or "").strip().lower()
    if pipeline_scope not in _FULL_PIPELINE_SCOPE_VALUES:
        return False
    generated_by = str(value.get("generated_by") or "").strip().lower()
    if generated_by not in _TRUSTED_FULL_PIPELINE_PERMUTATION_GENERATORS:
        return False
    input_scope = str(value.get("input_scope") or "").strip().lower()
    if input_scope not in _TRUSTED_FULL_PIPELINE_INPUT_SCOPES:
        return False
    return any(
        bool(str(value.get(key) or "").strip())
        for key in _PIPELINE_INVOCATION_DIGEST_KEYS
    )


def _has_full_pipeline_permutation_probe(
    context: dict[str, Any],
    *,
    confirmatory: bool,
) -> bool:
    for section in (
        context,
        _nested_mapping(context, "review_probes"),
        _nested_mapping(context, "null_model"),
    ):
        for key in _PREDICTIVE_PERMUTATION_PROBE_KEYS:
            if _is_full_pipeline_permutation_probe(
                section.get(key),
                confirmatory=confirmatory,
            ):
                return True
    return False


def _normalize_for_compare(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _normalize_for_compare(inner)
            for key, inner in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, set):
        return sorted(_normalize_for_compare(item) for item in value)
    if isinstance(value, list | tuple):
        normalized_items = [_normalize_for_compare(item) for item in value]
        return sorted(
            normalized_items,
            key=lambda item: json.dumps(item, sort_keys=True, default=str),
        )
    if isinstance(value, str):
        return value.strip()
    return value


def _path_value(context: dict[str, Any], path: tuple[str, ...]) -> tuple[bool, Any]:
    current: Any = context
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return False, None
        current = current[key]
    return True, current


def _bundle_run_dir(bundle: CodeReviewBundle) -> Path | None:
    for artifact_key in ("analysis_bundle", "observation", "review_contract"):
        artifact = _artifact_dict(bundle, artifact_key)
        raw = artifact.get("run_dir")
        if isinstance(raw, str) and raw.strip():
            return Path(raw).expanduser()
    return None


def _evidence_path_exists(
    *,
    evidence_path: str,
    indexed_artifacts: set[str],
    run_dir: Path | None,
) -> bool:
    prefix = evidence_path.split(":", 1)[0].strip()
    if not prefix:
        return False

    normalized_index = {item.strip() for item in indexed_artifacts if item.strip()}
    prefix_name = Path(prefix).name
    indexed_basenames = {Path(item).name for item in normalized_index}

    if prefix in normalized_index or prefix_name in indexed_basenames:
        return True

    if run_dir is None:
        return False

    candidate_paths = [
        run_dir / prefix,
        run_dir / "artifacts" / "source" / prefix,
    ]
    for candidate in candidate_paths:
        if candidate.exists():
            return True

    try:
        for path in (run_dir / "artifacts" / "source").rglob("*"):
            if path.is_file() and path.name == prefix_name:
                return True
    except Exception:
        return False
    return False


def predictive_review_context_metadata_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Flag predictive review contexts that omit split or null-model metadata."""

    context = _review_context(bundle)
    profile = str(
        context.get("scientific_review_profile")
        or bundle.stats_metrics.get("artifact_scientific_review_profile")
        or ""
    ).strip()
    reason_tags = _context_reason_tags(context)

    is_predictive_context = (
        profile in _PREDICTIVE_PROFILES
        or bool(reason_tags & _PREDICTIVE_REASON_TAGS)
        or str(context.get("claim_type") or "").strip().lower()
        in {"prediction", "predictive", "fit"}
    )
    if not is_predictive_context:
        return None

    split_context = _nested_mapping(context, "split")
    null_context = _nested_mapping(context, "null_model")
    has_split_metadata = _has_any_value(
        context, _PREDICTIVE_SPLIT_KEYS
    ) or _has_any_value(split_context, _PREDICTIVE_SPLIT_KEYS)
    has_null_model_metadata = _has_any_value(
        context, _PREDICTIVE_NULL_MODEL_KEYS
    ) or _has_any_value(null_context, _PREDICTIVE_NULL_MODEL_KEYS)
    if has_split_metadata and has_null_model_metadata:
        return None

    missing_bits: list[str] = []
    if not has_split_metadata:
        missing_bits.append("split metadata")
    if not has_null_model_metadata:
        missing_bits.append("null-model metadata")

    evidence = [f"review_context.reason_tags={sorted(reason_tags)}"]
    if profile:
        evidence.append(f"review_context.scientific_review_profile={profile}")
    evidence.append(f"missing={', '.join(missing_bits)}")
    finding_tags = ["predictive", "generalization"]
    if not has_split_metadata:
        finding_tags.append("leakage")
    if not has_null_model_metadata:
        finding_tags.append("null_mismatch")

    return ReviewFinding(
        rule_id="REVIEW_PREDICTIVE_REVIEW_CONTEXT_METADATA",
        severity="error",
        action="block",
        message=(
            "Predictive review context is missing required split and/or null-model "
            f"metadata ({', '.join(missing_bits)})."
        ),
        suggested_fix=(
            "Populate review_context with an explicit split manifest or CV manifest "
            "and a null-model / permutation baseline spec before presenting the run "
            "as predictive-validation ready."
        ),
        kg_evidence=evidence,
        reason_tags=finding_tags,
    )


def predictive_required_diagnostics_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Require evidence that high-risk predictive operations were actually audited."""

    context = _review_context(bundle)
    if not _is_predictive_context(context, bundle):
        return None

    is_confirmatory = _is_confirmatory_claim(context)
    split_context = _nested_mapping(context, "split")

    has_split_manifest = _has_any_value(
        context, _PREDICTIVE_STRICT_SPLIT_KEYS
    ) or _has_any_value(split_context, _PREDICTIVE_STRICT_SPLIT_KEYS)
    has_fit_scope = _has_any_section_value(
        context,
        _PREDICTIVE_FIT_SCOPE_KEYS,
        ("preprocessing", "cv_contract", "provenance"),
    ) or _has_any_section_value(
        context,
        _PREDICTIVE_PREPROCESSING_SCOPE_KEYS,
        ("preprocessing", "cv_contract", "provenance"),
    )
    has_permutation_null = _has_full_pipeline_permutation_probe(
        context,
        confirmatory=is_confirmatory,
    )

    missing: list[str] = []
    if not has_split_manifest:
        missing.append("split_manifest")
    if not has_fit_scope:
        missing.append("fit_scope_by_step")
    if not has_permutation_null:
        missing.append("full_pipeline_permutation_null")
    if not missing:
        return None

    severity = "error" if is_confirmatory else "warn"
    action = "block" if is_confirmatory else "warn"

    claim_contract = _nested_mapping(context, "claim_contract")
    claim_mode = (
        claim_contract.get("confirmatory_or_exploratory")
        or context.get("confirmatory_or_exploratory")
        or context.get("analysis_mode")
        or context.get("claim_mode")
        or "unspecified"
    )
    profile = str(
        context.get("scientific_review_profile")
        or bundle.stats_metrics.get("artifact_scientific_review_profile")
        or ""
    ).strip()
    reason_tags = _context_reason_tags(context)

    evidence = [
        f"missing_required_diagnostics={missing}",
        f"claim_mode={claim_mode}",
        f"confirmatory={is_confirmatory}",
        f"review_context.reason_tags={sorted(reason_tags)}",
    ]
    if profile:
        evidence.append(f"review_context.scientific_review_profile={profile}")

    return ReviewFinding(
        rule_id="REVIEW_GOVERNANCE_MISSING_DIAGNOSTIC",
        severity=severity,
        action=action,
        message=(
            "Predictive review context is missing required diagnostics for a "
            f"reviewable predictive claim: {', '.join(missing)}."
        ),
        suggested_fix=(
            "Emit a split manifest, fold-local fit_scope_by_step/preprocessing "
            "scope diagnostics, and a full-pipeline label-permutation-null probe "
            "before presenting predictive performance as a supported claim."
        ),
        kg_evidence=evidence,
        reason_tags=["predictive", "coverage", "data_contract"],
    )


def review_context_leakage_circularity_flag_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Surface explicit leakage/circularity disclosures in review_context."""

    context = _review_context(bundle)
    reason_tags = _context_reason_tags(context)
    explicit_flags = set(reason_tags & _LEAKAGE_REASON_TAGS)

    for key in ("leakage", "circularity"):
        value = context.get(key)
        if value is True:
            explicit_flags.add(key)
        elif isinstance(value, str) and value.strip().lower() in {"true", "yes", "1"}:
            explicit_flags.add(key)

    flags = _string_list(context.get("flags"))
    explicit_flags.update(flag for flag in flags if flag in _LEAKAGE_REASON_TAGS)

    if not explicit_flags:
        return None

    ordered_flags = sorted(explicit_flags)
    evidence = [f"review_context.reason_tags={sorted(reason_tags)}"]
    if flags:
        evidence.append(f"review_context.flags={sorted(set(flags))}")
    evidence.append(f"explicit_flags={ordered_flags}")

    return ReviewFinding(
        rule_id="REVIEW_REVIEW_CONTEXT_LEAKAGE_CIRCULARITY",
        severity="warn",
        action="warn",
        message=(
            "Review context explicitly flags leakage/circularity: "
            f"{', '.join(ordered_flags)}."
        ),
        suggested_fix=(
            "Carry the flagged caveat into the final scientific review and avoid "
            "describing the result as clean validation unless the leakage or "
            "circularity concern is resolved."
        ),
        kg_evidence=evidence,
        reason_tags=ordered_flags,
    )


def review_context_mirror_conflict_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Warn when mirrored review_context payloads disagree across staged artifacts."""

    context = _review_context(bundle)
    profile = str(
        context.get("scientific_review_profile")
        or bundle.stats_metrics.get("artifact_scientific_review_profile")
        or ""
    ).strip()
    reason_tags = _context_reason_tags(context)
    is_predictive_or_neuroai = (
        profile in _PREDICTIVE_PROFILES
        or bool(reason_tags & _PREDICTIVE_REASON_TAGS)
        or str(bundle.kg_context.get("analysis_family") or "").strip().lower()
        in {
            "embedding_analysis",
            "neural_encoding_prediction",
            "neuroai",
            "tribe_prediction",
        }
    )
    if not is_predictive_or_neuroai:
        return None

    sources = _context_sources(bundle)
    if len(sources) < 2:
        return None

    conflicts: list[str] = []
    evidence: list[str] = []
    for path in _MIRROR_CONTEXT_PATHS:
        values_by_signature: dict[str, list[str]] = {}
        rendered_values: dict[str, str] = {}
        for label, source_context in sources:
            present, raw_value = _path_value(source_context, path)
            if not present:
                continue
            normalized = _normalize_for_compare(raw_value)
            signature = json.dumps(normalized, sort_keys=True, default=str)
            values_by_signature.setdefault(signature, []).append(label)
            rendered_values.setdefault(
                signature, json.dumps(normalized, sort_keys=True, default=str)
            )
        if len(values_by_signature) <= 1:
            continue
        path_label = ".".join(path)
        conflicts.append(path_label)
        rendered_conflicts = "; ".join(
            f"{rendered_values[signature]} <- {sorted(labels)}"
            for signature, labels in sorted(values_by_signature.items())
        )
        evidence.append(f"{path_label}: {rendered_conflicts}")

    if not conflicts:
        return None

    return ReviewFinding(
        rule_id="REVIEW_REVIEW_CONTEXT_MIRROR_CONFLICT",
        severity="warn",
        action="warn",
        message=(
            "Mirrored review_context metadata disagrees across staged artifacts, "
            "so provenance for the scientific review is internally inconsistent."
        ),
        suggested_fix=(
            "Regenerate or restage the run so run.json, analysis_bundle.json, "
            "review_contract, and source-side summaries carry the same review_context."
        ),
        kg_evidence=evidence[:8],
        reason_tags=["low_reliability"],
    )


def external_evidence_path_integrity_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Warn when external extraction_report evidence paths do not resolve to staged source artifacts."""

    extraction_report = _artifact_dict(bundle, "extraction_report")
    if not extraction_report:
        return None

    review_contract = _artifact_dict(bundle, "review_contract")
    contract_mode = str(review_contract.get("contract_mode") or "").strip().lower()
    if contract_mode != "external_review_bundle" and not extraction_report.get(
        "adapter_name"
    ):
        return None

    inferred_fields = extraction_report.get("inferred_fields")
    if not isinstance(inferred_fields, list) or not inferred_fields:
        return None

    indexed_artifacts = {
        str(item).strip()
        for item in extraction_report.get("indexed_artifacts") or []
        if str(item).strip()
    }
    run_dir = _bundle_run_dir(bundle)

    missing: list[str] = []
    for item in inferred_fields:
        if not isinstance(item, dict):
            continue
        evidence_path = item.get("evidence_path")
        if not isinstance(evidence_path, str) or not evidence_path.strip():
            continue
        if _evidence_path_exists(
            evidence_path=evidence_path,
            indexed_artifacts=indexed_artifacts,
            run_dir=run_dir,
        ):
            continue
        field = str(item.get("field") or "?").strip()
        missing.append(f"{field}:{evidence_path}")

    if not missing:
        return None

    evidence = [f"missing_evidence_paths={missing[:8]}"]
    if indexed_artifacts:
        evidence.append(f"indexed_artifacts_sample={sorted(indexed_artifacts)[:8]}")

    return ReviewFinding(
        rule_id="REVIEW_EXTERNAL_EVIDENCE_PATH_INTEGRITY",
        severity="warn",
        action="warn",
        message=(
            "External extraction metadata references evidence paths that do not "
            "resolve to staged source artifacts."
        ),
        suggested_fix=(
            "Restage the external run so inferred_fields.evidence_path points to "
            "real staged source files or indexed artifacts."
        ),
        kg_evidence=evidence,
        reason_tags=["low_reliability"],
    )


__all__ = [
    "external_evidence_path_integrity_check",
    "predictive_required_diagnostics_check",
    "predictive_review_context_metadata_check",
    "review_context_mirror_conflict_check",
    "review_context_leakage_circularity_flag_check",
]
