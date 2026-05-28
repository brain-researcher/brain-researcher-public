# Claim Benchmark Charter

As of March 10, 2026.

This document is the week-1 benchmark contract for `claim_spine_readiness`.
Its purpose is to freeze a bounded, auditable comparison between claim-first
verification and mention-level fallback before the claim layer grows further.

## Purpose

`claim_benchmark_charter` defines:

- the benchmark question for `Workstream B`
- which sources are authoritative for claim-first behavior
- the exact bounded scope for the first benchmark
- how accepted vs review-queue records are determined
- how the held-out hypothesis set must be frozen
- which metrics are headline metrics for `Gate B`
- which failure modes invalidate the benchmark

## Benchmark Question

The first benchmark answers one question:

- Does claim-first verification in BR-KG produce evidence that is more
  auditable than mention-level fallback while remaining at least
  non-inferior on verdict quality for a fixed held-out hypothesis set?

This benchmark is not trying to prove full scientific truth. It is trying to
prove that the claim spine is a real runtime layer rather than a planned
schema.

## Authority Order

Use this precedence order when sources disagree:

1. `docs/specs/kg_verify_hypothesis_spec.md`
   Runtime contract for verifier inputs, outputs, strictness modes, and the
   claim-first preference rule.
2. `src/brain_researcher/services/neurokg/schemas/node_schemas.py`
   Canonical node fields and deterministic ID rules for `Claim`,
   `EvidenceSpan`, and `MeasurementRun`.
3. `src/brain_researcher/services/neurokg/schemas/edge_schemas.py`
   Canonical edge fields for `MENTIONS`, `MENTIONS_REGION`,
   `REPORTS_CLAIM`, `SUPPORTS`, and `GENERATED`.
4. `docs/neurokg/gabriel_sample_quickstart.md`
   Bounded sample ingest contract and expected review-queue behavior.
5. `src/brain_researcher/services/neurokg/etl/loaders/gabriel_loader.py`
   Operational ingest behavior for accepted records, created edges, and
   review-queue routing.
6. `src/brain_researcher/services/neurokg/etl/loaders/gabriel_measurements.py`
   Measurement thresholds and mandatory provenance-field logic.

Operational rule:

- The benchmark is invalid if it depends on behavior that is not supported by
  both the verifier contract and the actual sample ingest path.

## Fixed Scope

The first benchmark is bounded on purpose.

In scope:

- the GABRIEL sample source at
  `tests/fixtures/neurokg/gabriel_measurements.sample.jsonl`
- the local runtime copy at `data/neurokg/raw/gabriel/measurements.jsonl`
- `Publication`, `Claim`, `EvidenceSpan`, and `MeasurementRun` nodes
- `MENTIONS`, `MENTIONS_REGION`, `REPORTS_CLAIM`, `SUPPORTS`, and `GENERATED`
  edges
- `kg_verify_hypothesis` output fields required by spec:
  `verdict`, `confidence`, `supporting_evidence`, `conflicting_evidence`,
  `neutral_evidence`, `top_paths`, `subgraph`, and `provenance`

Out of scope for this charter:

- full-corpus GABRIEL ingest
- cross-paper claim canonicalization
- contradiction mining
- idea-generation workflows
- downstream graph learning or operator modeling

## Benchmark Conditions

Run the same frozen hypothesis set under two conditions:

| Condition | Description | Intended Use |
|---|---|---|
| `claim_first` | Bounded sample graph with `Claim`, `EvidenceSpan`, `MeasurementRun`, `REPORTS_CLAIM`, `SUPPORTS`, and `GENERATED` present | Headline condition |
| `mention_fallback_control` | Isolated control snapshot or isolated test DB where mention edges remain but claim/evidence/run edges are absent or disabled | Comparison baseline |

Operational rule:

- Do not compare claim-first against a control run that differs in hypothesis
  set, seed hints, or verifier parameters.
- If the repo does not yet expose a runtime switch for evidence mode, the
  comparison must be done with isolated graph snapshots rather than ad hoc code
  edits to the verifier.

## Accepted Record Gate

Only accepted sample records may contribute to the benchmark graph.

Accepted records must satisfy the GABRIEL high-precision gate:

- `mention_strength >= 0.70`
- `mapping_confidence >= 0.85`
- `claim_strength >= 0.65`
- `method_rigor >= 0.50`
- `provenance_completeness >= 1.0`
- `evidence_quality != low`

Required provenance fields for accepted records:

- `run_id`
- `prompt_hash`
- `template_hash`
- `model`
- `raw_response_path`
- `loader_version`
- `timestamp`

Rejected or marginal records must be routed to:

- `data/neurokg/raw/gabriel/review_queue.jsonl`

Operational rule:

- No record that lands in the review queue may be counted as accepted benchmark
  evidence until explicitly adjudicated and re-ingested through a tracked path.

## Required IDs And Evidence Path

The bounded benchmark assumes deterministic IDs:

- `Claim.id = claim:<md5(paper_id:text)>`
- `EvidenceSpan.id = evidence:<md5(paper_id:claim_id:quote)>`
- `MeasurementRun.id = run:<run_id>`

The minimum auditable path is:

- `Publication -> REPORTS_CLAIM -> Claim <- SUPPORTS <- EvidenceSpan`
- `MeasurementRun -> GENERATED -> Claim`
- `MeasurementRun -> GENERATED -> EvidenceSpan`

`Gate B` cannot pass if this path is not queryable end to end.

## Held-Out Hypothesis Set

The benchmark must freeze two slices:

- `calibration` slice:
  6 to 10 hypotheses used only for smoke tests and wiring checks
- `held_out` slice:
  minimum 12 hypotheses, target 18 to 24 hypotheses, used for headline
  reporting

The held-out slice must be stratified across:

- `supported`
- `conflicted` or `mixed`
- `insufficient_evidence`

Every hypothesis record must include:

- `hypothesis_id`
- `text`
- `entity_hints`
- `expected_verdict`
- `expected_anchor_entities`
- `notes`

Preferred additional fields when known:

- `expected_supporting_publications`
- `expected_conflicting_publications`
- `review_status`

Operational rules:

- Freeze the held-out manifest before the first headline benchmark run.
- Do not reuse calibration hypotheses in headline metrics.
- Do not change expected labels after reading system outputs unless the change
  is recorded through adjudication.

## Frozen Verifier Parameters

Headline runs must use:

- `strictness = high_recall`
- `max_evidence = 60`
- `max_paths = 60`
- `include_subgraph = true`
- `include_path_details = true`

Secondary sensitivity runs may use:

- `strictness = balanced`

Operational rule:

- Headline metrics must never mix outputs from different strictness settings.

## Review And Adjudication Protocol

Each held-out hypothesis must be labeled without looking at the model verdict
first.

Review flow:

1. `VE` prepares hypothesis records and source-paper anchors.
2. `RA` reviews quote-level evidence, provenance fields, and expected verdict.
3. Disagreements between `VE` and `RA` are escalated to `PI`.
4. Final adjudicated labels are frozen before the headline comparison.

For each adjudicated hypothesis, record:

- final verdict label
- support/conflict rationale
- source publication IDs
- quote or section/page anchor when available
- whether the example remains valid for held-out evaluation

Operational rule:

- Review-queue items may inform adjudication, but they may not be counted as
  accepted graph evidence unless promoted through a tracked re-ingest path.

## Headline Metrics

Headline metrics for `Gate B`:

- held-out verdict accuracy
- held-out macro-F1 across `supported`, `conflicted|mixed`,
  `insufficient_evidence`
- auditability pass rate
- claim-path availability rate
- mean provenance completeness for returned evidence items
- non-empty `top_paths` rate for hypotheses with non-empty evidence
- claim-first minus control delta for verdict accuracy
- claim-first minus control delta for auditability

`auditability pass rate` means the returned evidence can be traced to:

- a `Publication`
- a `Claim`
- an `EvidenceSpan`
- a `MeasurementRun`
- the required provenance fields listed above

Secondary metrics:

- accepted vs rejected record counts
- review-queue routing rate
- `supporting_evidence` precision on adjudicated supported cases
- `conflicting_evidence` precision on adjudicated conflicted cases
- median `query_time_s`

## Gate B Pass Criteria

`Gate B` passes only if all of the following are true:

- the `claim_first` condition is fully runnable on the bounded sample path
- the minimum auditable claim-first path is live end to end
- no accepted benchmark evidence is missing required provenance fields
- claim-first verdict quality is at least non-inferior to the
  `mention_fallback_control` on the held-out slice
- claim-first auditability pass rate is at least `0.90`
- claim-first auditability is at least `0.20` absolute better than the control,
  or the control cannot produce an auditable claim path at all
- non-empty `top_paths` are present for at least `0.80` of held-out hypotheses
  that return evidence

## Benchmark Invalidators

The benchmark is invalid if any of the following happen:

- the held-out manifest changes after headline evaluation begins
- the claim-first and control runs use different hypothesis sets
- the claim-first and control runs use different verifier parameters
- review-queue records are silently mixed into the accepted graph snapshot
- provenance completeness is computed with a different required-field set
- verdict labels are changed without adjudication notes

## No-Go Rule

Do not claim claim-spine readiness if, by the end of week 6, the bounded sample
path still cannot support the auditable chain
`Publication -> REPORTS_CLAIM -> Claim <- SUPPORTS <- EvidenceSpan` plus
`MeasurementRun -> GENERATED -> Claim|EvidenceSpan`.

## Outputs Required Next

- `claim_hypotheses_calibration_v1.jsonl`
- `claim_hypotheses_heldout_v1.jsonl`
- `claim_review_guidelines_v1.md`
- `claim_baseline_report.md`
- `claim_first_vs_mention_report.md`
- `claim_snapshot_v1`
