# Workflow Runbook: Longitudinal LME

Stable-pack intent: keep a lightweight, public-data-friendly longitudinal analysis recipe inside BR.

Example dataset: `ds000114`

Primary entrypoint: `workflow_longitudinal_lme`

Required inputs:
- `data_file`
- `subject_col`
- `time_col`
- `output_dir`

Expected artifacts:
- `lme_results.csv`

Acceptance gate:
- `tests/integration/realdata/test_workflow_longitudinal_lme_ds000114_smoke.py`
- `scripts/workflows/run_workflow_realdata_gate.py`
