#!/usr/bin/env python3
"""
Load ALL NeuroVault Collection Metadata

This script loads all ~15,975 NeuroVault collections (metadata only, no images)
into the BR-KG database using pagination.

Features:
- Paginated API fetching to get all collections
- Metadata-only loading (images skipped for performance)
- Progress logging
- Handles API rate limiting gracefully

Expected:
- Collections: ~15,975
- Time: 15-30 minutes
- No images loaded (can be added later if needed)
"""

import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from brain_researcher.services.br_kg.etl.load_all import MasterDataLoader
from brain_researcher.services.br_kg.graph.graph_factory import create_graph_client

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("neurovault_metadata_loading.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


def main():
    """Load all NeuroVault collection metadata."""

    logger.info("=" * 80)
    logger.info("NEUROVAULT METADATA LOADING")
    logger.info("=" * 80)
    logger.info("Target: ALL NeuroVault collections (~15,975)")
    logger.info("Mode: Metadata only (no images)")
    logger.info("=" * 80)

    # Initialize loader (defaults to Neo4j; falls back to SQLite only if allowed)
    loader = MasterDataLoader(
        db_factory=lambda: create_graph_client(db_path="data/br-kg/db/br_kg_full.db"),
        db_path="data/br-kg/db/br_kg_full.db",
    )

    # Load NeuroVault metadata
    logger.info("\n[1/2] Loading ALL NeuroVault collections...")
    logger.info("  This will paginate through the entire NeuroVault API")
    logger.info("  Expected: ~15,975 collections")
    logger.info("  Estimated time: 15-30 minutes")

    config = {
        "paginate_all": True,  # Fetch ALL collections
        "load_images": False,  # Skip images (metadata only)
        "cache_dir": "data/neurovault/cache"
    }

    try:
        stats = loader.load_neurovault(config=config)
        logger.info(f"\n✓ NeuroVault loaded: {stats}")

    except Exception as e:
        logger.error(f"\n✗ Failed to load NeuroVault: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 1

    # Report completion
    logger.info("\n[2/2] Loading complete!")
    logger.info(f"  Collections loaded: {stats.get('collections', 0):,}")
    logger.info(f"  Images loaded: {stats.get('images', 0):,}")

    logger.info("\n" + "=" * 80)
    logger.info("METADATA LOADING COMPLETE!")
    logger.info("=" * 80)

    # Close connections
    loader.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
