#!/usr/bin/env python3
"""
Merge GLM FitLins data into the main BR-KG database.
This creates a unified database with all data sources.
"""

import argparse
import logging
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def merge_databases(output_db_path=None):
    """Merge GLM FitLins data into the main database.

    Args:
        output_db_path: Optional custom output database path.
                       If not provided, uses default location.
    """
    logger.error(
        "SQLite merge is deprecated. Use Neo4j admin tooling or run the Neo4j "
        "ingestion pipeline directly."
    )
    return False

    # Database paths
    default_main_db = "data/br-kg/db/br_kg_full.db"
    main_db_path = output_db_path or default_main_db

    logger.info("Starting database merge process...")
    logger.info(f"Output database: {main_db_path}")

    # If using custom output path and default exists, copy it first
    if (
        output_db_path
        and output_db_path != default_main_db
        and Path(default_main_db).exists()
    ):
        logger.info(f"Copying base database from {default_main_db} to {output_db_path}")
        os.makedirs(Path(output_db_path).parent, exist_ok=True)
        shutil.copy2(default_main_db, output_db_path)

    # Check if database exists
    if not Path(main_db_path).exists():
        logger.error(f"Database not found: {main_db_path}")
        return False

    # Load GLM FitLins data into the database
    logger.info("Loading GLM FitLins data into database...")
    try:
        # Use the existing loader but point it to the target database
        # Construct paths relative to this script
        script_dir = Path(__file__).parent
        manifest_path = (
            script_dir.parent / "etl" / "glmfitlins_ingest" / "dataset_manifest.csv"
        )
        contrasts_path = (
            script_dir.parent / "etl" / "glmfitlins_ingest" / "contrasts_raw.csv"
        )

        load_to_br_kg(
            manifest_path=manifest_path,
            contrasts_path=contrasts_path,
            db_path=Path(main_db_path),
        )
        success = True

        if not success:
            logger.error("Failed to load GLM FitLins data")
            return False

    except Exception as e:
        logger.error(f"Error loading GLM FitLins data: {e}")
        return False

    # Verify the merge
    logger.info("Verifying merged database...")
    try:
        db = BRKGGraphDB(main_db_path)
        stats = db.get_stats()

        logger.info("Merged database statistics:")
        logger.info(f"  Output path: {main_db_path}")
        logger.info(f"  Total nodes: {stats['total_nodes']}")
        logger.info(f"  Total relationships: {stats['total_relationships']}")
        logger.info(f"  Node types: {stats['node_labels']}")
        logger.info(f"  Relationship types: {stats['relationship_types']}")

        db.close()

    except Exception as e:
        logger.error(f"Error verifying database: {e}")
        return False

    logger.info("Database merge completed successfully!")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Merge GLM FitLins data into BR-KG database"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        help="Output database path (default: data/br-kg/db/br_kg_full.db)",
    )

    args = parser.parse_args()

    success = merge_databases(output_db_path=args.output)
    sys.exit(0 if success else 1)
