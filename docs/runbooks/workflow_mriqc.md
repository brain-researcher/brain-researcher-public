# Workflow Runbook: MRIQC

Source repo: `nipreps/mriqc`

Current BR status: candidate-pack workflow with real wrapper-backed execution
through `run_bids_app` and `run_mriqc`. The workflow remains preview-first by
default; set `dry_run=false` to execute. BR's minimal execute and prod
certification path adds `--no-sub` so the single-subject gate stays within a
bounded runtime and emphasizes group-level QC table generation over
subject-report breadth.

Primary entrypoint: `workflow_mriqc`

Required inputs:
- `bids_dir`
- `output_dir`

Optional inputs:
- `analysis_level`
- `participant_label`
- `modalities`
- `work_dir`
- `bids_filter_file`
- `n_procs`
- `mem_gb`
- `extra_args`
- `dry_run` with default `true`

Expected backend:
- Current: resolved local Neurodesk/neurocommand `mriqc` wrapper executable
- Future: stricter report extraction and downstream QC table surfacing

Acceptance gate:
- `tests/integration/realdata/test_workflow_external_repo_preproc_candidates_smoke.py`
- `scripts/workflows/run_workflow_realdata_gate.py`
- `tests/integration/realdata/test_workflow_external_repo_minimal_execute_gate.py`
- `scripts/workflows/run_external_repo_minimal_execute_gate.py`

Minimal BR invocation:

```python
from brain_researcher.services.tools.runner import execute_tool

res = execute_tool(
    "workflow_mriqc",
    {
        "bids_dir": "/data/openneuro/ds000114/bids",
        "output_dir": "./out/mriqc_single_subject_minimal",
        "analysis_level": "participant",
        "participant_label": ["01"],
        "modalities": ["bold"],
        "work_dir": "./out/mriqc_single_subject_minimal_work",
        "n_procs": 4,
        "mem_gb": 8,
        "dry_run": False,
    },
)
```

Minimal execute gate:

```bash
python scripts/workflows/run_external_repo_minimal_execute_gate.py \
  --workflow-id workflow_mriqc
```

MCP recipe:
- `get_execution_recipe("workflow_mriqc", target_runtime="neurodesk"|"container"|"slurm")`
- The returned recipe now includes `README.md`, `params.json`, and a runnable `run_workflow_mriqc.sh`.
