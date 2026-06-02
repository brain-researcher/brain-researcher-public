#!/usr/bin/env python3
"""Backfill provenance metadata for MEASURES relationships in Neo4j."""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import Any, Dict

from brain_researcher.services.br_kg.graph.neo4j_graph_database import (
    Neo4jGraphDB,
)


def _get_db() -> Neo4jGraphDB:
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "password")
    database = os.environ.get("NEO4J_DATABASE")
    return Neo4jGraphDB(uri, user, password, database)


def _fetch_stats(db: Neo4jGraphDB) -> Dict[str, Any]:
    query = """
    MATCH ()-[r:MEASURES]->()
    RETURN count(r) AS total,
           sum(CASE WHEN trim(coalesce(r.method, "")) = "" THEN 1 ELSE 0 END) AS missing_method,
           sum(CASE WHEN trim(coalesce(r.source, "")) = "" THEN 1 ELSE 0 END) AS missing_source,
           sum(CASE WHEN r.confidence IS NULL THEN 1 ELSE 0 END) AS missing_confidence
    """
    record = db._run(query).single()  # pylint: disable=protected-access
    return {key: record[key] if record else 0 for key in [
        "total", "missing_method", "missing_source", "missing_confidence"
    ]}

def _backfill(
    db: Neo4jGraphDB,
    default_method: str,
    default_source: str,
    default_conf: float,
    note: str,
    ca_conf: float,
) -> Dict[str, Any]:
    timestamp = datetime.utcnow().isoformat()
    query = """
    MATCH ()-[r:MEASURES]->()
    WITH r,
         CASE WHEN trim(coalesce(r.method, "")) = "" THEN 1 ELSE 0 END AS method_missing,
         CASE WHEN trim(coalesce(r.source, "")) = "" THEN 1 ELSE 0 END AS source_missing,
         CASE WHEN r.confidence IS NULL THEN 1 ELSE 0 END AS confidence_missing
    WHERE method_missing + source_missing + confidence_missing > 0
    SET r.method = CASE WHEN method_missing = 1 THEN $default_method ELSE r.method END,
        r.source = CASE WHEN source_missing = 1 THEN $default_source ELSE r.source END,
        r.confidence = CASE
            WHEN confidence_missing = 1 THEN CASE
                WHEN coalesce(r.source, $default_source) = "cognitive_atlas" THEN $ca_confidence
                ELSE $default_confidence
            END
            ELSE r.confidence
        END,
        r.provenance_backfill_at = $timestamp,
        r.provenance_backfill_notes = $note
    RETURN count(r) AS updated,
           sum(method_missing) AS methods_backfilled,
           sum(source_missing) AS sources_backfilled,
           sum(confidence_missing) AS confidences_backfilled
    """
    params = {
        "default_method": default_method,
        "default_source": default_source,
        "default_confidence": default_conf,
        "ca_confidence": ca_conf,
        "timestamp": timestamp,
        "note": note,
    }
    record = db._run(query, params).single()  # pylint: disable=protected-access
    return dict(record) if record else {
        "updated": 0,
        "methods_backfilled": 0,
        "sources_backfilled": 0,
        "confidences_backfilled": 0,
    }


def _set_ca_confidence(db: Neo4jGraphDB, ca_conf: float, note: str, dry_run: bool) -> Dict[str, Any]:
    base = """
    MATCH ()-[r:MEASURES]->()
    WHERE toLower(coalesce(r.source, "")) = "cognitive_atlas"
    """
    if dry_run:
        result = db._run(base + " RETURN count(r) AS affected").single()  # pylint: disable=protected-access
        return {"affected": result["affected"] if result else 0, "updated": 0}

    params = {
        "ca_confidence": ca_conf,
        "timestamp": datetime.utcnow().isoformat(),
        "note": note,
    }
    update_query = base + """
    SET r.confidence = $ca_confidence,
        r.provenance_backfill_at = $timestamp,
        r.provenance_backfill_notes = $note
    RETURN count(r) AS affected
    """
    result = db._run(update_query, params).single()  # pylint: disable=protected-access
    return {"affected": result["affected"] if result else 0, "updated": result["affected"] if result else 0}


def main() -> None:
    parser = argparse.ArgumentParser(description="Ensure MEASURES edges have provenance metadata.")
    parser.add_argument("--dry-run", action="store_true", help="Only print counts without modifying data")
    parser.add_argument("--default-method", default="legacy_unknown", help="Method value to use when missing")
    parser.add_argument("--default-source", default="legacy_unknown", help="Source value to use when missing")
    parser.add_argument("--default-confidence", type=float, default=0.2, help="Confidence to apply when missing for non-Cognitive Atlas edges")
    parser.add_argument("--cognitive-atlas-confidence", type=float, default=1.0, help="Confidence to enforce on Cognitive Atlas MEASURES edges")
    parser.add_argument(
        "--note",
        default="Backfilled via scripts/br-kg/cleanup_measures_provenance.py",
        help="Annotation stored on updated relationships",
    )
    args = parser.parse_args()

    db = _get_db()
    stats = _fetch_stats(db)
    print("Current MEASURES provenance status:")
    for key, value in stats.items():
        print(f"  {key}: {value}")

    if args.dry_run:
        print("Dry run complete; no updates applied.")
        return

    result = _backfill(
        db,
        args.default_method,
        args.default_source,
        args.default_confidence,
        args.note,
        args.cognitive_atlas_confidence,
    )
    print("Backfill summary:")
    for key, value in result.items():
        print(f"  {key}: {value}")

    ca_result = _set_ca_confidence(
        db,
        args.cognitive_atlas_confidence,
        args.note,
        dry_run=False,
    )
    print("Cognitive Atlas confidence summary:")
    for key, value in ca_result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
