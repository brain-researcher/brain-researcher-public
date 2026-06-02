#!/usr/bin/env python3
"""
Integrate Study-Concept Relationships into BR-KG

This script creates STUDIES and MENTIONS_CONCEPT relationships between:
1. NeuroSynth studies and concepts (already done in coordinate integration)
2. PubMed papers and concepts based on text analysis
3. Any other study sources and concepts

This completes the study-concept integration for BR-KG.
"""

import argparse
import logging
import os
import sys
from collections import defaultdict

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_researcher.services.br_kg.etl.loaders.enhanced_neurosynth_loader import EnhancedNeurosynthLoader
from brain_researcher.services.br_kg.etl.loaders.neurosynth_relationship_loader import NeurosynthRelationshipLoader
from brain_researcher.services.br_kg.etl.loaders.pubmed_relationship_loader import PubMedRelationshipLoader
from graph.neo4j_utils import require_neo4j_db

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def integrate_all_study_concept_relationships(
    db_path: str | None,
    pubmed_limit: int | None = None,
    neurosynth_limit: int | None = None,
    dry_run: bool = False,
):
    """
    Integrate all study-concept relationships.

    Args:
        db_path: Deprecated (ignored). Neo4j connection uses NEO4J_* env vars.
        pubmed_limit: Limit PubMed studies to process
        neurosynth_limit: Limit NeuroSynth studies to process
        dry_run: If True, preview changes without creating them
    """
    logger.info("Starting study-concept relationship integration...")

    # Load database
    db = require_neo4j_db(db_path, preload_cache=False)
    initial_stats = db.get_stats()
    logger.info(f"Initial database state: {initial_stats}")

    total_stats = {
        "STUDIES_created": 0,
        "MENTIONS_CONCEPT_created": 0,
        "CO_AUTHORED_created": 0,
        "errors": 0,
    }

    try:
        # Step 1: Create PubMed relationships
        logger.info("\n=== Creating PubMed study-concept relationships ===")

        # Check if we have PubMed studies
        pubmed_studies = db.find_nodes("Study", {"source": "pubmed"})
        logger.info(f"Found {len(pubmed_studies)} PubMed studies")

        if pubmed_studies:
            pubmed_loader = PubMedRelationshipLoader(db)

            # Create study-concept relationships
            pubmed_stats = pubmed_loader.create_study_concept_relationships(
                limit=pubmed_limit
            )

            # Create co-authorship relationships
            pubmed_loader.create_author_relationships()

            # Aggregate stats
            for key, value in pubmed_loader.stats.items():
                if key in total_stats:
                    total_stats[key] += value

            logger.info(f"PubMed relationships created: {pubmed_stats}")

        # Step 2: Check NeuroSynth relationships (may already exist)
        logger.info("\n=== Checking NeuroSynth study-concept relationships ===")

        # Check existing NeuroSynth relationships
        ns_studies_rels = db.find_relationships(rel_type="STUDIES")
        ns_mentions_rels = db.find_relationships(rel_type="MENTIONS_CONCEPT")

        ns_with_source = 0
        for start, end, data in ns_studies_rels + ns_mentions_rels:
            if (
                data.get("source") == "text_matching"
                or data.get("created_by") == "neurosynth_relationship_loader"
            ):
                ns_with_source += 1

        logger.info(f"Existing NeuroSynth relationships: {ns_with_source}")

        # If not enough NeuroSynth relationships, create them
        if ns_with_source < 100:  # Arbitrary threshold
            logger.info("Creating additional NeuroSynth relationships...")

            ns_loader = EnhancedNeurosynthLoader()
            ns_rel_loader = NeurosynthRelationshipLoader(db)

            ns_stats = ns_rel_loader.load_relationships(
                ns_loader, limit=neurosynth_limit
            )

            logger.info(f"NeuroSynth relationships created: {ns_stats}")

        # Step 3: Create relationships for other study sources
        logger.info("\n=== Checking for other study sources ===")

        # Find studies from other sources
        all_studies = db.find_nodes("Study")
        other_sources = set()

        for study_id, study_data in all_studies:
            source = study_data.get("source", "unknown")
            if source not in ["pubmed", "neurosynth"]:
                other_sources.add(source)

        if other_sources:
            logger.info(f"Found studies from other sources: {other_sources}")
            # Could implement specific loaders for these sources

        # Get final statistics
        final_stats = db.get_stats()

        # Print summary report
        logger.info("\n" + "=" * 60)
        logger.info("STUDY-CONCEPT INTEGRATION SUMMARY")
        logger.info("=" * 60)

        logger.info("\nRelationships Created:")
        for key, value in total_stats.items():
            if value > 0:
                logger.info(f"  {key}: {value}")

        logger.info("\nDatabase Growth:")
        logger.info(
            f"  Nodes: {initial_stats['total_nodes']} -> {final_stats['total_nodes']}"
        )
        logger.info(
            f"  Relationships: {initial_stats['total_relationships']} -> {final_stats['total_relationships']}"
        )

        logger.info("\nRelationship Types:")
        for rel_type in ["STUDIES", "MENTIONS_CONCEPT", "CO_AUTHORED"]:
            initial_count = initial_stats.get("relationship_types", {}).get(rel_type, 0)
            final_count = final_stats.get("relationship_types", {}).get(rel_type, 0)
            if final_count > initial_count:
                logger.info(
                    f"  {rel_type}: {initial_count} -> {final_count} (+{final_count - initial_count})"
                )

        if dry_run:
            logger.info("\n[DRY RUN] No changes were made to the database")

    except Exception as e:
        logger.error(f"Error during integration: {e}")
        raise
    finally:
        db.close()


def analyze_study_coverage(db_path: str | None):
    """
    Analyze which studies have concept relationships.

    Args:
        db_path: Deprecated (ignored). Neo4j connection uses NEO4J_* env vars.
    """
    logger.info("Analyzing study-concept coverage...")

    db = require_neo4j_db(db_path, preload_cache=False)

    try:
        # Get all studies
        all_studies = db.find_nodes("Study")
        logger.info(f"Total studies: {len(all_studies)}")

        # Count studies by source
        studies_by_source = defaultdict(int)
        studies_with_concepts = defaultdict(int)

        for study_id, study_data in all_studies:
            source = study_data.get("source", "unknown")
            studies_by_source[source] += 1

            # Check if study has concept relationships
            outgoing = db.find_relationships(start_node=study_id)
            has_concepts = False

            for start, end, data in outgoing:
                if data.get("type") in ["STUDIES", "MENTIONS_CONCEPT"]:
                    has_concepts = True
                    break

            if has_concepts:
                studies_with_concepts[source] += 1

        # Print coverage report
        logger.info("\nStudy Coverage Report:")
        logger.info("-" * 40)

        for source in sorted(studies_by_source.keys()):
            total = studies_by_source[source]
            with_concepts = studies_with_concepts[source]
            percentage = (with_concepts / total * 100) if total > 0 else 0

            logger.info(f"{source}:")
            logger.info(f"  Total studies: {total}")
            logger.info(f"  With concepts: {with_concepts} ({percentage:.1f}%)")

    finally:
        db.close()


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Integrate study-concept relationships into BR-KG"
    )
    parser.add_argument(
        "--database",
        default=None,
        help="Deprecated (ignored). Neo4j connection uses NEO4J_* env vars.",
    )
    parser.add_argument(
        "--pubmed-limit", type=int, help="Limit PubMed studies to process"
    )
    parser.add_argument(
        "--neurosynth-limit", type=int, help="Limit NeuroSynth studies to process"
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Analyze study coverage instead of creating relationships",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without creating them"
    )

    args = parser.parse_args()

    if args.analyze:
        # Just analyze coverage
        analyze_study_coverage(args.database)
    else:
        # Run integration
        integrate_all_study_concept_relationships(
            args.database,
            pubmed_limit=args.pubmed_limit,
            neurosynth_limit=args.neurosynth_limit,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()
