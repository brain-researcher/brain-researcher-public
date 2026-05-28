"""Smoke test for workflow_realtime_twophoton_closed_loop.

This workflow is intended for live microscope-side raw_socket streaming, but the
smoke uses a synthetic replay publisher so the workflow contract stays
deterministic and lightweight.
"""

from __future__ import annotations

import os
import queue
import threading
from pathlib import Path

import pytest

from brain_researcher.services.tools.realtime_twophoton_calibration import (
    build_coarse_place_calibration_bundle_from_replay,
)
from brain_researcher.services.tools.realtime_twophoton_publisher import (
    publish_replay_bundle_to_raw_socket,
)
from brain_researcher.services.tools.realtime_twophoton_runtime import (
    build_simulated_bundle,
)
from brain_researcher.services.tools.runner import execute_tool

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TMP_ROOT = PROJECT_ROOT / "out" / "tmp_tests"
TMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TMPDIR", str(TMP_ROOT))
os.environ.setdefault("BR_GRANDMASTER_ENABLE", "1")
os.environ.setdefault("BR_GRANDMASTER_STUBS", "1")


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.mark.realdata
@pytest.mark.timeout(120)
def test_workflow_realtime_twophoton_closed_loop_smoke(tmp_path: Path):
    bundle = build_simulated_bundle(
        n_frames=48,
        frame_shape=(32, 32),
        n_rois=12,
        n_state_bins=8,
        noise=0.04,
        frame_rate_hz=20.0,
    )
    calibration = build_coarse_place_calibration_bundle_from_replay(
        replay_source=bundle,
        output_dir=tmp_path / "calibration_bundle",
        decode_window_frames=4,
    )

    out_dir = tmp_path / "workflow_rt2p"
    port = _free_port()
    result_queue: queue.Queue = queue.Queue()

    def _run_workflow() -> None:
        result_queue.put(
            execute_tool(
                "workflow_realtime_twophoton_closed_loop",
                {
                    "reference_template": calibration.reference_template,
                    "roi_manifest": calibration.roi_manifest,
                    "decoder_path": calibration.decoder_bundle,
                    "output_dir": str(out_dir),
                    "data_source": "raw_socket",
                    "mode": "shadow",
                    "stream_host": "127.0.0.1",
                    "stream_port": port,
                    "stream_timeout_s": 5.0,
                    "frame_rate_hz": 20.0,
                    "controller_backend": "none",
                },
            )
        )

    workflow_thread = threading.Thread(target=_run_workflow, daemon=True)
    workflow_thread.start()

    publish_replay_bundle_to_raw_socket(
        bundle,
        host="127.0.0.1",
        port=port,
        connect_timeout_s=3.0,
        write_timeout_s=1.0,
        connect_retry_interval_s=0.05,
    )
    workflow_thread.join(timeout=10.0)

    assert not workflow_thread.is_alive()
    res = result_queue.get_nowait()
    assert res.status == "success", res.error

    workflow_data = res.data or {}
    provenance = workflow_data.get("provenance") or {}
    assert provenance.get("workflow_id") == "workflow_realtime_twophoton_closed_loop"
    assert provenance.get("recipe_family") == "realtime_twophoton"

    assert (out_dir / "summary.json").exists()
    assert (out_dir / "motion.jsonl").exists()
    assert (out_dir / "decoder.jsonl").exists()
    assert (out_dir / "controller.jsonl").exists()
    assert (out_dir / "trace_df_f.npy").exists()
