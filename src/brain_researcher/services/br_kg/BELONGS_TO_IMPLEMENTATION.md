# BELONGS_TO Relationship Implementation Summary

## Overview
This document summarizes the implementation of the BELONGS_TO relationship feature that links contrasts to their associated publications in the BR-KG system.

## Implementation Details

### 1. Files Modified

#### a. `etl/loaders/openneuro_loader/fitlins_loader.py`
- Added publication node creation in `_load_task()` method
- Extracts DOI from `cite_links` in task metadata
- Creates or finds existing Study nodes based on DOI
- Updated `_load_contrast()` to accept optional `publication_node_id` parameter
- Creates BELONGS_TO relationships from contrasts to publications

#### b. `etl/load_all_openneuro_datasets.py`
- Similar changes to fitlins_loader.py
- Added Optional import for type hints
- Fixed indentation issues
- Creates Study nodes and BELONGS_TO relationships

#### c. `etl/glmfitlins_ingest/load_to_br_kg.py`
- Added `dataset_publications` dictionary to track publications per dataset
- Creates Study nodes from DOI in task metadata
- Links all contrasts in a dataset to the same publication

### 2. Key Improvements Made

1. **Standardized Node Labels**: Using "Study" instead of "Publication" to match existing codebase conventions
2. **Error Handling**: Added try-catch blocks around publication node creation with appropriate logging
3. **Node Reuse**: Checks for existing Study nodes before creating new ones to avoid duplicates
4. **Optional Relationships**: BELONGS_TO relationships are only created when a publication/DOI exists

### 3. Graph Structure
```
Contrast --[BELONGS_TO]--> Study (publication)
```

### 4. Test Coverage

#### `tests/test_fitlins_loader_publication.py`
- Tests basic BELONGS_TO relationship creation
- Tests handling of missing DOIs
- Tests reuse of existing publication nodes
- Tests multiple contrasts linking to same publication

#### `tests/test_glmfitlins_load_to_br_kg.py`
- Tests the glmfitlins_ingest implementation
- Verifies CSV-based loading creates proper relationships

All 6 tests passing.

### 5. Query Examples Updated

Both `query_br_kg_examples.py` and `query_br_kg_fixed.py` have been updated with examples showing how to query BELONGS_TO relationships:

```python
# Find all BELONGS_TO relationships
belongs_rels = db.find_relationships(rel_type="BELONGS_TO")
for rel in belongs_rels[:5]:
    contrast = db.get_node(rel[0])
    pub = db.get_node(rel[1])
    print(f"{contrast.get('name')} -> {pub.get('doi', pub.get('title'))}")
```

## Usage

### When Loading OpenNeuro Datasets
The loaders automatically:
1. Extract DOI from `cite_links` in task metadata
2. Create or find Study nodes
3. Link contrasts to their associated publications

### Manual Creation
```python
# Create or find publication
pub_node = db.create_node("Study", {"doi": "10.1234/example", "title": "Example Study"})

# Create contrast
contrast_node = db.create_node("Contrast", {"name": "contrast1"})

# Create relationship
db.create_relationship(contrast_node, pub_node, "BELONGS_TO")
```

## Future Enhancements

1. **Enhanced DOI Extraction**: Currently only takes first DOI from first task. Could collect all unique DOIs per dataset.
2. **Publication Metadata**: Could fetch additional metadata (title, authors, year) from DOI APIs
3. **Multiple Publications**: Support datasets that cite multiple publications
4. **Validation**: Add DOI format validation before creating nodes
