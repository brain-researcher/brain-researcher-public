#!/usr/bin/env python3
"""Backfill direct Disease->Dataset ABOUT links from mediated evidence paths.

This script is optional when read-time mediated retrieval is enabled, but helps
materialize stable direct edges for downstream services and analytics.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass

from neo4j import GraphDatabase


ONVOC_CONCEPT_LABELS = ["ONVOC", "Concept", "OnvocClass", "OntologyConcept"]
DATASET_LABELS = ["Dataset", "DataResource", "OpenNeuroDataset"]
PAPER_LABELS = ["Publication", "Paper"]
STUDY_LABELS = ["Study", "Experiment"]
TASK_LABELS = ["Task", "TaskSpec", "TaskDef", "TaskAnalysis"]
STATMAP_LABELS = ["StatMap", "StatsMap", "StatisticalMap"]
# Full ONVOC Disorders subtree (medical + neurological + psychiatric).
DISEASE_ROOT_IDS = ["ONVOC_0000003"]


@dataclass(frozen=True)
class BackfillResult:
    concept_id: str
    concept_label: str
    matched: int
    created: int
    updated: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--neo4j-uri", required=True)
    parser.add_argument("--neo4j-user", required=True)
    parser.add_argument("--neo4j-password", required=True)
    parser.add_argument("--neo4j-database", default=None)
    parser.add_argument(
        "--concept-id",
        action="append",
        default=[],
        help="Specific disease concept id (repeatable). If omitted, scans ONVOC disease subtree.",
    )
    parser.add_argument("--source", default="disease_path_backfill")
    parser.add_argument("--method", default="mediated_path_backfill")
    parser.add_argument("--confidence", type=float, default=0.65)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def list_disease_concepts(driver, database: str | None) -> list[tuple[str, str]]:
    cypher = """
    MATCH (root)
    WHERE root.id IN $root_ids
      AND any(lbl IN labels(root) WHERE lbl IN $concept_labels)
      AND (coalesce(root.scheme, '') = 'ONVOC' OR root.id STARTS WITH 'ONVOC_')
    MATCH (c)-[:CLASSIFIED_UNDER*1..8]->(root)
    WHERE c.id IS NOT NULL
      AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
    RETURN DISTINCT c.id AS id, coalesce(c.label, c.name, c.id) AS label
    ORDER BY label
    """
    with driver.session(database=database) as session:
        rows = session.run(
            cypher,
            {
                "root_ids": DISEASE_ROOT_IDS,
                "concept_labels": ONVOC_CONCEPT_LABELS,
            },
        ).data()
    return [(str(row["id"]), str(row["label"])) for row in rows]


def resolve_concept(driver, database: str | None, concept_id: str) -> tuple[str, str]:
    cypher = """
    MATCH (c {id:$concept_id})
    WHERE any(lbl IN labels(c) WHERE lbl IN $concept_labels)
      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
    RETURN c.id AS id, coalesce(c.label, c.name, c.id) AS label
    LIMIT 1
    """
    with driver.session(database=database) as session:
        row = session.run(
            cypher,
            {"concept_id": concept_id, "concept_labels": ONVOC_CONCEPT_LABELS},
        ).single()
    if not row:
        raise RuntimeError(f"Disease concept not found: {concept_id}")
    return str(row["id"]), str(row["label"])


def run_for_concept(
    *,
    driver,
    database: str | None,
    concept_id: str,
    concept_label: str,
    source: str,
    method: str,
    confidence: float,
    dry_run: bool,
) -> BackfillResult:
    common_params = {
        "concept_id": concept_id,
        "concept_labels": ONVOC_CONCEPT_LABELS,
        "dataset_labels": DATASET_LABELS,
        "paper_labels": PAPER_LABELS,
        "study_labels": STUDY_LABELS,
        "task_labels": TASK_LABELS,
        "statmap_labels": STATMAP_LABELS,
        "source": source,
        "method": method,
        "confidence": confidence,
    }

    path_query = """
    MATCH (c {id:$concept_id})
    WHERE any(lbl IN labels(c) WHERE lbl IN $concept_labels)
      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
    CALL {
      WITH c
      OPTIONAL MATCH (c)-[]-(d)
      WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
      RETURN collect(DISTINCT {id: coalesce(d.id, elementId(d)), mode: 'direct'}) AS direct_hits
    }
    CALL {
      WITH c
      OPTIONAL MATCH (c)-[]-(p)
      WHERE any(lbl IN labels(p) WHERE lbl IN $paper_labels)
      OPTIONAL MATCH (p)-[]-(d)
      WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
      WITH p, d WHERE d IS NOT NULL
      RETURN collect(DISTINCT {id: coalesce(d.id, elementId(d)), mode: 'via_paper'}) AS paper_hits
    }
    CALL {
      WITH c
      OPTIONAL MATCH (c)-[]-(s)
      WHERE any(lbl IN labels(s) WHERE lbl IN $study_labels)
      OPTIONAL MATCH (s)-[]-(d)
      WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
      WITH s, d WHERE d IS NOT NULL
      RETURN collect(DISTINCT {id: coalesce(d.id, elementId(d)), mode: 'via_study'}) AS study_hits
    }
    CALL {
      WITH c
      OPTIONAL MATCH (c)-[]-(t)
      WHERE any(lbl IN labels(t) WHERE lbl IN $task_labels)
      OPTIONAL MATCH (d)-[]-(t)
      WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
      WITH t, d WHERE d IS NOT NULL
      RETURN collect(DISTINCT {id: coalesce(d.id, elementId(d)), mode: 'via_task'}) AS task_hits
    }
    CALL {
      WITH c
      OPTIONAL MATCH (c)-[]-(m)
      WHERE any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
      OPTIONAL MATCH (m)-[]-(d)
      WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
      WITH m, d WHERE d IS NOT NULL
      RETURN collect(DISTINCT {id: coalesce(d.id, elementId(d)), mode: 'via_statmap'}) AS map_hits
    }
    WITH c, direct_hits + paper_hits + study_hits + task_hits + map_hits AS all_hits
    UNWIND all_hits AS hit
    WITH c, hit.id AS dataset_id, collect(DISTINCT hit.mode) AS modes
    WHERE dataset_id IS NOT NULL
    RETURN dataset_id, modes
    """

    with driver.session(database=database) as session:
        path_rows = session.run(path_query, common_params).data()

    if dry_run:
        return BackfillResult(
            concept_id=concept_id,
            concept_label=concept_label,
            matched=len(path_rows),
            created=0,
            updated=0,
        )

    created = 0
    updated = 0
    merge_query = """
    MATCH (c {id:$concept_id})
    WHERE any(lbl IN labels(c) WHERE lbl IN $concept_labels)
      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
    MATCH (d)
    WHERE coalesce(d.id, elementId(d)) = $dataset_id
      AND any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
    WITH c, d, $modes AS modes
    OPTIONAL MATCH (d)-[existing:ABOUT]->(c)
    WITH c, d, modes, existing IS NULL AS is_new
    MERGE (d)-[r:ABOUT]->(c)
    ON CREATE SET
      r.source = $source,
      r.method = $method,
      r.confidence = $confidence,
      r.confidence_tier = 'high',
      r.path_support = size(modes),
      r.path_modes = modes,
      r.created_at = timestamp(),
      r.updated_at = timestamp()
    ON MATCH SET
      r.updated_at = timestamp(),
      r.path_support = case
        when coalesce(r.path_support, 0) >= size(modes) then coalesce(r.path_support, 0)
        else size(modes)
      end,
      r.path_modes = case
        when r.path_modes IS NULL then modes
        else r.path_modes + [x IN modes WHERE NOT x IN r.path_modes]
      end,
      r.confidence = case
        when coalesce(r.confidence, 0.0) >= $confidence then coalesce(r.confidence, 0.0)
        else $confidence
      end
    RETURN is_new AS created
    """

    with driver.session(database=database) as session:
        for row in path_rows:
            outcome = session.run(
                merge_query,
                {
                    **common_params,
                    "dataset_id": row["dataset_id"],
                    "modes": list(row.get("modes") or []),
                },
            ).single()
            if outcome and outcome["created"]:
                created += 1
            else:
                updated += 1

    return BackfillResult(
        concept_id=concept_id,
        concept_label=concept_label,
        matched=len(path_rows),
        created=created,
        updated=updated,
    )


def main() -> None:
    args = parse_args()
    if args.confidence < 0 or args.confidence > 1:
        raise ValueError("--confidence must be between 0 and 1")

    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))
    try:
        concepts: list[tuple[str, str]] = []
        if args.concept_id:
            for raw in args.concept_id:
                concepts.append(resolve_concept(driver, args.neo4j_database, raw))
        else:
            concepts = list_disease_concepts(driver, args.neo4j_database)

        results: list[BackfillResult] = []
        for concept_id, concept_label in concepts:
            results.append(
                run_for_concept(
                    driver=driver,
                    database=args.neo4j_database,
                    concept_id=concept_id,
                    concept_label=concept_label,
                    source=args.source,
                    method=args.method,
                    confidence=args.confidence,
                    dry_run=args.dry_run,
                )
            )

        report = {
            "dry_run": args.dry_run,
            "concepts_processed": len(results),
            "totals": {
                "matched": sum(item.matched for item in results),
                "created": sum(item.created for item in results),
                "updated": sum(item.updated for item in results),
            },
            "results": [
                {
                    "concept_id": item.concept_id,
                    "concept_label": item.concept_label,
                    "matched": item.matched,
                    "created": item.created,
                    "updated": item.updated,
                }
                for item in results
            ],
        }
        print(json.dumps(report, indent=2, sort_keys=True))
    finally:
        driver.close()


if __name__ == "__main__":
    main()
