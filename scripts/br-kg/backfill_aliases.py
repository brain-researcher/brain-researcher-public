#!/usr/bin/env python3
"""
Backfill aliases for Task/Construct/Dataset nodes in Neo4j.

Adds/merges `aliases` based on existing name/label/id fields and legacy `alias`.
"""

from __future__ import annotations

import argparse
import logging
import os
from typing import Any, Iterable

from neo4j import GraphDatabase

logger = logging.getLogger(__name__)


def _normalize_alias(value: str) -> str:
    return " ".join(value.strip().split())


def _iter_aliases(value: Any) -> Iterable[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            items.extend(list(_iter_aliases(item)))
        return items
    if isinstance(value, str):
        v = _normalize_alias(value)
        return [v] if v else []
    return []


def _build_aliases(record: dict[str, Any], fields: list[str]) -> list[str]:
    aliases: set[str] = set()
    # existing aliases/alias
    for key in ("aliases", "alias"):
        if key in record:
            for val in _iter_aliases(record.get(key)):
                aliases.add(val)
                lower = val.lower()
                if lower != val:
                    aliases.add(lower)
    # candidate fields
    for field in fields:
        for val in _iter_aliases(record.get(field)):
            aliases.add(val)
            lower = val.lower()
            if lower != val:
                aliases.add(lower)
    return sorted(a for a in aliases if a)


def _backfill_label(
    session,
    label: str,
    fields: list[str],
    batch_size: int,
) -> int:
    cypher = (
        f"MATCH (n:{label}) "
        "RETURN elementId(n) AS eid, "
        + ", ".join([f"n.{field} AS {field}" for field in (fields + ["aliases", "alias"])])
    )
    updated = 0
    batch: list[dict[str, Any]] = []
    for record in session.run(cypher):
        data = record.data()
        aliases = _build_aliases(data, fields)
        if not aliases:
            continue
        batch.append({"eid": data["eid"], "aliases": aliases})
        if len(batch) >= batch_size:
            session.run(
                "UNWIND $rows AS row "
                "MATCH (n) WHERE elementId(n) = row.eid "
                "SET n.aliases = row.aliases",
                {"rows": batch},
            )
            updated += len(batch)
            batch = []

    if batch:
        session.run(
            "UNWIND $rows AS row "
            "MATCH (n) WHERE elementId(n) = row.eid "
            "SET n.aliases = row.aliases",
            {"rows": batch},
        )
        updated += len(batch)

    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill aliases for KG nodes")
    parser.add_argument("--neo4j-uri", default=os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--neo4j-user", default=os.getenv("NEO4J_USER", "neo4j"))
    parser.add_argument("--neo4j-password", default=os.getenv("NEO4J_PASSWORD", "password"))
    parser.add_argument("--neo4j-database", default=os.getenv("NEO4J_DATABASE"))
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))
    with driver.session(database=args.neo4j_database) as session:
        total = 0
        total += _backfill_label(
            session,
            "Dataset",
            [
                "id",
                "dataset_id",
                "openneuro_id",
                "accession",
                "dataset_uuid",
                "name",
                "title",
                "short_name",
                "source_repo_id",
            ],
            args.batch_size,
        )
        total += _backfill_label(
            session,
            "Task",
            ["id", "name", "task", "label"],
            args.batch_size,
        )
        total += _backfill_label(
            session,
            "TaskDef",
            ["id", "name", "task", "label"],
            args.batch_size,
        )
        total += _backfill_label(
            session,
            "TaskSpec",
            ["id", "name", "task", "label", "task_name"],
            args.batch_size,
        )
        total += _backfill_label(
            session,
            "Construct",
            ["id", "name", "label", "construct_id", "cognitive_atlas_id"],
            args.batch_size,
        )
        total += _backfill_label(
            session,
            "CognitiveConstruct",
            ["id", "name", "label", "construct_id", "cognitive_atlas_id"],
            args.batch_size,
        )
        total += _backfill_label(
            session,
            "Concept",
            ["id", "name", "label", "construct_id", "cognitive_atlas_id"],
            args.batch_size,
        )
        logger.info("Alias backfill complete. Nodes updated: %s", total)

    driver.close()


if __name__ == "__main__":
    main()
