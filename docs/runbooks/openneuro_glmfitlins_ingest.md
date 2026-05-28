# OpenNeuro GLM FitLins Ingest + Yeo17 Recompute

This runbook provides a repeatable path to:
1) ingest OpenNeuro GLM FitLins maps/specs into Neo4j, and
2) recompute Yeo17 summaries + IN_REGION edges.

## Prerequisites

- OpenNeuro GLM FitLins data is available under `data/openneuro_glmfitlins`.
- Neo4j is reachable and env vars are set:
  - `NEO4J_URI` (e.g., `bolt://localhost:7687`)
  - `NEO4J_PASSWORD`
  - Optional: `NEO4J_USER`, `NEO4J_DATABASE`
- Optional metadata path (if dataset DOI lookup is needed):
  - `OPENNEURO_METADATA_ROOT=/path/to/openneuro_metadata`

## One-click run

```bash
scripts/ingest/run_openneuro_glmfitlins_ingest_neo4j.sh
scripts/ingest/run_openneuro_glmfitlins_yeo17_recompute.sh
```

Logs are written to `logs/`.

## Manifest handling

If `data/openneuro_glmfitlins/manifest/openneuro_glm_statsmaps.json` is missing,
the ingest script will build it automatically. You can also rebuild manually:

```bash
python3 scripts/tools/once/build_openneuro_glm_manifest.py \
  --config data/openneuro_glmfitlins/path_config.local.json \
  --output data/openneuro_glmfitlins/manifest/openneuro_glm_statsmaps.json
```

## Ingest script options

```bash
scripts/ingest/run_openneuro_glmfitlins_ingest_neo4j.sh \
  --path-config data/openneuro_glmfitlins/path_config.local.json \
  --manifest data/openneuro_glmfitlins/manifest/openneuro_glm_statsmaps.json \
  --statsmodel-dir data/openneuro_glmfitlins/statsmodel_specs \
  --mode full \
  --limit 200 \
  --manifest-limit 200 \
  --rebuild-manifest
```

Notes:
- `--mode full` ingests all maps unless `--limit` is provided.
- Use `--manifest-limit` only when you explicitly want a truncated manifest.
- Use `--no-links` to skip cross-source linking.

## Yeo17 recompute options

```bash
scripts/ingest/run_openneuro_glmfitlins_yeo17_recompute.sh \
  --datasets-root data/openneuro_glmfitlins \
  --manifest data/openneuro_glmfitlins/manifest/openneuro_glm_statsmaps.json \
  --summaries-dir data/openneuro_glmfitlins/summaries \
  --top-k 17 \
  --z-thr 2.3
```

Common variants:
- `--from-summary`: ingest edges from an existing summary CSV only
- `--no-resume`: recompute all maps even if summary rows exist
- `--clear-existing`: delete existing OpenNeuro GLMFitLins Yeo17 edges first

## Expected outputs

- Ingest:
  - Neo4j nodes/edges for `StatsMap`, `ModelSpec`, `TaskAnalysis`, `Contrast`, etc.
- Yeo17 recompute:
  - `data/openneuro_glmfitlins/summaries/yeo17_summary.csv`
  - `IN_REGION` edges for Yeo17 (source: `openneuro_glmfitlins`)
