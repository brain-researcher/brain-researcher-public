# GLM FitLins Web Service Integration Guide

## Overview

The GLM FitLins data has been successfully integrated into the BR-KG web service. This guide explains how to use the new functionality.

## What's Been Added

1. **Database**: Created `br_kg_glmfitlins.db` with:
   - 34 OpenNeuro datasets
   - 317 statistical contrasts
   - 250 cognitive constructs
   - 3,546 contrast-to-construct mappings with confidence scores

2. **API Endpoints**: New REST API endpoints under `/api/glmfitlins/`:
   - `/datasets` - List all datasets
   - `/contrasts` - Query contrasts with filtering
   - `/contrasts/{id}/constructs` - Get constructs for a contrast
   - `/constructs` - List all cognitive constructs
   - `/search` - Search across all data
   - `/stats` - Get database statistics
   - `/concept-aliases` - Get concept name variations

3. **Processing Pipeline**:
   - `generate_concept_aliases.py` - Generate concept aliases from annotations
   - `load_glmfitlins_to_kg.py` - Load data into knowledge graph

## Quick Start

### 1. Start the API Server

```bash
# Set the database path (optional)
export BR_KG_GLMFITLINS_DB_PATH=br-kg/data/br-kg/db/br-kg_glmfitlins.db

# Start the server
python br-kg/api/graph_api.py
```

### 2. Test the API

```bash
# Check if GLM endpoints are working
curl http://localhost:5000/api/glmfitlins/stats

# Get all datasets
curl http://localhost:5000/api/glmfitlins/datasets

# Search for "working memory"
curl "http://localhost:5000/api/glmfitlins/search?q=working%20memory"
```

### 3. Use the Python Client

```python
from br_kg.examples.glmfitlins_client import GLMFitLinsClient

client = GLMFitLinsClient()

# Get statistics
stats = client.get_stats()
print(f"Total contrasts: {stats['glmfitlins']['contrasts']}")

# Search for a concept
results = client.search("attention")
print(f"Found {results['total']['all']} results")

# Get high-confidence constructs
constructs = client.get_constructs(min_confidence=0.8)
for c in constructs['constructs'][:5]:
    print(f"{c['name']}: {c['avg_confidence']}")
```

## Use Cases

### 1. Find Studies Using a Specific Cognitive Construct

```python
# Search for "cognitive control"
results = client.search("cognitive control", type_filter="construct")

# Get the construct ID
construct_id = results['constructs'][0]['id']

# Find all contrasts involving this construct
# (Currently requires direct database query, could be added as endpoint)
```

### 2. Explore a Dataset's Contrasts

```python
# Get dataset
datasets = client.get_datasets()
dataset_id = "ds000001"  # Balloon Analogue Risk Task

# Get all contrasts for this dataset
contrasts = client.get_contrasts(dataset_id=dataset_id)

# For each contrast, get its constructs
for contrast in contrasts['contrasts']:
    constructs = client.get_contrast_constructs(contrast['id'])
    print(f"\n{contrast['name']}:")
    for c in constructs['constructs']:
        print(f"  - {c['name']} ({c['overall_confidence']})")
```

### 3. Build a Visualization

```javascript
// Fetch data for visualization
async function buildContrastNetwork(datasetId) {
    // Get contrasts
    const contrastsResp = await fetch(
        `/api/glmfitlins/contrasts?dataset_id=${datasetId}`
    );
    const contrasts = await contrastsResp.json();

    // Build nodes and edges
    const nodes = [];
    const edges = [];

    for (const contrast of contrasts.contrasts) {
        // Add contrast node
        nodes.push({
            data: {
                id: contrast.id,
                label: contrast.name,
                type: 'contrast'
            }
        });

        // Get constructs
        const constructsResp = await fetch(
            `/api/glmfitlins/contrasts/${contrast.id}/constructs`
        );
        const constructs = await constructsResp.json();

        for (const construct of constructs.constructs) {
            // Add construct node if not exists
            if (!nodes.find(n => n.data.id === construct.id)) {
                nodes.push({
                    data: {
                        id: construct.id,
                        label: construct.name,
                        type: 'construct'
                    }
                });
            }

            // Add edge
            edges.push({
                data: {
                    source: contrast.id,
                    target: construct.id,
                    confidence: construct.overall_confidence,
                    direction: construct.direction
                }
            });
        }
    }

    // Render with Cytoscape.js
    const cy = cytoscape({
        container: document.getElementById('cy'),
        elements: { nodes, edges },
        style: [
            {
                selector: 'node[type="contrast"]',
                style: {
                    'background-color': '#66c2a5',
                    'label': 'data(label)'
                }
            },
            {
                selector: 'node[type="construct"]',
                style: {
                    'background-color': '#fc8d62',
                    'label': 'data(label)'
                }
            },
            {
                selector: 'edge',
                style: {
                    'width': 'mapData(confidence, 0, 1, 1, 5)',
                    'opacity': 'mapData(confidence, 0, 1, 0.3, 1)',
                    'line-color': '#999'
                }
            }
        ]
    });
}
```

## Frontend Integration Options

### 1. Add to Existing Dashboard

Add a new section for GLM FitLins data:

```javascript
// Add menu item
<MenuItem onClick={() => setView('glmfitlins')}>
    GLM FitLins Analysis
</MenuItem>

// Add view component
{view === 'glmfitlins' && <GLMFitLinsExplorer />}
```

### 2. Create Dedicated Interface

Build a specialized interface for exploring contrasts and constructs:

- Dataset selector
- Contrast browser with filtering
- Construct confidence visualization
- Network graph of relationships

### 3. Integrate with Existing Search

Extend the current search to include GLM FitLins data:

```javascript
async function unifiedSearch(query) {
    const [mainResults, glmResults] = await Promise.all([
        fetch(`/api/search`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query, rerank: 'gfs' })
        }),
        fetch(`/api/glmfitlins/search?q=${encodeURIComponent(query)}`)
    ]);

    const mainPayload = await mainResults.json();
    const mainList = Array.isArray(mainPayload) ? mainPayload : (mainPayload.results || []);
    const glmList = await glmResults.json();

    // Combine and display results (optionally keep rerank metadata from mainPayload.rerank_gfs)
}
```

## Advanced Features to Consider

1. **Confidence Filtering**: Add UI controls to filter by confidence thresholds
2. **Batch Analysis**: Compare constructs across multiple datasets
3. **Export Functions**: Allow users to export contrast-construct mappings
4. **Statistical Summaries**: Show distribution of confidence scores
5. **Integration with Main Graph**: Link GLM constructs to main BR-KG concepts

## GLM Priors (Schema)

GLM design priors are stored as `GLMDesignPrior` nodes and linked from datasets
and tasks using `HAS_GLM_PRIOR`.

**Node label**: `GLMDesignPrior`
**Key fields**:
- `id`: deterministic ID (e.g., `glm_prior:ds000114:fingerfootlips`)
- `task`: task label or `__all__` for global priors
- `dataset_id`: dataset ID when dataset‑scoped (optional for task/global)
- `axes`: normalized priors map including `{hrf_basis, confounds, high_pass}`
  plus confound-family presence axes (e.g., `confounds_motion_6`,
  `confounds_acompcor`, `confounds_global_signal`, `confounds_cosine_dct`).
- `hrf_basis`, `confounds`, `high_pass`: per‑axis maps (same as `axes`)
- `n_specs`: number of specs contributing to priors
- `source`: e.g., `openneuro_glmfitlins`

**Relationships**:
- `(Dataset)-[:HAS_GLM_PRIOR {scope:"dataset"}]->(GLMDesignPrior)`
- `(TaskSpec|Task)-[:HAS_GLM_PRIOR {scope:"task", dataset_id?}]->(GLMDesignPrior)`

## Maintenance

### Update Data

When new annotations are available:

```bash
# 1. Run the pipeline
python br-kg/etl/glmfitlins_ingest/discover_specs.py
python br-kg/etl/glmfitlins_ingest/parse_statsmodel.py
# (Skip annotate_constructs.py if using existing annotations)

# 2. Regenerate aliases
python generate_concept_aliases.py

# 3. Reload into database
python load_glmfitlins_to_kg.py

# 4. (Optional) Ingest GLM priors
python src/brain_researcher/services/br_kg/etl/glmfitlins_ingest/ingest_glm_priors.py --scope all
```

### Monitor Performance

The API includes timing information in logs. Monitor for:
- Slow queries (> 500ms)
- Large result sets
- Frequent searches

Consider adding caching for common queries.

## Troubleshooting

### API Returns 404
- Check that the GLM blueprint is registered in `graph_api.py`
- Verify the database file exists at the configured path

### No Data Returned
- Check that `load_glmfitlins_to_kg.py` ran successfully
- Verify annotation files exist in `llm_cognitive_function/data/processed_with_direction/`
- If querying priors, ensure `ingest_glm_priors.py` has run and that `HAS_GLM_PRIOR`
  relationships exist from `Dataset`/`TaskSpec` to `GLMDesignPrior` nodes.

### Slow Performance
- Add database indexes for frequently queried fields
- Implement pagination for large result sets
- Consider caching layer for repeated queries
