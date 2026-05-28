# `workflow_psych101_benchmark_import`

Lightweight bridge from a Psych-101 eval manifest into the benchmark board.

## Inputs
- `eval_manifest_json`: Path to a Psych-101 eval manifest with `benchmark_tasks`.
- `output_dir`: Directory for import summary artifacts.
- Optional: `output_stem`, `dataset_id`, `version`, `benchmark_db_path`, `overwrite_governance`.

## What It Does
1. Reads the eval manifest from disk.
2. Extracts `benchmark_tasks` in TaskSpec-compatible form.
3. Imports them into the benchmark board SQLite registry.
4. Writes a compact JSON import summary artifact.

## Expected Outputs
- `psych101_benchmark_import.json`

## Notes
- This workflow is intentionally non-GPU.
- The import step reuses the standard benchmark importer path, so it preserves idempotent content-hash behavior.
- The workflow currently uses one lightweight step tool: `psych101_import_eval_manifest`.
