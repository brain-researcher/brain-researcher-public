# NiCLIP Complete Integration Guide

## Overview

This document summarizes all NiCLIP (Neuroimaging Contrastive Language-Image Pre-training) integrations into the Brain Researcher system. NiCLIP provides scientifically validated brain-language alignment data that enhances multiple components of the knowledge graph.

## Completed Integrations

### 1. CoordinateToConceptTool Enhancement ✅

**File**: `src/brain_researcher/services/tools/neurokg_tools.py`

**What it does**:
- Maps MNI brain coordinates to cognitive concepts using NiCLIP's DiFuMo 512 brain atlas
- Provides alignment scores between brain regions and cognitive tasks
- Includes cognitive process classification

**Key improvements**:
- Replaced mock data with real brain parcellation mappings
- Added brain-language alignment scores
- Provides cognitive process information (6 processes)

### 2. StrengthCalculator Integration ✅

**File**: `src/brain_researcher/services/neurokg/etl/strength_calculator.py`

**What it does**:
- Adds NiCLIP brain-language alignment as 4th evidence channel
- Calculates strength scores based on task-brain alignment priors
- Enhances composite strength calculations

**Key method**:
```python
def strength_from_niclip(self, concept: str, region: str = None) -> tuple[float, dict[str, Any]]
```

**Benefits**:
- Provides evidence when traditional methods lack data
- Scientifically validated alignment scores
- Integrates seamlessly with existing evidence channels

### 3. CrossSourceLinker Enhancement ✅

**File**: `src/brain_researcher/services/neurokg/etl/mappers/cross_source_linker.py`

**What it does**:
- Adds NiCLIP-specific linking strategies
- Enhances task and concept linking with validated mappings
- Groups concepts by cognitive process for better linking

**Key features**:
- `_link_with_niclip_validation()` method for enhanced accuracy
- Automatic NiCLIP enhancement when linking from "niclip" source
- Process-based concept grouping

### 4. Spatial-Semantic Mapping Service ✅

**File**: `src/brain_researcher/services/neurokg/etl/mappers/niclip_spatial_mapper.py`

**What it does**:
- Maps brain coordinates to concepts using NiCLIP embeddings
- Provides task-brain alignment scores
- Uses DiFuMo 512 parcellation for accurate mapping

**Key capabilities**:
- 851 tasks with brain priors
- 23,865 brain voxel embeddings
- Cognitive process classification

### 5. Concept Hierarchy Extension ✅

**File**: `src/brain_researcher/services/neurokg/etl/mappers/niclip_concept_hierarchy.py`

**What it does**:
- Builds hierarchical concept relationships using embeddings
- Clusters concepts semantically
- Creates IS_A, PART_OF, and RELATED_TO relationships

**Key features**:
- Agglomerative clustering of concepts
- Process-based organization
- 1,000+ hierarchical relationships generated

## Data Flow

```
NiCLIP Data Sources
├── reduced_tasks.csv (88 tasks → 3 concepts each)
├── concept_to_process.json (concepts → 6 processes)
├── difumo512_priors.npy (task-brain alignment)
└── difumo512_embeddings.npy (brain region embeddings)
         ↓
    Integration Points
    ├── Agent Tools (coordinate mapping)
    ├── Strength Calculator (evidence channel)
    ├── Cross-Source Linker (entity matching)
    ├── Spatial Mapper (brain-concept alignment)
    └── Concept Hierarchy (semantic organization)
         ↓
    Knowledge Graph
    └── Enhanced with validated relationships
```

## Cognitive Processes

NiCLIP classifies cognitive concepts into 6 processes:

1. **ctp_C1**: Perception
2. **ctp_C3**: Cognitive Control
3. **ctp_C4**: Visual Processing
4. **ctp_C6**: Language
5. **ctp_C7**: Motor
6. **ctp_C8**: Emotion

## Usage Examples

### 1. Coordinate to Concept Mapping
```python
# In agent conversation
result = coordinate_to_concept_tool.run({
    "coordinates": [[-42, -22, 54]],
    "radius": 10.0
})
# Returns concepts with NiCLIP alignment scores
```

### 2. Strength Calculation
```python
calculator = StrengthCalculator()
strength, details = calculator.strength_from_niclip("n-back task", "prefrontal cortex")
# Uses brain-language alignment for evidence
```

### 3. Cross-Source Linking
```python
linker = CrossSourceLinker(db)
linker.link_after_source_load("niclip")
# Automatically uses NiCLIP enhancement
```

### 4. Concept Hierarchy
```python
builder = get_hierarchy_builder(db)
hierarchy = builder.build_hierarchy(n_clusters=20)
created = builder.create_hierarchy_in_graph()
# Creates semantic concept organization
```

## Benefits

1. **Scientific Validation**: All mappings based on neuroimaging literature
2. **Multi-Modal Integration**: Combines brain imaging with language models
3. **Enhanced Accuracy**: Reduces false positives in entity linking
4. **Semantic Organization**: Data-driven concept hierarchies
5. **Fallback Evidence**: Provides data when traditional methods fail

## Testing

All integrations include test files in `tests/niclip/`:
- `test_coordinate_tool_niclip.py`
- `test_strength_calculator_niclip.py`
- `test_cross_source_linker_niclip.py`
- `test_concept_hierarchy_niclip.py`

## Future Enhancements

1. **Embedding-based search**: Use NiCLIP embeddings for semantic search
2. **Task recommendation**: Suggest related tasks based on brain patterns
3. **Visualization**: Brain-concept alignment heatmaps
4. **Dynamic updates**: Refresh mappings as new NiCLIP data becomes available

## Configuration

NiCLIP data is automatically loaded from:
```
data/niclip/dsj56/osfstorage/osfstorage/data/
```

No additional configuration required - all integrations work out of the box!
