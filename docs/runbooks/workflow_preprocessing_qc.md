# Workflow Runbook: Preprocessing + QC

Current BR status: composite workflow that chains `validate_bids_structure`,
`workflow_fmriprep_preprocessing`, `workflow_mriqc`, and lightweight QC
aggregation. The workflow remains preview-first by default; set `dry_run=false`
to execute the fMRIPrep and MRIQC substeps for real. BR's minimal execute path
now uses split per-backend overrides so the bounded prod recipe can force
`--fs-no-reconall` on the fMRIPrep substep and `--no-sub` on the MRIQC substep
without conflating the two backends.

Primary entrypoint: `workflow_preprocessing_qc`

Required inputs:
- `bids_dir`
- `output_dir`

Optional inputs:
- `qc_tsv`
- `participant_label`
- `work_dir`
- `fmriprep_work_dir`
- `mriqc_work_dir`
- `fs_license_file`
- `output_spaces`
- `analysis_level`
- `modalities`
- `modality`
- `bids_filter_file`
- `n_cpus`
- `omp_nthreads`
- `mem_mb`
- `n_procs`
- `mem_gb`
- `extra_args`
- `fmriprep_extra_args`
- `mriqc_extra_args`
- `skip_bids_validation`
- `outlier_metric`
- `outlier_z`
- `dashboard_title`
- `dry_run` with default `true`

Expected outputs:
- `fmriprep/` when `dry_run=false`
- `mriqc/` when `dry_run=false`
- `qc/qc_table.csv`
- `qc/qc_outliers.csv`
- `qc/qc_summary.json`
- `qc/index.html`

Acceptance gate:
- `tests/integration/realdata/test_workflow_preprocessing_qc_ds000114_smoke.py`
- `scripts/workflows/run_workflow_realdata_gate.py`
- `tests/integration/realdata/test_workflow_external_repo_minimal_execute_gate.py`
- `scripts/workflows/run_external_repo_minimal_execute_gate.py`

Minimal BR invocation:

```python
from brain_researcher.services.tools.runner import execute_tool

res = execute_tool(
    "workflow_preprocessing_qc",
    {
        "bids_dir": "/data/openneuro/ds000114/bids",
        "output_dir": "./out/preprocessing_qc_single_subject_minimal",
        "participant_label": ["01"],
        "work_dir": "./out/preprocessing_qc_single_subject_minimal_work",
        "fs_license_file": "/path/to/freesurfer/license.txt",
        "output_spaces": ["MNI152NLin2009cAsym"],
        "modalities": ["bold"],
        "n_cpus": 4,
        "omp_nthreads": 2,
        "mem_mb": 16000,
        "n_procs": 4,
        "mem_gb": 8,
        "extra_args": ["--skip-bids-validation"],
        "fmriprep_extra_args": ["--fs-no-reconall"],
        "mriqc_extra_args": ["--no-sub"],
        "qc_tsv": "/path/to/qc.tsv",
        "dry_run": False,
    },
)
```

Minimal execute gate:

```bash
python scripts/workflows/run_external_repo_minimal_execute_gate.py \
  --workflow-id workflow_preprocessing_qc
```

MCP recipe:
- `get_execution_recipe("workflow_preprocessing_qc", target_runtime="neurodesk"|"container"|"slurm")`
- The returned recipe includes `README.md`, `params.json`, `post_qc.py`, and runnable `run_workflow_preprocessing_qc.sh` / `run_fmriprep.sh` / `run_mriqc.sh` scripts.
