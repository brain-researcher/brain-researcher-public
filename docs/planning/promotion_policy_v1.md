# Promotion Policy V1

Date: 2026-03-13

## Purpose

This document freezes the Week 10 promotion boundary referenced in
[neurokg_evidence_coverage_expansion_plan.md](<repo>/docs/planning/neurokg_evidence_coverage_expansion_plan.md#L94):

- what may count as benchmark-admitted evidence
- what must remain candidate-only
- what should be held for manual policy review
- what is terminally retired from benchmark follow-up

This is a policy freeze, not a new extraction or ingest run.

## Authority Order

When sources disagree, use this order:

1. [claim_benchmark_charter.md](<repo>/docs/planning/claim_benchmark_charter.md)
2. [neurokg_evidence_coverage_expansion_plan.md](<repo>/docs/planning/neurokg_evidence_coverage_expansion_plan.md)
3. [gabriel_full_pipeline.md](<repo>/docs/neurokg/gabriel_full_pipeline.md)
4. [gabriel_loader.py](<repo>/src/brain_researcher/services/neurokg/etl/loaders/gabriel_loader.py)
5. [gabriel_generator.py](<repo>/src/brain_researcher/services/neurokg/etl/gabriel_generator.py)
6. bounded adjudication and closeout notes under [docs/planning](<repo>/docs/planning)

Operational rule:

- code-enforced boundaries win over older planning prose when they conflict
- benchmark headline reporting must still follow the stricter benchmark charter

## Lane Definitions

### 1. Benchmark-admitted evidence

These rows are part of the benchmark graph contract and may count in benchmark
coverage and quality reporting.

Allowed entry paths:

- accepted ordinary ingest under `high_precision`
- bounded regeneration rows that were:
  - benchmark-suppressed first
  - regenerated from non-title evidence
  - explicitly reviewed as salvageable
  - re-ingested through a tracked manifest
  - accepted without returning to review queue

Current examples of the second path are documented in
[balanced_title_only_regeneration_followup_20260313.md](<repo>/docs/planning/balanced_title_only_regeneration_followup_20260313.md).

Operational rule:

- raw candidate runs do not become benchmark-admitted merely because they exist
  in live Neo4j

### 2. Candidate-only evidence

These rows may exist in live Neo4j and may appear in `broad` queries, but they
must not count as benchmark-admitted evidence.

Allowed sources:

- replayed `review_queue_candidate_only.jsonl` via
  `br gabriel ingest-candidate-only`
- adjudicated reroutes from benchmark follow-up
- terminal candidate-only closeouts for rows that remain useful for coverage but
  are not benchmarkable

Code-enforced properties:

- loader replay writes `candidate_lane_present=true` plus `candidate_lane_*`
  provenance in
  [gabriel_loader.py](<repo>/src/brain_researcher/services/neurokg/etl/loaders/gabriel_loader.py#L770)
- replay skips rows that would mutate existing benchmark graph state in
  [gabriel_loader.py](<repo>/src/brain_researcher/services/neurokg/etl/loaders/gabriel_loader.py#L628)
- CLI path is `br gabriel ingest-candidate-only` in
  [gabriel_commands.py](<repo>/src/brain_researcher/cli/commands/gabriel_commands.py#L358)

### 3. Hold / manual-review rows

These rows are neither benchmark-admitted nor candidate-only by default.

They stay outside automatic promotion until a bounded review decides whether
they should become:

- benchmark regeneration candidates
- candidate-only
- retire-benchmark

Representative examples were recorded in
[balanced_residual_hold_unresolved_ledger_20260313.md](<repo>/docs/planning/balanced_residual_hold_unresolved_ledger_20260313.md).

### 4. Retire-benchmark rows

These rows are explicitly removed from active benchmark follow-up.

Meaning:

- they do not remain in benchmark retry queues
- they do not require further benchmark adjudication
- they may still exist as audit artifacts
- if a weaker live candidate claim already exists, that does not re-open them
  for benchmark accounting

Examples are documented in
[balanced_residual_followup_20260313.md](<repo>/docs/planning/balanced_residual_followup_20260313.md)
and
[balanced_final_tail_closeout_20260313.md](<repo>/docs/planning/balanced_final_tail_closeout_20260313.md).

## Hard Policy Decisions

### Benchmark lane stays claim-first and auditable

The benchmark contract still inherits the benchmark charter:

- accepted evidence must be provenance-complete
- review-queue rows do not count as benchmark evidence
- benchmark reporting must not silently mix in weaker candidate rows

Anchor:
[claim_benchmark_charter.md](<repo>/docs/planning/claim_benchmark_charter.md#L91)

### Raw `balanced_marginal` and `kg_bootstrap` output is not benchmark-admitted

This policy freezes the distinction that the expansion plan already wanted:

- `high_precision` remains the clean benchmark gate
- `balanced_marginal` and `kg_bootstrap` remain candidate-generation lanes
- a row from those lanes becomes benchmark-admitted only through explicit,
  tracked promotion

Anchor:
[neurokg_evidence_coverage_expansion_plan.md](<repo>/docs/planning/neurokg_evidence_coverage_expansion_plan.md#L17)

### Title-only benchmark rows are not benchmark-admitted

For benchmark profiles, title-only rows are suppressed before ordinary
promotion.

Code-enforced behavior:

- benchmark profiles append `benchmark_title_only_suppressed`
- obvious generic title-only concepts also append
  `candidate_only_title_generic_reroute`

Anchor:
[gabriel_loader.py](<repo>/src/brain_researcher/services/neurokg/etl/loaders/gabriel_loader.py#L860)
and
[balanced_title_only_reroute_20260313.md](<repo>/docs/planning/balanced_title_only_reroute_20260313.md)

### Candidate-only is a real live graph layer, not an offline queue

Candidate-only evidence may be materialized into Neo4j, but it remains
non-benchmark evidence by policy.

Operational consequences:

- `strict` query mode excludes candidate-lane evidence
- `broad` query mode includes it and exposes `candidate_lane` provenance

Anchors:
[gabriel_full_pipeline.md](<repo>/docs/neurokg/gabriel_full_pipeline.md#L87)
and
[query_service.py](<repo>/src/brain_researcher/services/neurokg/query_service.py#L4212)

### Concept exact reroute is migration-only, not benchmark ingest

This is separate from candidate-vs-benchmark evidence policy, but the boundary
must remain explicit:

- `Task` reroute: tracked ingest plus exact-id migration
- `Concept` reroute: exact-id migration only

Ordinary ingest rejects manifests marked `promotion_strategy=exact_id_migration_only`.

Anchor:
[gabriel_generator.py](<repo>/src/brain_researcher/services/neurokg/etl/gabriel_generator.py#L795)

## What Is Still Policy-Only

The following categories are adjudication policy, not a single loader-native
runtime table:

- `fulltext_retry`
- `concept_hold_candidate_only`
- disease-diagnosis scope reroutes
- broad behavioral or biomarker holds
- `retire_benchmark` decisions from bounded closeout packs

Operational rule:

- these buckets are valid because they are produced through tracked builders and
  reviewed notes
- they should not be described as globally enforced ingest categories unless the
  runtime code is updated to enforce them directly

## Allowed Promotion Paths

### Path A. Direct benchmark admission

Use when a generated row is accepted under the benchmark gate directly.

Path:

1. `br gabriel generate`
2. `br gabriel ingest --quality-profile high_precision`
3. row is accepted
4. row counts as benchmark-admitted

### Path B. Bounded salvage to benchmark-admitted

Use when a row was suppressed or held out of benchmark, but later becomes
salvageable under bounded review.

Required sequence:

1. row is suppressed or held out of benchmark
2. row enters a bounded review pack
3. row is classified as salvageable
4. non-title regeneration or equivalent bounded recovery is run
5. accepted regenerated rows are re-ingested through a tracked manifest
6. only accepted rows become benchmark-admitted

Current validated examples:

- title-only `Task/Region` regeneration
- specific concept regeneration
- measurable behavioral and biomarker regeneration

Anchors:
[balanced_title_only_regeneration_followup_20260313.md](<repo>/docs/planning/balanced_title_only_regeneration_followup_20260313.md)

### Path C. Candidate-only promotion

Use when a row is useful for recall or exploratory querying, but not
benchmarkable.

Required sequence:

1. row is adjudicated or policy-rerouted as candidate-only
2. row is written to `review_queue_candidate_only.jsonl`
3. `br gabriel ingest-candidate-only` replays it to Neo4j
4. row remains non-benchmark and query-visible only under `broad`

### Path D. Terminal closeout

Use when a row should stop consuming benchmark review budget.

Allowed terminal outcomes:

- `candidate_only`
- `retire_benchmark`

Not allowed:

- keeping empirically blocked rows indefinitely in benchmark retry state

## Decision Table

| Row type | Policy action | Live graph destination | Benchmark count? |
|---|---|---|---|
| `high_precision` accepted row | admit | benchmark-admitted | yes |
| raw `balanced_marginal` accepted/review row | keep candidate lane or review | candidate or review only | no |
| raw `kg_bootstrap` row | keep candidate lane | candidate-only or candidate snapshot | no |
| generic title-only concept | auto-reroute | candidate-only | no |
| salvageable title-only `Task/Region` | regenerate then tracked re-ingest | benchmark-admitted if accepted | yes, after promotion only |
| salvageable specific concept | regenerate then tracked re-ingest | benchmark-admitted if accepted | yes, after promotion only |
| composite/analysis concept hold | reroute | candidate-only | no |
| broad disease diagnosis title concept | reroute | candidate-only | no |
| broad behavioral or biomarker hold | hold, then candidate-only or retire | candidate-only or none | no |
| anatomy-only or unrecoverable benchmark residual | retire | none required | no |

## Query Semantics Freeze

This policy depends on the current query contract:

- `candidate_lane_mode="strict"` means benchmark-style verification
- `candidate_lane_mode="broad"` means coverage-first verification

Operational rule:

- benchmark reporting must use `strict`
- exploratory idea mining may use `broad`, but must treat `candidate_lane`
  provenance as first-class output

Anchors:
[server.py](<repo>/src/brain_researcher/services/mcp/server.py#L8715),
[server.py](<repo>/src/brain_researcher/services/mcp/server.py#L9080),
and
[server.py](<repo>/src/brain_researcher/services/mcp/server.py#L9141)

## Snapshot Rules For `evidence_snapshot_alpha`

When `evidence_snapshot_alpha.md` is cut, it must separate at least:

- `benchmark_admitted_rows`
- `candidate_only_rows`
- `hold_rows`
- `retired_rows`

It must also distinguish:

- live graph presence
- benchmark eligibility

Operational rule:

- a row can be present in live Neo4j and still be non-benchmark
- snapshot metrics must not collapse candidate presence into benchmark growth

## Explicit No-Go Rules

- Do not count candidate-only replay as benchmark growth.
- Do not count raw `balanced_marginal` or `kg_bootstrap` rows as benchmark
  evidence without tracked promotion.
- Do not re-open terminally retired benchmark rows without a new bounded pack.
- Do not keep ambiguous hold rows in perpetual benchmark limbo.
- Do not let query `broad` behavior redefine benchmark policy.

## Status

Status: `frozen-v1`

This document is sufficient to proceed to
[evidence_snapshot_alpha.md](<repo>/docs/planning/evidence_snapshot_alpha.md).

It does not by itself unblock `novelty_architecture`; it freezes the evidence
promotion boundary that later novelty work must respect.
