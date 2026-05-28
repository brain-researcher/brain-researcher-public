# Workflow Runbook: FitLins Direct

Source repo: `poldracklab/fitlins`

Current BR status: candidate-pack workflow that delegates to Brain Researcher's
container-first FitLins runner. The workflow is preview-first by default and
returns the resolved command unless `dry_run=false`. Wrapper execution remains
available as a development fallback.

Primary entrypoint: `workflow_fitlins_direct`

Example dataset: `ds000114`

Required inputs:
- `bids_dir`
- `fmriprep_dir`
- `output_dir`

Optional inputs:
- `model`
- `task`
- `analysis_level`
- `participant_label`
- `work_dir`
- `reports_only`
- `runtime`
- `container_type`
- `container_image`
- `extra_args`
- `dry_run`

Expected outputs:
- `fitlins/dataset_description.json`

Optional outputs:
- `fitlins/*_stat-*_statmap.nii.gz`
- `fitlins/*/*.html`
- `fitlins/logs/*`

Acceptance gate:
- `tests/integration/realdata/test_workflow_fitlins_direct_ds000114_smoke.py`
- `scripts/workflows/run_workflow_realdata_gate.py`

Minimal BR invocation:

```python
from brain_researcher.services.tools.runner import execute_tool

res = execute_tool(
    "workflow_fitlins_direct",
    {
        "bids_dir": "/data/openneuro/ds000114/bids",
        "fmriprep_dir": "/data/openneuro/ds000114/derivatives/fmriprep",
        "model": "/data/openneuro_glmfitlins/statsmodel_specs/ds000114/ds000114-linebisection_specs.json",
        "task": "linebisection",
        "participant_label": ["01", "02"],
        "runtime": "apptainer",
        "output_dir": "./out/fitlins_direct_minimal",
        "dry_run": True,
    },
)
```

Minimal gate invocation:

```bash
python scripts/workflows/run_workflow_realdata_gate.py \
  --workflow-id workflow_fitlins_direct
```

MCP recipe:
- `get_execution_recipe("workflow_fitlins_direct", target_runtime="python")`
- The returned recipe is a BR-local runnable script (`run_workflow_fitlins_direct.py`)
  plus `params.json`.
