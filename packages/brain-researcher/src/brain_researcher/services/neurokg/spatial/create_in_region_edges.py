"""
Spatial mapping helpers for Coordinate -> BrainRegion relationships.

CLI wrappers should import this module instead of depending on the legacy
BR-KG script namespace.
"""

import argparse
import logging
from datetime import datetime

import nibabel as nib
import numpy as np

from brain_researcher.core.ingestion.graph_factory import GraphDatabaseProtocol
from brain_researcher.core.utils.spatial import (
    find_nearby_rois,
    validate_coordinates,
)
from brain_researcher.services.neurokg.graph.neo4j_utils import require_neo4j_db

# Atlas NIfTI paths (populated by nilearn fetchers)
ATLAS_NIFTI_PATHS: dict[str, str] = {}


def load_atlas_nifti(atlas_name: str) -> tuple[np.ndarray, np.ndarray]:
    """
    Load atlas NIfTI and return data array + inverse affine.

    Returns:
        (data, inv_affine) where data is the label array and inv_affine converts MNI -> voxel
    """
    from nilearn import datasets

    if atlas_name.lower() in ("aal", "aal116"):
        aal = datasets.fetch_atlas_aal()
        img_path = aal.maps
    elif atlas_name.lower() in ("schaefer400", "schaefer"):
        schaefer = datasets.fetch_atlas_schaefer_2018(
            n_rois=400, yeo_networks=7, resolution_mm=1
        )
        img_path = schaefer.maps
    elif atlas_name.lower() in ("yeo17", "yeo"):
        yeo = datasets.fetch_atlas_yeo_2011()
        img_path = yeo.thick_17
    else:
        raise ValueError(f"Unknown atlas for mask mode: {atlas_name}")

    img = nib.load(img_path)
    data = np.asarray(img.dataobj).astype(int)
    inv_affine = np.linalg.inv(img.affine)

    return data, inv_affine


def mni_to_label(
    x: float, y: float, z: float, data: np.ndarray, inv_affine: np.ndarray
) -> int:
    """
    Convert MNI coordinate to atlas label by sampling the label image.

    Args:
        x, y, z: MNI coordinates in mm
        data: Atlas label array
        inv_affine: Inverse affine matrix (MNI mm -> voxel)

    Returns:
        Label index (0 if outside brain or no label)
    """
    # Convert MNI mm to voxel indices
    mni_coord = np.array([x, y, z, 1.0])
    voxel_coord = inv_affine @ mni_coord
    i, j, k = int(round(voxel_coord[0])), int(round(voxel_coord[1])), int(round(voxel_coord[2]))

    # Check bounds
    if 0 <= i < data.shape[0] and 0 <= j < data.shape[1] and 0 <= k < data.shape[2]:
        return int(data[i, j, k])
    return 0

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class CoordinateRegionMapper:
    """Maps coordinate nodes to brain region nodes based on spatial proximity or mask lookup."""

    def __init__(
        self,
        db: GraphDatabaseProtocol,
        atlas: str = "MNI",
        radius_mm: float = 20.0,
        mask_mode: bool = False,
    ):
        """
        Initialize the mapper.

        Args:
            db: BR-KG database instance
            atlas: Atlas to use for mapping (default: MNI)
            radius_mm: Search radius in millimeters (default: 20mm)
            mask_mode: If True, use direct label lookup instead of distance-based matching
        """
        self.db = db
        self.atlas = atlas
        self.radius_mm = radius_mm
        self.mask_mode = mask_mode

        # Statistics tracking
        self.stats = {
            "coordinates_processed": 0,
            "regions_found": 0,
            "edges_created": 0,
            "edges_skipped": 0,
            "invalid_coordinates": 0,
            "no_nearby_regions": 0,
            "mask_lookups": 0,
            "mask_hits": 0,
        }

        # Cache for brain regions
        self.brain_regions = {}
        self._load_brain_regions()

        # Load atlas NIfTI for mask mode
        self.atlas_data = None
        self.atlas_inv_affine = None
        if self.mask_mode:
            self._load_atlas_nifti()

    def _load_atlas_nifti(self) -> None:
        """Load atlas NIfTI image for mask-based mapping."""
        logger.info(f"Loading atlas NIfTI for mask mode: {self.atlas}")
        try:
            self.atlas_data, self.atlas_inv_affine = load_atlas_nifti(self.atlas)
            logger.info(f"Atlas loaded: shape={self.atlas_data.shape}, unique labels={len(np.unique(self.atlas_data)) - 1}")
        except Exception as e:
            logger.error(f"Failed to load atlas NIfTI: {e}")
            raise

    def _load_brain_regions(self) -> None:
        """Load all BrainRegion nodes from the database."""
        logger.info("Loading BrainRegion nodes from database...")

        brain_region_nodes = self.db.find_nodes(labels="BrainRegion")

        for node_id, properties in brain_region_nodes:
            # Get region name - try multiple property names
            region_name = (
                properties.get("name")
                or properties.get("label")
                or properties.get("region_name")
                or properties.get("title", "")
            ).lower()

            if region_name:
                # Store under full name
                self.brain_regions[region_name] = {
                    "node_id": node_id,
                    "properties": properties,
                    "atlas": properties.get("atlas", "unknown"),
                }

                # Also store under common abbreviations
                abbreviations = self._get_region_abbreviations(region_name)
                for abbrev in abbreviations:
                    self.brain_regions[abbrev] = {
                        "node_id": node_id,
                        "properties": properties,
                        "atlas": properties.get("atlas", "unknown"),
                    }

        logger.info(f"Loaded {len(self.brain_regions)} BrainRegion nodes")

    def _get_region_abbreviations(self, full_name: str) -> list[str]:
        """Get common abbreviations for a brain region name."""
        abbreviations = []

        # Common abbreviation mappings
        mappings = {
            "dorsolateral prefrontal cortex": ["dlpfc"],
            "ventromedial prefrontal cortex": ["vmpfc", "vmPFC"],
            "anterior cingulate cortex": ["acc", "ACC"],
            "posterior cingulate cortex": ["pcc", "PCC"],
            "superior temporal gyrus": ["stg", "STG"],
            "middle temporal gyrus": ["mtg", "MTG"],
            "inferior temporal gyrus": ["itg", "ITG"],
            "superior parietal lobule": ["spl", "SPL"],
            "inferior parietal lobule": ["ipl", "IPL"],
            "dorsal attention network": ["dan", "DAN", "dorsal_attention"],
            "ventral attention network": ["van", "VAN", "ventral_attention"],
            "default mode network": ["dmn", "DMN", "default"],
            "frontoparietal network": ["fpn", "FPN", "frontoparietal"],
            "primary motor cortex": ["m1", "M1", "ba4"],
            "primary visual cortex": ["v1", "V1", "ba17"],
            "primary auditory cortex": ["a1", "A1", "ba41"],
            "broca's area": ["ba44", "ba45"],
            "hippocampus": ["hipp", "HPC"],
            "amygdala": ["amyg", "AMY"],
            "thalamus": ["thal", "THAL"],
            "caudate": ["cd", "CD"],
            "putamen": ["put", "PUT"],
            "pallidum": ["gp", "GP", "globus pallidus"],
        }

        # Check if full name contains any of the mapped terms
        for term, abbrevs in mappings.items():
            if term in full_name:
                abbreviations.extend(abbrevs)

        # Handle left/right hemisphere variations
        if "left" in full_name or " l " in full_name:
            base_abbrevs = abbreviations.copy()
            for abbrev in base_abbrevs:
                abbreviations.append(f"l_{abbrev}")
                abbreviations.append(f"left_{abbrev}")
                abbreviations.append(f"{abbrev}_l")

        if "right" in full_name or " r " in full_name:
            base_abbrevs = abbreviations.copy()
            for abbrev in base_abbrevs:
                abbreviations.append(f"r_{abbrev}")
                abbreviations.append(f"right_{abbrev}")
                abbreviations.append(f"{abbrev}_r")

        return abbreviations

    def map_coordinate_to_regions_mask(
        self, coord_id: str, coord_data: dict, test_mode: bool = False
    ) -> list[dict]:
        """
        Map a single coordinate to brain region using direct mask lookup.

        Args:
            coord_id: Coordinate node ID
            coord_data: Coordinate properties (must include x, y, z)
            test_mode: If True, only find regions without creating edges

        Returns:
            List of edge specifications (0 or 1 edge per coordinate)
        """
        # Extract coordinates
        try:
            x = float(coord_data.get("x", 0))
            y = float(coord_data.get("y", 0))
            z = float(coord_data.get("z", 0))
        except (ValueError, TypeError):
            logger.debug(f"Invalid coordinates for node {coord_id}")
            self.stats["invalid_coordinates"] += 1
            return []

        self.stats["mask_lookups"] += 1

        # Direct label lookup from atlas NIfTI
        label_idx = mni_to_label(x, y, z, self.atlas_data, self.atlas_inv_affine)

        if label_idx == 0:
            self.stats["no_nearby_regions"] += 1
            return []

        self.stats["mask_hits"] += 1

        # Build BrainRegion node ID based on atlas naming convention
        atlas_prefix = self.atlas.lower()
        if atlas_prefix in ("aal", "aal116"):
            atlas_prefix = "aal"
        elif atlas_prefix in ("schaefer400", "schaefer"):
            atlas_prefix = "schaefer400"
        elif atlas_prefix in ("yeo17", "yeo"):
            atlas_prefix = "yeo17"

        region_id = f"{atlas_prefix}:{label_idx}"

        # Look up BrainRegion node by ID
        region_info = None
        for stored_name, info in self.brain_regions.items():
            if info.get("properties", {}).get("id") == region_id:
                region_info = info
                break

        if not region_info:
            # Fallback: search by label_index property
            for stored_name, info in self.brain_regions.items():
                props = info.get("properties", {})
                if (
                    props.get("label_index") == label_idx
                    and props.get("atlas", "").lower() == atlas_prefix
                ):
                    region_info = info
                    break

        if not region_info:
            logger.debug(f"No BrainRegion node found for {region_id}")
            return []

        edge_spec = {
            "start_node": coord_id,
            "end_node": region_info["node_id"],
            "type": "IN_REGION",
            "properties": {
                "confidence": 1.0,  # Direct lookup = 100% confidence
                "atlas": self.atlas,
                "label_index": label_idx,
                "region_name": region_info.get("properties", {}).get("name", f"Region_{label_idx}"),
                "created_at": datetime.utcnow().isoformat(),
                "method": "mask_lookup",
            },
        }

        self.stats["regions_found"] += 1
        return [edge_spec]

    def map_coordinate_to_regions(
        self, coord_id: str, coord_data: dict, test_mode: bool = False
    ) -> list[dict]:
        """
        Map a single coordinate to nearby brain regions.

        Args:
            coord_id: Coordinate node ID
            coord_data: Coordinate properties (must include x, y, z)
            test_mode: If True, only find regions without creating edges

        Returns:
            List of edge specifications
        """
        # Use mask mode if enabled
        if self.mask_mode:
            return self.map_coordinate_to_regions_mask(coord_id, coord_data, test_mode)

        # Extract coordinates
        try:
            x = float(coord_data.get("x", 0))
            y = float(coord_data.get("y", 0))
            z = float(coord_data.get("z", 0))
            coords = [x, y, z]
        except (ValueError, TypeError):
            logger.warning(f"Invalid coordinates for node {coord_id}")
            self.stats["invalid_coordinates"] += 1
            return []

        # Validate coordinates
        is_valid, msg = validate_coordinates(coords, self.atlas)
        if not is_valid:
            logger.warning(f"Coordinate validation failed for {coord_id}: {msg}")
            self.stats["invalid_coordinates"] += 1
            return []

        # Find nearby ROIs using spatial utilities
        nearby_rois = find_nearby_rois(
            coords,
            atlas=self.atlas,
            radius=self.radius_mm,
            top_k=None,  # Get all within radius
        )

        if not nearby_rois:
            self.stats["no_nearby_regions"] += 1
            return []

        # Create edge specifications
        edges = []
        for roi_name, distance in nearby_rois:
            # Look up the BrainRegion node
            region_info = self.brain_regions.get(roi_name.lower())

            if not region_info:
                # Try to find partial matches
                matched = False
                for stored_name, info in self.brain_regions.items():
                    if (
                        roi_name.lower() in stored_name
                        or stored_name in roi_name.lower()
                    ):
                        region_info = info
                        matched = True
                        break

                if not matched:
                    logger.debug(f"No BrainRegion node found for ROI: {roi_name}")
                    continue

            # Calculate confidence based on distance (inverse relationship)
            # Confidence = 1.0 at distance 0, drops to ~0.37 at radius
            confidence = min(1.0, max(0.0, 1.0 - (distance / (self.radius_mm * 2))))

            edge_spec = {
                "start_node": coord_id,
                "end_node": region_info["node_id"],
                "type": "IN_REGION",
                "properties": {
                    "distance_mm": round(distance, 2),
                    "confidence": round(confidence, 3),
                    "atlas": self.atlas,
                    "region_name": roi_name,
                    "created_at": datetime.utcnow().isoformat(),
                    "method": "spatial_proximity",
                },
            }

            edges.append(edge_spec)
            self.stats["regions_found"] += 1

        return edges

    def process_coordinates(
        self, limit: int = None, batch_size: int = 1000, test_mode: bool = False
    ) -> None:
        """
        Process all coordinates and create IN_REGION relationships.

        Args:
            limit: Maximum number of coordinates to process (None for all)
            batch_size: Number of coordinates to process before logging progress
            test_mode: If True, only analyze without creating edges
        """
        # Get all coordinate nodes
        logger.info("Loading Coordinate nodes...")
        all_coords = self.db.find_nodes(labels="Coordinate")

        if limit:
            all_coords = all_coords[:limit]

        total_coords = len(all_coords)
        logger.info(f"Processing {total_coords} coordinates...")

        # Process coordinates
        all_edges = []

        for idx, (coord_id, coord_data) in enumerate(all_coords):
            self.stats["coordinates_processed"] += 1

            # Map to regions
            edges = self.map_coordinate_to_regions(coord_id, coord_data, test_mode)
            all_edges.extend(edges)

            # Progress logging
            if (idx + 1) % batch_size == 0:
                logger.info(
                    f"Processed {idx + 1}/{total_coords} coordinates, "
                    f"found {len(all_edges)} potential edges"
                )

        # Create edges in database (unless in test mode)
        if not test_mode and all_edges:
            logger.info(f"Creating {len(all_edges)} IN_REGION edges...")

            for edge in all_edges:
                # Check if edge already exists
                existing = self.db.find_relationships(
                    start_node=edge["start_node"],
                    end_node=edge["end_node"],
                    rel_type=edge["type"],
                )

                if existing:
                    self.stats["edges_skipped"] += 1
                    continue

                # Create the edge
                success = self.db.create_relationship(
                    edge["start_node"],
                    edge["end_node"],
                    edge["type"],
                    edge["properties"],
                )

                if success:
                    self.stats["edges_created"] += 1

        # Print summary
        self._print_summary()

    def _print_summary(self) -> None:
        """Print processing summary."""
        logger.info("\n" + "=" * 50)
        logger.info("COORDINATE TO REGION MAPPING SUMMARY")
        logger.info("=" * 50)
        logger.info(f"Atlas used: {self.atlas}")
        logger.info(f"Mode: {'mask_lookup' if self.mask_mode else 'spatial_proximity'}")
        if not self.mask_mode:
            logger.info(f"Search radius: {self.radius_mm} mm")
        logger.info(f"Coordinates processed: {self.stats['coordinates_processed']}")
        logger.info(f"Invalid coordinates: {self.stats['invalid_coordinates']}")
        logger.info(
            f"Coordinates with no nearby regions: {self.stats['no_nearby_regions']}"
        )
        logger.info(f"Total region mappings found: {self.stats['regions_found']}")
        logger.info(f"IN_REGION edges created: {self.stats['edges_created']}")
        logger.info(f"Edges skipped (already exist): {self.stats['edges_skipped']}")

        if self.mask_mode:
            logger.info(f"Mask lookups: {self.stats['mask_lookups']}")
            logger.info(f"Mask hits (label > 0): {self.stats['mask_hits']}")
            if self.stats["mask_lookups"] > 0:
                hit_rate = self.stats["mask_hits"] / self.stats["mask_lookups"] * 100
                logger.info(f"Mask hit rate: {hit_rate:.1f}%")

        if self.stats["coordinates_processed"] > 0:
            avg_regions = (
                self.stats["regions_found"] / self.stats["coordinates_processed"]
            )
            logger.info(f"Average regions per coordinate: {avg_regions:.2f}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Create IN_REGION edges between Coordinates and BrainRegions"
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Deprecated (ignored). Neo4j connection uses NEO4J_* env vars.",
    )
    parser.add_argument(
        "--atlas",
        default="MNI",
        help="Atlas to use for mapping (MNI for centroid mode; aal/schaefer400/yeo17 for mask mode)",
    )
    parser.add_argument(
        "--radius",
        type=float,
        default=20.0,
        help="Search radius in millimeters (default: 20mm, only used in centroid mode)",
    )
    parser.add_argument(
        "--limit", type=int, help="Limit number of coordinates to process (for testing)"
    )
    parser.add_argument(
        "--batch-size", type=int, default=1000, help="Batch size for progress updates"
    )
    parser.add_argument(
        "--test-mode", action="store_true", help="Run in test mode (no edges created)"
    )
    parser.add_argument(
        "--mask-mode",
        action="store_true",
        help="Use mask-based lookup instead of centroid distance matching. "
        "Requires atlas to be one of: aal, schaefer400, yeo17",
    )

    args = parser.parse_args()

    # Validate mask mode atlas
    if args.mask_mode:
        valid_mask_atlases = ("aal", "aal116", "schaefer400", "schaefer", "yeo17", "yeo")
        if args.atlas.lower() not in valid_mask_atlases:
            logger.error(
                f"Mask mode requires atlas to be one of: {valid_mask_atlases}. Got: {args.atlas}"
            )
            raise SystemExit(1)

    # Initialize database (Neo4j only)
    db = require_neo4j_db(args.db_path, preload_cache=False)
    logger.info("Connected to graph backend: %s", type(db).__name__)

    try:
        # Check initial statistics
        try:
            stats = db.get_stats()
            if isinstance(stats, dict):
                initial_in_region = stats.get("relationship_types", {}).get("IN_REGION", 0)
            else:
                # Fallback: query directly
                result = db.execute_query("MATCH ()-[r:IN_REGION]->() RETURN count(r) as cnt")
                initial_in_region = result[0]["cnt"] if result else 0
        except Exception:
            initial_in_region = 0
        logger.info(f"Initial IN_REGION relationships: {initial_in_region}")

        # Create mapper and process
        mapper = CoordinateRegionMapper(
            db, atlas=args.atlas, radius_mm=args.radius, mask_mode=args.mask_mode
        )
        mapper.process_coordinates(
            limit=args.limit, batch_size=args.batch_size, test_mode=args.test_mode
        )

        # Final statistics
        if not args.test_mode:
            try:
                final_stats = db.get_stats()
                if isinstance(final_stats, dict):
                    final_in_region = final_stats.get("relationship_types", {}).get("IN_REGION", 0)
                else:
                    result = db.execute_query("MATCH ()-[r:IN_REGION]->() RETURN count(r) as cnt")
                    final_in_region = result[0]["cnt"] if result else 0
            except Exception:
                final_in_region = 0
            logger.info(
                f"\nFinal IN_REGION relationships: {initial_in_region} -> {final_in_region}"
            )

    finally:
        db.close()


if __name__ == "__main__":
    main()
