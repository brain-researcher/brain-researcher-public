# Claim Snapshot V4 Downstream Task Manifest

Date: 2026-03-14

## Purpose

This note records the first materialized claim-side downstream task built from
the bounded `claim_snapshot_v4` split.

The selected task is:

- `B1 canonical claim family support/conflict reasoning`

This is the first point where the bounded split becomes a directly consumable
task artifact rather than only a split manifest.

## Inputs

- [task_charter.md](<repo>/docs/planning/task_charter.md)
- [claim_snapshot_v4_split_manifest_20260314.md](<repo>/docs/planning/claim_snapshot_v4_split_manifest_20260314.md)
- [claim_snapshot_v4_split_manifest.json](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_split/off400_downstream_20260314/claim_snapshot_v4_split_manifest.json)
- [build_claim_snapshot_v4_downstream_task_manifest.py](<repo>/scripts/tools/etl/build_claim_snapshot_v4_downstream_task_manifest.py)
- [run_claim_snapshot_v4_baseline_eval.py](<repo>/scripts/tools/etl/run_claim_snapshot_v4_baseline_eval.py)

## Task Artifacts

- [claim_snapshot_v4_downstream_task_manifest.json](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_downstream_task_manifest/off400_b1_family_stance_20260314/claim_snapshot_v4_downstream_task_manifest.json)
- [claim_snapshot_v4_b1_train.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_downstream_task_manifest/off400_b1_family_stance_20260314/claim_snapshot_v4_b1_train.jsonl)
- [claim_snapshot_v4_b1_dev.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_downstream_task_manifest/off400_b1_family_stance_20260314/claim_snapshot_v4_b1_dev.jsonl)
- [claim_snapshot_v4_b1_test.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_downstream_task_manifest/off400_b1_family_stance_20260314/claim_snapshot_v4_b1_test.jsonl)
- [claim_snapshot_v4_downstream_task_summary.json](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_downstream_task_manifest/off400_b1_family_stance_20260314/claim_snapshot_v4_downstream_task_summary.json)

## Baseline Artifacts

- [claim_snapshot_v4_baseline_eval_summary.json](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_baseline_eval/off400_b1_family_stance_20260314/claim_snapshot_v4_baseline_eval_summary.json)
- [dev_predictions.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_baseline_eval/off400_b1_family_stance_20260314/dev_predictions.jsonl)
- [test_predictions.jsonl](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_baseline_eval/off400_b1_family_stance_20260314/test_predictions.jsonl)
- [claim_snapshot_v4_richer_b1_baseline_eval_summary.json](<repo>/data/neurokg/raw/gabriel/eval/claim_snapshot_v4_richer_b1_baseline_eval/off400_b1_family_stance_20260314/claim_snapshot_v4_richer_b1_baseline_eval_summary.json)

## Task Operationalization

Input unit:

- one `canonical_claim_id` family per example

Label space:

- `support_only`
- `refute_only`
- `conflict_bearing`
- `insufficient`

Important bounded refinement:

- this task keeps an explicit `refute_only` label
- it does not collapse the single refute-only family into `insufficient`
- that keeps the current `test` slice honest without pretending the charter is
  already benchmark-complete

## Summary

Current task counts:

- `train = 14` examples
- `dev = 5` examples
- `test = 5` examples

Current label distribution:

- train: `14 support_only`
- dev: `4 support_only`, `1 conflict_bearing`
- test: `4 support_only`, `1 refute_only`

Operational reading:

- the task is now materially runnable
- the split is still extremely skewed
- this is useful as a bounded eval skeleton, not as a meaningful train-scale
  benchmark

## Baseline Results

Baseline `1`: train-majority label

- learned majority label: `support_only`
- `dev accuracy = 0.8`
- `test accuracy = 0.8`
- `dev macro_f1 = 0.2222`
- `test macro_f1 = 0.2222`

Baseline `2`: family polarity rule

- predicts from `support_count / refute_count`
- `dev accuracy = 1.0`
- `test accuracy = 1.0`

Baseline `3`: richer metadata heuristic

- uses `snapshot_role`, `failure_tags`, `target_type`, and `quality_profile`
- does not read `support_count` or `refute_count`
- `dev accuracy = 1.0`
- `test accuracy = 1.0`
- `dev macro_f1 = 0.5`
- `test macro_f1 = 0.5`

Interpretation:

- the majority baseline confirms the current bounded split is highly skewed
- the polarity-signature rule confirms the task manifest is internally coherent
- the richer metadata heuristic shows that the current bounded slice is still
  easy to saturate with review-metadata shortcuts
- this is still a contract/skeleton baseline set, not a nontrivial research
  baseline

## Next Move

The next useful step is not another split tweak.

The next useful step is to add either:

- a bounded split or first baseline over the new
  [claim_snapshot_v4_b2_task_manifest_20260314.md](<repo>/docs/planning/claim_snapshot_v4_b2_task_manifest_20260314.md)
- or a less metadata-tethered `B1` baseline that cannot shortcut off
  `snapshot_role`
