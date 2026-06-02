#!/usr/bin/env python3
"""Export prioritized true-task candidates from forced_uncategorized backlog."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

from brain_researcher.services.br_kg.task_family_matcher import (
    TaskFamilyMatcher,
    normalize_task_label,
)


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is not None and value != "":
        return value
    return default


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--neo4j-uri", default=_env("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--neo4j-user", default=_env("NEO4J_USER", "neo4j"))
    parser.add_argument("--neo4j-password", default=_env("NEO4J_PASSWORD"))
    parser.add_argument("--neo4j-database", default=_env("NEO4J_DATABASE"))
    parser.add_argument("--method-tag", default="task_family_backfill_v1")
    parser.add_argument(
        "--taxonomy-path",
        type=Path,
        default=Path("configs/taxonomy/exports/task_families_master.yaml"),
    )
    parser.add_argument(
        "--alias-extensions-path",
        type=Path,
        default=Path("configs/taxonomy/exports/task_family_alias_extensions.yaml"),
    )
    parser.add_argument(
        "--exclude-labels-tsv",
        type=Path,
        default=Path("tmp/task_family_calibration/round14_excluded_from_taskfamily.tsv"),
        help="Optional labels TSV to exclude from true-task export.",
    )
    parser.add_argument("--min-score", type=float, default=0.66)
    parser.add_argument("--min-gap", type=float, default=0.015)
    parser.add_argument("--min-freq", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--output-all-csv",
        type=Path,
        default=Path("tmp/task_family_calibration/round14_unmapped_priority_all.csv"),
    )
    parser.add_argument(
        "--output-true-task-csv",
        type=Path,
        default=Path("tmp/task_family_calibration/round14_unmapped_true_task_priority.csv"),
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("tmp/task_family_calibration/round14_unmapped_priority_summary.json"),
    )
    return parser.parse_args()


def _load_excluded_labels(path: Path | None) -> set[str]:
    if path is None:
        return set()
    p = path.expanduser().resolve()
    if not p.exists():
        return set()
    lines = [line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return set()

    delimiter = "\t" if "\t" in lines[0] else ","
    labels: set[str] = set()
    header = [token.strip().lower() for token in lines[0].split(delimiter)]
    if "label" in header:
        label_idx = header.index("label")
        for line in lines[1:]:
            parts = [token.strip() for token in line.split(delimiter)]
            raw = parts[label_idx] if label_idx < len(parts) else ""
            norm = normalize_task_label(raw)
            if norm:
                labels.add(norm)
    else:
        for line in lines:
            norm = normalize_task_label(line)
            if norm:
                labels.add(norm)
    return labels


def _bucket(label: str) -> str:
    lower = label.lower()
    if any(token in lower for token in ("404", "not found", "page not found")):
        return "noise"
    if any(
        token in lower
        for token in (
            "analysis",
            "measurement",
            "mri",
            "fmri",
            "pet",
            "psg",
            "causality",
            "centrality",
            "traveling waves",
            "ivaso",
            "bci",
        )
    ):
        return "analysis"
    if any(
        token in lower
        for token in (
            "scale",
            "inventory",
            "assessment",
            "battery",
            "score",
            "index",
            "questionnaire",
            "quality of life",
            "wechsler",
            "raven",
            "psychometric",
            "self-report",
            "self report",
        )
    ):
        return "scale_assessment"
    return "task_like"


def _fetch_backlog_rows(
    *,
    uri: str,
    user: str,
    password: str,
    database: str | None,
    method_tag: str,
) -> list[dict[str, Any]]:
    cypher = """
    MATCH (t:Task)-[r:BELONGS_TO_FAMILY]->(:TaskFamily)
    WHERE r.method_tag = $method_tag AND r.match_method = 'forced_uncategorized'
    WITH coalesce(t.name, t.label, t.title, t.id, elementId(t)) AS label, count(*) AS freq
    WHERE label IS NOT NULL AND trim(toString(label)) <> ''
    RETURN toString(label) AS label, toInteger(freq) AS freq
    ORDER BY freq DESC, label ASC
    """
    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        with driver.session(database=database or None) as session:
            return session.run(cypher, {"method_tag": method_tag}).data()


def _priority_score(
    *,
    freq: int,
    max_freq: int,
    best_score: float,
    gap: float,
    overlap: int,
) -> float:
    freq_norm = (math.log1p(freq) / math.log1p(max_freq)) if max_freq > 0 else 0.0
    gap_norm = min(1.0, max(0.0, gap) / 0.20)
    overlap_norm = min(1.0, max(0, overlap) / 3.0)
    return round(
        0.45 * freq_norm
        + 0.40 * max(0.0, best_score)
        + 0.10 * gap_norm
        + 0.05 * overlap_norm,
        6,
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "rank",
        "priority_score",
        "freq",
        "bucket",
        "label",
        "normalized",
        "best_score",
        "gap",
        "overlap_count",
        "family_id",
        "subfamily_id",
        "paradigm_name",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in fieldnames})


def main() -> None:
    args = parse_args()
    if not args.neo4j_password:
        raise SystemExit("Missing --neo4j-password (or NEO4J_PASSWORD env)")

    matcher = TaskFamilyMatcher(
        taxonomy_path=args.taxonomy_path.expanduser().resolve(),
        alias_extensions_path=(
            args.alias_extensions_path.expanduser().resolve()
            if args.alias_extensions_path.expanduser().resolve().exists()
            else None
        ),
        enable_fuzzy=True,
        aggressive_mode=True,
    )
    if not matcher.available:
        raise SystemExit("TaskFamilyMatcher unavailable.")

    excluded_labels = _load_excluded_labels(args.exclude_labels_tsv)
    backlog_rows = _fetch_backlog_rows(
        uri=str(args.neo4j_uri),
        user=str(args.neo4j_user),
        password=str(args.neo4j_password),
        database=args.neo4j_database,
        method_tag=str(args.method_tag),
    )

    max_freq = max((int(row.get("freq") or 0) for row in backlog_rows), default=1)
    all_rows: list[dict[str, Any]] = []
    for row in backlog_rows:
        label = str(row.get("label") or "").strip()
        freq = int(row.get("freq") or 0)
        if not label or freq < int(args.min_freq):
            continue
        normalized = normalize_task_label(label)
        bucket = _bucket(label)
        excluded = bool(normalized and normalized in excluded_labels)

        best_score = 0.0
        gap = 0.0
        overlap_count = 0
        family_id = ""
        subfamily_id = ""
        paradigm_name = ""

        if normalized:
            cands = matcher._collect_fuzzy_candidates(normalized)  # noqa: SLF001
            if cands:
                best = cands[0]
                second = cands[1] if len(cands) > 1 else None
                best_score = float(best.combined_score)
                overlap_count = int(best.overlap_count)
                gap = (
                    float(best.combined_score - second.combined_score)
                    if second is not None
                    else 1.0
                )
                family_id = best.record.family_id
                subfamily_id = best.record.subfamily_id
                paradigm_name = best.record.paradigm_name

        all_rows.append(
            {
                "freq": freq,
                "bucket": bucket,
                "label": label,
                "normalized": normalized,
                "best_score": round(best_score, 4),
                "gap": round(gap, 4),
                "overlap_count": overlap_count,
                "family_id": family_id,
                "subfamily_id": subfamily_id,
                "paradigm_name": paradigm_name,
                "excluded_by_measurement_layer": excluded,
                "priority_score": _priority_score(
                    freq=freq,
                    max_freq=max_freq,
                    best_score=best_score,
                    gap=gap,
                    overlap=overlap_count,
                ),
            }
        )

    all_rows.sort(key=lambda item: (item["priority_score"], item["freq"]), reverse=True)
    for idx, row in enumerate(all_rows, start=1):
        row["rank"] = idx

    true_task_rows = [
        row
        for row in all_rows
        if row["bucket"] == "task_like"
        and not row["excluded_by_measurement_layer"]
        and float(row["best_score"]) >= float(args.min_score)
        and float(row["gap"]) >= float(args.min_gap)
    ]
    if int(args.limit) > 0:
        true_task_rows = true_task_rows[: int(args.limit)]
    for idx, row in enumerate(true_task_rows, start=1):
        row["rank"] = idx

    _write_csv(args.output_all_csv, all_rows)
    _write_csv(args.output_true_task_csv, true_task_rows)

    summary = {
        "method_tag": str(args.method_tag),
        "input_backlog_labels": len(backlog_rows),
        "excluded_labels_count": len(excluded_labels),
        "bucket_counts": {
            "task_like": sum(1 for row in all_rows if row["bucket"] == "task_like"),
            "scale_assessment": sum(1 for row in all_rows if row["bucket"] == "scale_assessment"),
            "analysis": sum(1 for row in all_rows if row["bucket"] == "analysis"),
            "noise": sum(1 for row in all_rows if row["bucket"] == "noise"),
        },
        "true_task_candidate_count": len(true_task_rows),
        "criteria": {
            "min_score": float(args.min_score),
            "min_gap": float(args.min_gap),
            "min_freq": int(args.min_freq),
        },
        "top_true_task_preview": true_task_rows[:20],
        "outputs": {
            "all_csv": str(args.output_all_csv.expanduser().resolve()),
            "true_task_csv": str(args.output_true_task_csv.expanduser().resolve()),
        },
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(summary, ensure_ascii=True, indent=2), encoding="utf-8")

    print(f"Backlog labels: {len(backlog_rows)}")
    print(f"True-task candidates: {len(true_task_rows)}")
    print(f"Wrote all rows: {args.output_all_csv}")
    print(f"Wrote true-task rows: {args.output_true_task_csv}")
    print(f"Wrote summary: {args.output_json}")


if __name__ == "__main__":
    main()
