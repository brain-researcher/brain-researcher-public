from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from brain_researcher.services.tools.calibrated_perfusion_surrogate_tool import (
    CalibratedPerfusionSurrogateTool,
)


def test_calibrated_perfusion_surrogate_tool_bundles_asl_and_cvr_outputs(
    tmp_path: Path,
) -> None:
    asl_path = tmp_path / "asl.npy"
    asl = np.zeros((4, 4, 4, 4), dtype=np.float32)
    asl[..., 0::2] = 1.2
    asl[..., 1::2] = 0.8
    np.save(asl_path, asl)

    t_r = 2.0
    times = np.arange(0.0, 80.0, t_r)
    onsets = [16.0, 40.0]
    durations = [12.0, 12.0]
    event_boxcar = np.zeros_like(times)
    for onset, duration in zip(onsets, durations, strict=True):
        event_boxcar[(times >= onset) & (times < onset + duration)] = 1.0
    lag_true = 4.0
    signal = 50.0 + 2.5 * np.interp(
        times - lag_true, times, event_boxcar, left=0.0, right=0.0
    )
    signal_path = tmp_path / "signal.csv"
    pd.DataFrame({"time_s": times, "roi_signal": signal}).to_csv(
        signal_path, index=False
    )

    events_path = tmp_path / "events.tsv"
    pd.DataFrame(
        {"onset": onsets, "duration": durations, "trial_type": ["breath_hold", "breath_hold"]}
    ).to_csv(events_path, sep="	", index=False)

    result = CalibratedPerfusionSurrogateTool()._run(
        asl_file=str(asl_path),
        signal_file=str(signal_path),
        events_file=str(events_path),
        signal_column="roi_signal",
        output_dir=str(tmp_path / "out"),
        t_r=t_r,
        n_scans=len(times),
        lag_min_s=0.0,
        lag_max_s=8.0,
        lag_step_s=1.0,
        baseline_window_s=10.0,
    )

    assert result.status == "success"
    outputs = result.data["outputs"]
    summary_path = Path(outputs["summary_json"])
    summary_tsv = Path(outputs["summary_tsv"])
    manifest_path = Path(outputs["manifest_json"])

    assert summary_path.exists()
    assert summary_tsv.exists()
    assert manifest_path.exists()

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert summary["calibration_type"] == "surrogate"
    assert summary["cmro2_estimated"] is False
    assert summary["oef_estimated"] is False
    assert summary["selected_metrics"]["cbf_mean"] is not None
    assert summary["selected_metrics"]["best_cvr_lag_s"] is not None
    assert "asl_summary" in summary and "cvr_summary" in summary
    assert manifest["tool_id"] == "calibrated_perfusion_surrogate"
    assert "asl_perfusion" in manifest["subtools"]
    assert "cvr_breath_hold" in manifest["subtools"]
    assert "cbf_mean" in summary_tsv.read_text(encoding="utf-8")
