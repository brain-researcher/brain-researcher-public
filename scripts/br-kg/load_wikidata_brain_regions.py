#!/usr/bin/env python3
"""
Load WikiData brain regions from JSON file into the database.

This script loads the 200 brain regions from the WikiData JSON file
that was previously fetched but not properly loaded into the database.
"""

import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from graph.neo4j_utils import require_neo4j_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)


def load_wikidata_brain_regions(db_path: str | None, json_file: str):
    """Load WikiData brain regions from JSON file."""

    logger.info(f"Loading WikiData brain regions from: {json_file}")

    if not os.path.exists(json_file):
        logger.error(f"JSON file not found: {json_file}")
        return

    # Load JSON data
    with open(json_file) as f:
        data = json.load(f)

    logger.info(f"Loaded data with {len(data.get('brain_regions', []))} brain regions")

    # Open database
    db = require_neo4j_db(db_path, preload_cache=False)

    try:
        # Get current brain region count
        initial_regions = db.find_nodes(labels="BrainRegion")
        logger.info(f"Initial BrainRegion nodes: {len(initial_regions)}")

        # Track statistics
        created_regions = 0
        created_relationships = 0
        skipped_regions = 0

        # Create lookup for existing regions by name
        existing_regions = {}
        for region_id, region_data in initial_regions:
            name = region_data.get("name", "").lower()
            if name:
                existing_regions[name] = region_id

        # Load brain regions
        brain_regions = data.get("brain_regions", [])
        region_id_map = {}  # WikiData ID -> Node ID mapping

        for region in brain_regions:
            wikidata_id = region.get("id", "")
            name = region.get("name", "")

            if not name:
                continue

            # Check if region already exists
            name_lower = name.lower()
            if name_lower in existing_regions:
                region_id_map[wikidata_id] = existing_regions[name_lower]
                skipped_regions += 1
                logger.debug(f"Region already exists: {name}")
                continue

            # Create new BrainRegion node
            properties = {
                "name": name,
                "wikidata_id": wikidata_id,
                "description": region.get("description", ""),
                "synonyms": ", ".join(region.get("synonyms", [])),
                "source": "wikidata",
            }

            # Add coordinates if available
            if "coordinates" in region:
                properties["coordinates"] = str(region["coordinates"])

            node_id = db.create_node("BrainRegion", properties)

            if node_id:
                region_id_map[wikidata_id] = node_id
                existing_regions[name_lower] = node_id
                created_regions += 1
                logger.debug(f"Created BrainRegion: {name}")

        logger.info(
            f"Created {created_regions} new BrainRegion nodes, skipped {skipped_regions} existing"
        )

        # Create relationships from the data
        relationships = data.get("relationships", [])
        logger.info(f"Processing {len(relationships)} relationships")

        for rel in relationships:
            if rel.get("relationship_type") == "PART_OF":
                child_wiki_id = rel.get("child_qid")
                parent_wiki_id = rel.get("parent_qid")

                # Get node IDs
                child_id = region_id_map.get(child_wiki_id)
                parent_id = region_id_map.get(parent_wiki_id)

                if child_id and parent_id:
                    # Check if relationship exists
                    existing = db.find_relationships(
                        start_node=child_id, end_node=parent_id, rel_type="PART_OF"
                    )

                    if not existing:
                        success = db.create_relationship(
                            child_id,
                            parent_id,
                            "PART_OF",
                            {
                                "source": "wikidata",
                                "confidence": rel.get("confidence", 1.0),
                            },
                        )

                        if success:
                            created_relationships += 1
                            logger.debug("Created PART_OF relationship")

        logger.info(f"Created {created_relationships} PART_OF relationships")

        # Create additional hierarchical relationships based on name patterns
        logger.info(
            "Creating additional hierarchical relationships based on name patterns..."
        )

        # Common hierarchical patterns
        hierarchy_patterns = {
            "cortex": ["lobe", "gyrus", "area"],
            "lobe": ["gyrus", "lobule"],
            "gyrus": ["area", "region"],
            "nucleus": ["subnucleus", "division"],
            "ganglia": ["nucleus"],
        }

        additional_rels = 0
        all_regions = db.find_nodes(labels="BrainRegion")

        for parent_id, parent_data in all_regions:
            parent_name = parent_data.get("name", "").lower()

            for parent_pattern, child_patterns in hierarchy_patterns.items():
                if parent_pattern in parent_name:
                    # Find potential children
                    for child_id, child_data in all_regions:
                        if child_id == parent_id:
                            continue

                        child_name = child_data.get("name", "").lower()

                        # Check if child name contains parent name and a child pattern
                        if parent_name in child_name:
                            for child_pattern in child_patterns:
                                if child_pattern in child_name:
                                    # Check if relationship exists
                                    existing = db.find_relationships(
                                        start_node=child_id,
                                        end_node=parent_id,
                                        rel_type="PART_OF",
                                    )

                                    if not existing:
                                        success = db.create_relationship(
                                            child_id,
                                            parent_id,
                                            "PART_OF",
                                            {
                                                "source": "name_pattern",
                                                "confidence": 0.8,
                                            },
                                        )

                                        if success:
                                            additional_rels += 1
                                            logger.debug(
                                                f"Created PART_OF: {child_data['name']} -> {parent_data['name']}"
                                            )
                                    break

        logger.info(
            f"Created {additional_rels} additional PART_OF relationships from name patterns"
        )

        # Final statistics
        final_regions = db.find_nodes(labels="BrainRegion")
        final_stats = db.get_stats()

        logger.info("\n=== Summary ===")
        logger.info(
            f"Total BrainRegion nodes: {len(initial_regions)} -> {len(final_regions)}"
        )
        logger.info(f"New BrainRegion nodes created: {created_regions}")
        logger.info(
            f"PART_OF relationships created: {created_relationships + additional_rels}"
        )
        logger.info(
            f"Total PART_OF relationships: {final_stats.get('relationship_types', {}).get('PART_OF', 0)}"
        )

    finally:
        db.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Load WikiData brain regions from JSON"
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Deprecated (ignored). Neo4j connection uses NEO4J_* env vars.",
    )
    parser.add_argument(
        "--json-file",
        default="data/br-kg/raw/wikidata_brain_regions_sample_200.json",
        help="Path to WikiData JSON file",
    )

    args = parser.parse_args()

    # Get absolute paths
    if not os.path.isabs(args.json_file):
        args.json_file = os.path.abspath(args.json_file)

    load_wikidata_brain_regions(args.db_path, args.json_file)


if __name__ == "__main__":
    main()
