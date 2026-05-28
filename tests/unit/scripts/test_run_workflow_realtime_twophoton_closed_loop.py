"""Tests for scripts/workflows/run_workflow_realtime_twophoton_closed_loop.py."""

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
from scripts.workflows import run_workflow_realtime_twophoton_closed_loop as runner


def test_realtime_twophoton_example_param_files_are_valid_json():
    repo_root = Path(__file__).resolve().parents[3]
    example_dir = repo_root / "configs" / "workflows" / "examples"
    expected = [
        "workflow_realtime_twophoton_closed_loop.file_replay.params.example.json",
        "workflow_realtime_twophoton_closed_loop.raw_socket.params.example.json",
    ]

    for name in expected:
        path = example_dir / name
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        assert payload["reference_template"]
        assert payload["roi_manifest"]
        assert payload["decoder_path"]
        assert payload["output_dir"]


def test_realtime_twophoton_runner_executes_file_replay(monkeypatch, tmp_path, capsys):
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
        "data_source": "file_replay",
        "input_file": str(replay_path),
        "mode": "shadow",
        "reference_template": calibration.reference_template,
        "roi_manifest": calibration.roi_manifest,
        "decoder_path": calibration.decoder_bundle,
        "output_dir": str(tmp_path / "workflow_output"),
        "frame_rate_hz": 20.0,
        "controller_backend": "none",
    }
    params_path = tmp_path / "params.json"
    params_path.write_text(json.dumps(params), encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "run_workflow_realtime_twophoton_closed_loop.py",
            "--params",
            str(params_path),
        ],
    )

    exit_code = runner.main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["status"] == "success"
    assert payload["data"]["workflow"] == "workflow_realtime_twophoton_closed_loop"
    assert (Path(params["output_dir"]) / "summary.json").exists()
