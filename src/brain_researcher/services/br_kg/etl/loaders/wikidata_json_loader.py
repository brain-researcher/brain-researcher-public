#!/usr/bin/env python3
"""
WikiData JSON File Loader

Loads brain region data from the existing wikidata JSON file into BR-KG.
This loader reads from the cached JSON file instead of fetching from SPARQL.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class WikidataJSONLoader:
    """Load WikiData brain regions from JSON file into BR-KG."""

    def __init__(self, db):
        """
        Initialize the loader.

        Args:
            db: BRKGGraphDB instance
        """
        self.db = db
        self.stats = {
            "brain_regions_created": 0,
            "brain_regions_updated": 0,
            "relationships_created": 0,
            "errors": 0,
        }

    def load_from_json(self, json_path: str) -> dict[str, int]:
        """
        Load brain regions from WikiData JSON file.

        Args:
            json_path: Path to the WikiData JSON file

        Returns:
            Dictionary with loading statistics
        """
        logger.info(f"Loading WikiData brain regions from: {json_path}")

        try:
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)

            brain_regions = data.get("brain_regions", [])
            relationships = data.get("relationships", [])

            logger.info(
                f"Found {len(brain_regions)} brain regions and {len(relationships)} relationships"
            )

            # Create a mapping of QID to node ID
            qid_to_node_id = {}

            # First pass: Create all brain region nodes
            for region in brain_regions:
                node_id = self._create_brain_region(region)
                if node_id:
                    qid_to_node_id[region["qid"]] = node_id

            # Second pass: Create hierarchical relationships
            for region in brain_regions:
                if "part_of_qid" in region and region["part_of_qid"]:
                    self._create_part_of_relationship(
                        region["qid"], region["part_of_qid"], qid_to_node_id
                    )

            logger.info("WikiData loading complete")
            logger.info(f"Statistics: {self.stats}")

            return self.stats

        except Exception as e:
            logger.error(f"Error loading WikiData JSON: {e}")
            self.stats["errors"] += 1
            return self.stats

    def _create_brain_region(self, region_data: dict) -> str | None:
        """
        Create or update a brain region node.

        Args:
            region_data: Dictionary with brain region information

        Returns:
            Node ID if successful, None otherwise
        """
        try:
            # Check if brain region already exists by name
            existing = self.db.find_nodes("BrainRegion", {"name": region_data["name"]})

            properties = {
                "name": region_data["name"],
                "description": region_data.get("description", ""),
                "wikidata_id": region_data["qid"],
                "wikidata_url": region_data.get(
                    "wikidata_url",
                    f"http://www.wikidata.org/entity/{region_data['qid']}",
                ),
                "source": "wikidata",
            }

            if existing:
                # Use existing node ID
                node_id = existing[0][
                    0
                ]  # find_nodes returns list of (node_id, node_data) tuples
                self.stats["brain_regions_updated"] += 1
                logger.debug(f"Found existing brain region: {region_data['name']}")
            else:
                # Create new brain region node
                node_id = self.db.create_node("BrainRegion", properties)
                self.stats["brain_regions_created"] += 1
                logger.debug(f"Created brain region: {region_data['name']}")

            return node_id

        except Exception as e:
            logger.error(
                f"Error creating brain region {region_data.get('name', 'unknown')}: {e}"
            )
            self.stats["errors"] += 1
            return None

    def _create_part_of_relationship(
        self, child_qid: str, parent_qid: str, qid_mapping: dict[str, str]
    ):
        """
        Create PART_OF relationship between brain regions.

        Args:
            child_qid: WikiData ID of the child region
            parent_qid: WikiData ID of the parent region
            qid_mapping: Mapping of WikiData IDs to node IDs
        """
        try:
            if child_qid not in qid_mapping or parent_qid not in qid_mapping:
                logger.debug(
                    f"Skipping relationship {child_qid} -> {parent_qid}: nodes not found"
                )
                return

            child_id = qid_mapping[child_qid]
            parent_id = qid_mapping[parent_qid]

            # Check if relationship already exists
            existing = self.db.find_relationships(
                start_node=child_id, end_node=parent_id, rel_type="PART_OF"
            )

            if not existing:
                self.db.create_relationship(
                    child_id, parent_id, "PART_OF", {"source": "wikidata"}
                )
                self.stats["relationships_created"] += 1
                logger.debug(
                    f"Created PART_OF relationship: {child_qid} -> {parent_qid}"
                )

        except Exception as e:
            logger.error(
                f"Error creating relationship {child_qid} -> {parent_qid}: {e}"
            )
            self.stats["errors"] += 1


def load_wikidata_brain_regions(db, json_path: str) -> dict[str, int]:
    """
    Convenience function to load WikiData brain regions.

    Args:
        db: BRKGGraphDB instance
        json_path: Path to WikiData JSON file

    Returns:
        Loading statistics
    """
    loader = WikidataJSONLoader(db)
    return loader.load_from_json(json_path)


if __name__ == "__main__":
    # Test the loader
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

    from graph.graph_database import BRKGGraphDB

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Test with sample data
    db_path = "data/br-kg/db/test_wikidata.db"
    json_path = "data/br-kg/raw/wikidata_brain_regions_sample_200.json"

    db = BRKGGraphDB(db_path)
    loader = WikidataJSONLoader(db)
    stats = loader.load_from_json(json_path)

    print(f"\nLoading complete. Statistics: {stats}")

    # Verify
    db_stats = db.get_stats()
    print("\nDatabase statistics:")
    print(f"  Total nodes: {db_stats['total_nodes']}")
    print(f"  BrainRegion nodes: {db_stats['node_labels'].get('BrainRegion', 0)}")
    print(
        f"  PART_OF relationships: {db_stats['relationship_types'].get('PART_OF', 0)}"
    )

    db.close()
