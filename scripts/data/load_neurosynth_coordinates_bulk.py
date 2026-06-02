#!/usr/bin/env python3
"""
Bulk Load Remaining NeuroSynth Coordinates

Loads the remaining ~493k NeuroSynth coordinates (out of 507k total)
using bulk insert for fast performance.

Expected: 5-10 minutes for 493k coordinates
"""

import gzip
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from brain_researcher.services.br_kg.graph.graph_database import BRKGGraphDB

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("neurosynth_coordinates_bulk.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


def main():
    """Load remaining NeuroSynth coordinates using bulk insert."""

    logger.info("=" * 80)
    logger.info("BULK LOADING NEUROSYNTH COORDINATES")
    logger.info("=" * 80)

    # Connect to database
    db = BRKGGraphDB(db_path="data/br-kg/db/br_kg_full.db")

    # Check current state
    logger.info(f"Current database: {db.graph.number_of_nodes():,} nodes")

    # Load coordinates file
    coords_file = Path("data/neurosynth_nimare/neurosynth_v7/data-neurosynth_version-7_coordinates.tsv.gz")

    if not coords_file.exists():
        # Try alternative path
        coords_file = Path("data/nimare_data/neurosynth/data-neurosynth_version-7_coordinates.tsv.gz")

    if not coords_file.exists():
        logger.error(f"Coordinates file not found at {coords_file}")
        return 1

    logger.info(f"Loading from: {coords_file}")

    # Read and prepare coordinates for bulk insert
    coordinates_to_insert = []
    total_lines = 0

    logger.info("Reading coordinates file...")

    with gzip.open(coords_file, 'rt') as f:
        # Skip header
        header = f.readline()

        for line in f:
            total_lines += 1
            parts = line.strip().split('\t')

            if len(parts) >= 7:
                study_id, table_id, table_num, peak_id, x, y, z = parts[:7]

                # Create coordinate properties
                properties = {
                    'study_id': study_id,
                    'table_id': table_id,
                    'peak_id': peak_id,
                    'x': float(x),
                    'y': float(y),
                    'z': float(z),
                    'space': 'MNI',
                    'source': 'neurosynth_v7'
                }

                # Add to bulk insert list
                coordinates_to_insert.append(('Coordinate', properties))

                # Log progress every 50k
                if len(coordinates_to_insert) % 50000 == 0:
                    logger.info(f"  Prepared {len(coordinates_to_insert):,} coordinates...")

    logger.info(f"Total coordinates in file: {total_lines:,}")
    logger.info(f"Prepared {len(coordinates_to_insert):,} coordinates for insertion")

    # Bulk insert coordinates
    logger.info("Starting bulk insert (this may take 5-10 minutes)...")

    try:
        node_ids = db.bulk_create_nodes(coordinates_to_insert, batch_size=10000)
        logger.info(f"✓ Successfully inserted {len(node_ids):,} coordinates")

    except Exception as e:
        logger.error(f"✗ Failed to insert coordinates: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 1

    # Final statistics
    logger.info(f"\nFinal database: {db.graph.number_of_nodes():,} nodes")

    logger.info("=" * 80)
    logger.info("BULK LOADING COMPLETE!")
    logger.info("=" * 80)

    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
