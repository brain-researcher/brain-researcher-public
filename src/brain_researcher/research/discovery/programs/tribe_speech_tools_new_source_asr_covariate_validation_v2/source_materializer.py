"""Public score-blind pre-QC source materialization for TRIBE v2.

Collection-specific discovery remains a caller adapter.  This module preserves
the typed candidate, parent-group, and explicit-output boundary without
embedding any source catalog, remote endpoint, or raw recording location.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from brain_researcher.research.discovery.programs.tribe_speech_tools_public import (
    write_json_new,
)

from .contracts import CONDITIONS

PRE_QC_CANDIDATE_MANIFEST_SCHEMA_VERSION = (
    "br.tribe_speech_tools_public.pre_qc_candidate_manifest.v2"
)
PRE_QC_CANDIDATE_PROVENANCE_SCHEMA_VERSION = (
    "br.tribe_speech_tools_public.pre_qc_candidate_provenance.v2"
)


class SourceMaterializerError(ValueError):
    """A public source candidate cannot be materialized score-blind."""


@dataclass(frozen=True, slots=True)
class SourceParentCandidate:
    candidate_key: str
    parent_key: str
    collection_key: str
    condition: str
    annotation_key: str
    start_seconds: float
    end_seconds: float


def _text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceMaterializerError(f"{label} must be non-empty text")
    return value.strip()


def discover_parent_candidates(
    records: Sequence[Mapping[str, Any]],
) -> tuple[SourceParentCandidate, ...]:
    """Validate caller-discovered annotations without knowing their source."""

    if isinstance(records, str | bytes) or not isinstance(records, Sequence):
        raise SourceMaterializerError("records must be an array")
    candidates: list[SourceParentCandidate] = []
    keys: set[str] = set()
    for position, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise SourceMaterializerError(f"records[{position}] must be an object")
        candidate_key = _text(record.get("candidate_key"), label="candidate_key")
        if candidate_key in keys:
            raise SourceMaterializerError("candidate_key values must be unique")
        keys.add(candidate_key)
        condition = _text(record.get("condition"), label="condition")
        if condition not in CONDITIONS:
            raise SourceMaterializerError("condition must be speech or tools")
        start = record.get("start_seconds")
        end = record.get("end_seconds")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int | float)
            or not isinstance(end, int | float)
            or not float(start) >= 0.0
            or not float(end) > float(start)
        ):
            raise SourceMaterializerError("candidate interval must be finite and ordered")
        candidates.append(
            SourceParentCandidate(
                candidate_key=candidate_key,
                parent_key=_text(record.get("parent_key"), label="parent_key"),
                collection_key=_text(
                    record.get("collection_key"), label="collection_key"
                ),
                condition=condition,
                annotation_key=_text(
                    record.get("annotation_key"), label="annotation_key"
                ),
                start_seconds=float(start),
                end_seconds=float(end),
            )
        )
    return tuple(sorted(candidates, key=lambda row: row.candidate_key))


def materialize_pre_qc_source_candidates(
    *,
    candidates: Sequence[SourceParentCandidate],
    manifest_path: str | Path,
    provenance_path: str | Path,
    maximum_alternatives_per_parent: int,
) -> dict[str, Any]:
    """Write explicit public pre-QC artifacts from caller-localized candidates."""

    if (
        isinstance(maximum_alternatives_per_parent, bool)
        or not isinstance(maximum_alternatives_per_parent, int)
        or maximum_alternatives_per_parent < 1
    ):
        raise SourceMaterializerError("maximum_alternatives_per_parent must be positive")
    ordered = tuple(sorted(candidates, key=lambda row: row.candidate_key))
    if not ordered:
        raise SourceMaterializerError("at least one candidate is required")
    parent_counts = Counter(row.parent_key for row in ordered)
    if any(count > maximum_alternatives_per_parent for count in parent_counts.values()):
        raise SourceMaterializerError("parent has too many selected alternatives")
    rows = [
        {
            "candidate_key": row.candidate_key,
            "parent_key": row.parent_key,
            "collection_key": row.collection_key,
            "condition": row.condition,
            "annotation_key": row.annotation_key,
            "start_seconds": row.start_seconds,
            "end_seconds": row.end_seconds,
        }
        for row in ordered
    ]
    manifest = {
        "schema_version": PRE_QC_CANDIDATE_MANIFEST_SCHEMA_VERSION,
        "status": "pre_qc_candidates_materialized",
        "score_blind": True,
        "candidate_count": len(rows),
        "rows": rows,
    }
    provenance = {
        "schema_version": PRE_QC_CANDIDATE_PROVENANCE_SCHEMA_VERSION,
        "status": "pre_qc_candidates_materialized",
        "candidate_count": len(rows),
        "parent_count": len(parent_counts),
        "maximum_alternatives_per_parent": maximum_alternatives_per_parent,
        "collection_keys": sorted({row.collection_key for row in ordered}),
    }
    write_json_new(manifest_path, manifest, label="pre_qc_manifest")
    write_json_new(provenance_path, provenance, label="pre_qc_provenance")
    return {
        "manifest": Path(manifest_path).name,
        "provenance": Path(provenance_path).name,
        "candidate_count": len(rows),
    }


__all__ = [
    "PRE_QC_CANDIDATE_MANIFEST_SCHEMA_VERSION",
    "PRE_QC_CANDIDATE_PROVENANCE_SCHEMA_VERSION",
    "SourceMaterializerError",
    "SourceParentCandidate",
    "discover_parent_candidates",
    "materialize_pre_qc_source_candidates",
]
