#!/usr/bin/env python3
"""Build a pre-Gate-B adjudication pack from the v3-lite bootstrap manifests."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import numpy as np

from brain_researcher.services.br_kg.etl.loaders.gabriel_measurements import (
    DEFAULT_REQUIRED_PROVENANCE_FIELDS,
    compute_gabriel_variables,
)

ROOT = Path(__file__).resolve().parents[2]

CALIBRATION_PATH = ROOT / "docs/planning/claim_hypotheses_calibration_v3_lite.jsonl"
HELDOUT_PATH = ROOT / "docs/planning/claim_hypotheses_heldout_v3_lite.jsonl"
REVIEW_QUEUE_PATH = ROOT / "data/br-kg/raw/gabriel/review_queue.jsonl"

PACK_JSONL_PATH = ROOT / "docs/planning/pre_gate_b_claim_adjudication_pack_v1.jsonl"
PACK_MD_PATH = ROOT / "docs/planning/pre_gate_b_claim_adjudication_pack_v1.md"

SCHEMA_VERSION = "claim-adjudication-pack-v1"
PACK_VERSION = "pre_gate_b_claim_adjudication_pack_v1"
# Bootstrap-only v1 threshold. This is intentionally conservative but still
# uncalibrated; it should be re-fit against labeled match/mismatch pairs before Gate B.
SEMANTIC_SIMILARITY_MODEL = "all-MiniLM-L6-v2"
SEMANTIC_MISMATCH_THRESHOLD = 0.25

_SEMANTIC_MODEL: Any | None = None
_SEMANTIC_MODEL_LOAD_ATTEMPTED = False


@dataclass(frozen=True)
class Selection:
    rank: int
    hypothesis_id: str
    target_after_adjudication: str
    why_now: str


SELECTIONS = [
    Selection(
        rank=1,
        hypothesis_id="bootstrap:attention_mixed",
        target_after_adjudication="future_held_out",
        why_now="Only mixed candidate in v3-lite; highest leverage for preserving a non-support class in the formal benchmark.",
    ),
    Selection(
        rank=2,
        hypothesis_id="bootstrap:default_mode_network_conflicting",
        target_after_adjudication="future_held_out",
        why_now="Only conflicting candidate retained after the weak precuneus refute was dropped.",
    ),
    Selection(
        rank=3,
        hypothesis_id="claim:88f2eb8941c9228d0071651be108fa58",
        target_after_adjudication="future_held_out",
        why_now="Only Task seed in v3-lite and the cleanest way to diversify the formal benchmark beyond region/concept anchors.",
    ),
    Selection(
        rank=4,
        hypothesis_id="claim:b16751b473f09874df8053775fbb35f0",
        target_after_adjudication="future_held_out",
        why_now="Clean concept-level support case with exact title claim and auditable concept mapping.",
    ),
    Selection(
        rank=5,
        hypothesis_id="claim:872fcaaffec17ba363216ac5eb04c317",
        target_after_adjudication="future_held_out",
        why_now="Intervention-specific amygdala support case that adds richer supported-region coverage than generic cortical rows.",
    ),
    Selection(
        rank=6,
        hypothesis_id="claim:7b858b2e0cfe374856830def8df4a681",
        target_after_adjudication="future_calibration",
        why_now="Highly auditable exact region/title match for a specific brainstem nucleus; strong formal calibration anchor.",
    ),
    Selection(
        rank=7,
        hypothesis_id="claim:28fcbcec2470e0c24db5a5fc716143cc",
        target_after_adjudication="future_calibration",
        why_now="Clean TPJ region seed with exact mapping and low ambiguity, suitable for a durable calibration slot.",
    ),
    Selection(
        rank=8,
        hypothesis_id="pmid:40000003",
        target_after_adjudication="future_held_out",
        why_now="Only insufficient-evidence control; provenance is now repaired, so adjudication can decide whether it remains the negative-control row for Gate B.",
    ),
]


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _read_jsonl_record(path: Path, line_number: int) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        for current, raw in enumerate(handle, start=1):
            if current == line_number:
                return json.loads(raw)
    raise ValueError(f"{path} does not contain line {line_number}")


def _quote_span(quote: str | None) -> dict[str, int] | None:
    text = str(quote or "")
    if not text:
        return None
    return {
        "start_line": 1,
        "end_line": 1,
        "start_char": 0,
        "end_char": len(text),
    }


def _normalize_text(text: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or "")).strip().lower()
    return re.sub(r"\s+", " ", normalized)


def _tokenize(text: str | None) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _normalize_text(text)))


def _lexical_similarity(left: str | None, right: str | None) -> float:
    left_text = _normalize_text(left)
    right_text = _normalize_text(right)
    if not left_text or not right_text:
        return 0.0
    left_tokens = _tokenize(left_text)
    right_tokens = _tokenize(right_text)
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    token_jaccard = intersection / union if union else 0.0
    smaller_cover = intersection / min(len(left_tokens), len(right_tokens))
    sequence_ratio = SequenceMatcher(None, left_text, right_text).ratio()
    return round(max(token_jaccard, smaller_cover, sequence_ratio), 4)


def _load_semantic_model() -> Any | None:
    global _SEMANTIC_MODEL
    global _SEMANTIC_MODEL_LOAD_ATTEMPTED
    if _SEMANTIC_MODEL_LOAD_ATTEMPTED:
        return _SEMANTIC_MODEL
    _SEMANTIC_MODEL_LOAD_ATTEMPTED = True
    try:
        from sentence_transformers import SentenceTransformer

        cache_dir = ROOT / "data/models/sentence-transformers"
        cache_dir.mkdir(parents=True, exist_ok=True)
        _SEMANTIC_MODEL = SentenceTransformer(
            SEMANTIC_SIMILARITY_MODEL,
            cache_folder=str(cache_dir),
        )
    except Exception:
        _SEMANTIC_MODEL = None
    return _SEMANTIC_MODEL


def _semantic_text_similarity(left: str | None, right: str | None) -> tuple[float, str]:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return 0.0, "empty"

    model = _load_semantic_model()
    if model is not None:
        try:
            embeddings = model.encode(
                [left_text, right_text],
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            score = float(np.dot(embeddings[0], embeddings[1]))
            return round(score, 4), "sentence_transformer"
        except Exception:
            pass

    return _lexical_similarity(left_text, right_text), "lexical_overlap"


def _infer_evidence_depth(record: dict[str, Any]) -> str:
    evidence = dict(record.get("evidence") or {})
    paper = dict(record.get("paper") or {})
    section = _normalize_text(evidence.get("section"))
    quote_text = _normalize_text(evidence.get("quote"))
    title_text = _normalize_text(paper.get("title"))
    if section == "title" or (quote_text and title_text and quote_text == title_text):
        return "title_only"
    if (
        not evidence.get("locatable")
        and not evidence.get("direct_quote")
        and not evidence.get("has_statistical_detail")
    ):
        return "unverifiable_snippet"
    if section in {"abstract", "background", "summary"}:
        return "abstract_or_summary"
    if evidence.get("has_statistical_detail"):
        return "body_quote"
    if evidence.get("direct_quote") or evidence.get("locatable"):
        return "body_quote"
    return "unknown"


def _provenance_payload(record: dict[str, Any]) -> dict[str, Any]:
    run = dict(record.get("run") or {})
    return {
        "run_id": str(
            run.get("id") or run.get("run_id") or record.get("run_id") or "unknown"
        ),
        "prompt_hash": str(run.get("prompt_hash") or record.get("prompt_hash") or "unknown"),
        "template_hash": str(
            run.get("template_hash") or record.get("template_hash") or "unknown"
        ),
        "model": str(run.get("model") or record.get("model") or "unknown"),
        "raw_response_path": str(
            run.get("raw_response_path") or record.get("raw_response_path") or "unknown"
        ),
        "loader_version": str(
            run.get("loader_version") or record.get("loader_version") or "unknown"
        ),
        "timestamp": str(record.get("timestamp") or run.get("timestamp") or "unknown"),
    }


def _anchor_warnings(
    *,
    hypothesis_text: str,
    semantic_similarity: float,
    evidence_depth: str,
    source_record: dict[str, Any],
    provenance: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []
    if semantic_similarity < SEMANTIC_MISMATCH_THRESHOLD:
        warnings.append("claim_evidence_semantic_mismatch")
    if evidence_depth == "title_only":
        warnings.append("evidence_depth_title_only")
    if evidence_depth == "unverifiable_snippet":
        warnings.append("evidence_unverifiable_snippet")
    method_rigor = float((source_record.get("variables") or {}).get("method_rigor", 0.0))
    if method_rigor <= 0.0:
        warnings.append("method_rigor_zero")
    if evidence_depth == "title_only" and method_rigor <= 0.0:
        warnings.append("title_only_low_rigor_evidence")
    if provenance.get("loader_version") == "unknown":
        warnings.append("provenance_loader_version_unknown")
    if provenance.get("raw_response_path") == "unknown":
        warnings.append("provenance_raw_response_path_unknown")
    if not hypothesis_text.strip():
        warnings.append("hypothesis_text_missing")
    return sorted(set(warnings))


def _evidence_anchor(
    hypothesis_text: str, record: dict[str, Any], source_record: dict[str, Any]
) -> dict[str, Any]:
    evidence = dict(record.get("evidence") or {})
    claim = dict(record.get("claim") or {})
    paper = dict(record.get("paper") or {})
    run = dict(record.get("run") or {})
    quote_text = str(evidence.get("quote") or "")
    ref_path = source_record["path"]
    ref_line = source_record["line_number"]
    evidence_depth = _infer_evidence_depth(record)
    semantic_similarity, semantic_backend = _semantic_text_similarity(
        hypothesis_text, quote_text
    )
    provenance = _provenance_payload(record)
    return {
        "evidence_id": (
            f"{paper.get('id') or 'unknown'}:"
            f"{claim.get('id') or 'noclaim'}:{evidence.get('span_id') or 'nospan'}"
        ),
        "publication_id": paper.get("id"),
        "claim_id": claim.get("id"),
        "span_id": evidence.get("span_id"),
        "measurement_run_id": run.get("id") or run.get("run_id") or record.get("run_id"),
        "ref": f"{ref_path}#{ref_line}",
        "quote_span": _quote_span(quote_text),
        "quote_text": quote_text or None,
        "section": evidence.get("section"),
        "page": evidence.get("page"),
        "evidence_depth": evidence_depth,
        "semantic_similarity": semantic_similarity,
        "semantic_check_backend": semantic_backend,
        "provenance": provenance,
        "warnings": _anchor_warnings(
            hypothesis_text=hypothesis_text,
            semantic_similarity=semantic_similarity,
            evidence_depth=evidence_depth,
            source_record=source_record,
            provenance=provenance,
        ),
    }


def _dedup_review_queue_entries(manifest_row: dict[str, Any]) -> list[dict[str, Any]]:
    if not REVIEW_QUEUE_PATH.exists():
        return []
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    target_papers = {
        str(item.get("paper_id") or "")
        for item in manifest_row.get("source_records", [])
        if str(item.get("paper_id") or "")
    }
    for line in REVIEW_QUEUE_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        record = dict(row.get("record") or {})
        paper = dict(record.get("paper") or {})
        paper_id = str(paper.get("id") or record.get("paper_id") or "")
        if paper_id not in target_papers:
            continue
        reasons = tuple(row.get("reasons") or [])
        variables = row.get("variables") or {}
        fingerprint = json.dumps(
            {"paper_id": paper_id, "reasons": reasons, "variables": variables},
            sort_keys=True,
        )
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        results.append(
            {
                "queued_at": row.get("queued_at"),
                "reasons": list(reasons),
                "variables": variables,
                "record_ref": f"{manifest_row['source_records'][0]['path']}#{manifest_row['source_records'][0]['line_number']}",
            }
        )
    return results


def _enriched_source_record(source_record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    path = ROOT / str(source_record["path"])
    record = _read_jsonl_record(path, int(source_record["line_number"]))
    variables = compute_gabriel_variables(record, DEFAULT_REQUIRED_PROVENANCE_FIELDS)
    enriched = dict(source_record)
    enriched["variables"] = {
        "mention_strength": variables.mention_strength,
        "mapping_confidence": variables.mapping_confidence,
        "claim_polarity": variables.claim_polarity,
        "claim_strength": variables.claim_strength,
        "evidence_quality": variables.evidence_quality,
        "evidence_quality_score": variables.evidence_quality_score,
        "method_rigor": variables.method_rigor,
        "provenance_completeness": variables.provenance_completeness,
    }
    return enriched, record


def _review_questions(row: dict[str, Any]) -> list[str]:
    verdict = row["expected_verdict"]
    questions = [
        "Does the quoted evidence support the expected verdict without reading model outputs first?",
        "Are the anchor entity and allowed node type specific enough for future benchmark use?",
        "Should this example remain valid after manual review, or should it be retired from the benchmark candidate pool?",
    ]
    if verdict in {"mixed", "conflicting"}:
        questions.append(
            "Are the support and refute sources both strong enough and semantically aligned enough to justify a non-supported verdict class?"
        )
    if verdict == "insufficient_evidence":
        questions.append(
            "Does this still function as a valid negative-control example now that provenance has been repaired, or should it be removed before Gate B?"
        )
    return questions


def _verdict_structure_warnings(
    expected_verdict: str,
    source_records: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
) -> tuple[list[str], dict[str, int]]:
    support_count = 0
    refute_count = 0
    aligned_support_count = 0
    aligned_refute_count = 0
    for source_record, anchor in zip(source_records, anchors, strict=False):
        polarity = str(source_record.get("polarity") or "")
        aligned = "claim_evidence_semantic_mismatch" not in (anchor.get("warnings") or [])
        if polarity == "supports":
            support_count += 1
            if aligned:
                aligned_support_count += 1
        if polarity == "refutes":
            refute_count += 1
            if aligned:
                aligned_refute_count += 1

    warnings: list[str] = []
    if expected_verdict in {"mixed", "conflicting"}:
        if support_count < 1 or refute_count < 1:
            warnings.append("verdict_structural_prerequisite_unmet")
        if aligned_support_count < 1 or aligned_refute_count < 1:
            warnings.append("verdict_semantic_prerequisite_unmet")

    return warnings, {
        "support_count": support_count,
        "refute_count": refute_count,
        "aligned_support_count": aligned_support_count,
        "aligned_refute_count": aligned_refute_count,
    }


def _row_warnings(
    *,
    manifest_row: dict[str, Any],
    source_records: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
) -> tuple[list[str], dict[str, Any]]:
    warnings: list[str] = []
    title_only_count = sum(
        1 for anchor in anchors if anchor.get("evidence_depth") == "title_only"
    )
    method_rigors = [
        float((record.get("variables") or {}).get("method_rigor", 0.0))
        for record in source_records
    ]
    if any(
        "claim_evidence_semantic_mismatch" in (anchor.get("warnings") or [])
        for anchor in anchors
    ):
        warnings.append("claim_evidence_semantic_mismatch_present")
    if title_only_count:
        warnings.append("title_only_evidence_present")
    if any(
        anchor.get("evidence_depth") == "unverifiable_snippet" for anchor in anchors
    ):
        warnings.append("unverifiable_snippet_present")
    if method_rigors and any(score <= 0.0 for score in method_rigors):
        warnings.append("method_rigor_zero_present")
    if method_rigors and all(score <= 0.0 for score in method_rigors):
        warnings.append("all_method_rigor_zero")
    if any(
        anchor.get("provenance", {}).get("loader_version") == "unknown"
        for anchor in anchors
    ):
        warnings.append("provenance_loader_version_unknown")
    structure_warnings, counts = _verdict_structure_warnings(
        str(manifest_row.get("expected_verdict") or ""),
        source_records,
        anchors,
    )
    warnings.extend(structure_warnings)
    builder_checks = {
        **counts,
        "title_only_count": title_only_count,
        "unknown_loader_version_count": sum(
            1
            for anchor in anchors
            if anchor.get("provenance", {}).get("loader_version") == "unknown"
        ),
        "semantic_mismatch_count": sum(
            1
            for anchor in anchors
            if "claim_evidence_semantic_mismatch" in (anchor.get("warnings") or [])
        ),
        "evidence_depths": [anchor.get("evidence_depth") for anchor in anchors],
    }
    return sorted(set(warnings)), builder_checks


def _pack_row(selection: Selection, manifest_row: dict[str, Any], slice_name: str) -> dict[str, Any]:
    enriched_sources: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    for source_record in manifest_row.get("source_records", []):
        enriched, record = _enriched_source_record(source_record)
        enriched_sources.append(enriched)
        anchors.append(_evidence_anchor(manifest_row["text"], record, enriched))

    warnings, builder_checks = _row_warnings(
        manifest_row=manifest_row,
        source_records=enriched_sources,
        anchors=anchors,
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "pack_version": PACK_VERSION,
        "benchmark_version": manifest_row["benchmark_version"],
        "slice": slice_name,
        "manifest_status": "pre_gate_b_adjudication",
        "bootstrap_only": True,
        "rank": selection.rank,
        "target_after_adjudication": selection.target_after_adjudication,
        "why_now": selection.why_now,
        "hypothesis_id": manifest_row["hypothesis_id"],
        "text": manifest_row["text"],
        "entity_hints": manifest_row.get("entity_hints", []),
        "allowed_node_types": manifest_row.get("allowed_node_types", []),
        "expected_verdict": manifest_row["expected_verdict"],
        "expected_anchor_entities": manifest_row.get("expected_anchor_entities", []),
        "expected_supporting_publications": manifest_row.get(
            "expected_supporting_publications", []
        ),
        "expected_conflicting_publications": manifest_row.get(
            "expected_conflicting_publications", []
        ),
        "review_status": manifest_row.get("review_status"),
        "notes": manifest_row.get("notes"),
        "warnings": warnings,
        "source_records": enriched_sources,
        "review_material": {
            "review_queue_entries": _dedup_review_queue_entries(manifest_row),
            "evidence_anchors": anchors,
            "builder_checks": builder_checks,
            "review_questions": _review_questions(manifest_row),
        },
        "adjudication": {
            "status": "pending",
            "submitted_by": "codex",
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "reviewed_by": None,
            "reviewed_at": None,
            "final_verdict": None,
            "rationale": None,
            "valid_for_heldout": None,
            "comments": [],
            "tags": [],
        },
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


def _write_markdown(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Pre-Gate-B Claim Adjudication Pack v1",
        "",
        "As of March 10, 2026.",
        "",
        "This pack is a canonical pre-Gate-B review set derived from `v3-lite`.",
        "It is intended for quote-first manual adjudication before any formal benchmark upgrade.",
        "",
        "## Review Rules",
        "",
        "- Review quote-level evidence before looking at any verifier output.",
        "- Confirm final verdict, rationale, and whether the example is valid for future held-out use.",
        "- If provenance is not good enough, mark the item `needs_revision` or `rejected` rather than forcing a label.",
        "",
        "## Pack Summary",
        "",
        "| Rank | hypothesis_id | current slice | expected_verdict | target after adjudication | builder warnings | why now |",
        "|---:|---|---|---|---|---|---|",
    ]
    for row in rows:
        warning_text = ", ".join(f"`{warning}`" for warning in row.get("warnings", [])) or "none"
        lines.append(
            f"| {row['rank']} | `{row['hypothesis_id']}` | `{row['slice']}` | "
            f"`{row['expected_verdict']}` | `{row['target_after_adjudication']}` | "
            f"{warning_text} | {row['why_now']} |"
        )

    lines.extend(
        [
            "",
            "## Builder Warnings",
            "",
            "- `claim_evidence_semantic_mismatch_present`: at least one evidence quote is not semantically aligned enough with the benchmark claim text.",
            "- `verdict_structural_prerequisite_unmet`: a `mixed` or `conflicting` row is missing either support or refute evidence.",
            "- `verdict_semantic_prerequisite_unmet`: a `mixed` or `conflicting` row does not retain at least one semantically aligned support and one semantically aligned refute.",
            "- `title_only_evidence_present`: at least one anchor is derived only from the paper title.",
            "- `unverifiable_snippet_present`: at least one anchor is a non-locatable, non-direct, non-statistical snippet and should be treated as extraction debt.",
            "- `method_rigor_zero_present` / `all_method_rigor_zero`: extracted evidence has no method-rigor signal for some or all anchors.",
            "",
            "## Item Checklist",
            "",
            "For each row in the JSONL pack:",
            "",
            "1. Read the `review_material.evidence_anchors` quote(s) and provenance first.",
            "2. Decide whether the expected verdict is still correct without using system outputs.",
            "3. Record `final_verdict`, `rationale`, and `valid_for_heldout` in the adjudication block.",
            "4. If the seed is weak but salvageable, set `status=needs_revision` and describe the repair needed.",
            "",
            "## Artifacts",
            "",
            f"- Canonical pack: `{PACK_JSONL_PATH.relative_to(ROOT)}`",
            f"- Source calibration manifest: `{CALIBRATION_PATH.relative_to(ROOT)}`",
            f"- Source held-out manifest: `{HELDOUT_PATH.relative_to(ROOT)}`",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    calibration_rows = {
        row["hypothesis_id"]: row for row in _load_jsonl(CALIBRATION_PATH)
    }
    heldout_rows = {row["hypothesis_id"]: row for row in _load_jsonl(HELDOUT_PATH)}

    packed_rows: list[dict[str, Any]] = []
    for selection in SELECTIONS:
        if selection.hypothesis_id in calibration_rows:
            row = calibration_rows[selection.hypothesis_id]
            packed_rows.append(_pack_row(selection, row, "calibration"))
            continue
        if selection.hypothesis_id in heldout_rows:
            row = heldout_rows[selection.hypothesis_id]
            packed_rows.append(_pack_row(selection, row, "held_out"))
            continue
        raise KeyError(f"{selection.hypothesis_id} not found in v3-lite manifests")

    _write_jsonl(PACK_JSONL_PATH, packed_rows)
    _write_markdown(PACK_MD_PATH, packed_rows)

    summary = {
        "pack_jsonl": str(PACK_JSONL_PATH.relative_to(ROOT)),
        "pack_markdown": str(PACK_MD_PATH.relative_to(ROOT)),
        "n_rows": len(packed_rows),
        "hypothesis_ids": [row["hypothesis_id"] for row in packed_rows],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
