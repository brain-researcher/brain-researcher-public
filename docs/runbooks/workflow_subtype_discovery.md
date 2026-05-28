# Workflow Runbook: Subtype Discovery

Stable-pack intent: provide a lightweight subtype-discovery baseline in BR while tying clustering workflows to reusable Schaefer/Yeo atlas assets.

Example dataset: `ds000114`

Primary entrypoint: `workflow_subtype_discovery`

Required inputs:
- `features`
- `n_clusters`
- `output_dir`

Reference assets:
- `nilearn.atlas.schaefer2018.400.17networks`
- `nilearn.atlas.yeo2011.17networks.volume`

Expected artifacts:
- `clusters.csv`

Acceptance gate:
- `tests/integration/realdata/test_workflow_subtype_discovery_ds000114_smoke.py`
- `scripts/workflows/run_workflow_realdata_gate.py`
