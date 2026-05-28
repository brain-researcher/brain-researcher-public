from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pandas as pd

from brain_researcher.services.tools.params.pnm_evs_regressors import (
    PnmEvsRegressorParameters,
    build_pnm_evs_command,
    run_pnm_evs_regressors,
)
from brain_researcher.services.tools.pnm_evs_regressors_tool import PnmEvsRegressorsTool


def test_build_pnm_evs_command_includes_slice_aware_arguments(tmp_path: Path):
    func_file = tmp_path / "func.nii.gz"
    func_file.write_bytes(b"fake")
    cardiac_file = tmp_path / "cardiac.txt"
    respiratory_file = tmp_path / "resp.txt"
    slice_timing = tmp_path / "slice_timing.txt"
    cardiac_file.write_text("0 0\n", encoding="utf-8")
    respiratory_file.write_text("0 0\n", encoding="utf-8")
    slice_timing.write_text("0\n0.5\n", encoding="utf-8")
    params = PnmEvsRegressorParameters(
        func_file=str(func_file),
        output_dir=str(tmp_path / "out"),
        tr=2.0,
        cardiac_file=str(cardiac_file),
        respiratory_file=str(respiratory_file),
        slice_direction="z",
        slice_order="interleaved_up",
        slice_timing_file=str(slice_timing),
    )

    cmd = build_pnm_evs_command(
        params,
        raw_output_file=str(tmp_path / "out" / "pnm_matrix.txt"),
        executable="pnm_evs",
    )

    assert "--tr" in cmd
    assert "--slicedir" in cmd
    assert "--sliceorder" in cmd
    assert "--slicetiming" in cmd
    assert "-c" in cmd
    assert "-r" in cmd



def test_run_pnm_evs_regressors_dry_run_writes_plan(tmp_path: Path):
    func_file = tmp_path / "func.nii.gz"
    func_file.write_bytes(b"fake")
    cardiac_file = tmp_path / "cardiac.txt"
    cardiac_file.write_text("0 0\n", encoding="utf-8")
    params = PnmEvsRegressorParameters(
        func_file=str(func_file),
        output_dir=str(tmp_path / "out"),
        tr=1.5,
        cardiac_file=str(cardiac_file),
        dry_run=True,
    )

    result = run_pnm_evs_regressors(params)

    assert result["dry_run"] is True
    assert result["executed"] is False
    assert Path(result["raw_output_file"]).parent.exists()
    metadata = json.loads((tmp_path / "out" / "pnm_metadata.json").read_text())
    assert metadata["tool"] == "pnm_evs_regressors"



def test_run_pnm_evs_regressors_materializes_confounds(monkeypatch, tmp_path: Path):
    import brain_researcher.services.tools.params.pnm_evs_regressors as pnm_mod

    func_file = tmp_path / "func.nii.gz"
    func_file.write_bytes(b"fake")
    cardiac_file = tmp_path / "cardiac.txt"
    respiratory_file = tmp_path / "resp.txt"
    cardiac_file.write_text("0 0\n", encoding="utf-8")
    respiratory_file.write_text("0 0\n", encoding="utf-8")
    params = PnmEvsRegressorParameters(
        func_file=str(func_file),
        output_dir=str(tmp_path / "out"),
        tr=2.0,
        cardiac_file=str(cardiac_file),
        respiratory_file=str(respiratory_file),
    )

    def _fake_execute(planned_command: list[str], *, params: PnmEvsRegressorParameters):
        raw_output = Path(params.output_dir) / f"{params.output_prefix}_pnm_matrix.txt"
        raw_output.parent.mkdir(parents=True, exist_ok=True)
        raw_output.write_text("1 2 3 4 5 6\n7 8 9 10 11 12\n", encoding="utf-8")
        return subprocess.CompletedProcess(planned_command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(pnm_mod, "_execute_pnm_evs_command", _fake_execute)

    result = run_pnm_evs_regressors(params)
    confounds = pd.read_csv(result["confounds_file"], sep="\t")

    assert result["executed"] is True
    assert confounds.columns.tolist()[:4] == [
        "cardiac_retroicor_sin1",
        "cardiac_retroicor_cos1",
        "cardiac_retroicor_sin2",
        "cardiac_retroicor_cos2",
    ]



def test_pnm_evs_regressors_tool_wraps_params(tmp_path: Path):
    func_file = tmp_path / "func.nii.gz"
    func_file.write_bytes(b"fake")
    cardiac_file = tmp_path / "cardiac.txt"
    cardiac_file.write_text("0 0\n", encoding="utf-8")

    result = PnmEvsRegressorsTool()._run(
        func_file=str(func_file),
        tr=2.0,
        cardiac_file=str(cardiac_file),
        output_dir=str(tmp_path / "out"),
        dry_run=True,
    )

    assert result.status == "success"
    assert result.data["tool"] == "pnm_evs_regressors"
