from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from brain_researcher.services.tools.cvr_breath_hold_tool import CVRBreathHoldTool


def test_cvr_breath_hold_tool_estimates_lag_from_events_file(tmp_path: Path) -> None:
    t_r = 2.0
    times = np.arange(0.0, 120.0, t_r)
    event_df = pd.DataFrame(
        {
            "onset": [20.0, 60.0],
            "duration": [16.0, 16.0],
            "trial_type": ["breath_hold", "breath_hold"],
        }
    )
    events_path = tmp_path / "events.tsv"
    event_df.to_csv(events_path, sep="\t", index=False)

    event_boxcar = np.zeros_like(times)
    for onset, duration in zip(event_df["onset"], event_df["duration"], strict=True):
        event_boxcar[(times >= onset) & (times < onset + duration)] = 1.0

    lag_true = 6.0
    lagged = np.interp(times - lag_true, times, event_boxcar, left=0.0, right=0.0)
    signal = 100.0 + 4.0 * lagged + 0.05 * np.sin(2 * np.pi * 0.02 * times)

    signal_path = tmp_path / "bold.tsv"
    pd.DataFrame({"time_s": times, "roi_signal": signal}).to_csv(
        signal_path, sep="\t", index=False
    )

    result = CVRBreathHoldTool()._run(
        signal_file=str(signal_path),
        signal_column="roi_signal",
        events_file=str(events_path),
        output_dir=str(tmp_path / "out"),
        lag_min_s=0.0,
        lag_max_s=12.0,
        lag_step_s=1.0,
        baseline_window_s=10.0,
    )

    assert result.status == "success"
    outputs = result.data["outputs"]
    timeseries_path = Path(outputs["timeseries_tsv"])
    lag_scan_path = Path(outputs["lag_scan_tsv"])
    event_summary_path = Path(outputs["event_summary_tsv"])
    summary_path = Path(outputs["summary_json"])

    assert timeseries_path.exists()
    assert lag_scan_path.exists()
    assert event_summary_path.exists()
    assert summary_path.exists()

    timeseries_df = pd.read_csv(timeseries_path, sep="\t")
    lag_scan_df = pd.read_csv(lag_scan_path, sep="\t")
    event_summary_df = pd.read_csv(event_summary_path, sep="\t")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert "breath_hold_regressor" in timeseries_df.columns
    assert "breath_hold_regressor_shifted" in timeseries_df.columns
    assert abs(summary["best_lag_s"] - 6.0) <= 1.0
    assert summary["best_correlation"] > 0.9
    assert event_summary_df["amplitude"].mean() > 3.0
    assert event_summary_df["percent_change"].mean() > 3.0
    assert len(lag_scan_df) >= 10


def test_cvr_breath_hold_tool_accepts_inline_schedule(tmp_path: Path) -> None:
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
    signal_path = tmp_path / "bold.csv"
    pd.DataFrame({"roi_mean": signal}).to_csv(signal_path, index=False)

    result = CVRBreathHoldTool()._run(
        signal_file=str(signal_path),
        signal_column="roi_mean",
        t_r=t_r,
        n_scans=len(times),
        breath_hold_onsets=onsets,
        breath_hold_durations=durations,
        output_dir=str(tmp_path / "inline"),
        lag_min_s=0.0,
        lag_max_s=8.0,
        lag_step_s=1.0,
    )

    assert result.status == "success"
    summary = result.data["summary"]
    assert abs(summary["best_lag_s"] - 4.0) <= 1.0
    assert summary["n_events"] == 2
