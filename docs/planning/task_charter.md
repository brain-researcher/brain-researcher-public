# Task Charter

Date: 2026-03-14

## Purpose

This charter freezes the first downstream task definitions that sit on top of
the current graph-side and claim-side snapshot layer.

It satisfies the Step 11 requirement from
[neurokg_graph_claim_execution_plan.md](<repo>/docs/planning/neurokg_graph_claim_execution_plan.md)
to define downstream operator-learning tasks and claim-centric reasoning tasks
without pretending those tasks are already benchmark-complete.

## Inputs

Graph-side snapshot layer:

- [graph_snapshot_v1_1_20260314.md](<repo>/docs/planning/graph_snapshot_v1_1_20260314.md)
- [graph_snapshot_v1_1_manifest.json](<repo>/data/neurokg/raw/graph_snapshot_v1_1/bound_20260314/graph_snapshot_v1_1_manifest.json)

Claim-side snapshot layer:

- [claim_snapshot_v4_20260314.md](<repo>/docs/planning/claim_snapshot_v4_20260314.md)
- [claim_snapshot_v4.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4/off400_terminal_reviewed_20260314/claim_snapshot_v4.jsonl)
- [claim_snapshot_v4_split_manifest_20260314.md](<repo>/docs/planning/claim_snapshot_v4_split_manifest_20260314.md)
- [claim_snapshot_v4_split_manifest.json](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_split/off400_downstream_20260314/claim_snapshot_v4_split_manifest.json)

Execution frame:

- [readiness_packet_20260314.md](<repo>/docs/planning/readiness_packet_20260314.md)
- [readiness_review.md](<repo>/docs/planning/readiness_review.md)

## Charter Scope

This charter defines task *families* and their intended evaluation semantics.

It does not define:

- model architecture
- feature extraction pipeline
- loss functions
- final training dataset sizes
- success metrics for a released benchmark leaderboard

Those remain downstream once a larger frozen split exists.

## Workstream A Task Families

### A1. Typed-path operator completion

Objective:

- predict or recover missing edge instances on top of the graph substrate while
  respecting the canonical path contract

In-scope edge families:

- `PART_OF`
- `MEASURES`
- `CITES`

Out of scope for the first pass:

- `ACTIVATES`
- free-form semantic relation induction

Evaluation unit:

- typed edge prediction on the frozen graph-side substrate

Success condition:

- models or heuristics must be interpretable against the same canonical path
  families already frozen in the graph packet

### A2. Typed-path retrieval and probe consistency

Objective:

- test whether a reasoning system can recover the gate-critical typed paths
  already known to exist in the substrate

Probe families:

- `Publication -> HAS_COORDINATE -> Coordinate`
- `StatsMap -> IN_REGION -> BrainRegion`
- `BrainRegion -> PART_OF -> BrainRegion`
- `Task -> MEASURES -> Concept`
- `Publication -> CITES -> Publication`
- `StatsMap -> IN_REGION -> BrainRegion -> PART_OF -> BrainRegion`

This is a retrieval/consistency task, not a new graph construction task.

## Workstream B Task Families

### B0. Headline claim-first verifier benchmark

Objective:

- preserve the existing bounded benchmark question already frozen in
  [claim_benchmark_charter.md](<repo>/docs/planning/claim_benchmark_charter.md)

Operational rule:

- this headline task continues to use the frozen calibration and held-out
  hypothesis slices from the benchmark charter
- it is not replaced by `claim_snapshot_v4`

Reason:

- `claim_snapshot_v4` is a reviewed canonicalization/split freeze
- the headline benchmark remains the claim-first vs mention-fallback benchmark

### B1. Canonical claim family support/conflict reasoning

Objective:

- reason over a `canonical_claim_id` family while preserving paper-level stance
  disagreement

Current positive bounded example:

- the single opposing-stance `concept:attention` cluster in
  [claim_snapshot_v4_b1_dev.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_downstream_task_manifest/off400_b1_family_stance_20260314/claim_snapshot_v4_b1_dev.jsonl)

Task output:

- determine whether the canonical family is:
  - support-only
  - refute-only when the bounded slice contains only retained refute rows
  - conflict-bearing
  - insufficient

Operational constraint:

- polarity remains a row-level property
- canonical identity must not collapse support and refute into a single scalar
  without preserving the disagreement

### B2. Failure-aware claim inclusion/exclusion reasoning

Objective:

- decide whether a paper-local claim row belongs in the reviewed snapshot or
  should remain excluded

Required failure tags:

- `title_only_or_insufficient_text`
- `semantic_composite_or_analysis_claim`
- `polarity_or_antonym_confusion`
- `granularity_mismatch`
- `intervention_or_context_mismatch`
- `population_or_disease_scope_mismatch`
- `modality_or_method_leakage`

Task output:

- `retain_singleton`
- `retain_singleton_with_warning`
- `retain_conflict_cluster_with_warning`
- `exclude_from_snapshot`

This task is about adjudication quality, not raw retrieval score.

### B3. Claim-first evidence retrieval on reviewed snapshot rows

Objective:

- retrieve the auditable evidence path for a reviewed claim row or canonical
  family

Required path shape:

- `Publication -> REPORTS_CLAIM -> Claim <- SUPPORTS <- EvidenceSpan`

Task output:

- the correct reviewed evidence items and their provenance-bearing anchors

This is a claim-side retrieval task, not a novelty-generation task.

## Current Bounded Instantiation

The present snapshot and split are sufficient to instantiate:

- a first materialized bounded `B1 canonical claim family support/conflict reasoning`
  task in
  [claim_snapshot_v4_downstream_task_manifest_20260314.md](<repo>/docs/planning/claim_snapshot_v4_downstream_task_manifest_20260314.md)
- a conflict-expanded reviewed-seed `B2 failure-aware claim inclusion/exclusion reasoning`
  task in
  [claim_snapshot_v4_b2_task_manifest_20260314.md](<repo>/docs/planning/claim_snapshot_v4_b2_task_manifest_20260314.md)
- a bounded `B2` split and baseline with conflict in both eval partitions in
  [claim_snapshot_v4_b2_split_manifest_20260314.md](<repo>/docs/planning/claim_snapshot_v4_b2_split_manifest_20260314.md)
- bounded seeds for `B3 claim-first evidence retrieval`

It is only sufficient to instantiate proposal-level seeds for:

- `A1 typed-path operator completion`
- `A2 typed-path retrieval and probe consistency`

Reason:

- graph-side pass state is explicitly bound
- claim-side freeze and split are real
- but the current claim tasks are still too small, too skewed, or too
  metadata-tethered to treat as large-scale trainable benchmarks

## Explicit Non-Claims

This charter does **not** claim that:

- the repo now has a full operator-learning dataset
- the repo now has a benchmark-scale claim reasoning benchmark
- novelty architecture is unblocked
- relation-as-operator work should start immediately

## Next Dependency

This charter becomes operational only together with:

- [train_dev_test_split_proposal.md](<repo>/docs/planning/train_dev_test_split_proposal.md)

That proposal defines how these tasks should be split without leakage.
