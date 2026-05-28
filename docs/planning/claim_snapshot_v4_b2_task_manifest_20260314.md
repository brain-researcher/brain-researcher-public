# Claim Snapshot V4 B2 Task Manifest

Date: 2026-03-14

## Purpose

This note records the conflict-expanded `B2 failure-aware claim
inclusion/exclusion reasoning` reviewed seed.

Unlike the bounded `B1` family-stance task, this `B2` artifact is still a
reviewed adjudication seed, not a split benchmark.

## Inputs

- [task_charter.md](<repo>/docs/planning/task_charter.md)
- [build_claim_snapshot_v4_b2_task_manifest.py](<repo>/scripts/tools/etl/build_claim_snapshot_v4_b2_task_manifest.py)
- [claim_snapshot_v4_b2_conflict_expansion_20260314.md](<repo>/docs/planning/claim_snapshot_v4_b2_conflict_expansion_20260314.md)
- reviewed packs:
  [claim_clustering_adjudication_pack.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v1/bounded_v1_20260314/claim_clustering_adjudication_pack.jsonl),
  [claim_snapshot_v2_expansion_review_pack.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v2/off400_seed_reviewed_20260314/claim_snapshot_v2_expansion_review_pack.jsonl),
  [claim_snapshot_v3_review_pack.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v3/off400_bridge_reviewed_20260314/claim_snapshot_v3_review_pack.jsonl),
  [claim_snapshot_v4_review_pack.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4/off400_terminal_reviewed_20260314/claim_snapshot_v4_review_pack.jsonl),
  [claim_snapshot_v4_b2_conflict_expansion_pack.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_b2_conflict_expansion/off400_live_attention_20260314/claim_snapshot_v4_b2_conflict_expansion_pack.jsonl)

## Artifacts

- [claim_snapshot_v4_b2_task_manifest.json](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_b2_task_manifest/off400_reviewed_seed_conflict_expanded_20260314/claim_snapshot_v4_b2_task_manifest.json)
- [claim_snapshot_v4_b2_examples.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_b2_task_manifest/off400_reviewed_seed_conflict_expanded_20260314/claim_snapshot_v4_b2_examples.jsonl)
- [claim_snapshot_v4_b2_task_summary.json](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_b2_task_manifest/off400_reviewed_seed_conflict_expanded_20260314/claim_snapshot_v4_b2_task_summary.json)

## Task Operationalization

Input unit:

- one reviewed paper-local claim row

Label space:

- `retain_singleton`
- `retain_singleton_with_warning`
- `retain_conflict_cluster_with_warning`
- `exclude_from_snapshot`

Construction rule:

- merge reviewed adjudication packs from `v1` through `v4`
- append a bounded `v5_conflict` live-reviewed expansion pack
- dedupe by `source_claim_id`
- let the latest review stage win on conflicts

This yields a compact but much more useful reviewed seed than looking only at
`v4`, whose local review pack is too small on its own.

## Summary

Real task counts:

- `raw_rows_total = 46`
- `deduped_examples_total = 37`
- `duplicate_overwrites_total = 9`

Label distribution:

- `retain_singleton = 5`
- `retain_singleton_with_warning = 18`
- `retain_conflict_cluster_with_warning = 4`
- `exclude_from_snapshot = 10`

Stage mix after dedupe:

- `v1 = 7`
- `v2 = 12`
- `v3 = 12`
- `v4 = 4`
- `v5_conflict = 2`

Target-type mix:

- `Concept = 14`
- `Region = 15`
- `Task = 8`

## Interpretation

This is now a stronger reviewed seed than the first B2 cut, but it is still a
bounded reviewed seed.

What is now true:

- `B2` no longer exists only as charter prose
- the repo now has a concrete, labeled adjudication task file for inclusion vs
  exclusion reasoning
- the reviewed seed now contains `2` conflict families rather than `1`
- the task now also has a bounded split and first baseline in
  [claim_snapshot_v4_b2_split_manifest_20260314.md](<repo>/docs/planning/claim_snapshot_v4_b2_split_manifest_20260314.md)

What is still not true:

- this is not a split benchmark
- this is not a final train/dev/test dataset
- the label mix is still dominated by warning-retain and exclusion cases

## Next Move

The next useful move for `B2` is no longer “make the first split.”

The next useful move is either:

- make B2 conflict expansion less manual than the current bounded live-reviewed
  `v5_conflict` pack
- or add a less metadata-dependent baseline over the current bounded split
