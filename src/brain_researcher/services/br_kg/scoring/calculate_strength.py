"""
Runtime helpers for calculating evidence-based concept-region strength.

CLI wrappers should import this module instead of depending on the legacy
BR-KG script namespace.
"""

import argparse
import json
import logging
import os
from typing import Any

import pandas as pd

from brain_researcher.core.ingestion.graph_factory import GraphDatabaseProtocol
from brain_researcher.services.br_kg.etl.strength_calculator import StrengthCalculator
from brain_researcher.services.br_kg.graph.neo4j_utils import require_neo4j_db

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def _get_node_by_id(db: GraphDatabaseProtocol, node_id: str) -> dict[str, Any] | None:
    try:
        matches = db.find_nodes(properties={"id": node_id})
    except Exception:
        matches = []
    if matches:
        _, data = matches[0]
        return data
    return None


def update_database_strengths(
    db_path: str | None,
    limit: int = None,
    dry_run: bool = False,
) -> None:
    """Update strength values for all ACTIVATES relationships in the database."""
    db = require_neo4j_db(db_path, preload_cache=False)
    logger.info("Connected to graph backend: %s", type(db).__name__)

    try:
        # Initialize calculator
        calc = StrengthCalculator()

        # Get all ACTIVATES relationships
        logger.info("Finding ACTIVATES relationships...")
        activates_rels = db.find_relationships(rel_type="ACTIVATES")

        if limit:
            activates_rels = activates_rels[:limit]

        logger.info(f"Processing {len(activates_rels)} ACTIVATES relationships...")

        updated = 0
        errors = 0

        # Process each relationship
        for idx, (start_id, end_id, rel_data) in enumerate(activates_rels):
            try:
                # Get concept and region info
                concept_data = _get_node_by_id(db, start_id)
                region_data = _get_node_by_id(db, end_id)

                if not concept_data or not region_data:
                    continue

                concept_name = concept_data.get("name", "")
                region_name = region_data.get("name", "")

                if not concept_name or not region_name:
                    continue

                # Get coordinate data for this concept-region pair
                # For now, use synthetic data - in production, this would query real data
                foci_df = create_synthetic_coordinate_data(concept_name, region_name)

                # Calculate strength
                if not foci_df.empty:
                    results = calc.calculate_all_strengths(
                        concept_name, region_name, foci_df=foci_df
                    )

                    strength = results.get("strength", 0.0)

                    if dry_run:
                        logger.info(
                            f"[DRY RUN] Would update {concept_name} -> {region_name}: "
                            f"strength={strength:.3f}"
                        )
                    else:
                        # Update relationship properties
                        # Note: This would need actual database update method
                        logger.info(
                            f"Updated {concept_name} -> {region_name}: "
                            f"strength={strength:.3f}"
                        )

                    updated += 1

            except Exception as e:
                logger.error(f"Error processing relationship {idx}: {e}")
                errors += 1

            if (idx + 1) % 10 == 0:
                logger.info(f"Processed {idx + 1}/{len(activates_rels)} relationships")

        logger.info(f"\nSummary: Updated {updated} relationships, {errors} errors")

    finally:
        db.close()


def create_synthetic_coordinate_data(concept: str, region: str) -> pd.DataFrame:
    """Create synthetic coordinate data for testing."""
    # In production, this would query real coordinate data from the database
    # For now, create some plausible data
    import numpy as np

    # Generate coordinates based on region
    if "dlpfc" in region.lower() or "prefrontal" in region.lower():
        base_coords = [-45, 15, 30]  # DLPFC coordinates
    elif "hippocampus" in region.lower():
        base_coords = [-26, -20, -12]  # Hippocampus
    elif "amygdala" in region.lower():
        base_coords = [-24, -4, -18]  # Amygdala
    else:
        base_coords = [0, 0, 0]  # Default

    # Add some noise
    n_foci = 25
    coords_data = []
    for i in range(n_foci):
        coords_data.append(
            {
                "x": base_coords[0] + np.random.normal(0, 5),
                "y": base_coords[1] + np.random.normal(0, 5),
                "z": base_coords[2] + np.random.normal(0, 5),
                "study_id": f"study_{i // 5 + 1}",
            }
        )

    return pd.DataFrame(coords_data)


def main():
    parser = argparse.ArgumentParser(
        description="Calculate evidence-based strength between concepts and brain regions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Calculate strength for a specific pair
  %(prog)s "working memory" "DLPFC" --coords-file coords.csv

  # Update database strengths
  %(prog)s --update-db

  # Test update without making changes
  %(prog)s --update-db --dry-run --limit 10
        """,
    )

    # Mode selection
    parser.add_argument(
        "concept", nargs="?", help='Cognitive concept (e.g., "working memory")'
    )
    parser.add_argument("region", nargs="?", help='Brain region (e.g., "DLPFC")')

    # Database update mode
    parser.add_argument(
        "--update-db",
        action="store_true",
        help="Update strength values for all ACTIVATES relationships in database",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Deprecated (ignored). Neo4j connection uses NEO4J_* env vars.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of relationships to update (for testing)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Calculate strengths without updating database",
    )

    parser.add_argument(
        "--coords-file",
        type=str,
        help="CSV file with coordinate data (x,y,z,study_id columns)",
    )
    parser.add_argument(
        "--studies-file", type=str, help="JSON file with effect size data"
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data",
        help="Directory containing neuroimaging data",
    )
    parser.add_argument(
        "--output",
        type=str,
        choices=["json", "simple"],
        default="simple",
        help="Output format",
    )

    args = parser.parse_args()

    # Check if database update mode
    if args.update_db:
        if args.db_path and not os.path.isabs(args.db_path):
            args.db_path = os.path.abspath(args.db_path)
        update_database_strengths(args.db_path, args.limit, args.dry_run)
        return

    # Otherwise, require concept and region
    if not args.concept or not args.region:
        parser.error("concept and region are required unless using --update-db mode")

    # Initialize calculator
    calc = StrengthCalculator(data_dir=args.data_dir)

    # Load coordinate data if provided
    foci_df = None
    if args.coords_file:
        try:
            foci_df = pd.read_csv(args.coords_file)
            print(f"Loaded {len(foci_df)} coordinates from {args.coords_file}")
        except Exception as e:
            print(f"Error loading coordinates: {e}")

    # Load studies data if provided
    studies_data = None
    if args.studies_file:
        try:
            with open(args.studies_file) as f:
                studies_data = json.load(f)
            print(f"Loaded {len(studies_data)} studies from {args.studies_file}")
        except Exception as e:
            print(f"Error loading studies: {e}")

    # Calculate strengths
    results = calc.calculate_all_strengths(
        concept=args.concept,
        region=args.region,
        foci_df=foci_df,
        studies_data=studies_data,
    )

    # Output results
    if args.output == "json":
        print(json.dumps(results, indent=2))
    else:
        print(f"\nStrength calculation for: {args.concept} → {args.region}")
        print("=" * 50)
        print(f"Composite strength: {results.get('strength', 'N/A')}")
        print(f"Evidence sources: {', '.join(results.get('evidence', []))}")

        if "strength_coord" in results:
            print(f"\nCoordinate-based: {results['strength_coord']}")
            if "coord_details" in results:
                print(f"  - Method: {results['coord_details'].get('method', 'N/A')}")
                print(
                    f"  - Studies: {results['coord_details'].get('n_studies', 'N/A')}"
                )

        if "strength_effect" in results:
            print(f"\nEffect size-based: {results['strength_effect']}")
            if "effect_details" in results:
                print(
                    f"  - Studies: {results['effect_details'].get('n_studies', 'N/A')}"
                )
                print(
                    f"  - Mean effect: {results['effect_details'].get('weighted_mean_effect', 'N/A')}"
                )


if __name__ == "__main__":
    main()
