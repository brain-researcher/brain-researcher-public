# Node Matching and Entity Resolution

This module implements the node matching mechanism for BR-KG, creating `SAME_AS` edges between equivalent nodes from different sources.

## Quick Start

```python
from brain_researcher.services.neurokg.matching import UnifiedNodeMatcher
from brain_researcher.services.neurokg.graph.graph_database import NeuroKGGraphDB

# Initialize
matcher = UnifiedNodeMatcher()
db = NeuroKGGraphDB("data/neurokg/db/neurokg_full.db")

# Match a new node
candidate = {
    "id": "openneuro:nback",
    "label": "n-back working memory task",
    "description": "2-back variant"
}

# Get existing nodes of same type
existing = db.find_nodes(labels="Task")
existing_dicts = [{"id": nid, **data} for nid, data in existing]

# Find matches
matches = matcher.match_node(candidate, "Task", existing_dicts)

# Create SAME_AS edges for high-confidence matches
if matches:
    edge_ids = matcher.create_same_as_edges(candidate["id"], matches, db)
    print(f"Created {len(edge_ids)} SAME_AS edges")
```

## Configuration

Matching behavior is configured in:
- `configs/neurokg/edge_scoring.yaml` - Methods and thresholds per node type
- `configs/neurokg/thresholds.yaml` - SAME_AS confidence thresholds

### Node Type Configs

Each node type has:
- **methods**: Matching algorithms to apply (exact, fuzzy, embedding, spatial)
- **primary_fields**: Fields used for matching
- **canonical_priority**: Source priority for canonical node selection
- **same_as_threshold**: Minimum confidence for SAME_AS edge creation

Example:
```yaml
Task:
  methods: [exact, embedding, fuzzy]
  primary_fields: [id, label]
  canonical_priority: [cogat, niclip, bids, openneuro]
  same_as_threshold: 0.90
```

## Matching Methods

### 1. Exact Match
- Case-folded, punctuation-stripped comparison
- Threshold: 1.0 (exact)
- Best for: IDs, DOIs, PMIDs

### 2. Fuzzy Match
- Dice coefficient / token sort ratio
- Threshold: 0.9
- Best for: Labels with minor variations

### 3. Embedding Match
- Semantic similarity (NiCLIP > SBERT)
- Threshold: 0.85 (NiCLIP), 0.80 (SBERT)
- Best for: Task/Concept labels

### 4. Spatial Match
- Euclidean distance for coordinates
- Threshold: 8mm radius
- Best for: MNI/TAL coordinates

## Canonical Node Selection

When multiple nodes match via SAME_AS, a canonical node is selected based on:

1. **Source priority** (e.g., cogat > niclip > bids for Tasks)
2. **Connection count** (node with most edges)
3. **Creation time** (earliest node)
4. **Label length** (most descriptive)

## Integration with Bulk Loader

```python
from brain_researcher.services.neurokg.bulk_loader import LoaderConfig, BulkLoader

config = LoaderConfig(
    enable_matching=True,
    match_node_types=["Task", "Concept", "Publication"]  # or None for all
)

loader = BulkLoader(db, config)
# Loader will automatically match nodes and create SAME_AS edges
```

## Stats and Monitoring

```python
# After loading
print(f"Nodes matched: {stats.nodes_matched}")
print(f"SAME_AS edges: {stats.same_as_edges_created}")
```

Low-confidence matches are logged to `logs/match_failures.tsv` for review.

## Schema References

- See `docs/standards/schema_catalog.md` for edge types
- See `docs/standards/invariants.md` for ID rules (ID-01, REL-01)
- See `docs/PRD/prd_o2_kg_schema.md` for matching methods table
