# Workflow Runbook: Data Harmonization

Source repo: `ThomasYeoLab/Standalone_An2024_DeepResBat`

Stable-pack intent: keep `brain_researcher`'s default Python ComBat-like backend runnable everywhere while reserving `deepresbat_external` as an opt-in external backend.

Example dataset: `ds000114`

Primary entrypoint: `workflow_data_harmonization`

Required inputs:
- `bids_dir`
- `features`
- `batch`
- `output_dir`

Optional inputs:
- `covars`
- `backend` with default `combat`

Expected artifacts:
- `harmonized.csv`
- `harmonization_report.json`
- `provenance.json`

Acceptance gate:
- `tests/integration/realdata/test_workflow_data_harmonization_ds000114_smoke.py`
- `scripts/workflows/run_workflow_realdata_gate.py`
