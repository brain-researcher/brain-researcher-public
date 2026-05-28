# Neuroimaging Workflow Repo Intake

This document tracks mature external neuroimaging repositories that Brain
Researcher should absorb as workflows, adapters, or reference backends.

The machine-readable source of truth is:

- `configs/workflows/neuroimaging_repo_intake.yaml`

Validate it with:

```bash
python scripts/validation/check_neuroimaging_repo_intake.py
```

## Selection rule

The default priority is:

1. Preprocessing and QC BIDS apps
2. Structural and surface workflows
3. Diffusion reconstruction
4. Broader frameworks

That ordering is intentional. Brain Researcher already has recipe/runtime
support for container-backed BIDS-app style workflows, so those repositories
have the clearest path to stable workflow packs.

## Current first-wave shortlist

- `nipreps/fmriprep`
- `nipreps/mriqc`
- `PennLINC/qsiprep`
- `nipreps/smriprep`
- `PennLINC/qsirecon`
- `Deep-MI/FastSurfer`

## Integration posture

- `fmriprep`, `mriqc`, `qsiprep`, and `smriprep` should be treated as
  container-first workflow backends.
- `qsirecon` should remain a constrained downstream workflow with a whitelist of
  reconstruction presets rather than a raw command mirror.
- `FastSurfer` can start as a lightweight adapter and later be replaced by a
  real container-backed backend.
- `MRtrix3` and `Connectome Workbench` should stay behind opinionated workflows,
  not direct command exposure.

## Registry semantics

- `already_usable`: Brain Researcher already has enough runtime support to treat
  the repo as an active dependency.
- `present_not_standardized`: parts of the integration exist, but the workflow
  contract or backend packaging is still incomplete.
- `missing_and_should_acquire`: keep on the backlog until the surrounding
  workflow contracts are more stable.
