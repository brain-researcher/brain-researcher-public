from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from brain_researcher.services.tools.params.physio_noise_regressors import (
    merge_scan_confounds_tables,
)
from brain_researcher.services.tools.physio_noise_regressors_tool import (
    PhysioNoiseRegressorTool,
)


def test_physio_noise_regressors_tool_writes_confounds_and_metadata(
    tmp_path: Path,
) -> None:
    sample_rate_hz = 10.0
    duration_s = 20.0
    times = np.arange(0.0, duration_s, 1.0 / sample_rate_hz)
    physio = pd.DataFrame(
        {
            "cardiac": np.sin(2 * np.pi * 1.2 * times),
            "respiratory": np.sin(2 * np.pi * 0.25 * times + 0.3),
        }
    )
    physio_path = tmp_path / "physio.tsv"
    physio.to_csv(physio_path, sep="\t", index=False)

    tool = PhysioNoiseRegressorTool()
    result = tool._run(
        physio_file=str(physio_path),
        sampling_rate_hz=sample_rate_hz,
        t_r=2.0,
        n_scans=8,
        output_dir=str(tmp_path / "out"),
    )

    assert result.status == "success"
    outputs = result.data["outputs"]
    confounds_path = Path(outputs["confounds_tsv"])
    metadata_path = Path(outputs["metadata_json"])
    assert confounds_path.exists()
    assert metadata_path.exists()

    confounds_df = pd.read_csv(confounds_path, sep="\t")
    assert len(confounds_df) == 8
    assert "cardiac_retroicor_sin1" in confounds_df.columns
    assert "respiratory_retroicor_cos1" in confounds_df.columns
    assert "cardiorespiratory_sum_sin1" in confounds_df.columns

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["resolved_columns"]["cardiac_column"] == "cardiac"
    assert metadata["resolved_columns"]["respiratory_column"] == "respiratory"
    assert "cardiac_retroicor_sin1" in metadata["generated_columns"]


def test_physio_noise_regressors_tool_can_resolve_single_trace(tmp_path: Path) -> None:
    sample_rate_hz = 20.0
    times = np.arange(0.0, 12.0, 1.0 / sample_rate_hz)
    physio = pd.DataFrame({"pulse_ox": np.cos(2 * np.pi * 1.1 * times)})
    physio_path = tmp_path / "physio.csv"
    physio.to_csv(physio_path, index=False)

    result = PhysioNoiseRegressorTool()._run(
        physio_file=str(physio_path),
        sampling_rate_hz=sample_rate_hz,
        t_r=1.5,
        n_scans=6,
        output_dir=str(tmp_path / "single"),
    )

    assert result.status == "success"
    confounds_df = pd.read_csv(result.data["outputs"]["confounds_tsv"], sep="\t")
    assert "cardiac_retroicor_sin1" in confounds_df.columns
    assert "respiratory_retroicor_sin1" not in confounds_df.columns


def test_merge_scan_confounds_tables_prefers_shared_columns_and_prefixes_collisions(
    tmp_path: Path,
) -> None:
    physio_path = tmp_path / "physio.tsv"
    pupil_path = tmp_path / "pupil.tsv"
    pd.DataFrame({"shared": [1.0, 2.0], "physio_only": [3.0, 4.0]}).to_csv(
        physio_path,
        sep="	",
        index=False,
    )
    pd.DataFrame({"shared": [5.0, 6.0], "pupil_only": [7.0, 8.0]}).to_csv(
        pupil_path,
        sep="	",
        index=False,
    )

    result = merge_scan_confounds_tables(
        {"physio": str(physio_path), "pupil": str(pupil_path)},
        str(tmp_path / "merged"),
    )

    merged_df = pd.read_csv(result["outputs"]["confounds_tsv"], sep="	")
    assert merged_df.columns.tolist() == [
        "shared",
        "physio_only",
        "pupil__shared",
        "pupil_only",
    ]
    assert result["summary"]["n_columns"] == 4
    assert result["summary"]["sources"][0]["label"] == "physio"
