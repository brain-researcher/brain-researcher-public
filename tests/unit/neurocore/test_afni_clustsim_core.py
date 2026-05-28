from __future__ import annotations

from pathlib import Path

from brain_researcher.services.tools.params import (
    AFNIClustSimParameters,
    run_afni_clustsim,
)


def test_run_afni_clustsim(tmp_path):
    params = AFNIClustSimParameters(
        input_file=None,
        mask_file=None,
        fwhm=None,
        pthr=(0.01, 0.001),
        athr=(0.05,),
        iterations=500,
        seed=42,
        sided=2,
        prefix="demo",
        acf=True,
        fast=False,
        nodec=False,
        output_dir=str(tmp_path / "afni"),
    )

    result = run_afni_clustsim(params)
    summary_path = Path(result["outputs"]["summary"])
    assert summary_path.exists()
    assert result["summary"]["iterations"] == 500
