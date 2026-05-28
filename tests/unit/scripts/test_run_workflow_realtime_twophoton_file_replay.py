"""Tests for scripts/workflows/run_workflow_realtime_twophoton_file_replay.py."""

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
from scripts.workflows import run_workflow_realtime_twophoton_file_replay as runner


def test_realtime_twophoton_file_replay_example_param_file_is_valid_json():
    repo_root = Path(__file__).resolve().parents[3]
    path = (
        repo_root
        / "configs"
        / "workflows"
        / "examples"
        / "workflow_realtime_twophoton_file_replay.params.example.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["data_source"] == "file_replay"
    assert payload["input_file"]
    assert payload["reference_template"]
    assert payload["roi_manifest"]
    assert payload["decoder_path"]
    assert payload["output_dir"]


def test_realtime_twophoton_file_replay_runner_executes(monkeypatch, tmp_path, capsys):
    bundle = build_simulated_bundle(
        n_frames=32,
        frame_shape=(32, 32),
        n_rois=8,
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
    params = {
        "input_file": str(replay_path),
        "mode": "shadow",
        "reference_template": calibration.reference_template,
        "roi_manifest": calibration.roi_manifest,
        "decoder_path": calibration.decoder_bundle,
        "calibration_meta": calibration.calibration_meta,
        "output_dir": str(tmp_path / "workflow_output"),
        "controller_backend": "none",
    }
    params_path = tmp_path / "params.json"
    params_path.write_text(json.dumps(params), encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "run_workflow_realtime_twophoton_file_replay.py",
            "--params",
            str(params_path),
        ],
    )

    exit_code = runner.main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["status"] == "success"
    assert payload["data"]["workflow"] == "workflow_realtime_twophoton_file_replay"
    assert (Path(params["output_dir"]) / "summary.json").exists()
