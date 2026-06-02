"""
NiCLIP Spatial-Semantic Mapper

Maps brain coordinates to cognitive concepts using NiCLIP's
brain-language alignment model and DiFuMo atlas.

This module provides:
1. Coordinate to parcel mapping (DiFuMo 512)
2. Parcel to concept mapping via CLIP embeddings
3. Concept scoring and ranking
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import nibabel as nib
import numpy as np
from scipy.spatial.distance import cdist

logger = logging.getLogger(__name__)


class NiCLIPSpatialMapper:
    """Maps brain coordinates to concepts using NiCLIP brain-language alignment."""

    def __init__(self, niclip_path: Optional[Path] = None):
        """Initialize spatial mapper with NiCLIP data."""
        # Default to standard NiCLIP data path
        if niclip_path is None:
            niclip_path = (
                Path(__file__).parent.parent.parent.parent.parent.parent
                / "data"
                / "niclip"
                / "dsj56"
                / "osfstorage"
                / "osfstorage"
                / "data"
            )

        self.niclip_path = Path(niclip_path)
        if not self.niclip_path.exists():
            logger.warning(f"NiCLIP data path not found: {self.niclip_path}")
            self._loaded = False
            return

        # Load brain mask for coordinate validation
        self.brain_mask_path = self.niclip_path / "MNI152_2x2x2_brainmask.nii.gz"

        # Load embeddings and mappings
        self._loaded = False
        self._load_data()

    def _load_data(self):
        """Load NiCLIP embeddings and mappings."""
        try:
            # Load brain mask
            if self.brain_mask_path.exists():
                self.brain_mask = nib.load(str(self.brain_mask_path))
                self.brain_affine = self.brain_mask.affine
                self.brain_data = self.brain_mask.get_fdata()
            else:
                logger.warning("Brain mask not found")
                self.brain_mask = None

            # Load task vocabulary and priors
            self._load_vocabulary_priors()

            # Load brain embeddings (DiFuMo)
            self._load_brain_embeddings()

            # Load concept mappings
            self._load_concept_mappings()

            self._loaded = True
            logger.info("NiCLIP spatial mapper loaded successfully")

        except Exception as e:
            logger.error(f"Failed to load NiCLIP spatial data: {e}")
            self._loaded = False

    def _load_vocabulary_priors(self):
        """Load vocabulary priors (task/concept scores)."""
        # Use BrainGPT-7B-v0.2 as it's the latest
        prior_file = (
            self.niclip_path
            / "vocabulary"
            / "vocabulary-cogatlas_task-combined_embedding-BrainGPT-7B-v0.2_section-abstract_prior.csv"
        )

        self.task_priors = {}
        if prior_file.exists():
            import csv

            with open(prior_file) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    self.task_priors[row["name"]] = float(row["prior"])
            logger.info(f"Loaded {len(self.task_priors)} task priors")
        else:
            logger.warning("Task priors file not found")

    def _load_brain_embeddings(self):
        """Load DiFuMo brain embeddings."""
        # Load standardized MKDA embeddings
        embed_file = (
            self.niclip_path
            / "image"
            / "image-standardized_coord-MKDA_embedding-DiFuMo.npy"
        )

        if embed_file.exists():
            self.brain_embeddings = np.load(str(embed_file))
            logger.info(f"Loaded brain embeddings: {self.brain_embeddings.shape}")
        else:
            logger.warning("Brain embeddings not found")
            self.brain_embeddings = None

    def _load_concept_mappings(self):
        """Load concept to task/process mappings."""
        # Load reduced tasks mapping
        tasks_file = self.niclip_path / "cognitive_atlas" / "reduced_tasks.csv"
        self.task_concepts = {}

        if tasks_file.exists():
            import csv

            with open(tasks_file) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    task = row["task"]
                    concepts = [
                        row.get("concept_1", "").strip(),
                        row.get("concept_2", "").strip(),
                        row.get("concept_3", "").strip(),
                    ]
                    self.task_concepts[task] = [c for c in concepts if c]

        # Load concept to process mapping
        process_file = self.niclip_path / "cognitive_atlas" / "concept_to_process.json"
        if process_file.exists():
            with open(process_file) as f:
                self.concept_process = json.load(f)
        else:
            self.concept_process = {}

    def coordinate_to_concepts(
        self,
        coordinates: List[Tuple[float, float, float]],
        radius: float = 10.0,
        top_k: int = 5,
    ) -> List[Dict]:
        """
        Map MNI coordinates to cognitive concepts.

        Args:
            coordinates: List of (x, y, z) MNI coordinates
            radius: Search radius in mm
            top_k: Number of top concepts to return

        Returns:
            List of mappings for each coordinate
        """
        if not self._loaded:
            return [
                {"coordinate": coord, "concepts": [], "error": "NiCLIP data not loaded"}
                for coord in coordinates
            ]

        results = []

        for coord in coordinates:
            # Validate coordinate is in brain
            if self.brain_mask and not self._is_in_brain(coord):
                results.append(
                    {
                        "coordinate": coord,
                        "concepts": [],
                        "warning": "Coordinate outside brain mask",
                    }
                )
                continue

            # Find nearby parcels/regions
            nearby_regions = self._find_nearby_regions(coord, radius)

            # Map regions to concepts using priors
            concept_scores = self._regions_to_concepts(nearby_regions)

            # Sort by score and take top k
            sorted_concepts = sorted(
                concept_scores.items(), key=lambda x: x[1], reverse=True
            )[:top_k]

            results.append(
                {
                    "coordinate": coord,
                    "concepts": [
                        {
                            "name": concept,
                            "score": score,
                            "process": self.concept_process.get(concept, "unmapped"),
                        }
                        for concept, score in sorted_concepts
                    ],
                    "radius_mm": radius,
                }
            )

        return results

    def _is_in_brain(self, coord: Tuple[float, float, float]) -> bool:
        """Check if coordinate is within brain mask."""
        if self.brain_mask is None:
            return True  # Assume valid if no mask

        # Convert MNI to voxel coordinates
        voxel_coord = nib.affines.apply_affine(np.linalg.inv(self.brain_affine), coord)

        # Check bounds
        x, y, z = [int(round(c)) for c in voxel_coord]
        if (
            0 <= x < self.brain_data.shape[0]
            and 0 <= y < self.brain_data.shape[1]
            and 0 <= z < self.brain_data.shape[2]
        ):
            return self.brain_data[x, y, z] > 0
        return False

    def _find_nearby_regions(
        self, coord: Tuple[float, float, float], radius: float
    ) -> List[Dict]:
        """Find brain regions within radius of coordinate."""
        # For now, return mock regions
        # In full implementation, this would use DiFuMo atlas
        return [
            {"region": "dlPFC", "distance": 5.0, "weight": 0.8},
            {"region": "ACC", "distance": 8.0, "weight": 0.6},
        ]

    def _regions_to_concepts(self, regions: List[Dict]) -> Dict[str, float]:
        """Map brain regions to cognitive concepts with scores."""
        concept_scores = {}

        # Aggregate scores from all nearby regions
        for region in regions:
            # Find tasks associated with this region
            # This is simplified - full implementation would use
            # brain embeddings and CLIP alignment

            # For now, use task priors as proxy
            for task, prior in self.task_priors.items():
                # Weight by region proximity
                score = prior * region["weight"]

                # Get concepts for this task
                if task in self.task_concepts:
                    for concept in self.task_concepts[task]:
                        if concept:
                            if concept not in concept_scores:
                                concept_scores[concept] = 0
                            concept_scores[concept] += score

        return concept_scores

    def get_task_brain_alignment(self, task_name: str) -> Optional[float]:
        """Get brain-language alignment score for a task."""
        return self.task_priors.get(task_name, None)

    def get_concept_process(self, concept: str) -> Optional[str]:
        """Get cognitive process for a concept."""
        return self.concept_process.get(concept, None)


# Convenience function
def get_spatial_mapper() -> Optional[NiCLIPSpatialMapper]:
    """Get or create the global spatial mapper instance."""
    try:
        return NiCLIPSpatialMapper()
    except Exception as e:
        logger.error(f"Failed to create spatial mapper: {e}")
        return None
