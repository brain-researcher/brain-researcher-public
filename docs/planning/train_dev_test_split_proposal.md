# Train / Dev / Test Split Policy

Date: 2026-03-14

## Purpose

This document records the split policy for downstream graph-side and claim-side
tasks defined in
[task_charter.md](<repo>/docs/planning/task_charter.md).

Current status:

- claim-side bounded split is now materialized from
  [claim_snapshot_v4_20260314.md](<repo>/docs/planning/claim_snapshot_v4_20260314.md)
  via
  [claim_snapshot_v4_split_manifest_20260314.md](<repo>/docs/planning/claim_snapshot_v4_split_manifest_20260314.md)
- graph-side remains policy-only

## Inputs

- [graph_snapshot_v1_1_20260314.md](<repo>/docs/planning/graph_snapshot_v1_1_20260314.md)
- [claim_snapshot_v4_20260314.md](<repo>/docs/planning/claim_snapshot_v4_20260314.md)
- [claim_snapshot_v4.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4/off400_terminal_reviewed_20260314/claim_snapshot_v4.jsonl)
- [claim_snapshot_v4_split_manifest_20260314.md](<repo>/docs/planning/claim_snapshot_v4_split_manifest_20260314.md)
- [claim_snapshot_v4_split_manifest.json](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_split/off400_downstream_20260314/claim_snapshot_v4_split_manifest.json)

## Split Principles

### Principle 1. Split by semantic unit, not by row

Graph-side:

- split by task family, edge family, atlas/dataset family, or publication
  family

Claim-side:

- split by `canonical_claim_id`
- never split support/refute rows from the same canonical family across
  train/dev/test

### Principle 2. Avoid paper leakage

If one `paper_id` contributes multiple rows to a canonical family, those rows
must stay in the same partition.

### Principle 3. Keep failure-tag distributions explicit

Rows with failure tags should not be randomly sprinkled without accounting.
They should be allocated intentionally so dev/test still contain:

- clean control examples
- warning-tagged singleton examples
- conflict-bearing canonical families

### Principle 4. Historical undersized-freeze rule remains part of the policy

The initial `claim_snapshot_v1` was too small to justify a meaningful train/dev/
test partition.

Historical operational rule:

- until the reviewed claim snapshot expands, the current `claim_snapshot_v1`
  should be treated as a `dev_seed` / `evaluation_seed`, not a trainable split

This rule is retained here because it governed the path to the first real
bounded split. It no longer describes the current `claim_snapshot_v4` state.

## Claim-Side Policy

### Headline verifier benchmark split remains unchanged

For the existing headline claim-first benchmark, keep using the already frozen
benchmark split from
[claim_benchmark_charter.md](<repo>/docs/planning/claim_benchmark_charter.md):

- `dev = calibration`
- `test = held_out`

Operational rule:

- this document does not override the verifier benchmark split
- it only proposes the first split policy for the *downstream snapshot-based
  task families* defined in
  [task_charter.md](<repo>/docs/planning/task_charter.md)

### First bounded materialization

Current reviewed snapshot size:

- `25` rows
- `24` canonical claim families
- `19` warning/conflict families
- `3` target-type buckets

Materialized bounded split:

- `train = 14 families / 14 rows`
- `dev = 5 families / 6 rows`
- `test = 5 families / 5 rows`

Checks:

- `family_cross_split_violations = 0`
- `paper_leakage_violations = 0`
- `dev_has_warning_or_conflict_family = true`
- `test_has_warning_or_conflict_family = true`
- `dev_has_clean_control_family = true`
- `test_has_clean_control_family = true`

Interpretation:

- the first real bounded claim-side split now exists
- it should be used as a bounded downstream task manifest, not as a
  benchmark-scale dataset export
- the warning/conflict load is intentionally high, so this is still a
  conservative closeout artifact rather than a scale-ready benchmark

### Threshold that governed first real split

The first real bounded split was gated by the reviewed snapshot reaching at
least:

- `>= 24` canonical claim families
- `>= 6` conflict-bearing or warning-bearing families
- `>= 3` target-type buckets across `Concept`, `Region`, and `Task`

The current `claim_snapshot_v4` meets all three thresholds.

### First real split policy

Once the threshold above is met, the split policy is:

- `train`: approximately `60%` of canonical claim families
- `dev`: approximately `20%`
- `test`: approximately `20%`

Required balancing:

- preserve at least one conflict-bearing family in both `dev` and `test`
- preserve clean controls in all non-train partitions
- do not let title-only/failure-dominated families overwhelm `test`

## Graph-Side Policy

### Current status

Graph-side is stronger on structural readiness than on explicit benchmark split
materialization.

The current proposal is therefore task-family-first, not row-export-first.

### Proposed graph task split units

For `typed-path retrieval and probe consistency`:

- split by probe family:
  - train: none initially
  - dev: current deterministic probe families
  - test: a later held-out probe set once additional frozen probes are defined

For `typed-path operator completion`:

- split by edge family and source family
- avoid holding out isolated individual edges without holding out their local
  source neighborhood

Preferred holdout boundaries:

- atlas family
- dataset family
- publication family

## Materialization Rule

Claim-side:

- this rule is now instantiated by
  [claim_snapshot_v4_split_manifest.json](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_split/off400_downstream_20260314/claim_snapshot_v4_split_manifest.json)
  and the accompanying `train/dev/test` JSONL exports

Graph-side:

- when the repo is ready to instantiate a real graph-side split artifact, it
  should produce a separate manifest that lists partition membership by
  edge/probe family for the graph-side task families

This document should therefore be read as:

- a frozen split policy for both graph-side and claim-side tasks
- plus the current materialization status for the claim-side bounded packet

## Explicit Non-Claims

This policy does **not** claim that:

- the current `claim_snapshot_v4` is large enough for benchmark-scale training
- the current graph-side packet is already a ready-to-train operator-learning
  dataset
- final gate has passed

## Next Move

The next closeout step after this bounded materialization is not another split
rewrite.

The next closeout step is to keep the current `claim_snapshot_v4` split frozen
inside the readiness packet while preserving the correct remaining caveat:

- the split now exists
- the packet is still bounded and warning-heavy
