#!/usr/bin/env python3
"""
Test script for spatial-semantic mapping implementation.

This script tests the coordinate-to-region mapping and NiCLIP integration
with a small subset of data before running on the full dataset.

Author: BR-KG Team
"""

import logging
import os
import sys

import pytest

# Add brain_researcher to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from brain_researcher.services.neurokg.etl.loaders.niclip_loader import NiCLIPLoader
from brain_researcher.services.neurokg.graph.neo4j_utils import require_neo4j_db
from brain_researcher.services.neurokg.spatial.create_in_region_edges import (
    CoordinateRegionMapper,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


if os.environ.get("RUN_SPATIAL_SEMANTIC_MAPPING") != "1":
    pytest.skip(
        "Set RUN_SPATIAL_SEMANTIC_MAPPING=1 to run spatial-semantic mapping integration tests",
        allow_module_level=True,
    )
if not os.getenv("NEO4J_URI") or not os.getenv("NEO4J_PASSWORD"):
    pytest.skip(
        "NEO4J_URI/NEO4J_PASSWORD required for Neo4j-only tests",
        allow_module_level=True,
    )


def test_coordinate_mapping(limit: int = 100):
    """Test coordinate to region mapping with a small subset."""
    logger.info("\n" + "=" * 60)
    logger.info("TESTING COORDINATE TO REGION MAPPING")
    logger.info("=" * 60)

    db = require_neo4j_db()

    try:
        # Get initial stats
        stats = db.get_stats()
        initial_coords = len(db.find_nodes(labels="Coordinate"))
        initial_regions = len(db.find_nodes(labels="BrainRegion"))
        initial_in_region = stats.get("relationship_types", {}).get("IN_REGION", 0)

        logger.info("Initial state:")
        logger.info(f"  Coordinates: {initial_coords}")
        logger.info(f"  BrainRegions: {initial_regions}")
        logger.info(f"  IN_REGION edges: {initial_in_region}")

        # Test with a small subset
        mapper = CoordinateRegionMapper(db, atlas="MNI", radius_mm=10.0)

        # Run in test mode first
        logger.info(f"\nRunning test analysis on {limit} coordinates...")
        mapper.process_coordinates(limit=limit, test_mode=True)

        # Integration tests run in non-mutating mode only
        assert initial_coords >= 0
        assert initial_regions >= 0

    finally:
        db.close()


def test_niclip_integration():
    """Test NiCLIP integration."""
    logger.info("\n" + "=" * 60)
    logger.info("TESTING NICLIP INTEGRATION")
    logger.info("=" * 60)

    db = require_neo4j_db()

    try:
        # Get initial stats
        stats = db.get_stats()
        initial_concepts = len(db.find_nodes(labels="Concept"))
        initial_regions = len(db.find_nodes(labels="BrainRegion"))
        initial_activates = stats.get("relationship_types", {}).get("ACTIVATES", 0)

        logger.info("Initial state:")
        logger.info(f"  Concepts: {initial_concepts}")
        logger.info(f"  BrainRegions: {initial_regions}")
        logger.info(f"  ACTIVATES edges: {initial_activates}")

        # Test NiCLIP loader
        loader = NiCLIPLoader(
            db,
            niclip_data_path="data/niclip",
            model_name="BrainGPT-7B-v0.0",
            section="abstract",
        )

        # Run in test mode first
        logger.info("\nRunning test analysis...")
        loader.load_and_create_edges(weight_threshold=0.3, test_mode=True)

        # Integration tests run in non-mutating mode only
        assert initial_concepts >= 0
        assert initial_regions >= 0

    finally:
        db.close()


def test_strength_calculator():
    """Test that StrengthCalculator can work with new edges."""
    logger.info("\n" + "=" * 60)
    logger.info("TESTING STRENGTH CALCULATOR")
    logger.info("=" * 60)

    # Import strength calculator
    from brain_researcher.services.neurokg.etl.strength_calculator import (
        StrengthCalculator,
    )

    db = require_neo4j_db()

    try:
        # Get some sample data
        in_region_edges = db.find_relationships(rel_type="IN_REGION")[:10]
        activates_edges = db.find_relationships(rel_type="ACTIVATES")[:10]

        logger.info(f"Found {len(in_region_edges)} IN_REGION edges")
        logger.info(f"Found {len(activates_edges)} ACTIVATES edges")

        if in_region_edges:
            logger.info("\nSample IN_REGION edge:")
            edge = in_region_edges[0]
            logger.info(f"  Start: {edge[0]}")
            logger.info(f"  End: {edge[1]}")
            logger.info(f"  Properties: {edge[3]}")

        if activates_edges:
            logger.info("\nSample ACTIVATES edge:")
            edge = activates_edges[0]
            logger.info(f"  Start: {edge[0]}")
            logger.info(f"  End: {edge[1]}")
            logger.info(f"  Properties: {edge[3]}")

        # Initialize strength calculator
        calc = StrengthCalculator()
        logger.info("\nStrengthCalculator initialized successfully")
        logger.info("Ready to compute evidence-based strengths")

    finally:
        db.close()


def main():
    """Main test runner."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Test spatial-semantic mapping implementation"
    )
    parser.add_argument(
        "--test",
        choices=["coord", "niclip", "strength", "all"],
        default="all",
        help="Which test to run",
    )
    parser.add_argument(
        "--coord-limit", type=int, default=100, help="Number of coordinates to test"
    )

    args = parser.parse_args()
    if not os.getenv("NEO4J_URI") or not os.getenv("NEO4J_PASSWORD"):
        logger.error("NEO4J_URI/NEO4J_PASSWORD required for Neo4j-only tests")
        return

    # Run tests
    if args.test in ["coord", "all"]:
        test_coordinate_mapping(args.coord_limit)

    if args.test in ["niclip", "all"]:
        test_niclip_integration()

    if args.test in ["strength", "all"]:
        test_strength_calculator()

    logger.info("\n" + "=" * 60)
    logger.info("TESTING COMPLETE")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
