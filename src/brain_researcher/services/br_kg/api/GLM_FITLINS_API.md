# GLM FitLins API Documentation

This document describes the API endpoints for accessing GLM FitLins data in BR-KG.

## Overview

The GLM FitLins API provides programmatic access to:
- OpenNeuro datasets with GLM FitLins analyses
- Statistical contrasts from fMRI studies
- Cognitive constructs mapped to contrasts
- Confidence scores from LLM and literature sources

This API is currently **unversioned** and should be treated as **v0** (subject to
backward‑incompatible changes). See **Versioning & Change Policy** below.

## Base URL

All endpoints are prefixed with: `/api/glmfitlins`

## Authentication

Currently, no authentication is required.

## API Contract (Summary)

**Error format (current):**
```json
{ "error": "Error message" }
```

**Known status codes:**
- `200 OK`: Success
- `400 Bad Request`: Invalid parameters (e.g., missing `q` for search)
- `404 Not Found`: Resource not found
- `503 Service Unavailable`: Backend unavailable (e.g., priors)
- `500 Internal Server Error`: Server error / backend failure

**Pagination:** `/contrasts`, `/constructs`, and `/search` accept `limit` + `offset`.

**Sorting:**
- `/contrasts/{id}/constructs` sorts by `overall_confidence` descending.
- `/constructs` sorts by `usage_count` descending.

The old draft OpenAPI file has been removed from the docs because it was not
generated from the live routes. Treat this Markdown file and the current Flask
blueprint as the source of truth until a generated contract is added.

## Endpoints

### 1. Get All Datasets

**GET** `/api/glmfitlins/datasets`

Returns all datasets that have GLM FitLins data.

**Response:**
```json
{
  "datasets": [
    {
      "id": "node_id",
      "dataset_id": "ds000001",
      "name": "Dataset Name",
      "doi": "10.xxx/xxx",
      "source": "openneuro_glmfitlins",
      "contrast_count": 25
    }
  ],
  "total": 34
}
```

### 2. Get Contrasts

**GET** `/api/glmfitlins/contrasts`

Returns contrasts with optional filtering.

**Query Parameters:**
- `dataset_id` *(string, optional)*: Filter by dataset ID (e.g., `ds000001`)
- `task` *(string, optional)*: Filter by task label
- `limit` *(integer, optional, default=100)*: Maximum results
- `offset` *(integer, optional, default=0)*: Pagination offset

**Example:** `/api/glmfitlins/contrasts?dataset_id=ds000001&limit=10`

**Response:**
```json
{
  "contrasts": [
    {
      "id": "contrast_node_id",
      "name": "faces>shapes",
      "task_label": "face_matching",
      "dataset_id": "ds000001",
      "construct_count": 5
    }
  ],
  "total": 744,
  "limit": 10,
  "offset": 0
}
```

### 3. Get Constructs for a Contrast

**GET** `/api/glmfitlins/contrasts/{contrast_id}/constructs`

Returns cognitive constructs associated with a specific contrast.

**Response:**
```json
{
  "contrast_id": "contrast_node_id",
  "constructs": [
    {
      "id": "trm_4a3fd79d0a038",
      "name": "face recognition",
      "direction": "+1",
      "llm_confidence": 0.9,
      "literature_confidence": 0.85,
      "overall_confidence": 0.88
    }
  ],
  "total": 5
}
```

### 4. Get All Constructs

**GET** `/api/glmfitlins/constructs`

Returns all cognitive constructs with usage statistics.

**Query Parameters:**
- `name` *(string, optional)*: Filter by construct name (partial match)
- `min_confidence` *(float, optional, default=0)*: Minimum avg confidence threshold
- `limit` *(integer, optional)*: Maximum results (if provided)
- `offset` *(integer, optional, default=0)*: Pagination offset

**Response:**
```json
{
  "constructs": [
    {
      "id": "trm_4a3fd79d0a038",
      "name": "cognitive control",
      "node_id": "construct_node_id",
      "usage_count": 146,
      "avg_confidence": 0.823
    }
  ],
  "total": 250,
  "limit": 50,
  "offset": 0
}
```

### 5. Search

**GET** `/api/glmfitlins/search`

Search across datasets, contrasts, and constructs.

**Query Parameters:**
- `q` *(string, required)*: Search query
- `type` *(string, optional)*: Filter by type (`dataset`, `contrast`, `construct`)
- `limit` *(integer, optional)*: Maximum results per type (if provided)
- `offset` *(integer, optional, default=0)*: Pagination offset per type

**Example:** `/api/glmfitlins/search?q=memory&type=construct`

**Response:**
```json
{
  "datasets": [],
  "contrasts": [
    {
      "id": "node_id",
      "name": "working_memory>baseline",
      "task_label": "n-back",
      "dataset_id": "ds000105"
    }
  ],
  "constructs": [
    {
      "id": "trm_xxx",
      "name": "working memory",
      "node_id": "node_id"
    }
  ],
  "total": {
    "datasets": 0,
    "contrasts": 15,
    "constructs": 3,
    "all": 18
  },
  "limit": 50,
  "offset": 0
}
```

### 6. Get GLM Priors

**GET** `/api/glmfitlins/priors`

Returns GLM design priors for a dataset/task (fallbacks to task/global if dataset has no priors).
When called without `dataset_id` and `task`, returns **global** priors only (no
task mixing). If no global priors exist, a **default baseline** prior is returned.
The response may merge evidence from multiple sources (e.g., BR-KG + literature),
and will explicitly report `sources` and `literature_support` when available.
`coverage` reports the fraction of specs where each axis is observable.

`priors` may include **confounds family axes** (e.g., `confounds_motion_6`,
`confounds_acompcor`) represented as `{"present": p, "absent": 1-p}` distributions.

**Query Parameters:**
- `dataset_id` *(string, optional)*: Dataset ID
- `task` *(string, optional)*: Task label
- `mode` *(string, optional, default=distribution)*: `distribution` or `family`
- `k` *(integer, optional, default=24)*: Number of specs (mode=family)
- `seed` *(integer, optional)*: RNG seed (mode=family)

**Response:**
```json
{
  "priors": {
    "hrf_basis": { "canonical": 0.7, "derivs": 0.3 },
    "confounds": { "6mot": 0.6, "24mot": 0.4 },
    "high_pass": { "128": 1.0 },
    "confounds_motion_6": { "present": 0.9, "absent": 0.1 }
  },
  "scanned": 42,
  "source": "hybrid",
  "scope": "dataset",
  "support": {
    "n_nodes_scanned": 42,
    "n_specs": 42,
    "n_datasets": 1,
    "n_tasks": 1,
    "default_axes": ["high_pass"]
  },
  "coverage": {
    "hrf_basis": 1.0,
    "confounds": 1.0,
    "high_pass": 0.0,
    "confounds_motion_6": 1.0
  },
  "literature_support": {
    "high_pass": {
      "status": "ok",
      "query": "task fMRI high-pass filter cutoff seconds",
      "store": "fileSearchStores/your-store",
      "model": "gemini-2.5-flash",
      "n_docs_hit": 5,
      "top_papers": [
        { "pmcid": "PMC123456", "doi": "10.1234/abcd.efgh", "title": "Example paper", "snippet": "..." }
      ]
    },
    "smoothing_fwhm": { "status": "ok", "n_docs_hit": 5, "top_papers": [] }
  },
  "sources": {
    "br-kg": { "n_nodes_scanned": 42, "n_datasets": 1, "n_tasks": 1 },
    "literature": { "high_pass": { "n_docs_hit": 5 }, "smoothing_fwhm": { "n_docs_hit": 5 } },
    "default": { "axes": ["high_pass"] }
  }
}
```

**Mode=family example:**
```json
{
  "scope": "global",
  "source": "hybrid",
  "support": { "n_nodes_scanned": 42, "n_datasets": 34, "n_tasks": 120 },
  "literature_support": {
    "high_pass": { "status": "ok", "n_docs_hit": 5 },
    "smoothing_fwhm": { "status": "ok", "n_docs_hit": 5 }
  },
  "sources": {
    "br-kg": { "n_nodes_scanned": 42, "n_datasets": 34, "n_tasks": 120 },
    "literature": { "high_pass": { "n_docs_hit": 5 }, "smoothing_fwhm": { "n_docs_hit": 5 } }
  },
  "spec_family": [
    {
      "variant_id": "4f8c1c0a7a3e9f5d2a6c...",
      "decision_points": {
        "hrf_basis": "canonical",
        "confounds": "6mot",
        "high_pass": 128,
        "confounds_families": {
          "confounds_acompcor": true,
          "confounds_global_signal": false
        }
      },
      "selection_reason": "coverage_required"
    },
    {
      "variant_id": "b2f1a0d8c4e9f7a1b3c5...",
      "decision_points": {
        "hrf_basis": "derivs",
        "confounds": "24mot",
        "high_pass": 128
      },
      "selection_reason": "priors_weighted"
    }
  ]
}
```

### 7. Get Contrasts for a Construct (Reverse Lookup)

**GET** `/api/glmfitlins/constructs/{id}/contrasts`

Returns contrasts linked to a given construct.

**Query Parameters:**
- `dataset_id` *(string, optional)*: Filter by dataset
- `min_confidence` *(float, optional, default=0)*: Minimum overall confidence
- `limit` *(integer, optional, default=100)*: Maximum results
- `offset` *(integer, optional, default=0)*: Pagination offset

**Response:**
```json
{
  "construct_id": "trm_...",
  "contrasts": [
    {
      "id": "contrast_node_id",
      "name": "faces>shapes",
      "task_label": "face_matching",
      "dataset_id": "ds000001",
      "direction": "+1",
      "overall_confidence": 0.88
    }
  ],
  "total": 5,
  "limit": 100,
  "offset": 0
}
```

### 8. Batch Constructs for Contrasts

**POST** `/api/glmfitlins/contrasts/constructs:batch`

**Body:**
```json
{ "contrast_ids": ["id1", "id2"], "min_confidence": 0.8 }
```

**Response:**
```json
{
  "results": [
    { "contrast_id": "id1", "constructs": [ ... ], "total": 3 }
  ],
  "total": 1
}
```

### 9. Get Statistics

**GET** `/api/glmfitlins/stats`

Returns statistics about the GLM FitLins data.

**Response:**
```json
{
  "database": {
    "total_nodes": 620,
    "total_relationships": 4913
  },
  "glmfitlins": {
    "datasets": 34,
    "contrasts": 317,
    "constructs": 250,
    "annotations": 3546
  },
  "confidence_stats": {
    "llm": {
      "mean": 0.723,
      "min": 0.0,
      "max": 1.0
    },
    "literature": {
      "mean": 0.456,
      "min": 0.0,
      "max": 0.98
    },
    "overall": {
      "mean": 0.612,
      "min": 0.0,
      "max": 0.99
    }
  }
}
```

### 10. Concept Aliases

**GET** `/api/glmfitlins/concept-aliases`

Returns concept alias mapping (useful for UI search suggestions).

**Response:**
```json
{
  "aliases": [{ "alias": "wm", "concept_id": "trm_xxx" }],
  "grouped_by_concept": { "trm_xxx": ["working memory", "wm"] },
  "total_aliases": 1234,
  "total_concepts": 456
}
```

## Error Responses

All endpoints return standard HTTP status codes:

- `200 OK`: Success
- `400 Bad Request`: Invalid parameters
- `404 Not Found`: Resource not found
- `503 Service Unavailable`: Backend unavailable
- `500 Internal Server Error`: Server error

Error format:
```json
{
  "error": "Error message"
}
```

## Data Dictionary & Semantics

**Dataset**
OpenNeuro dataset node. Use `dataset_id` (e.g., `ds000001`) for stable references.

**Contrast**
Contrast definition within a task. `contrast.id` is a **graph node id** (stable
within a database snapshot but not guaranteed across reloads). Prefer using
`dataset_id + name + task_label` for long‑term references.

**Construct**
Cognitive construct (typically Cognitive Atlas). `construct.id` is the
`construct_id` stored during ingestion (e.g., `trm_...`).

**Construct summary fields**
`usage_count` is the number of linked contrasts. `avg_confidence` is the mean
`overall_confidence` across those links (as returned by `/constructs`).

**Mapping / Annotation**
`INVOLVES_CONSTRUCT` relationship between a contrast and a construct, with
fields:
- `direction`: string (typically `+1` or `-1`; pipeline does not enforce a closed set)
- `llm_confidence`: float in `[0,1]`
- `literature_confidence`: float in `[0,1]`
- `overall_confidence`: float in `[0,1]` (pipeline‑computed)

**Confidence semantics**
Scores are produced by the annotation pipeline (LLM + literature signals). They
are **not calibrated probabilities**. Treat as relative rankings unless you
apply your own calibration.

## GLM Priors

GLM design priors live as `GLMDesignPrior` nodes and are linked via
`HAS_GLM_PRIOR` relationships. Use `/api/glmfitlins/priors` to fetch them.

## Key Workflows & N+1 Avoidance

The current API supports **reverse lookup** and **batch fetching** to avoid
N+1 patterns:
- `GET /constructs/{id}/contrasts?min_confidence=...`
- `POST /contrasts/constructs:batch { contrast_ids: [...] }`
- Consider adding `include=constructs` to `/contrasts` if UI still needs fewer calls.

## Pagination / Sorting / Limits

- `/contrasts` paginates by default (`limit` default = 100, `offset` default = 0).
- `/constructs` and `/search` accept `limit` + `offset`; if `limit` is omitted,
  the endpoints return all matches.
- `/datasets` is unpaginated (small payload).
- Sorting: `/constructs` by `usage_count` desc; `/contrasts/{id}/constructs`
  by `overall_confidence` desc.
- `limit`/`offset` are included in `/constructs` and `/search` responses only
  when `limit` is provided.
- Rate limits: none enforced (add at gateway if exposed publicly).

## Deployment (Dev & Prod)

**Dev (Flask)**
```bash
python brain_researcher/services/br_kg/api/graph_api.py
```

**Prod (example)**
```bash
gunicorn -w 4 -b 0.0.0.0:5000 brain_researcher.services.br_kg.api.graph_api:app
```

**Env vars (core):**
- `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`
- `NEO4J_PRELOAD_CACHE` (optional; default true)

**CORS:** not configured by default.

## Versioning & Change Policy

The API is **unversioned** today. For external clients, treat as v0 and pin to a
specific deployment. Recommended future path: `/api/v1/glmfitlins/...`.

## Data Provenance & Licensing

Primary source datasets are OpenNeuro; cite dataset‑level metadata and
`dataset_description.json` when available. The annotations/construct mappings
are **derived metadata** generated by the pipeline; clarify internal vs public
licensing before external release.

## Usage Examples

### Python
```python
import requests

# Get all datasets
response = requests.get("http://localhost:5000/api/glmfitlins/datasets")
datasets = response.json()

# Get contrasts for a dataset
response = requests.get(
    "http://localhost:5000/api/glmfitlins/contrasts",
    params={"dataset_id": "ds000001"}
)
contrasts = response.json()

# Search for working memory
response = requests.get(
    "http://localhost:5000/api/glmfitlins/search",
    params={"q": "working memory"}
)
results = response.json()
```

### JavaScript (fetch)
```javascript
// Get statistics
fetch('http://localhost:5000/api/glmfitlins/stats')
  .then(response => response.json())
  .then(data => console.log(data));

// Get constructs with high confidence
fetch('http://localhost:5000/api/glmfitlins/constructs?min_confidence=0.8')
  .then(response => response.json())
  .then(data => {
    data.constructs.forEach(construct => {
      console.log(`${construct.name}: ${construct.avg_confidence}`);
    });
  });
```

### cURL
```bash
# Get datasets
curl http://localhost:5000/api/glmfitlins/datasets

# Search for attention
curl "http://localhost:5000/api/glmfitlins/search?q=attention"

# Get constructs for a contrast
curl http://localhost:5000/api/glmfitlins/contrasts/abc123/constructs
```

## Running the API Server

1. Set environment variables (optional):
```bash
export BR_KG_GLMFITLINS_DB_PATH=br-kg/data/br-kg/db/br-kg_glmfitlins.db
export PORT=5000
export FLASK_DEBUG=true
```

2. Start the server:
```bash
python br-kg/api/graph_api.py
```

3. Test the API:
```bash
# Check health
curl http://localhost:5000/health

# Get GLM stats
curl http://localhost:5000/api/glmfitlins/stats
```

## Integration with Frontend

The API returns data in a format compatible with visualization libraries:

1. **Cytoscape.js**: The main `/subgraph` endpoint returns Cytoscape-compatible format
2. **D3.js**: The JSON responses can be directly used with D3 visualizations
3. **Plotly**: Confidence statistics can be visualized as distributions

Example visualization workflow:
1. Query contrasts for a dataset
2. Get constructs for each contrast
3. Build a network visualization showing contrast-construct relationships
4. Color edges by confidence scores
5. Size nodes by usage frequency
