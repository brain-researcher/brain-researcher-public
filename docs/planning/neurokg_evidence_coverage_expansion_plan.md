# BR-KG Evidence Coverage Expansion Plan

As of March 11, 2026.

This document operationalizes a concrete coverage-expansion program for
`BR-KG` evidence.

It is not a generic “add more edges” plan.

The goal is to increase `auditable evidence coverage` while preserving a clean
benchmark lane and avoiding ontology drift.

## Goal

Increase usable evidence coverage for:

- `Publication -> Claim <- EvidenceSpan`
- normalized `Task`, `Concept`, and `BrainRegion` targets
- finer claim-first relation families such as:
  `REPLICATES`, `FAILED_REPLICATION_OF`, `NULL_RESULT_FOR`, `CONTRADICTS`,
  `ASSUMES`, and `CHALLENGES_ASSUMPTION`

without treating raw candidate generation as graph truth.

## Operating Principle

Use three lanes with different trust levels:

1. `Benchmark lane`
   `GABRIEL high_precision` only. This lane stays clean and auditable.
2. `Candidate lane`
   `GABRIEL balanced_marginal` and `kg_bootstrap` for recall expansion plus
   review/adjudication.
3. `Normalization lane`
   `KGGEN -> ONVOC -> task-panel -> GABRIEL ingest` for expanding normalized
   task coverage.

Operational rule:

- raw `KGGEN` triplets never write directly to the benchmark graph
- review-queue rows do not count as accepted evidence until adjudicated and
  re-ingested
- `kg_bootstrap` and `kg_task_panel` are coverage-building lanes, not headline
  benchmark lanes

## Repo Anchors

- generation + ingest: [gabriel_full_pipeline.md](<repo>/docs/neurokg/gabriel_full_pipeline.md)
- bounded sample path: [gabriel_sample_quickstart.md](<repo>/docs/neurokg/gabriel_sample_quickstart.md)
- loader + quality profiles: [gabriel_loader.py](<repo>/src/brain_researcher/services/neurokg/etl/loaders/gabriel_loader.py)
- variable computation + gate logic: [gabriel_measurements.py](<repo>/src/brain_researcher/services/neurokg/etl/loaders/gabriel_measurements.py)
- KGGEN evaluation: [gabriel_kggen_eval.py](<repo>/src/brain_researcher/services/neurokg/etl/evaluation/gabriel_kggen_eval.py)
- ONVOC mapping: [gabriel_onvoc_map.py](<repo>/src/brain_researcher/services/neurokg/etl/evaluation/gabriel_onvoc_map.py)
- task package builder: [build_task_panel_ingest_package.py](<repo>/scripts/build/build_task_panel_ingest_package.py)
- claim-first verifier bootstrap: [claim_first_vs_mention_bootstrap.py](<repo>/src/brain_researcher/services/neurokg/etl/evaluation/claim_first_vs_mention_bootstrap.py)

## Hard Preconditions

Coverage expansion must not continue until these parity issues are resolved:

- edge registry parity across
  [edge_schemas.py](<repo>/src/brain_researcher/services/neurokg/schemas/edge_schemas.py),
  [bulk_loader.py](<repo>/src/brain_researcher/services/neurokg/bulk_loader.py),
  and
  [canonical_mapping.py](<repo>/src/brain_researcher/services/neurokg/semantic/canonical_mapping.py)
- quality-profile governance parity between code and
  [thresholds.yaml](<repo>/configs/neurokg/thresholds.yaml)
- review-queue deduplication and unique-candidate accounting
- config/status parity for claim-spine node families in
  [config.yml](<repo>/configs/neurokg/config.yml)

## Owner Roles

- `PI`: go/no-go authority
- `CE`: claim/evidence ingest owner
- `VE`: verifier and benchmark owner
- `RA`: review queue and adjudication owner
- `OE`: ontology and ONVOC normalization owner
- `GE`: graph integration / validator parity owner

## 10-Week Execution Table

| Week | Lane | Concrete Work | Owner(s) | Artifacts | Pass / Fail |
|---|---|---|---|---|---|
| 1 | plumbing | Align validators, canonical mapping, and quality-profile config. Deduplicate the live GABRIEL review queue. | `GE, CE, RA` | `evidence_registry_parity_report.md`, `review_queue_dedup_report.md` | `Fail` if richer claim relations still cannot pass the same ingest path end to end. |
| 2 | benchmark | Freeze benchmark-lane rules and protect `high_precision` from candidate spillover. Reconfirm accepted-vs-queued accounting. | `VE, CE, RA` | `benchmark_lane_guardrails.md`, updated queue metrics | `Fail` if queued or low-rigor rows are still eligible for headline evidence. |
| 3 | candidate | Run sharded `br gabriel generate` on a larger publication slice. Ingest once with `balanced_marginal` and once with `kg_bootstrap` into candidate snapshots. | `CE, GE` | `gabriel_balanced_marginal_run.md`, `gabriel_kg_bootstrap_run.md` | `Pass` only if accepted objects grow and the benchmark lane remains unchanged. |
| 4 | candidate | Build an adjudication batch from unique rejected rows and near-threshold accepted rows. Promote reviewed rows through tracked re-ingest only. | `RA, CE` | `pre_gate_b_claim_adjudication_pack_v2.jsonl`, `adjudication_decisions_v1.md` | `Fail` if promotion bypasses tracked ingest or duplicates dominate queue counts. |
| 5 | kggen | Generate KGGEN candidates from the same Gabriel manifest and run `br gabriel eval-kggen`. Measure true `new_high_conf_edges`. | `OE, CE, VE` | `kggen_eval_report_v1.md`, `kggen_adapted_v1.jsonl` | `Fail` if KGGEN adds mostly parse noise or no net accepted-edge lift. |
| 6 | onvoc | Run `br gabriel map-onvoc` on accepted KGGEN-adapted candidates. Tune thresholds and inspect review spillover. | `OE, RA` | `onvoc_mapping_report_v1.md`, `onvoc_threshold_calibration_v1.md` | `Pass` only if normalized mappings beat raw-label drift and review burden stays bounded. |
| 7 | task panel | Build ONVOC-backed task-panel ingest package and ingest with `kg_task_panel`. | `OE, CE, GE` | `task_panel_package_v1/`, `task_panel_ingest_report_v1.md` | `Fail` if task coverage grows only through unnormalized labels. |
| 8 | finer relations | Increase extraction of explicit claim kinds: replication, failed replication, contradiction, null result, challenged assumption. | `CE, VE` | `fine_relation_coverage_report_v1.md` | `Pass` only if nontrivial counts appear for claim-kind edges with acceptable review quality. |
| 9 | verifier wiring | Push claim-first evidence controls into the novelty workflow path and rerun claim-first vs mention-fallback comparison. | `VE, GE` | `claim_first_vs_mention_report_v3.md`, `novelty_claim_first_gap_report.md` | `Fail` if richer claim evidence still does not affect runtime verifier behavior. |
| 10 | freeze | Freeze a candidate evidence snapshot and decide what graduates into the benchmark graph vs remains candidate-only. | `PI, CE, VE, RA, OE` | `evidence_snapshot_alpha.md`, `promotion_policy_v1.md`, `go_no_go_memo.md` | `Pass` only if accepted evidence growth is measurable and benchmark contamination remains controlled. |

## Immediate Command Surface

### 1. Broader GABRIEL generation

```bash
br gabriel generate \
  --limit 1000 \
  --shard-size 50 \
  --model gemini-2.5-pro
```

### 2. Candidate-lane ingest

```bash
br gabriel ingest \
  --manifest data/neurokg/raw/gabriel/runs/<run_id>/manifest.json \
  --quality-profile balanced_marginal

br gabriel ingest \
  --manifest data/neurokg/raw/gabriel/runs/<run_id>/manifest.json \
  --quality-profile kg_bootstrap
```

### 3. KGGEN coverage evaluation

```bash
br gabriel eval-kggen \
  --manifest data/neurokg/raw/gabriel/runs/<run_id>/manifest.json \
  --kggen-input data/neurokg/raw/kggen/candidates.jsonl \
  --output-dir data/neurokg/raw/gabriel/eval/kggen \
  --quality-profile balanced \
  --sample-size 300
```

Operational note:

- `eval-kggen` only works if KGGEN paper ids overlap the Gabriel manifest paper
  ids. Generate KGGEN from the same Gabriel manifest rather than an unrelated
  paper slice.

### 4. ONVOC normalization

```bash
br gabriel map-onvoc \
  --kggen-input data/neurokg/raw/gabriel/eval/kggen/kggen_adapted.jsonl \
  --output-dir data/neurokg/raw/gabriel/eval/kggen/onvoc \
  --min-score 0.82 \
  --margin-min 0.04
```

Operational note:

- keep ONVOC normalization enabled for the task-panel lane. The package builder
  expects `kggen_normalized_onvoc.jsonl`.

### 5. Task-panel package

```bash
python scripts/build/build_task_panel_ingest_package.py \
  --onvoc-dir data/neurokg/raw/gabriel/eval/kggen/onvoc \
  --output-dir data/neurokg/raw/gabriel/eval/kggen/task_panel_package \
  --task-fold-mode subfamily \
  --json

br gabriel ingest \
  --manifest data/neurokg/raw/gabriel/eval/kggen/task_panel_package/manifest_task_panel.json \
  --quality-profile kg_task_panel \
  --create-missing-targets
```

## Headline Metrics

- accepted `Claim` count
- accepted `EvidenceSpan` count
- accepted `MeasurementRun` count
- unique review-queue candidates
- adjudicated-and-promoted candidate count
- normalized `Task` target count from ONVOC-backed ingest
- `new_high_conf_edges` from KGGEN evaluation
- nonzero counts for:
  `REPLICATES`, `FAILED_REPLICATION_OF`, `NULL_RESULT_FOR`,
  `CONTRADICTS`, `CHALLENGES_ASSUMPTION`
- claim-first verifier auditability pass rate
- claim-first minus mention-fallback delta on held-out benchmark

## Hard No-Go Rules

- Do not ingest raw KGGEN predicates directly to the benchmark graph.
- Do not count review-queue rows as accepted evidence before adjudication and
  tracked re-ingest.
- Do not report `kg_bootstrap` growth as benchmark-quality evidence.
- Do not continue if validator/config drift means richer claim edges are still
  silently noncanonical downstream.

## First Artifacts To Produce

- `evidence_registry_parity_report.md`
- `review_queue_dedup_report.md`
- `kggen_eval_report_v1.md`
- `onvoc_mapping_report_v1.md`
- `task_panel_ingest_report_v1.md`
- `fine_relation_coverage_report_v1.md`
- `promotion_policy_v1.md`

## Success Definition

This plan succeeds when all of the following are true:

- accepted claim/evidence/run objects grow materially without contaminating the
  benchmark lane
- normalized `Task` coverage grows through the ONVOC task-panel bridge
- finer claim-first relations are present at nontrivial usable counts
- claim-first verification and novelty paths actually use the richer evidence
  rather than falling back to mention-only behavior
