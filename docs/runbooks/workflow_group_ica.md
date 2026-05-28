# Workflow Runbook: Group ICA

Current BR status: active BR-native group-connectivity workflow. It runs the
lightweight CanICA-based `group_ica` baseline, computes ICA-derived
connectivity matrices, and then performs NBS-style group statistics.

Primary entrypoint: `workflow_group_ica`

Example dataset: `ds000114`

Required inputs:
- `img`
- `labels`
- `output_dir`

Optional inputs:
- `n_components`
- `threshold`
- `n_permutations`

Expected outputs:
- `group_ica/canica_components.nii.gz`
- `group_ica/canica_timecourses.npy`
- `group_ica/connectivity.npy`
- `group_ica/nbs.npy`
- `group_ica/nbs.mask.npy`
- `group_ica/nbs.components.json`
- `group_ica/nbs.json`

Acceptance gate:
- `tests/integration/realdata/test_workflow_group_ica_ds000114_smoke.py`
- `scripts/workflows/run_workflow_realdata_gate.py`

Minimal BR invocation:

```python
from brain_researcher.services.tools.runner import execute_tool

res = execute_tool(
    "workflow_group_ica",
    {
        "img": [
            "/data/openneuro/ds000114/derivatives/fmriprep/sub-01/..._desc-preproc_bold.nii.gz",
            "/data/openneuro/ds000114/derivatives/fmriprep/sub-02/..._desc-preproc_bold.nii.gz",
        ],
        "labels": [0, 1],
        "n_components": 10,
        "threshold": 1.0,
        "n_permutations": 20,
        "output_dir": "./out/group_ica_minimal",
    },
)
```

Minimal gate invocation:

```bash
python scripts/workflows/run_workflow_realdata_gate.py \
  --workflow-id workflow_group_ica
```

MCP recipe:
- `get_execution_recipe("workflow_group_ica", target_runtime="python")`
- The returned recipe is a BR-local runnable script (`run_workflow_group_ica.py`)
  plus `params.json`.
