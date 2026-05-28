# Workflow Runbook: fMRIPrep Preprocessing

Source repo: `nipreps/fmriprep`

Current BR status: candidate-pack workflow with real wrapper-backed execution
through `run_bids_app` and `run_fmriprep`. The workflow remains preview-first
by default; set `dry_run=false` to execute.

For the minimal execute recipe and prod certification path, BR now defaults to
`--fs-no-reconall` so the single-subject gate stays within a bounded runtime
and memory profile.

Primary entrypoint: `workflow_fmriprep_preprocessing`

Required inputs:
- `bids_dir`
- `output_dir`

Optional inputs:
- `participant_label`
- `work_dir`
- `fs_license_file`
- `output_spaces`
- `n_cpus`
- `omp_nthreads`
- `mem_mb`
- `extra_args`
- `dry_run` with default `true`

Expected backend:
- Current: resolved local Neurodesk/neurocommand `fmriprep` wrapper executable
- Future: stricter artifact validation and cluster execution hardening

Acceptance gate:
- `tests/integration/realdata/test_workflow_external_repo_preproc_candidates_smoke.py`
- `scripts/workflows/run_workflow_realdata_gate.py`
- `tests/integration/realdata/test_workflow_external_repo_minimal_execute_gate.py`
- `scripts/workflows/run_external_repo_minimal_execute_gate.py`

Minimal BR invocation:

```python
from brain_researcher.services.tools.runner import execute_tool

res = execute_tool(
    "workflow_fmriprep_preprocessing",
    {
        "bids_dir": "/data/openneuro/ds000114/bids",
        "output_dir": "./out/fmriprep_single_subject_minimal",
        "participant_label": ["01"],
        "work_dir": "./out/fmriprep_single_subject_minimal_work",
        "fs_license_file": "/path/to/freesurfer/license.txt",
        "output_spaces": ["MNI152NLin2009cAsym"],
        "n_cpus": 4,
        "omp_nthreads": 2,
        "mem_mb": 16000,
        "extra_args": ["--skip-bids-validation", "--fs-no-reconall"],
        "dry_run": False,
    },
)
```

Minimal execute gate:

```bash
python scripts/workflows/run_external_repo_minimal_execute_gate.py \
  --workflow-id workflow_fmriprep_preprocessing
```

MCP recipe:
- `get_execution_recipe("workflow_fmriprep_preprocessing", target_runtime="neurodesk"|"container"|"slurm")`
- The returned recipe now includes `README.md`, `params.json`, and a runnable `run_workflow_fmriprep_preprocessing.sh`.
