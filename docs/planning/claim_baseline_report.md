# Claim Baseline Report

As of March 10, 2026.

This report is the first baseline for `claim_spine_readiness`.

## Baseline Provenance

This report combines three evidence sources:

1. High-precision fixture analysis of
   `data/neurokg/raw/gabriel/measurements.jsonl`
2. Runtime review-queue sanity check of
   `data/neurokg/raw/gabriel/review_queue.jsonl`
3. Existing GABRIEL run manifests under `data/neurokg/raw/gabriel/runs/`

Additional repo anchors used for interpretation:

- `docs/specs/kg_verify_hypothesis_spec.md`
- `docs/neurokg/gabriel_sample_quickstart.md`
- `src/brain_researcher/services/neurokg/etl/loaders/gabriel_measurements.py`
- `src/brain_researcher/services/neurokg/etl/loaders/gabriel_loader.py`
- `src/brain_researcher/services/neurokg/schemas/node_schemas.py`
- `src/brain_researcher/services/neurokg/schemas/edge_schemas.py`

Important implementation note:

- The sample path accepts explicit `claim_id` and `span_id` values when present
  and falls back to generated IDs only when absent. That means the sample
  fixture is valid for benchmarking, but it is not a pure demonstration of the
  schema fallback ID path.

## High-Precision Fixture Baseline

Bounded sample analyzed: `3` records total.

| Metric | Value |
|---|---:|
| Records parsed | `3` |
| Records accepted by high-precision gate | `2` |
| Records rejected by high-precision gate | `1` |
| Unique rejected candidates in runtime review queue | `1` |
| Raw lines currently present in runtime review queue | `2` |

Interpretation:

- The bounded sample proves the claim-spine object model can be represented.
- The current runtime review queue file is not a canonical metric by itself
  because it contains duplicate rejections for the same rejected record.

### Accepted Records

| Paper | Target | Claim ID | Evidence ID | Run ID | Gate Summary |
|---|---|---|---|---|---|
| `pmid:40000001` | `concept:working_memory` | `claim:wm_dlpfc` | `evidence:wm_dlpfc_1` | `run-20260224-001` | mention `1.0`, mapping `0.943`, claim `0.885`, rigor `0.97`, evidence `high`, provenance `1.0` |
| `pmid:40000002` | `schaefer400-7n:L_Cont_7` | `claim:conflict_lcont7` | `evidence:conflict_lcont7_1` | `run-20260224-002` | mention `1.0`, mapping `0.901`, claim `0.79`, rigor `0.94`, evidence `high`, provenance `1.0` |

### Rejected Record

| Paper | Target Label | Run ID | Rejection Reasons |
|---|---|---|---|
| `pmid:40000003` | `Executive Control` | `run-20260224-003` | `mention_strength_below_threshold`, `mapping_confidence_below_threshold`, `claim_strength_below_threshold`, `method_rigor_below_threshold`, `provenance_incomplete`, `evidence_quality_low` |

Rejected-record details:

- `claim_id` is absent
- `span_id` is absent
- target canonical ID is absent
- provenance completeness is only `0.429`

## Expected Claim-First Footprint From The Bounded Sample

If the accepted sample records are ingested cleanly, the minimum expected
claim-first footprint is:

- `2` accepted `Claim` nodes
- `2` accepted `EvidenceSpan` nodes
- `2` accepted `MeasurementRun` nodes
- `2` `REPORTS_CLAIM` edges
- `2` `SUPPORTS` edges
- `4` `GENERATED` edges
- `1` `MENTIONS` edge
- `1` `MENTIONS_REGION` edge

This is the smallest auditable object set that can support the week-1 bootstrap
benchmark manifests.

## Existing Run Baselines

| Run | Quality Profile | Records Accepted | Review Queue | Nodes Created | Relationships Created | Interpretation |
|---|---|---:|---:|---:|---:|---|
| `e2e-gabriel-20260224` | `balanced` | `0` | `5` | `0` | `0` | Heuristic bounded run did not clear the gate |
| `gabriel-pubget-smoke-20260225` | `kg_bootstrap` | `5` | `0` | `22` | `25` | Throughput is viable under relaxed thresholds |
| `gabriel-gemini-sdk-batch100-off100-20260225_013625` | `kg_bootstrap` | `99` | `1` | `396` | `496` | Claim spine can materialize at moderate scale under relaxed thresholds |
| `gabriel-full-20260224_heuristic` | `balanced_marginal` | `1,347` | `48,389` | `5,392` | `6,735` | Heuristic full run has very high review burden |

Interpretation:

- The bounded high-precision fixture is strong enough to prove schema shape.
- The current heuristic bounded run is not strong enough to serve as headline
  evidence.
- Relaxed `kg_bootstrap` runs demonstrate operational throughput, but they are
  not equivalent to the benchmark charter's high-precision claim-first gate.

## Benchmark Manifest Status

The newly published manifests are intentionally bootstrap-sized:

- `claim_hypotheses_calibration_v1.jsonl`: `1` grounded calibration hypothesis
- `claim_hypotheses_heldout_v1.jsonl`: `2` grounded held-out hypotheses

Why they are undersized:

- The current bounded sample only contains `3` grounded candidates total.
- Of those `3`, only `2` are accepted high-precision records.
- The sample does not yet provide a grounded `conflicted|mixed` claim example.

Operational implication:

- The manifests are sufficient to smoke-test claim-first plumbing.
- They are not sufficient to satisfy the charter's target held-out size or class
  balance requirements for `Gate B`.

## Current Gate Verdict

`Gate B` status: `NO-GO`

Reasons:

- The bounded sample supports only a bootstrap manifest, not a real held-out
  benchmark.
- A claim-first versus mention-fallback comparison has not yet been run on
  isolated snapshots.
- The current local review queue includes duplicate rejections, so queue counts
  need canonicalization before they can be used as metrics.
- There is still no evidence in this baseline that the auditable claim-first
  path has been measured through `kg_verify_hypothesis` end to end.

## Immediate Next Actions

- Expand the bounded benchmark with additional audited high-precision examples,
  especially true `conflicted|mixed` cases.
- Freeze a larger held-out manifest before headline evaluation starts.
- Run `claim_first` and `mention_fallback_control` on isolated snapshots with
  the same frozen hypotheses.
- Normalize review-queue counting to unique rejected candidates rather than raw
  appended lines.
- Publish `claim_first_vs_mention_report.md` only after the controlled
  comparison exists.
