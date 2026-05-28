# Workflow Runbook: FitLins Multiverse Yeo17

Source repo: `poldracklab/fitlins`

Current BR status: candidate-pack workflow that drives the local
`run_fitlins_multiverse_execute.py` orchestration script. It executes a compact
container-first FitLins multiverse and materializes Yeo17 robustness summaries
when available. Wrapper execution remains available as a development fallback.

Primary entrypoint: `workflow_fitlins_multiverse_yeo17`

Example dataset: `ds000114`

Required inputs:
- `bids_dir`
- `fmriprep_dir`
- `output_dir`

Optional inputs:
- `task`
- `participant_label_csv`
- `analysis_level`
- `runtime`
- `k`
- `no_priors`
- `skip_yeo17`

Expected outputs:
- `fitlins_multiverse/run_manifest.json`

Optional outputs:
- `fitlins_multiverse/specs/multiverse_manifest.json`
- `fitlins_multiverse/fitlins/yeo17_summary.csv`
- `fitlins_multiverse/fitlins/robustness_yeo17.json`
- `fitlins_multiverse/fitlins/robustness_yeo17.md`

Acceptance gate:
- `tests/integration/realdata/test_workflow_fitlins_multiverse_yeo17_smoke.py`
- `scripts/workflows/run_workflow_realdata_gate.py`

Minimal BR invocation:

```python
from brain_researcher.services.tools.runner import execute_tool

res = execute_tool(
    "workflow_fitlins_multiverse_yeo17",
    {
        "bids_dir": "/data/openneuro/ds000114/bids",
        "fmriprep_dir": "/data/openneuro/ds000114/derivatives/fmriprep",
        "output_dir": "./out/fitlins_multiverse_minimal",
        "task": "linebisection",
        "participant_label_csv": "01,02",
        "analysis_level": "run",
        "runtime": "apptainer",
        "k": 1,
        "no_priors": True,
    },
)
```

Minimal gate invocation:

```bash
python scripts/workflows/run_workflow_realdata_gate.py \
  --workflow-id workflow_fitlins_multiverse_yeo17
```

MCP recipe:
- `get_execution_recipe("workflow_fitlins_multiverse_yeo17", target_runtime="python")`
- The returned recipe is a BR-local runnable script
  (`run_workflow_fitlins_multiverse_yeo17.py`) plus `params.json`.

Related runbook:
- For importing already-finished Sherlock/OAK multiverse outputs into the BR
  run store for scientific review, see
  `docs/runbooks/fitlins_multiverse_external_import.md`.
