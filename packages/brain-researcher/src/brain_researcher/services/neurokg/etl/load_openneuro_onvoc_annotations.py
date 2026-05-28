#!/usr/bin/env python3
"""Backfill OpenNeuro ONVOC dataset annotations into BR-KG."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from brain_researcher.core.ingestion.loaders.openneuro_onvoc_annotations import (
    DEFAULT_ANNOTATIONS_PATH,
    OpenNeuroOnvocAnnotationApplier,
    OpenNeuroOnvocAnnotationLoader,
)
from brain_researcher.core.ingestion.loaders.openneuro_study_links import (
    link_openneuro_dataset_studies,
)
from brain_researcher.core.ingestion.loaders.publication_study_alignment import (
    link_publication_study_alignments,
)
from brain_researcher.services.neurokg.graph.neo4j_graph_database import Neo4jGraphDB

logger = logging.getLogger(__name__)


def _summarize_rows(rows: list[dict], limit: int = 10) -> str:
    if not rows:
        return "none"
    sample = rows[:limit]
    return json.dumps(sample, indent=2, sort_keys=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load OpenNeuro ONVOC dataset annotations into BR-KG"
    )
    parser.add_argument("--neo4j-uri", required=True)
    parser.add_argument("--neo4j-user", required=True)
    parser.add_argument("--neo4j-password", required=True)
    parser.add_argument("--neo4j-database", default=None)
    parser.add_argument(
        "--annotations",
        type=Path,
        default=DEFAULT_ANNOTATIONS_PATH,
        help="Path to datasets_openneuro_march18th.json",
    )
    parser.add_argument(
        "--onvoc-dir",
        type=Path,
        default=Path("data/ontologies/onvoc"),
        help="Directory containing onvoc_concepts.json",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    loader = OpenNeuroOnvocAnnotationLoader(
        annotations_path=args.annotations,
        onvoc_dir=args.onvoc_dir,
    )
    db = Neo4jGraphDB(
        args.neo4j_uri,
        args.neo4j_user,
        args.neo4j_password,
        database=args.neo4j_database,
    )
    applier = OpenNeuroOnvocAnnotationApplier(db, loader=loader)

    stats = applier.apply()
    logger.info(
        "Applied OpenNeuro ONVOC annotations: "
        "records=%d datasets_upserted=%d datasets_created=%d "
        "positive_links_created=%d exclusion_links_created=%d "
        "legacy_concepts_upserted=%d legacy_publication_links_created=%d",
        stats["records_processed"],
        stats["datasets_upserted"],
        stats["datasets_created"],
        stats["positive_links_created"],
        stats["exclusion_links_created"],
        stats.get("legacy_concepts_upserted", 0),
        stats.get("legacy_publication_links_created", 0),
    )

    study_stats = link_openneuro_dataset_studies(db)
    logger.info("Applied OpenNeuro Dataset->Study linker stats: %s", study_stats)
    alignment_stats = link_publication_study_alignments(db)
    logger.info(
        "Applied Publication->Study alignment linker stats: %s", alignment_stats
    )

    if stats["missing_reference_terms"]:
        logger.warning(
            "Found %d reference ONVOC ids missing from the local ONVOC artifact. Sample:\n%s",
            len(stats["missing_reference_terms"]),
            _summarize_rows(stats["missing_reference_terms"]),
        )
    if stats["label_mismatches"]:
        logger.warning(
            "Found %d ONVOC label mismatches versus local reference. Sample:\n%s",
            len(stats["label_mismatches"]),
            _summarize_rows(stats["label_mismatches"]),
        )
    if stats["missing_graph_terms"]:
        logger.warning(
            "Found %d ONVOC ids absent from the current graph. Sample:\n%s",
            len(stats["missing_graph_terms"]),
            _summarize_rows(stats["missing_graph_terms"]),
        )


if __name__ == "__main__":
    main()
