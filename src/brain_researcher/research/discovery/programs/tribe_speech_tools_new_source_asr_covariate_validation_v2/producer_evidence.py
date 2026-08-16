"""Public producer-evidence envelope for TRIBE v2.

The private implementation validates protected files and copies them into a
canonical bundle.  This public version validates caller-supplied JSON
evidence, preserves its score-blind/QC boundary, and never discovers raw
recordings or private caches.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from brain_researcher.research.discovery.programs.tribe_speech_tools_public import (
    read_json_object,
    write_json_new,
)

from .intake_tooling import AUDITORY_QC_DECISION_SCHEMA_VERSION
from .source_materializer import (
    PRE_QC_CANDIDATE_MANIFEST_SCHEMA_VERSION,
    PRE_QC_CANDIDATE_PROVENANCE_SCHEMA_VERSION,
)

SELECTED_PANEL_SCHEMA_VERSION = (
    "br.tribe_speech_tools_public.selected_panel_evidence.v2"
)
COPIED_PRODUCER_EVIDENCE_SCHEMA_VERSION = (
    "br.tribe_speech_tools_public.copied_producer_evidence.v2"
)


class ProducerEvidenceError(ValueError):
    """A caller-supplied v2 producer-evidence chain is malformed."""


@dataclass(frozen=True, slots=True)
class ProducerEvidencePathsV2:
    pre_qc_manifest_path: Path
    pre_qc_provenance_path: Path
    qc_decisions_path: Path
    selected_panel_path: Path


@dataclass(frozen=True, slots=True)
class ValidatedProducerEvidenceV2:
    candidate_rows: tuple[Mapping[str, Any], ...]
    qc_reviews_by_candidate: Mapping[str, Any]
    selected_candidate_keys: tuple[str, ...]
    artifact_names: Mapping[str, str]


def _text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProducerEvidenceError(f"{label} must be non-empty text")
    return value.strip()


def _mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProducerEvidenceError(f"{label} must be an object")
    return value


def _paths(value: Mapping[str, Any]) -> ProducerEvidencePathsV2:
    required = {
        "pre_qc_manifest_path",
        "pre_qc_provenance_path",
        "qc_decisions_path",
        "selected_panel_path",
    }
    if set(value) != required:
        raise ProducerEvidenceError("producer evidence paths have an unsupported field set")
    paths = {
        key: Path(_text(value[key], label=key)).expanduser()
        for key in required
    }
    if any(not path.is_file() or path.is_symlink() for path in paths.values()):
        raise ProducerEvidenceError("producer evidence paths must be regular files")
    return ProducerEvidencePathsV2(**paths)


def validate_external_producer_evidence(
    paths: Mapping[str, Any],
) -> ValidatedProducerEvidenceV2:
    """Validate pre-QC, blinded-QC, and selected-panel JSON supplied by a caller."""

    resolved = _paths(paths)
    manifest = read_json_object(resolved.pre_qc_manifest_path, label="pre_qc_manifest")
    provenance = read_json_object(
        resolved.pre_qc_provenance_path, label="pre_qc_provenance"
    )
    decisions = read_json_object(resolved.qc_decisions_path, label="qc_decisions")
    selected = read_json_object(resolved.selected_panel_path, label="selected_panel")
    if manifest.get("schema_version") != PRE_QC_CANDIDATE_MANIFEST_SCHEMA_VERSION:
        raise ProducerEvidenceError("pre-QC manifest schema is invalid")
    if provenance.get("schema_version") != PRE_QC_CANDIDATE_PROVENANCE_SCHEMA_VERSION:
        raise ProducerEvidenceError("pre-QC provenance schema is invalid")
    if decisions.get("schema_version") != AUDITORY_QC_DECISION_SCHEMA_VERSION:
        raise ProducerEvidenceError("auditory QC decision schema is invalid")
    if selected.get("schema_version") != SELECTED_PANEL_SCHEMA_VERSION:
        raise ProducerEvidenceError("selected panel schema is invalid")
    if manifest.get("score_blind") is not True:
        raise ProducerEvidenceError("pre-QC manifest must be score-blind")
    rows = manifest.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ProducerEvidenceError("pre-QC manifest has no candidates")
    candidate_keys = {
        _text(row.get("candidate_key"), label="candidate_key")
        for row in rows
        if isinstance(row, Mapping)
    }
    if len(candidate_keys) != len(rows):
        raise ProducerEvidenceError("pre-QC candidate keys must be unique")
    reviews = decisions.get("reviews_by_candidate")
    if not isinstance(reviews, Mapping):
        raise ProducerEvidenceError("auditory QC decisions lack reviews_by_candidate")
    selection = selected.get("selected_candidate_keys")
    if not isinstance(selection, list) or not selection:
        raise ProducerEvidenceError("selected panel lacks selected_candidate_keys")
    selected_keys = tuple(_text(value, label="selected_candidate_key") for value in selection)
    if len(selected_keys) != len(set(selected_keys)) or not set(selected_keys).issubset(candidate_keys):
        raise ProducerEvidenceError("selected panel does not bind pre-QC candidates")
    for candidate_key in selected_keys:
        candidate_reviews = reviews.get(candidate_key)
        if not isinstance(candidate_reviews, list) or len(candidate_reviews) != 2:
            raise ProducerEvidenceError("selected candidate lacks two blinded reviews")
    return ValidatedProducerEvidenceV2(
        candidate_rows=tuple(copy.deepcopy(rows)),
        qc_reviews_by_candidate=copy.deepcopy(reviews),
        selected_candidate_keys=selected_keys,
        artifact_names={
            "pre_qc_manifest": resolved.pre_qc_manifest_path.name,
            "pre_qc_provenance": resolved.pre_qc_provenance_path.name,
            "qc_decisions": resolved.qc_decisions_path.name,
            "selected_panel": resolved.selected_panel_path.name,
        },
    )


def write_copied_producer_evidence(
    evidence: ValidatedProducerEvidenceV2,
    *,
    output_path: str | Path,
) -> dict[str, Any]:
    """Write an opaque logical projection, never a copy of producer identities."""

    candidate_keys: dict[str, str] = {}
    parent_keys: dict[str, str] = {}
    collection_keys: dict[str, str] = {}
    rows: list[dict[str, str]] = []
    for index, raw_row in enumerate(evidence.candidate_rows):
        row = _mapping(raw_row, label="candidate_row")
        candidate_key = _text(row.get("candidate_key"), label="candidate_key")
        parent_key = _text(row.get("parent_key"), label="parent_key")
        collection_key = _text(row.get("collection_key"), label="collection_key")
        condition = _text(row.get("condition"), label="condition")
        if candidate_key in candidate_keys:
            raise ProducerEvidenceError("candidate rows repeat candidate_key")
        candidate_keys[candidate_key] = f"candidate-{index:04d}"
        parent_keys.setdefault(parent_key, f"parent-{len(parent_keys):04d}")
        collection_keys.setdefault(collection_key, f"collection-{len(collection_keys):02d}")
        rows.append(
            {
                "candidate_key": candidate_keys[candidate_key],
                "parent_key": parent_keys[parent_key],
                "collection_key": collection_keys[collection_key],
                "condition": condition,
            }
        )
    selected = [
        candidate_keys[key]
        for key in evidence.selected_candidate_keys
        if key in candidate_keys
    ]
    if len(selected) != len(evidence.selected_candidate_keys):
        raise ProducerEvidenceError("selected candidates cannot be made opaque")

    payload = {
        "schema_version": COPIED_PRODUCER_EVIDENCE_SCHEMA_VERSION,
        "status": "validated_opaque_projection",
        "artifact_names": {
            "pre_qc_manifest": "pre_qc_manifest.json",
            "pre_qc_provenance": "pre_qc_provenance.json",
            "qc_decisions": "qc_decisions.json",
            "selected_panel": "selected_panel.json",
        },
        "candidate_rows": rows,
        "qc_reviews_by_candidate": {
            key: {"validated": True} for key in selected
        },
        "selected_candidate_keys": selected,
    }
    write_json_new(output_path, payload, label="copied_producer_evidence")
    return {"artifact": Path(output_path).name, "selected_count": len(selected)}


def load_copied_producer_evidence(path: str | Path) -> ValidatedProducerEvidenceV2:
    """Load a public evidence copy without contacting any external source."""

    payload = read_json_object(path, label="copied_producer_evidence")
    if payload.get("schema_version") != COPIED_PRODUCER_EVIDENCE_SCHEMA_VERSION:
        raise ProducerEvidenceError("copied producer evidence schema is invalid")
    if payload.get("status") != "validated_opaque_projection":
        raise ProducerEvidenceError("copied producer evidence is not an opaque projection")
    rows = payload.get("candidate_rows")
    reviews = payload.get("qc_reviews_by_candidate")
    selection = payload.get("selected_candidate_keys")
    names = payload.get("artifact_names")
    if not isinstance(rows, list) or not isinstance(reviews, Mapping) or not isinstance(names, Mapping):
        raise ProducerEvidenceError("copied producer evidence fields are invalid")
    selected = tuple(_text(value, label="selected_candidate_key") for value in selection or [])
    if not selected:
        raise ProducerEvidenceError("copied producer evidence has no selected candidates")
    return ValidatedProducerEvidenceV2(
        candidate_rows=tuple(copy.deepcopy(rows)),
        qc_reviews_by_candidate=copy.deepcopy(reviews),
        selected_candidate_keys=selected,
        artifact_names={str(key): _text(value, label="artifact_name") for key, value in names.items()},
    )


def project_runtime_inputs(evidence: ValidatedProducerEvidenceV2) -> dict[str, Any]:
    """Project only logical selected-panel inputs for a caller-injected runtime."""

    selected = set(evidence.selected_candidate_keys)
    rows = [
        dict(row)
        for row in evidence.candidate_rows
        if row.get("candidate_key") in selected
    ]
    if len(rows) != len(selected):
        raise ProducerEvidenceError("selected candidates cannot be projected")
    return {
        "selected_candidate_keys": list(evidence.selected_candidate_keys),
        "selected_rows": rows,
        "runtime_command_must_be_injected": True,
    }


__all__ = [
    "COPIED_PRODUCER_EVIDENCE_SCHEMA_VERSION",
    "ProducerEvidenceError",
    "ProducerEvidencePathsV2",
    "SELECTED_PANEL_SCHEMA_VERSION",
    "ValidatedProducerEvidenceV2",
    "load_copied_producer_evidence",
    "project_runtime_inputs",
    "validate_external_producer_evidence",
    "write_copied_producer_evidence",
]
