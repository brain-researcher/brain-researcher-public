"""Best-effort producer that auto-attaches artifact/code provenance to claims.

The traceability *gate* (``claim_provenance.build_claim_provenance_gate``) only
validates provenance a caller already supplied. Real runs rarely populate it, so
the gate has nothing to check. This module closes that gap on the producer side:
given a run's claims, its evidence items, and the run's file manifest + plan
steps, it resolves each claim's evidence references against the manifest and,
*only on a real match*, attaches:

* ``claim.extra['artifact_provenance']`` — a list of
  ``{evidence_id, artifact_path, artifact_sha256, code_ref}`` records, one per
  resolved evidence reference; and
* ``EvidenceItemV1.provenance_ref`` (when currently ``None``) for the evidence
  item that mapped to a produced artifact.

Honesty contract: provenance is attached **only** when an evidence reference
resolves to an entry that is actually in the run's file manifest. Claims with no
resolvable artifact are left untouched and reported in ``unprovenanced_claim_ids``
— no fabricated paths, hashes, or code refs.

Pure logic; no I/O. Mutates the passed-in claim/evidence objects in place and
returns a small summary.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, Field


class ClaimProvenanceProducerSummary(BaseModel):
    """What the producer attached vs. what it could not trace."""

    claims_total: int = 0
    claims_provenanced: int = 0
    unprovenanced_claim_ids: list[str] = Field(default_factory=list)
    evidence_refs_resolved: int = 0


def _normalize_path(value: Any) -> str | None:
    """Normalize a path/uri reference to a run-relative posix path key.

    Strips artifact-URL prefixes and ``file://`` schemes, drops http(s) refs,
    and lower-cases for case-insensitive matching. Mirrors the manifest keying
    convention used elsewhere in the bundle builder.
    """

    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    marker = "/artifacts/files/"
    if marker in text:
        text = text.split(marker, 1)[1]
    elif text.startswith("file://"):
        text = text[len("file://") :]
    elif text.startswith(("http://", "https://")):
        return None
    text = text.lstrip("/").strip()
    return text.lower() or None


def _build_manifest_index(file_manifest: Any) -> dict[str, dict[str, Any]]:
    """Map normalized path keys (full + basename) -> manifest entry.

    Keys: the full normalized run-relative path, and the bare basename, so an
    evidence ``ref`` that records only a file name can still resolve. Full-path
    keys win over basename keys on collision.
    """

    index: dict[str, dict[str, Any]] = {}
    basename_index: dict[str, dict[str, Any]] = {}
    for entry in file_manifest or []:
        if not isinstance(entry, dict):
            continue
        raw_path = entry.get("path")
        norm = _normalize_path(raw_path)
        if not norm:
            continue
        record = {
            "artifact_path": raw_path if isinstance(raw_path, str) else norm,
            "artifact_sha256": _normalize_sha(entry.get("checksum")),
        }
        index[norm] = record
        base = PurePosixPath(norm).name
        if base and base != norm:
            basename_index.setdefault(base, record)
    # Merge basenames without clobbering exact full-path keys.
    for base, record in basename_index.items():
        index.setdefault(base, record)
    return index


def _normalize_sha(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if not text:
        return None
    if text.startswith("sha256:"):
        text = text[len("sha256:") :]
    return text or None


def _match_manifest(ref: Any, manifest_index: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    norm = _normalize_path(ref)
    if not norm:
        return None
    if norm in manifest_index:
        return manifest_index[norm]
    base = PurePosixPath(norm).name
    if base and base in manifest_index:
        return manifest_index[base]
    return None


def _code_ref_for_artifact(
    artifact_path: str,
    plan_steps: Any,
) -> str | None:
    """Best-effort: find the plan step that produced ``artifact_path``.

    A step is attributed when any of its param values references the artifact
    (path/basename substring). When no step references it but the run has
    exactly one tool-bearing step, that single step is attributed (the only
    plausible producer). Otherwise no code ref is invented.
    """

    steps = [s for s in (plan_steps or []) if isinstance(s, dict) and s.get("tool")]
    norm = _normalize_path(artifact_path) or artifact_path.lower()
    base = PurePosixPath(norm).name

    for step in steps:
        params = step.get("params")
        if not isinstance(params, dict):
            continue
        for value in params.values():
            for candidate in _flatten_strs(value):
                cnorm = _normalize_path(candidate) or candidate.lower()
                if not cnorm:
                    continue
                if cnorm == norm or norm.startswith(cnorm.rstrip("/") + "/") or (
                    base and base in cnorm
                ):
                    return _format_code_ref(step)
    if len(steps) == 1:
        return _format_code_ref(steps[0])
    return None


def _flatten_strs(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            out.extend(_flatten_strs(item))
        return out
    if isinstance(value, dict):
        out = []
        for item in value.values():
            out.extend(_flatten_strs(item))
        return out
    return []


def _format_code_ref(step: dict[str, Any]) -> str:
    tool = str(step.get("tool") or "")
    step_id = step.get("step_id")
    if step_id is not None and str(step_id):
        return f"{tool}:{step_id}"
    return tool


def _claim_candidate_refs(claim: Any, evidence_by_id: dict[str, Any]) -> list[tuple[str, Any]]:
    """Yield (evidence_id, ref) candidates for a claim, de-duplicated.

    Resolves each ``evidence_id`` to the evidence item's ``ref``/``payload_ref``;
    also includes the claim's own ``ref``/``payload_ref`` recorded in ``extra``.
    """

    candidates: list[tuple[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def _add(evidence_id: str, ref: Any) -> None:
        if not isinstance(ref, str) or not ref.strip():
            return
        key = (evidence_id, ref.strip().lower())
        if key in seen:
            return
        seen.add(key)
        candidates.append((evidence_id, ref))

    for evidence_id in getattr(claim, "evidence_ids", None) or []:
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            continue
        item = evidence_by_id.get(evidence_id)
        if item is not None:
            _add(evidence_id, getattr(item, "ref", None))
            _add(evidence_id, getattr(item, "payload_ref", None))
        else:
            # The id itself may be a path-like reference.
            _add(evidence_id, evidence_id)

    extra = getattr(claim, "extra", None)
    if isinstance(extra, dict):
        for key in ("ref", "payload_ref", "artifact_path"):
            _add(str(extra.get(key) or ""), extra.get(key))

    return candidates


def attach_claim_artifact_provenance(
    claims: list[Any],
    evidence_items: list[Any],
    *,
    file_manifest: Any,
    plan_steps: Any,
) -> ClaimProvenanceProducerSummary:
    """Attach real artifact/code provenance to claims, in place (best-effort).

    For each claim, resolve its evidence references against ``file_manifest``.
    On a real match, append ``{evidence_id, artifact_path, artifact_sha256,
    code_ref}`` to ``claim.extra['artifact_provenance']`` and set the matching
    evidence item's ``provenance_ref`` (when it is currently ``None``). Claims
    with no resolvable artifact are left without provenance and recorded in the
    summary's ``unprovenanced_claim_ids``.
    """

    summary = ClaimProvenanceProducerSummary(claims_total=len(claims))
    manifest_index = _build_manifest_index(file_manifest)
    evidence_by_id = {
        getattr(item, "evidence_id", None): item
        for item in evidence_items or []
        if getattr(item, "evidence_id", None)
    }

    if not manifest_index:
        # Nothing produced to bind to: every claim is honestly unprovenanced.
        summary.unprovenanced_claim_ids = [
            str(getattr(claim, "claim_id", "")) for claim in claims
        ]
        return summary

    for claim in claims:
        records: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        for evidence_id, ref in _claim_candidate_refs(claim, evidence_by_id):
            match = _match_manifest(ref, manifest_index)
            if match is None:
                continue
            artifact_path = match["artifact_path"]
            if artifact_path in seen_paths:
                continue
            seen_paths.add(artifact_path)
            code_ref = _code_ref_for_artifact(artifact_path, plan_steps)
            record = {
                "evidence_id": evidence_id or None,
                "artifact_path": artifact_path,
                "artifact_sha256": match["artifact_sha256"],
                "code_ref": code_ref,
            }
            records.append(record)
            summary.evidence_refs_resolved += 1

            # Populate evidence provenance_ref where it is currently unset.
            item = evidence_by_id.get(evidence_id)
            if item is not None and getattr(item, "provenance_ref", None) is None:
                try:
                    item.provenance_ref = code_ref or f"artifact:{artifact_path}"
                except Exception:
                    pass

        if records:
            extra = getattr(claim, "extra", None)
            if not isinstance(extra, dict):
                extra = {}
                try:
                    claim.extra = extra
                except Exception:
                    pass
            extra["artifact_provenance"] = records
            summary.claims_provenanced += 1
        else:
            summary.unprovenanced_claim_ids.append(
                str(getattr(claim, "claim_id", ""))
            )

    return summary


__all__ = [
    "ClaimProvenanceProducerSummary",
    "attach_claim_artifact_provenance",
]
