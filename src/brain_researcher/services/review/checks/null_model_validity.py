"""Deterministic null-model validity checks for scientific review.

These checks are intentionally high precision and only fire when explicit
metadata or provenance is present in the review bundle.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from brain_researcher.core.contracts.code_review import CodeReviewBundle, ReviewFinding

_INVALID_STATUS_VALUES = frozenset(
    {
        "invalid",
        "violated",
        "broken",
        "failed",
        "unsupported",
        "not_supported",
        "incompatible",
        "false",
        "no",
        "0",
    }
)
_VALID_STATUS_VALUES = frozenset({"valid", "passed", "supported", "ok", "true", "yes", "1"})
_SURFACE_TOKENS = frozenset(
    {
        "surface",
        "surface-based",
        "surface_based",
        "cifti",
        "grayordinates",
        "fsaverage",
        "fslr",
        "fs_l_r",
        "surface-space",
    }
)
_VOLUME_TOKENS = frozenset(
    {
        "volume",
        "volumetric",
        "voxel",
        "voxelwise",
        "volume-based",
        "volume_based",
        "native_volume",
    }
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


def _nested_mapping(context: dict[str, Any], key: str) -> dict[str, Any]:
    value = context.get(key)
    return value if isinstance(value, dict) else {}


def _stringify(value: Any) -> str:
    return str(value).strip().lower()


def _status_is_invalid(value: Any) -> bool:
    if isinstance(value, bool):
        return value is False
    text = _stringify(value)
    return bool(text) and text in _INVALID_STATUS_VALUES


def _nested_invalid_status(context: dict[str, Any], keys: tuple[str, ...]) -> bool:
    if _has_explicit_invalid_status(context, keys):
        return True
    for value in context.values():
        if isinstance(value, dict) and _has_explicit_invalid_status(value, keys):
            return True
    return False


def _extract_explicit_status(context: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in context and context.get(key) is not None:
            return context.get(key)
    return None


def _has_explicit_invalid_status(context: dict[str, Any], keys: tuple[str, ...]) -> bool:
    value = _extract_explicit_status(context, keys)
    if value is None:
        return False
    if isinstance(value, dict):
        status = _extract_explicit_status(
            value,
            (
                "status",
                "validity",
                "exchangeability_status",
                "spatial_null_status",
                "domain_status",
                "correction_domain_status",
            ),
        )
        if status is not None:
            return _status_is_invalid(status)
        return False
    return _status_is_invalid(value)


def _domain_family(value: Any) -> str | None:
    text = _stringify(value)
    if not text:
        return None

    if any(token in text for token in _SURFACE_TOKENS):
        return "surface"
    if any(token in text for token in _VOLUME_TOKENS):
        return "volume"
    return None


def _collect_domain_families(context: dict[str, Any], keys: tuple[str, ...]) -> set[str]:
    families: set[str] = set()
    for key in keys:
        value = context.get(key)
        if isinstance(value, dict):
            for nested_key in (
                "domain",
                "analysis_domain",
                "correction_domain",
                "space_kind",
                "space",
                "correction_space",
                "data_domain",
            ):
                family = _domain_family(value.get(nested_key))
                if family:
                    families.add(family)
        else:
            family = _domain_family(value)
            if family:
                families.add(family)
    return families


def _explicit_invalid_exchangeability(context: dict[str, Any]) -> bool:
    candidate_keys = (
        "exchangeability_status",
        "exchangeability_valid",
        "exchangeability",
        "restricted_exchangeability",
    )
    if _has_explicit_invalid_status(context, candidate_keys):
        return True

    for nested_key in ("null_model", "permutation", "permutation_manifest", "exchangeability"):
        nested = _nested_mapping(context, nested_key)
        if nested and _nested_invalid_status(
            nested,
            (
                "exchangeability_status",
                "exchangeability_valid",
                "status",
                "valid",
                "validity",
                "preserved",
            ),
        ):
            return True
    return False


def permutation_exchangeability_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Block explicit permutation schemes that declare exchangeability failure."""

    context = _review_context(bundle)
    reason_tags = _context_reason_tags(context)

    explicit_permutation = any(
        key in context
        for key in (
            "permutation",
            "permutation_manifest",
            "permutation_scheme",
            "null_model",
            "exchangeability",
        )
    )
    if not explicit_permutation:
        return None

    if not _explicit_invalid_exchangeability(context):
        return None

    evidence = [
        f"review_context.reason_tags={sorted(reason_tags)}",
        "explicit exchangeability status indicates invalid / violated / unsupported",
    ]
    if "null_model" in context:
        evidence.append(f"review_context.null_model={sorted(context['null_model']) if isinstance(context['null_model'], dict) else type(context['null_model']).__name__}")

    return ReviewFinding(
        rule_id="REVIEW_PERMUTATION_EXCHANGEABILITY_INVALID",
        severity="error",
        action="block",
        message=(
            "Explicit permutation provenance indicates exchangeability is not "
            "preserved for the stated null model."
        ),
        suggested_fix=(
            "Use a permutation scheme that matches the repeated-measures, "
            "family, or block structure, or replace the permutation null with "
            "a valid restricted-exchangeability design."
        ),
        kg_evidence=evidence,
        reason_tags=["null_mismatch"],
    )


def spatial_null_validity_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Block explicit spatial null provenance that marks the null as invalid."""

    context = _review_context(bundle)
    reason_tags = _context_reason_tags(context)

    explicit_spatial_null = any(
        key in context
        for key in (
            "spatial_null",
            "spatial_null_method",
            "spatial_null_provenance",
            "null_model",
            "map_null",
        )
    )
    if not explicit_spatial_null:
        return None

    spatial_context = _nested_mapping(context, "spatial_null")
    null_context = _nested_mapping(context, "null_model")
    nested_spatial_context = _nested_mapping(null_context, "spatial_null")
    candidate_statuses: list[Any] = [
        context.get("spatial_null_status"),
        context.get("spatial_null_valid"),
        spatial_context.get("status"),
        spatial_context.get("valid"),
        spatial_context.get("validity"),
        spatial_context.get("exchangeability_status"),
        null_context.get("spatial_null_status"),
        null_context.get("spatial_null_valid"),
        nested_spatial_context.get("status"),
        nested_spatial_context.get("valid"),
        nested_spatial_context.get("validity"),
        nested_spatial_context.get("exchangeability_status"),
    ]
    if not any(_status_is_invalid(value) for value in candidate_statuses):
        return None

    evidence = [
        f"review_context.reason_tags={sorted(reason_tags)}",
        "explicit spatial-null status indicates invalid / unsupported / failed",
    ]
    if spatial_context:
        evidence.append(f"review_context.spatial_null_keys={sorted(spatial_context)}")
    if null_context:
        evidence.append(f"review_context.null_model_keys={sorted(null_context)}")

    return ReviewFinding(
        rule_id="REVIEW_SPATIAL_NULL_INVALID",
        severity="error",
        action="block",
        message=(
            "Explicit spatial-null provenance marks the spatial null as invalid "
            "or unsupported."
        ),
        suggested_fix=(
            "Provide a spatial-null method that is explicitly valid for the data "
            "geometry and correlation structure, or remove spatial-null-based "
            "inference claims."
        ),
        kg_evidence=evidence,
        reason_tags=["null_mismatch"],
    )


def surface_volume_correction_domain_mismatch_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Block explicit mismatches between surface/CIFTI and volume correction domains."""

    context = _review_context(bundle)
    reason_tags = _context_reason_tags(context)

    domain_keys = (
        "analysis_domain",
        "data_domain",
        "correction_domain",
        "cluster_correction_domain",
        "multiple_comparison_domain",
        "inference_domain",
        "space_kind",
        "correction_space",
    )
    families = _collect_domain_families(context, domain_keys)
    if len(families) < 2:
        return None

    if not ("surface" in families and "volume" in families):
        return None

    null_model = _nested_mapping(context, "null_model")
    if null_model:
        null_model_families = _collect_domain_families(
            null_model,
            (
                "analysis_domain",
                "data_domain",
                "correction_domain",
                "cluster_correction_domain",
                "multiple_comparison_domain",
                "inference_domain",
                "space_kind",
                "correction_space",
                "space",
            ),
        )
        if "surface" in null_model_families and "volume" in null_model_families:
            explicit_surface_volume_pair = True
        else:
            explicit_surface_volume_pair = False
    else:
        explicit_surface_volume_pair = False

    paired_values: list[tuple[str, str]] = []
    for key in domain_keys:
        value = context.get(key)
        family = _domain_family(value)
        if not family:
            continue
        paired_values.append((key, _stringify(value)))

    for left_key in ("data_domain", "analysis_domain", "space_kind", "space"):
        left_family = _domain_family(context.get(left_key))
        if left_family is None:
            continue
        for right_key in (
            "correction_domain",
            "cluster_correction_domain",
            "multiple_comparison_domain",
            "inference_domain",
            "correction_space",
        ):
            right_family = _domain_family(context.get(right_key))
            if right_family is None:
                continue
            if left_family != right_family:
                explicit_surface_volume_pair = True
                break
        if explicit_surface_volume_pair:
            break

    if not explicit_surface_volume_pair:
        return None

    evidence = [f"review_context.reason_tags={sorted(reason_tags)}"]
    if paired_values:
        evidence.append(
            "explicit domain pairs="
            + ", ".join(f"{key}={value}" for key, value in paired_values)
        )

    return ReviewFinding(
        rule_id="REVIEW_SURFACE_VOLUME_CORRECTION_DOMAIN_MISMATCH",
        severity="error",
        action="block",
        message=(
            "Explicit review metadata places the correction domain in a different "
            "family from the analyzed data domain (surface/CIFTI vs volume)."
        ),
        suggested_fix=(
            "Keep the correction and inference domain aligned with the data "
            "representation, or convert the data to the matching domain before "
            "cluster / multiple-comparison correction."
        ),
        kg_evidence=evidence,
        reason_tags=["null_mismatch"],
    )


__all__ = [
    "permutation_exchangeability_check",
    "spatial_null_validity_check",
    "surface_volume_correction_domain_mismatch_check",
]
