"""Unit tests for realtime two-photon calibration helpers."""

from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.services.tools.realtime_twophoton_calibration import (
    build_coarse_place_calibration_bundle_from_replay,
)
from brain_researcher.services.tools.realtime_twophoton_runtime import (
    build_simulated_bundle,
    save_replay_bundle,
)


def test_build_coarse_place_calibration_bundle_from_replay(tmp_path: Path):
    replay_bundle = build_simulated_bundle(
        n_frames=80,
        frame_shape=(32, 32),
        n_rois=10,
        n_state_bins=8,
        noise=0.03,
        frame_rate_hz=15.0,
    )
    replay_path = save_replay_bundle(replay_bundle, tmp_path / "calibration_replay.npz")

    artifacts = build_coarse_place_calibration_bundle_from_replay(
        replay_source=replay_path,
        output_dir=tmp_path / "calibration",
        decode_window_frames=5,
    )

    assert Path(artifacts.roi_manifest).exists()
    assert Path(artifacts.reference_template).exists()
    assert Path(artifacts.decoder_bundle).exists()
    meta = json.loads(Path(artifacts.calibration_meta).read_text(encoding="utf-8"))
    assert meta["schema_version"] == "realtime-twophoton-calibration-v1"
    assert meta["state_name"] == "coarse_place_bin_8"
    assert meta["n_state_bins"] == 8
    assert meta["n_rois"] == 10
    assert meta["decode_window_frames"] == 5
