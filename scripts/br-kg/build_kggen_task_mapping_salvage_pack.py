#!/usr/bin/env python3
"""Build a reviewable salvage pack for KGGEN task-like ONVOC near-misses.

This script is intentionally conservative. It does not modify crosswalks or
ingest anything into BR-KG. It builds a human-reviewable pack that separates:

- task candidates that are close to useful task mappings,
- labels that should be rerouted to construct or baseline/meta-task lanes, and
- labels that should stay out of the task panel because they are modality or
  pipeline descriptors rather than tasks.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_MAPPING_ROWS = Path(
    "data/br-kg/raw/gabriel/eval/gabriel-evidence-expansion-20260311-base/"
    "kggen_eval_gemini30_kg_bootstrap/onvoc/mapping_rows.jsonl"
)
DEFAULT_KGGEN_ADAPTED = Path(
    "data/br-kg/raw/gabriel/eval/gabriel-evidence-expansion-20260311-base/"
    "kggen_eval_gemini30_kg_bootstrap/kggen_adapted.jsonl"
)
DEFAULT_OUTPUT_DIR = Path(
    "data/br-kg/raw/gabriel/eval/gabriel-evidence-expansion-20260311-base/"
    "kggen_eval_gemini30_kg_bootstrap/task_mapping_salvage_pack"
)

TASK_LIKE_RE = re.compile(
    r"\b("
    r"task|reading|memory|attention|language|inhibition|go/no-go|n-back|stroop|"
    r"checkerboard|resting|fmri|paradigm|cognitive|executive|semantic|"
    r"phonological|visuospatial|learning|reward|emotion|face-name|paired-associate"
    r")\b",
    flags=re.IGNORECASE,
)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def _normalize(value: str | None) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[_\-]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _is_task_like(label: str | None) -> bool:
    return bool(TASK_LIKE_RE.search(label or ""))


def _priority_for_bucket(bucket: str) -> int:
    order = {
        "threshold_gap": 1,
        "crosswalk_gap": 1,
        "construct_gap": 2,
        "meta_baseline_gap": 2,
        "non_task_modality": 3,
        "generic_ambiguity": 3,
    }
    return order.get(bucket, 4)


def _classify_candidate(
    row: dict[str, Any],
    adapted_record: dict[str, Any] | None,
) -> dict[str, Any]:
    label = str(row.get("source_label") or "")
    label_norm = _normalize(label)
    status = str(row.get("status") or "")
    top1_score = row.get("top1_score")
    min_score = 0.82
    score_gap = None
    if isinstance(top1_score, int | float):
        score_gap = round(max(0.0, float(min_score) - float(top1_score)), 6)

    suggested_action = "manual_review"
    bucket = "generic_ambiguity"
    suggested_onvoc_id = row.get("onvoc_id")
    suggested_onvoc_label = row.get("onvoc_label")
    taxonomy_hint = ""
    rationale = ""

    if label_norm == "phonological localizers":
        bucket = "threshold_gap"
        suggested_action = "add_task_alias_review"
        suggested_onvoc_id = "ONVOC_0000475"
        suggested_onvoc_label = "Phonological Processing"
        taxonomy_hint = (
            "Language family / Phonology & Morphology subfamily; also plausible "
            "Functional Localizers lane because the source is a localizer."
        )
        rationale = (
            "The current top candidate already lands on a plausible ONVOC task "
            "target. This looks like a localizer-to-task alias gap rather than a "
            "semantic mismatch."
        )
    elif label_norm == "semantic localizers":
        bucket = "threshold_gap"
        suggested_action = "add_task_alias_review"
        suggested_onvoc_id = "ONVOC_0000477"
        suggested_onvoc_label = "Semantics"
        taxonomy_hint = (
            "Language family / Semantic Processing subfamily; also plausible "
            "Functional Localizers lane because the source is a localizer."
        )
        rationale = (
            "The current top candidate is semantically aligned. The miss looks "
            "driven by alias or score calibration, not by the absence of a "
            "reasonable task target."
        )
    elif label_norm == "word reading":
        bucket = "crosswalk_gap"
        suggested_action = "add_task_alias_review"
        suggested_onvoc_id = None
        suggested_onvoc_label = None
        taxonomy_hint = (
            "Language family / Lexical Access & Orthography. Taxonomy explicitly "
            "covers word/nonword reading, but the current ONVOC hit "
            "'Reading Comprehension' is too coarse."
        )
        rationale = (
            "This is task-like, but the best current ONVOC label is not a clean "
            "match. It needs a dedicated reading/lexical-access alias or a safer "
            "manual crosswalk instead of auto-promoting 'Reading Comprehension'."
        )
    elif label_norm == "inclusive face name fmri task":
        bucket = "crosswalk_gap"
        suggested_action = "manual_task_alias_review"
        suggested_onvoc_id = None
        suggested_onvoc_label = None
        taxonomy_hint = (
            "Likely episodic-memory / associative-memory flavored, but no clean "
            "existing task alias is exposed in the current crosswalk."
        )
        rationale = (
            "This is a task label, but the current ontology surfaces do not offer "
            "a safe direct auto-map. Manual alias design is needed."
        )
    elif label_norm in {"cognitive performance", "cognitive function"}:
        bucket = "construct_gap"
        suggested_action = "reroute_construct_lane"
        suggested_onvoc_id = None
        suggested_onvoc_label = None
        taxonomy_hint = (
            "Treat as construct/outcome rather than task. Keep out of the task "
            "panel unless future evidence ties it to a specific paradigm."
        )
        rationale = (
            "These labels describe broad constructs or outcomes, not paradigms. "
            "Task-panel forcing would create false specificity."
        )
    elif label_norm == "resting state fmri":
        bucket = "meta_baseline_gap"
        suggested_action = "reroute_meta_baseline_lane"
        suggested_onvoc_id = None
        suggested_onvoc_label = None
        taxonomy_hint = (
            "Functional Localizers & Baseline Tasks family; treat as baseline/meta "
            "rather than an ordinary task-panel concept."
        )
        rationale = (
            "Resting-state belongs in a baseline/meta-task lane. The issue is "
            "policy mismatch, not lack of a task ontology string."
        )
    elif label_norm in {
        "task based fmri",
        "bold fmri based regional intrinsic neural timescales",
        "bold fmri",
        "fmri processing",
        "fmri",
    }:
        bucket = "non_task_modality"
        suggested_action = "blacklist_non_task_modality"
        suggested_onvoc_id = None
        suggested_onvoc_label = None
        taxonomy_hint = (
            "Modality / pipeline / acquisition descriptor; should be rerouted to "
            "method metadata, not task panel."
        )
        rationale = (
            "These labels describe imaging modality or processing context rather "
            "than a cognitive paradigm. Auto-mapping them into task nodes is a "
            "category error."
        )
    elif status == "below_threshold":
        bucket = "threshold_gap"
        suggested_action = "manual_review"
        rationale = (
            "This label reached a concrete ONVOC candidate but stayed below the "
            "auto-map threshold. Review whether alias expansion is warranted."
        )
    elif status == "ambiguous":
        bucket = "generic_ambiguity"
        suggested_action = "manual_review"
        rationale = (
            "The mapper found multiple nearby candidates without enough margin to "
            "auto-promote."
        )
    else:
        rationale = "Needs manual review."

    priority = _priority_for_bucket(bucket)
    paper = adapted_record.get("paper") if isinstance(adapted_record, dict) else {}
    claim = adapted_record.get("claim") if isinstance(adapted_record, dict) else {}
    evidence = adapted_record.get("evidence") if isinstance(adapted_record, dict) else {}
    signals = adapted_record.get("signals") if isinstance(adapted_record, dict) else {}

    return {
        "schema_version": "kggen-task-mapping-salvage-pack-v1",
        "pack_version": "task_mapping_salvage_pack_20260312",
        "record_index": row.get("record_index"),
        "paper_id": paper.get("id"),
        "paper_title": paper.get("title"),
        "source_id": row.get("source_id"),
        "source_label": label,
        "current_status": status,
        "current_reason": row.get("reason"),
        "current_method": row.get("method"),
        "current_onvoc_id": row.get("onvoc_id"),
        "current_onvoc_label": row.get("onvoc_label"),
        "current_top1_score": row.get("top1_score"),
        "current_top2_score": row.get("top2_score"),
        "current_score_gap_to_min": score_gap,
        "salvage_bucket": bucket,
        "priority_rank": priority,
        "suggested_action": suggested_action,
        "suggested_onvoc_id": suggested_onvoc_id,
        "suggested_onvoc_label": suggested_onvoc_label,
        "taxonomy_hint": taxonomy_hint,
        "why_now": rationale,
        "claim_text": claim.get("text"),
        "evidence_quote": evidence.get("quote"),
        "evidence_section": evidence.get("section"),
        "source_ref": (
            "data/br-kg/raw/gabriel/eval/gabriel-evidence-expansion-20260311-base/"
            f"kggen_eval_gemini30_kg_bootstrap/kggen_adapted.jsonl#{row.get('record_index')}"
        ),
        "signals": {
            "mention_frequency": signals.get("mention_frequency"),
            "title_hit": signals.get("title_hit"),
            "abstract_hit": signals.get("abstract_hit"),
            "context_overlap": signals.get("context_overlap"),
            "statistical_density": signals.get("statistical_density"),
            "assertive_verb_ratio": signals.get("assertive_verb_ratio"),
        },
    }


def build_task_mapping_salvage_pack(
    *,
    mapping_rows_path: Path,
    kggen_adapted_path: Path,
    output_dir: Path,
    include_mapped_controls: bool = True,
) -> dict[str, Any]:
    mapping_rows = _read_jsonl(mapping_rows_path)
    adapted_rows = _read_jsonl(kggen_adapted_path)
    adapted_by_index = {idx: row for idx, row in enumerate(adapted_rows, start=1)}

    unique_task_like: dict[str, dict[str, Any]] = {}
    mapped_controls: list[dict[str, Any]] = []
    for row in mapping_rows:
        label = str(row.get("source_label") or "")
        source_id = str(row.get("source_id") or "").strip()
        if not source_id or not _is_task_like(label):
            continue
        if source_id in unique_task_like:
            continue
        if str(row.get("status") or "") == "mapped":
            if include_mapped_controls:
                mapped_controls.append(
                    {
                        "record_index": row.get("record_index"),
                        "source_id": source_id,
                        "source_label": label,
                        "current_onvoc_id": row.get("onvoc_id"),
                        "current_onvoc_label": row.get("onvoc_label"),
                        "current_method": row.get("method"),
                    }
                )
            continue
        unique_task_like[source_id] = row

    pack = [
        _classify_candidate(row, adapted_by_index.get(int(row.get("record_index") or 0)))
        for row in unique_task_like.values()
    ]
    pack.sort(
        key=lambda item: (
            int(item["priority_rank"]),
            str(item["salvage_bucket"]),
            str(item["source_label"]).lower(),
        )
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / "task_mapping_salvage_pack.jsonl"
    tsv_path = output_dir / "task_mapping_salvage_pack.tsv"
    report_path = output_dir / "task_mapping_salvage_report.json"

    _write_jsonl(jsonl_path, pack)

    with tsv_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "priority_rank",
            "salvage_bucket",
            "suggested_action",
            "source_label",
            "paper_id",
            "current_status",
            "current_onvoc_label",
            "current_top1_score",
            "current_score_gap_to_min",
            "suggested_onvoc_label",
            "taxonomy_hint",
            "source_ref",
        ]
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            delimiter="\t",
        )
        writer.writeheader()
        for row in pack:
            writer.writerow({field: row.get(field) for field in fieldnames})

    bucket_counts = Counter(item["salvage_bucket"] for item in pack)
    action_counts = Counter(item["suggested_action"] for item in pack)
    report = {
        "schema_version": "kggen-task-mapping-salvage-report-v1",
        "inputs": {
            "mapping_rows_path": str(mapping_rows_path),
            "kggen_adapted_path": str(kggen_adapted_path),
        },
        "counts": {
            "mapping_rows_total": len(mapping_rows),
            "task_like_unique_unresolved": len(pack),
            "mapped_controls": len(mapped_controls),
        },
        "bucket_counts": dict(bucket_counts),
        "action_counts": dict(action_counts),
        "artifacts": {
            "salvage_pack_jsonl": str(jsonl_path),
            "salvage_pack_tsv": str(tsv_path),
            "report_json": str(report_path),
        },
        "mapped_controls": mapped_controls,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build KGGEN task-mapping salvage pack from ONVOC mapping rows."
    )
    parser.add_argument(
        "--mapping-rows",
        type=Path,
        default=DEFAULT_MAPPING_ROWS,
        help="Path to ONVOC mapping_rows.jsonl",
    )
    parser.add_argument(
        "--kggen-adapted",
        type=Path,
        default=DEFAULT_KGGEN_ADAPTED,
        help="Path to KGGEN-adapted JSONL from eval-kggen",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for salvage-pack artifacts",
    )
    parser.add_argument(
        "--no-mapped-controls",
        action="store_true",
        help="Exclude mapped task-like controls from the JSON report.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the report payload as JSON.",
    )
    args = parser.parse_args()

    report = build_task_mapping_salvage_pack(
        mapping_rows_path=args.mapping_rows,
        kggen_adapted_path=args.kggen_adapted,
        output_dir=args.output_dir,
        include_mapped_controls=not args.no_mapped_controls,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=True, indent=2))
    else:
        print(f"Wrote salvage pack to {report['artifacts']['salvage_pack_jsonl']}")


if __name__ == "__main__":
    main()
