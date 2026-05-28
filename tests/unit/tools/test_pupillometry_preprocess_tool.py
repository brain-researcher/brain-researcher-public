from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from brain_researcher.services.tools.pupillometry_preprocess_tool import (
    PupillometryPreprocessTool,
)


def test_pupillometry_preprocess_tool_writes_trace_events_and_confounds(
    tmp_path: Path,
) -> None:
    sample_rate_hz = 20.0
    times = np.arange(0.0, 20.0, 1.0 / sample_rate_hz)
    baseline = 4.0 + 0.15 * np.sin(2 * np.pi * 0.1 * times)
    peaks = 0.9 * np.exp(-0.5 * ((times - 5.0) / 0.35) ** 2)
    peaks += 0.7 * np.exp(-0.5 * ((times - 12.0) / 0.4) ** 2)
    pupil = baseline + peaks
    pupil[(times >= 7.0) & (times < 7.2)] = 0.0

    pupil_path = tmp_path / "pupil.tsv"
    pd.DataFrame({"time_s": times, "pupilDiameter_raw": pupil}).to_csv(
        pupil_path, sep="\t", index=False
    )

    result = PupillometryPreprocessTool()._run(
        pupil_file=str(pupil_path),
        output_dir=str(tmp_path / "out"),
        low_pass_hz=4.0,
        tonic_low_pass_hz=0.2,
        peak_prominence_z=0.8,
        peak_distance_s=1.5,
        t_r=2.0,
        n_scans=8,
    )

    assert result.status == "success"
    outputs = result.data["outputs"]
    trace_path = Path(outputs["preprocessed_tsv"])
    events_path = Path(outputs["events_tsv"])
    confounds_path = Path(outputs["confounds_tsv"])
    metadata_path = Path(outputs["metadata_json"])

    assert trace_path.exists()
    assert events_path.exists()
    assert confounds_path.exists()
    assert metadata_path.exists()

    trace_df = pd.read_csv(trace_path, sep="\t")
    events_df = pd.read_csv(events_path, sep="\t")
    confounds_df = pd.read_csv(confounds_path, sep="\t")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert "pupil_filtered_z" in trace_df.columns
    assert "pupil_phasic_z" in trace_df.columns
    assert "pupil_tonic_z" in trace_df.columns
    assert trace_df["blink_mask"].sum() > 0
    assert trace_df["pupil_clean"].isna().sum() == 0
    assert len(events_df) >= 1
    assert set(confounds_df.columns) == {
        "pupil_filtered_z",
        "pupil_derivative1_z",
        "pupil_tonic_z",
        "pupil_phasic_z",
        "pupil_blink_fraction",
    }
    assert len(confounds_df) == 8
    assert metadata["resolved_columns"]["pupil_column"] == "pupilDiameter_raw"
    assert metadata["resolved_columns"]["time_column"] == "time_s"


def test_pupillometry_preprocess_tool_can_synthesize_time_axis(tmp_path: Path) -> None:
    sample_rate_hz = 10.0
    times = np.arange(0.0, 8.0, 1.0 / sample_rate_hz)
    pupil = 3.5 + 0.25 * np.sin(2 * np.pi * 0.3 * times)
    pupil += 0.6 * np.exp(-0.5 * ((times - 3.0) / 0.25) ** 2)

    pupil_path = tmp_path / "pupil.csv"
    pd.DataFrame({"pupil_diameter": pupil}).to_csv(pupil_path, index=False)

    result = PupillometryPreprocessTool()._run(
        pupil_file=str(pupil_path),
        output_dir=str(tmp_path / "synth"),
        sampling_rate_hz=sample_rate_hz,
        peak_prominence_z=0.5,
    )

    assert result.status == "success"
    trace_df = pd.read_csv(result.data["outputs"]["preprocessed_tsv"], sep="\t")
    events_df = pd.read_csv(result.data["outputs"]["events_tsv"], sep="\t")
    metadata = json.loads(
        Path(result.data["outputs"]["metadata_json"]).read_text(encoding="utf-8")
    )

    assert "time_s" in trace_df.columns
    assert trace_df["time_s"].iloc[0] == 0.0
    assert metadata["resolved_columns"]["time_column"] is None
    assert metadata["resolved_columns"]["pupil_column"] == "pupil_diameter"
    assert len(events_df) >= 1


def test_pupillometry_preprocess_tool_reads_parquet_with_ibl_style_columns(
    tmp_path: Path,
) -> None:
    times = np.asarray([0.0, 0.1, 0.2, 0.3, 0.4, 0.5], dtype=float)
    pupil = np.asarray([4.1, 4.2, 0.0, 4.5, 4.8, 4.4], dtype=float)
    pupil_path = tmp_path / "ibl_pupil.pqt"
    pd.DataFrame({"time_s": times, "pupilDiameter_raw": pupil}).to_parquet(
        pupil_path, index=False
    )

    result = PupillometryPreprocessTool()._run(
        pupil_file=str(pupil_path),
        output_dir=str(tmp_path / "ibl"),
        peak_prominence_z=0.2,
    )

    assert result.status == "success"
    trace_df = pd.read_csv(result.data["outputs"]["preprocessed_tsv"], sep="\t")
    metadata = json.loads(
        Path(result.data["outputs"]["metadata_json"]).read_text(encoding="utf-8")
    )

    assert len(trace_df) == len(times)
    assert metadata["resolved_columns"]["pupil_column"] == "pupilDiameter_raw"
    assert metadata["resolved_columns"]["time_column"] == "time_s"
