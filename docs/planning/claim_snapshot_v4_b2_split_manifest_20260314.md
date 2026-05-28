# Claim Snapshot V4 B2 Split Manifest

Date: 2026-03-14

## Purpose

This note records the conflict-expanded bounded split materialization for the reviewed-seed
`B2 failure-aware claim inclusion/exclusion reasoning` task.

This is not a large benchmark split. It is the smallest leakage-safe split that
keeps `B2` from remaining a single unsliced review file.

## Inputs

- [claim_snapshot_v4_b2_task_manifest_20260314.md](<repo>/docs/planning/claim_snapshot_v4_b2_task_manifest_20260314.md)
- [build_claim_snapshot_v4_b2_split_manifest.py](<repo>/scripts/tools/etl/build_claim_snapshot_v4_b2_split_manifest.py)
- [run_claim_snapshot_v4_b2_baseline_eval.py](<repo>/scripts/tools/etl/run_claim_snapshot_v4_b2_baseline_eval.py)

## Split Artifacts

- [claim_snapshot_v4_b2_split_manifest.json](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_b2_split/off400_reviewed_seed_conflict_expanded_20260314/claim_snapshot_v4_b2_split_manifest.json)
- [claim_snapshot_v4_b2_train.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_b2_split/off400_reviewed_seed_conflict_expanded_20260314/claim_snapshot_v4_b2_train.jsonl)
- [claim_snapshot_v4_b2_dev.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_b2_split/off400_reviewed_seed_conflict_expanded_20260314/claim_snapshot_v4_b2_dev.jsonl)
- [claim_snapshot_v4_b2_test.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_b2_split/off400_reviewed_seed_conflict_expanded_20260314/claim_snapshot_v4_b2_test.jsonl)
- [claim_snapshot_v4_b2_split_summary.json](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_b2_split/off400_reviewed_seed_conflict_expanded_20260314/claim_snapshot_v4_b2_split_summary.json)

## Baseline Artifacts

- [claim_snapshot_v4_b2_baseline_eval_summary.json](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_b2_baseline_eval/off400_reviewed_seed_conflict_expanded_20260314/claim_snapshot_v4_b2_baseline_eval_summary.json)

## Summary

Curated split:

- `train = 21`
- `dev = 7`
- `test = 9`

Integrity checks:

- `paper_leakage_violations = 0`
- `canonical_leakage_violations = 0`
- `dev_has_retain_singleton = true`
- `test_has_retain_singleton = true`
- `dev_has_warning_retain = true`
- `test_has_warning_retain = true`
- `dev_has_exclude = true`
- `test_has_exclude = true`
- `dev_has_conflict = true`
- `test_has_conflict = true`

Important bounded caveat now:

- this is still a very small reviewed seed
- conflict now appears in both eval partitions, but only after a bounded
  live-reviewed `v5_conflict` expansion

## Baseline Results

Majority baseline:

- majority label = `retain_singleton_with_warning`
- `dev accuracy = 0.4286`
- `test accuracy = 0.3333`

Metadata heuristic baseline:

- `conflict role -> retain_conflict_cluster_with_warning`
- `modality_or_method_leakage -> exclude_from_snapshot`
- `no failure tags -> retain_singleton`
- `else -> retain_singleton_with_warning`

Results:

- `dev accuracy = 1.0`
- `dev macro_f1 = 1.0`
- `test accuracy = 0.7778`
- `test macro_f1 = 0.7917`

## Interpretation

This is a real bounded `B2` split and the first nontrivial baseline over it.

What is now true:

- `B2` has a leak-checked split
- both `dev` and `test` now contain real conflict rows
- the baseline is better than majority
- the task is no longer only a reviewed seed with no evaluation path

What is still not true:

- the split is still very small
- one of the conflict families still comes from a bounded live-reviewed
  expansion pack rather than from a broader reviewed corpus
- the heuristic still relies heavily on review metadata and failure tags

## Next Move

The next useful move is no longer “make test contain conflict.”

The next useful move is:

- add more than one additional reviewed conflict family so B2 conflict coverage
  is not carried by a single bounded live expansion
- or add a less metadata-dependent `B2` baseline
