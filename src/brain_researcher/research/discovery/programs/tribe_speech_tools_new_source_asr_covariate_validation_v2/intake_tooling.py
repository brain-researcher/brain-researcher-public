"""Public helper artifacts for TRIBE v2 intake.

Historical-exposure, PCM, and auditory-QC values are accepted from explicit
caller adapters.  The helpers never scan a local cache or infer an archive.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from brain_researcher.research.discovery.programs.tribe_speech_tools_public import (
    read_json_object,
    write_json_new,
)

HISTORICAL_EXPOSURE_SIDECAR_SCHEMA_VERSION = (
    "br.tribe_speech_tools_public.historical_exposure_sidecar.v2"
)
HISTORICAL_EXPOSURE_INDEX_SCHEMA_VERSION = (
    "br.tribe_speech_tools_public.historical_exposure_index.v2"
)
NOVEL_CANDIDATE_PCM_RECORDS_SCHEMA_VERSION = (
    "br.tribe_speech_tools_public.novel_candidate_pcm_records.v2"
)
AUDITORY_QC_PACKET_SCHEMA_VERSION = (
    "br.tribe_speech_tools_public.auditory_qc_packet.v2"
)
AUDITORY_QC_DECISION_SCHEMA_VERSION = (
    "br.tribe_speech_tools_public.auditory_qc_decision.v2"
)


class NewSourceIntakeToolingError(ValueError):
    """A caller-supplied intake sidecar or blinded review is invalid."""


def _text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NewSourceIntakeToolingError(f"{label} must be non-empty text")
    return value.strip()


def _token_list(value: Any, *, label: str) -> list[str]:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise NewSourceIntakeToolingError(f"{label} must be an array")
    tokens = [_text(token, label=label) for token in value]
    if len(tokens) != len(set(tokens)):
        raise NewSourceIntakeToolingError(f"{label} must not repeat values")
    return sorted(tokens)


def materialize_historical_exposure_sidecars(
    *,
    exposure_sets: Sequence[Mapping[str, Any]],
    index_path: str | Path,
) -> dict[str, Any]:
    """Write the exact four-token-set sidecar expected by the v2 contract."""

    rows: list[dict[str, Any]] = []
    for position, raw in enumerate(exposure_sets):
        if not isinstance(raw, Mapping):
            raise NewSourceIntakeToolingError(f"exposure_sets[{position}] must be an object")
        row = {
            "candidate_keys": _token_list(
                raw.get("candidate_keys"), label="candidate_keys"
            ),
            "source_tokens": _token_list(raw.get("source_tokens"), label="source_tokens"),
            "pcm_tokens": _token_list(raw.get("pcm_tokens"), label="pcm_tokens"),
            "collection_keys": _token_list(
                raw.get("collection_keys"), label="collection_keys"
            ),
        }
        rows.append(row)
    if not rows:
        raise NewSourceIntakeToolingError("at least one exposure set is required")
    payload = {
        "schema_version": HISTORICAL_EXPOSURE_INDEX_SCHEMA_VERSION,
        "status": "caller_supplied",
        "sidecars": rows,
    }
    write_json_new(index_path, payload, label="historical_exposure_index")
    return {"index": Path(index_path).name, "sidecar_count": len(rows)}


def read_historical_exposure_sidecars(index_path: str | Path) -> list[dict[str, Any]]:
    """Read explicit sidecars in the shape consumed by the v2 feasibility contract."""

    payload = read_json_object(index_path, label="historical_exposure_index")
    if payload.get("schema_version") != HISTORICAL_EXPOSURE_INDEX_SCHEMA_VERSION:
        raise NewSourceIntakeToolingError("historical exposure index schema is invalid")
    rows = payload.get("sidecars")
    if not isinstance(rows, list) or not rows:
        raise NewSourceIntakeToolingError("historical exposure index lacks sidecars")
    validated: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {
            "candidate_keys",
            "source_tokens",
            "pcm_tokens",
            "collection_keys",
        }:
            raise NewSourceIntakeToolingError("historical exposure sidecar fields are invalid")
        validated.append(
            {
                field: _token_list(row[field], label=field)
                for field in (
                    "candidate_keys",
                    "source_tokens",
                    "pcm_tokens",
                    "collection_keys",
                )
            }
        )
    return validated


def materialize_novel_candidate_pcm_identities(
    *,
    records: Sequence[Mapping[str, Any]],
    output_path: str | Path,
) -> dict[str, Any]:
    """Persist caller-derived PCM identities without reading source media itself."""

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for position, raw in enumerate(records):
        if not isinstance(raw, Mapping):
            raise NewSourceIntakeToolingError(f"records[{position}] must be an object")
        candidate_key = _text(raw.get("candidate_key"), label="candidate_key")
        if candidate_key in seen:
            raise NewSourceIntakeToolingError("candidate_key must be unique")
        seen.add(candidate_key)
        rows.append(
            {
                "candidate_key": candidate_key,
                "decoded_pcm_identity": _text(
                    raw.get("decoded_pcm_identity"), label="decoded_pcm_identity"
                ),
            }
        )
    payload = {
        "schema_version": NOVEL_CANDIDATE_PCM_RECORDS_SCHEMA_VERSION,
        "status": "caller_supplied",
        "rows": rows,
    }
    write_json_new(output_path, payload, label="novel_candidate_pcm_records")
    return {"artifact": Path(output_path).name, "record_count": len(rows)}


def write_blinded_auditory_qc_packet(
    *,
    candidates: Sequence[Mapping[str, Any]],
    packet_path: str | Path,
) -> dict[str, Any]:
    """Create a condition-free reviewer packet from caller-selected candidates."""

    rows: list[dict[str, str]] = []
    for position, raw in enumerate(candidates):
        if not isinstance(raw, Mapping):
            raise NewSourceIntakeToolingError(f"candidates[{position}] must be an object")
        rows.append(
            {
                "candidate_key": _text(raw.get("candidate_key"), label="candidate_key"),
                "blind_clip_key": _text(
                    raw.get("blind_clip_key"), label="blind_clip_key"
                ),
            }
        )
    if len({row["candidate_key"] for row in rows}) != len(rows):
        raise NewSourceIntakeToolingError("auditory QC packet repeats candidate_key")
    payload = {
        "schema_version": AUDITORY_QC_PACKET_SCHEMA_VERSION,
        "status": "awaiting_blinded_reviews",
        "blinded_to_proposed_condition": True,
        "blinded_to_source": True,
        "blinded_to_acoustic": True,
        "blinded_to_asr": True,
        "blinded_to_tribe": True,
        "rows": rows,
    }
    write_json_new(packet_path, payload, label="auditory_qc_packet")
    return {"packet": Path(packet_path).name, "candidate_count": len(rows)}


def adjudicate_blinded_auditory_qc(
    *,
    packet_path: str | Path,
    decisions: Sequence[Mapping[str, Any]],
    output_path: str | Path,
) -> dict[str, Any]:
    """Persist caller reviews after checking packet membership and two reviewers."""

    packet = read_json_object(packet_path, label="auditory_qc_packet")
    if packet.get("schema_version") != AUDITORY_QC_PACKET_SCHEMA_VERSION:
        raise NewSourceIntakeToolingError("auditory QC packet schema is invalid")
    available = {
        row.get("candidate_key")
        for row in packet.get("rows", [])
        if isinstance(row, Mapping)
    }
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in decisions:
        if not isinstance(raw, Mapping):
            raise NewSourceIntakeToolingError("auditory QC decision must be an object")
        candidate_key = _text(raw.get("candidate_key"), label="candidate_key")
        if candidate_key not in available:
            raise NewSourceIntakeToolingError("auditory QC decision is outside packet")
        review = {
            "reviewer_key": _text(raw.get("reviewer_key"), label="reviewer_key"),
            "target_present": raw.get("target_present") is True,
            "opposite_condition_absent": raw.get("opposite_condition_absent") is True,
            "dominant_condition": _text(
                raw.get("dominant_condition"), label="dominant_condition"
            ),
            "blinded_to_proposed_condition": raw.get("blinded_to_proposed_condition") is True,
            "blinded_to_source": raw.get("blinded_to_source") is True,
            "blinded_to_acoustic": raw.get("blinded_to_acoustic") is True,
            "blinded_to_asr": raw.get("blinded_to_asr") is True,
            "blinded_to_tribe": raw.get("blinded_to_tribe") is True,
        }
        grouped.setdefault(candidate_key, []).append(review)
    for candidate_key, reviews in grouped.items():
        if len(reviews) != 2 or len({row["reviewer_key"] for row in reviews}) != 2:
            raise NewSourceIntakeToolingError(
                f"candidate {candidate_key} requires two distinct reviews"
            )
    payload = {
        "schema_version": AUDITORY_QC_DECISION_SCHEMA_VERSION,
        "status": "adjudicated",
        "reviews_by_candidate": grouped,
    }
    write_json_new(output_path, payload, label="auditory_qc_decisions")
    return {"artifact": Path(output_path).name, "candidate_count": len(grouped)}


__all__ = [
    "AUDITORY_QC_DECISION_SCHEMA_VERSION",
    "AUDITORY_QC_PACKET_SCHEMA_VERSION",
    "HISTORICAL_EXPOSURE_INDEX_SCHEMA_VERSION",
    "HISTORICAL_EXPOSURE_SIDECAR_SCHEMA_VERSION",
    "NOVEL_CANDIDATE_PCM_RECORDS_SCHEMA_VERSION",
    "NewSourceIntakeToolingError",
    "adjudicate_blinded_auditory_qc",
    "materialize_historical_exposure_sidecars",
    "materialize_novel_candidate_pcm_identities",
    "read_historical_exposure_sidecars",
    "write_blinded_auditory_qc_packet",
]
