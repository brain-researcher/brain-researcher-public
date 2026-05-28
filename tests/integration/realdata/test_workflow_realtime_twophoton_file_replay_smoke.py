"""Smoke test for workflow_realtime_twophoton_file_replay."""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_researcher.services.tools.realtime_twophoton_calibration import (
    build_coarse_place_calibration_bundle_from_replay,
)
from brain_researcher.services.tools.realtime_twophoton_runtime import (
    build_simulated_bundle,
    save_replay_bundle,
)
from brain_researcher.services.tools.runner import execute_tool


@pytest.mark.realdata
def test_workflow_realtime_twophoton_file_replay_smoke(tmp_path: Path):
    bundle = build_simulated_bundle(
        n_frames=48,
        frame_shape=(32, 32),
        n_rois=12,
        n_state_bins=8,
        noise=0.04,
        frame_rate_hz=20.0,
    )
    replay_path = save_replay_bundle(bundle, tmp_path / "replay_bundle.npz")
    calibration = build_coarse_place_calibration_bundle_from_replay(
        replay_source=replay_path,
        output_dir=tmp_path / "calibration_bundle",
        decode_window_frames=4,
    )

    out_dir = tmp_path / "workflow_rt2p_file_replay"
    res = execute_tool(
        "workflow_realtime_twophoton_file_replay",
        {
            "input_file": str(replay_path),
            "mode": "shadow",
            "reference_template": calibration.reference_template,
            "roi_manifest": calibration.roi_manifest,
            "decoder_path": calibration.decoder_bundle,
            "calibration_meta": calibration.calibration_meta,
            "output_dir": str(out_dir),
            "controller_backend": "none",
        },
    )

    assert res.status == "success", res.error
    workflow_data = res.data or {}
    provenance = workflow_data.get("provenance") or {}
    assert provenance.get("workflow_id") == "workflow_realtime_twophoton_file_replay"
    assert provenance.get("recipe_family") == "realtime_twophoton_file_replay"

    assert (out_dir / "summary.json").exists()
    assert (out_dir / "motion.jsonl").exists()
    assert (out_dir / "decoder.jsonl").exists()
    assert (out_dir / "controller.jsonl").exists()
    assert (out_dir / "trace_df_f.npy").exists()
