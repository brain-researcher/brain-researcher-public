# Workflow Runbook: QSIPrep

Source repo: `PennLINC/qsiprep`

Current BR status: candidate-pack workflow with real wrapper-backed execution
through `run_bids_app` and `run_qsiprep`. The workflow remains preview-first by
default; set `dry_run=false` to execute.

Primary entrypoint: `workflow_qsiprep`

Required inputs:
- `bids_dir`
- `output_dir`

Optional inputs:
- `participant_label`
- `work_dir`
- `fs_license_file`
- `bids_filter_file`
- `n_cpus`
- `omp_nthreads`
- `mem_mb`
- `output_resolution`
- `hmc_model`
- `distortion_correction`
- `eddy_config`
- `low_mem`
- `extra_args`
- `dry_run` with default `true`

Expected backend:
- Current: resolved local Neurodesk/neurocommand `qsiprep` wrapper executable
- Future: stricter diffusion artifact validation and execute-gate hardening

Acceptance gate:
- `tests/integration/realdata/test_workflow_external_repo_preproc_candidates_smoke.py`
- `scripts/workflows/run_workflow_realdata_gate.py`
- `tests/integration/realdata/test_workflow_external_repo_minimal_execute_gate.py`
- `scripts/workflows/run_external_repo_minimal_execute_gate.py`

Minimal BR invocation:

```python
from brain_researcher.services.tools.runner import execute_tool

res = execute_tool(
    "workflow_qsiprep",
    {
        "bids_dir": "/data/openneuro/ds000114/bids",
        "output_dir": "./out/qsiprep_single_subject_minimal",
        "participant_label": ["01"],
        "work_dir": "./out/qsiprep_single_subject_minimal_work",
        "fs_license_file": "/path/to/freesurfer/license.txt",
        "n_cpus": 4,
        "omp_nthreads": 2,
        "mem_mb": 16000,
        "output_resolution": "1.25mm",
        "extra_args": ["--skip-bids-validation"],
        "dry_run": False,
    },
)
```

Minimal execute gate:

```bash
python scripts/workflows/run_external_repo_minimal_execute_gate.py \
  --workflow-id workflow_qsiprep
```

MCP recipe:
- `get_execution_recipe("workflow_qsiprep", target_runtime="neurodesk"|"container"|"slurm")`
- The returned recipe should include `README.md`, `params.json`, and a runnable
  `run_workflow_qsiprep.sh`.
