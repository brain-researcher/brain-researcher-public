#!/usr/bin/env python3
"""Backfill IN_ONVOC links for existing entities using configured ONVOC linkers.

This is a graph-mutation script intended for one-off or periodic reconciliation
after config/crosswalk updates.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

from brain_researcher.config.mapping_resolver import resolve_mapping_path
from brain_researcher.services.neurokg.graph.neo4j_graph_database import Neo4jGraphDB
from brain_researcher.services.neurokg.utils.onvoc_linker import OnvocLinker

logger = logging.getLogger(__name__)

DEFAULT_CROSSWALK_PATH = resolve_mapping_path(
    "onvoc_crosswalk",
    fallback=Path("configs/legacy/mappings/onvoc_crosswalk.yaml"),
    must_exist=False,
)

DATASET_LABELS = ["Dataset", "DataResource", "OpenNeuroDataset"]
TASK_LABELS = ["Task", "TaskSpec", "TaskDef", "TaskAnalysis"]
CONTRAST_LABELS = ["Contrast", "ContrastSpec"]
STATMAP_LABELS = ["StatMap", "StatsMap", "StatisticalMap"]
ONVOC_LABELS = ["ONVOC", "OnvocClass", "Concept", "OntologyConcept"]


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _norm_strs(values: list[Any]) -> list[str]:
    out: list[str] = []
    seen = set()
    for raw in values:
        val = str(raw).strip()
        if not val:
            continue
        if val in seen:
            continue
        seen.add(val)
        out.append(val)
    return out


def _shorten_dataset_id(dataset_id: str | None) -> str | None:
    if not dataset_id:
        return None
    if dataset_id.startswith("ds:openneuro:"):
        return dataset_id.split(":", 2)[-1]
    if dataset_id.startswith("ds:"):
        return dataset_id.split(":", 1)[-1]
    return dataset_id


def _collect_nodes(db: Neo4jGraphDB, labels: list[str]) -> list[tuple[str, dict[str, Any]]]:
    merged: dict[str, dict[str, Any]] = {}
    for label in labels:
        for node_id, props in db.find_nodes(labels=label):
            merged[str(node_id)] = props
    return [(node_id, props) for node_id, props in merged.items()]


def _fetch_statmap_hints(db: Neo4jGraphDB, statmap_id: str) -> dict[str, list[str]]:
    query = """
    MATCH (m {id:$id})
    OPTIONAL MATCH (m)--(d)
    WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
    OPTIONAL MATCH (m)--(t)
    WHERE any(lbl IN labels(t) WHERE lbl IN $task_labels)
    OPTIONAL MATCH (t)-[:IN_ONVOC|MAPS_TO]->(ot)
    WHERE any(lbl IN labels(ot) WHERE lbl IN $onvoc_labels)
      AND (coalesce(ot.scheme, '') = 'ONVOC' OR ot.id STARTS WITH 'ONVOC_')
    OPTIONAL MATCH (m)--(c)
    WHERE any(lbl IN labels(c) WHERE lbl IN $contrast_labels)
    OPTIONAL MATCH (c)-[:IN_ONVOC|MAPS_TO]->(oc)
    WHERE any(lbl IN labels(oc) WHERE lbl IN $onvoc_labels)
      AND (coalesce(oc.scheme, '') = 'ONVOC' OR oc.id STARTS WITH 'ONVOC_')
    RETURN collect(DISTINCT d.id) AS dataset_ids,
           collect(DISTINCT ot.id) AS task_onvoc_ids,
           collect(DISTINCT oc.id) AS contrast_onvoc_ids
    """
    try:
        result = db._run(
            query,
            {
                "id": statmap_id,
                "dataset_labels": DATASET_LABELS,
                "task_labels": TASK_LABELS,
                "contrast_labels": CONTRAST_LABELS,
                "onvoc_labels": ONVOC_LABELS,
            },
        )
        record = result.single()
        try:
            result.close()
        except Exception:
            pass
        if not record:
            return {"dataset_ids": [], "task_onvoc_ids": [], "contrast_onvoc_ids": []}
        return {
            "dataset_ids": _norm_strs(_as_list(record.get("dataset_ids"))),
            "task_onvoc_ids": _norm_strs(_as_list(record.get("task_onvoc_ids"))),
            "contrast_onvoc_ids": _norm_strs(_as_list(record.get("contrast_onvoc_ids"))),
        }
    except Exception:  # pragma: no cover - best effort hints
        return {"dataset_ids": [], "task_onvoc_ids": [], "contrast_onvoc_ids": []}


def _backfill_datasets(db: Neo4jGraphDB, linker: OnvocLinker) -> dict[str, int]:
    nodes = _collect_nodes(db, DATASET_LABELS)
    stats = {"nodes_seen": len(nodes), "links_created": 0, "errors": 0}

    for node_id, props in nodes:
        names = _norm_strs(
            [
                props.get("name"),
                props.get("title"),
                props.get("label"),
                props.get("description"),
                *_as_list(props.get("alias")),
                *_as_list(props.get("aliases")),
                *_as_list(props.get("tasks")),
            ]
        )
        dataset_ids = _norm_strs(
            [
                props.get("id"),
                props.get("dataset_id"),
                props.get("source_repo_id"),
                _shorten_dataset_id(props.get("id")),
                _shorten_dataset_id(props.get("dataset_id")),
                _shorten_dataset_id(props.get("source_repo_id")),
            ]
        )
        try:
            stats["links_created"] += int(
                linker.link_dataset(node_id, names=names, dataset_ids=dataset_ids)
            )
        except Exception as exc:  # pragma: no cover - keep run resilient
            logger.warning("dataset backfill failed for %s: %s", node_id, exc)
            stats["errors"] += 1
    return stats


def _backfill_tasks(db: Neo4jGraphDB, linker: OnvocLinker) -> dict[str, int]:
    nodes = _collect_nodes(db, TASK_LABELS)
    stats = {"nodes_seen": len(nodes), "links_created": 0, "errors": 0}

    for node_id, props in nodes:
        names = _norm_strs(
            [
                props.get("name"),
                props.get("title"),
                props.get("label"),
                props.get("description"),
                props.get("task"),
                props.get("bids_task"),
                *_as_list(props.get("alias")),
                *_as_list(props.get("aliases")),
            ]
        )
        canonical_ids = _norm_strs(
            [
                props.get("id"),
                props.get("task_id"),
                props.get("slug"),
                props.get("task_slug"),
                props.get("bids_task"),
            ]
        )
        concept_ids = _norm_strs(
            [
                props.get("cognitive_atlas_id"),
                props.get("construct_id"),
                *_as_list(props.get("construct_ids")),
                *_as_list(props.get("concept_ids")),
                *_as_list(props.get("onvoc_ids")),
            ]
        )
        try:
            stats["links_created"] += int(
                linker.link_task_analysis(
                    node_id,
                    names=names,
                    canonical_ids=canonical_ids,
                    concept_ids=concept_ids,
                )
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("task backfill failed for %s: %s", node_id, exc)
            stats["errors"] += 1
    return stats


def _backfill_contrasts(db: Neo4jGraphDB, linker: OnvocLinker) -> dict[str, int]:
    nodes = _collect_nodes(db, CONTRAST_LABELS)
    stats = {"nodes_seen": len(nodes), "links_created": 0, "errors": 0}

    for node_id, props in nodes:
        names = _norm_strs(
            [
                props.get("name"),
                props.get("title"),
                props.get("label"),
                props.get("description"),
                props.get("contrast"),
                props.get("contrast_name"),
                *_as_list(props.get("aliases")),
            ]
        )
        canonical_ids = _norm_strs(
            [
                props.get("id"),
                props.get("contrast_id"),
                props.get("neurostore_id"),
            ]
        )
        concept_ids = _norm_strs(
            [
                props.get("cognitive_atlas_id"),
                props.get("construct_id"),
                *_as_list(props.get("construct_ids")),
                *_as_list(props.get("concept_ids")),
                *_as_list(props.get("onvoc_ids")),
            ]
        )
        try:
            stats["links_created"] += int(
                linker.link_contrast(
                    node_id,
                    names=names,
                    canonical_ids=canonical_ids,
                    concept_ids=concept_ids,
                )
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("contrast backfill failed for %s: %s", node_id, exc)
            stats["errors"] += 1
    return stats


def _backfill_statmaps(db: Neo4jGraphDB, linker: OnvocLinker) -> dict[str, int]:
    nodes = _collect_nodes(db, STATMAP_LABELS)
    stats = {"nodes_seen": len(nodes), "links_created": 0, "errors": 0}

    for node_id, props in nodes:
        names = _norm_strs(
            [
                props.get("name"),
                props.get("title"),
                props.get("label"),
                props.get("description"),
                props.get("map_id"),
                props.get("contrast"),
                props.get("task"),
            ]
        )
        dataset_ids = _norm_strs(
            [
                props.get("dataset_id"),
                props.get("source_repo_id"),
                props.get("dataset"),
                _shorten_dataset_id(props.get("dataset_id")),
                _shorten_dataset_id(props.get("source_repo_id")),
            ]
        )
        hints = _fetch_statmap_hints(db, node_id)
        if hints["dataset_ids"]:
            dataset_ids = _norm_strs(dataset_ids + hints["dataset_ids"])
        try:
            stats["links_created"] += int(
                linker.link_stats_map(
                    node_id,
                    names=names,
                    contrast_onvoc_ids=hints["contrast_onvoc_ids"],
                    task_onvoc_ids=hints["task_onvoc_ids"],
                    dataset_ids=dataset_ids,
                )
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("statmap backfill failed for %s: %s", node_id, exc)
            stats["errors"] += 1
    return stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill IN_ONVOC links for existing graph entities"
    )
    parser.add_argument("--neo4j-uri", required=True)
    parser.add_argument("--neo4j-user", required=True)
    parser.add_argument("--neo4j-password", required=True)
    parser.add_argument("--neo4j-database", default=None)
    parser.add_argument("--crosswalk", type=Path, default=DEFAULT_CROSSWALK_PATH)
    parser.add_argument(
        "--entity-types",
        default="datasets,tasks,contrasts,statmaps",
        help="Comma-separated list: datasets,tasks,contrasts,statmaps",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    resolved_crosswalk = resolve_mapping_path(
        "onvoc_crosswalk",
        requested_path=args.crosswalk,
        fallback=DEFAULT_CROSSWALK_PATH,
        must_exist=True,
    )
    if not resolved_crosswalk.exists():
        raise FileNotFoundError(f"Crosswalk not found: {resolved_crosswalk}")

    db = Neo4jGraphDB(
        args.neo4j_uri,
        args.neo4j_user,
        args.neo4j_password,
        database=args.neo4j_database,
        preload_cache=False,
    )
    linker = OnvocLinker(db, crosswalk_path=resolved_crosswalk)
    if not linker.available:
        raise RuntimeError(
            "ONVOC classes are not available in graph for linker initialization"
        )

    selected = {
        token.strip().lower()
        for token in str(args.entity_types or "").split(",")
        if token.strip()
    }
    valid = {"datasets", "tasks", "contrasts", "statmaps"}
    unknown = sorted(selected - valid)
    if unknown:
        raise ValueError(f"Unsupported entity types: {', '.join(unknown)}")
    if not selected:
        raise ValueError("No entity types selected")

    overall: dict[str, dict[str, int]] = {}
    if "datasets" in selected:
        overall["datasets"] = _backfill_datasets(db, linker)
    if "tasks" in selected:
        overall["tasks"] = _backfill_tasks(db, linker)
    if "contrasts" in selected:
        overall["contrasts"] = _backfill_contrasts(db, linker)
    if "statmaps" in selected:
        overall["statmaps"] = _backfill_statmaps(db, linker)

    logger.info("Backfill completed: %s", overall)
    print(overall)


if __name__ == "__main__":
    main()
