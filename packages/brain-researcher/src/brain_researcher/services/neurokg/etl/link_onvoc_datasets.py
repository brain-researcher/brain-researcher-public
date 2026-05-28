#!/usr/bin/env python3
"""
Link Dataset nodes to ONVOC classes using the crosswalk.

Usage:
  python -m brain_researcher.services.neurokg.etl.link_onvoc_datasets \
    --neo4j-uri bolt://localhost:7687 --neo4j-user neo4j --neo4j-password password
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import List, Optional

import yaml

from brain_researcher.config.mapping_resolver import resolve_mapping_path
from brain_researcher.services.neurokg.graph.neo4j_graph_database import Neo4jGraphDB
from brain_researcher.services.neurokg.utils.onvoc_linker import OnvocLinker

logger = logging.getLogger(__name__)

DEFAULT_CROSSWALK_PATH = resolve_mapping_path(
    "onvoc_crosswalk",
    fallback=Path(__file__).resolve().parents[1] / "mappings" / "onvoc_crosswalk.yaml",
    must_exist=False,
)


def _shorten(dataset_id: Optional[str]) -> Optional[str]:
    if not dataset_id:
        return None
    # strip leading ds: prefixes to match legacy crosswalk keys
    if dataset_id.startswith("ds:openneuro:"):
        return dataset_id.split(":", 2)[-1]
    if dataset_id.startswith("ds:"):
        return dataset_id.split(":", 1)[-1]
    return dataset_id


def link_datasets(
    db: Neo4jGraphDB,
    linker: OnvocLinker,
) -> dict[str, int]:
    stats = {"datasets_seen": 0, "links_created": 0, "skipped": 0}

    datasets = db.find_nodes(labels="Dataset")
    stats["datasets_seen"] = len(datasets)
    logger.info("Found %d Dataset nodes", len(datasets))

    for node_id, props in datasets:
        names: List[str] = []
        if props.get("name"):
            names.append(str(props["name"]))
        if props.get("alias"):
            names.extend([str(a) for a in props["alias"] if a])
        # Add task labels to the candidate name pool to improve matching via
        # ONVOC task labels (many datasets are task-named rather than
        # dataset-named, e.g., "Stop-signal task").
        if props.get("tasks"):
            names.extend([str(t) for t in props["tasks"] if t])

        ds_ids: List[str] = []
        for cand in [
            props.get("id"),
            props.get("dataset_id"),
            props.get("source_repo_id"),
            _shorten(props.get("id")),
            _shorten(props.get("dataset_id")),
            _shorten(props.get("source_repo_id")),
        ]:
            if cand:
                ds_ids.append(str(cand))

        try:
            created = linker.link_dataset(node_id, names=names, dataset_ids=ds_ids)
            stats["links_created"] += created
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to link %s: %s", node_id, exc)
            stats["skipped"] += 1

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Link Dataset nodes to ONVOC classes using crosswalk")
    parser.add_argument("--neo4j-uri", required=True)
    parser.add_argument("--neo4j-user", required=True)
    parser.add_argument("--neo4j-password", required=True)
    parser.add_argument("--neo4j-database", default=None)
    parser.add_argument("--crosswalk", type=Path, default=DEFAULT_CROSSWALK_PATH)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    resolved_crosswalk = resolve_mapping_path(
        "onvoc_crosswalk",
        requested_path=args.crosswalk,
        fallback=DEFAULT_CROSSWALK_PATH,
        must_exist=True,
    )
    if not resolved_crosswalk.exists():
        raise FileNotFoundError(f"Crosswalk not found: {resolved_crosswalk}")

    logger.info("Using crosswalk: %s", resolved_crosswalk)
    try:
        yaml.safe_load(resolved_crosswalk.read_text())
    except Exception as exc:  # pragma: no cover - parse safeguard
        raise ValueError(f"Crosswalk YAML is invalid: {exc}") from exc

    db = Neo4jGraphDB(args.neo4j_uri, args.neo4j_user, args.neo4j_password, database=args.neo4j_database)
    linker = OnvocLinker(db, crosswalk_path=resolved_crosswalk)
    if not linker.available:
        raise RuntimeError("ONVOC classes are not present in the graph; load ONVOC first.")

    stats = link_datasets(db, linker)
    logger.info("Linking done: %s", stats)


if __name__ == "__main__":
    main()
