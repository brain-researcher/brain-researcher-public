"""Canonical IDs for V-HRL robustness binding.

These helpers implement the identity layer from the P0.3 binding contract without
changing producer or resolver behavior. They make the contrast and multiverse-run
namespaces testable before wiring them into real report/provenance flows.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable

from pydantic import BaseModel, Field


def _slug(value: object, *, fallback: str = "unknown") -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
    return cleaned.strip("-") or fallback


def _normalize_weight(value: float | int | str) -> float:
    weight = round(float(value), 6)
    return 0.0 if weight == -0.0 else weight


class CanonicalContrastV1(BaseModel):
    """Content-derived, sign-folded contrast identity.

    ``polarity`` records whether the caller's contrast points in the same direction
    as the canonical sign convention. The id itself deliberately folds pure sign
    negation, so ``A>B`` and ``B>A`` share a contrast id while preserving direction
    separately.
    """

    contrast_id: str
    dataset_id: str
    task: str
    conditions: tuple[str, ...]
    weights: tuple[float, ...]
    test: str = "t"
    polarity: int = Field(default=1, ge=-1, le=1)
    definition_hash: str
    conditions_slug: str


def canonical_contrast_definition(
    conditions: Iterable[object],
    weights: Iterable[float | int | str],
    *,
    test: str = "t",
) -> tuple[tuple[str, ...], tuple[float, ...], str, int]:
    """Return the sorted, sign-folded contrast definition.

    The returned tuple is ``(conditions, weights, test, polarity)``. Conditions are
    sorted with their weights so input order does not affect identity. Pure
    sign-negation is folded by making the first non-zero sorted weight positive.
    """

    condition_list = [str(item).strip() for item in conditions]
    weight_list = [_normalize_weight(item) for item in weights]
    if len(condition_list) != len(weight_list):
        raise ValueError("conditions and weights must have the same length")
    if not condition_list:
        raise ValueError("contrast must include at least one condition")
    if any(not item for item in condition_list):
        raise ValueError("condition names must be non-empty")
    if all(weight == 0.0 for weight in weight_list):
        raise ValueError("contrast weights cannot all be zero")

    pairs = sorted(zip(condition_list, weight_list, strict=True), key=lambda pair: pair[0])
    sorted_conditions = tuple(condition for condition, _ in pairs)
    sorted_weights = tuple(weight for _, weight in pairs)
    first_nonzero = next(weight for weight in sorted_weights if weight != 0.0)
    polarity = -1 if first_nonzero < 0 else 1
    if polarity < 0:
        sorted_weights = tuple(-weight for weight in sorted_weights)
    normalized_test = str(test or "t").strip().lower() or "t"
    return sorted_conditions, sorted_weights, normalized_test, polarity


def canonical_contrast(
    *,
    dataset_id: str,
    task: str,
    conditions: Iterable[object],
    weights: Iterable[float | int | str],
    test: str = "t",
) -> CanonicalContrastV1:
    """Build the P0.3 canonical contrast identity object."""

    conds, ws, normalized_test, polarity = canonical_contrast_definition(
        conditions, weights, test=test
    )
    payload = json.dumps(
        {"conditions": list(conds), "weights": list(ws), "test": normalized_test},
        separators=(",", ":"),
        sort_keys=True,
    )
    definition_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]
    conditions_slug = "__".join(_slug(condition) for condition in conds)[:40]
    contrast_id = (
        f"contrast:{_slug(dataset_id)}:{_slug(task)}:"
        f"{conditions_slug}:{definition_hash}"
    )
    return CanonicalContrastV1(
        contrast_id=contrast_id,
        dataset_id=str(dataset_id),
        task=str(task),
        conditions=conds,
        weights=ws,
        test=normalized_test,
        polarity=polarity,
        definition_hash=definition_hash,
        conditions_slug=conditions_slug,
    )


def canonical_contrast_id(
    dataset_id: str,
    task: str,
    conditions: Iterable[object],
    weights: Iterable[float | int | str],
    *,
    test: str = "t",
) -> str:
    """Return only the canonical contrast id string."""

    return canonical_contrast(
        dataset_id=dataset_id,
        task=task,
        conditions=conditions,
        weights=weights,
        test=test,
    ).contrast_id


def canonical_multiverse_run_id(
    *,
    dataset_id: str,
    task: str,
    variant_ids: Iterable[object],
) -> str:
    """Content-address the logical multiverse run by its variant-id set."""

    unique_variant_ids = sorted({str(item).strip() for item in variant_ids if str(item).strip()})
    if not unique_variant_ids:
        raise ValueError("multiverse_run_id requires at least one variant id")
    payload = json.dumps(unique_variant_ids, separators=(",", ":"))
    family_hash = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    return f"mv:{_slug(dataset_id)}:{_slug(task)}:{family_hash}"
