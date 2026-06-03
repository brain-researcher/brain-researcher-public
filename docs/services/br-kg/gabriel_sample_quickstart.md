# GABRIEL Sample Quickstart

For full-corpus sharded generation + ingest, see:

- `docs/br-kg/gabriel_full_pipeline.md`

This repo now includes a runnable sample at:

- `tests/fixtures/br-kg/gabriel_measurements.sample.jsonl`

A local runtime copy is also placed at:

- `data/br-kg/raw/gabriel/measurements.jsonl`

## Run only the GABRIEL source

```bash
export NEO4J_URI='bolt://localhost:7687'
export NEO4J_USER='neo4j'
export NEO4J_PASSWORD='your-password'

python -m brain_researcher.services.br_kg.etl.load_all \
  --config configs/br-kg/data_config.json \
  --sources gabriel
```

## Expected behavior

- High-confidence records are ingested into `Publication`, `Claim`, `EvidenceSpan`, and `MeasurementRun` nodes.
- New evidence-first edges are created: `MENTIONS`, `MENTIONS_REGION`, `REPORTS_CLAIM`, `SUPPORTS`, and `GENERATED`.
- Low-confidence records are routed to:
  - `data/br-kg/raw/gabriel/review_queue.jsonl`
