# GABRIEL Sample Quickstart

For full-corpus sharded generation + ingest, see:

- `docs/neurokg/gabriel_full_pipeline.md`

This repo now includes a runnable sample at:

- `tests/fixtures/neurokg/gabriel_measurements.sample.jsonl`

A local runtime copy is also placed at:

- `data/neurokg/raw/gabriel/measurements.jsonl`

## Run only the GABRIEL source

```bash
export NEO4J_URI='bolt://localhost:7687'
export NEO4J_USER='neo4j'
export NEO4J_PASSWORD='your-password'

python -m brain_researcher.services.neurokg.etl.load_all \
  --config configs/neurokg/data_config.json \
  --sources gabriel
```

## Expected behavior

- High-confidence records are ingested into `Publication`, `Claim`, `EvidenceSpan`, and `MeasurementRun` nodes.
- New evidence-first edges are created: `MENTIONS`, `MENTIONS_REGION`, `REPORTS_CLAIM`, `SUPPORTS`, and `GENERATED`.
- Low-confidence records are routed to:
  - `data/neurokg/raw/gabriel/review_queue.jsonl`
