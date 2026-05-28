# Workflow Runbook: Rest Connectome E2E

Current BR status: active BR-native connectivity workflow. It fetches or reuses
an atlas, extracts ROI timeseries, and computes a single-subject functional
connectivity matrix through the local Python toolchain.

Verified prod/UI smoke: `job_018f571e7531` on OpenNeuro `ds000114` completed
for `workflow_rest_connectome_e2e` and produced the required outputs
`timeseries/timeseries.npy`, `timeseries/timeseries.csv`, and
`connectivity_matrix.npy`; the workflow now also declares the emitted
`feature_contract.json` sidecar. The UI renders those outputs as ready.

Primary entrypoint: `workflow_rest_connectome_e2e`

Example dataset: `ds000114`

Required inputs:
- `img`
- `output_dir`

Optional inputs:
- `atlas_name`
- `atlas_path`
- `connectivity_kind`

Expected outputs:
- `atlas/*`
- `timeseries/timeseries.npy`
- `timeseries/timeseries.csv`
- `timeseries/timeseries_summary.json`
- `connectivity_matrix.npy`
- `feature_contract.json`

Acceptance gate:
- `tests/integration/realdata/test_workflow_rest_connectome_ds000114_smoke.py`
- `scripts/workflows/run_workflow_realdata_gate.py`

Minimal BR invocation:

```python
from brain_researcher.services.tools.runner import execute_tool

res = execute_tool(
    "workflow_rest_connectome_e2e",
    {
        "img": "/data/openneuro/ds000114/derivatives/fmriprep/sub-01/..._desc-preproc_bold.nii.gz",
        "atlas_name": "Schaefer2018_100",
        "output_dir": "./out/rest_connectome_minimal",
    },
)
```

Minimal gate invocation:

```bash
python scripts/workflows/run_workflow_realdata_gate.py \
  --workflow-id workflow_rest_connectome_e2e
```

MCP recipe:
- `get_execution_recipe("workflow_rest_connectome_e2e", target_runtime="python")`
- The returned recipe is a local runnable Python script plus `params.json`.
