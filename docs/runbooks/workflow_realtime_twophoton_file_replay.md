# Workflow Runbook: Real-time Two-Photon File Replay

Current BR status: replay-only realtime two-photon workflow for validating the
online stack without live hardware. This workflow wraps `realtime_twophoton` in
`file_replay` mode and is intended for shadow-mode validation, regression
testing, and recipe-first MCP execution.

Primary entrypoint: `workflow_realtime_twophoton_file_replay`

Required inputs:
- `input_file`
- `reference_template`
- `roi_manifest`
- `decoder_path`
- `output_dir`

Common optional inputs:
- `mode` with default `shadow`
- `calibration_meta`
- `state_space`
- `frame_rate_hz`
- `controller_backend`
- `controller_host`
- `controller_port`
- `controller_target`
- `motion_correction`
- `motion_backend`
- `motion_confidence_threshold`
- `max_translation_px`
- `drop_on_low_confidence`
- `baseline_window_frames`
- `neuropil_correction`
- `decoder_threshold`
- `decoder_release_threshold`
- `state_hold_frames`
- `refractory_frames`
- `save_frames`

Expected outputs:
- `summary.json`
- `motion.jsonl`
- `decoder.jsonl`
- `controller.jsonl`
- `trace_df_f.npy`
- `timing.jsonl`
- `registered_frames.npy` when `save_frames=true`

Prepare a synthetic demo bundle:

```bash
python scripts/demos/prepare_realtime_twophoton_demo.py \
  --output-root out/realtime_twophoton_demo
```

Repo-local runner:

```bash
python scripts/workflows/run_workflow_realtime_twophoton_file_replay.py \
  --params configs/workflows/examples/workflow_realtime_twophoton_file_replay.params.example.json
```

Example parameter template:
- `configs/workflows/examples/workflow_realtime_twophoton_file_replay.params.example.json`

Then run the replay workflow directly:

```bash
python - <<'PY'
from brain_researcher.services.tools.executor import execute_tool

result = execute_tool(
    "workflow_realtime_twophoton_file_replay",
    {
        "input_file": "out/realtime_twophoton_demo/replay_bundle.npz",
        "reference_template": "out/realtime_twophoton_demo/calibration_bundle/reference_template.npy",
        "roi_manifest": "out/realtime_twophoton_demo/calibration_bundle/roi_manifest.npz",
        "decoder_path": "out/realtime_twophoton_demo/calibration_bundle/decoder.joblib",
        "calibration_meta": "out/realtime_twophoton_demo/calibration_bundle/calibration_meta.json",
        "output_dir": "out/realtime_twophoton_demo/workflow_output_file_replay"
    },
)
print(result)
PY
```

Repo-local closed-loop runner remains available at:
- `scripts/workflows/run_workflow_realtime_twophoton_closed_loop.py`

MCP recipe:
- `get_execution_recipe("workflow_realtime_twophoton_file_replay", target_runtime="python")`
- The returned recipe is a local runnable Python script
  (`run_workflow_realtime_twophoton_file_replay.py`) plus `params.json`,
  `run_pack.py`, and `pack_manifest.json`.

Smoke test:
- `tests/integration/realdata/test_workflow_realtime_twophoton_file_replay_smoke.py`
