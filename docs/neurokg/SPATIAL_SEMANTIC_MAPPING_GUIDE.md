# Spatial-Semantic Mapping Implementation Guide

This guide documents the implementation of spatial-semantic mapping in BR-KG, which creates relationships between neuroimaging coordinates, brain regions, and cognitive concepts.

## Overview

The spatial-semantic mapping consists of three main components:

1. **Coordinate to Region Mapping** - Maps neuroimaging coordinates to brain regions using spatial proximity
2. **NiCLIP Integration** - Loads concept-brain region associations from NiCLIP models
3. **Strength Calculation** - Computes evidence-based relationship strengths for UI visualization

## Implementation Details

### 1. Coordinate to Region Mapping (IN_REGION edges)

**CLI**: `scripts/neurokg/create_in_region_edges.py`  
**Runtime**: `src/brain_researcher/services/neurokg/spatial/create_in_region_edges.py`

This script creates `IN_REGION` relationships between `Coordinate` nodes and `BrainRegion` nodes based on spatial proximity.

#### Features:
- Uses configurable search radius (default: 10mm)
- Supports multiple brain atlases (MNI, Talairach, AAL, etc.)
- Calculates confidence scores based on distance
- Validates coordinates before processing
- Batch processing for large datasets

#### Usage:
```bash
# Test with 100 coordinates
python scripts/neurokg/create_in_region_edges.py \
    --limit 100 \
    --test-mode

# Full run with MNI atlas
python scripts/neurokg/create_in_region_edges.py \
    --atlas MNI \
    --radius 10.0 \
    --batch-size 1000
```

#### Edge Properties:
- `distance_mm`: Euclidean distance from coordinate to region centroid
- `confidence`: Confidence score (1.0 at center, decreases with distance)
- `atlas`: Atlas used for mapping
- `region_name`: Name of the brain region
- `method`: Always "spatial_proximity"

### 2. NiCLIP Integration (ACTIVATES edges)

**Script**: `src/brain_researcher/services/neurokg/etl/loaders/niclip_loader.py`

This loader creates `ACTIVATES` relationships between `Concept` nodes and
`BrainRegion` nodes using NiCLIP prior files plus the current loader's
heuristic concept-region association builder.

#### Features:
- Supports multiple NiCLIP model names and section-specific prior files
- Configurable weight threshold for edge creation
- Uses concept-task mappings from Cognitive Atlas
- Current implementation builds proxy associations from priors +
  `reduced_tasks.csv`; direct model-weight extraction is still future work

#### Usage:
```bash
# Test mode with BrainGPT model
python -m brain_researcher.services.neurokg.etl.loaders.niclip_loader \
    --model BrainGPT-7B-v0.0 \
    --section abstract \
    --weight-threshold 0.3 \
    --test-mode

# Full run
python -m brain_researcher.services.neurokg.etl.loaders.niclip_loader \
    --model BrainGPT-7B-v0.0 \
    --section abstract \
    --weight-threshold 0.3
```

#### Edge Properties:
- `weight`: Proxy association strength produced by the current loader
- `model`: Model name used (e.g., "BrainGPT-7B-v0.0")
- `section`: Text section used (abstract/body)
- `method`: Always "niclip"
- `source`: Always "niclip_loader"

### 3. Strength Calculator

**CLI**: `scripts/neurokg/calculate_strength.py`  
**Runtime**: `src/brain_researcher/services/neurokg/scoring/calculate_strength.py`

The existing StrengthCalculator can process the new edge types to compute evidence-based strengths.

#### Usage:
```bash
# Run strength calculation
python scripts/neurokg/calculate_strength.py "working memory" "DLPFC"
```

## Testing

An integration test module is provided to verify the implementation.
Set `RUN_SPATIAL_SEMANTIC_MAPPING=1` plus `NEO4J_URI` /
`NEO4J_PASSWORD` before running it:

**Script**: `tests/integration/mappers/test_spatial_semantic_mapping.py`

```bash
# Test all components
RUN_SPATIAL_SEMANTIC_MAPPING=1 \
python tests/integration/mappers/test_spatial_semantic_mapping.py --test all

# Test only coordinate mapping with 50 coordinates
RUN_SPATIAL_SEMANTIC_MAPPING=1 \
python tests/integration/mappers/test_spatial_semantic_mapping.py --test coord --coord-limit 50

# Test only NiCLIP integration
RUN_SPATIAL_SEMANTIC_MAPPING=1 \
python tests/integration/mappers/test_spatial_semantic_mapping.py --test niclip

# Test strength calculator
RUN_SPATIAL_SEMANTIC_MAPPING=1 \
python tests/integration/mappers/test_spatial_semantic_mapping.py --test strength
```

## Data Setup

### NiCLIP Data
The NiCLIP data is accessed via symlink:
```bash
ln -s /data/ECoG-foundation-model/mnndl_temp/niclip/osf_data data/niclip
```

### Required Node Types
Ensure your database contains:
- `Coordinate` nodes with x, y, z properties
- `BrainRegion` nodes with name/label properties
- `Concept` nodes from Cognitive Atlas

## Performance Considerations

### Coordinate Mapping
- Processing 40,000+ coordinates can take time
- Use batch processing (default: 1000 per batch)
- Consider using `--limit` for initial testing

### NiCLIP Integration
- Current loader uses prior CSVs plus heuristic synthetic associations
- Direct trained-weight extraction is not implemented yet
- Weight threshold affects how many proxy `ACTIVATES` edges are created

## Troubleshooting

### Missing Brain Regions
If coordinates don't map to regions:
1. Check that BrainRegion nodes exist in database
2. Verify region names match atlas definitions
3. Consider increasing search radius

### Missing Concepts
If NiCLIP concepts aren't found:
1. Ensure Cognitive Atlas concepts are loaded
2. Check concept name variations (lowercase matching)
3. Verify reduced_tasks.csv exists in NiCLIP data

### Database Path Issues
Always use absolute paths or ensure working directory is correct:
```bash
cd /path/to/brain_researcher
python scripts/neurokg/create_in_region_edges.py
```

## Next Steps

After running the spatial-semantic mapping:

1. **Verify edges in database**:
   ```python
   db.find_relationships(rel_type="IN_REGION", limit=10)
   db.find_relationships(rel_type="ACTIVATES", limit=10)
   ```

2. **Run strength calculator** to update UI visualization

3. **Check the Web UI** at http://localhost:3000/en/kg/explore to see:
   - Updated relationship counts
   - New edge types in graph view
   - Strength values in concept/region displays

## Architecture Notes

The implementation follows BR-KG patterns:
- Modular loaders in `src/brain_researcher/services/neurokg/etl/loaders/`
- CLI wrappers in `scripts/neurokg/`
- Spatial runtime helpers in `src/brain_researcher/services/neurokg/spatial/`
- Edge properties follow consistent schema
- Statistics tracking for monitoring

## Future Enhancements

1. **Real NiCLIP Model Integration**:
   - Load actual PyTorch model weights
   - Extract learned concept-region associations
   - Support for multiple model architectures

2. **Advanced Spatial Mapping**:
   - Probabilistic region assignment
   - Multiple atlas support per coordinate
   - Volume-based (not just centroid) mapping

3. **Batch Processing Optimization**:
   - Parallel processing for coordinates
   - GPU acceleration for model inference
   - Incremental updates for new data
