"""Unit tests for target-space dispatch in run_forward_encoding_v2."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from scripts.analysis import run_forward_encoding_v2 as fev2


def test_load_y_dispatch_voxel(monkeypatch) -> None:
    df = pd.DataFrame({"map_path": ["a.nii.gz", "b.nii.gz"]})

    def fake_load_resampled(_df):
        y = np.ones((2, 3), dtype=np.float32)
        mask = np.ones((2, 2, 2), dtype=bool)
        template = object()
        keep = np.array([True, False], dtype=bool)
        return y, mask, template, keep

    monkeypatch.setattr(fev2, "load_resampled_Y", fake_load_resampled)
    Y, mask, template, keep, meta = fev2.load_Y(df, target_space="voxel")

    assert Y.shape == (2, 3)
    assert mask is not None
    assert template is not None
    assert keep.tolist() == [True, False]
    assert meta["target_space"] == "voxel"
    assert meta["n_targets"] == 3


def test_load_y_dispatch_schaefer(monkeypatch) -> None:
    df = pd.DataFrame({"map_path": ["a.nii.gz"]})

    def fake_load_parcel(_df, **kwargs):
        y = np.ones((1, 4), dtype=np.float32)
        keep = np.array([True], dtype=bool)
        meta = {"target_space": "schaefer", "n_targets": 4, "atlas_name": "Schaefer2018"}
        return y, keep, meta

    monkeypatch.setattr(fev2, "load_parcel_Y_schaefer", fake_load_parcel)
    Y, mask, template, keep, meta = fev2.load_Y(df, target_space="schaefer")

    assert Y.shape == (1, 4)
    assert mask is None
    assert template is None
    assert keep.tolist() == [True]
    assert meta["target_space"] == "schaefer"
    assert meta["n_targets"] == 4


def test_peak_distance_is_nan_without_voxel_context() -> None:
    y_true = np.asarray([1.0, 2.0, 3.0])
    y_pred = np.asarray([1.5, 1.0, 2.5])
    d = fev2.peak_distance_mm(y_true, y_pred, None, None)
    assert math.isnan(d)


def test_load_parcel_handles_1d_transform(monkeypatch, tmp_path) -> None:
    class FakeAtlas:
        maps = "atlas.nii.gz"
        labels = [b"roi_1", b"roi_2"]

    class FakeMasker:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.fitted = False

        def fit(self, *args, **kwargs):
            self.fitted = True
            return self

        def transform(self, _img):
            return np.asarray([1.0, 2.0], dtype=np.float32)

    monkeypatch.setattr(
        fev2.datasets,
        "fetch_atlas_schaefer_2018",
        lambda **kwargs: FakeAtlas(),
    )
    monkeypatch.setattr(fev2, "NiftiLabelsMasker", FakeMasker)

    img = tmp_path / "sample_map.nii.gz"
    img.write_text("placeholder", encoding="utf-8")
    df = pd.DataFrame({"map_path": [str(img)]})

    Y, keep_mask, meta = fev2.load_parcel_Y_schaefer(df)

    assert Y.shape == (1, 2)
    assert keep_mask.tolist() == [True]
    assert meta["target_space"] == "schaefer"
    assert meta["n_targets"] == 2
