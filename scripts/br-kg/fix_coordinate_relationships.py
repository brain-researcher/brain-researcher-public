#!/usr/bin/env python3
"""
Fix coordinate relationships by creating HAS_COORDINATE links between Studies and Coordinates.

NeuroSynth data includes coordinates with study PMIDs, but these relationships
weren't properly created during loading.
"""

import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from graph.neo4j_utils import require_neo4j_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)


def fix_coordinate_relationships(db_path: str | None):
    """Create missing HAS_COORDINATE relationships."""

    logger.info("Fixing coordinate relationships using Neo4j backend")
    db = require_neo4j_db(db_path, preload_cache=False)

    try:
        # Get current stats
        stats = db.get_stats()
        initial_has_coord = stats.get("relationship_types", {}).get("HAS_COORDINATE", 0)
        logger.info(f"Initial HAS_COORDINATE relationships: {initial_has_coord}")

        # Load NeuroSynth data to get coordinate-study mappings
        neurosynth_file = Path("data/br-kg/raw/neurosynth_coordinates.json")
        if not neurosynth_file.exists():
            logger.error(f"NeuroSynth data file not found: {neurosynth_file}")
            return

        with open(neurosynth_file) as f:
            neurosynth_data = json.load(f)

        logger.info(
            f"Loaded {len(neurosynth_data.get('coordinates', []))} coordinates from NeuroSynth"
        )

        # Get all coordinates and their associated study PMIDs
        coord_to_pmid = {}
        for coord in neurosynth_data.get("coordinates", []):
            coord_id = f"coord_{coord['x']}_{coord['y']}_{coord['z']}_{coord.get('space', 'MNI')}"
            pmid = coord.get("pmid") or coord.get("study_id")
            if pmid:
                coord_to_pmid[coord_id] = str(pmid)

        logger.info(f"Found {len(coord_to_pmid)} coordinate-PMID mappings")

        # Create relationships
        created = 0
        missing_studies = set()

        for coord_id, pmid in coord_to_pmid.items():
            # Check if both nodes exist
            coord_nodes = db.find_nodes(
                labels="Coordinate", properties={"id": coord_id}
            )
            if not coord_nodes:
                continue

            study_nodes = db.find_nodes(labels="Study", properties={"pmid": pmid})
            if not study_nodes:
                missing_studies.add(pmid)
                continue

            # Check if relationship already exists
            coord_node_id = coord_nodes[0][0]
            study_node_id = study_nodes[0][0]

            existing_rels = db.find_relationships(
                start_node=study_node_id,
                end_node=coord_node_id,
                rel_type="HAS_COORDINATE",
            )

            if not existing_rels:
                # Create the relationship
                db.create_relationship(
                    study_node_id,
                    "HAS_COORDINATE",
                    coord_node_id,
                    {"source": "neurosynth"},
                )
                created += 1

                if created % 100 == 0:
                    logger.info(f"Created {created} HAS_COORDINATE relationships...")

        # Also check if coordinates have metadata with PMIDs
        logger.info("Checking coordinate metadata for additional PMIDs...")

        all_coords = db.find_nodes(labels="Coordinate")
        logger.info(f"Found {len(all_coords)} total coordinates")

        metadata_created = 0
        for coord_id, coord_data in all_coords[:1000]:  # Sample first 1000
            pmid = coord_data.get("pmid") or coord_data.get("study_id")
            if pmid:
                # Find study
                study_nodes = db.find_nodes(
                    labels="Study", properties={"pmid": str(pmid)}
                )
                if study_nodes:
                    study_node_id = study_nodes[0][0]

                    # Check if relationship exists
                    existing_rels = db.find_relationships(
                        start_node=study_node_id,
                        end_node=coord_id,
                        rel_type="HAS_COORDINATE",
                    )

                    if not existing_rels:
                        db.create_relationship(
                            study_node_id,
                            "HAS_COORDINATE",
                            coord_id,
                            {"source": "metadata"},
                        )
                        metadata_created += 1

        logger.info(
            f"Created {metadata_created} additional relationships from metadata"
        )

        # Final stats
        final_stats = db.get_stats()
        final_has_coord = final_stats.get("relationship_types", {}).get(
            "HAS_COORDINATE", 0
        )

        logger.info("\n=== Summary ===")
        logger.info(f"Created {created} relationships from NeuroSynth data")
        logger.info(
            f"Created {metadata_created} relationships from coordinate metadata"
        )
        logger.info(
            f"Total HAS_COORDINATE relationships: {initial_has_coord} -> {final_has_coord}"
        )
        logger.info(f"Missing studies (not in database): {len(missing_studies)}")

    finally:
        db.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Fix coordinate relationships")
    parser.add_argument(
        "--db-path",
        default=None,
        help="Deprecated (ignored). Neo4j connection uses NEO4J_* env vars.",
    )

    args = parser.parse_args()

    fix_coordinate_relationships(args.db_path)


if __name__ == "__main__":
    main()
