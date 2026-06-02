#!/usr/bin/env python3
"""
Create HAS_COORDINATE relationships between Studies and Coordinates.

This script uses the study_id metadata in Coordinate nodes to create
the missing HAS_COORDINATE relationships.
"""

import logging
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from graph.neo4j_utils import require_neo4j_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)


def create_coordinate_relationships(db_path: str | None, batch_size: int = 1000):
    """Create HAS_COORDINATE relationships from coordinate metadata."""

    logger.info("Creating coordinate relationships using Neo4j backend")
    db = require_neo4j_db(db_path, preload_cache=False)

    try:
        # Get current stats
        stats = db.get_stats()
        initial_has_coord = stats.get("relationship_types", {}).get("HAS_COORDINATE", 0)
        logger.info(f"Initial HAS_COORDINATE relationships: {initial_has_coord}")

        # Get all coordinates with study metadata
        all_coords = db.find_nodes(labels="Coordinate")
        logger.info(f"Found {len(all_coords)} total coordinates")

        # Group coordinates by study_id
        study_coords = defaultdict(list)
        coords_with_study = 0

        for coord_id, coord_data in all_coords:
            study_id = coord_data.get("study_id") or coord_data.get("pmid")
            if study_id:
                study_coords[str(study_id)].append(coord_id)
                coords_with_study += 1

        logger.info(f"Found {coords_with_study} coordinates with study IDs")
        logger.info(f"Unique studies referenced: {len(study_coords)}")

        # Get all Study nodes
        all_studies = db.find_nodes(labels="Study")
        study_map = {}
        for study_node_id, study_data in all_studies:
            pmid = study_data.get("pmid")
            if pmid:
                study_map[str(pmid)] = study_node_id

        logger.info(f"Found {len(study_map)} Study nodes with PMIDs")

        # Create relationships
        created = 0
        missing_studies = set()
        already_exists = 0

        for pmid, coord_ids in study_coords.items():
            study_node_id = study_map.get(pmid)

            if not study_node_id:
                missing_studies.add(pmid)
                continue

            for coord_id in coord_ids:
                # Check if relationship already exists
                existing = db.find_relationships(
                    start_node=study_node_id,
                    end_node=coord_id,
                    rel_type="HAS_COORDINATE",
                )

                if not existing:
                    success = db.create_relationship(
                        study_node_id,
                        coord_id,
                        "HAS_COORDINATE",
                        {"source": "coordinate_metadata"},
                    )

                    if success:
                        created += 1
                        if created % batch_size == 0:
                            logger.info(
                                f"Created {created} HAS_COORDINATE relationships..."
                            )
                else:
                    already_exists += 1

        # Final stats
        final_stats = db.get_stats()
        final_has_coord = final_stats.get("relationship_types", {}).get(
            "HAS_COORDINATE", 0
        )

        logger.info("\n=== Summary ===")
        logger.info(f"Coordinates with study IDs: {coords_with_study}")
        logger.info(f"Studies referenced by coordinates: {len(study_coords)}")
        logger.info(
            f"Studies found in database: {len(study_coords) - len(missing_studies)}"
        )
        logger.info(f"Missing studies: {len(missing_studies)}")
        logger.info(f"Relationships created: {created}")
        logger.info(f"Relationships already existed: {already_exists}")
        logger.info(
            f"Total HAS_COORDINATE relationships: {initial_has_coord} -> {final_has_coord}"
        )

        if missing_studies and len(missing_studies) < 20:
            logger.info(f"Sample missing PMIDs: {list(missing_studies)[:20]}")

    finally:
        db.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Create coordinate relationships")
    parser.add_argument(
        "--db-path",
        default=None,
        help="Deprecated (ignored). Neo4j connection uses NEO4J_* env vars.",
    )
    parser.add_argument(
        "--batch-size", type=int, default=1000, help="Batch size for progress updates"
    )

    args = parser.parse_args()

    create_coordinate_relationships(args.db_path, args.batch_size)


if __name__ == "__main__":
    main()
