"""
# Spatial Mapping Guide for BR-KG

This guide explains the enhanced spatial search capabilities that allow searching neuroimaging data using ROI names and automatic coordinate conversions.

## Overview

The enhanced SpatialSearchTool now supports:
- **ROI Name Lookup**: Search using anatomical region names instead of coordinates
- **Multiple Atlases**: Support for MNI, Talairach, AAL, and Harvard-Oxford atlases
- **Coordinate Conversion**: Automatic conversion between Talairach and MNI spaces
- **Overlap Scoring**: Probabilistic overlap scores when searching with ROIs
- **Nearby ROI Detection**: Find what brain regions are near your search location

## Quick Start

### Search by ROI Name

Instead of providing coordinates, you can now search using common ROI names:

```python
# Search near the insula
result = spatial_search_tool.run(
    roi_name="insula",
    atlas_name="MNI",
    radius=15.0,
    top_k=10
)

# Search near Broca's area (BA44)
result = spatial_search_tool.run(
    roi_name="ba44",
    atlas_name="MNI",
    radius=20.0
)

# Search using AAL atlas regions
result = spatial_search_tool.run(
    roi_name="hippocampus_l",
    atlas_name="AAL",
    radius=25.0
)
```

### Search with Coordinate Conversion

The tool automatically handles coordinate space conversions:

```python
# Provide Talairach coordinates, automatically converted to MNI
result = spatial_search_tool.run(
    coordinates=[34.0, 16.0, 4.0],
    coord_space="Talairach",
    radius=10.0
)
```

## Available Atlases and ROIs

### Anatomical Atlases

#### MNI Atlas
The most comprehensive atlas with ~50+ regions including:
- **Anatomical regions**: insula, hippocampus, amygdala, thalamus, caudate, putamen
- **Brodmann areas**: ba44, ba45, ba4, ba6, ba17, ba41, ba1-3
- **Cortical regions**: prefrontal_cortex, dlpfc, vmpfc, acc, pcc
- **Lobes and gyri**: superior_temporal_gyrus, fusiform_gyrus, angular_gyrus

#### Talairach Atlas
Selected regions with Talairach coordinates:
- Major subcortical structures
- Key Brodmann areas
- Primary sensory/motor regions

#### AAL (Automated Anatomical Labeling)
Detailed parcellation with lateralized regions:
- precentral_l/r, frontal_sup_l/r, frontal_mid_l/r
- hippocampus_l/r, amygdala_l/r
- ~90 regions with left/right variants

#### Harvard-Oxford Atlas
Probabilistic atlas regions:
- Cortical and subcortical parcellations
- frontal_pole, insular_cortex
- Detailed temporal and frontal subdivisions

### Functional Network Atlases

#### Yeo7 (7-Network Parcellation)
Resting-state functional connectivity networks (Yeo et al., 2011):
- **visual**: Primary and higher visual areas
- **somatomotor**: Motor and somatosensory cortex
- **dorsal_attention** (DAN): FEF, IPS regions
- **ventral_attention** (VAN): TPJ, ventral frontal cortex
- **limbic**: Orbitofrontal, temporal pole regions
- **frontoparietal** (FPN): Lateral prefrontal, posterior parietal
- **default** (DMN): mPFC, PCC, angular gyrus

Common aliases supported: dmn, dan, van, fpn

#### Yeo17 (17-Network Parcellation)
Finer-grained version with network subdivisions:
- Visual networks (A/B)
- Somatomotor networks (A/B)
- Dorsal attention networks (A/B)
- Salience/Ventral attention networks (A/B)
- Limbic networks (A/B)
- Control networks (A/B/C)
- Default mode networks (A/B/C)
- Temporal-parietal network

#### Schaefer400 (400 Parcels)
Functional parcellation based on Yeo networks:
- Named parcels within each network (vis_1, sommat_1, etc.)
- 400 cortical parcels total
- Hierarchical organization by network

#### Power264 (264 Nodes)
Functional nodes grouped by network:
- **Default mode**: dmn_mpfc, dmn_pcc, dmn_lp_l/r
- **Fronto-parietal**: fpn_lpfc_l/r, fpn_ppc_l/r
- **Cingulo-opercular**: co_ains_l/r, co_dacc
- **Dorsal attention**: dan_fef_l/r, dan_ips_l/r
- **Ventral attention**: van_tpj_l/r, van_vfc_r
- **Visual**: vis_v1, vis_mt_l/r
- **Sensorimotor**: sm_m1_l/r, sm_s1_l/r

#### Gordon333 (333 Parcels)
Community-based parcellation:
- **Default**: default_pcc, default_mpfc, default_ag_l/r
- **Fronto-parietal**: fp_dlpfc_l/r, fp_ips_l/r
- **Cingulo-opercular**: co_acc, co_ains_l/r
- **Dorsal attention**: da_fef_l/r, da_mt_l/r
- **Ventral attention**: va_tpj_l/r
- **Visual**: vis_v1, vis_v2_l/r
- **Sensorimotor**: sm_cs_hand, sm_cs_face_l/r
- **Auditory**: aud_stg_l/r

## ROI Naming Conventions

- **Case-insensitive**: "Insula", "insula", "INSULA" all work
- **Underscores**: Use underscores for multi-word regions (e.g., "superior_temporal_gyrus")
- **Lateralization**:
  - Prefix: "left_insula", "right_insula"
  - Suffix (AAL style): "hippocampus_l", "hippocampus_r"
- **Abbreviations**: Common abbreviations supported (e.g., "dlpfc", "vmpfc", "acc", "stg")

## Response Enhancements

When using ROI search, the response includes additional information:

```json
{
    "results": [
        {
            "id": "study1_coord1",
            "coordinates": [35, 20, 5],
            "distance_to_query": 2.5,
            "overlap_score": 0.88,  // NEW: Probabilistic overlap with ROI
            ...
        }
    ],
    "nearby_rois": [  // NEW: What ROIs are near the search location
        {"name": "insula", "distance_mm": 0.0},
        {"name": "rolandic_operculum", "distance_mm": 8.5}
    ],
    "search_summary": "Searched within 15mm of insula (MNI atlas)"
}
```

## Overlap Scoring

The overlap score indicates how much a result overlaps with the target ROI:
- **1.0**: Perfect overlap (at ROI center)
- **0.5-0.9**: High overlap (within typical ROI boundaries)
- **0.1-0.5**: Moderate overlap (nearby but distinct)
- **<0.1**: Low overlap (distant from ROI)

Two scoring methods are available:
- **Gaussian** (default): Smooth decay based on distance
- **Sphere**: Binary sphere model with transition zone

## Coordinate Transformations

The system supports two transformation methods:

### Lancaster Transform (default)
- More accurate for subcortical structures
- Recommended for most use cases

### Brett Transform
- Alternative transformation matrix
- May be preferred for certain applications

## Error Handling

The tool provides helpful error messages:

```python
# Invalid ROI name
"ROI 'unknown_region' not found in MNI atlas. Available ROIs include: insula, hippocampus, amygdala..."

# Invalid atlas
"atlas_name must be one of: MNI, Talairach, AAL, HarvardOxford"

# Missing input
"Either 'coordinates' or 'roi_name' must be provided"

# Conflicting input
"Provide either 'coordinates' or 'roi_name', not both"
```

## Best Practices

1. **Choose the right atlas**:
   - MNI for general searches
   - AAL for detailed lateralized searches
   - Harvard-Oxford for probabilistic regions

2. **Adjust search radius**:
   - 10-15mm for focused searches
   - 20-30mm for broader regional searches
   - Consider ROI size when setting radius

3. **Use overlap scores**:
   - Filter results by overlap_score for ROI-specific studies
   - Higher thresholds (>0.7) for strict ROI matching

4. **Combine with semantic search**:
   - Use hybrid_search with ROI constraints for best results
   - Example: Find "working memory" studies near "dlpfc"

## Examples

### Find Language Studies near Broca's Area
```python
result = spatial_search_tool.run(
    roi_name="ba44",
    atlas_name="MNI",
    radius=20.0,
    top_k=20
)
# Filter by high overlap scores
language_studies = [r for r in result.data["results"] if r["overlap_score"] > 0.7]
```

### Search within Brain Networks
```python
# Search for studies in the default mode network
result = spatial_search_tool.run(
    roi_name="default",
    atlas_name="Yeo7",
    radius=25.0,
    top_k=50
)

# Search specific DMN nodes
result = spatial_search_tool.run(
    roi_name="dmn_pcc",
    atlas_name="Power264",
    radius=15.0
)

# Search frontoparietal network
result = spatial_search_tool.run(
    roi_name="frontoparietal",
    atlas_name="Yeo7",
    radius=30.0
)
```

### Fine-grained Network Parcellation Search
```python
# Search within specific network subdivisions
result = spatial_search_tool.run(
    roi_name="default_a",  # Core DMN
    atlas_name="Yeo17",
    radius=20.0
)

# Search specific Schaefer parcels
for parcel in ["default_1", "default_2", "default_3"]:
    result = spatial_search_tool.run(
        roi_name=parcel,
        atlas_name="Schaefer400",
        radius=10.0
    )
    print(f"Parcel {parcel}: {result.data['n_results']} studies")
```

### Network Node Comparison
```python
# Compare DMN nodes across atlases
dmn_nodes = {
    "Power264": ["dmn_mpfc", "dmn_pcc", "dmn_lp_l"],
    "Gordon333": ["default_mpfc", "default_pcc", "default_ag_l"],
    "Yeo7": ["default"]
}

for atlas, nodes in dmn_nodes.items():
    for node in nodes:
        result = spatial_search_tool.run(
            roi_name=node,
            atlas_name=atlas,
            radius=15.0
        )
        coords = result.data["query_params"]["coordinates"]
        print(f"{atlas} - {node}: {coords}")
```

### Search Multiple ROIs
```python
# Search memory network regions
for roi in ["hippocampus", "pcc", "angular_gyrus"]:
    result = spatial_search_tool.run(
        roi_name=roi,
        atlas_name="MNI",
        radius=15.0
    )
    print(f"{roi}: {result.data['n_results']} studies found")
```

### Cross-Atlas Search
```python
# Compare results across atlases
roi_name = "hippocampus"
for atlas in ["MNI", "AAL", "HarvardOxford"]:
    try:
        result = spatial_search_tool.run(
            roi_name=roi_name if atlas != "AAL" else "hippocampus_l",
            atlas_name=atlas,
            radius=20.0
        )
        coords = result.data["query_params"]["coordinates"]
        print(f"{atlas}: {coords}")
    except:
        print(f"{atlas}: ROI not found")
```

## Utility Functions

The `utils.spatial` module provides additional functions:

- `list_available_rois(atlas)`: Get all ROIs in an atlas
- `find_nearby_rois(coord, atlas, radius)`: Find ROIs near a coordinate
- `validate_coordinates(coords, space)`: Check if coordinates are valid
- `euclidean_distance(coord1, coord2)`: Calculate distance between points

## Future Enhancements

Planned improvements include:
- Support for surface-based atlases (fsaverage, CIFTI)
- Integration with probabilistic atlas maps
- Custom atlas upload capability
- Connectivity-based ROI definitions
- Automated ROI size estimation

Enhanced NiCLIP Spatial-Semantic Mapper

Maps brain coordinates to cognitive concepts using NiCLIP's
brain-language alignment model with improved spatial mapping.

Key improvements:
1. Gaussian distance weighting for smooth spatial decay
2. Percentile-based normalization of alignment scores
3. Proper DiFuMo atlas integration
4. Multi-dimensional concept embeddings
"""

import logging
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import pandas as pd
from scipy.spatial.distance import cdist, cosine
from scipy.stats import percentileofscore

logger = logging.getLogger(__name__)


class EnhancedNiCLIPSpatialMapper:
    """Enhanced spatial mapper with Gaussian weighting and percentile normalization."""

    def __init__(
        self,
        niclip_path: Path | None = None,
        atlas: str = "difumo512",
        gaussian_sigma: float = 3.33,  # Default: radius/3
        percentile_base: int = 100000,  # Sample size for percentile calculation
    ):
        """
        Initialize enhanced spatial mapper.

        Args:
            niclip_path: Path to NiCLIP data
            atlas: Atlas to use (difumo256, difumo512, difumo1024)
            gaussian_sigma: Sigma for Gaussian distance weighting
            percentile_base: Number of samples for percentile normalization
        """
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
        self.atlas = atlas
        self.gaussian_sigma = gaussian_sigma
        self.percentile_base = percentile_base

        if not self.niclip_path.exists():
            logger.warning(f"NiCLIP data path not found: {self.niclip_path}")
            self._loaded = False
            return

        self._loaded = False
        self._load_data()

    def _load_data(self):
        """Load all necessary data with error handling."""
        try:
            # Load brain mask for validation
            self._load_brain_mask()

            # Load DiFuMo atlas
            self._load_difumo_atlas()

            # Load CLIP embeddings
            self._load_clip_embeddings()

            # Load vocabulary and mappings
            self._load_vocabulary()

            # Calculate percentile distributions
            self._calculate_percentiles()

            self._loaded = True
            logger.info(f"Enhanced NiCLIP mapper loaded successfully with {self.atlas}")

        except Exception as e:
            logger.error(f"Failed to load enhanced mapper: {e}")
            self._loaded = False

    def _load_brain_mask(self):
        """Load MNI brain mask for coordinate validation."""
        mask_path = self.niclip_path / "MNI152_2x2x2_brainmask.nii.gz"

        if mask_path.exists():
            self.brain_mask = nib.load(str(mask_path))
            self.brain_affine = self.brain_mask.affine
            self.brain_data = self.brain_mask.get_fdata()
            logger.info("Loaded brain mask")
        else:
            logger.warning("Brain mask not found, coordinate validation disabled")
            self.brain_mask = None

    def _load_difumo_atlas(self):
        """Load DiFuMo atlas parcellation and coordinates."""
        # Map atlas names to file patterns
        atlas_map = {"difumo256": "256", "difumo512": "512", "difumo1024": "1024"}

        atlas_num = atlas_map.get(self.atlas, "512")

        # Load atlas image
        atlas_path = (
            self.niclip_path
            / "atlases"
            / f"atlas-DiFuMo_dimension-{atlas_num}_data-MNI152_2mm.nii.gz"
        )

        if atlas_path.exists():
            self.atlas_img = nib.load(str(atlas_path))
            self.atlas_data = self.atlas_img.get_fdata()
            self.atlas_affine = self.atlas_img.affine
            logger.info(f"Loaded DiFuMo {atlas_num} atlas")
        else:
            # Try alternative path
            atlas_path = self.niclip_path / "difumo" / f"maps_{atlas_num}.nii.gz"
            if atlas_path.exists():
                self.atlas_img = nib.load(str(atlas_path))
                self.atlas_data = self.atlas_img.get_fdata()
                self.atlas_affine = self.atlas_img.affine
                logger.info(f"Loaded DiFuMo {atlas_num} atlas (alternative path)")
            else:
                raise FileNotFoundError(f"DiFuMo atlas not found: {atlas_path}")

        # Load parcel coordinates
        coords_path = self.niclip_path / "difumo" / f"labels_{atlas_num}_dictionary.csv"
        if coords_path.exists():
            self.parcel_coords = pd.read_csv(coords_path)
            # Extract MNI coordinates
            self.parcel_centers = self.parcel_coords[["x", "y", "z"]].values
            self.parcel_names = self.parcel_coords["Difumo_names"].values
            logger.info(f"Loaded {len(self.parcel_centers)} parcel coordinates")
        else:
            # Calculate parcel centers from atlas
            self._calculate_parcel_centers()

    def _calculate_parcel_centers(self):
        """Calculate parcel centers from atlas image."""
        unique_parcels = np.unique(self.atlas_data)
        unique_parcels = unique_parcels[unique_parcels > 0]  # Exclude background

        self.parcel_centers = []
        self.parcel_names = []

        for parcel_id in unique_parcels:
            # Find voxel coordinates for this parcel
            voxel_coords = np.array(np.where(self.atlas_data == parcel_id)).T

            # Calculate center of mass
            center_voxel = voxel_coords.mean(axis=0)

            # Convert to MNI coordinates
            center_mni = nib.affines.apply_affine(self.atlas_affine, center_voxel)

            self.parcel_centers.append(center_mni)
            self.parcel_names.append(f"Parcel_{int(parcel_id)}")

        self.parcel_centers = np.array(self.parcel_centers)
        logger.info(f"Calculated {len(self.parcel_centers)} parcel centers")

    def _load_clip_embeddings(self):
        """Load brain and text CLIP embeddings."""
        # Load brain embeddings
        brain_embed_path = (
            self.niclip_path
            / "image"
            / f"image-DiFuMo_{self.atlas.replace('difumo', '')}_embedding-CLIP-ViT-B-32.npy"
        )

        if brain_embed_path.exists():
            self.brain_embeddings = np.load(str(brain_embed_path))
            logger.info(f"Loaded brain embeddings: {self.brain_embeddings.shape}")
        else:
            # Try alternative path
            brain_embed_path = (
                self.niclip_path / "embeddings" / f"brain_embeddings_{self.atlas}.npy"
            )
            if brain_embed_path.exists():
                self.brain_embeddings = np.load(str(brain_embed_path))
            else:
                raise FileNotFoundError(
                    f"Brain embeddings not found: {brain_embed_path}"
                )

        # Load text embeddings
        text_embed_path = (
            self.niclip_path / "text" / "text-cogatlas_task_embedding-CLIP-ViT-B-32.npy"
        )

        if text_embed_path.exists():
            self.text_embeddings = np.load(str(text_embed_path))
            logger.info(f"Loaded text embeddings: {self.text_embeddings.shape}")
        else:
            raise FileNotFoundError(f"Text embeddings not found: {text_embed_path}")

    def _load_vocabulary(self):
        """Load task vocabulary and concept mappings."""
        # Load vocabulary priors
        vocab_path = (
            self.niclip_path
            / "vocabulary"
            / "vocabulary-cogatlas_task-combined_embedding-CLIP-ViT-B-32_prior.csv"
        )

        if vocab_path.exists():
            self.vocabulary = pd.read_csv(vocab_path)
            self.task_names = self.vocabulary["name"].values
            self.task_priors = dict(
                zip(self.vocabulary["name"], self.vocabulary["prior"], strict=False)
            )
            logger.info(f"Loaded {len(self.task_names)} tasks")
        else:
            raise FileNotFoundError(f"Vocabulary not found: {vocab_path}")

        # Load task to concept mappings
        self._load_task_concepts()

    def _load_task_concepts(self):
        """Load task to concept mappings."""
        # Try reduced tasks first
        tasks_file = self.niclip_path / "cognitive_atlas" / "reduced_tasks.csv"
        self.task_to_concepts = {}
        self.concept_to_process = {}

        if tasks_file.exists():
            df = pd.read_csv(tasks_file)
            for _, row in df.iterrows():
                task = row["task"]
                concepts = []
                for i in range(1, 4):  # concept_1, concept_2, concept_3
                    concept = row.get(f"concept_{i}", "").strip()
                    if concept:
                        concepts.append(concept)
                        # Map concept to process
                        process = row.get(f"process_{i}", "").strip()
                        if process:
                            self.concept_to_process[concept] = process

                self.task_to_concepts[task] = concepts

            logger.info(f"Loaded {len(self.task_to_concepts)} task-concept mappings")
        else:
            logger.warning("Task concepts file not found")

    def _calculate_percentiles(self):
        """Pre-calculate percentile distributions for normalization."""
        if not hasattr(self, "brain_embeddings") or not hasattr(
            self, "text_embeddings"
        ):
            logger.warning("Embeddings not loaded, skipping percentile calculation")
            return

        # Sample random brain-text pairs for percentile calculation
        n_brain = self.brain_embeddings.shape[0]
        n_text = self.text_embeddings.shape[0]
        n_samples = min(self.percentile_base, n_brain * n_text)

        # Generate random pairs
        brain_indices = np.random.randint(0, n_brain, n_samples)
        text_indices = np.random.randint(0, n_text, n_samples)

        # Calculate cosine similarities
        sample_scores = []
        for b_idx, t_idx in zip(brain_indices, text_indices, strict=False):
            score = 1 - cosine(
                self.brain_embeddings[b_idx], self.text_embeddings[t_idx]
            )
            sample_scores.append(score)

        self.score_distribution = np.array(sample_scores)

        # Calculate key percentiles
        self.percentiles = {
            "p50": np.percentile(self.score_distribution, 50),
            "p75": np.percentile(self.score_distribution, 75),
            "p90": np.percentile(self.score_distribution, 90),
            "p95": np.percentile(self.score_distribution, 95),
            "p99": np.percentile(self.score_distribution, 99),
        }

        logger.info(
            f"Calculated percentiles from {n_samples} samples: {self.percentiles}"
        )

    def coordinate_to_concepts(
        self,
        coordinates: list[tuple[float, float, float]],
        radius: float = 10.0,
        top_k: int = 5,
        min_percentile: float = 50.0,
    ) -> list[dict[str, Any]]:
        """
        Map MNI coordinates to cognitive concepts using enhanced method.

        Args:
            coordinates: List of MNI coordinates (x, y, z)
            radius: Search radius in mm
            top_k: Number of top concepts to return
            min_percentile: Minimum percentile for concept inclusion

        Returns:
            List of mappings with concepts and scores
        """
        if not self._loaded:
            return [
                {
                    "coordinate": coord,
                    "error": "Enhanced mapper not loaded",
                    "concepts": [],
                }
                for coord in coordinates
            ]

        results = []

        for coord in coordinates:
            # Validate coordinate
            if self.brain_mask and not self._is_in_brain(coord):
                results.append(
                    {
                        "coordinate": coord,
                        "warning": "Coordinate outside brain mask",
                        "concepts": [],
                    }
                )
                continue

            # Find nearby parcels with Gaussian weighting
            parcel_weights = self._get_parcel_weights(coord, radius)

            if not parcel_weights:
                results.append(
                    {
                        "coordinate": coord,
                        "warning": "No parcels found within radius",
                        "concepts": [],
                    }
                )
                continue

            # Calculate concept scores
            concept_scores = self._calculate_concept_scores(
                parcel_weights, min_percentile
            )

            # Get top concepts
            top_concepts = sorted(
                concept_scores.items(), key=lambda x: x[1]["score"], reverse=True
            )[:top_k]

            # Format results
            concepts = []
            for concept_name, concept_data in top_concepts:
                concepts.append(
                    {
                        "concept": concept_name,
                        "score": concept_data["score"],
                        "percentile": concept_data["percentile"],
                        "process": self.concept_to_process.get(concept_name, "unknown"),
                        "contributing_parcels": concept_data["parcels"],
                    }
                )

            results.append(
                {
                    "coordinate": coord,
                    "concepts": concepts,
                    "n_parcels": len(parcel_weights),
                    "method": "enhanced_gaussian_weighted",
                }
            )

        return results

    def _is_in_brain(self, coord: tuple[float, float, float]) -> bool:
        """Check if coordinate is within brain mask."""
        if self.brain_mask is None:
            return True

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

    def _get_parcel_weights(
        self, coord: tuple[float, float, float], radius: float
    ) -> dict[int, float]:
        """
        Get parcels within radius with Gaussian distance weighting.

        Returns:
            Dict mapping parcel index to weight
        """
        coord_array = np.array(coord).reshape(1, -1)

        # Calculate distances to all parcel centers
        distances = cdist(coord_array, self.parcel_centers, metric="euclidean")[0]

        # Find parcels within radius
        within_radius = distances <= radius

        if not np.any(within_radius):
            return {}

        # Calculate Gaussian weights
        sigma = self.gaussian_sigma
        if sigma <= 0:  # Use radius/3 as default
            sigma = radius / 3.0

        weights = np.exp(-(distances[within_radius] ** 2) / (2 * sigma**2))

        # Normalize weights to sum to 1
        weights = weights / weights.sum()

        # Create weight dictionary
        parcel_indices = np.where(within_radius)[0]
        parcel_weights = dict(zip(parcel_indices, weights, strict=False))

        return parcel_weights

    def _calculate_concept_scores(
        self, parcel_weights: dict[int, float], min_percentile: float
    ) -> dict[str, dict[str, Any]]:
        """
        Calculate concept scores from weighted parcels.

        Returns:
            Dict mapping concept name to score data
        """
        concept_scores = {}

        # For each task/concept
        for task_idx, task_name in enumerate(self.task_names):
            # Skip if no concept mapping
            if task_name not in self.task_to_concepts:
                continue

            # Calculate weighted average of brain-text alignment
            weighted_score = 0.0
            contributing_parcels = []

            for parcel_idx, weight in parcel_weights.items():
                if parcel_idx < len(self.brain_embeddings):
                    # Calculate cosine similarity
                    similarity = 1 - cosine(
                        self.brain_embeddings[parcel_idx],
                        self.text_embeddings[task_idx],
                    )

                    weighted_score += similarity * weight
                    contributing_parcels.append(
                        {
                            "parcel": (
                                self.parcel_names[parcel_idx]
                                if parcel_idx < len(self.parcel_names)
                                else f"Parcel_{parcel_idx}"
                            ),
                            "weight": weight,
                            "similarity": similarity,
                        }
                    )

            # Calculate percentile
            percentile = percentileofscore(self.score_distribution, weighted_score)

            # Skip if below minimum percentile
            if percentile < min_percentile:
                continue

            # Normalize score to 0-1 range based on percentiles
            if weighted_score >= self.percentiles["p95"]:
                normalized_score = 0.9 + 0.1 * (
                    weighted_score - self.percentiles["p95"]
                ) / (1.0 - self.percentiles["p95"])
            elif weighted_score >= self.percentiles["p90"]:
                normalized_score = 0.8 + 0.1 * (
                    weighted_score - self.percentiles["p90"]
                ) / (self.percentiles["p95"] - self.percentiles["p90"])
            elif weighted_score >= self.percentiles["p75"]:
                normalized_score = 0.6 + 0.2 * (
                    weighted_score - self.percentiles["p75"]
                ) / (self.percentiles["p90"] - self.percentiles["p75"])
            else:
                normalized_score = (
                    0.6
                    * (weighted_score - self.percentiles["p50"])
                    / (self.percentiles["p75"] - self.percentiles["p50"])
                )

            normalized_score = np.clip(normalized_score, 0.0, 1.0)

            # Add concepts associated with this task
            for concept in self.task_to_concepts[task_name]:
                if (
                    concept not in concept_scores
                    or normalized_score > concept_scores[concept]["score"]
                ):
                    concept_scores[concept] = {
                        "score": normalized_score,
                        "percentile": percentile,
                        "task": task_name,
                        "parcels": contributing_parcels[
                            :3
                        ],  # Top 3 contributing parcels
                    }

        return concept_scores

    def get_concept_embeddings(self, concept_names: list[str]) -> dict[str, np.ndarray]:
        """
        Get multi-dimensional embeddings for concepts.

        Args:
            concept_names: List of concept names

        Returns:
            Dict mapping concept name to embedding vector
        """
        embeddings = {}

        for concept in concept_names:
            # Find tasks associated with this concept
            associated_tasks = []
            for task, concepts in self.task_to_concepts.items():
                if concept in concepts:
                    associated_tasks.append(task)

            if not associated_tasks:
                # Use zero embedding if concept not found
                embeddings[concept] = np.zeros(self.text_embeddings.shape[1])
                continue

            # Average embeddings of associated tasks
            task_embeddings = []
            for task in associated_tasks:
                if task in self.task_names:
                    task_idx = list(self.task_names).index(task)
                    task_embeddings.append(self.text_embeddings[task_idx])

            if task_embeddings:
                embeddings[concept] = np.mean(task_embeddings, axis=0)
            else:
                embeddings[concept] = np.zeros(self.text_embeddings.shape[1])

        return embeddings


# Convenience function
def get_enhanced_mapper(
    atlas: str = "difumo512",
) -> EnhancedNiCLIPSpatialMapper | None:
    """Get or create enhanced spatial mapper instance."""
    try:
        return EnhancedNiCLIPSpatialMapper(atlas=atlas)
    except Exception as e:
        logger.error(f"Failed to create enhanced mapper: {e}")
        return None
