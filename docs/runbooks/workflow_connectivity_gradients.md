# Workflow Runbook: Connectivity Gradients

Current BR status: active BR-native connectivity workflow whose current BR
baseline is connectivity plus graph-topology summaries. It computes a
connectivity matrix and then runs `analyze_graph_topology` to emit graph
metrics and a graph summary.

Primary entrypoint: `workflow_connectivity_gradients`

Example dataset: `ds000114`

Required inputs:
- `timeseries`
- `output_dir`

Optional inputs:
- `connectivity_kind`

Expected outputs:
- `connectivity.npy`
- `gradients/graph_metrics.json`
- `gradients/graph_summary.json`
- `gradients/thresholded_connectivity.npy`

Acceptance gate:
- `tests/integration/realdata/test_workflow_connectivity_gradients_ds000114_smoke.py`
- `scripts/workflows/run_workflow_realdata_gate.py`

Minimal BR invocation:

```python
from brain_researcher.services.tools.runner import execute_tool

res = execute_tool(
    "workflow_connectivity_gradients",
    {
        "timeseries": "./timeseries.npy",
        "output_dir": "./out/connectivity_gradients_minimal",
    },
)
```

Minimal gate invocation:

```bash
python scripts/workflows/run_workflow_realdata_gate.py \
  --workflow-id workflow_connectivity_gradients
```

MCP recipe:
- `get_execution_recipe("workflow_connectivity_gradients", target_runtime="python")`
- The returned recipe is a BR-local runnable script (`run_workflow_connectivity_gradients.py`)
  plus `params.json`.
