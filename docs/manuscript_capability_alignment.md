# Manuscript Capability Alignment (System-Only)

Date: 2026-02-14
Scope: Align implementation to manuscript target capabilities without changing manuscript text.

## Narrative Packaging Note

- Use `R1-R5` as an internal capability decomposition for architecture and Methods only.
- Do **not** use `R1-R5` as the main Results spine for the flagship paper.
- The flagship manuscript should be framed around:
  - closed-loop scientific infrastructure
  - reliable executable science
  - one flagship neuroscience result
  - prospective collaborator-cohort generalization

## Current Status (R1-R5)

### R1 Read (Conflict Mapping)
- Status: `partial`
- Implemented:
  - BR-KG query/search surfaces available via web and MCP routes.
- Gaps:
  - Need paper-grade evaluation outputs (conflict F1, citation precision/recall) materialized and versioned.

### R2 Audit (Robustness / Multiverse)
- Status: `partial`
- Implemented:
  - Typed tool execution and parameterized analysis paths exist.
- Gaps:
  - Need stable, repeatable benchmark pipelines and stored audit summaries for manuscript tables.

### R3 Design (Decision Support)
- Status: `partial`
- Implemented:
  - Plan checks and dynamic workflow selection in web UI.
- Gaps:
  - Need stronger plan-verification gates tied to real runtime/tool availability.

### R4 Execute (Reliable + Auditable)
- Status: `in_progress`
- Implemented:
  - Dynamic workflow route is supported in web UI APIs.
  - `workflow_rest_connectome_e2e` has a verified prod/UI smoke on OpenNeuro
    `ds000114`: `job_018f571e7531` completed and produced
    `timeseries/timeseries.npy`, `timeseries/timeseries.csv`, and
    `connectivity_matrix.npy`, with the UI rendering those outputs as ready.
  - `workflow_preprocessing_qc`, fMRIPrep, MRIQC, and FastSurfer remain
    recipe/handoff-only until workflow-specific UI end-to-end smokes verify
    runtime execution and required artifacts.
  - Shared SQLite JobStore wiring exists in Helm values/templates.
- Known caveats:
  - `run_mriqc_workflow` tool remains preview-only and should not be used as canonical execution path.
  - BIDS-app and structural routes should not be described as hosted UI
    executable until their own runtime, artifact, and UI smoke gates pass.
  - Audit artifact generation is still best-effort in several orchestrator paths.
    - `trace.jsonl` is strongest/most consistent.
    - `observation.json`, `provenance.json`, `trajectory.json`, `reward_breakdown.json` can still be missing in edge paths.

### R5 Loop Closure (Integrated > Isolated)
- Status: `partial`
- Implemented:
  - End-to-end wiring across plan -> execute -> analyses views exists.
- Gaps:
  - Need controlled integrated-vs-isolated experiments with frozen configs and stored outputs.

## Delta to Close Before Claiming Full Alignment

1. Make audit artifact contract strict for executable runs.
   - Require and verify: `trace.jsonl`, `observation.json`, `provenance.json`, `trajectory.json`.
   - Fail run finalization (or mark degraded) when required artifacts are missing.

2. Validate runtime executability for every declared execution workflow.
   - Preflight check for required runtimes/binaries/container images (`fmriprep`, `mriqc`, etc.).
   - Expose preflight result in run metadata and UI.
   - Do not treat fMRIPrep, MRIQC, FastSurfer, or preprocessing/QC BIDS-app
     routes as web-executable until workflow-specific UI end-to-end smokes
     create completed runs with required artifacts.

3. Lock queue/backend behavior in production.
   - Agent + orchestrator must share same persistent JobStore backend.
   - Verify with live jobs transitioning `queued -> running -> completed` and logs present.

4. Add E2E verification for UI + MCP plan paths for each claimed execution workflow.
   - UI submit with explicit `plan`.
   - MCP submit with explicit `plan`.
   - Assert step tool IDs are preserved and actually executed.

5. Publish reproducible evidence bundle for manuscript metrics.
   - Benchmark run manifests, seeds, configs, and computed tables/figures.

## Acceptance Gates (Recommended)

- R4 Gate A: For executable benchmark subset, >=95% runs have complete artifact set:
  - `trace.jsonl`, `observation.json`, `provenance.json`, `trajectory.json`.
- R4 Gate B: `workflow_rest_connectome_e2e` has passed live UI + prod artifact
  smoke; preprocessing/QC/structural routes require separate workflow-specific
  UI E2E gates before executable claims.
- R5 Gate: Integrated vs isolated experiment package is reproducible from a pinned commit + config snapshot.
