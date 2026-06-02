"""Grounding anchors and reference resolver gates.

This module keeps citation/reference handling out of free-form model text:
tools emit typed anchors, and final evidence rows can be checked against those
anchors before they are treated as grounded.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

UTC = timezone.utc

GROUNDED_BASIS_TYPES = {
    "specific_citation",
    "retrieved_document",
    "kg_fact",
    "session_memory",
}
UNGROUNDED_BASIS_TYPES = {"general_principle", "uncertain"}

_DOI_RE = re.compile(r"^doi:10\.\d{4,9}/\S+$", re.IGNORECASE)
_PMID_RE = re.compile(r"^pmid:\d{4,}$", re.IGNORECASE)
_PMCID_RE = re.compile(r"^pmcid:PMC\d+$", re.IGNORECASE)
_DOC_RE = re.compile(r"^(?:doc|document):\S+$", re.IGNORECASE)
_KG_RE = re.compile(r"^kg:[A-Za-z0-9_.:/#-]+$", re.IGNORECASE)
_SESSION_RE = re.compile(r"^session:[A-Za-z0-9_.:/#-]+$", re.IGNORECASE)
_BARE_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
_BARE_PMID_RE = re.compile(r"^\d{4,}$")
_PMCID_VALUE_RE = re.compile(r"^PMC\d+$", re.IGNORECASE)
_MIXED_REF_RE = re.compile(r"\b(?:doi|pmid|pmcid)\s*:", re.IGNORECASE)
_ALIGNMENT_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]{2,}")
_ALIGNMENT_STOPWORDS = {
    "about",
    "after",
    "also",
    "and",
    "among",
    "because",
    "been",
    "before",
    "being",
    "between",
    "both",
    "could",
    "does",
    "for",
    "from",
    "have",
    "into",
    "more",
    "must",
    "not",
    "only",
    "or",
    "should",
    "than",
    "that",
    "the",
    "their",
    "there",
    "these",
    "this",
    "those",
    "through",
    "using",
    "when",
    "where",
    "which",
    "with",
    "within",
    "would",
}

ReferenceLookup = Callable[[str], Mapping[str, Any] | str | None]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_doi(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    lowered = text.lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if lowered.startswith(prefix):
            text = text[len(prefix) :].strip()
            lowered = text.lower()
    text = re.sub(r"\s+", "", text)
    text = text.rstrip(".,;:)]}")
    text = text.lstrip("([{")
    return text.lower() if _BARE_DOI_RE.match(text) else None


def normalize_pmid(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    if text.lower().startswith("pmid:"):
        text = text.split(":", 1)[1].strip()
    digits = re.sub(r"\D+", "", text)
    return digits if _BARE_PMID_RE.match(digits) else None


def normalize_pmcid(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    if text.lower().startswith("pmcid:"):
        text = text.split(":", 1)[1].strip()
    if text.upper().startswith("PMC"):
        candidate = text.upper()
    else:
        digits = re.sub(r"\D+", "", text)
        candidate = f"PMC{digits}" if digits else ""
    return candidate if _PMCID_VALUE_RE.match(candidate) else None


def normalize_reference(value: Any) -> str:
    """Normalize one reference string without merging multiple identifiers."""

    text = _clean_text(value)
    if not text:
        return ""
    if ";" in text or "\n" in text:
        return text
    if _BARE_DOI_RE.match(text):
        doi = normalize_doi(text)
        return f"doi:{doi}" if doi else text
    lowered = text.lower()
    if lowered.startswith("doi:"):
        doi = normalize_doi(text)
        return f"doi:{doi}" if doi else text
    if lowered.startswith("pmid:"):
        pmid = normalize_pmid(text)
        return f"pmid:{pmid}" if pmid else text
    if lowered.startswith("pmcid:"):
        pmcid = normalize_pmcid(text)
        return f"pmcid:{pmcid}" if pmcid else text
    if _BARE_PMID_RE.match(text):
        return f"pmid:{text}"
    return text


def reference_kind(reference: Any) -> str:
    ref = normalize_reference(reference)
    if not ref:
        return "missing"
    if ";" in ref or "\n" in ref:
        return "malformed"
    if _MIXED_REF_RE.search(ref) and not (
        _DOI_RE.match(ref) or _PMID_RE.match(ref) or _PMCID_RE.match(ref)
    ):
        return "malformed"
    if _DOI_RE.match(ref):
        return "doi"
    if _PMID_RE.match(ref):
        return "pmid"
    if _PMCID_RE.match(ref):
        return "pmcid"
    if _DOC_RE.match(ref):
        return "retrieved_document"
    if _KG_RE.match(ref):
        return "kg_fact"
    if _SESSION_RE.match(ref):
        return "session_memory"
    return "unknown"


def basis_type_for_reference(reference: Any) -> str:
    kind = reference_kind(reference)
    if kind in {"doi", "pmid", "pmcid"}:
        return "specific_citation"
    if kind == "retrieved_document":
        return "retrieved_document"
    if kind == "kg_fact":
        return "kg_fact"
    if kind == "session_memory":
        return "session_memory"
    return "uncertain"


def reference_matches_basis(basis_type: str, reference: Any) -> bool:
    kind = reference_kind(reference)
    if basis_type == "specific_citation":
        return kind in {"doi", "pmid", "pmcid"}
    if basis_type == "retrieved_document":
        return kind == "retrieved_document"
    if basis_type == "kg_fact":
        return kind == "kg_fact"
    if basis_type == "session_memory":
        return kind == "session_memory"
    if basis_type in UNGROUNDED_BASIS_TYPES:
        return kind in {"missing", "unknown"}
    return False


def make_anchor(
    *,
    anchor_id: str,
    anchor_type: str,
    title: Any = None,
    snippet: Any = None,
    doi: Any = None,
    pmid: Any = None,
    pmcid: Any = None,
    score: Any = None,
    doc_id: Any = None,
    support_text: Any = None,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    anchor = {
        "anchor_id": normalize_reference(anchor_id),
        "anchor_type": anchor_type,
        "title": _clean_text(title) or None,
        "snippet": _clean_text(snippet) or None,
        "doi": normalize_doi(doi),
        "pmid": normalize_pmid(pmid),
        "pmcid": normalize_pmcid(pmcid),
        "score": score,
        "doc_id": _clean_text(doc_id) or None,
        "support_text": _clean_text(support_text) or None,
        "provenance": dict(provenance or {}),
    }
    return {key: value for key, value in anchor.items() if value not in (None, "", {})}


def anchors_from_gfs_hit(hit: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Build copyable anchors for a single File Search hit.

    A document anchor is emitted when `doc_id` is present. DOI/PMID/PMCID are
    emitted as separate `specific_citation` anchors so callers never need to
    concatenate identifiers into one reference string.
    """

    title = hit.get("title")
    snippet = hit.get("snippet")
    support_text = hit.get("text") or snippet
    doi = normalize_doi(hit.get("doi"))
    pmid = normalize_pmid(hit.get("pmid"))
    pmcid = normalize_pmcid(hit.get("pmcid"))
    score = hit.get("score")
    doc_id = _clean_text(hit.get("doc_id"))
    anchors: list[dict[str, Any]] = []

    if doc_id:
        doc_anchor_id = (
            doc_id
            if doc_id.lower().startswith(("doc:", "document:"))
            else f"doc:{doc_id}"
        )
        anchors.append(
            make_anchor(
                anchor_id=doc_anchor_id,
                anchor_type="retrieved_document",
                title=title,
                snippet=snippet,
                doi=doi,
                pmid=pmid,
                pmcid=pmcid,
                score=score,
                doc_id=doc_id,
                support_text=support_text,
                provenance={"source": "google_file_search"},
            )
        )

    if doi:
        anchors.append(
            make_anchor(
                anchor_id=f"doi:{doi}",
                anchor_type="specific_citation",
                title=title,
                snippet=snippet,
                doi=doi,
                pmid=pmid,
                pmcid=pmcid,
                score=score,
                doc_id=doc_id,
                support_text=support_text,
                provenance={"source": "google_file_search"},
            )
        )
    if pmid:
        anchors.append(
            make_anchor(
                anchor_id=f"pmid:{pmid}",
                anchor_type="specific_citation",
                title=title,
                snippet=snippet,
                doi=doi,
                pmid=pmid,
                pmcid=pmcid,
                score=score,
                doc_id=doc_id,
                support_text=support_text,
                provenance={"source": "google_file_search"},
            )
        )
    if pmcid:
        anchors.append(
            make_anchor(
                anchor_id=f"pmcid:{pmcid}",
                anchor_type="specific_citation",
                title=title,
                snippet=snippet,
                doi=doi,
                pmid=pmid,
                pmcid=pmcid,
                score=score,
                doc_id=doc_id,
                support_text=support_text,
                provenance={"source": "google_file_search"},
            )
        )

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for anchor in anchors:
        anchor_id = str(anchor.get("anchor_id") or "")
        if not anchor_id or anchor_id in seen:
            continue
        seen.add(anchor_id)
        deduped.append(anchor)
    return deduped


def anchors_from_gfs_hits(hits: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    seen: set[str] = set()
    for hit in hits:
        for anchor in anchors_from_gfs_hit(hit):
            anchor_id = str(anchor.get("anchor_id") or "")
            if not anchor_id or anchor_id in seen:
                continue
            seen.add(anchor_id)
            anchors.append(anchor)
    return anchors


def _resolver_lookup(mapping: Mapping[str, Any] | None, ref: str) -> Any:
    if not mapping:
        return None
    candidates = [ref]
    if ref.startswith("doc:"):
        candidates.append(ref[4:])
    elif reference_kind(ref) == "retrieved_document":
        candidates.append(f"doc:{ref}")
    for candidate in candidates:
        if candidate in mapping:
            return mapping[candidate]
    return None


def _coerce_lookup_payload(
    value: Mapping[str, Any] | str | None,
    *,
    fallback_resolver: str,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        if value.get("resolved") is False or value.get("ok") is False:
            return None
        support_text = _clean_text(
            value.get("support_text")
            or value.get("text")
            or value.get("claim_text")
            or value.get("output_summary")
            or value.get("task_description")
            or value.get("embedding_text")
        )
        if not support_text:
            return None
        provenance_raw = value.get("provenance")
        provenance = dict(provenance_raw) if isinstance(provenance_raw, Mapping) else {}
        provenance.setdefault("resolver", fallback_resolver)
        for key in (
            "kg_id",
            "card_id",
            "stable_key",
            "created_at",
            "card_type",
            "properties",
        ):
            if key in value and key not in provenance:
                provenance[key] = value[key]
        return {"support_text": support_text, "provenance": provenance}

    support_text = _clean_text(value)
    if not support_text:
        return None
    return {
        "support_text": support_text,
        "provenance": {"resolver": fallback_resolver},
    }


def resolver_from_anchors(anchors: list[Mapping[str, Any]] | None) -> dict[str, str]:
    resolver: dict[str, str] = {}
    for anchor in anchors or []:
        if not isinstance(anchor, Mapping):
            continue
        anchor_id = normalize_reference(anchor.get("anchor_id"))
        if not anchor_id:
            continue
        support_text = _clean_text(anchor.get("support_text") or anchor.get("snippet"))
        if not support_text:
            continue
        resolver.setdefault(anchor_id, support_text)
        if anchor_id.startswith("doc:"):
            resolver.setdefault(anchor_id[4:], support_text)
    return resolver


def _alignment_tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in _ALIGNMENT_TOKEN_RE.findall(text)
        if token.lower() not in _ALIGNMENT_STOPWORDS
    }


def claim_support_alignment(
    claim: Any, support_text: Any
) -> tuple[str, dict[str, Any]]:
    """Return the benchmark-compatible lexical claim/support alignment label."""

    claim_tokens = _alignment_tokens(_clean_text(claim))
    support_tokens = _alignment_tokens(_clean_text(support_text))
    overlap = sorted(claim_tokens & support_tokens)
    ratio = len(overlap) / len(claim_tokens) if claim_tokens else 0.0
    if (len(overlap) >= 3 and ratio >= 0.35) or (len(overlap) >= 5 and ratio >= 0.25):
        label = "yes"
    elif len(overlap) >= 2 or ratio >= 0.15:
        label = "partial"
    else:
        label = "no_unrelated"
    return label, {
        "claim_token_count": len(claim_tokens),
        "support_token_count": len(support_tokens),
        "overlap_count": len(overlap),
        "overlap_ratio": round(ratio, 6),
        "overlap_terms": overlap[:20],
    }


def _anchor_support_maps(
    anchors: list[Mapping[str, Any]] | None,
) -> tuple[dict[str, str], dict[str, str]]:
    support_by_reference: dict[str, str] = {}
    source_by_reference: dict[str, str] = {}
    for anchor in anchors or []:
        if not isinstance(anchor, Mapping):
            continue
        anchor_id = normalize_reference(anchor.get("anchor_id"))
        if not anchor_id:
            continue
        support_text = _clean_text(anchor.get("support_text"))
        support_source = "anchor.support_text"
        if not support_text:
            support_text = _clean_text(anchor.get("snippet"))
            support_source = "anchor.snippet"
        if not support_text:
            continue

        candidates = [anchor_id]
        if anchor_id.startswith("doc:"):
            candidates.append(anchor_id[4:])
        doc_id = _clean_text(anchor.get("doc_id"))
        if doc_id:
            candidates.append(doc_id)
            if not doc_id.lower().startswith(("doc:", "document:")):
                candidates.append(f"doc:{doc_id}")

        for candidate in candidates:
            normalized = normalize_reference(candidate)
            if not normalized:
                continue
            support_by_reference.setdefault(normalized, support_text)
            source_by_reference.setdefault(normalized, support_source)
    return support_by_reference, source_by_reference


def _alignment_support_text(
    reference: str,
    *,
    resolved: Mapping[str, Any] | None,
    anchor_support_by_reference: Mapping[str, str],
    anchor_source_by_reference: Mapping[str, str],
    document_resolver: Mapping[str, Any] | None,
) -> tuple[str, str]:
    if reference in anchor_support_by_reference:
        return (
            _clean_text(anchor_support_by_reference.get(reference)),
            str(anchor_source_by_reference.get(reference) or "anchor"),
        )
    resolver_support = _resolver_lookup(document_resolver, reference)
    if resolver_support is not None:
        return _clean_text(resolver_support), "document_resolver"
    support_text = _clean_text((resolved or {}).get("support_text"))
    if support_text:
        provenance = (resolved or {}).get("provenance")
        if isinstance(provenance, Mapping):
            resolver_name = _clean_text(provenance.get("resolver"))
            if resolver_name:
                return support_text, resolver_name
        return support_text, "resolver"
    return "", ""


def _downgrade_grounded_item(item: Mapping[str, Any], gate_note: str) -> dict[str, Any]:
    downgraded = dict(item)
    downgraded["basis_type"] = "uncertain"
    downgraded["reference"] = None
    downgraded["verifiable"] = False
    downgraded.setdefault("gate_note", gate_note)
    return downgraded


def resolve_reference(
    ref: Any,
    *,
    document_resolver: Mapping[str, Any] | None = None,
    kg_resolver: Mapping[str, Any] | None = None,
    session_resolver: Mapping[str, Any] | None = None,
    kg_lookup: ReferenceLookup | None = None,
    session_lookup: ReferenceLookup | None = None,
    run_root: Any = None,
) -> dict[str, Any]:
    """Resolve one reference to structural/provenance support.

    DOI/PMID/PMCID resolve structurally. Document/KG/session anchors require a
    resolver entry or backing service lookup.
    """

    reference = normalize_reference(ref)
    kind = reference_kind(reference)
    payload: dict[str, Any] = {
        "ok": kind != "malformed",
        "reference": reference,
        "reference_kind": kind,
        "resolved": False,
        "timestamp": _now_iso(),
    }
    if kind in {"missing", "unknown", "malformed"}:
        payload["error"] = (
            "malformed_reference" if kind == "malformed" else f"{kind}_reference"
        )
        return payload

    if kind in {"doi", "pmid", "pmcid"}:
        payload.update(
            {
                "resolved": True,
                "support_text": None,
                "provenance": {"resolver": "structural_citation_identifier"},
            }
        )
        return payload

    if kind == "retrieved_document":
        support = _resolver_lookup(document_resolver, reference)
        if support is not None:
            payload.update(
                {
                    "resolved": True,
                    "support_text": str(support),
                    "provenance": {"resolver": "document_anchor_resolver"},
                }
            )
        else:
            payload["error"] = "document_anchor_unresolved"
        return payload

    if kind == "kg_fact":
        support = _resolver_lookup(kg_resolver, reference)
        if support is not None:
            payload.update(
                {
                    "resolved": True,
                    "support_text": str(support),
                    "provenance": {"resolver": "kg_resolver_map"},
                }
            )
            return payload
        if kg_lookup is not None:
            kg_id = reference.split(":", 1)[1]
            try:
                resolved = _coerce_lookup_payload(
                    kg_lookup(kg_id),
                    fallback_resolver="kg_lookup",
                )
                if resolved is not None:
                    payload.update({"resolved": True, **resolved})
                    return payload
            except Exception as exc:
                payload["resolver_error"] = str(exc)
        payload["error"] = "kg_anchor_unresolved"
        return payload

    if kind == "session_memory":
        support = _resolver_lookup(session_resolver, reference)
        if support is not None:
            payload.update(
                {
                    "resolved": True,
                    "support_text": str(support),
                    "provenance": {"resolver": "session_resolver_map"},
                }
            )
            return payload
        if session_lookup is not None:
            card_ref = reference.split(":", 1)[1]
            try:
                resolved = _coerce_lookup_payload(
                    session_lookup(card_ref),
                    fallback_resolver="session_lookup",
                )
                if resolved is not None:
                    payload.update({"resolved": True, **resolved})
                    return payload
            except Exception as exc:
                payload["resolver_error"] = str(exc)
        payload["error"] = "session_anchor_unresolved"
        return payload

    payload["error"] = "unsupported_reference_kind"
    return payload


def gate_evidence_basis(
    evidence_basis: list[Mapping[str, Any]],
    *,
    anchors: list[Mapping[str, Any]] | None = None,
    document_resolver: Mapping[str, Any] | None = None,
    kg_resolver: Mapping[str, Any] | None = None,
    session_resolver: Mapping[str, Any] | None = None,
    kg_lookup: ReferenceLookup | None = None,
    session_lookup: ReferenceLookup | None = None,
    run_root: Any = None,
    alignment_mode: str = "judge_parity",
    partial_action: str = "downgrade",
    min_claim_chars: int = 12,
    alignment_judge: "Callable[[str, str], str] | None" = None,
) -> dict[str, Any]:
    """Validate/degrade evidence_basis rows before final submission.

    Unresolved grounded rows are downgraded to `uncertain`. Malformed grounded
    references make the gate fail so callers do not submit invalid references.
    When enabled, the alignment gate also downgrades resolved grounded rows
    whose claim text is not supported by the resolved support text.

    alignment_mode:
      - "off"          : no claim/support alignment check.
      - "judge_parity" : (default) lexical token-overlap heuristic (fast, gameable).
      - "strict"       : lexical, but partial also downgrades.
      - "judge"        : SEMANTIC — call `alignment_judge(claim, support_text)` -> one of
                         {"yes","partial","no_unrelated"}. Falls back to lexical if no judge
                         is supplied. This is the spam-resistant mode (lexical overlap is
                         gameable by paraphrase; a semantic judge is not).
    """

    anchor_document_resolver = resolver_from_anchors(anchors)
    anchor_support_by_reference, anchor_source_by_reference = _anchor_support_maps(
        anchors
    )
    anchor_ids = {
        normalize_reference(anchor.get("anchor_id"))
        for anchor in anchors or []
        if isinstance(anchor, Mapping)
    }
    anchor_ids.discard("")
    merged_document_resolver = dict(anchor_document_resolver)
    merged_document_resolver.update(dict(document_resolver or {}))

    gated: list[dict[str, Any]] = []
    resolutions: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    mode = (
        alignment_mode
        if alignment_mode in {"off", "judge_parity", "strict", "judge"}
        else "judge_parity"
    )
    if mode == "judge" and alignment_judge is None:
        mode = "judge_parity"  # no semantic judge supplied -> fall back to lexical
    partial_policy = (
        partial_action
        if partial_action in {"keep", "mark_unverifiable", "downgrade"}
        else "downgrade"
    )
    alignment = {
        "mode": mode,
        "partial_action": partial_policy,
        "checked": 0,
        "yes": 0,
        "partial": 0,
        "no_unrelated": 0,
        "skipped": 0,
        "downgraded_by_alignment": 0,
        "per_row": [],
    }

    def append_alignment_row(row: dict[str, Any]) -> None:
        row.setdefault("label", "skipped")
        row.setdefault("support_source", None)
        if row["label"] == "skipped":
            alignment["skipped"] += 1
        alignment["per_row"].append(row)

    for index, raw in enumerate(evidence_basis or []):
        item = dict(raw or {})
        basis_type = str(
            item.get("basis_type") or item.get("basis") or "uncertain"
        ).strip()
        reference = normalize_reference(item.get("reference"))
        if basis_type not in GROUNDED_BASIS_TYPES | UNGROUNDED_BASIS_TYPES:
            basis_type = basis_type_for_reference(reference)
        item["basis_type"] = basis_type
        item["reference"] = reference or None
        inferred_basis_type = basis_type_for_reference(reference)
        if (
            basis_type in UNGROUNDED_BASIS_TYPES
            and inferred_basis_type in GROUNDED_BASIS_TYPES
        ):
            basis_type = inferred_basis_type
            item["basis_type"] = basis_type

        if basis_type not in GROUNDED_BASIS_TYPES:
            if reference_kind(reference) == "malformed":
                errors.append(
                    {
                        "index": index,
                        "reference": reference,
                        "error": "malformed_reference",
                    }
                )
            gated.append(item)
            append_alignment_row(
                {
                    "index": index,
                    "reference": reference or None,
                    "reason": "ungrounded_basis",
                }
            )
            continue

        kind = reference_kind(reference)
        if kind in {"missing", "unknown", "malformed"} or not reference_matches_basis(
            basis_type, reference
        ):
            errors.append(
                {
                    "index": index,
                    "basis_type": basis_type,
                    "reference": reference,
                    "error": (
                        "malformed_reference"
                        if kind == "malformed"
                        else "reference_does_not_match_basis_type"
                    ),
                }
            )
            gated.append(item)
            append_alignment_row(
                {
                    "index": index,
                    "reference": reference or None,
                    "reason": "structural_gate_failed",
                }
            )
            continue

        if (
            anchor_ids
            and basis_type in {"specific_citation", "retrieved_document"}
            and reference not in anchor_ids
        ):
            downgraded = _downgrade_grounded_item(
                item, "reference was not emitted as a typed anchor"
            )
            resolutions.append(
                {
                    "index": index,
                    "reference": reference,
                    "reference_kind": kind,
                    "resolved": False,
                    "error": "reference_not_from_anchor_set",
                    "timestamp": _now_iso(),
                }
            )
            gated.append(downgraded)
            append_alignment_row(
                {
                    "index": index,
                    "reference": reference,
                    "reason": "reference_not_from_anchor_set",
                }
            )
            continue

        resolved = resolve_reference(
            reference,
            document_resolver=merged_document_resolver,
            kg_resolver=kg_resolver,
            session_resolver=session_resolver,
            kg_lookup=kg_lookup,
            session_lookup=session_lookup,
            run_root=run_root,
        )
        resolutions.append({"index": index, **resolved})
        if resolved.get("resolved"):
            support_text, support_source = _alignment_support_text(
                reference,
                resolved=resolved,
                anchor_support_by_reference=anchor_support_by_reference,
                anchor_source_by_reference=anchor_source_by_reference,
                document_resolver=merged_document_resolver,
            )
            claim = _clean_text(item.get("claim"))
            if mode == "off":
                gated.append(item)
                append_alignment_row(
                    {
                        "index": index,
                        "reference": reference,
                        "reason": "alignment_off",
                    }
                )
                continue
            if len(claim) < min_claim_chars:
                gated.append(item)
                append_alignment_row(
                    {
                        "index": index,
                        "reference": reference,
                        "reason": "claim_too_short",
                    }
                )
                continue
            if not support_text:
                gated.append(item)
                append_alignment_row(
                    {
                        "index": index,
                        "reference": reference,
                        "reason": "missing_support_text",
                    }
                )
                continue

            if mode == "judge":
                try:
                    jl = str(alignment_judge(claim, support_text) or "").strip().lower()
                except (
                    Exception
                ) as exc:  # judge failure -> fall back to lexical, never crash the gate
                    jl = ""
                    errors.append(
                        {"index": index, "error": f"alignment_judge_failed: {exc}"}
                    )
                if jl in {"yes", "partial", "no_unrelated"}:
                    label, details = jl, {"alignment_source": "llm_judge"}
                else:
                    label, details = claim_support_alignment(claim, support_text)
                    details["alignment_source"] = "lexical_fallback"
            else:
                label, details = claim_support_alignment(claim, support_text)
            alignment["checked"] += 1
            alignment[label] += 1
            row = {
                "index": index,
                "reference": reference,
                "label": label,
                "support_source": support_source,
                **details,
            }
            if label == "yes":
                gated.append(item)
                append_alignment_row(row)
                continue
            if label == "partial" and mode != "strict":
                if partial_policy == "keep":
                    gated.append(item)
                    append_alignment_row(row)
                    continue
                if partial_policy == "mark_unverifiable":
                    marked = dict(item)
                    marked["verifiable"] = False
                    marked.setdefault("gate_note", "partial claim-anchor overlap")
                    gated.append(marked)
                    append_alignment_row(row)
                    continue

            note = (
                "partial claim-anchor overlap"
                if label == "partial"
                else "claim was not supported by anchor text"
            )
            downgraded = _downgrade_grounded_item(item, note)
            alignment["downgraded_by_alignment"] += 1
            gated.append(downgraded)
            append_alignment_row(row)
            continue

        downgraded = _downgrade_grounded_item(
            item, "grounded reference did not resolve"
        )
        gated.append(downgraded)
        append_alignment_row(
            {
                "index": index,
                "reference": reference,
                "reason": "reference_unresolved",
            }
        )

    grounded_in = sum(
        1
        for raw in evidence_basis or []
        if str((raw or {}).get("basis_type") or "").strip() in GROUNDED_BASIS_TYPES
        or basis_type_for_reference((raw or {}).get("reference"))
        in GROUNDED_BASIS_TYPES
    )
    grounded_out = sum(
        1 for item in gated if item.get("basis_type") in GROUNDED_BASIS_TYPES
    )

    return {
        "ok": not errors,
        "evidence_basis": gated,
        "resolutions": resolutions,
        "errors": errors,
        "degraded_count": sum(
            1
            for before, after in zip(evidence_basis or [], gated, strict=False)
            if str((before or {}).get("basis_type") or "").strip()
            in GROUNDED_BASIS_TYPES
            and after.get("basis_type") == "uncertain"
        ),
        "alignment": alignment,
        "coverage": {
            "grounded_in": grounded_in,
            "grounded_out": grounded_out,
            "ungrounded_after_gate": len(gated) - grounded_out,
        },
    }


__all__ = [
    "GROUNDED_BASIS_TYPES",
    "UNGROUNDED_BASIS_TYPES",
    "anchors_from_gfs_hit",
    "anchors_from_gfs_hits",
    "basis_type_for_reference",
    "claim_support_alignment",
    "gate_evidence_basis",
    "normalize_doi",
    "normalize_pmcid",
    "normalize_pmid",
    "normalize_reference",
    "reference_kind",
    "reference_matches_basis",
    "resolve_reference",
    "resolver_from_anchors",
]
