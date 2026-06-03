# Dataset Task Unmatched Report
_Generated: 2026-01-06 (after rerunning `create_dataset_task_relationships.py --report ...` with the latest synonym + keyword + blacklist logic.)_

## Summary

- Prepped 755 `HAS_TASK` edges (includes `--include-all-tasks`, and can optionally source tasks from `Dataset.tasks`).
- Current unmatched normalized tokens: **18** (down from 248 after synonym + keyword updates, and now excluding blacklisted/noise tokens from the report).
- The most recent report is persisted at `/tmp/dataset_task_unmatched.tsv`.

## Buckets

### 1. Short codes / internal labels
These appear dataset-specific and require manual mapping (or should remain unmatched to avoid false positives).

Top items (see `artifacts/dataset_task_review/top_tokens.tsv` for the full list):

- `cmiyc` (2)
- `frequency reports block 1` (2)
- `frequency reports block 2` (2)
- `repmem1` / `repmem2b` (2 each)
- `modulate` (2)

### 2. Note: blacklisted/noise tokens are excluded from this report
The unmatched report now excludes tasks that are ignored by `task_mapping.yaml` blacklists (including `blacklist_terms` and `blacklist_regex`). This keeps `/tmp/dataset_task_unmatched.tsv` focused on actionable mapping gaps.

## Prov-conf confidence note

Keyword matches now flow through `match_task(... method="keyword_rule")`, which sets `match.confidence_hint = <confidence>`; `create_dataset_task_relationships.py` feeds that value into `_build_edge_props` via `prov_base_conf_override`. This keeps the `prov_base_conf` at 0.55 while giving the edge a traceable `mapping_method`.

## Task canonicalization note (MAPS_TO)

Some Task nodes in the KG do not carry `MEASURES`. To enable an explainable canonical path:

`Dataset -> HAS_TASK/USES_TASK -> Task -> MAPS_TO -> Task(with MEASURES) -> Concept`

we use `create_task_mapsto.py` (scoped to dataset-linked `needs_measures=true` targets) to write conservative `MAPS_TO` links when a near-certain canonical exists.

## Coverage metric note (denominator matters)

The overall `connected_coverage = connected / total_datasets` can look low because the KG includes many structural-only or non-task datasets (no meaningful `HAS_TASK` expected). For a more relevant signal, track the fMRI/BOLD subset:

- `connected_coverage_fmri`: counts only datasets with `modalities` containing `fMRI`/`BOLD`/`func` or `acquisitions` containing `BOLD`.

## Next steps

1. Continue to regenerate `/tmp/dataset_task_unmatched.tsv` after each catalog refresh, then append new entries to the table above.
2. When new high-frequency short codes emerge, either map them to canonical Tasks in `task_synonyms.yaml` or add more targeted `keyword_rules`.
3. Keep the `keyword_rules` section under `task_mapping.yaml` in sync with the canonical names exposed by `MATCH (t:Task)-[:MEASURES]` to avoid stale patterns.

Command to regenerate the report:
```
set -a; source .env; set +a;
python scripts/br-kg/create_dataset_task_relationships.py \\
  --report /tmp/dataset_task_unmatched.tsv \\
  --use-taxonomy-aliases --include-all-tasks --use-dataset-node-tasks --fuzzy-threshold 0.65
```

To additionally backfill missing fMRI/BOLD datasets by scanning local BIDS filenames for `task-<label>` (high coverage, but may create many new unmatched labels if you opt into reporting them):

```
set -a; source .env; set +a;
python scripts/br-kg/create_dataset_task_relationships.py \\
  --scan-bids-for-missing-fmri-tasks \\
  --use-taxonomy-aliases --include-all-tasks
```

## Dataset-context review pack

To build the dataset-context review pack (remaining unmatched tokens grouped by dataset_id):

```
set -a; source .env; set +a;
python scripts/br-kg/build_dataset_task_review_pack.py \\
  --unmatched /tmp/dataset_task_unmatched.tsv \\
  --out-dir artifacts/dataset_task_review \\
  --scan-task-json
```

Outputs:

- `artifacts/dataset_task_review/review_pack.tsv`
- `artifacts/dataset_task_review/top_tokens.tsv`

To generate a conservative human-review decision pack (does not apply mappings):

```
python scripts/br-kg/build_dataset_task_decision_pack.py
```

Output:

- `artifacts/dataset_task_review/decision_pack.tsv`
