# Capability Catalog

This directory contains the capability catalog YAML file for neuroimaging tools.

## Documentation

For complete documentation, see:
- **[Catalog User Guide](../../docs/catalog_README.md)** - Quick start, tool listings, schema reference
- **[Developer Guide](../../docs/development/planner_catalog.md)** - Architecture, adding tools, CI/CD

## Files

- **capabilities.yaml** - Catalog of 14 containerized tools with their capabilities and configurations
- **../tools_catalog.json** - 41 Python analysis tools (automatically converted in catalog mode)

## Quick Start

```bash
# Enable catalog mode (loads 55 total tools: 14 container + 41 Python)
export BR_PLANNER_SOURCE=catalog

# Validate catalog
python scripts/ci/validate_capabilities.py

# Run tests
pytest tests/unit/planner/ -v
```

## PR-2: Catalog-Driven Selection

The catalog now supports intelligent tool selection with:
- **Natural language queries** - "skull strip T1 image" instead of exact tool IDs
- **Synonym mapping** - Multiple terms map to operators (configured in `configs/legacy/mappings/op_synonyms.yaml`)
- **Preflight checks** - Validates tool availability before selection
- **Multi-factor scoring** - Ranks candidates by intent match (40%), preflight (30%), description relevance (20%), metadata (10%)

## PR-3: Performance & Materialization

Enhanced catalog with caching, 5-factor scoring, and structured plans:
- **Preflight caching** - Redis-backed with 15min TTL, automatic fallback to in-memory
- **Enhanced scoring** - 5 factors: intent (35%), preflight (25%), description (20%), metadata (10%), resource fit (10%)
- **Configurable weights** - Via `configs/planner/scoring_weights.yaml` or env vars (`BR_SCORE_WEIGHT_*`)
- **Narrative explanations** - Auto-generated brief explanations for each candidate
- **Plan materializer** - Converts candidates to structured Plan/PlanDAG format

Configuration files:
- `configs/planner/preflight.yaml` - Cache TTL, check settings
- `configs/planner/scoring_weights.yaml` - Factor weights, explanation templates

See [Developer Guide](../../docs/development/planner_catalog.md#performance--materialization-pr-3) for details.
