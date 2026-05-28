# `workflow_psych101_ingest_eval`

Minimal non-GPU scaffold for Psych-101 trial ingestion and eval-manifest prep.
It is intended for Phase 0/1 integration work, not for model serving.

## Inputs
- `psych101_tsv`: Psych-101 trial export in TSV or CSV form.
- `output_dir`: Directory for normalized trial and manifest artifacts.
- Optional: `output_stem`, `dataset_id`, `source_name`, `heldout_ratio`,
  `audit_group_keys`, `target_population`, `sampling_frame`,
  `inclusion_criteria`, `exclusion_criteria`, `sample_weight_column`,
  `min_group_count`.

## What It Does
1. Normalizes the trial export into a canonical trial table.
2. Aggregates the normalized table into a compact eval manifest.
3. Optionally records subgroup-audit metadata, group counts, missingness, and
   underpowered-group warnings in the eval manifest.
4. Writes artifacts that downstream workflows or benchmarks can consume.

## Expected Outputs
- `psych101_trials.csv`
- `psych101_eval_manifest.json`

## Notes
- Keep the input lightweight and local. This workflow assumes the Psych-101
  export has already been unpacked or converted to a tabular trial file.
- The workflow is declarative and chains two lightweight step tools:
  `psych101_ingest` and `psych101_prepare_eval_manifest`.
- When `audit_group_keys` are provided, the manifest includes a
  `fairness_audit` section that is intended for selection-bias review rather
  than automatic fairness claims.
