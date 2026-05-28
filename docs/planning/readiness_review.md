# Readiness Review

Date: 2026-03-14

## Scope

This review evaluates whether the current graph-side and claim-side artifacts
are sufficient to unblock the next architecture phase described in
[neurokg_graph_claim_execution_plan.md](<repo>/docs/planning/neurokg_graph_claim_execution_plan.md).

The relevant Step 4 expectation is a joint readiness review for:

- graph learning and typed operator work
- claim-centric reasoning and later idea-mining use

This review is bounded to the current packet:

- [readiness_packet_20260314.md](<repo>/docs/planning/readiness_packet_20260314.md)

## Inputs Reviewed

Graph-side evidence:

- [graph_contract_v1.md](<repo>/docs/planning/graph_contract_v1.md)
- [graph_baseline_report.md](<repo>/docs/planning/graph_baseline_report.md)
- [typed_path_regression_report.md](<repo>/docs/planning/typed_path_regression_report.md)

Claim-side evidence:

- [claim_snapshot_v4_20260314.md](<repo>/docs/planning/claim_snapshot_v4_20260314.md)
- [claim_snapshot_v4_summary.json](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4/off400_terminal_reviewed_20260314/claim_snapshot_v4_summary.json)
- [claim_snapshot_v4_split_manifest_20260314.md](<repo>/docs/planning/claim_snapshot_v4_split_manifest_20260314.md)
- [claim_snapshot_v4_split_summary.json](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_split/off400_downstream_20260314/claim_snapshot_v4_split_summary.json)
- [claim_clustering_eval_pack_20260313.md](<repo>/docs/planning/claim_clustering_eval_pack_20260313.md)
- [claim_canonicalization_adr.md](<repo>/docs/planning/claim_canonicalization_adr.md)

Planning frame:

- [idea_mining_status_memo_20260313.md](<repo>/docs/planning/idea_mining_status_memo_20260313.md)
- [roadmap.md](<repo>/docs/planning/roadmap.md)

## What Is Ready

### Graph substrate readiness is documented as passing

The graph-side packet is strong enough for Step 4 review.

Documented status:

- `Gate A1` is `PASS` in [graph_baseline_report.md](<repo>/docs/planning/graph_baseline_report.md)
- `Gate A2` is `PASS` in [graph_baseline_report.md](<repo>/docs/planning/graph_baseline_report.md)
- all gate-critical typed paths are `pass` in [typed_path_regression_report.md](<repo>/docs/planning/typed_path_regression_report.md)

Operationally, this means the canonical substrate is no longer the blocker for
later claim-side or idea-mining work.

### Claim-side bounded freeze and split now exist

The claim-side packet has crossed from reviewed freeze into materialized bounded
split.

Current bounded reviewed status:

- `snapshot_v4_rows_total = 25`
- `snapshot_v4_canonical_families_total = 24`
- `snapshot_v4_warning_or_conflict_families_total = 19`
- `snapshot_v4_target_type_buckets_total = 3`
- `threshold_all_met = true`

Current bounded split status:

- `train_families = 14`
- `dev_families = 5`
- `test_families = 5`
- `family_cross_split_violations = 0`
- `paper_leakage_violations = 0`
- `dev_has_warning_or_conflict_family = true`
- `test_has_warning_or_conflict_family = true`
- `dev_has_clean_control_family = true`
- `test_has_clean_control_family = true`

That is enough to prove two things:

- the canonical claim layer is no longer implicit
- the downstream split layer is no longer proposal-only

### Failure taxonomy is now real, not aspirational

The bounded clustering pass and adjudicated snapshot together make the failure
taxonomy operational.

The current packet shows explicit handling for:

- `title_only_or_insufficient_text`
- `semantic_composite_or_analysis_claim`
- `polarity_or_antonym_confusion`
- `intervention_or_context_mismatch`
- `granularity_mismatch`
- `population_or_disease_scope_mismatch`
- `modality_or_method_leakage`

This matters because the first-pass claim snapshot is no longer mixing
reviewable and nonreviewable rows without explanation.

## What Is Not Yet Ready

### The joint final gate for new architecture work is not yet satisfied

The execution plan requires a final joint readiness packet anchored by:

- `graph_snapshot_v1_1`
- a reviewed claim snapshot layer
- `readiness_review.md`
- `go_no_go_memo.md`

Current state:

- `graph_snapshot_v1_1` is now explicitly bound by
  [graph_snapshot_v1_1_20260314.md](<repo>/docs/planning/graph_snapshot_v1_1_20260314.md)
  and
  [graph_snapshot_v1_1_manifest.json](<repo>/data/neurokg/raw/graph_snapshot_v1_1/bound_20260314/graph_snapshot_v1_1_manifest.json)
- `claim_snapshot_v4` is present
- a bounded claim-side split manifest is present
- `readiness_review.md` and `go_no_go_memo.md` are now present
- [task_charter.md](<repo>/docs/planning/task_charter.md)
  is now present
- [train_dev_test_split_proposal.md](<repo>/docs/planning/train_dev_test_split_proposal.md)
  is now present

The remaining caution is no longer “missing artifacts.” The remaining caution
is that the current freeze and split are still bounded and warning-heavy rather
than a large benchmark-ready export.

### The claim snapshot and split are bounded, not benchmark-complete

The current `claim_snapshot_v4` is intentionally conservative:

- `25` snapshot rows
- `24` canonical families
- `19` warning/conflict families
- `3` target-type buckets
- bounded split only

This is correct for a bounded closeout packet, but it means the packet
demonstrates reviewed canonicalization plus bounded split materialization, not
broad claim coverage.

### Novelty architecture remains blocked

The current review packet is sufficient to move Step 4 forward, but it is not a
license to reopen `novelty_architecture`.

The roadmap remains explicit that the architecture track is blocked until the
quality gates are closed in a way that supports grounded downstream use, not
just bounded runtime usability.

## Review Verdict

Claim-side verdict:

- `PASS (bounded)`

Reason:

- a reviewed `claim_snapshot_v4` exists
- canonicalization is explicit
- a real bounded split manifest exists
- dev/test integrity checks pass with preserved clean controls and
  warning/conflict families

Graph-side verdict:

- `PASS`

Reason:

- `Gate A1` and `Gate A2` are documented as passing
- typed path probes are stable on the current live substrate

Joint Step 4 verdict:

- `PASS (bounded closeout)`

Reason:

- the packet now contains:
  graph snapshot binding, threshold-meeting claim snapshot, materialized
  claim-side split manifest, readiness review, go/no-go memo, task charter, and
  split policy
- the remaining limitations are explicitly bounded-scope caveats, not missing
  closeout artifacts or missing split materialization

## Recommendation

Treat Step 4 closeout as complete on the current bounded packet.

Do not reinterpret that as permission to scale immediately into a broad
operator-learning or novelty-architecture phase.

The correct next move is:

1. keep the current `graph_snapshot_v1_1` binding and `claim_snapshot_v4` split
   as the bounded snapshot layer of record
2. treat [task_charter.md](<repo>/docs/planning/task_charter.md)
   and
   [train_dev_test_split_proposal.md](<repo>/docs/planning/train_dev_test_split_proposal.md)
   as frozen bounded definitions, with the claim-side rule now instantiated in
   the `claim_snapshot_v4` split manifest, not as evidence of large-scale
   benchmark readiness
3. use the accompanying [go_no_go_memo.md](<repo>/docs/planning/go_no_go_memo.md)
   as the formal architecture decision record
