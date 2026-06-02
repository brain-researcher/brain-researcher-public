"""Create HAS_TASK/USES_TASK relationships between Dataset and Task nodes.

This module backs ``scripts/br-kg/create_dataset_task_relationships.py`` and
keeps the graph/task-linking orchestration importable from the canonical
package tree.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from brain_researcher.core.datasets.catalog import load_catalog
from brain_researcher.services.br_kg.etl.dataset_task_linker import (
    TaskIndex,
    TaskMappingConfig,
    build_task_index,
    is_blacklisted_task,
    load_task_mapping_config,
    load_task_synonyms,
    load_taxonomy_aliases,
    match_task,
    normalize_task,
)
from brain_researcher.services.br_kg.graph.neo4j_utils import require_neo4j_db

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_CATALOGS",
    "DEFAULT_TASK_MAPPING",
    "DEFAULT_TASK_SYNONYMS",
    "DEFAULT_TAXONOMY_ALIASES",
    "EdgeRecord",
    "METHOD_CONF",
    "SOURCE_CONF",
    "_build_edge_props",
    "_chunked",
    "_group_edges",
    "_infer_bids_source",
    "_infer_dataset_task_source",
    "_infer_source_key",
    "_is_path_under_any_prefix",
    "_iter_bids_task_labels",
    "_iter_dataset_task_props",
    "_iter_fmri_datasets_missing_task_edges",
    "_iter_task_rows",
    "_load_dataset_ids",
    "_load_task_index",
    "_method_to_prov_method",
    "_parse_rel_types",
    "_write_edges",
    "main",
]

DEFAULT_CATALOGS = [
    Path("configs/datasets/catalog.v1.jsonl"),
    Path("configs/datasets/catalog_manual.jsonl"),
    Path("configs/datasets/catalog_openneuro.jsonl"),
]
DEFAULT_TASK_SYNONYMS = Path("configs/legacy/mappings/task_synonyms.yaml")
DEFAULT_TASK_MAPPING = Path("configs/legacy/task_mapping.yaml")
DEFAULT_TAXONOMY_ALIASES = Path("configs/taxonomy/exports/task_families_master.yaml")
METHOD_CONF = {
    "alias_match": 0.9,
    "name_match": 0.85,
    "fuzzy_match": 0.65,
    "keyword_rule": 0.55,
}
SOURCE_CONF = {
    "manual": 0.95,
    "openneuro": 0.85,
    "catalog": 0.80,
    "graph": 0.80,
    "bids": 0.85,
}

_TASK_LABEL_RE = re.compile(r"task-([^_\\.]+)", flags=re.IGNORECASE)


@dataclass
class EdgeRecord:
    dataset_id: str
    task_id: str
    rel_type: str
    props: dict


def _iter_task_rows(db, *, include_all_tasks: bool) -> list[dict[str, object]]:
    if include_all_tasks:
        cypher = """
        MATCH (t:Task)
        OPTIONAL MATCH (t)-[r:MEASURES]->()
        WITH t, count(r) AS measures_count
        RETURN t.id AS id, t.name AS name, t.alias AS alias, t.aliases AS aliases, measures_count
        """
    else:
        cypher = """
        MATCH (t:Task)-[r:MEASURES]->()
        WITH t, count(r) AS measures_count
        RETURN t.id AS id, t.name AS name, t.alias AS alias, t.aliases AS aliases, measures_count
        """
    return [dict(row) for row in db._run(cypher)]


def _load_task_index(
    db, config: TaskMappingConfig, *, include_all_tasks: bool
) -> TaskIndex:
    rows = _iter_task_rows(db, include_all_tasks=include_all_tasks)
    if include_all_tasks:
        logger.info("Loaded %s Task nodes (all)", len(rows))
    else:
        logger.info("Loaded %s Task nodes with MEASURES edges", len(rows))
    return build_task_index(rows, config)


def _load_dataset_ids(db) -> set[str]:
    cypher = """
    MATCH (d:Dataset)
    RETURN d.id AS id
    """
    return {row["id"] for row in db._run(cypher) if row.get("id")}


def _iter_dataset_task_props(db) -> list[dict[str, object]]:
    cypher = """
    MATCH (d:Dataset)
    WHERE d.tasks IS NOT NULL OR d.task IS NOT NULL OR d.task_name IS NOT NULL
    RETURN d.id AS id,
           d.tasks AS tasks,
           d.task AS task,
           d.task_name AS task_name,
           d.created_from AS created_from
    """
    return [dict(row) for row in db._run(cypher)]


def _iter_fmri_datasets_missing_task_edges(db) -> list[dict[str, object]]:
    cypher = """
    MATCH (d:Dataset)
    WHERE (
        any(m IN coalesce(d.modalities, []) WHERE
            toLower(m) CONTAINS 'fmri' OR toLower(m) = 'bold' OR toLower(m) = 'func'
        )
        OR any(a IN coalesce(d.acquisitions, []) WHERE toLower(a) = 'bold')
    )
    AND NOT (d)-[:HAS_TASK|USES_TASK]->()
    RETURN d.id AS id, d.created_from AS created_from
    """
    return [dict(row) for row in db._run(cypher)]


def _infer_source_key(catalog_path: Path, source_repo: Optional[str]) -> str:
    repo = (source_repo or "").lower()
    name = catalog_path.name.lower()
    if "manual" in name:
        return "manual"
    if "openneuro" in name or "openneuro" in repo:
        return "openneuro"
    return "catalog"


def _method_to_prov_method(method: str) -> str:
    if method == "fuzzy_match":
        return "fuzzy_match"
    return "string_match"


def _infer_dataset_task_source(
    *, dataset_id: str, created_from: str | None
) -> tuple[str, str]:
    created_from_lower = (created_from or "").lower()
    dataset_id_lower = dataset_id.lower()
    if "openneuro" in dataset_id_lower or "openneuro" in created_from_lower:
        return "openneuro", "openneuro_metadata"
    return "graph", "dataset_node_tasks"


def _infer_bids_source(*, dataset_id: str, created_from: str | None) -> tuple[str, str]:
    created_from_lower = (created_from or "").lower()
    dataset_id_lower = dataset_id.lower()
    if "openneuro" in dataset_id_lower or "openneuro" in created_from_lower:
        return "openneuro", "openneuro_bids_scan"
    return "bids", "bids_scan"


def _build_edge_props(
    *,
    raw_task: str,
    normalized_task: str,
    match: str,
    match_score: float,
    source_key: str,
    source_detail: str,
    needs_measures: bool,
    prov_base_conf_override: float | None = None,
    evidence_type: str = "dataset_metadata",
    mapping_version: str = "dataset_task_v1",
) -> dict:
    method_conf = METHOD_CONF.get(match, 0.7)
    source_conf = SOURCE_CONF.get(source_key, 0.7)
    if prov_base_conf_override is not None:
        prov_base_conf = prov_base_conf_override
    else:
        prov_base_conf = method_conf * source_conf
    return {
        "raw_task": raw_task,
        "normalized_task": normalized_task,
        "prov_source": source_detail,
        "prov_method": _method_to_prov_method(match),
        "prov_base_conf": prov_base_conf,
        "match_score": match_score,
        "mapping_method": match,
        "mapping_version": mapping_version,
        "evidence_type": evidence_type,
        "needs_measures": needs_measures,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


def _is_path_under_any_prefix(path: Path, prefixes: list[Path]) -> bool:
    if not prefixes:
        return True
    try:
        resolved = path.resolve()
    except Exception:
        return False
    for prefix in prefixes:
        try:
            resolved.relative_to(prefix.resolve())
            return True
        except Exception:
            continue
    return False


def _iter_bids_task_labels(dataset_root: Path) -> set[str]:
    """Extract BIDS task labels from filenames under a dataset root."""
    labels: set[str] = set()
    if not dataset_root.exists():
        return labels

    skip_dirs = {".git", ".datalad", ".github", "__pycache__", "derivatives"}
    for dirpath, dirnames, filenames in os.walk(dataset_root, topdown=True):
        dirnames[:] = [
            d for d in dirnames if d not in skip_dirs and not d.startswith(".")
        ]
        for name in filenames:
            lower = name.lower()
            if "task-" not in lower:
                continue
            if not (
                lower.endswith(".nii")
                or lower.endswith(".nii.gz")
                or lower.endswith(".json")
                or lower.endswith(".tsv")
            ):
                continue
            match = _TASK_LABEL_RE.search(name)
            if not match:
                continue
            label = match.group(1).strip()
            if label:
                labels.add(label)
    return labels


def _chunked(items: list, batch_size: int) -> Iterable[list]:
    for i in range(0, len(items), batch_size):
        yield items[i : i + batch_size]


def _write_edges(db, edges: list[EdgeRecord], batch_size: int) -> int:
    total = 0
    for rel_type, rel_edges in _group_edges(edges):
        logger.info("Writing %s edges for rel_type=%s", len(rel_edges), rel_type)
        for batch in _chunked(rel_edges, batch_size):
            rows = [
                {
                    "dataset_id": edge.dataset_id,
                    "task_id": edge.task_id,
                    "props": edge.props,
                }
                for edge in batch
            ]
            cypher = f"""
            UNWIND $rows AS row
            MATCH (d:Dataset {{id: row.dataset_id}})
            MATCH (t:Task {{id: row.task_id}})
            MERGE (d)-[r:`{rel_type}`]->(t)
            SET r += row.props
            """
            db._run(cypher, {"rows": rows}).consume()
            total += len(rows)
    return total


def _group_edges(edges: list[EdgeRecord]) -> list[tuple[str, list[EdgeRecord]]]:
    grouped: dict[str, list[EdgeRecord]] = {}
    for edge in edges:
        grouped.setdefault(edge.rel_type, []).append(edge)
    return list(grouped.items())


def _parse_rel_types(raw: str) -> list[str]:
    rels = []
    for chunk in raw.replace(",", " ").split():
        if chunk.strip():
            rels.append(chunk.strip())
    return rels


def main() -> None:
    parser = argparse.ArgumentParser(description="Create Dataset→Task relationships")
    parser.add_argument(
        "--catalog",
        action="append",
        default=None,
        help="Path to dataset catalog JSONL (repeatable)",
    )
    parser.add_argument(
        "--task-synonyms",
        type=Path,
        default=DEFAULT_TASK_SYNONYMS,
        help="Path to task_synonyms.yaml",
    )
    parser.add_argument(
        "--task-mapping",
        type=Path,
        default=DEFAULT_TASK_MAPPING,
        help="Path to task_mapping.yaml",
    )
    parser.add_argument(
        "--ignore-blacklist",
        action="store_true",
        help="Bypass the task_mapping blacklist (allows 'rest' tasks)",
    )
    parser.add_argument(
        "--taxonomy-aliases",
        type=Path,
        default=DEFAULT_TAXONOMY_ALIASES,
        help="Path to task_families_master.yaml (taxonomy aliases)",
    )
    parser.add_argument(
        "--use-taxonomy-aliases",
        action="store_true",
        help="Include taxonomy task family paradigm aliases",
    )
    parser.add_argument(
        "--include-all-tasks",
        action="store_true",
        help="Allow linking to Task nodes without MEASURES (marks needs_measures=true)",
    )
    parser.add_argument(
        "--use-dataset-node-tasks",
        action="store_true",
        help="Use Dataset node task properties (d.tasks/d.task/d.task_name) as an additional task source",
    )
    parser.add_argument(
        "--scan-bids-for-missing-fmri-tasks",
        action="store_true",
        help="For fMRI/BOLD datasets that have no task edges, scan local BIDS files for task labels",
    )
    parser.add_argument(
        "--bids-root-prefix",
        action="append",
        default=[],
        help="Allowlist prefix for BIDS scans (repeatable). If omitted, an allowlist is inferred from the graph's created_from paths.",
    )
    parser.add_argument(
        "--report-include-bids-unmatched",
        action="store_true",
        help="Include BIDS-scan unmatched task labels in --report output (can be very large).",
    )
    parser.add_argument(
        "--rel-types",
        type=str,
        default="HAS_TASK",
        help="Relationship types to create (comma or space separated)",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Limit records per catalog"
    )
    parser.add_argument(
        "--batch-size", type=int, default=500, help="Batch size for writes"
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not write updates")
    parser.add_argument(
        "--disable-fuzzy",
        action="store_true",
        help="Disable fuzzy matching fallback",
    )
    parser.add_argument(
        "--fuzzy-threshold",
        type=float,
        default=None,
        help="Override fuzzy threshold (0-1)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional path to write unmatched task report (TSV)",
    )

    args = parser.parse_args()

    catalogs = [Path(p) for p in (args.catalog or [])]
    if not catalogs:
        catalogs = DEFAULT_CATALOGS

    rel_types = _parse_rel_types(args.rel_types)
    if not rel_types:
        raise SystemExit("No rel-types provided")

    config = load_task_mapping_config(
        args.task_mapping,
        enable_fuzzy=not args.disable_fuzzy,
        ignore_blacklist=args.ignore_blacklist,
    )
    if args.fuzzy_threshold is not None:
        config.fuzzy_threshold = float(args.fuzzy_threshold)

    alias_to_canonical = load_task_synonyms(args.task_synonyms, config)
    logger.info("Loaded %s task synonyms", len(alias_to_canonical))
    if args.use_taxonomy_aliases:
        taxonomy_aliases = load_taxonomy_aliases(args.taxonomy_aliases, config)
        for alias, canonical in taxonomy_aliases.items():
            alias_to_canonical.setdefault(alias, canonical)
        logger.info(
            "Loaded %s taxonomy aliases (total alias map=%s)",
            len(taxonomy_aliases),
            len(alias_to_canonical),
        )

    db = require_neo4j_db(preload_cache=False)
    try:
        task_index = _load_task_index(
            db, config, include_all_tasks=args.include_all_tasks
        )
        dataset_ids = _load_dataset_ids(db)
        logger.info("Loaded %s Dataset ids from graph", len(dataset_ids))

        edge_map: dict[tuple[str, str, str], EdgeRecord] = {}
        unmatched_counts: Counter[str] = Counter()
        unmatched_examples: dict[str, str] = {}

        for catalog_path in catalogs:
            if not catalog_path.exists():
                logger.warning("Catalog not found: %s", catalog_path)
                continue
            records = load_catalog(catalog_path)
            if args.limit:
                records = records[: args.limit]
            logger.info("Processing %s records from %s", len(records), catalog_path)

            for rec in records:
                if rec.dataset_id not in dataset_ids:
                    continue
                if not rec.tasks:
                    continue

                source_key = _infer_source_key(catalog_path, rec.source_repo)
                source_detail = source_key
                if source_key == "catalog":
                    source_detail = catalog_path.name
                elif source_key == "openneuro":
                    source_detail = "openneuro"
                elif source_key == "manual":
                    source_detail = "manual_catalog"

                for raw_task in rec.tasks:
                    match = match_task(raw_task, alias_to_canonical, task_index, config)
                    if match is None:
                        normalized = normalize_task(raw_task, config)
                        if normalized and not is_blacklisted_task(
                            raw_task=raw_task, normalized=normalized, config=config
                        ):
                            unmatched_counts[normalized] += 1
                            unmatched_examples.setdefault(normalized, raw_task)
                        continue

                    for rel_type in rel_types:
                        edge_key = (rec.dataset_id, match.task_id, rel_type)
                        props = _build_edge_props(
                            raw_task=raw_task,
                            normalized_task=match.normalized,
                            match=match.method,
                            match_score=match.score,
                            source_key=source_key,
                            source_detail=source_detail,
                            needs_measures=match.measures_count == 0,
                            prov_base_conf_override=match.confidence_hint,
                        )
                        existing = edge_map.get(edge_key)
                        if existing:
                            if props.get("prov_base_conf", 0.0) <= existing.props.get(
                                "prov_base_conf", 0.0
                            ):
                                continue
                        edge_map[edge_key] = EdgeRecord(
                            dataset_id=rec.dataset_id,
                            task_id=match.task_id,
                            rel_type=rel_type,
                            props=props,
                        )

        if args.use_dataset_node_tasks:
            dataset_rows = _iter_dataset_task_props(db)
            logger.info(
                "Processing %s Dataset nodes with task properties", len(dataset_rows)
            )
            for row in dataset_rows:
                dataset_id = row.get("id")
                if not dataset_id or dataset_id not in dataset_ids:
                    continue

                raw_tasks: list[str] = []
                tasks_prop = row.get("tasks")
                if isinstance(tasks_prop, list):
                    raw_tasks.extend(
                        [t for t in tasks_prop if isinstance(t, str) and t.strip()]
                    )
                elif isinstance(tasks_prop, str) and tasks_prop.strip():
                    raw_tasks.append(tasks_prop)

                for field in ("task", "task_name"):
                    val = row.get(field)
                    if isinstance(val, str) and val.strip():
                        raw_tasks.append(val)

                if not raw_tasks:
                    continue

                created_from = row.get("created_from")
                source_key, source_detail = _infer_dataset_task_source(
                    dataset_id=dataset_id,
                    created_from=(
                        created_from if isinstance(created_from, str) else None
                    ),
                )

                for raw_task in sorted(set(raw_tasks)):
                    match = match_task(raw_task, alias_to_canonical, task_index, config)
                    if match is None:
                        normalized = normalize_task(raw_task, config)
                        if normalized and not is_blacklisted_task(
                            raw_task=raw_task, normalized=normalized, config=config
                        ):
                            unmatched_counts[normalized] += 1
                            unmatched_examples.setdefault(normalized, raw_task)
                        continue

                    for rel_type in rel_types:
                        edge_key = (dataset_id, match.task_id, rel_type)
                        props = _build_edge_props(
                            raw_task=raw_task,
                            normalized_task=match.normalized,
                            match=match.method,
                            match_score=match.score,
                            source_key=source_key,
                            source_detail=source_detail,
                            needs_measures=match.measures_count == 0,
                            prov_base_conf_override=match.confidence_hint,
                        )
                        existing = edge_map.get(edge_key)
                        if existing:
                            if props.get("prov_base_conf", 0.0) <= existing.props.get(
                                "prov_base_conf", 0.0
                            ):
                                continue
                        edge_map[edge_key] = EdgeRecord(
                            dataset_id=dataset_id,
                            task_id=match.task_id,
                            rel_type=rel_type,
                            props=props,
                        )

        if args.scan_bids_for_missing_fmri_tasks:
            prefixes = [Path(p) for p in (args.bids_root_prefix or []) if p]

            targets = _iter_fmri_datasets_missing_task_edges(db)
            if not prefixes:
                prefix_counts: Counter[Path] = Counter()
                for row in targets:
                    created_from = row.get("created_from")
                    if not isinstance(created_from, str) or not created_from:
                        continue
                    dataset_desc = Path(created_from)
                    dataset_root = dataset_desc.parent
                    if dataset_desc.name != "dataset_description.json":
                        continue
                    if "openneuro_metadata" not in created_from:
                        continue
                    prefix_counts[dataset_root.parent] += 1
                if prefix_counts:
                    prefixes = [prefix_counts.most_common(1)[0][0]]

            logger.info(
                "Scanning BIDS for %s fMRI/BOLD datasets with no task edges (prefix allowlist=%s)",
                len(targets),
                [str(p) for p in prefixes] if prefixes else "any",
            )
            scanned = 0
            matched_datasets = 0
            datasets_with_edges = 0
            edges_added = 0
            for row in targets:
                dataset_id = row.get("id")
                created_from = row.get("created_from")
                if (
                    not dataset_id
                    or not isinstance(created_from, str)
                    or not created_from
                ):
                    continue
                dataset_desc = Path(created_from)
                dataset_root = dataset_desc.parent
                if not dataset_desc.name.endswith("dataset_description.json"):
                    continue
                if not _is_path_under_any_prefix(dataset_root, prefixes):
                    continue
                if not dataset_root.exists():
                    continue

                scanned += 1
                source_key, source_detail = _infer_bids_source(
                    dataset_id=dataset_id, created_from=created_from
                )
                task_labels = _iter_bids_task_labels(dataset_root)
                any_matched = False
                any_edge_added = False
                for raw_task in sorted(task_labels):
                    match = match_task(raw_task, alias_to_canonical, task_index, config)
                    if match is None:
                        if args.report_include_bids_unmatched:
                            normalized = normalize_task(raw_task, config)
                            if normalized and not is_blacklisted_task(
                                raw_task=raw_task, normalized=normalized, config=config
                            ):
                                unmatched_counts[normalized] += 1
                                unmatched_examples.setdefault(normalized, raw_task)
                        continue

                    any_matched = True
                    for rel_type in rel_types:
                        edge_key = (dataset_id, match.task_id, rel_type)
                        props = _build_edge_props(
                            raw_task=raw_task,
                            normalized_task=match.normalized,
                            match=match.method,
                            match_score=match.score,
                            source_key=source_key,
                            source_detail=source_detail,
                            needs_measures=match.measures_count == 0,
                            prov_base_conf_override=match.confidence_hint,
                            evidence_type="bids_metadata",
                            mapping_version="dataset_task_bids_v1",
                        )
                        existing = edge_map.get(edge_key)
                        if existing:
                            if props.get("prov_base_conf", 0.0) <= existing.props.get(
                                "prov_base_conf", 0.0
                            ):
                                continue
                        edge_map[edge_key] = EdgeRecord(
                            dataset_id=dataset_id,
                            task_id=match.task_id,
                            rel_type=rel_type,
                            props=props,
                        )
                        edges_added += 1
                        any_edge_added = True

                if any_matched:
                    matched_datasets += 1
                if any_edge_added:
                    datasets_with_edges += 1

            logger.info(
                "BIDS scan: scanned=%s matched_datasets=%s datasets_with_edges=%s edges_added=%s",
                scanned,
                matched_datasets,
                datasets_with_edges,
                edges_added,
            )

        edges = list(edge_map.values())
        logger.info(
            "Prepared %s edges (%s rel types). Unmatched tasks: %s",
            len(edges),
            ",".join(rel_types),
            sum(unmatched_counts.values()),
        )

        if args.report:
            report_lines = ["normalized_task\tcount\texample_raw_task"]
            for task, count in unmatched_counts.most_common():
                example = unmatched_examples.get(task, "")
                report_lines.append(f"{task}\t{count}\t{example}")
            args.report.write_text("\n".join(report_lines), encoding="utf-8")
            logger.info("Wrote unmatched report to %s", args.report)

        if args.dry_run:
            logger.info("Dry run enabled - skipping writes")
            return

        written = _write_edges(db, edges, args.batch_size)
        logger.info("Wrote %s relationships", written)
    finally:
        db.close()


if __name__ == "__main__":
    main()
