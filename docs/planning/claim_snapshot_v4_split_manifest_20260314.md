# Claim Snapshot V4 Split Manifest

Date: 2026-03-14

## Purpose

This note records the first real downstream split materialization built from the
threshold-meeting bounded snapshot in
[claim_snapshot_v4_20260314.md](<repo>/docs/planning/claim_snapshot_v4_20260314.md).

This is the first claim-side artifact that moves from split policy to a
materialized `train/dev/test` manifest.

## Inputs

- [claim_snapshot_v4.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4/off400_terminal_reviewed_20260314/claim_snapshot_v4.jsonl)
- [claim_snapshot_v4_summary.json](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4/off400_terminal_reviewed_20260314/claim_snapshot_v4_summary.json)
- [train_dev_test_split_proposal.md](<repo>/docs/planning/train_dev_test_split_proposal.md)
- [build_claim_snapshot_v4_split_manifest.py](<repo>/scripts/tools/etl/build_claim_snapshot_v4_split_manifest.py)
- [test_build_claim_snapshot_v4_split_manifest.py](<repo>/tests/unit/scripts/test_build_claim_snapshot_v4_split_manifest.py)

## Artifacts

- [claim_snapshot_v4_split_manifest.json](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_split/off400_downstream_20260314/claim_snapshot_v4_split_manifest.json)
- [claim_snapshot_v4_family_partitions.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_split/off400_downstream_20260314/claim_snapshot_v4_family_partitions.jsonl)
- [claim_snapshot_v4_train.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_split/off400_downstream_20260314/claim_snapshot_v4_train.jsonl)
- [claim_snapshot_v4_dev.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_split/off400_downstream_20260314/claim_snapshot_v4_dev.jsonl)
- [claim_snapshot_v4_test.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_split/off400_downstream_20260314/claim_snapshot_v4_test.jsonl)
- [claim_snapshot_v4_split_summary.json](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_split/off400_downstream_20260314/claim_snapshot_v4_split_summary.json)

## Summary

Source snapshot state:

- `snapshot_v4_rows_total = 25`
- `snapshot_v4_canonical_families_total = 24`
- `snapshot_v4_warning_or_conflict_families_total = 19`
- `snapshot_v4_target_type_buckets_total = 3`
- `threshold_all_met = true`

Materialized split:

- `train_families = 14`
- `dev_families = 5`
- `test_families = 5`
- `train_rows = 14`
- `dev_rows = 6`
- `test_rows = 5`

Integrity checks:

- `family_cross_split_violations = 0`
- `paper_leakage_violations = 0`
- `multi_partition_papers_total = 0`
- `dev_has_warning_or_conflict_family = true`
- `test_has_warning_or_conflict_family = true`
- `dev_has_clean_control_family = true`
- `test_has_clean_control_family = true`

## Interpretation

This closes the bounded claim-side split-materialization gap.

What is now true:

- a reviewed claim-side split artifact exists
- the split is family-based, leak-checked, and policy-conformant
- `dev` and `test` each preserve both clean controls and warning/conflict
  families

What is still not true:

- this is not a benchmark-scale claim dataset
- this is not a low-warning export
- this does not reopen `novelty_architecture`

The correct reading is:

- the bounded downstream split is now real
- the current split is still warning-heavy and seed-scale
- downstream task prototyping can use this manifest without claiming broad
  architecture readiness

## Next Move

The next step is not another split rewrite.

The next step is to bind this manifest into the readiness packet and keep the
remaining caveat narrow:

- `bounded split exists`
- `novelty_architecture remains blocked because the packet is still bounded and
  warning-heavy`
