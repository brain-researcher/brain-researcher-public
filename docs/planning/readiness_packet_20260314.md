# Readiness Packet

Date: 2026-03-14

## Purpose

This packet collects the bounded artifacts needed for the current Step 4
readiness review.

It is a packet for review, not a claim that the final joint gate has already
passed.

## Claim-Side Packet

- [claim_snapshot_v4_20260314.md](<repo>/docs/planning/claim_snapshot_v4_20260314.md)
- [claim_snapshot_v4.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4/off400_terminal_reviewed_20260314/claim_snapshot_v4.jsonl)
- [claim_snapshot_v4_summary.json](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4/off400_terminal_reviewed_20260314/claim_snapshot_v4_summary.json)
- [claim_snapshot_v4_review_pack.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4/off400_terminal_reviewed_20260314/claim_snapshot_v4_review_pack.jsonl)
- [claim_snapshot_v4_split_manifest_20260314.md](<repo>/docs/planning/claim_snapshot_v4_split_manifest_20260314.md)
- [claim_snapshot_v4_split_manifest.json](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_split/off400_downstream_20260314/claim_snapshot_v4_split_manifest.json)
- [claim_snapshot_v4_split_summary.json](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_split/off400_downstream_20260314/claim_snapshot_v4_split_summary.json)
- [claim_snapshot_v4_family_partitions.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_split/off400_downstream_20260314/claim_snapshot_v4_family_partitions.jsonl)
- [claim_snapshot_v4_train.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_split/off400_downstream_20260314/claim_snapshot_v4_train.jsonl)
- [claim_snapshot_v4_dev.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_split/off400_downstream_20260314/claim_snapshot_v4_dev.jsonl)
- [claim_snapshot_v4_test.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_split/off400_downstream_20260314/claim_snapshot_v4_test.jsonl)
- [claim_clustering_eval_pack_20260313.md](<repo>/docs/planning/claim_clustering_eval_pack_20260313.md)
- [claim_canonicalization_adr.md](<repo>/docs/planning/claim_canonicalization_adr.md)

## Graph-Side Packet

- [graph_snapshot_v1_1_20260314.md](<repo>/docs/planning/graph_snapshot_v1_1_20260314.md)
- [graph_snapshot_v1_1_manifest.json](<repo>/data/neurokg/raw/graph_snapshot_v1_1/bound_20260314/graph_snapshot_v1_1_manifest.json)
- [graph_contract_v1.md](<repo>/docs/planning/graph_contract_v1.md)
- [graph_baseline_report.md](<repo>/docs/planning/graph_baseline_report.md)
- [typed_path_regression_report.md](<repo>/docs/planning/typed_path_regression_report.md)
- [neurokg_graph_claim_execution_plan.md](<repo>/docs/planning/neurokg_graph_claim_execution_plan.md)

## Review Artifacts

- [readiness_review.md](<repo>/docs/planning/readiness_review.md)
- [go_no_go_memo.md](<repo>/docs/planning/go_no_go_memo.md)
- [task_charter.md](<repo>/docs/planning/task_charter.md)
- [train_dev_test_split_proposal.md](<repo>/docs/planning/train_dev_test_split_proposal.md)

## Packet Status

Claim-side packet status:

- threshold-meeting bounded `claim_snapshot_v4` exists
- a materialized claim-side downstream split now exists
- canonical claim layer is explicit and tested on a bounded slice
- the current split remains warning-heavy and bounded by design

Graph-side packet status:

- `Gate A1` and `Gate A2` are documented as passing
- typed path probes are documented as passing
- a discrete `graph_snapshot_v1_1` binding artifact is now explicitly present
  in this packet

Operational reading:

- this packet is sufficient for a formal readiness review
- the task-definition layer is now present
- the claim-side split-materialization layer is now present
- this packet is still conservative and bounded, but it is no longer missing
  the Step 11 task-definition artifacts or the bounded claim-side split export
