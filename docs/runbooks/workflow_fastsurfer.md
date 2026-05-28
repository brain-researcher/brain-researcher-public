# Workflow Runbook: FastSurfer

Source repo: `Deep-MI/FastSurfer`

Current BR status: candidate-pack workflow backed by the real `run_fastsurfer`
container adapter. The workflow remains preview-first by default; set
`dry_run=false` to execute the FastSurfer backend.

Primary entrypoint: `workflow_fastsurfer`

Required inputs:
- `t1w_image`
- `subject_id`
- `output_dir`

Optional inputs:
- `fs_license_file`
- `n_threads`
- `use_gpu`
- `runtime`
- `container_image`
- `extra_args`
- `dry_run` with default `true`

Expected backend:
- Current: container-backed FastSurfer runtime via `run_fastsurfer`
- Fallback: BR still retains the generic `smri_recon` stub for lightweight paths

Acceptance gate:
- `tests/integration/realdata/test_workflow_external_repo_preproc_candidates_smoke.py`
- `scripts/workflows/run_workflow_realdata_gate.py`
- `tests/integration/realdata/test_workflow_external_repo_minimal_execute_gate.py`
- `scripts/workflows/run_external_repo_minimal_execute_gate.py`

Minimal BR invocation:

```python
from brain_researcher.services.tools.runner import execute_tool

res = execute_tool(
    "workflow_fastsurfer",
    {
        "t1w_image": "/data/openneuro/ds000114/bids/sub-01/anat/sub-01_T1w.nii.gz",
        "subject_id": "sub-01",
        "output_dir": "./out/fastsurfer_single_subject_minimal",
        "fs_license_file": "/path/to/freesurfer/license.txt",
        "n_threads": 1,
        "use_gpu": False,
        "runtime": "docker",
        "dry_run": False,
    },
)
```

Minimal execute gate:

```bash
python scripts/workflows/run_external_repo_minimal_execute_gate.py \
  --workflow-id workflow_fastsurfer
```

MCP recipe:
- `get_execution_recipe("workflow_fastsurfer", target_runtime="container")`
- The returned recipe now includes `README.md`, `params.json`, and a runnable `run_workflow_fastsurfer.sh`.
