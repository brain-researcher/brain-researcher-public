# Workflow Runbook: Real-time Two-Photon Closed Loop

Current BR status: raw-socket realtime workflow for head-fixed two-photon
experiments. The workflow wraps `realtime_twophoton` in streaming mode and is
designed to pair with the microscope-side callback adapter in
`brain_researcher.services.tools.realtime_twophoton`.

Primary entrypoint: `workflow_realtime_twophoton_closed_loop`

Required inputs:
- `reference_template`
- `roi_manifest`
- `decoder_path`
- `output_dir`

Common optional inputs:
- `data_source` with default `raw_socket`
- `mode` with default `closed_loop`
- `stream_host` with default `127.0.0.1`
- `stream_port` with default `7788`
- `stream_timeout_s`
- `stream_max_frames`
- `frame_rate_hz`
- `calibration_meta`
- `state_space`
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

Minimal BR invocation:

```python
from brain_researcher.services.tools.runner import execute_tool

res = execute_tool(
    "workflow_realtime_twophoton_closed_loop",
    {
        "reference_template": "/path/to/reference_template.npy",
        "roi_manifest": "/path/to/roi_manifest.npz",
        "decoder_path": "/path/to/decoder.joblib",
        "output_dir": "./out/realtime_twophoton_session",
        "data_source": "raw_socket",
        "mode": "closed_loop",
        "stream_host": "127.0.0.1",
        "stream_port": 7788,
        "controller_backend": "none",
    },
)
```

Repo-local runner:

```bash
python scripts/workflows/run_workflow_realtime_twophoton_closed_loop.py \
  --params configs/workflows/examples/workflow_realtime_twophoton_closed_loop.file_replay.params.example.json
```

Example parameter templates:
- `configs/workflows/examples/workflow_realtime_twophoton_closed_loop.file_replay.params.example.json`
- `configs/workflows/examples/workflow_realtime_twophoton_closed_loop.raw_socket.params.example.json`

Prepare a synthetic demo bundle plus ready-to-edit params:

```bash
python scripts/demos/prepare_realtime_twophoton_demo.py \
  --output-root out/realtime_twophoton_demo
```

Microscope-side callback adapter:

```python
from brain_researcher.services.tools.realtime_twophoton import (
    MicroscopeFrameAdapter,
    MicroscopeFrameAdapterConfig,
    RawSocketPublisherConfig,
)

adapter = MicroscopeFrameAdapter(
    MicroscopeFrameAdapterConfig(
        publisher=RawSocketPublisherConfig(host="127.0.0.1", port=7788),
        session_id="mouse_01",
        source_name="vendor_sdk",
    )
)

adapter.start_session()
adapter.publish_frame(frame, timestamp_s=timestamp_s)
adapter.end_session()
adapter.close()
```

Mapped payload callback for a vendor SDK:

```python
callback = adapter.make_field_callback(
    frame_field=("frame", "image"),
    timestamp_field=("timestamp_s", "timestamp"),
    frame_id_field=("frame_id", "index"),
    metadata_fields={"plane": "meta.plane"},
    optional_metadata_fields={"channel": ("meta.channel", "channel")},
)

vendor_sdk.register_frame_callback(callback)
```

Vendor preset helpers:
- `brain_researcher.services.tools.realtime_twophoton_vendors.available_vendor_presets()`
- `brain_researcher.services.tools.realtime_twophoton_vendors.build_vendor_callback(...)`

Minimal publisher script:

```bash
python scripts/realtime_twophoton_raw_socket_publisher.py \
  --replay /path/to/replay_bundle.npz \
  --host 127.0.0.1 \
  --port 7788
```

SDK callback bridge example:

```bash
python scripts/realtime_twophoton_sdk_callback_bridge_example.py \
  --host 127.0.0.1 \
  --port 7788 \
  --n-frames 20
```

Smoke test:
- `tests/integration/realdata/test_workflow_realtime_twophoton_closed_loop_smoke.py`

Notes:
- For deterministic smoke/debugging, override `data_source=file_replay`.
- For live rig use, keep `data_source=raw_socket` and start the microscope-side
  adapter before or just after the workflow listener starts.
