# Workflow Runbook: QSIRecon

Source repo: `PennLINC/qsirecon`

Current BR status: candidate-pack workflow with constrained reconstruction
preview by default and real wrapper-backed execution when `dry_run=false`.

Primary entrypoint: `workflow_qsirecon`

Required inputs:
- `qsiprep_dir`
- `output_dir`
- `recon_spec`

Optional inputs:
- `participant_label`
- `work_dir`
- `fs_license_file`
- `n_cpus`
- `omp_nthreads`
- `extra_args`
- `dry_run` with default `true`

Expected backend:
- Current: resolved local `qsirecon` wrapper executable with constrained preset handling
- Future: stronger whitelist/provenance checks and richer reconstruction artifact collection

Acceptance gate:
- `tests/integration/realdata/test_workflow_external_repo_preproc_candidates_smoke.py`
- `scripts/workflows/run_workflow_realdata_gate.py`
- `tests/integration/realdata/test_workflow_external_repo_minimal_execute_gate.py`
- `scripts/workflows/run_external_repo_minimal_execute_gate.py`

Minimal BR invocation:

```python
from brain_researcher.services.tools.runner import execute_tool

res = execute_tool(
    "workflow_qsirecon",
    {
        "qsiprep_dir": "/data/derivatives/ds000114-qsiprep",
        "output_dir": "./out/qsirecon_single_subject_minimal",
        "recon_spec": "mrtrix_multishell_msmt_ACT-hsvs",
        "participant_label": ["01"],
        "work_dir": "./out/qsirecon_single_subject_minimal_work",
        "fs_license_file": "/path/to/freesurfer/license.txt",
        "n_cpus": 4,
        "omp_nthreads": 2,
        "dry_run": False,
    },
)
```

Minimal execute gate:

```bash
python scripts/workflows/run_external_repo_minimal_execute_gate.py \
  --workflow-id workflow_qsirecon
```

MCP recipe:
- `get_execution_recipe("workflow_qsirecon", target_runtime="container"|"slurm")`
- The returned recipe should include `README.md`, `params.json`, and a runnable
  `run_workflow_qsirecon.sh`.
