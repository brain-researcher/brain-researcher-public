from __future__ import annotations

from pathlib import Path

import numpy as np

from scripts import msc_schaefer_connectomes as mod


def test_session_output_paths_use_bids_like_entities(tmp_path: Path) -> None:
    paths = mod.session_output_paths("MSC01", "func01", 100, tmp_path)
    expected_prefix = (
        "sub-MSC01_ses-func01_task-rest_run-01_space-MNI152NLin2009cAsym_res-2_"
        "atlas-Schaefer2018_desc-100Parcels7Networks"
    )

    assert paths["matrix"].name == f"{expected_prefix}_corrmat.npy"
    assert paths["timeseries_npy"].name == f"{expected_prefix}_timeseries.npy"
    assert paths["timeseries_csv"].name == f"{expected_prefix}_timeseries.csv"
    assert paths["provenance"].name == f"{expected_prefix}_provenance.json"

    for token in Path(paths["matrix"]).stem.split("_")[:-1]:
        assert "-" in token


def test_aggregate_subject_reads_canonical_and_legacy_session_outputs(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(mod, "SESSIONS", ["func01", "func02"])

    canonical = mod.session_output_paths("MSC01", "func01", 100, tmp_path)
    canonical["session_dir"].mkdir(parents=True, exist_ok=True)
    canonical_matrix = np.array([[[1.0, 0.1], [0.1, 1.0]]], dtype=float)
    canonical_timeseries = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]], dtype=float)
    np.save(canonical["matrix"], canonical_matrix)
    np.save(canonical["timeseries_npy"], canonical_timeseries)

    legacy_timeseries_dir = (
        tmp_path / "sub-MSC01" / "ses-func02" / "Schaefer100" / "timeseries"
    )
    legacy_timeseries_dir.mkdir(parents=True, exist_ok=True)
    legacy_matrix = np.array([[[0.8, 0.2], [0.2, 0.8]]], dtype=float)
    legacy_timeseries = np.array([[2.0, 1.0], [1.0, 2.0]], dtype=float)
    np.save(legacy_timeseries_dir.parent / "connectivity_matrix.npy", legacy_matrix)
    np.save(legacy_timeseries_dir / "timeseries.npy", legacy_timeseries)

    mod.aggregate_subject("MSC01", 100, tmp_path)

    agg_dir = tmp_path / "sub-MSC01" / "aggregate"
    stacked = np.load(agg_dir / "Schaefer100_session_matrices.npy")
    concat_ts = np.load(agg_dir / "Schaefer100_concat_timeseries.npy")

    assert stacked.shape == (2, 2, 2)
    np.testing.assert_array_equal(stacked[0], canonical_matrix[0])
    np.testing.assert_array_equal(stacked[1], legacy_matrix[0])
    np.testing.assert_array_equal(
        concat_ts,
        np.concatenate([canonical_timeseries, legacy_timeseries], axis=0),
    )


def test_fetch_schaefer_atlas_prefers_templateflow_api_over_legacy_local(
    tmp_path: Path, monkeypatch
) -> None:
    atlas_root = tmp_path / "atlas_root"
    legacy_dir = atlas_root / "schaefer_2018"
    legacy_dir.mkdir(parents=True)
    legacy = legacy_dir / "Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz"
    legacy.write_bytes(b"legacy")

    templateflow_root = tmp_path / "templateflow" / "tpl-MNI152NLin2009cAsym"
    templateflow_root.mkdir(parents=True)
    fetched = (
        templateflow_root
        / "tpl-MNI152NLin2009cAsym_res-02_atlas-Schaefer2018_desc-100Parcels7Networks_dseg.nii.gz"
    )
    fetched.write_bytes(b"templateflow")

    def _fail_if_called(**kwargs):
        raise AssertionError("unexpected schaefer nilearn fetch")

    monkeypatch.setenv("BR_ATLAS_SEARCH_ROOTS", str(atlas_root))
    monkeypatch.setattr(
        mod,
        "fetch_templateflow_schaefer_atlas",
        lambda **kwargs: fetched,
    )
    monkeypatch.setattr(mod.datasets, "fetch_atlas_schaefer_2018", _fail_if_called)

    resolved = mod.fetch_schaefer_atlas(100, tmp_path / "cache")
    assert resolved == fetched
