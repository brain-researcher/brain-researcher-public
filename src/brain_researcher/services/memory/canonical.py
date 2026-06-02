"""Shared canonicalization helpers for claim-family identity."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any

from .models import normalize_space, unique_non_empty

_TEXT_SPACE_RE = re.compile(r"\s+")
_TEXT_CLEAN_RE = re.compile(r"[^a-z0-9\s]")


def normalize_claim_text(value: Any) -> str:
    text = _TEXT_SPACE_RE.sub(" ", str(value or "").strip().lower())
    text = _TEXT_CLEAN_RE.sub(" ", text)
    return _TEXT_SPACE_RE.sub(" ", text).strip()


def infer_canonical_claim_kind(*, text: str, polarity: str | None = None) -> str:
    del polarity
    lowered = normalize_claim_text(text)
    if any(token in lowered for token in ("failed replication", "failed to replicate")):
        return "failed_replication"
    if any(
        token in lowered
        for token in ("no effect", "no difference", "null result", "did not differ")
    ):
        return "null_result"
    if any(
        token in lowered
        for token in ("replication", "replicate", "reproduced", "reproduce")
    ):
        return "replication"
    if any(token in lowered for token in ("contradiction", "contradicts", "conflict")):
        return "contradiction"
    return "claim"


def build_canonical_claim_id(
    *,
    target_id: str,
    target_type: str,
    claim_text: str,
    polarity: str | None = None,
) -> str:
    signature = "|".join(
        [
            str(target_id or "").strip(),
            str(target_type or "").strip().lower(),
            infer_canonical_claim_kind(text=claim_text, polarity=polarity),
            normalize_claim_text(claim_text),
        ]
    )
    return f"canonical_claim:{hashlib.md5(signature.encode('utf-8')).hexdigest()}"


def build_claim_memory_stable_key(
    *,
    target_id: str,
    target_type: str,
    claim_text: str,
    polarity: str | None = None,
) -> str:
    return "claim_memory:" + build_canonical_claim_id(
        target_id=target_id,
        target_type=target_type,
        claim_text=claim_text,
        polarity=polarity,
    )


def _tag_value(tags: list[Any] | tuple[Any, ...] | None, prefix: str) -> str | None:
    normalized_prefix = str(prefix or "").strip()
    for raw_tag in tags or []:
        tag = normalize_space(raw_tag)
        if tag.startswith(normalized_prefix):
            value = normalize_space(tag[len(normalized_prefix) :])
            if value:
                return value
    return None


def extract_claim_family_identity(
    raw_card: Mapping[str, Any] | None,
) -> dict[str, Any]:
    raw = dict(raw_card or {})
    tags = list(raw.get("tags") or [])
    claim_text = normalize_space(raw.get("claim_text"))
    claim_polarity = normalize_space(raw.get("claim_polarity")) or None
    target_ids = unique_non_empty(raw.get("target_ids") or [])
    canonical_target_id = (
        normalize_space(raw.get("canonical_target_id"))
        or _tag_value(tags, "canonical_target_id:")
        or (target_ids[0] if target_ids else "")
    )
    target_type = (
        normalize_space(raw.get("target_type"))
        or normalize_space(raw.get("domain"))
        or "unknown"
    )
    canonical_claim_id = normalize_space(raw.get("canonical_claim_id")) or _tag_value(
        tags, "canonical_claim_id:"
    )
    if not canonical_claim_id and claim_text and canonical_target_id:
        canonical_claim_id = build_canonical_claim_id(
            target_id=canonical_target_id,
            target_type=target_type,
            claim_text=claim_text,
            polarity=claim_polarity,
        )
    family_key = (
        canonical_claim_id
        or canonical_target_id
        or normalize_space(raw.get("stable_key"))
        or normalize_space(raw.get("card_id"))
        or normalize_claim_text(claim_text)
        or None
    )
    return {
        "canonical_claim_id": canonical_claim_id or None,
        "canonical_target_id": canonical_target_id or None,
        "claim_text": claim_text or None,
        "claim_type": normalize_space(raw.get("claim_type")) or None,
        "claim_polarity": claim_polarity,
        "target_type": target_type or None,
        "target_ids": unique_non_empty(
            [canonical_target_id, *target_ids] if canonical_target_id else target_ids
        ),
        "analytic_conditions": unique_non_empty(raw.get("analytic_conditions") or []),
        "source_run_ids": unique_non_empty(raw.get("source_run_ids") or []),
        "stable_key": normalize_space(raw.get("stable_key")) or None,
        "family_key": family_key,
    }


def summarize_claim_families(
    raw_cards: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] | None,
    *,
    limit: int = 3,
) -> dict[str, Any]:
    claim_families: dict[str, dict[str, Any]] = {}
    target_families: dict[str, dict[str, Any]] = {}

    for raw_card in raw_cards or []:
        if not isinstance(raw_card, Mapping):
            continue
        identity = extract_claim_family_identity(raw_card)
        family_key = str(identity.get("family_key") or "").strip()
        canonical_target_id = str(identity.get("canonical_target_id") or "").strip()
        if not family_key:
            continue

        claim_entry = claim_families.setdefault(
            family_key,
            {
                "canonical_claim_id": identity.get("canonical_claim_id"),
                "canonical_target_id": identity.get("canonical_target_id"),
                "claim_text": identity.get("claim_text"),
                "claim_types": [],
                "claim_polarities": [],
                "target_ids": [],
                "analytic_conditions": [],
                "source_run_ids": [],
                "n_cards": 0,
            },
        )
        claim_entry["n_cards"] = int(claim_entry.get("n_cards") or 0) + 1
        claim_entry["claim_types"] = unique_non_empty(
            [*list(claim_entry.get("claim_types") or []), identity.get("claim_type")]
        )
        claim_entry["claim_polarities"] = unique_non_empty(
            [
                *list(claim_entry.get("claim_polarities") or []),
                identity.get("claim_polarity"),
            ]
        )
        claim_entry["target_ids"] = unique_non_empty(
            [
                *list(claim_entry.get("target_ids") or []),
                *identity.get("target_ids", []),
            ]
        )
        claim_entry["analytic_conditions"] = unique_non_empty(
            [
                *list(claim_entry.get("analytic_conditions") or []),
                *identity.get("analytic_conditions", []),
            ]
        )
        claim_entry["source_run_ids"] = unique_non_empty(
            [
                *list(claim_entry.get("source_run_ids") or []),
                *identity.get("source_run_ids", []),
            ]
        )

        if canonical_target_id:
            target_entry = target_families.setdefault(
                canonical_target_id,
                {
                    "canonical_target_id": canonical_target_id,
                    "target_ids": [],
                    "claim_family_ids": [],
                    "claim_texts": [],
                    "analytic_conditions": [],
                    "source_run_ids": [],
                    "n_cards": 0,
                },
            )
            target_entry["n_cards"] = int(target_entry.get("n_cards") or 0) + 1
            target_entry["target_ids"] = unique_non_empty(
                [
                    *list(target_entry.get("target_ids") or []),
                    *identity.get("target_ids", []),
                ]
            )
            target_entry["claim_family_ids"] = unique_non_empty(
                [
                    *list(target_entry.get("claim_family_ids") or []),
                    identity.get("canonical_claim_id") or family_key,
                ]
            )
            target_entry["claim_texts"] = unique_non_empty(
                [
                    *list(target_entry.get("claim_texts") or []),
                    identity.get("claim_text"),
                ]
            )
            target_entry["analytic_conditions"] = unique_non_empty(
                [
                    *list(target_entry.get("analytic_conditions") or []),
                    *identity.get("analytic_conditions", []),
                ]
            )
            target_entry["source_run_ids"] = unique_non_empty(
                [
                    *list(target_entry.get("source_run_ids") or []),
                    *identity.get("source_run_ids", []),
                ]
            )

    sorted_claim_families = sorted(
        claim_families.values(),
        key=lambda item: (
            -int(item.get("n_cards") or 0),
            str(item.get("claim_text") or ""),
            str(item.get("canonical_claim_id") or ""),
        ),
    )
    sorted_target_families = sorted(
        target_families.values(),
        key=lambda item: (
            -int(item.get("n_cards") or 0),
            str(item.get("canonical_target_id") or ""),
        ),
    )
    safe_limit = max(1, int(limit))
    return {
        "n_claim_families": len(sorted_claim_families),
        "n_target_families": len(sorted_target_families),
        "claim_families": sorted_claim_families[:safe_limit],
        "target_families": sorted_target_families[:safe_limit],
        "dominant_claim_family": (
            dict(sorted_claim_families[0]) if sorted_claim_families else None
        ),
        "dominant_target_family": (
            dict(sorted_target_families[0]) if sorted_target_families else None
        ),
    }


def build_verification_claim_mapping(
    *,
    hypothesis: str,
    normalized_claim: Mapping[str, Any] | None,
    verdict: str | None,
) -> dict[str, Any]:
    normalized = dict(normalized_claim or {})
    subject = (
        dict(normalized.get("subject") or {})
        if isinstance(normalized.get("subject"), Mapping)
        else {}
    )
    obj = (
        dict(normalized.get("object") or {})
        if isinstance(normalized.get("object"), Mapping)
        else {}
    )
    predicate = normalize_space(normalized.get("predicate")) or "related_to"
    predicate_key = (
        re.sub(r"[^a-z0-9_]+", "_", predicate.lower()).strip("_") or "related_to"
    )

    subject_id = normalize_space(
        subject.get("kg_id") or subject.get("element_id") or subject.get("label")
    )
    object_id = normalize_space(
        obj.get("kg_id") or obj.get("element_id") or obj.get("label")
    )
    subject_label = normalize_space(
        subject.get("label") or subject.get("kg_id") or subject.get("element_id")
    )
    object_label = normalize_space(
        obj.get("label") or obj.get("kg_id") or obj.get("element_id")
    )
    subject_type = normalize_space(subject.get("node_type")) or "Entity"
    object_type = normalize_space(obj.get("node_type")) or "Entity"

    canonical_target_id = (
        f"{subject_id}|{predicate_key}|{object_id}"
        if subject_id and object_id
        else subject_id
        or object_id
        or normalize_claim_text(hypothesis)
        or "verification_claim"
    )
    target_type = (
        "Relation"
        if subject_id and object_id
        else subject_type or object_type or "unknown"
    )
    canonical_claim_text = " ".join(
        part
        for part in [subject_label, predicate, object_label]
        if normalize_space(part)
    ) or normalize_space(hypothesis)
    claim_polarity = {
        "supported": "supports",
        "conflicting": "refutes",
    }.get(normalize_space(verdict).lower(), normalize_space(verdict) or None)
    canonical_claim_id = build_canonical_claim_id(
        target_id=canonical_target_id,
        target_type=target_type,
        claim_text=canonical_claim_text,
        polarity=claim_polarity,
    )
    stable_key = f"claim_memory:{canonical_claim_id}"
    domain = target_type
    tags = unique_non_empty(
        [
            "verification",
            f"predicate:{predicate}",
            f"subject:{subject_id}" if subject_id else None,
            f"object:{object_id}" if object_id else None,
            f"subject_type:{subject_type}" if subject_type else None,
            f"object_type:{object_type}" if object_id and object_type else None,
            f"canonical_target_id:{canonical_target_id}",
            f"canonical_claim_id:{canonical_claim_id}",
        ]
    )
    return {
        "canonical_target_id": canonical_target_id,
        "target_type": target_type,
        "canonical_claim_id": canonical_claim_id,
        "canonical_claim_text": canonical_claim_text,
        "stable_key": stable_key,
        "target_ids": unique_non_empty([canonical_target_id, subject_id, object_id]),
        "predicate": predicate,
        "domain": domain,
        "subject_id": subject_id or None,
        "object_id": object_id or None,
        "claim_polarity": claim_polarity,
        "tags": tags,
    }


__all__ = [
    "build_canonical_claim_id",
    "build_claim_memory_stable_key",
    "build_verification_claim_mapping",
    "extract_claim_family_identity",
    "infer_canonical_claim_kind",
    "normalize_claim_text",
    "summarize_claim_families",
]
