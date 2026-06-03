# NiCLIP Integration Features

This document describes the two major features implemented for integrating NiCLIP (Neuroimaging-to-Cognitive-Mapping with Language-Image Pretraining) data into the BR-KG knowledge graph.

## Runtime Surfaces

NiCLIP is treated as an in-process BR-KG capability by default. The preferred
entrypoints are the CLI and the knowledge-layer loaders:

```bash
br niclip health
br niclip encode "working memory"
br niclip search "working memory"
```

The optional HTTP prediction app is an internal development surface and is not
started by default:

```bash
python -m uvicorn brain_researcher.services.br_kg.niclip.prediction_service:app --host 0.0.0.0 --port 8001
```

## Implementation References

The current integration spans these runtime modules:

- `src/brain_researcher/services/tools/br_kg_tools.py`
- `src/brain_researcher/services/br_kg/etl/strength_calculator.py`
- `src/brain_researcher/services/br_kg/etl/mappers/cross_source_linker.py`
- `src/brain_researcher/services/br_kg/etl/mappers/niclip_spatial_mapper.py`
- `src/brain_researcher/services/br_kg/etl/mappers/niclip_concept_hierarchy.py`

Relationship strengths should remain provenance-aware and calibrated by source
type. Treat simple geometric overlap, task-concept priors, and LLM semantic
fusion as distinct evidence channels rather than interchangeable scores.

## Feature 1: TaskSpec to TaskDef Mapping

### Overview
Maps TaskSpec nodes (from OpenNeuro datasets) to TaskDef nodes (from Cognitive Atlas) using multiple matching strategies enhanced by NiCLIP synonym data.

### Components

1. **Configuration** (`config/task_mapping.yaml`)
   - Defines thresholds for fuzzy matching (0.8) and NiCLIP confidence (0.7)
   - Maintains blacklist of non-task terms (test, demo, practice, etc.)
   - Specifies task name normalization rules

2. **NiCLIP Synonym Extractor** (`utils/niclip_synonyms.py`)
   - Extracts task synonyms from NiCLIP vocabulary files
   - Builds comprehensive synonym dictionary with 810 tasks and 3233 variants
   - Includes confidence scores and prior probabilities

3. **Task Mapper** (`etl/mappers/task_mapper.py`)
   - Implements three-tier matching strategy:
     - **Exact matching**: Direct name matches after normalization
     - **Fuzzy matching**: String similarity using fuzzywuzzy (threshold: 80%)
     - **NiCLIP matching**: Synonym-based matching with confidence scores
   - Tracks detailed statistics and logs unmatched tasks

### Usage Example
```python
from etl.mappers.task_mapper import TaskMapper

# Initialize mapper
mapper = TaskMapper()

# Set available TaskDef nodes from database
mapper.set_task_definitions(task_def_nodes)

# Map a TaskSpec
result = mapper.map_task("n-back")
# Returns: {'task_def_id': 'task_001', 'match_type': 'exact', 'confidence': 1.0}

# Create MAPS_TO relationship in graph
db.create_relationship(task_spec_id, result['task_def_id'], 'MAPS_TO', {
    'match_type': result['match_type'],
    'confidence': result['confidence']
})
```

### Benefits
- Automatically links experimental tasks to standardized cognitive concepts
- Handles variations in task naming conventions
- Provides confidence scores for mapping quality
- Reduces manual curation effort

## Feature 2: Contrast to Concept Edge Rollup

### Overview
Creates HAS_CONCEPT edges between Contrast nodes and Concept nodes by aggregating evidence from NiCLIP's reduced task-concept mappings.

### Components

1. **NiCLIP Concept Extractor** (`utils/niclip_concept_extractor.py`)
   - Extracts concept frequencies from Cognitive Atlas data
   - Builds weight prior dictionary for concept importance
   - Integrates multiple evidence sources (vocabulary priors, co-occurrence data)

2. **Contrast-Concept Linker** (`etl/mappers/contrast_concept_linker.py`)
   - Uses NiCLIP's `reduced_tasks.csv` mapping 88 tasks to top 3 concepts each
   - Implements weight aggregation algorithm:
     - Top concept: weight 0.5
     - Second concept: weight 0.3
     - Third concept: weight 0.2
   - Supports GLM weight integration for future enhancements

### Usage Example
```python
from etl.mappers.contrast_concept_linker import ContrastConceptLinker

# Initialize linker
linker = ContrastConceptLinker()

# Link a single contrast
contrast_data = {
    'name': 'nback_2back_vs_0back',
    'task_name': 'n-back task'
}
edges = linker.link_contrast_to_concepts(contrast_id, contrast_data, concept_nodes)

# Creates edges like:
# Contrast(nback_2back_vs_0back) -[HAS_CONCEPT {weight: 1.0}]-> Concept(working_memory)
# Contrast(nback_2back_vs_0back) -[HAS_CONCEPT {weight: 0.6}]-> Concept(executive_control)
```

### Weight Aggregation Process
1. Extract task information from contrast (task_name, task_label, or parse from contrast name)
2. Look up task in NiCLIP reduced_tasks.csv to find top 3 associated concepts
3. Assign decreasing weights to concepts based on ranking
4. Normalize weights to 0-1 range
5. Filter by minimum weight threshold (default: 0.1)

### Benefits
- Automatically enriches contrasts with cognitive concept annotations
- Leverages expert-curated task-concept mappings from NiCLIP
- Provides weighted relationships for downstream analysis
- Enables concept-based queries across studies

## Integration Workflow

The complete integration workflow (`etl/integrate_niclip_mappings.py`) demonstrates:

1. Loading Cognitive Atlas concepts and tasks
2. Loading OpenNeuro datasets with TaskSpec and Contrast nodes
3. Mapping TaskSpecs to TaskDefs using NiCLIP synonyms
4. Creating HAS_CONCEPT edges from Contrasts to Concepts
5. Generating comprehensive statistics and logs

### Example Output
```
=== Step 3: Mapping TaskSpecs to TaskDefs ===
Mapped 'nback' -> TaskDef (exact, confidence: 1.00)
Mapped 'stroop_task' -> TaskDef (fuzzy, confidence: 0.85)
Created 25 TaskSpec->TaskDef mappings

Task Mapping Summary:
--------------------
Total processed: 30
Successfully mapped: 25 (83.3%)
  - Exact matches: 10
  - Fuzzy matches: 12
  - NiCLIP matches: 3
Unmatched: 5 (16.7%)

=== Step 4: Linking Contrasts to Concepts ===
Created 150 Contrast->Concept edges

Contrast-Concept Linking Summary:
--------------------------------
Total contrasts processed: 50
Contrasts with concepts: 45 (90.0%)
Total HAS_CONCEPT edges: 150
Average concepts per contrast: 3.3
```

## Testing

Both features include comprehensive unit tests:

- `tests/test_task_mapper.py`: 10 test cases covering all matching strategies
- `tests/test_contrast_concept_linker.py`: 9 test cases for weight aggregation

Run tests with:
```bash
python -m pytest tests/test_task_mapper.py -v
python -m pytest tests/test_contrast_concept_linker.py -v
```

## Future Enhancements

1. **Semantic Embedding Matching**: Use NiCLIP's learned embeddings for more sophisticated task matching
2. **GLM Weight Integration**: Incorporate actual GLM beta weights from neuroimaging analyses
3. **Confidence Calibration**: Learn optimal confidence thresholds from manual validation data
4. **Cross-Dataset Harmonization**: Extend mappings to handle dataset-specific task variations
