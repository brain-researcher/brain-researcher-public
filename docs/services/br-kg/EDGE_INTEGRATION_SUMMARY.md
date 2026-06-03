# BR-KG Edge Integration Summary

This document summarizes all the edge types (relationships) that have been integrated into BR-KG and how to create them in the knowledge graph.

## Overview

BR-KG now supports comprehensive relationship types across multiple categories:

1. **Evidence-Based Relationships** - Created from data analysis
2. **Dataset Relationships** - Links between datasets and their components
3. **Subject/Phenotype Relationships** - Clinical and demographic data
4. **Ontological Relationships** - Hierarchical and semantic relationships
5. **Cross-Source Mappings** - Links between equivalent entities
6. **Task Relationships** - Cognitive task associations

## Integrated Edge Types

### 1. Coordinate-Based Relationships

**Script**: `scripts/br-kg/integrate_coordinate_relationships.py`
**Loader**: `etl/loaders/neurosynth_relationship_loader.py`

- **HAS_COORDINATE**: Study → Coordinate
  - Links studies to their reported MNI coordinates
  - Created from NeuroSynth data

- **IN_REGION**: Coordinate → BrainRegion
  - Maps coordinates to anatomical brain regions
  - Uses MNI coordinate bounds for region mapping

- **ACTIVATES**: Concept/Task → BrainRegion
  - Evidence-based activation relationships
  - Created when multiple coordinates for a concept fall within a region
  - Includes activation strength and coordinate count

#### Spatial-Semantic Mapping Notes

Spatial-semantic mapping creates coordinate, region, and concept links without
turning proximity alone into cognitive evidence. The implementation has two
main surfaces:

- `scripts/br-kg/create_in_region_edges.py`
- `src/brain_researcher/services/br_kg/spatial/create_in_region_edges.py`

The runtime path maps coordinates to regions first, then uses curated or
model-derived evidence to attach cognitive concepts. Keep these stages
separate when adding new relationship types:

1. coordinate-to-region assignment (`IN_REGION`)
2. concept/task evidence rollup (`HAS_CONCEPT`, `MEASURES`, `ACTIVATES`)
3. strength calculation with provenance and source-specific confidence

### 2. Study-Concept Relationships

**Script**: `scripts/br-kg/integrate_study_concept_relationships.py`
**Loaders**:
- `etl/loaders/pubmed_relationship_loader.py`
- `etl/loaders/neurosynth_relationship_loader.py`

- **STUDIES**: Study → Concept
  - Strong relationship when study directly investigates a concept
  - Created from title matching and metadata

- **MENTIONS_CONCEPT**: Study → Concept
  - Weaker relationship for concept mentions in abstracts
  - Created from text analysis

- **CO_AUTHORED**: Study → Study
  - Links papers by the same first author
  - Enables author network analysis

### 3. Ontological Relationships

**Script**: `scripts/br-kg/integrate_ontology_relationships.py`
**Loader**: `etl/loaders/cognitive_atlas_relationships_loader.py`

- **IS_A**: Concept → Concept
  - Hierarchical relationships between concepts
  - Created from Cognitive Atlas ontology

- **MEASURES**: Task → Concept
  - Links cognitive tasks to concepts they measure
  - From Cognitive Atlas task definitions

- **PART_OF**: BrainRegion → BrainRegion
  - Anatomical hierarchy relationships
  - E.g., "hippocampus PART_OF temporal_lobe"

### 4. Statistical Map Relationships

**Script**: `scripts/br-kg/integrate_statistical_maps.py`
**Loader**: `etl/loaders/enhanced_neurovault_loader.py`

- **DERIVED_FROM**: StatMap → Contrast
  - Links statistical maps to their contrasts
  - Uses multiple matching methods with confidence scores

- **BELONGS_TO**: StatMap → Collection
  - Groups maps into collections

- **FROM_STUDY**: StatMap → Study
  - Links maps to their source studies via DOI

### 5. Subject-Level Relationships

**Script**: `scripts/br-kg/integrate_subject_relationships.py`
**Loader**: `etl/loaders/neurobagel_loader.py`

- **HAS_SUBJECT**: Dataset/Study → Subject
  - Links datasets/studies to their participants

- **HAS_PHENOTYPE**: Subject → Phenotype
  - Clinical and demographic information
  - Created from Neurobagel data

- **BELONGS_TO**: Subject → SubjectGroup
  - Groups subjects into cohorts

- **SAME_AS**: Subject → Subject
  - Links same subject across different sources

### 6. Dataset Relationships

**Built into loaders**

- **HAS_TASK**: Dataset → Task
- **HAS_CONTRAST**: Dataset → Contrast
- **HAS_CONCEPT**: Task → Concept
- **INVOLVES_CONSTRUCT**: Contrast → CognitiveConstruct

### 7. Cross-Source Mappings

**Loader**: `etl/mappers/cross_source_linker.py`

- **MAPS_TO**: Entity → Entity
  - Links equivalent entities across sources
  - E.g., NeuroSynth concept → Cognitive Atlas concept
  - Includes confidence scores

## How to Use

### Running Full Integration

To integrate all edge types into an existing database:

```bash
# 1. Coordinate relationships
python scripts/br-kg/integrate_coordinate_relationships.py --database path/to/db

# 2. Ontological relationships
python scripts/br-kg/integrate_ontology_relationships.py --database path/to/db

# 3. Study-concept relationships
python scripts/br-kg/integrate_study_concept_relationships.py --database path/to/db

# 4. Statistical map relationships
python scripts/br-kg/integrate_statistical_maps.py --database path/to/db

# 5. Subject-level relationships
python scripts/br-kg/integrate_subject_relationships.py --database path/to/db
```

### Initializing New Database

The `scripts/br-kg/init_database.py` script automatically integrates all relationship types when loading data:

```bash
# Full database with all relationships
python scripts/br-kg/init_database.py --full

# Resume loading if interrupted
python scripts/br-kg/init_database.py --resume
```

### Analyzing Coverage

Each integration script includes an `--analyze` flag to check current coverage:

```bash
python scripts/br-kg/integrate_coordinate_relationships.py --analyze
python scripts/br-kg/integrate_study_concept_relationships.py --analyze
# etc.
```

## Integration Architecture

1. **Modular Loaders**: Each relationship type has its own loader class
2. **Integration Scripts**: Standalone scripts for each relationship category
3. **Automatic Integration**: `init_database.py` calls all loaders in sequence
4. **Cross-Source Linking**: Automatic MAPS_TO relationships after each source load
5. **Dry Run Support**: All scripts support `--dry-run` to preview changes

## Key Features

- **Confidence Scoring**: Many relationships include confidence scores
- **Provenance Tracking**: Relationships track their creation method
- **Batch Processing**: Efficient handling of large datasets
- **Resume Support**: Can continue interrupted loading
- **Comprehensive Logging**: Detailed statistics and progress tracking

## Next Steps

All major edge types identified in BR-KG have been successfully integrated. The knowledge graph now supports:
- Coordinate-based neuroscience analysis
- Literature integration
- Ontological reasoning
- Statistical map analysis
- Subject-level phenotype analysis
- Cross-source entity mapping

Users can now query across all these relationship types to perform comprehensive neuroscience analyses.
