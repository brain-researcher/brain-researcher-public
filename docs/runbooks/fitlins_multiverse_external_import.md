# FitLins Multiverse External Import on Sherlock/OAK

This runbook covers the practical path for taking existing FitLins multiverse
outputs on Sherlock/OAK, registering them as BR external runs, and then using
the resulting explicit `run_id` values with `run_scientific_review`.

Primary entrypoint:
- `scripts/review/import_fitlins_multiverse_batch.py`

Related surfaces:
- `scripts/review/import_external_run.py`
- `scripts/review/direct_review_external_run.py`
- `docs/runbooks/workflow_fitlins_multiverse_yeo17.md`

## Recommended path layout

Use OAK for the original multiverse outputs:
- Example source root: `$OAK/projects/<project>/fitlins_multiverse`

Use `$PI_HOME` for the imported BR run store when you want durable shared
`run_id` values:
- Example run store: `$PI_HOME/brain_researcher/mcp_runs`

Use `$SCRATCH` or `$LOCAL_SCRATCH` only for temporary logs or transient working
files:
- Example log dir: `$SCRATCH/br_logs`

Reasoning:
- the source artifacts may be large and should stay on OAK
- imported BR runs are mostly small JSON files plus symlinks back to OAK
- if the run store lives on purgeable scratch, the explicit `run_id` values are
  not durable

## Sherlock login

```bash
ssh <sunetid>@login.sherlock.stanford.edu
```

Do not scan a large OAK tree repeatedly from the login node. Use the login node
for quick dry-runs or one-off imports only.

## One-time setup

```bash
export REPO_ROOT="$PI_HOME/brain_researcher"
export FITLINS_SOURCE_ROOT="$OAK/projects/<project>/fitlins_multiverse"
export BR_MCP_RUN_ROOT="$PI_HOME/brain_researcher/mcp_runs"
mkdir -p "$BR_MCP_RUN_ROOT"
cd "$REPO_ROOT"
```

## Dry-run candidate discovery

Use this first to see what the script will import and what `run_id` values it
will derive.

```bash
python scripts/review/import_fitlins_multiverse_batch.py \
  --search-root "$FITLINS_SOURCE_ROOT" \
  --run-root "$BR_MCP_RUN_ROOT" \
  --dry-run \
  --output-json "$PI_HOME/brain_researcher/logs/fitlins_multiverse_import_dryrun.json"
```

If you only want to import a few known runs:

```bash
python scripts/review/import_fitlins_multiverse_batch.py \
  --source-dir "$FITLINS_SOURCE_ROOT/ds000114/linebisection" \
  --source-dir "$FITLINS_SOURCE_ROOT/ds000001/stopsignal" \
  --run-root "$BR_MCP_RUN_ROOT" \
  --dry-run
```

## Batch import on Sherlock

For a moderate or large source tree, prefer a batch job.

```bash
python scripts/review/import_fitlins_multiverse_batch.py \
  --search-root "$FITLINS_SOURCE_ROOT" \
  --run-root "$BR_MCP_RUN_ROOT" \
  --output-json "$PI_HOME/brain_researcher/logs/fitlins_multiverse_import_$(date +%Y%m%d_%H%M%S).json"
```

Behavior notes:
- default mode is idempotent: existing imported runs are reported as `skipped_existing`
- pass `--overwrite` only when you intentionally want to restage runs
- pass `--source-dir` to constrain import scope when only a few runs matter

## `sbatch` template

```bash
#!/bin/bash
#SBATCH --job-name=br-fitlins-import
#SBATCH --output=%x-%j.out
#SBATCH --error=%x-%j.err
#SBATCH --time=01:00:00
#SBATCH --mem=8G
#SBATCH --cpus-per-task=2

set -euo pipefail

export REPO_ROOT="$PI_HOME/brain_researcher"
export FITLINS_SOURCE_ROOT="$OAK/projects/<project>/fitlins_multiverse"
export BR_MCP_RUN_ROOT="$PI_HOME/brain_researcher/mcp_runs"

mkdir -p "$PI_HOME/brain_researcher/logs"
mkdir -p "$BR_MCP_RUN_ROOT"

cd "$REPO_ROOT"

python scripts/review/import_fitlins_multiverse_batch.py \
  --search-root "$FITLINS_SOURCE_ROOT" \
  --run-root "$BR_MCP_RUN_ROOT" \
  --output-json "$PI_HOME/brain_researcher/logs/fitlins_multiverse_import_${SLURM_JOB_ID}.json"
```

Submit it with:

```bash
sbatch import_fitlins_multiverse_batch.sbatch
```

## Import only one known run

If you already know the exact output directory and do not need discovery:

```bash
python scripts/review/import_external_run.py \
  --source-dir "$FITLINS_SOURCE_ROOT/ds000114/linebisection" \
  --run-id fitlins-multiverse-ds000114-linebisection-manual \
  --adapter fitlins_multiverse \
  --run-root "$BR_MCP_RUN_ROOT"
```

## After import: run scientific review

Once the batch import finishes, use the generated `run_id` values from the JSON
summary and call review with the explicit id:

```python
run_scientific_review(run_id="fitlins-multiverse-ds000114-linebisection-<hash>")
```

## Expected layouts the importer recognizes

Workflow-root layout:
- `run_manifest.json`
- optional `specs/multiverse_manifest.json`
- optional `fitlins/yeo17_summary.csv`
- optional `fitlins/robustness_yeo17.json`

Run-only layout:
- `multiverse_manifest.json`
- optional `yeo17_summary.csv`
- optional `robustness_yeo17.json`

## Troubleshooting

If the dry-run finds nothing:
- confirm the source tree actually contains `run_manifest.json` or `multiverse_manifest.json`
- confirm Yeo17 outputs were written under either `fitlins/` or the run root
- try explicit `--source-dir` on a known run directory instead of scanning the whole tree

If runs are skipped unexpectedly:
- the derived `run_id` already exists under `--run-root`
- rerun with `--overwrite` only if you want to replace the staged BR run

If you want temporary local review without writing to the shared run store:
- use `scripts/review/direct_review_external_run.py` instead of importing
