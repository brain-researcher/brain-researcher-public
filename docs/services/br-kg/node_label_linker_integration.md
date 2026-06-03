# NodeLabelLinker Integration Documentation

## Overview

This document describes the complete integration of NodeLabelLinker into the BR-KG system, providing automatic cross-source node linking capabilities through MAPS_TO relationships.

## Components Implemented

### 1. Core NodeLabelLinker Utility
**File**: `/services/br-kg/utils/node_label_linker.py`

A powerful utility for comparing node labels across sources using:
- Embedding-based similarity (sentence-transformers)
- Fuzzy string matching (RapidFuzz)
- FAISS indexing for efficient similarity search
- Hybrid matching combining multiple methods

Key features:
- `match_nodes()`: Find similar nodes between two sets
- `create_maps_to_edges()`: Create MAPS_TO relationships
- `link_nodes_by_label()`: Link nodes with similar labels
- Support for large-scale matching with FAISS optimization

### 2. Cross-Source Linker Module
**File**: `/services/br-kg/etl/mappers/cross_source_linker.py`

Centralized module for ETL pipeline integration:
- Predefined linking strategies for each data source
- Automatic duplicate detection and linking
- Configurable thresholds and matching rules
- Comprehensive statistics and reporting

Key strategies:
- Cognitive Atlas ↔ NeuroSynth concept mapping
- Task to TaskDef mapping across sources
- Brain region cross-referencing
- Dataset and contrast deduplication

### 3. Duplicate Node Linking Script
**File**: `/scripts/br-kg/link_duplicate_nodes.py`

One-time cleanup script for existing duplicates:
- Identifies and links duplicate nodes (Concept/CognitiveConstruct, Dataset/OpenNeuro, etc.)
- Successfully created 410 MAPS_TO relationships in testing
- Generates detailed reports
- Supports dry-run mode for preview

### 4. ETL Pipeline Integration

#### a. Main Database Initialization
**File**: `/scripts/br-kg/init_database.py`

Added automatic cross-source linking after loading each data source:
- Cognitive Atlas
- NeuroSynth
- WikiData
- NeuroVault
- Neurobagel

#### b. OpenNeuro Batch Loader
**File**: `/services/br-kg/etl/load_all_openneuro_datasets.py`

Integrated cross-source linking for batch OpenNeuro dataset loading.

#### c. Individual ETL Scripts
- `/scripts/br-kg/load_glmfitlins_to_kg.py`
- `/scripts/br-kg/load_openneuro_fitlins.py`

### 5. Scheduled Linking Job
**File**: `/scripts/br-kg/scheduled_cross_linker.py`

Automated job for periodic cross-source linking:
- Finds unmapped nodes
- Attempts to create new links
- Runs standard linking strategies
- Generates comprehensive reports
- Can be scheduled via cron

**Setup Script**: `/scripts/br-kg/setup_cron_linker.sh`
- Interactive cron job setup
- Configurable frequency (daily, weekly, hourly)
- Automatic directory creation
- Log rotation support

### 5b. TTL Cleanup Job (On-Demand Edge Hygiene)
**File**: `/scripts/br-kg/ttl_edge_cleanup.py`

Removes expired `IN_REGION` edges written by on-demand pipelines (e.g., Neurosynth term decodes).

Key behaviors:
- Counts pending expirations and deletes them in batches
- Targets edges by `atlas` (default `yeo17`) and `edge_source` (default `neurosynth`)
- Supports dry-run mode for CI/ops verification

**Setup Script**: `/scripts/br-kg/setup_cron_ttl_cleanup.sh`
- Adds a cron entry (hourly/daily/weekly) for the cleanup job
- Defaults to daily 03:15 server time (modifiable during prompts)
- Logs to `logs/ttl_cleanup/cron.log`

### 6. UI Components for Mapping Review

#### a. Mapping Review API
**File**: `/services/br-kg/api/mapping_review_api.py`

Flask Blueprint providing REST endpoints:
- `GET /api/mapping-review/mappings` - List and filter mappings
- `DELETE /api/mapping-review/mappings/<id>` - Delete mapping
- `POST /api/mapping-review/mappings/<id>/approve` - Approve mapping
- `GET /api/mapping-review/mappings/stats` - Get statistics
- `POST /api/mapping-review/mappings/bulk-action` - Bulk operations

Features:
- Filtering by confidence, method, labels
- Pagination support
- Sorting capabilities
- Bulk approval/deletion

#### b. Web UI
**File**: `/services/br-kg/ui/mapping_review.html`

Interactive web interface for reviewing MAPS_TO relationships:
- Real-time statistics dashboard
- Advanced filtering options
- Sortable table view
- Individual approval/deletion
- Bulk operations support
- Responsive design

Access via: `http://localhost:<port>/mapping-review`

## Usage Examples

### 1. Run One-Time Duplicate Cleanup
```bash
python scripts/br-kg/link_duplicate_nodes.py --database data/br-kg/db/br-kg_full.db
```

### 2. Initialize Database with Auto-Linking
```bash
python scripts/br-kg/init_database.py --full
```

### 3. Setup Scheduled Linking
```bash
./scripts/br-kg/setup_cron_linker.sh
# Follow interactive prompts
```

### 4. Manual Cross-Source Linking
```python
from graph.graph_database import BR-KGGraphDB
from etl.mappers.cross_source_linker import CrossSourceLinker

db = BR-KGGraphDB("path/to/db")
linker = CrossSourceLinker(db)

# Link after loading a source
links_created = linker.link_after_source_load("cognitive_atlas")

# Custom linking
linker.link_specific_nodes(
    source_label="Concept",
    target_label="CognitiveConstruct",
    threshold=0.90
)
```

### 5. Review Mappings via API
```bash
# Get all high-confidence mappings
curl "http://localhost:5000/api/mapping-review/mappings?confidence_min=0.9"

# Approve a mapping
curl -X POST "http://localhost:5000/api/mapping-review/mappings/node1->node2/approve"
```

## Integration Points

1. **Database Schema**: MAPS_TO relationships include:
   - `confidence`: Similarity score (0-1)
   - `method`: Matching method used (embedding, fuzzy, exact)
   - `created_by`: Component that created the link
   - `timestamp`: Creation time
   - Additional metadata

2. **ETL Workflows**: Automatic linking triggered after:
   - Data source loading
   - Batch processing
   - Manual imports

3. **API Integration**: Mapping review endpoints integrated into main Flask app

## Benefits

1. **Automatic Deduplication**: Reduces redundant nodes across sources
2. **Cross-Source Integration**: Enables queries across different ontologies
3. **Quality Control**: Review interface for manual validation
4. **Scalability**: FAISS indexing handles large datasets efficiently
5. **Flexibility**: Configurable thresholds and strategies per source

## Future Enhancements

1. Machine learning-based confidence scoring
2. User feedback integration for improving matches
3. Real-time linking during data ingestion
4. Graph visualization of MAPS_TO relationships
5. Export functionality for mapping validation

## Summary

The NodeLabelLinker integration provides a comprehensive solution for cross-source node linking in BR-KG. With automatic linking during ETL, scheduled maintenance jobs, and interactive review tools, the system maintains high-quality cross-references between different neuroscience ontologies and databases.
