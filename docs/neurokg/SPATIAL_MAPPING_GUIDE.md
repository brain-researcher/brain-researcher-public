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