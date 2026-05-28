# Workflow Runbook: DWI Connectome

Source repo: `MRtrix3/mrtrix3`

Current BR status: candidate-pack composite workflow with a derivative-first
runtime. The preferred path is `qsirecon_dir` directly, or `qsiprep_dir` that
is promoted through `workflow_qsirecon` before Brain Researcher materializes a
standardized connectome contract. A raw `dwi`/`bvals`/`bvecs` tractography
fallback remains available for compatibility and lightweight smoke coverage.

Primary entrypoint: `workflow_dwi_connectome`

Example dataset: `ds000117`

Required inputs:
- `atlas`
- `output_dir`

Optional inputs:
- `qsirecon_dir`
- `qsiprep_dir`
- `recon_dir`
- `tractogram`
- `connectome_file`
- `dwi`
- `bvals`
- `bvecs`
- `participant_label`
- `session_label`
- `recon_spec`
- `work_dir`
- `fs_license_file`
- `n_cpus`
- `omp_nthreads`
- `extra_args`
- `qsirecon_extra_args`
- `dry_run`

Expected outputs:
- `sc/connectivity_matrix.csv`
- `sc/connectivity_matrix.npy`
- `sc/graph_metrics.json`
- `sc/connectome_manifest.json`

Optional route-dependent outputs:
- `qsirecon_dir`
- `tractogram`
- `source_connectome`
- `tracts/streamlines.npy`
- `tracts/tractography_summary.json`
- `tracts/tractography_provenance.json`

Acceptance gate:
- `tests/integration/realdata/test_workflow_dwi_connectome_ds000117_smoke.py`
- `scripts/workflows/run_workflow_realdata_gate.py`

Minimal BR invocation:

```python
from brain_researcher.services.tools.runner import execute_tool

res = execute_tool(
    "workflow_dwi_connectome",
    {
        "qsiprep_dir": "/data/openneuro/ds000117/derivatives/qsiprep",
        "atlas": "/data/atlases/Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz",
        "output_dir": "./out/dwi_connectome_single_subject_minimal",
        "participant_label": ["01"],
        "recon_spec": "mrtrix_multishell_msmt_ACT-hsvs",
        "dry_run": False,
    },
)
```

Minimal gate invocation:

```bash
python scripts/workflows/run_workflow_realdata_gate.py \
  --workflow-id workflow_dwi_connectome
```

MCP recipe:
- `get_execution_recipe("workflow_dwi_connectome", target_runtime="neurodesk"|"container"|"slurm")`
- The generated recipe is derivative-first: it prefers an existing
  `qsirecon_dir`, otherwise runs QSIRecon against `qsiprep_dir` and then
  standardizes the connectome outputs into the BR artifact contract.
