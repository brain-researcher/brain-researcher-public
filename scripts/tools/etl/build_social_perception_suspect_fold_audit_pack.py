#!/usr/bin/env python3
"""Build an audit pack for suspect Social Perception task-family folds."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SOCIAL_PERCEPTION_ONVOC_ID = "ONVOC_0000503"
SPEECH_SUBFAMILY_ID = "sf_speech_perception_comprehension"
SPEECH_TASK_ID = f"task:subfamily:{SPEECH_SUBFAMILY_ID}"

SOCIAL_SIGNAL_TERMS = (
    "social perception",
    "face",
    "faces",
    "familiar",
    "self-face",
    "gaze",
    "emotion",
    "person perception",
    "personally familiar",
    "social",
)
SPEECH_SIGNAL_TERMS = (
    "speech",
    "language",
    "semantic",
    "phonolog",
    "auditory",
    "lexical",
    "reading",
    "verbal",
    "sentence",
    "comprehension",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if raw:
                yield json.loads(raw)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _load_source_index(mapping_rows_path: Path) -> dict[str, str]:
    by_source_id: dict[str, str] = {}
    for row in _iter_jsonl(mapping_rows_path):
        source_id = _clean_text(row.get("source_id"))
        source_label = _clean_text(row.get("source_label"))
        if source_id and source_label and source_id not in by_source_id:
            by_source_id[source_id] = source_label
    return by_source_id


def _unique_labels(
    row: dict[str, Any],
    *,
    by_source_id: dict[str, str],
) -> list[str]:
    labels: list[str] = []
    target = row.get("target") or {}
    mapping = row.get("mapping") or {}
    normalization = row.get("normalization") or {}
    task_panel = (
        normalization.get("task_panel") if isinstance(normalization, dict) else {}
    )
    for candidate_label in (
        _clean_text(task_panel.get("family_match_input_label")),
        _clean_text(target.get("original_label")),
    ):
        if candidate_label and candidate_label not in labels:
            labels.append(candidate_label)
    for candidate_id in (
        _clean_text(mapping.get("original_canonical_id")),
        _clean_text(target.get("original_id")),
    ):
        label = by_source_id.get(candidate_id)
        if label and label not in labels:
            labels.append(label)
    target_label = _clean_text(target.get("label"))
    if target_label and target_label not in labels:
        labels.append(target_label)
    return labels


def _matched_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    lowered = text.lower()
    return [term for term in terms if term in lowered]


def _classify_row(
    row: dict[str, Any], *, source_labels: list[str]
) -> tuple[str, list[str], list[str], list[str]]:
    paper = row.get("paper") or {}
    claim = row.get("claim") or {}
    evidence = row.get("evidence") or {}
    target = row.get("target") or {}
    normalization = row.get("normalization") or {}
    task_panel = (
        normalization.get("task_panel") if isinstance(normalization, dict) else {}
    )
    text_fields = [
        _clean_text(paper.get("title")),
        _clean_text(claim.get("text")),
        _clean_text(evidence.get("quote")),
        _clean_text(task_panel.get("family_match_input_label")),
        *source_labels,
    ]
    combined_text = " ".join(field for field in text_fields if field)
    social_hits = _matched_terms(combined_text, SOCIAL_SIGNAL_TERMS)
    speech_hits = _matched_terms(combined_text, SPEECH_SIGNAL_TERMS)
    reason_codes: list[str] = []
    if social_hits:
        reason_codes.append("social_face_signal")
    if speech_hits:
        reason_codes.append("speech_language_signal")
    if not _clean_text(task_panel.get("family_match_input_label")):
        reason_codes.append("missing_match_input_label")
    if _clean_text(task_panel.get("family_match_method")) == "aggressive_fuzzy_guarded":
        reason_codes.append("aggressive_fuzzy_guarded")
    if _clean_text(target.get("label")).lower() == "social perception":
        reason_codes.append("generic_social_perception_label")

    if social_hits and not speech_hits:
        bucket = "high_conflict_social_not_speech"
    elif social_hits:
        bucket = "mixed_social_and_speech_signals"
    else:
        bucket = "other_review_needed"
    return bucket, social_hits, speech_hits, reason_codes


def build_social_perception_suspect_fold_audit_pack(
    *,
    package_dir: Path,
    output_dir: Path,
    target_task_id: str = SPEECH_TASK_ID,
    target_onvoc_id: str = SOCIAL_PERCEPTION_ONVOC_ID,
) -> dict[str, Any]:
    package_dir = package_dir.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    records_path = package_dir / "task_panel_records.jsonl"
    mapping_rows_path = package_dir / "task_panel_mapping_rows.jsonl"
    if not records_path.exists() or not mapping_rows_path.exists():
        missing = [
            str(path) for path in (records_path, mapping_rows_path) if not path.exists()
        ]
        raise FileNotFoundError(f"Missing required inputs: {missing}")

    by_source_id = _load_source_index(mapping_rows_path)

    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / "suspect_fold_audit_pack.jsonl"
    tsv_path = output_dir / "suspect_fold_audit_pack.tsv"
    summary_path = output_dir / "suspect_fold_summary.json"

    selected_rows: list[dict[str, Any]] = []
    bucket_counts: Counter[str] = Counter()
    method_counts: Counter[str] = Counter()
    primary_source_counts: Counter[str] = Counter()

    with jsonl_path.open("w", encoding="utf-8") as jsonl_handle:
        for row in _iter_jsonl(records_path):
            target = row.get("target") or {}
            normalization = row.get("normalization") or {}
            task_panel = (
                normalization.get("task_panel")
                if isinstance(normalization, dict)
                else {}
            )
            onvoc = (
                normalization.get("onvoc") if isinstance(normalization, dict) else {}
            )
            target_id = _clean_text(target.get("id"))
            onvoc_id = _clean_text(target.get("onvoc_id")) or _clean_text(
                (onvoc or {}).get("onvoc_id")
            )
            if target_id != target_task_id:
                continue
            if target_onvoc_id and onvoc_id != target_onvoc_id:
                continue

            source_labels = _unique_labels(
                row,
                by_source_id=by_source_id,
            )
            bucket, social_hits, speech_hits, reason_codes = _classify_row(
                row, source_labels=source_labels
            )
            paper = row.get("paper") or {}
            claim = row.get("claim") or {}
            evidence = row.get("evidence") or {}
            mapping = row.get("mapping") or {}

            audit_row = {
                "paper_id": _clean_text(paper.get("id")),
                "paper_original_id": _clean_text(paper.get("original_id")),
                "paper_pmid": _clean_text(paper.get("pmid")),
                "paper_doi": _clean_text(paper.get("doi")),
                "paper_title": _clean_text(paper.get("title")),
                "claim_id": _clean_text(claim.get("id")),
                "claim_text": _clean_text(claim.get("text")),
                "evidence_quote": _clean_text(evidence.get("quote")),
                "target_id": target_id,
                "target_label": _clean_text(target.get("label")),
                "target_original_id": _clean_text(target.get("original_id")),
                "mapping_original_canonical_id": _clean_text(
                    mapping.get("original_canonical_id")
                ),
                "mapping_onvoc_id": _clean_text(mapping.get("onvoc_id")) or onvoc_id,
                "mapping_confidence": mapping.get("mapping_confidence"),
                "family_id": _clean_text(task_panel.get("family_id")),
                "subfamily_id": _clean_text(task_panel.get("subfamily_id")),
                "family_match_method": _clean_text(
                    task_panel.get("family_match_method")
                ),
                "family_match_score": task_panel.get("family_match_score"),
                "family_match_input_label": _clean_text(
                    task_panel.get("family_match_input_label")
                ),
                "heuristic_bucket": bucket,
                "social_signal_terms": social_hits,
                "speech_signal_terms": speech_hits,
                "reason_codes": reason_codes,
                "source_label_candidates": source_labels,
            }
            jsonl_handle.write(json.dumps(audit_row, ensure_ascii=False) + "\n")
            selected_rows.append(audit_row)
            bucket_counts[bucket] += 1
            method_counts[audit_row["family_match_method"] or ""] += 1
            if source_labels:
                primary_source_counts[source_labels[0]] += 1

    tsv_fields = [
        "paper_id",
        "paper_original_id",
        "paper_pmid",
        "paper_doi",
        "paper_title",
        "claim_id",
        "claim_text",
        "evidence_quote",
        "target_id",
        "target_label",
        "target_original_id",
        "mapping_original_canonical_id",
        "mapping_onvoc_id",
        "mapping_confidence",
        "family_id",
        "subfamily_id",
        "family_match_method",
        "family_match_score",
        "family_match_input_label",
        "heuristic_bucket",
        "social_signal_terms",
        "speech_signal_terms",
        "reason_codes",
        "source_label_candidates",
    ]
    with tsv_path.open("w", encoding="utf-8", newline="") as tsv_handle:
        writer = csv.DictWriter(tsv_handle, fieldnames=tsv_fields, delimiter="\t")
        writer.writeheader()
        for row in selected_rows:
            writer.writerow(
                {
                    **row,
                    "social_signal_terms": " | ".join(row["social_signal_terms"]),
                    "speech_signal_terms": " | ".join(row["speech_signal_terms"]),
                    "reason_codes": " | ".join(row["reason_codes"]),
                    "source_label_candidates": " | ".join(
                        row["source_label_candidates"]
                    ),
                }
            )

    summary = {
        "generated_at": _utc_now_iso(),
        "package_dir": str(package_dir),
        "records_path": str(records_path),
        "mapping_rows_path": str(mapping_rows_path),
        "target_task_id": target_task_id,
        "target_onvoc_id": target_onvoc_id,
        "suspect_rows_total": len(selected_rows),
        "unique_papers": len(
            {row["paper_id"] for row in selected_rows if row["paper_id"]}
        ),
        "unique_source_ids": len(
            {
                row["mapping_original_canonical_id"]
                for row in selected_rows
                if row["mapping_original_canonical_id"]
            }
        ),
        "heuristic_bucket_counts": dict(bucket_counts),
        "family_match_method_counts": dict(method_counts),
        "top_primary_source_labels": primary_source_counts.most_common(20),
        "sample_rows": selected_rows[:20],
        "artifacts": {
            "jsonl": str(jsonl_path),
            "tsv": str(tsv_path),
            "summary": str(summary_path),
        },
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package-dir",
        type=Path,
        required=True,
        help="Task-panel package directory containing task_panel_records.jsonl.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for the audit pack. Defaults to <package-dir>/social_perception_suspect_fold_audit.",
    )
    parser.add_argument(
        "--target-task-id",
        type=str,
        default=SPEECH_TASK_ID,
        help="Exact folded task id to audit.",
    )
    parser.add_argument(
        "--target-onvoc-id",
        type=str,
        default=SOCIAL_PERCEPTION_ONVOC_ID,
        help="Expected ONVOC id for the suspect fold cluster.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON summary.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir or (
        args.package_dir.expanduser().resolve() / "social_perception_suspect_fold_audit"
    )
    summary = build_social_perception_suspect_fold_audit_pack(
        package_dir=args.package_dir,
        output_dir=output_dir,
        target_task_id=args.target_task_id,
        target_onvoc_id=args.target_onvoc_id,
    )
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"Audit pack: {summary['artifacts']['jsonl']}")
        print(f"Summary: {summary['artifacts']['summary']}")
        print(f"Suspect rows: {summary['suspect_rows_total']}")


if __name__ == "__main__":
    main()
