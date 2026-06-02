#!/usr/bin/env python3
"""Mine candidate alias extensions for TaskFamilyMatcher from Task labels."""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml
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


def _fetch_task_label_counts(
    *,
    uri: str,
    user: str,
    password: str,
    database: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    cypher = """
    MATCH (t:Task)
    WITH coalesce(t.name, t.label, t.title, t.id, elementId(t)) AS label, count(*) AS freq
    WHERE label IS NOT NULL AND trim(toString(label)) <> ''
    RETURN toString(label) AS label, toInteger(freq) AS freq
    ORDER BY freq DESC, label ASC
    LIMIT $limit
    """
    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        with driver.session(database=database or None) as session:
            rows = session.run(cypher, {"limit": int(limit)}).data()
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--neo4j-uri", default=_env("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--neo4j-user", default=_env("NEO4J_USER", "neo4j"))
    parser.add_argument("--neo4j-password", default=_env("NEO4J_PASSWORD"))
    parser.add_argument("--neo4j-database", default=_env("NEO4J_DATABASE"))
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
    parser.add_argument("--limit", type=int, default=20000)
    parser.add_argument("--min-score", type=float, default=0.72)
    parser.add_argument("--min-overlap", type=int, default=1)
    parser.add_argument("--min-gap", type=float, default=0.03)
    parser.add_argument("--max-suggestions", type=int, default=500)
    parser.add_argument(
        "--target-methods",
        default="ambiguous_rejected,guardrail_rejected,unmapped",
        help="Comma-separated match methods to mine from",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("tmp/task_family_calibration/task_family_alias_candidates.json"),
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=Path("tmp/task_family_calibration/task_family_alias_candidates.csv"),
    )
    parser.add_argument(
        "--output-yaml",
        type=Path,
        default=Path("tmp/task_family_calibration/task_family_alias_extensions.suggested.yaml"),
    )
    return parser.parse_args()


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "alias",
        "label",
        "frequency",
        "source_method",
        "score",
        "gap",
        "overlap_count",
        "family_id",
        "subfamily_id",
        "paradigm_name",
        "choice",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> None:
    args = parse_args()
    if not args.neo4j_password:
        raise SystemExit("Missing --neo4j-password (or NEO4J_PASSWORD env)")

    taxonomy_path = args.taxonomy_path.expanduser().resolve()
    alias_extensions_path = args.alias_extensions_path.expanduser().resolve()
    matcher = TaskFamilyMatcher(
        taxonomy_path=taxonomy_path,
        alias_extensions_path=alias_extensions_path if alias_extensions_path.exists() else None,
        enable_fuzzy=True,
        aggressive_mode=True,
    )
    if not matcher.available:
        raise SystemExit("TaskFamilyMatcher is unavailable; check taxonomy path.")

    target_methods = {
        token.strip()
        for token in str(args.target_methods).split(",")
        if token.strip()
    }
    rows = _fetch_task_label_counts(
        uri=str(args.neo4j_uri),
        user=str(args.neo4j_user),
        password=str(args.neo4j_password),
        database=args.neo4j_database,
        limit=max(1, int(args.limit)),
    )

    suggestions: list[dict[str, Any]] = []
    seen_aliases: set[str] = set()
    for row in rows:
        label = str(row.get("label") or "").strip()
        if not label:
            continue
        freq = int(row.get("freq") or 0)
        _record, method, _score = matcher.match(label)
        if method not in target_methods:
            continue
        normalized = normalize_task_label(label)
        if not normalized or normalized in seen_aliases:
            continue

        candidates = matcher._collect_fuzzy_candidates(normalized)  # noqa: SLF001
        if not candidates:
            continue
        best = candidates[0]
        second = candidates[1] if len(candidates) > 1 else None
        gap = (
            float(best.combined_score - second.combined_score)
            if second is not None
            else 1.0
        )
        if best.combined_score < float(args.min_score):
            continue
        if best.overlap_count < int(args.min_overlap):
            continue
        if gap < float(args.min_gap):
            continue

        suggestion = {
            "alias": normalized,
            "label": label,
            "frequency": freq,
            "source_method": method,
            "score": round(float(best.combined_score), 4),
            "gap": round(gap, 4),
            "overlap_count": int(best.overlap_count),
            "family_id": best.record.family_id,
            "subfamily_id": best.record.subfamily_id,
            "paradigm_name": best.record.paradigm_name,
            "choice": best.choice,
        }
        suggestions.append(suggestion)
        seen_aliases.add(normalized)
        if len(suggestions) >= int(args.max_suggestions):
            break

    suggestions.sort(
        key=lambda item: (
            int(item.get("frequency", 0)),
            float(item.get("score", 0.0)),
            float(item.get("gap", 0.0)),
        ),
        reverse=True,
    )

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in suggestions:
        key = (row["family_id"], row["subfamily_id"], row["paradigm_name"])
        grouped[key].append(row)

    extension_entries: list[dict[str, Any]] = []
    for rows_for_target in grouped.values():
        for row in rows_for_target:
            extension_entries.append(
                {
                    "alias": row["alias"],
                    "family_id": row["family_id"],
                    "subfamily_id": row["subfamily_id"],
                    "paradigm_name": row["paradigm_name"],
                }
            )

    report = {
        "input": {
            "limit": int(args.limit),
            "min_score": float(args.min_score),
            "min_overlap": int(args.min_overlap),
            "min_gap": float(args.min_gap),
            "target_methods": sorted(target_methods),
        },
        "suggestion_count": len(suggestions),
        "suggestions": suggestions,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    _write_csv(args.output_csv, suggestions)

    yaml_payload = {
        "version": 1,
        "description": "Auto-mined alias extension candidates from Task labels",
        "aliases": extension_entries,
    }
    args.output_yaml.parent.mkdir(parents=True, exist_ok=True)
    args.output_yaml.write_text(
        yaml.safe_dump(yaml_payload, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )

    print(f"Suggestions: {len(suggestions)}")
    print(f"Wrote JSON: {args.output_json}")
    print(f"Wrote CSV: {args.output_csv}")
    print(f"Wrote YAML: {args.output_yaml}")


if __name__ == "__main__":
    main()
