"""Tests for scripts/demos/prepare_realtime_twophoton_demo.py."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.demos import prepare_realtime_twophoton_demo as script


def test_prepare_realtime_twophoton_demo_writes_bundle_and_params(
    monkeypatch, tmp_path, capsys
):
    output_root = tmp_path / "demo"
    monkeypatch.setattr(
        "sys.argv",
        [
            "prepare_realtime_twophoton_demo.py",
            "--output-root",
            str(output_root),
            "--n-frames",
            "24",
            "--n-rois",
            "6",
        ],
    )

    exit_code = script.main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert Path(payload["replay_bundle"]).exists()
    calibration = payload["calibration_bundle"]
    assert Path(calibration["reference_template"]).exists()
    assert Path(calibration["roi_manifest"]).exists()
    assert Path(calibration["decoder_bundle"]).exists()
    assert Path(calibration["calibration_meta"]).exists()
    assert Path(payload["params_files"]["file_replay"]).exists()
    assert Path(payload["params_files"]["raw_socket"]).exists()
