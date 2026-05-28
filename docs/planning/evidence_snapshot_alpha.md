# Evidence Snapshot Alpha

Date: 2026-03-13

## Purpose

This document is the first Week 10 snapshot artifact referenced in
[neurokg_evidence_coverage_expansion_plan.md](<repo>/docs/planning/neurokg_evidence_coverage_expansion_plan.md#L94).

It freezes one concrete, policy-aligned evidence cut after the `off400`
`balanced_marginal` title-only follow-up track has been fully adjudicated.

It is intentionally not a repo-wide graph inventory.

## Snapshot ID

`off400_balanced_marginal_alpha_20260313`

## Authority Order

This snapshot follows:

1. [promotion_policy_v1.md](<repo>/docs/planning/promotion_policy_v1.md)
2. [claim_benchmark_charter.md](<repo>/docs/planning/claim_benchmark_charter.md)
3. bounded closeout notes under [docs/planning](<repo>/docs/planning)

Operational rule:

- policy determines which bucket a row belongs to
- this snapshot records the resulting frozen counts
- this snapshot does not redefine policy

## Scope

Included:

- the `off400` `balanced_marginal` benchmark follow-up track
- bounded title-only regeneration outcomes
- bounded concept-hold adjudication outcomes
- bounded scope-review lane outcomes
- bounded residual closeout outcomes

Excluded:

- repo-wide `high_precision` benchmark inventory
- repo-wide candidate-lane inventory in live Neo4j
- raw `kg_bootstrap` or raw `balanced_marginal` volume that was never promoted
- future evidence growth beyond the `off400` closeout track

## Source Artifacts

Primary sources:

- [promotion_policy_v1.md](<repo>/docs/planning/promotion_policy_v1.md)
- [balanced_title_only_regeneration_followup_20260313.md](<repo>/docs/planning/balanced_title_only_regeneration_followup_20260313.md)
- [balanced_residual_followup_20260313.md](<repo>/docs/planning/balanced_residual_followup_20260313.md)
- [balanced_final_tail_closeout_20260313.md](<repo>/docs/planning/balanced_final_tail_closeout_20260313.md)
- [balanced_residual_hold_unresolved_ledger_20260313.md](<repo>/docs/planning/balanced_residual_hold_unresolved_ledger_20260313.md)

## Bucket Definitions

### Benchmark-admitted

Rows count here only if they were promoted through a tracked, bounded salvage
path and then accepted through ordinary benchmark ingest behavior.

### Candidate-only

Rows count here if they were adjudicated or terminally downgraded to the
candidate lane. They may still exist in live Neo4j, but they do not count as
benchmark-admitted evidence.

### Hold/manual

Rows count here only if they remain outside both benchmark-admitted and
candidate-only at snapshot time.

### Retire-benchmark

Rows count here if they were explicitly removed from active benchmark follow-up.

## Frozen Counts

### 1. Benchmark-admitted salvage

Frozen count: `15`

Composition:

- `8` accepted `Task/Region` title-only regenerations
- `4` accepted specific-concept regenerations
- `1` accepted measurable biomarker regeneration
- `2` accepted measurable behavioral regeneration

Source anchors:

- [balanced_title_only_regeneration_followup_20260313.md](<repo>/docs/planning/balanced_title_only_regeneration_followup_20260313.md)

Operational reading:

- these `15` rows are the alpha snapshot's benchmark-admitted growth from the
  `off400` closeout track
- they count because they passed tracked regeneration plus tracked benchmark
  re-ingest

### 2. Candidate-only rows

Frozen count: `32`

Composition:

- `13` composite/analysis concept holds downgraded to candidate-only
- `2` disease/diagnosis title-only concepts downgraded to candidate-only
- `4` broad concept no-non-title rows downgraded to candidate-only
- `9` terminal blocked `Task/Concept` rows downgraded to candidate-only
- `4` final-tail concept holds downgraded to candidate-only

Source anchors:

- [balanced_title_only_regeneration_followup_20260313.md](<repo>/docs/planning/balanced_title_only_regeneration_followup_20260313.md)
- [balanced_residual_followup_20260313.md](<repo>/docs/planning/balanced_residual_followup_20260313.md)
- [balanced_final_tail_closeout_20260313.md](<repo>/docs/planning/balanced_final_tail_closeout_20260313.md)

Operational reading:

- these rows remain available for coverage-first querying and later review
- they do not count as benchmark growth in this snapshot

### 3. Retire-benchmark rows

Frozen count: `16`

Composition:

- `8` no-non-title rows retired from benchmark follow-up
- `5` anatomy-only rows retired after Neo4j-backed fuller-text retry
- `3` final-tail retry residuals retired from benchmark follow-up

Source anchors:

- [balanced_residual_followup_20260313.md](<repo>/docs/planning/balanced_residual_followup_20260313.md)
- [balanced_final_tail_closeout_20260313.md](<repo>/docs/planning/balanced_final_tail_closeout_20260313.md)

Operational reading:

- these rows are intentionally out of active benchmark accounting
- retirement here is a benchmark-policy outcome, not a claim that the rows have
  no exploratory value

### 4. Hold/manual rows

Frozen count: `0`

Reason:

- the earlier residual hold ledger contained `4` hold/manual rows, but those
  rows were subsequently resolved in the final-tail closeout:
  - all `4` moved to candidate-only

Source anchors:

- [balanced_residual_hold_unresolved_ledger_20260313.md](<repo>/docs/planning/balanced_residual_hold_unresolved_ledger_20260313.md)
- [balanced_final_tail_closeout_20260313.md](<repo>/docs/planning/balanced_final_tail_closeout_20260313.md)

### 5. Active benchmark backlog

Frozen count: `0`

Source anchors:

- [balanced_residual_followup_20260313.md](<repo>/docs/planning/balanced_residual_followup_20260313.md)
- [balanced_final_tail_closeout_20260313.md](<repo>/docs/planning/balanced_final_tail_closeout_20260313.md)

Operational reading:

- the `off400` benchmark closeout track is closed
- any new benchmark work after this snapshot is a fresh expansion phase, not a
  continuation of the same residual cleanup

## Summary Table

| Bucket | Frozen count | Counts as benchmark growth? |
|---|---:|---|
| benchmark-admitted salvage | `15` | yes |
| candidate-only | `32` | no |
| retire-benchmark | `16` | no |
| hold/manual | `0` | no |
| active benchmark backlog | `0` | no |

## What This Snapshot Proves

This alpha snapshot is strong enough to support the following claims:

- the benchmark-vs-candidate boundary is no longer only verbal; it has been
  applied to a concrete bounded track
- bounded salvage can produce benchmark-admitted evidence without reopening the
  whole candidate lane
- the residual benchmark tail for this track has been fully resolved

## What This Snapshot Does Not Prove

This alpha snapshot does not justify any of the following broader claims:

- that the repo-wide benchmark graph is fully frozen
- that all live candidate-only rows have been inventoried globally
- that `balanced_marginal` is itself a benchmark lane
- that future candidate growth can be counted as benchmark growth without
  another tracked promotion cycle

## Operational Interpretation

The correct reading is:

- `benchmark growth` from this bounded alpha cut = `15`
- `coverage retained outside benchmark` from this bounded alpha cut = `32`
- `benchmark cleanup completed` for this bounded alpha cut = `16 retired` and
  `0 active backlog`

This is enough to say that Week 10 now has both:

- a frozen promotion boundary in
  [promotion_policy_v1.md](<repo>/docs/planning/promotion_policy_v1.md)
- a first concrete policy-aligned snapshot in this document

It is not enough by itself to unblock `novelty_architecture`.

## Next Move

Proceed to the claim aggregation / canonicalization step:

- draft the claim canonicalization ADR

This snapshot removes the benchmark-vs-candidate ambiguity that would have made
that next step unstable.
