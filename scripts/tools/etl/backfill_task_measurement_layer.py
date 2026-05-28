#!/usr/bin/env python3
"""Backfill Task->MeasurementArtifact mapping for scale/assessment-style labels."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is not None and value != "":
        return value
    return default


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "unknown"


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--neo4j-uri", default=_env("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--neo4j-user", default=_env("NEO4J_USER", "neo4j"))
    parser.add_argument("--neo4j-password", default=_env("NEO4J_PASSWORD"))
    parser.add_argument("--neo4j-database", default=_env("NEO4J_DATABASE"))
    parser.add_argument(
        "--input-freq-tsv",
        type=Path,
        required=True,
        help="TSV file with columns: freq,label (typically forced_uncategorized freq>=2).",
    )
    parser.add_argument("--min-freq", type=int, default=2)
    parser.add_argument(
        "--include-buckets",
        default="scale_assessment,analysis,noise",
        help="Comma-separated buckets to include in measurement layer.",
    )
    parser.add_argument(
        "--method-tag",
        default="task_measurement_layer_v1",
    )
    parser.add_argument(
        "--family-method-tag",
        default="task_family_backfill_v1",
        help="TaskFamily method_tag used for optional pruning.",
    )
    parser.add_argument(
        "--prune-family-edges",
        action="store_true",
        help="Delete BELONGS_TO_FAMILY edges for included labels.",
    )
    parser.add_argument(
        "--exclude-labels-output-tsv",
        type=Path,
        default=Path("tmp/task_family_calibration/round14_excluded_from_taskfamily.tsv"),
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("tmp/task_family_calibration/task_measurement_layer_round14.json"),
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _load_rows(path: Path, min_freq: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            label = str(row.get("label") or "").strip()
            if not label:
                continue
            freq = int(row.get("freq") or 0)
            if freq < min_freq:
                continue
            rows.append(
                {
                    "label": label,
                    "freq": freq,
                    "bucket": _bucket(label),
                    "artifact_id": f"measurement:{_slugify(label)}",
                }
            )
    return rows


def _upsert_measurement_layer(
    *,
    driver: Any,
    database: str | None,
    rows: list[dict[str, Any]],
    method_tag: str,
) -> None:
    query = """
    UNWIND $rows AS row
    MATCH (t:Task)
    WHERE toLower(trim(coalesce(t.name, t.label, t.title, t.id, elementId(t)))) = toLower(trim(row.label))
    MERGE (m:MeasurementArtifact {id: row.artifact_id})
    ON CREATE SET
      m.label = row.label,
      m.category = row.bucket,
      m.created_at = datetime(),
      m.source = 'task_measurement_layer_backfill'
    SET
      m.label = coalesce(m.label, row.label),
      m.category = row.bucket,
      m.updated_at = datetime()
    MERGE (t)-[r:USES_MEASUREMENT]->(m)
    SET
      r.method_tag = $method_tag,
      r.source = 'task_measurement_layer_backfill',
      r.category = row.bucket,
      r.updated_at = datetime(),
      t.mapping_layer = 'measurement',
      t.mapping_bucket = row.bucket
    """
    with driver.session(database=database or None) as session:
        session.run(query, {"rows": rows, "method_tag": method_tag}).consume()


def _prune_family_edges(
    *,
    driver: Any,
    database: str | None,
    rows: list[dict[str, Any]],
    family_method_tag: str,
) -> int:
    query = """
    UNWIND $rows AS row
    MATCH (t:Task)-[r:BELONGS_TO_FAMILY]->(:TaskFamily)
    WHERE toLower(trim(coalesce(t.name, t.label, t.title, t.id, elementId(t)))) = toLower(trim(row.label))
      AND r.method_tag = $family_method_tag
    DELETE r
    RETURN count(r) AS deleted
    """
    with driver.session(database=database or None) as session:
        row = session.run(
            query,
            {"rows": rows, "family_method_tag": family_method_tag},
        ).single()
    return int((row or {}).get("deleted") or 0)


def main() -> None:
    args = parse_args()
    if not args.neo4j_password:
        raise SystemExit("Missing --neo4j-password (or NEO4J_PASSWORD env)")

    include_buckets = {
        token.strip() for token in str(args.include_buckets).split(",") if token.strip()
    }
    input_rows = _load_rows(args.input_freq_tsv.expanduser().resolve(), max(1, int(args.min_freq)))
    selected_rows = [row for row in input_rows if row["bucket"] in include_buckets]

    args.exclude_labels_output_tsv.parent.mkdir(parents=True, exist_ok=True)
    with args.exclude_labels_output_tsv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["freq", "label", "bucket", "artifact_id"],
            delimiter="\t",
        )
        writer.writeheader()
        for row in selected_rows:
            writer.writerow(row)

    deleted_family_edges = 0
    if not args.dry_run and selected_rows:
        driver = GraphDatabase.driver(
            str(args.neo4j_uri),
            auth=(str(args.neo4j_user), str(args.neo4j_password)),
        )
        try:
            _upsert_measurement_layer(
                driver=driver,
                database=args.neo4j_database,
                rows=selected_rows,
                method_tag=str(args.method_tag),
            )
            if args.prune_family_edges:
                deleted_family_edges = _prune_family_edges(
                    driver=driver,
                    database=args.neo4j_database,
                    rows=selected_rows,
                    family_method_tag=str(args.family_method_tag),
                )
        finally:
            driver.close()

    report = {
        "generated_at": _utc_now_iso(),
        "dry_run": bool(args.dry_run),
        "input_rows": len(input_rows),
        "selected_rows": len(selected_rows),
        "include_buckets": sorted(include_buckets),
        "bucket_counts": {
            bucket: sum(1 for row in selected_rows if row["bucket"] == bucket)
            for bucket in sorted(include_buckets)
        },
        "method_tag": str(args.method_tag),
        "family_method_tag": str(args.family_method_tag),
        "deleted_family_edges": int(deleted_family_edges),
        "exclude_labels_output_tsv": str(args.exclude_labels_output_tsv.expanduser().resolve()),
        "selected_preview": selected_rows[:20],
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    print(f"Measurement-layer rows selected: {len(selected_rows)}")
    print(f"Deleted TaskFamily edges: {deleted_family_edges}")
    print(f"Wrote exclude labels: {args.exclude_labels_output_tsv}")
    print(f"Wrote report: {args.output_json}")


if __name__ == "__main__":
    main()
