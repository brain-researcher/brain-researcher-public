# Claim Snapshot V4

Date: 2026-03-14

## Purpose

This note records the `v4` reviewed cut that consumes the
[claim_snapshot_terminal_shortfall_pack_20260314.md](<repo>/docs/planning/claim_snapshot_terminal_shortfall_pack_20260314.md).

This is the first reviewed snapshot cut that reaches the bounded split
thresholds defined in
[train_dev_test_split_proposal.md](<repo>/docs/planning/train_dev_test_split_proposal.md).

## Inputs

- [claim_snapshot_v3.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v3/off400_bridge_reviewed_20260314/claim_snapshot_v3.jsonl)
- [terminal_shortfall_pack.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_terminal_shortfall/off400_after_v3_20260314/terminal_shortfall_pack.jsonl)
- [terminal_shortfall_pack_reserve.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_terminal_shortfall/off400_after_v3_20260314/terminal_shortfall_pack_reserve.jsonl)
- [build_claim_snapshot_v4.py](<repo>/scripts/tools/etl/build_claim_snapshot_v4.py)
- [test_build_claim_snapshot_v4.py](<repo>/tests/unit/scripts/test_build_claim_snapshot_v4.py)

## Artifacts

- [claim_snapshot_v4.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4/off400_terminal_reviewed_20260314/claim_snapshot_v4.jsonl)
- [claim_snapshot_v4_review_pack.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4/off400_terminal_reviewed_20260314/claim_snapshot_v4_review_pack.jsonl)
- [claim_snapshot_v4_summary.json](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4/off400_terminal_reviewed_20260314/claim_snapshot_v4_summary.json)

## Summary

Starting point:

- `snapshot_v3_rows_total = 22`

Terminal review pass:

- `terminal_rows_reviewed_total = 4`
- `terminal_rows_retained_total = 3`
- `terminal_rows_excluded_total = 1`

Actual `claim_snapshot_v4` state:

- `snapshot_v4_rows_total = 25`
- `snapshot_v4_canonical_families_total = 24`
- `snapshot_v4_warning_or_conflict_families_total = 19`
- `snapshot_v4_target_type_buckets_total = 3`

Threshold status:

- `>= 24` canonical families: `met`
- `>= 6` warning/conflict families: `met`
- `>= 3` target-type buckets: `met`
- `threshold_all_met = true`

## Review Outcome

Retained into the snapshot as terminal warning-tier families:

- `concept:action_understanding`
- `region:prefrontal_and_limbic_brain_regions`
- `region:neural_circuits`

Reserve kept excluded:

- `concept:gait_speed`

## Interpretation

This cut clears the bounded split gate, but it does so with a clearly
warning-heavy terminal pass.

That matters for downstream interpretation:

- the gate is now satisfied on the reviewed bounded packet
- the last three added families are not clean control-style anchors
- they should be treated as terminal warning-tier breadth fillers, not as
  evidence that the broader novelty/claim snapshot problem is solved at scale

So the right conclusion is:

- the bounded split gate is now materially closed
- the repo should still describe this as a bounded, warning-heavy closeout
- this does not by itself reopen `novelty_architecture`

## Next Move

The next step is no longer family-count expansion.

The next step is to bind the now-materialized `claim_snapshot_v4` into the
downstream split artifact path and explicitly distinguish:

- bounded reviewed split readiness
- benchmark-scale novelty-architecture readiness
