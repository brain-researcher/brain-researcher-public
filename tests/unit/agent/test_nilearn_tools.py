"""Lightweight tests for nilearn visualization tools.

These tests avoid heavy plotting by monkeypatching nilearn.plotting to a
dummy object that writes a small placeholder file.
"""

from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd

from brain_researcher.services.tools.nilearn_preprocessing import ConfoundsCleanTool
from brain_researcher.services.tools.nilearn_viz import VizStatMapTool


def _make_dummy_nifti(path: Path):
    data = np.zeros((4, 4, 4), dtype=np.float32)
    img = nib.Nifti1Image(data, affine=np.eye(4))
    nib.save(img, path)


def test_viz_stat_maps_writes_output(monkeypatch, tmp_path):
    """viz_stat_maps should return success and honor output_file."""

    stat_map = tmp_path / "stat.nii.gz"
    _make_dummy_nifti(stat_map)

    out_png = tmp_path / "out.png"

    class DummyDisplay:
        def savefig(self, fname, dpi=300):
            Path(fname).write_text("ok")

    def fake_plot_stat_map(*args, **kwargs):
        return DummyDisplay()

    monkeypatch.setattr("nilearn.plotting.plot_stat_map", fake_plot_stat_map)

    tool = VizStatMapTool()
    result = tool._invoke(
        stat_map=str(stat_map),
        bg_img=str(stat_map),
        output_file=str(out_png),
        display_mode="ortho",
    )

    assert result.status == "success"
    assert out_png.exists()
    # New contract: output_file should also be mirrored under outputs for runner callers
    assert result.data.get("output_file") == str(out_png)
    assert result.data.get("outputs", {}).get("output_file") == str(out_png)


def test_clean_confounds_sanitizes_non_finite_regressors(monkeypatch, tmp_path):
    """clean_confounds should zero-fill NaN/Inf regressors before nilearn."""

    confounds_tsv = tmp_path / "confounds.tsv"
    pd.DataFrame(
        {
            "trans_x": [0.0, 0.1, 0.2],
            "trans_x_derivative1": [np.nan, 0.1, np.inf],
            "rot_y": [0.0, 0.01, 0.02],
            "white_matter": [0.5, 0.4, 0.3],
        }
    ).to_csv(confounds_tsv, sep="\t", index=False)

    img = nib.Nifti1Image(np.zeros((4, 4, 4, 3), dtype=np.float32), affine=np.eye(4))
    captured = {}

    def fake_load_img(path):
        assert path == "dummy_bold.nii.gz"
        return img

    def fake_clean_img(img_arg, confounds=None, **kwargs):
        captured["confounds"] = confounds
        captured["kwargs"] = kwargs
        return img_arg

    monkeypatch.setattr("nilearn.image.load_img", fake_load_img)
    monkeypatch.setattr("nilearn.image.clean_img", fake_clean_img)

    result = ConfoundsCleanTool()._invoke(
        img="dummy_bold.nii.gz",
        confounds=str(confounds_tsv),
        strategy="motion",
        motion_params=True,
        wm_csf=True,
        scrub_threshold=0.0,
        t_r=2.0,
    )

    assert result["status"] == "success"
    assert result["n_sanitized_values"] == 2
    assert "trans_x_derivative1" in result["sanitized_confounds"]
    assert np.isfinite(captured["confounds"]).all()
    assert captured["confounds"][0, 1] == 0.0
    assert captured["confounds"][2, 1] == 0.0
