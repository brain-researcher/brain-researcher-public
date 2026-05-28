from __future__ import annotations

from pathlib import Path

from brain_researcher.services.tools.params import (
    ANTsRegistrationParameters,
    run_ants_registration,
)


def test_run_ants_registration(tmp_path):
    fixed = tmp_path / "fixed.nii.gz"
    moving = tmp_path / "moving.nii.gz"
    fixed.write_text("fixed", encoding="utf-8")
    moving.write_text("moving", encoding="utf-8")

    params = ANTsRegistrationParameters(
        fixed_image=str(fixed),
        moving_image=str(moving),
        output_prefix=str(tmp_path / "ants" / "reg"),
        transform_type="SyN",
        metric="MI",
        convergence="[100x50,1e-6,10]",
        shrink_factors="4x2",
        smoothing_sigmas="2x1vox",
        interpolation="Linear",
        use_histogram_matching=True,
        dimension=3,
        float_precision=False,
        verbose=False,
        num_threads=1,
        extra_args=(),
    )

    result = run_ants_registration(params)
    summary_path = Path(result["outputs"]["summary"])
    assert summary_path.exists()
    assert result["summary"]["transform"] == "SyN"
