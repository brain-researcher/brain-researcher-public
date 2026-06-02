# Create Activation Edges Script

## Overview

The `create_activation_edges.py` script aggregates coordinate evidence from neuroscience studies to create ACTIVATES relationships between tasks/concepts and brain regions. It implements a threshold-based approach where relationships are only created when sufficient coordinate evidence exists.

## Algorithm

1. **Evidence Collection**: For each Task or Concept node:
   - Find connected Publications via STUDIES/MENTIONS_CONCEPT relationships
   - For each Publication, find associated Coordinates via HAS_COORDINATE
   - For each Coordinate, find the BrainRegion via LOCATED_IN
   - Aggregate coordinates by task/concept and brain region

2. **Edge Creation**: For each task/concept-region pair:
   - Count the number of supporting coordinates
   - If count >= threshold, create an ACTIVATES relationship
   - Store evidence count, confidence score, and sample coordinate IDs

## Usage

```bash
# NeoKG is Neo4j-only. Configure connection via env vars:
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="***"
export NEO4J_DATABASE="neo4j"

python scripts/br-kg/create_activation_edges.py [options]
```

### Options

- `--threshold N`: Minimum coordinate evidence required (default: 5)
- `--dry-run`: Preview edges without creating them
- `--verbose`: Enable verbose logging

### Examples

```bash
# Create edges with default threshold
python scripts/br-kg/create_activation_edges.py

# Preview what would be created with threshold of 10
python scripts/br-kg/create_activation_edges.py --threshold 10 --dry-run

# Run with verbose output
python scripts/br-kg/create_activation_edges.py --verbose
```

## Database Requirements

The script expects the following node types and relationships:

### Node Types
- `Task`: Cognitive tasks (e.g., n-back, stroop)
- `Concept`: Cognitive concepts (e.g., working memory, attention)
- `Study`: Research publications
- `Coordinate`: Brain activation coordinates
- `BrainRegion`: Anatomical brain regions

### Relationship Types
- `STUDIES`: Study -> Concept/Task
- `MENTIONS_CONCEPT`: Study -> Concept
- `HAS_COORDINATE`: Study -> Coordinate
- `LOCATED_IN`: Coordinate -> BrainRegion
- `ACTIVATES`: Task/Concept -> BrainRegion (created by this script)

## ACTIVATES Edge Properties

Created edges include the following properties:

- `evidence_count`: Number of supporting coordinates
- `coordinate_ids`: Sample of coordinate IDs (up to 10)
- `confidence`: Confidence score (0-1) based on evidence count
- `method`: Always "coordinate_aggregation"
- `threshold`: The threshold used when creating the edge

## Example Output

```
Processing Concept nodes...
Found 50 Concept nodes to process
Evidence collection complete: 35 Concept nodes have coordinate evidence
Creating ACTIVATES edges with threshold=5
  - Edges created: 42
  - Skipped (below threshold): 23
  - Skipped (already exists): 8

Processing Task nodes...
Found 30 Task nodes to process
Evidence collection complete: 25 Task nodes have coordinate evidence
Creating ACTIVATES edges with threshold=5
  - Edges created: 31
  - Skipped (below threshold): 15
  - Skipped (already exists): 5

Total edges created: 73
```

## Testing

Run the test suite:

```bash
python tests/unit/br-kg/test_create_activation_edges.py
```

## Integration Example

See `examples/br-kg/activation_edges_example.py` for a complete example of setting up test data and running the helpers programmatically.
