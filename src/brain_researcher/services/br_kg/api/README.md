# BR-KG Graph API

Flask-based REST API for serving graph subsets from the BR-KG knowledge graph database.

## Overview

This API provides endpoints to query and explore the BR-KG knowledge graph, enabling visualization of concepts, studies, brain regions, and their relationships.

## Quick Start

### Running the API

```bash
# From repository root
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="password"
python -m brain_researcher.services.br_kg.api.graph_api
```

The API will start on `http://localhost:5000` by default.

## Endpoints

### 1. Health Check
```
GET /health
```

Returns the health status of the API and database connection.

**Response:**
```json
{
  "status": "healthy",
  "database": "connected",
  "total_nodes": 12500,
  "total_relationships": 45000
}
```

### 2. Get Subgraph
```
GET /subgraph?label=<node_label>&name=<node_name>&depth=<depth>
```

Retrieves a subgraph starting from a specific node using breadth-first search.

**Parameters:**
- `label` (required): Node label (e.g., "Concept", "BrainRegion", "Study")
- `name` (required): Name of the node to search for
- `depth` (optional): Traversal depth (1-3, default: 2)

**Example Request:**
```bash
curl "http://localhost:5000/subgraph?label=Concept&name=working%20memory&depth=2"
```

**Response Format:**
```json
{
  "nodes": [
    {
      "data": {
        "id": "node123",
        "label": "working memory",
        "labels": ["Concept"],
        "definition": "A cognitive system with limited capacity...",
        "source": "cognitive_atlas"
      }
    }
  ],
  "edges": [
    {
      "data": {
        "id": "node123-node456-STUDIED_IN",
        "source": "node123",
        "target": "node456",
        "label": "STUDIED_IN",
        "significance": 0.001
      }
    }
  ],
  "metadata": {
    "query": {
      "label": "Concept",
      "name": "working memory",
      "depth": 2
    },
    "node_count": 35,
    "edge_count": 42
  }
}
```

### 3. Database Statistics
```
GET /stats
```

Returns statistics about the knowledge graph database.

**Response:**
```json
{
  "total_nodes": 12500,
  "total_relationships": 45000,
  "node_labels": {
    "Concept": 3200,
    "Study": 5000,
    "BrainRegion": 1500,
    "Task": 800
  },
  "relationship_types": {
    "STUDIES": 15000,
    "ACTIVATES": 20000,
    "RELATED_TO": 10000
  }
}
```

## Error Handling

The API returns appropriate HTTP status codes and error messages:

- `400 Bad Request`: Invalid parameters or missing required fields
- `404 Not Found`: Resource not found
- `500 Internal Server Error`: Server-side error

Error response format:
```json
{
  "error": "Error description",
  "message": "Detailed error message"
}
```

## Performance

- The `/subgraph` endpoint is optimized to respond in under 500ms for depth=2 queries
- Large subgraphs (depth=3) may take longer depending on the connectivity of the starting node

## Testing

Run the unit tests:
```bash
pytest tests/unit/br-kg/test_api.py -v
```

## Example Usage

### Python Client Example
```python
import requests

# Get subgraph for "working memory" concept
response = requests.get(
    "http://localhost:5000/subgraph",
    params={
        "label": "Concept",
        "name": "working memory",
        "depth": 2
    }
)

data = response.json()
print(f"Found {data['metadata']['node_count']} nodes")
print(f"Found {data['metadata']['edge_count']} edges")
```

### JavaScript/Fetch Example
```javascript
const params = new URLSearchParams({
  label: 'BrainRegion',
  name: 'hippocampus',
  depth: 2
});

fetch(`http://localhost:5000/subgraph?${params}`)
  .then(response => response.json())
  .then(data => {
    console.log(`Nodes: ${data.nodes.length}`);
    console.log(`Edges: ${data.edges.length}`);
  });
```

## Environment Variables

- `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`
- `PORT`: API port (default: 5000)
- `FLASK_DEBUG`: Enable debug mode (default: False)

## Next Steps

The Explorer UI lives in `apps/web-ui` and consumes this API over HTTP.
