"""Quote-grounded extraction helpers.

This module provides a small, UI-friendly artifact format that links:
  (query -> evidence items w/ payload + quote span -> structured claims).

The orchestrator can write these artifacts into a job `run_dir` so the web UI can
fetch them via the existing artifacts/files endpoints (which only serve files
directly under the run directory).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from brain_researcher.core.contracts import (
    ClaimScopeV1,
    ClaimV1,
    ClaimVerdictV1,
    EpistemicConfidenceTierV1,
    EvidenceItemV1,
    EvidenceProvenanceV1,
    EvidenceType,
    QuoteSpanV1,
)
from brain_researcher.core.grounding_references import anchors_from_gfs_hit

QUOTE_GROUNDED_EVIDENCE_ITEMS_FILENAME = "quote_grounded_evidence_items.json"
QUOTE_GROUNDED_CLAIMS_FILENAME = "quote_grounded_claims.json"
QUOTE_GROUNDED_FILE_SEARCH_FILENAME = "quote_grounded_file_search.json"
QUOTE_GROUNDED_EVIDENCE_PAYLOAD_PREFIX = "quote_grounded_evidence_"
QUOTE_GROUNDED_EVIDENCE_PAYLOAD_SUFFIX = ".txt"


def _sha256_hexdigest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stable_id(*parts: str) -> str:
    raw = "\n".join(p.strip() for p in parts if p is not None).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def validate_quote_span(payload_text: str, span: QuoteSpanV1) -> None:
    start = int(span.start_char)
    end = int(span.end_char)
    if start < 0 or end < 0:
        raise ValueError("quote_span offsets must be >= 0")
    if end < start:
        raise ValueError("quote_span end_char must be >= start_char")
    if end > len(payload_text):
        raise ValueError(
            f"quote_span end_char {end} exceeds payload length {len(payload_text)}"
        )


def build_evidence_items_from_gfs_hits(
    hits: Iterable[dict[str, Any]],
    *,
    query: str,
    payload_max_chars: int | None = None,
) -> tuple[list[EvidenceItemV1], dict[str, str]]:
    """Convert File Search hits into EvidenceItemV1 + payload blobs.

    Returns:
        (evidence_items, payload_by_filename)
    """

    evidence_items: list[EvidenceItemV1] = []
    payloads: dict[str, str] = {}

    for hit in hits:
        if not isinstance(hit, dict):
            continue

        doc_id = str(hit.get("doc_id") or "").strip()
        anchors = anchors_from_gfs_hit(hit)
        doc_anchor = next(
            (
                str(anchor.get("anchor_id") or "")
                for anchor in anchors
                if anchor.get("anchor_type") == "retrieved_document"
            ),
            "",
        )
        title = str(hit.get("title") or "").strip()
        text = hit.get("text") or hit.get("snippet") or ""
        if not isinstance(text, str):
            text = str(text)
        text = text.strip()
        if not text:
            continue
        if payload_max_chars is not None and payload_max_chars > 0:
            text = text[:payload_max_chars]

        evidence_id = f"gfs_{_stable_id(doc_id or title or query, text)}"
        payload_filename = (
            f"{QUOTE_GROUNDED_EVIDENCE_PAYLOAD_PREFIX}{evidence_id}"
            f"{QUOTE_GROUNDED_EVIDENCE_PAYLOAD_SUFFIX}"
        )

        # Quote the full payload for MVP; UI can highlight the entire chunk.
        sha = _sha256_hexdigest(text)
        span = QuoteSpanV1(
            start_char=0,
            end_char=len(text),
            start_line=1 if text else None,
            end_line=(text.count("\n") + 1) if text else None,
            text_sha256=sha,
        )
        validate_quote_span(text, span)

        score = hit.get("score")
        confidence: float | None = None
        if isinstance(score, (int, float)) and score == score:  # NaN-safe
            confidence = float(score)

        evidence_items.append(
            EvidenceItemV1(
                evidence_id=evidence_id,
                type=EvidenceType.file,
                ref=doc_anchor or doc_id or title or "gfs",
                payload_ref=payload_filename,
                quote_span=span,
                confidence=confidence,
                evidence_provenance=EvidenceProvenanceV1.cross_study_inference,
                raw_data_available=False,
                direct_statistical_test=False,
                provenance_ref=None,
                extra={
                    "source": "gfs",
                    "query": query,
                    "doc_id": doc_id or None,
                    "anchors": anchors,
                    "title": title or None,
                    "pmid": hit.get("pmid"),
                    "pmcid": hit.get("pmcid"),
                    "doi": hit.get("doi"),
                    "score": score,
                    "snippet": hit.get("snippet"),
                },
            )
        )
        payloads[payload_filename] = text

    return evidence_items, payloads


def build_claims_v1_mvp(
    evidence_items: Iterable[EvidenceItemV1],
) -> list[ClaimV1]:
    """MVP claims: 1 claim per evidence item (no LLM required)."""

    claims: list[ClaimV1] = []
    for idx, item in enumerate(evidence_items, start=1):
        title = None
        if isinstance(item.extra, dict):
            title = item.extra.get("title")
        snippet = None
        if isinstance(item.extra, dict):
            snippet = item.extra.get("snippet")

        claim_text = None
        if isinstance(snippet, str) and snippet.strip():
            claim_text = snippet.strip()
        elif isinstance(title, str) and title.strip():
            claim_text = title.strip()
        else:
            claim_text = f"Evidence item {item.evidence_id}"

        claims.append(
            ClaimV1(
                claim_id=f"claim_{idx}",
                claim_text=claim_text,
                verdict=ClaimVerdictV1.suggestive,
                confidence=item.confidence,
                epistemic_confidence_tier=EpistemicConfidenceTierV1.low,
                evidence_provenance=EvidenceProvenanceV1.cross_study_inference,
                claim_scope=ClaimScopeV1.cross_study,
                raw_data_available=False,
                direct_statistical_test=False,
                evidence_ids=[item.evidence_id],
                extra={},
            )
        )
    return claims


def write_quote_grounded_artifacts(
    *,
    run_dir: Path,
    query: str,
    hits: Iterable[dict[str, Any]],
    payload_max_chars: int | None = None,
    max_claims: int | None = None,
) -> dict[str, Any]:
    """Write quote-grounded evidence + claim artifacts into `run_dir`.

    Files are written directly under `run_dir` (no subdirectories) to stay
    compatible with orchestrator artifact download security constraints.
    """

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    evidence_items, payloads = build_evidence_items_from_gfs_hits(
        hits, query=query, payload_max_chars=payload_max_chars
    )

    # Write payload blobs first so payload_ref is always valid.
    for filename, payload in payloads.items():
        if "/" in filename or "\\" in filename:
            raise ValueError(
                f"Invalid payload filename (must be run_dir-local): {filename}"
            )
        _atomic_write_text(run_dir / filename, payload)

    evidence_path = run_dir / QUOTE_GROUNDED_EVIDENCE_ITEMS_FILENAME
    _atomic_write_json(evidence_path, [ev.model_dump() for ev in evidence_items])

    claims = build_claims_v1_mvp(evidence_items)
    if max_claims is not None and max_claims > 0:
        claims = claims[:max_claims]
    claims_path = run_dir / QUOTE_GROUNDED_CLAIMS_FILENAME
    _atomic_write_json(claims_path, [c.model_dump() for c in claims])

    return {
        "status": "ok",
        "query": query,
        "evidence_items_file": QUOTE_GROUNDED_EVIDENCE_ITEMS_FILENAME,
        "claims_file": QUOTE_GROUNDED_CLAIMS_FILENAME,
        "evidence_payload_prefix": QUOTE_GROUNDED_EVIDENCE_PAYLOAD_PREFIX,
        "evidence_count": len(evidence_items),
        "claim_count": len(claims),
    }


__all__ = [
    "QUOTE_GROUNDED_EVIDENCE_ITEMS_FILENAME",
    "QUOTE_GROUNDED_CLAIMS_FILENAME",
    "QUOTE_GROUNDED_FILE_SEARCH_FILENAME",
    "QUOTE_GROUNDED_EVIDENCE_PAYLOAD_PREFIX",
    "QUOTE_GROUNDED_EVIDENCE_PAYLOAD_SUFFIX",
    "build_evidence_items_from_gfs_hits",
    "build_claims_v1_mvp",
    "validate_quote_span",
    "write_quote_grounded_artifacts",
]
