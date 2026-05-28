#!/usr/bin/env python3
"""
NeuroSynth Relationship Loader

This module creates the proper relationships between NeuroSynth data:
- Study -> HAS_COORDINATE -> Coordinate
- Study -> STUDIES/MENTIONS_CONCEPT -> Concept
- Coordinate -> LOCATED_IN -> BrainRegion

This enables the create_activation_edges.py script to work properly.
"""

import json
import logging
from collections import defaultdict

import pandas as pd

logger = logging.getLogger(__name__)


class NeurosynthRelationshipLoader:
    """Creates proper relationships for NeuroSynth data in BR-KG."""

    # Brain region definitions for mapping coordinates
    # These are simplified MNI coordinate ranges for major regions
    BRAIN_REGIONS = {
        "dorsolateral prefrontal cortex": {
            "bounds": {"x": (-50, -25), "y": (10, 35), "z": (25, 45)},
            "hemispheres": ["left"],
        },
        "dorsolateral prefrontal cortex right": {
            "bounds": {"x": (25, 50), "y": (10, 35), "z": (25, 45)},
            "hemispheres": ["right"],
        },
        "anterior cingulate cortex": {
            "bounds": {"x": (-10, 10), "y": (0, 40), "z": (15, 40)},
            "hemispheres": ["bilateral"],
        },
        "posterior parietal cortex": {
            "bounds": {"x": (-45, -15), "y": (-70, -45), "z": (35, 60)},
            "hemispheres": ["left"],
        },
        "posterior parietal cortex right": {
            "bounds": {"x": (15, 45), "y": (-70, -45), "z": (35, 60)},
            "hemispheres": ["right"],
        },
        "inferior frontal gyrus": {
            "bounds": {"x": (-55, -35), "y": (5, 30), "z": (0, 25)},
            "hemispheres": ["left"],
        },
        "inferior frontal gyrus right": {
            "bounds": {"x": (35, 55), "y": (5, 30), "z": (0, 25)},
            "hemispheres": ["right"],
        },
        "hippocampus": {
            "bounds": {"x": (-35, -15), "y": (-30, -10), "z": (-20, -5)},
            "hemispheres": ["left"],
        },
        "hippocampus right": {
            "bounds": {"x": (15, 35), "y": (-30, -10), "z": (-20, -5)},
            "hemispheres": ["right"],
        },
        "amygdala": {
            "bounds": {"x": (-30, -15), "y": (-10, 5), "z": (-25, -10)},
            "hemispheres": ["left"],
        },
        "amygdala right": {
            "bounds": {"x": (15, 30), "y": (-10, 5), "z": (-25, -10)},
            "hemispheres": ["right"],
        },
        "primary motor cortex": {
            "bounds": {"x": (-45, -20), "y": (-25, -5), "z": (45, 70)},
            "hemispheres": ["left"],
        },
        "primary motor cortex right": {
            "bounds": {"x": (20, 45), "y": (-25, -5), "z": (45, 70)},
            "hemispheres": ["right"],
        },
        "primary visual cortex": {
            "bounds": {"x": (-25, 25), "y": (-100, -75), "z": (-15, 15)},
            "hemispheres": ["bilateral"],
        },
        "precuneus": {
            "bounds": {"x": (-15, 15), "y": (-70, -45), "z": (35, 60)},
            "hemispheres": ["bilateral"],
        },
        "insula": {
            "bounds": {"x": (-40, -30), "y": (-5, 20), "z": (-10, 15)},
            "hemispheres": ["left"],
        },
        "insula right": {
            "bounds": {"x": (30, 40), "y": (-5, 20), "z": (-10, 15)},
            "hemispheres": ["right"],
        },
    }

    def __init__(self, db):
        """Initialize the loader with a database connection."""
        self.db = db
        self.stats = defaultdict(int)

    def load_relationships(self, neurosynth_loader, limit: int | None = None):
        """
        Load all relationships from NeuroSynth data.

        Args:
            neurosynth_loader: EnhancedNeurosynthLoader instance with loaded data
            limit: Optional limit on number of studies to process

        Returns:
            Dict of statistics
        """
        logger.info("Starting NeuroSynth relationship loading...")

        # Ensure brain regions exist
        self._ensure_brain_regions()

        # Load data if not already loaded
        if (
            not hasattr(neurosynth_loader, "metadata")
            or neurosynth_loader.metadata is None
        ):
            logger.info("Loading NeuroSynth data...")
            neurosynth_loader.load_data()

        # Process studies and create relationships
        self._process_studies(neurosynth_loader, limit)

        # Create coordinate to brain region mappings
        self._map_coordinates_to_regions()

        logger.info("NeuroSynth relationship loading complete!")
        logger.info(f"Statistics: {dict(self.stats)}")

        return dict(self.stats)

    def _ensure_brain_regions(self):
        """Ensure all brain regions exist in the database."""
        logger.info("Ensuring brain regions exist...")

        for region_name, region_info in self.BRAIN_REGIONS.items():
            # Check if region exists
            existing = self.db.find_nodes("BrainRegion", {"name": region_name})

            if not existing:
                # Create the region
                bounds = region_info["bounds"]
                center_x = (bounds["x"][0] + bounds["x"][1]) / 2
                center_y = (bounds["y"][0] + bounds["y"][1]) / 2
                center_z = (bounds["z"][0] + bounds["z"][1]) / 2

                region_id = self.db.create_node(
                    "BrainRegion",
                    {
                        "name": region_name,
                        "coordinates": [center_x, center_y, center_z],
                        "mni_bounds": json.dumps(bounds),
                        "hemisphere": region_info["hemispheres"][0],
                        "source": "neurosynth_mapping",
                    },
                )
                self.stats["brain_regions_created"] += 1
                logger.debug(f"Created brain region: {region_name}")

    def _process_studies(self, neurosynth_loader, limit: int | None = None):
        """Process studies and create relationships."""
        metadata = neurosynth_loader.metadata
        coordinates = neurosynth_loader.coordinates

        if metadata is None or coordinates is None:
            logger.error("No metadata or coordinates available")
            return

        # Group coordinates by study ID
        coords_by_study = defaultdict(list)
        for idx, coord in coordinates.iterrows():
            study_id = str(coord.get("id", idx))
            coords_by_study[study_id].append((idx, coord))

        # Process each study
        studies_to_process = metadata.iloc[:limit] if limit else metadata

        for idx, study in studies_to_process.iterrows():
            study_id = str(study.get("id", idx))

            # Find the Study node
            study_nodes = self.db.find_nodes("Study", {"pmid": study_id})
            if not study_nodes:
                # Try alternative search
                study_nodes = self.db.find_nodes("Study", {"source": "neurosynth"})
                study_nodes = [
                    (nid, data)
                    for nid, data in study_nodes
                    if data.get("pmid") == study_id
                ]

            if not study_nodes:
                logger.debug(f"Study node not found for ID: {study_id}")
                self.stats["studies_not_found"] += 1
                continue

            study_node_id = study_nodes[0][0]

            # Create Study -> Concept relationships
            self._create_study_concept_relationships(study, study_node_id)

            # Create Study -> Coordinate relationships
            if study_id in coords_by_study:
                self._create_study_coordinate_relationships(
                    study_node_id, coords_by_study[study_id]
                )

            self.stats["studies_processed"] += 1

            if self.stats["studies_processed"] % 100 == 0:
                logger.info(f"Processed {self.stats['studies_processed']} studies...")

    def _create_study_concept_relationships(self, study, study_node_id):
        """Create STUDIES/MENTIONS_CONCEPT relationships between study and concepts."""
        # Extract concepts from study title and abstract
        study_text = ""
        if "title" in study and pd.notna(study["title"]):
            study_text += str(study["title"]).lower() + " "
        if "abstract" in study and pd.notna(study["abstract"]):
            study_text += str(study["abstract"]).lower()

        if not study_text:
            return

        # Find all concepts
        all_concepts = self.db.find_nodes("Concept")

        for concept_id, concept_data in all_concepts:
            concept_name = concept_data.get("name", "").lower()

            if not concept_name:
                continue

            # Check if concept appears in study text
            # Simple keyword matching - could be enhanced with NLP
            if concept_name in study_text:
                # Determine relationship type based on title vs abstract
                if "title" in study and concept_name in str(study["title"]).lower():
                    rel_type = "STUDIES"
                    confidence = 0.9
                else:
                    rel_type = "MENTIONS_CONCEPT"
                    confidence = 0.6

                # Create relationship
                success = self.db.create_relationship(
                    study_node_id,
                    concept_id,
                    rel_type,
                    {
                        "confidence": confidence,
                        "source": "text_matching",
                        "created_by": "neurosynth_relationship_loader",
                    },
                )

                if success:
                    self.stats[f"{rel_type}_created"] += 1

    def _create_study_coordinate_relationships(self, study_node_id, coord_list):
        """Create HAS_COORDINATE relationships between study and its coordinates."""
        for coord_idx, coord_data in coord_list:
            # Find the coordinate node
            coord_nodes = self.db.find_nodes(
                "Coordinate",
                {
                    "x": float(coord_data.get("x", 0)),
                    "y": float(coord_data.get("y", 0)),
                    "z": float(coord_data.get("z", 0)),
                    "source": "neurosynth",
                },
            )

            if not coord_nodes:
                logger.debug(f"Coordinate node not found for study {study_node_id}")
                self.stats["coordinates_not_found"] += 1
                continue

            coord_node_id = coord_nodes[0][0]

            # Create HAS_COORDINATE relationship
            success = self.db.create_relationship(
                study_node_id,
                coord_node_id,
                "HAS_COORDINATE",
                {
                    "peak_number": coord_idx,
                    "source": "neurosynth",
                    "created_by": "neurosynth_relationship_loader",
                },
            )

            if success:
                self.stats["HAS_COORDINATE_created"] += 1

    def _map_coordinates_to_regions(self):
        """Map all coordinates to brain regions based on spatial proximity."""
        logger.info("Mapping coordinates to brain regions...")

        # Prefer batch mapping when using Neo4j backend (much faster than per-node loops)
        if self.db.__class__.__name__ == "Neo4jGraphDB":
            self._map_coordinates_to_regions_neo4j_batch()
            return

        # Fallback: in-memory/SQLite path (original behavior)
        coord_nodes = self.db.find_nodes("Coordinate", {"source": "neurosynth"})

        if not coord_nodes:
            logger.warning("No coordinate nodes found")
            return

        logger.info(f"Processing {len(coord_nodes)} coordinates...")

        coords_mapped = 0
        for coord_id, coord_data in coord_nodes:
            x = coord_data.get("x", 0)
            y = coord_data.get("y", 0)
            z = coord_data.get("z", 0)

            # Find which brain region(s) this coordinate falls into
            for region_name, region_info in self.BRAIN_REGIONS.items():
                bounds = region_info["bounds"]

                # Check if coordinate is within bounds
                if (
                    bounds["x"][0] <= x <= bounds["x"][1]
                    and bounds["y"][0] <= y <= bounds["y"][1]
                    and bounds["z"][0] <= z <= bounds["z"][1]
                ):
                    # Find the brain region node
                    region_nodes = self.db.find_nodes(
                        "BrainRegion", {"name": region_name}
                    )

                    if region_nodes:
                        region_id = region_nodes[0][0]

                        # Create LOCATED_IN relationship
                        success = self.db.create_relationship(
                            coord_id,
                            region_id,
                            "LOCATED_IN",
                            {
                                "confidence": 0.8,  # Based on bounding box
                                "method": "spatial_bounds",
                                "created_by": "neurosynth_relationship_loader",
                            },
                        )

                        if success:
                            self.stats["LOCATED_IN_created"] += 1
                            coords_mapped += 1
                            break  # Only map to first matching region

            if coords_mapped % 1000 == 0:
                logger.info(f"Mapped {coords_mapped} coordinates to regions...")

        logger.info(f"Completed mapping {coords_mapped} coordinates to brain regions")

    def _map_coordinates_to_regions_neo4j_batch(self):
        """Batch mapping using Cypher to avoid per-node roundtrips."""
        try:
            from graph.neo4j_graph_database import Neo4jGraphDB  # noqa: WPS433
        except Exception:  # pragma: no cover
            logger.warning("Neo4j backend not available; falling back to slow path")
            return self._map_coordinates_to_regions()

        if not isinstance(self.db, Neo4jGraphDB):
            return self._map_coordinates_to_regions()

        total_mapped = 0
        for region_name, region_info in self.BRAIN_REGIONS.items():
            bounds = region_info["bounds"]
            params = {
                "source": "neurosynth",
                "region": region_name,
                "minx": bounds["x"][0],
                "maxx": bounds["x"][1],
                "miny": bounds["y"][0],
                "maxy": bounds["y"][1],
                "minz": bounds["z"][0],
                "maxz": bounds["z"][1],
                "conf": 0.8,
            }

            cypher = """
            MATCH (c:Coordinate {source:$source})
            WHERE c.x >= $minx AND c.x <= $maxx
              AND c.y >= $miny AND c.y <= $maxy
              AND c.z >= $minz AND c.z <= $maxz
            WITH c
            MATCH (r:BrainRegion {name:$region})
            MERGE (c)-[rel:LOCATED_IN]->(r)
            SET rel.confidence = $conf,
                rel.method = 'spatial_bounds',
                rel.created_by = 'neurosynth_relationship_loader'
            RETURN count(c) AS mapped
            """

            try:
                result = self.db.execute_query(cypher, params)
                mapped = result[0].get("mapped", 0) if result else 0
                total_mapped += mapped
                logger.info(f"{region_name}: mapped {mapped} coordinates")
            except Exception as e:  # pragma: no cover - log and continue
                logger.error(f"Failed mapping region {region_name}: {e}")

        self.stats["LOCATED_IN_created"] += total_mapped
        logger.info(f"Completed batch mapping: {total_mapped} coordinate->region edges")


def integrate_neurosynth_relationships(db_path: str, limit: int | None = None):
    """
    Convenience function to integrate NeuroSynth relationships into existing database.

    Args:
        db_path: Path to BR-KG database
        limit: Optional limit on studies to process
    """
    import os
    import sys

    sys.path.insert(
        0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )

    from brain_researcher.services.neurokg.etl.loaders.enhanced_neurosynth_loader import EnhancedNeurosynthLoader
    from graph.graph_database import NeuroKGGraphDB

    # Setup logging
    logging.basicConfig(level=logging.INFO)

    # Load database
    logger.info(f"Loading database: {db_path}")
    db = NeuroKGGraphDB(db_path)

    # Initialize loaders
    ns_loader = EnhancedNeurosynthLoader()
    rel_loader = NeurosynthRelationshipLoader(db)

    # Load relationships
    stats = rel_loader.load_relationships(ns_loader, limit=limit)

    # Get final database stats
    db_stats = db.get_stats()
    logger.info(f"Final database stats: {db_stats}")

    db.close()

    return stats


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Load NeuroSynth relationships into BR-KG"
    )
    parser.add_argument("db_path", help="Path to BR-KG database")
    parser.add_argument("--limit", type=int, help="Limit number of studies to process")

    args = parser.parse_args()

    stats = integrate_neurosynth_relationships(args.db_path, args.limit)
    print(f"\nCompleted! Statistics: {stats}")
