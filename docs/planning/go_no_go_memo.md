# Go / No-Go Memo

Date: 2026-03-14

## Decision

Decision for starting new `novelty_architecture` or relation-as-operator work:

- `NO-GO`

Decision for closing Step 4 on the current bounded packet:

- `GO`

## Why This Is Not A Contradiction

The repo is now in a better state than before:

- graph substrate gates are documented as passing
- a threshold-meeting bounded reviewed `claim_snapshot_v4` now exists
- a bounded claim-side downstream split now exists
- readiness documents now exist
- task definitions and split policy now exist

But the execution plan’s final joint gate is stricter than “the bounded claim
snapshot and split exist.”

The remaining caution is not missing paperwork. The remaining caution is scope:
the packet is still bounded and warning-heavy rather than a materialized
benchmark-scale dataset.

## Evidence

Claim-side support for continuing:

- [claim_snapshot_v4_20260314.md](<repo>/docs/planning/claim_snapshot_v4_20260314.md)
- [claim_snapshot_v4_summary.json](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4/off400_terminal_reviewed_20260314/claim_snapshot_v4_summary.json)
- [claim_snapshot_v4_split_manifest_20260314.md](<repo>/docs/planning/claim_snapshot_v4_split_manifest_20260314.md)
- [claim_snapshot_v4_split_manifest.json](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_split/off400_downstream_20260314/claim_snapshot_v4_split_manifest.json)
- [claim_snapshot_v4_split_summary.json](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_split/off400_downstream_20260314/claim_snapshot_v4_split_summary.json)

Graph-side support for continuing:

- [graph_snapshot_v1_1_20260314.md](<repo>/docs/planning/graph_snapshot_v1_1_20260314.md)
- [graph_snapshot_v1_1_manifest.json](<repo>/data/neurokg/raw/graph_snapshot_v1_1/bound_20260314/graph_snapshot_v1_1_manifest.json)
- [graph_baseline_report.md](<repo>/docs/planning/graph_baseline_report.md)
- [typed_path_regression_report.md](<repo>/docs/planning/typed_path_regression_report.md)

Packet index:

- [readiness_packet_20260314.md](<repo>/docs/planning/readiness_packet_20260314.md)

Review basis:

- [readiness_review.md](<repo>/docs/planning/readiness_review.md)
- [neurokg_graph_claim_execution_plan.md](<repo>/docs/planning/neurokg_graph_claim_execution_plan.md)
- [task_charter.md](<repo>/docs/planning/task_charter.md)
- [train_dev_test_split_proposal.md](<repo>/docs/planning/train_dev_test_split_proposal.md)

## Decision Table

Claim-side freeze quality:

- `GO`

Reason:

- bounded reviewed freeze exists
- bounded split manifest exists
- adjudication history exists
- canonical claim layer is explicit

Graph substrate quality:

- `GO`

Reason:

- `A1` and `A2` are documented as passing
- gate-critical typed paths are documented as passing

Joint final gate for new architecture work:

- `NO-GO`

Reason:

- the current packet is still bounded and warning-heavy
- the split layer is materialized, but only on a bounded reviewed packet
- the final gate should not be treated as equivalent to broad production-ready
  architecture clearance

## Consequence

What is allowed now:

- treat Step 4 closeout as complete on the current bounded packet
- continue bounded claim-side reasoning tasks against the current
  `claim_snapshot_v4` split manifest
- use the frozen task charter and split policy for later benchmark expansion

What is not allowed now:

- declare `novelty_architecture` unblocked
- start a new relation-as-operator phase
- claim broad benchmark-scale readiness from this bounded packet alone

## Next Action

The next action is narrow and concrete:

1. keep the bounded packet frozen as-is
2. treat the current `claim_snapshot_v4` split as the bounded downstream split
   of record
3. only materialize broader split manifests after family quality and scale
   increase beyond the current warning-heavy packet
