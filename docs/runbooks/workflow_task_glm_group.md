# Workflow Runbook: Task GLM Group

Current BR status: composite workflow that batches subject-level first-level
GLMs through `glm_first_level_batch` and then runs an intercept-only
second-level GLM through `run_glm_second_level`. This is a BR-native Nilearn
workflow contract, not a FitLins orchestration surface. The preferred MCP
recipe target is now `python`, because the workflow is executed through Brain
Researcher directly rather than through an external BIDS App runtime.

Primary entrypoint: `workflow_task_glm_group`

Example dataset: `ds000114`

Required inputs:
- `output_dir`

Optional inputs:
- `img`
- `events`
- `bids_dir`
- `fmriprep_dir`
- `task`
- `participant_label`
- `session`
- `space`
- `t_r`
- `smoothing_fwhm`
- `mask_img`
- `contrast_name`
- `dry_run`

Expected outputs:
- `first_level_dirs`
- `selected_zmaps`
- `resolved_inputs_manifest`
- `group_zmap`
- `first_level/<subject>/<contrast_name>_zmap.nii.gz`
- `first_level/<subject>/glm_first_level_summary.json`
- `second_level/group_zmap.nii.gz`
- `second_level/glm_second_level_summary.json`

Acceptance gate:
- `tests/integration/realdata/test_workflow_task_glm_group_ds000114_smoke.py`
- `scripts/workflows/run_workflow_realdata_gate.py`

Minimal BR invocation:

```python
from brain_researcher.services.tools.runner import execute_tool

res = execute_tool(
    "workflow_task_glm_group",
    {
        "img": [
            "/data/openneuro/ds000114/derivatives/fmriprep/sub-01/..._desc-preproc_bold.nii.gz",
            "/data/openneuro/ds000114/derivatives/fmriprep/sub-02/..._desc-preproc_bold.nii.gz",
        ],
        "events": [
            "/data/openneuro/ds000114/bids/sub-01/..._events.tsv",
            "/data/openneuro/ds000114/bids/sub-02/..._events.tsv",
        ],
        "t_r": 2.0,
        "contrast_name": "Correct_Task",
        "output_dir": "./out/task_glm_group_minimal",
    },
)
```

Minimal gate invocation:

```bash
python scripts/workflows/run_workflow_realdata_gate.py \
  --workflow-id workflow_task_glm_group
```

MCP recipe:
- `get_execution_recipe("workflow_task_glm_group", target_runtime="python")`
- The returned recipe is a BR-local runnable script (`run_workflow_task_glm_group.py`)
  plus `params.json`.
