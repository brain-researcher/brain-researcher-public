# Workflow Runbook: Seed-Based Connectivity

Current BR status: active BR-native voxelwise seed-connectivity workflow. The
workflow delegates to `seed_based_fc` and is intended for preprocessed
single-subject fMRI volumes.

Primary entrypoint: `workflow_seed_based_connectivity`

Example dataset: `ds000114`

Required inputs:
- `img`
- `output_dir`

Optional inputs:
- `seed_coords`
- `seed_mask`
- `radius`
- `mask_img`
- `smoothing_fwhm`
- `standardize`
- `detrend`
- `low_pass`
- `high_pass`
- `t_r`
- `confounds`

Expected outputs:
- `seed_based_fc.nii.gz`

Acceptance gate:
- `tests/integration/realdata/test_workflow_seed_based_connectivity_ds000114_smoke.py`
- `scripts/workflows/run_workflow_realdata_gate.py`

Minimal BR invocation:

```python
from brain_researcher.services.tools.runner import execute_tool

res = execute_tool(
    "workflow_seed_based_connectivity",
    {
        "img": "/data/openneuro/ds000114/derivatives/fmriprep/sub-01/..._desc-preproc_bold.nii.gz",
        "seed_coords": [0.0, -52.0, 18.0],
        "output_dir": "./out/seed_connectivity_minimal",
    },
)
```

Minimal gate invocation:

```bash
python scripts/workflows/run_workflow_realdata_gate.py \
  --workflow-id workflow_seed_based_connectivity
```

MCP recipe:
- `get_execution_recipe("workflow_seed_based_connectivity", target_runtime="python")`
- The returned recipe is a local runnable Python script plus `params.json`.
