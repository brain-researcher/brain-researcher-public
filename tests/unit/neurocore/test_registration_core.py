from __future__ import annotations

from pathlib import Path

from brain_researcher.services.tools.params import (
    RegistrationParameters,
    run_registration,
)


def test_run_registration(tmp_path):
    moving = tmp_path / "moving.nii.gz"
    fixed = tmp_path / "fixed.nii.gz"
    moving.write_text("moving", encoding="utf-8")
    fixed.write_text("fixed", encoding="utf-8")

    params = RegistrationParameters(
        moving_image=str(moving),
        fixed_image=str(fixed),
        output_dir=str(tmp_path / "out"),
        registration_type="affine",
        transform_type="Affine",
        metric="MI",
        iterations=(100, 50),
        shrink_factors=(4, 2),
        smoothing_sigmas=(2.0, 1.0),
        interpolation="Linear",
        save_transform=True,
        save_warped=True,
        save_inverse=False,
        save_field=False,
        compute_similarity=True,
        seed=None,
    )

    result = run_registration(params)
    summary_path = Path(result["outputs"]["summary"])
    assert summary_path.exists()
