# Workflow Runbook: Network-Based Statistics

Current BR status: active BR-native group-connectivity workflow. It computes a
group stack of functional connectivity matrices and then runs the lightweight
`nbs_engine` permutation test to materialize NBS-style outputs.

Primary entrypoint: `workflow_network_based_statistics`

Example dataset: `ds000114`

Required inputs:
- `timeseries`
- `labels`
- `output_dir`

Optional inputs:
- `connectivity_kind`
- `threshold`
- `n_permutations`

Expected outputs:
- `group_connectivity.npy`
- `nbs.npy`
- `nbs.mask.npy`
- `nbs.components.json`
- `nbs.json`

Acceptance gate:
- `tests/integration/realdata/test_workflow_network_based_statistics_ds000114_smoke.py`
- `scripts/workflows/run_workflow_realdata_gate.py`

Minimal BR invocation:

```python
from brain_researcher.services.tools.runner import execute_tool

res = execute_tool(
    "workflow_network_based_statistics",
    {
        "timeseries": "./timeseries.npy",
        "labels": [0, 0, 1, 1],
        "threshold": 1.0,
        "n_permutations": 20,
        "output_dir": "./out/network_based_statistics_minimal",
    },
)
```

Minimal gate invocation:

```bash
python scripts/workflows/run_workflow_realdata_gate.py \
  --workflow-id workflow_network_based_statistics
```

MCP recipe:
- `get_execution_recipe("workflow_network_based_statistics", target_runtime="python")`
- The returned recipe is a BR-local runnable script (`run_workflow_network_based_statistics.py`)
  plus `params.json`.
