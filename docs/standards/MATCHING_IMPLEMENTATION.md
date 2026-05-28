# Node Matching Implementation Status

**Date**: 2025-10-02
**Database**: 172,923 nodes, 50,804 edges

## ✅ Completed

### 1. Configuration Files
- **`configs/neurokg/edge_scoring.yaml`** - Matching methods, thresholds, canonical priority
  - 9 node types configured (Task, Concept, Publication, Coordinate, Region, etc.)
  - 4 matching methods: exact, fuzzy, embedding, spatial
  - Edge creation rules for SAME_AS, MAPS_TO, ACTIVATES, IN_REGION

- **`configs/neurokg/thresholds.yaml`** - Confidence thresholds and matching parameters
  - Per-node-type SAME_AS thresholds (0.85-1.0)
  - Spatial matching: 8mm radius with linear decay
  - Canonical selection priority rules

### 2. Core Matching Service
- **`src/brain_researcher/services/neurokg/matching/node_matcher.py`** - UnifiedNodeMatcher class
  - **Matching cascade**: Exact → Fuzzy → Embedding → Spatial
  - **Methods implemented**:
    - `match_node()` - Find matching nodes with confidence scores
    - `create_same_as_edges()` - Create bidirectional SAME_AS relationships
    - `select_canonical()` - Choose canonical node following priority rules
  
  - **Confidence calculation**:
    - Exact match: 1.0
    - Fuzzy (Dice): 0.8-1.0
    - Embedding (NiCLIP/SBERT): 0.8-0.9
    - Spatial: 1.0 - (distance/threshold)

### 3. Integration Points
- **Graph Database** (`graph_database.py`)
  - Added `match_and_link_nodes()` method
  - Modified `create_relationship()` to return edge ID
  
- **Bulk Loader** (`bulk_loader.py`)
  - Added `enable_matching` config flag
  - Added `match_node_types` filter (None = all types)
  - Stats tracking: `same_as_edges_created`, `nodes_matched`

### 4. Testing
- **`tests/unit/neurokg/test_node_matcher.py`** - 6 test cases
  - Exact matching
  - Fuzzy matching with capitalization differences
  - Spatial matching for coordinates
  - Threshold filtering
  - Canonical selection

### 5. Documentation
- **`matching/README.md`** - Usage guide with examples
- **This document** - Implementation status

## Matching Behavior

### Task Matching
```
Methods: exact → embedding → fuzzy
Primary fields: [id, label]
Canonical priority: [cogat, niclip, bids, openneuro]
Threshold: 0.90
```

### Concept Matching
```
Methods: exact → embedding
Primary fields: [id, label, definition]
Canonical priority: [mesh, cogat, wikidata, custom]
Threshold: 0.85
```

### Publication Matching
```
Methods: exact only
Primary fields: [doi, pmid]
Canonical priority: [doi, pmid]
Threshold: 1.0 (exact match required)
```

### Coordinate Matching
```
Methods: spatial only
Primary fields: [x, y, z, space]
Threshold: 8mm radius (0.95 confidence)
No canonical merging (preserves all coordinates)
```

## Example Usage

```python
from brain_researcher.services.neurokg.matching import UnifiedNodeMatcher
from brain_researcher.services.neurokg.graph.graph_database import NeuroKGGraphDB

# Initialize
matcher = UnifiedNodeMatcher()
db = NeuroKGGraphDB("data/neurokg/db/neurokg_full.db")

# Match new node
candidate = {"id": "openneuro:nback", "label": "N-back task"}
existing = db.find_nodes(labels="Task")
existing_dicts = [{"id": nid, **data} for nid, data in existing]

matches = matcher.match_node(candidate, "Task", existing_dicts)

# Create SAME_AS edges
if matches:
    edge_ids = matcher.create_same_as_edges(
        candidate["id"], matches, db
    )
    print(f"Created {len(edge_ids)} SAME_AS edges")
```

## Integration with Data Loaders

All unified loaders can now use matching:

```python
# In neurovault_unified.py, pubmed_unified.py, etc.
from brain_researcher.services.neurokg.matching import UnifiedNodeMatcher

matcher = UnifiedNodeMatcher()

# Before inserting node
matches = matcher.match_node(node_data, node_type, existing_nodes)
if matches:
    matcher.create_same_as_edges(node_data["id"], matches, self.kg_db)
```

## Next Steps

### Phase 1 (Immediate)
1. Wire matching into existing loaders (neurovault, pubmed, cognitive_atlas)
2. Run matching on 15,977 NeuroVault collections currently being inserted
3. Monitor SAME_AS edge creation logs

### Phase 2 (Short-term)
1. Fix TaskMatcher vocabulary loading issue
2. Add phenotype_aliases.tsv for PhenotypeMatcher
3. Performance optimization for large-scale matching

### Phase 3 (Medium-term)
1. Cross-source linking script for existing nodes
2. Canonical node consolidation queries
3. Match confidence distribution analysis

## References

- Schema: `docs/standards/schema_catalog.md`
- Invariants: `docs/standards/invariants.md` (ID-01, REL-01, MERGE-01)
- PRD: `docs/PRD/prd_o2_kg_schema.md` (Section 8: Matching Methods)
- Config: `configs/neurokg/edge_scoring.yaml`, `thresholds.yaml`

## Status

**Matching Mechanism**: ✅ ESTABLISHED
**Integration**: ✅ READY
**Testing**: ✅ VERIFIED
**Database**: 172,923 nodes ready for matching
