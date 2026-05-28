#!/usr/bin/env python3
"""Backfill Task->TaskFamily BELONGS_TO_FAMILY edges via TaskFamilyMatcher."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

from brain_researcher.services.neurokg.task_family_matcher import (
    TaskFamilyMatcher,
    normalize_task_label,
)

_MAPPED_METHODS = {"exact_alias", "fuzzy_alias", "aggressive_fuzzy_guarded"}
_PROFILE_DEFAULTS: dict[str, dict[str, float]] = {
    "legacy": {
        "fuzzy_threshold": 0.86,
        "aggressive_primary_threshold": 0.72,
        "aggressive_secondary_threshold": 0.64,
        "ambiguity_margin": 0.04,
        "min_token_overlap": 1.0,
    },
    "calibrated_v1": {
        "fuzzy_threshold": 0.82,
        "aggressive_primary_threshold": 0.68,
        "aggressive_secondary_threshold": 0.60,
        "ambiguity_margin": 0.03,
        "min_token_overlap": 1.0,
    },
}


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is not None and value != "":
        return value
    return default


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    parser.add_argument(
        "--profile",
        default="calibrated_v1",
        choices=sorted(_PROFILE_DEFAULTS.keys()),
    )
    parser.add_argument("--fuzzy-threshold", type=float, default=None)
    parser.add_argument("--primary-threshold", type=float, default=None)
    parser.add_argument("--secondary-threshold", type=float, default=None)
    parser.add_argument("--ambiguity-margin", type=float, default=None)
    parser.add_argument("--min-token-overlap", type=int, default=None)
    parser.add_argument("--method-tag", default="task_family_backfill_v1")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--force-map-all",
        action="store_true",
        help=(
            "Force every Task into a family. Unmatched rows use best fuzzy candidate "
            "when passing force thresholds; otherwise route to fallback family."
        ),
    )
    parser.add_argument(
        "--force-min-score",
        type=float,
        default=0.74,
        help="Minimum combined fuzzy score to accept forced best-candidate mapping.",
    )
    parser.add_argument(
        "--force-min-overlap",
        type=int,
        default=0,
        help="Minimum token overlap for forced best-candidate mapping.",
    )
    parser.add_argument(
        "--force-allow-no-overlap",
        action="store_true",
        help="Allow forced best-candidate mapping when overlap < force-min-overlap.",
    )
    parser.add_argument(
        "--fallback-family-id",
        default="tf_uncategorized",
        help="Family ID used when force-map-all is enabled and no forced candidate passes.",
    )
    parser.add_argument(
        "--fallback-family-label",
        default="Uncategorized / Needs Curation",
    )
    parser.add_argument(
        "--fallback-family-description",
        default=(
            "Tasks routed here by force-map-all fallback because no confident family "
            "candidate passed calibration thresholds."
        ),
    )
    parser.add_argument(
        "--fallback-subfamily-id",
        default="sf_needs_curation",
    )
    parser.add_argument(
        "--fallback-subfamily-label",
        default="Needs Curation",
    )
    parser.add_argument(
        "--fallback-paradigm-name",
        default="Unspecified / Review",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--prune-method-tag-first",
        action="store_true",
        help="Delete existing BELONGS_TO_FAMILY edges with the same method_tag before write",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("tmp/task_family_calibration/task_family_backfill_report.json"),
    )
    parser.add_argument(
        "--exclude-labels-tsv",
        type=Path,
        default=None,
        help=(
            "Optional TSV/CSV path containing labels to exclude from TaskFamily mapping. "
            "Accepted columns: label or normalized."
        ),
    )
    return parser.parse_args()


def _load_excluded_labels(path: Path | None) -> set[str]:
    if path is None:
        return set()
    p = path.expanduser().resolve()
    if not p.exists():
        return set()
    text = p.read_text(encoding="utf-8")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return set()

    # Supports either plain one-label-per-line or CSV/TSV with "label"/"normalized".
    header = lines[0].lower()
    delimiter = "\t" if "\t" in lines[0] else ","
    labels: set[str] = set()
    if "label" in header or "normalized" in header:
        keys = [token.strip().lower() for token in lines[0].split(delimiter)]
        for line in lines[1:]:
            values = [token.strip() for token in line.split(delimiter)]
            row = {k: values[idx] if idx < len(values) else "" for idx, k in enumerate(keys)}
            raw = row.get("label") or row.get("normalized") or ""
            norm = normalize_task_label(raw)
            if norm:
                labels.add(norm)
    else:
        for line in lines:
            norm = normalize_task_label(line)
            if norm:
                labels.add(norm)
    return labels


def _fetch_tasks(
    *,
    driver: Any,
    database: str | None,
    limit: int,
) -> list[dict[str, str]]:
    print("[task-family-backfill] fetching tasks...")
    cypher = """
    MATCH (t:Task)
    RETURN coalesce(t.id, elementId(t)) AS task_id,
           coalesce(t.name, t.label, t.title, t.id, elementId(t)) AS label
    ORDER BY task_id
    """
    if limit > 0:
        cypher += "\nLIMIT $limit"
    params = {"limit": int(limit)}
    with driver.session(database=database or None) as session:
        rows = session.run(cypher, params if limit > 0 else {}).data()
    print("[task-family-backfill] fetched rows from neo4j:", len(rows))
    out: list[dict[str, str]] = []
    for row in rows:
        task_id = str(row.get("task_id") or "").strip()
        label = str(row.get("label") or "").strip()
        if not task_id or not label:
            continue
        out.append({"task_id": task_id, "label": label})
    print("[task-family-backfill] usable tasks after filtering:", len(out))
    return out


def _build_matcher(args: argparse.Namespace) -> TaskFamilyMatcher:
    defaults = _PROFILE_DEFAULTS[args.profile]
    taxonomy_path = args.taxonomy_path.expanduser().resolve()
    alias_path = args.alias_extensions_path.expanduser().resolve()
    matcher = TaskFamilyMatcher(
        taxonomy_path=taxonomy_path,
        alias_extensions_path=alias_path if alias_path.exists() else None,
        fuzzy_threshold=(
            float(args.fuzzy_threshold)
            if args.fuzzy_threshold is not None
            else float(defaults["fuzzy_threshold"])
        ),
        enable_fuzzy=True,
        aggressive_mode=True,
        aggressive_primary_threshold=(
            float(args.primary_threshold)
            if args.primary_threshold is not None
            else float(defaults["aggressive_primary_threshold"])
        ),
        aggressive_secondary_threshold=(
            float(args.secondary_threshold)
            if args.secondary_threshold is not None
            else float(defaults["aggressive_secondary_threshold"])
        ),
        min_token_overlap=(
            int(args.min_token_overlap)
            if args.min_token_overlap is not None
            else int(defaults["min_token_overlap"])
        ),
        ambiguity_margin=(
            float(args.ambiguity_margin)
            if args.ambiguity_margin is not None
            else float(defaults["ambiguity_margin"])
        ),
    )
    if not matcher.available:
        raise RuntimeError(f"TaskFamilyMatcher unavailable for taxonomy: {taxonomy_path}")
    return matcher


def _chunked(rows: list[dict[str, Any]], batch_size: int):
    step = max(1, int(batch_size))
    for idx in range(0, len(rows), step):
        yield rows[idx : idx + step]


def _upsert_edges(
    *,
    driver: Any,
    database: str | None,
    rows: list[dict[str, Any]],
) -> None:
    query = """
    UNWIND $rows AS row
    MATCH (t:Task)
    WHERE coalesce(t.id, elementId(t)) = row.task_id
    MERGE (f:TaskFamily {id: row.family_id})
    ON CREATE SET
      f.label = row.family_label,
      f.description = row.family_description,
      f.created_at = datetime()
    SET
      f.label = coalesce(f.label, row.family_label),
      f.description = coalesce(f.description, row.family_description),
      f.updated_at = datetime()
    MERGE (t)-[r:BELONGS_TO_FAMILY]->(f)
    SET
      r.subfamily_id = row.subfamily_id,
      r.subfamily_label = row.subfamily_label,
      r.paradigm_name = row.paradigm_name,
      r.match_method = row.match_method,
      r.match_score = row.match_score,
      r.match_profile = row.match_profile,
      r.method_tag = row.method_tag,
      r.updated_at = datetime(),
      r.source = 'task_family_matcher_backfill'
    """
    with driver.session(database=database or None) as session:
        session.run(query, {"rows": rows}).consume()


def _delete_method_tag_edges(*, driver: Any, database: str | None, method_tag: str) -> int:
    query = """
    MATCH (:Task)-[r:BELONGS_TO_FAMILY]->(:TaskFamily)
    WHERE r.method_tag = $method_tag
    WITH r LIMIT 50000
    DELETE r
    RETURN count(r) AS deleted
    """
    deleted_total = 0
    with driver.session(database=database or None) as session:
        while True:
            row = session.run(query, {"method_tag": method_tag}).single()
            deleted = int((row or {}).get("deleted") or 0)
            deleted_total += deleted
            if deleted == 0:
                break
    return deleted_total


def _build_row(
    *,
    task_id: str,
    family_id: str,
    family_label: str,
    family_description: str,
    subfamily_id: str,
    subfamily_label: str,
    paradigm_name: str,
    match_method: str,
    match_score: float | None,
    match_profile: str,
    method_tag: str,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "family_id": family_id,
        "family_label": family_label,
        "family_description": family_description,
        "subfamily_id": subfamily_id,
        "subfamily_label": subfamily_label,
        "paradigm_name": paradigm_name,
        "match_method": match_method,
        "match_score": float(match_score) if match_score is not None else None,
        "match_profile": match_profile,
        "method_tag": method_tag,
    }


def _coerce_row_for_unmapped(
    *,
    task_id: str,
    label: str,
    matcher: TaskFamilyMatcher,
    args: argparse.Namespace,
) -> dict[str, Any]:
    normalized = normalize_task_label(label)
    if (
        normalized
        and matcher.enable_fuzzy
        and getattr(matcher, "_fuzzy_choices", None)
    ):
        candidates = matcher._collect_fuzzy_candidates(normalized)  # noqa: SLF001
        if candidates:
            best = candidates[0]
            score_ok = best.combined_score >= float(args.force_min_score)
            overlap_ok = best.overlap_count >= int(args.force_min_overlap)
            if score_ok and (overlap_ok or bool(args.force_allow_no_overlap)):
                record = best.record
                return _build_row(
                    task_id=task_id,
                    family_id=record.family_id,
                    family_label=record.family_label,
                    family_description=record.family_description,
                    subfamily_id=record.subfamily_id,
                    subfamily_label=record.subfamily_label,
                    paradigm_name=record.paradigm_name,
                    match_method="forced_best_candidate",
                    match_score=best.combined_score,
                    match_profile=str(args.profile),
                    method_tag=str(args.method_tag),
                )

    return _build_row(
        task_id=task_id,
        family_id=str(args.fallback_family_id),
        family_label=str(args.fallback_family_label),
        family_description=str(args.fallback_family_description),
        subfamily_id=str(args.fallback_subfamily_id),
        subfamily_label=str(args.fallback_subfamily_label),
        paradigm_name=str(args.fallback_paradigm_name),
        match_method="forced_uncategorized",
        match_score=None,
        match_profile=str(args.profile),
        method_tag=str(args.method_tag),
    )


def main() -> None:
    args = parse_args()
    if not args.neo4j_password:
        raise SystemExit("Missing --neo4j-password (or NEO4J_PASSWORD env)")

    matcher = _build_matcher(args)
    excluded_labels = _load_excluded_labels(args.exclude_labels_tsv)
    driver = GraphDatabase.driver(
        str(args.neo4j_uri),
        auth=(str(args.neo4j_user), str(args.neo4j_password)),
    )
    try:
        tasks = _fetch_tasks(
            driver=driver,
            database=args.neo4j_database,
            limit=max(0, int(args.limit)),
        )

        matched_rows: list[dict[str, Any]] = []
        method_counts: Counter[str] = Counter()
        written_method_counts: Counter[str] = Counter()
        excluded_count = 0
        for index, task in enumerate(tasks, start=1):
            if excluded_labels:
                norm_label = normalize_task_label(task["label"])
                if norm_label and norm_label in excluded_labels:
                    excluded_count += 1
                    continue
            record, method, score = matcher.match(task["label"])
            method_counts[method] += 1
            if record is not None and method in _MAPPED_METHODS:
                row = _build_row(
                    task_id=task["task_id"],
                    family_id=record.family_id,
                    family_label=record.family_label,
                    family_description=record.family_description,
                    subfamily_id=record.subfamily_id,
                    subfamily_label=record.subfamily_label,
                    paradigm_name=record.paradigm_name,
                    match_method=method,
                    match_score=score,
                    match_profile=str(args.profile),
                    method_tag=str(args.method_tag),
                )
                matched_rows.append(row)
                written_method_counts[row["match_method"]] += 1
                continue

            if not args.force_map_all:
                continue
            row = _coerce_row_for_unmapped(
                task_id=task["task_id"],
                label=task["label"],
                matcher=matcher,
                args=args,
            )
            matched_rows.append(row)
            written_method_counts[row["match_method"]] += 1
            if args.force_map_all and index % 2000 == 0:
                print(
                    "[task-family-backfill] force map progress",
                    index,
                    "of",
                    len(tasks),
                    flush=True,
                )

        print(
            "[task-family-backfill] tasks=",
            len(tasks),
            "matched=",
            len(matched_rows),
            "excluded=",
            excluded_count,
            "force_map_all=",
            bool(args.force_map_all),
            "batch_size=",
            max(1, int(args.batch_size)),
            flush=True,
        )

        deleted_before = 0
        if args.prune_method_tag_first and not args.dry_run:
            deleted_before = _delete_method_tag_edges(
                driver=driver,
                database=args.neo4j_database,
                method_tag=str(args.method_tag),
            )

        if not args.dry_run:
            batch_size = max(1, int(args.batch_size))
            total_chunks = (len(matched_rows) + batch_size - 1) // batch_size
            for chunk_index, chunk in enumerate(_chunked(matched_rows, batch_size), start=1):
                print(
                    "[task-family-backfill] writing chunk",
                    chunk_index,
                    "of",
                    total_chunks,
                    "rows",
                    len(chunk),
                    flush=True,
                )
                _upsert_edges(
                    driver=driver,
                    database=args.neo4j_database,
                    rows=chunk,
                )

        report = {
            "generated_at": _utc_now_iso(),
            "dry_run": bool(args.dry_run),
            "profile": str(args.profile),
            "method_tag": str(args.method_tag),
            "task_count": len(tasks),
            "matched_count": len(matched_rows),
            "excluded_count": excluded_count,
            "mapped_ratio": (float(len(matched_rows)) / float(len(tasks))) if tasks else 0.0,
            "method_counts": dict(sorted(method_counts.items())),
            "write_method_counts": dict(sorted(written_method_counts.items())),
            "deleted_existing_edges": deleted_before,
            "force_map_all": bool(args.force_map_all),
            "forced_count": int(
                sum(
                    1
                    for row in matched_rows
                    if str(row.get("match_method", "")).startswith("forced_")
                )
            ),
            "forced_uncategorized_count": int(
                sum(1 for row in matched_rows if row.get("match_method") == "forced_uncategorized")
            ),
            "config": {
                "fuzzy_threshold": matcher.fuzzy_threshold,
                "aggressive_primary_threshold": matcher.aggressive_primary_threshold,
                "aggressive_secondary_threshold": matcher.aggressive_secondary_threshold,
                "ambiguity_margin": matcher.ambiguity_margin,
                "min_token_overlap": matcher.min_token_overlap,
                "force_min_score": float(args.force_min_score),
                "force_min_overlap": int(args.force_min_overlap),
                "force_allow_no_overlap": bool(args.force_allow_no_overlap),
                "taxonomy_path": str(args.taxonomy_path.expanduser().resolve()),
                "alias_extensions_path": str(args.alias_extensions_path.expanduser().resolve()),
                "exclude_labels_tsv": (
                    str(args.exclude_labels_tsv.expanduser().resolve())
                    if args.exclude_labels_tsv is not None
                    else None
                ),
                "exclude_labels_count": len(excluded_labels),
            },
        }
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(report, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        print(
            f"TaskFamily backfill {'dry-run ' if args.dry_run else ''}done: "
            f"{report['matched_count']}/{report['task_count']} matched "
            f"(ratio={report['mapped_ratio']:.4f})"
        )
        print(f"Wrote report: {args.output_json}")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
