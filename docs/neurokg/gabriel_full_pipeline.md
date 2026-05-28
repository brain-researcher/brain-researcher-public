# GABRIEL Full Pipeline

This document describes the sharded two-step GABRIEL workflow:

1. `br gabriel generate`
2. `br gabriel ingest`

You can inspect progress at any point with:

- `br gabriel status`
- `br gabriel ingest-candidate-only` (promote `review_queue_candidate_only.jsonl`
  into a live candidate lane)
- `br gabriel eval-kggen` (research-only baseline vs KGGen coverage benchmark)

## Prerequisites

- Neo4j credentials for query and ingest:
  - `NEO4J_URI`
  - `NEO4J_PASSWORD`
  - `NEO4J_USER` (optional, defaults to `neo4j`)
  - `NEO4J_DATABASE` (optional)
- Optional LLM credentials for generation through `LLMRouter`:
  - `USE_GEMINI_CLI=true` with local Gemini auth, or
  - API key env vars (for example `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`)

If LLM access is unavailable, generation automatically falls back to heuristics.

## Step 1: Generate shards

```bash
br gabriel generate \
  --limit 500 \
  --shard-size 50 \
  --model gemini-2.5-pro
```

What this does:

- Queries `Publication` nodes from Neo4j.
- If Neo4j returns no publications (or is unavailable), optionally falls back to
  cached scholarly metadata under `data/neurokg/raw/scholarly_metadata`.
- Calls `LLMRouter` with a strict JSON prompt.
- Falls back to deterministic heuristic extraction when LLM output fails or no
  model credentials are available.
- Writes per-shard JSONL files, raw response files, and a run manifest.

Main output layout:

```text
data/neurokg/raw/gabriel/runs/<run_id>/
  manifest.json
  shards/
    shard_0000.jsonl
    shard_0001.jsonl
    ...
  raw/
    shard_0000/
      pub_0000001.json
      pub_0000002.json
      ...
```

## Step 2: Ingest shards

```bash
br gabriel ingest \
  --manifest data/neurokg/raw/gabriel/runs/<run_id>/manifest.json \
  --quality-profile balanced
```

What this does:

- Reads shard paths from `manifest.json`.
- Runs `GabrielMeasurementLoader` for each shard.
- Uses loader batch ingest over all pending shards with checkpoint tracking.
- Updates shard-level ingest state and aggregate ingest summary in manifest.
- Writes review queue items to:
  - `data/neurokg/raw/gabriel/runs/<run_id>/review_queue.jsonl`
- Writes loader checkpoint to:
  - `data/neurokg/raw/gabriel/runs/<run_id>/ingest_checkpoint.json`

Resume behavior:

- `br gabriel ingest` defaults to `--resume`, skipping shards already marked
  `completed` in manifest.

## Step 2.5: Load candidate-only review queue into live Neo4j

Use this when you want broader graph coverage without relaxing the benchmark
gate. Candidate-only rows stay explicitly marked as non-benchmark evidence, but
become queryable in the live graph.

From a run manifest:

```bash
br gabriel ingest-candidate-only \
  --manifest data/neurokg/raw/gabriel/runs/<run_id>/manifest.json \
  --source-quality-profile candidate_only
```

From a direct queue path:

```bash
br gabriel ingest-candidate-only \
  --queue data/neurokg/raw/gabriel/eval/<some_pack>/review_queue_candidate_only.jsonl \
  --source-quality-profile balanced_marginal_candidate_only
```

What this does:

- reads wrapped queue rows from `review_queue_candidate_only.jsonl`
- materializes them into live Neo4j using the normal Gabriel paper/evidence/claim
  spine
- annotates created or merged claim/evidence/relationship objects with
  `candidate_lane_*` metadata such as bucket, trigger reason, and source quality
  profile
- does not promote those rows into the benchmark lane

Operational rule:

- `benchmark ingest` remains `br gabriel ingest`
- `candidate lane replay` is `br gabriel ingest-candidate-only`

## Step 3: Status

```bash
br gabriel status --manifest data/neurokg/raw/gabriel/runs/<run_id>/manifest.json
```

Status reports:

- total shards
- shards ingested
- expected vs on-disk vs ingested record counts
- LLM vs heuristic record totals
- per-shard ingest state

Without `--manifest`, `br gabriel ingest` and `br gabriel status` resolve the
latest manifest under `data/neurokg/raw/gabriel/runs`.

## Step 3.5: Generate real KGGen candidates (research-only)

Use the helper script to produce evaluator-compatible KGGen candidates for the
same paper IDs present in your Gabriel manifest:

```bash
external/kg-gen/.venv/bin/python scripts/kggen_generate_from_manifest.py \
  --manifest data/neurokg/raw/gabriel/runs/<run_id>/manifest.json \
  --output data/neurokg/raw/kggen/real_from_manifest.jsonl \
  --max-papers 300 \
  --model gemini/gemini-2.5-flash \
  --overwrite \
  --json
```

Notes:

- If `kg_gen` is unavailable in the current interpreter, the script auto-reexecs
  with `external/kg-gen/.venv/bin/python`.
- It enriches title/abstract from `data/neurokg/raw/scholarly_metadata` when
  DOI-matched cache files exist.
- It writes a sibling summary file at
  `data/neurokg/raw/kggen/real_from_manifest.summary.json`.

## Step 4: Research-only KGGen evaluation

Use this command to compare KGGen-derived candidates against baseline Gabriel
records without writing anything to Neo4j:

```bash
br gabriel eval-kggen \
  --manifest data/neurokg/raw/gabriel/runs/<run_id>/manifest.json \
  --kggen-input data/neurokg/raw/kggen/candidates.jsonl \
  --output-dir data/neurokg/raw/gabriel/eval/kggen \
  --quality-profile balanced \
  --sample-size 300
```

What this does:

- Loads baseline records from Gabriel shard JSONL files.
- Adapts KGGen JSON/JSONL outputs into Gabriel-compatible candidate records.
- Applies the same quality gate variables and thresholds to both arms.
- Emits a research report and artifacts:
  - `report.json` (coverage/quality/ops summary)
  - `review_queue_combined.jsonl` (rejected candidates with reasons)
  - `kggen_adapted.jsonl` (normalized KGGen records)
  - `sample_paper_ids.json` (evaluated overlap sample)

## Step 5: ONVOC mapping + threshold calibration (research-only)

Map KGGen candidates to ONVOC concepts:

```bash
br gabriel map-onvoc \
  --kggen-input data/neurokg/raw/kggen/real_from_manifest.jsonl \
  --output-dir data/neurokg/raw/gabriel/eval/kggen/onvoc \
  --min-score 0.82 \
  --margin-min 0.04 \
  --json
```

Keep ONVOC normalization enabled for this lane. The downstream task-panel
package builder requires `kggen_normalized_onvoc.jsonl`, so
`--no-normalize-targets` breaks the handoff.

Then run threshold grid calibration on the generated `mapping_rows.jsonl`:

```bash
python scripts/calibrate_onvoc_thresholds.py \
  --mapping-rows data/neurokg/raw/gabriel/eval/kggen/onvoc/mapping_rows.jsonl \
  --min-scores 0.72,0.74,0.76,0.78,0.80,0.82,0.84 \
  --margins 0.00,0.01,0.02,0.03,0.04 \
  --top-n 20 \
  --json
```

This writes `onvoc_threshold_grid_summary.json` next to `mapping_rows.jsonl`.

## Step 6: Build task-panel ingest package (family-fold optional)

```bash
python scripts/build/build_task_panel_ingest_package.py \
  --onvoc-dir data/neurokg/raw/gabriel/eval/kggen/onvoc \
  --output-dir data/neurokg/raw/gabriel/eval/kggen/task_panel_package \
  --task-fold-mode subfamily \
  --json
```

`--task-fold-mode` options:

- `off`: keep original target IDs.
- `onvoc`: one canonical task per ONVOC concept.
- `subfamily`: fold similar paradigms to taxonomy subfamilies.
- `family`: fold to top-level task families.

## Step 6.5: Ingest the task-panel package with the task-panel gate

```bash
br gabriel ingest \
  --manifest data/neurokg/raw/gabriel/eval/kggen/task_panel_package/manifest_task_panel.json \
  --quality-profile kg_task_panel \
  --create-missing-targets
```

Use `kg_task_panel` here, not `balanced`. The package is ONVOC-normalized and
task-filtered, and the dedicated task-panel gate is the intended promotion path
for this lane.

## Step 6.6: Exact reroutes after task-panel packaging

Use exact reroute subsets when a small number of rows must be rewritten to a
more specific canonical target without rebuilding the full package.

There are two distinct cases:

- `Task` exact reroutes
  - build the subset
  - ingest it with `kg_task_panel`
  - then run exact-id migration to rewire `Claim.target_id` and
    `Publication-[:MENTIONS]`
- `Concept` exact reroutes
  - build the subset
  - skip ordinary `kg_task_panel` ingest
  - run exact-id migration directly

Why this split exists:

- the task-panel gate is for ONVOC-normalized task rows
- `Concept` reroutes intentionally leave the task lane and should not be
  treated as task-panel promotions
- in practice, `Concept` reroute subsets are expected to be rejected by
  `kg_task_panel`, so the safe path is `exact-id migration only`

Build an exact reroute subset:

```bash
python scripts/tools/etl/build_task_panel_exact_reroute_subset.py \
  --source-manifest data/neurokg/raw/gabriel/eval/kggen/task_panel_package/manifest_task_panel.json \
  --records-jsonl data/neurokg/raw/gabriel/eval/kggen/reroute_rows.jsonl \
  --output-dir data/neurokg/raw/gabriel/eval/kggen/reroute_subset \
  --new-target-type Task \
  --new-target-id task:subfamily:sf_affect_induction \
  --new-target-label "Emotion Regulation" \
  --new-family-id tf_preference_affective \
  --new-subfamily-id sf_affect_induction
```

For a `Concept` reroute, switch the target type and omit family/subfamily:

```bash
python scripts/tools/etl/build_task_panel_exact_reroute_subset.py \
  --source-manifest data/neurokg/raw/gabriel/eval/kggen/task_panel_package/manifest_task_panel.json \
  --records-jsonl data/neurokg/raw/gabriel/eval/kggen/reroute_rows.jsonl \
  --output-dir data/neurokg/raw/gabriel/eval/kggen/reroute_subset_concept \
  --new-target-type Concept \
  --new-target-id concept:feature_processing \
  --new-target-label "feature processing"
```

Run exact-id migration:

```bash
python scripts/tools/etl/migrate_task_panel_exact_ids.py \
  --manifest data/neurokg/raw/gabriel/eval/kggen/reroute_subset/manifest_task_panel.json
```

For `Concept` reroutes, include the concept prefix explicitly:

```bash
python scripts/tools/etl/migrate_task_panel_exact_ids.py \
  --manifest data/neurokg/raw/gabriel/eval/kggen/reroute_subset_concept/manifest_task_panel.json \
  --exact-prefix concept:
```

Operational rule:

- `Task reroute -> kg_task_panel ingest + exact-id migration`
- `Concept reroute -> exact-id migration only`

## Useful options

- Force deterministic extraction:
  - `br gabriel generate --force-heuristic`
- Run over all publications:
  - `br gabriel generate --limit 0`
- Disable cache fallback:
  - `br gabriel generate --no-cache-fallback`
- Reuse an explicit run id:
  - `br gabriel generate --run-id my-run-id --overwrite`
- JSON output:
  - `br gabriel generate --json`
  - `br gabriel ingest --json`
  - `br gabriel status --json`
