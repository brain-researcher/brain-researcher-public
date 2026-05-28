# Harness Certification Runbook

## When To Run It

Run harness certification when:

- changing execution recipe metadata
- changing workflow catalog metadata
- changing workflow `runbook` or `artifact_contract` declarations
- changing MCP execution or observation plumbing
- validating CI behavior before promoting new gates

## Entry Points

Local runner:

```bash
python scripts/ops/run_harness_certification.py \
  --output-root artifacts/harness_certification \
  --skip-tool-kg-audit
```

GitHub workflow:

- `.github/workflows/harness-certification.yml`
- trigger with `workflow_dispatch` for manual verification

## How To Read A Report Directory

Start here:

- `summary.md`: fast human summary
- `scorecard.json`: machine-readable status plus locked invariants
- `drift_report.json`: structured failures to triage
- `report.json`: full bundle for debugging

Then inspect:

- `static_checks/` for declaration and surface parity failures
- `gold_lanes/` for canary details
- `artifact_contract_scan.json` for recent run degradation

## Hard Gate Versus Drift

Current CI behavior is narrow by design:

- hard gate: `execution_recipe_zero_drift`
- everything else: visible drift, not a workflow-level hard fail

If the GitHub job fails, check `scorecard.json` first and confirm whether
`invariants.execution_recipe_zero_drift.ok` is `false`.

## Gold Lanes

Current lanes:

- `workflow_preprocessing_qc_preflight`
- `workflow_rest_connectome_e2e_python`
- `single_tool_python_job`
- `hosted_surface_discovery`

Only `single_tool_python_job` is a real single-tool canary.

## Single-Tool Python Gold Lane

Lane id:

- `single_tool_python_job`

Current canary:

- tool id: `resolve_transform`
- execution mode: real `tool_execute`
- fixture strategy: temporary registry-backed regfusion fixture created by the
  runner

Why this canary exists:

- it exercises a real Python tool path
- it avoids network and heavy workflow dependencies
- it produces a concrete output file
- it must also produce the full traceability surface for the run

Expected pass conditions:

- `tool_execute` returns `ok=true`
- run status is `succeeded`
- step status is `succeeded`
- copied regfusion outputs exist:
  - `tpl-MNI152_space-fsLR_den-32k_hemi-L_regfusion.txt`
  - `tpl-MNI152_space-fsLR_den-32k_hemi-R_regfusion.txt`
- required run artifacts exist and are non-empty:
  - `trace.jsonl`
  - `provenance.json`
  - `trajectory.json`
  - `observation.json`
  - `analysis_bundle.json`
- result summary includes:
  - `asset_id=warp.regfusion.mni152nlin2009casym.fslr.32k`
  - `source=registry_local_cache`

Failure interpretation:

- `tool_not_allowlisted` or `tool_execute_disabled`: runner regression
- missing run artifacts: observation or run-bundle regression; missing
  `analysis_bundle.json` or `observation.json` makes the bundle non-evaluable,
  while missing trace/provenance/trajectory is a degraded traceability state
- missing regfusion outputs: tool materialization regression
- run status `failed`: inspect `gold_lanes/single_tool_python_job.json`

## Updating The Lane Safely

If you replace the canary tool, keep the same bar:

- Python-backed
- local-only
- fast
- deterministic
- concrete output file
- full run traceability artifacts

Before merging a lane change:

1. run the local certification runner
2. confirm `gold_lanes/single_tool_python_job.json` shows a real run
3. confirm `summary.md` still reports observability-first mode
4. confirm `execution_recipe_zero_drift` is unchanged unless intentionally
   modified
