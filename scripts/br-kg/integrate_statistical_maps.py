#!/usr/bin/env python3
"""
Integrate Statistical Maps into BR-KG

This script ensures comprehensive integration of NeuroVault statistical maps by:
1. Creating DERIVED_FROM relationships between StatMaps and Contrasts
2. Creating BELONGS_TO relationships between StatMaps and Collections
3. Linking StatMaps to Studies when possible
4. Providing verification and statistics

This completes the statistical map integration for BR-KG.
"""

import argparse
import json
import logging
import os
import sys
from collections import defaultdict

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_researcher.services.br_kg.etl.loaders.enhanced_neurovault_loader import EnhancedNeuroVaultLoader
from graph.neo4j_utils import require_neo4j_db

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class StatisticalMapIntegrator:
    """Integrates statistical maps with comprehensive relationships."""

    def __init__(self, db):
        """Initialize the integrator with a database connection."""
        self.db = db
        self.stats = defaultdict(int)

    def integrate_all_maps(
        self,
        neurovault_data_path: str | None = None,
        confidence_threshold: float = 0.5,
        dry_run: bool = False,
    ) -> dict[str, any]:
        """
        Integrate all statistical maps with their relationships.

        Args:
            neurovault_data_path: Path to NeuroVault JSON data file
            confidence_threshold: Minimum confidence for creating relationships
            dry_run: If True, preview changes without creating them

        Returns:
            Statistics dictionary
        """
        logger.info("Starting statistical map integration...")

        # Step 1: Enhance existing StatMap->Contrast relationships
        self._enhance_contrast_relationships(confidence_threshold, dry_run)

        # Step 2: Create Collection relationships
        self._create_collection_relationships(dry_run)

        # Step 3: Link maps to studies
        self._link_maps_to_studies(dry_run)

        # Step 4: Create coordinate-based relationships
        self._create_coordinate_relationships(dry_run)

        # Step 5: If new data provided, ingest it
        if neurovault_data_path and os.path.exists(neurovault_data_path):
            self._ingest_new_maps(neurovault_data_path, confidence_threshold, dry_run)

        return dict(self.stats)

    def _enhance_contrast_relationships(
        self, confidence_threshold: float, dry_run: bool
    ):
        """Enhance existing StatMap->Contrast relationships."""
        logger.info("Enhancing StatMap->Contrast relationships...")

        # Find all StatMaps (support multiple label variants, OR logic)
        stat_maps = {}
        for lbl in ["StatMap", "StatisticalMap", "StatsMap"]:
            for mid, mdata in self.db.find_nodes(lbl):
                stat_maps[mid] = mdata
        stat_maps = list(stat_maps.items())
        logger.info(f"Found {len(stat_maps)} statistical maps")

        # Find maps without contrast relationships
        maps_without_contrasts = []

        for map_id, map_data in stat_maps:
            # Check for existing DERIVED_FROM relationships
            existing_rels = self.db.find_relationships(
                start_node=map_id, rel_type="DERIVED_FROM"
            )

            if not existing_rels:
                maps_without_contrasts.append((map_id, map_data))

        logger.info(
            f"Found {len(maps_without_contrasts)} maps without contrast relationships"
        )

        if maps_without_contrasts and not dry_run:
            # Use enhanced loader to match these maps
            loader = EnhancedNeuroVaultLoader(self.db)

            for map_id, map_data in maps_without_contrasts:
                # Try to match to contrast
                contrast_id, method, confidence = loader._match_contrast(map_data)

                if contrast_id and confidence >= confidence_threshold:
                    success = self.db.create_relationship(
                        map_id,
                        contrast_id,
                        "DERIVED_FROM",
                        {
                            "method": f"post_hoc_{method}",
                            "confidence": confidence,
                            "provenance": "Statistical map integration enhancement",
                        },
                    )

                    if success:
                        self.stats["contrast_relationships_added"] += 1
                        logger.debug(f"Linked map {map_id} to contrast {contrast_id}")

    def _create_collection_relationships(self, dry_run: bool):
        """Create BELONGS_TO relationships between StatMaps and Collections."""
        logger.info("Creating StatMap->Collection relationships...")

        # Find all StatMaps with collection_id
        stat_maps = {}
        for lbl in ["StatMap", "StatisticalMap", "StatsMap"]:
            for mid, mdata in self.db.find_nodes(lbl):
                stat_maps[mid] = mdata
        stat_maps = list(stat_maps.items())

        # Group by collection
        collections = defaultdict(list)

        for map_id, map_data in stat_maps:
            collection_id = map_data.get("collection_id")
            if collection_id:
                collections[collection_id].append((map_id, map_data))

        logger.info(f"Found {len(collections)} unique collections")

        # Create Collection nodes and relationships
        for collection_id, maps in collections.items():
            if not collection_id or collection_id == "None":
                continue

            # Get collection info from first map
            first_map = maps[0][1]
            collection_name = first_map.get(
                "collection_name", f"Collection {collection_id}"
            )

            if not dry_run:
                # Create or find Collection node
                collection_node_id = f"collection_{collection_id}"

                # Check if collection exists
                existing_collection = self.db.get_node(collection_node_id)

                if not existing_collection:
                    collection_node_id = self.db.create_node(
                        "Collection",
                        {
                            "id": collection_id,
                            "name": collection_name,
                            "source": "neurovault",
                            "map_count": len(maps),
                        },
                        node_id=collection_node_id,
                    )
                    self.stats["collections_created"] += 1

                # Create BELONGS_TO relationships
                for map_id, map_data in maps:
                    # Check if relationship exists
                    existing_rel = self.db.find_relationships(
                        start_node=map_id,
                        end_node=collection_node_id,
                        rel_type="BELONGS_TO",
                    )

                    if not existing_rel:
                        success = self.db.create_relationship(
                            map_id,
                            collection_node_id,
                            "BELONGS_TO",
                            {"created_by": "statistical_map_integrator"},
                        )

                        if success:
                            self.stats["belongs_to_relationships_created"] += 1

    def _link_maps_to_studies(self, dry_run: bool):
        """Link StatMaps to Studies based on DOI or other identifiers."""
        logger.info("Linking StatMaps to Studies...")

        # Find all StatMaps with DOI
        stat_maps = {}
        for lbl in ["StatMap", "StatisticalMap", "StatsMap"]:
            for mid, mdata in self.db.find_nodes(lbl):
                stat_maps[mid] = mdata
        stat_maps = list(stat_maps.items())
        maps_with_doi = [
            (m_id, m_data) for m_id, m_data in stat_maps if m_data.get("doi")
        ]

        logger.info(f"Found {len(maps_with_doi)} maps with DOI")

        if not dry_run:
            for map_id, map_data in maps_with_doi:
                doi = map_data.get("doi")

                # Try to find study with matching DOI
                # First check PubMed studies
                studies = self.db.find_nodes("Study")

                for study_id, study_data in studies:
                    # Check if DOI matches (might be in abstract or metadata)
                    study_doi = study_data.get("doi", "")
                    abstract = study_data.get("abstract", "")

                    if doi and (doi == study_doi or doi in abstract):
                        # Create relationship
                        existing_rel = self.db.find_relationships(
                            start_node=map_id, end_node=study_id, rel_type="FROM_STUDY"
                        )

                        if not existing_rel:
                            success = self.db.create_relationship(
                                map_id,
                                study_id,
                                "FROM_STUDY",
                                {
                                    "match_type": "doi",
                                    "doi": doi,
                                    "created_by": "statistical_map_integrator",
                                },
                            )

                            if success:
                                self.stats["study_relationships_created"] += 1
                                logger.debug(f"Linked map {map_id} to study {study_id}")
                        break

    def _create_coordinate_relationships(self, dry_run: bool):
        """Create relationships between StatMaps and Coordinates/BrainRegions."""
        logger.info("Creating StatMap coordinate relationships...")

        # This would require analyzing the actual map data (NIfTI files)
        # For now, we'll skip this as it requires additional processing
        logger.info("Skipping coordinate relationships (requires NIfTI processing)")

    def _ingest_new_maps(
        self, data_path: str, confidence_threshold: float, dry_run: bool
    ):
        """Ingest new NeuroVault maps from file."""
        logger.info(f"Ingesting new maps from {data_path}...")

        if dry_run:
            logger.info("[DRY RUN] Would ingest new maps")
            return

        # Load data
        with open(data_path) as f:
            data = json.load(f)

        # Handle both formats
        if isinstance(data, dict):
            maps = data.get("statistical_maps", [])
        else:
            maps = data

        # Use enhanced loader
        loader = EnhancedNeuroVaultLoader(self.db)
        stats = loader.ingest_maps(maps, confidence_threshold)

        # Merge stats
        self.stats["new_maps_ingested"] = stats.get("maps_processed", 0)
        self.stats["new_contrasts_matched"] = stats.get("contrasts_matched", 0)


def analyze_statistical_map_coverage(db_path: str | None):
    """
    Analyze statistical map integration coverage.

    Args:
        db_path: Deprecated (ignored). Neo4j connection uses NEO4J_* env vars.
    """
    logger.info("Analyzing statistical map coverage...")

    db = require_neo4j_db(db_path, preload_cache=False)

    try:
        # Get all StatMaps
        stat_maps = db.find_nodes("StatMap")
        total_maps = len(stat_maps)
        logger.info(f"\nTotal statistical maps: {total_maps}")

        # Analyze relationships
        maps_with_contrasts = 0
        maps_with_collections = 0
        maps_with_studies = 0

        relationship_methods = defaultdict(int)

        for map_id, map_data in stat_maps:
            # Check DERIVED_FROM (to Contrasts)
            derived_rels = db.find_relationships(
                start_node=map_id, rel_type="DERIVED_FROM"
            )
            if derived_rels:
                maps_with_contrasts += 1
                # Track methods
                for _, _, rel_data in derived_rels:
                    method = rel_data.get("method", "unknown")
                    relationship_methods[method] += 1

            # Check BELONGS_TO (to Collections)
            belongs_rels = db.find_relationships(
                start_node=map_id, rel_type="BELONGS_TO"
            )
            if belongs_rels:
                maps_with_collections += 1

            # Check FROM_STUDY
            study_rels = db.find_relationships(start_node=map_id, rel_type="FROM_STUDY")
            if study_rels:
                maps_with_studies += 1

        # Print coverage report
        logger.info("\nStatistical Map Coverage Report:")
        logger.info("-" * 50)

        if total_maps > 0:
            logger.info(
                f"Maps linked to Contrasts: {maps_with_contrasts} ({maps_with_contrasts/total_maps*100:.1f}%)"
            )
            logger.info(
                f"Maps in Collections: {maps_with_collections} ({maps_with_collections/total_maps*100:.1f}%)"
            )
            logger.info(
                f"Maps linked to Studies: {maps_with_studies} ({maps_with_studies/total_maps*100:.1f}%)"
            )

            logger.info("\nContrast matching methods:")
            for method, count in sorted(
                relationship_methods.items(), key=lambda x: x[1], reverse=True
            ):
                logger.info(f"  {method}: {count}")

        # Get Collection statistics
        collections = db.find_nodes("Collection")
        logger.info(f"\nTotal Collections: {len(collections)}")

    finally:
        db.close()


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Integrate statistical maps into BR-KG"
    )
    parser.add_argument(
        "--database",
        default=None,
        help="Deprecated (ignored). Neo4j connection uses NEO4J_* env vars.",
    )
    parser.add_argument(
        "--neurovault-data",
        help="Path to NeuroVault JSON data file for ingesting new maps",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.5,
        help="Minimum confidence threshold for relationships (default: 0.5)",
    )
    parser.add_argument(
        "--analyze", action="store_true", help="Analyze coverage instead of integrating"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without creating them"
    )

    args = parser.parse_args()

    db = require_neo4j_db(args.database, preload_cache=False)

    if args.analyze:
        analyze_statistical_map_coverage(args.database)
        db.close()
        return

    try:
        # Get initial stats
        initial_stats = db.get_stats()
        logger.info(f"Initial database state: {initial_stats}")

        # Run integration
        integrator = StatisticalMapIntegrator(db)
        stats = integrator.integrate_all_maps(
            neurovault_data_path=args.neurovault_data,
            confidence_threshold=args.confidence,
            dry_run=args.dry_run,
        )

        # Get final stats
        final_stats = db.get_stats()

        # Print summary
        logger.info("\n" + "=" * 60)
        logger.info("STATISTICAL MAP INTEGRATION SUMMARY")
        logger.info("=" * 60)

        logger.info("\nOperations Performed:")
        for key, value in stats.items():
            if value > 0:
                logger.info(f"  {key}: {value}")

        logger.info("\nDatabase Growth:")
        logger.info(
            f"  Nodes: {initial_stats['total_nodes']} -> {final_stats['total_nodes']}"
        )
        logger.info(
            f"  Relationships: {initial_stats['total_relationships']} -> {final_stats['total_relationships']}"
        )

        if args.dry_run:
            logger.info("\n[DRY RUN] No changes were made to the database")

    finally:
        db.close()


if __name__ == "__main__":
    main()
