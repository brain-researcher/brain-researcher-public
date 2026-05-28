# Workflow Runbook: Precision Parcellation

Stable-pack intent: expose individualized parcellation through the existing BR workflow surface while anchoring atlas references to shared Schaefer/Yeo assets.

Example dataset: `ds000114`

Primary entrypoint: `workflow_precision_parcellation`

Required inputs:
- `timeseries`
- `n_components`
- `output_dir`

Reference assets:
- `nilearn.atlas.schaefer2018.400.17networks`
- `nilearn.atlas.yeo2011.17networks.volume`

Expected artifacts:
- `parcellation.npz`
- `parcellation_labels.npy`
- `parcellation_stability_report.json`
- `parcellation_provenance.json`

Notes:
- `parcellation_stability_report.json` records the multi-seed agreement signal that
  makes this workflow "precision" rather than a single arbitrary factorization run.
- `parcellation_provenance.json` carries method settings plus reference-asset-friendly
  metadata so downstream workflows can preserve reference-asset context explicitly.

Acceptance gate:
- `tests/integration/realdata/test_workflow_precision_parcellation_ds000114_smoke.py`
- `scripts/workflows/run_workflow_realdata_gate.py`
