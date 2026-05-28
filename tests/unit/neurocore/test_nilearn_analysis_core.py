from __future__ import annotations

import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd

from brain_researcher.services.tools.params import (
    ConnectivityMatrixParameters,
    GLMFirstLevelParameters,
    GLMSecondLevelParameters,
    SeedBasedConnectivityParameters,
    run_connectivity_matrix,
    run_glm_first_level,
    run_glm_second_level,
    run_seed_based_connectivity,
)


def _make_4d_nifti(path: Path, shape: tuple[int, ...] = (5, 5, 5, 10)) -> str:
    data = np.random.randn(*shape)
    img = nib.Nifti1Image(data, np.eye(4))
    if len(shape) == 4:
        img.header.set_zooms((2.0, 2.0, 2.0, 2.0))
    else:
        img.header.set_zooms((2.0, 2.0, 2.0))
    nib.save(img, path)
    return str(path)


def test_run_glm_first_level(tmp_path):
    img = _make_4d_nifti(tmp_path / "func.nii.gz")
    mask = _make_4d_nifti(tmp_path / "mask.nii.gz", shape=(5, 5, 5))
    events = pd.DataFrame(
        {
            "onset": [0.0, 4.0],
            "duration": [1.0, 1.0],
            "trial_type": ["stim", "stim"],
        }
    )
    events_file = tmp_path / "events.tsv"
    events.to_csv(events_file, sep="\t", index=False)
    params = GLMFirstLevelParameters(
        img=str(img),
        output_dir=str(tmp_path / "glm1"),
        events=str(events_file),
        mask_img=str(mask),
    )
    result = run_glm_first_level(params)
    assert Path(result["outputs"]["summary"]).exists()


def test_run_glm_first_level_accepts_confounds_and_hrf_aliases(tmp_path):
    img = _make_4d_nifti(tmp_path / "func_alias.nii.gz")
    mask = _make_4d_nifti(tmp_path / "mask_alias.nii.gz", shape=(5, 5, 5))
    events = pd.DataFrame(
        {
            "onset": [0.0, 4.0],
            "duration": [1.0, 1.0],
            "trial_type": ["stim", "stim"],
        }
    )
    events_file = tmp_path / "events_alias.tsv"
    events.to_csv(events_file, sep="\t", index=False)
    confounds = pd.DataFrame(
        {
            "cardiac_retroicor_sin1": np.linspace(0.0, 1.0, 10),
            "respiratory_retroicor_cos1": np.linspace(1.0, 0.0, 10),
        }
    )
    confounds_file = tmp_path / "confounds.tsv"
    confounds.to_csv(confounds_file, sep="\t", index=False)

    params = GLMFirstLevelParameters(
        img=str(img),
        output_dir=str(tmp_path / "glm_alias"),
        events=str(events_file),
        hrf_model="canonical",
        mask_img=str(mask),
        confounds=str(confounds_file),
    )
    result = run_glm_first_level(params)
    summary = result["summary"]
    assert summary["hrf_model"] == "spm"
    assert summary["requested_hrf_model"] == "canonical"
    assert summary["confounds_columns"] == [
        "cardiac_retroicor_sin1",
        "respiratory_retroicor_cos1",
    ]


def test_run_glm_first_level_supports_flobs_basis(tmp_path):
    img = _make_4d_nifti(tmp_path / "func_flobs.nii.gz")
    mask = _make_4d_nifti(tmp_path / "mask_flobs.nii.gz", shape=(5, 5, 5))
    events = pd.DataFrame(
        {
            "onset": [0.0, 4.0],
            "duration": [1.0, 1.0],
            "trial_type": ["stim", "stim"],
        }
    )
    events_file = tmp_path / "events_flobs.tsv"
    events.to_csv(events_file, sep="\t", index=False)

    basis = np.column_stack(
        [
            np.exp(-np.linspace(0.0, 2.0, 20)),
            np.linspace(0.0, 1.0, 20),
            np.linspace(1.0, 0.0, 20),
        ]
    )
    basis_file = tmp_path / "flobs_basis.txt"
    np.savetxt(basis_file, basis)

    params = GLMFirstLevelParameters(
        img=str(img),
        output_dir=str(tmp_path / "glm_flobs"),
        events=str(events_file),
        hrf_model="flobs",
        mask_img=str(mask),
        flobs_basis_file=str(basis_file),
        flobs_dt=0.1,
    )
    result = run_glm_first_level(params)
    summary = result["summary"]

    assert summary["hrf_model"] == "flobs"
    assert summary["flobs_basis_file"] == str(basis_file)
    assert Path(result["outputs"]["summary"]).exists()
    assert Path(result["outputs"]["zmaps"][0]).exists()


def test_run_glm_second_level(tmp_path):
    contrast1 = _make_4d_nifti(tmp_path / "contrast1.nii.gz", shape=(5, 5, 5))
    contrast2 = _make_4d_nifti(tmp_path / "contrast2.nii.gz", shape=(5, 5, 5))
    params = GLMSecondLevelParameters(
        contrast_maps=(str(contrast1), str(contrast2)),
        output_dir=str(tmp_path / "glm2"),
    )
    result = run_glm_second_level(params)
    assert Path(result["outputs"]["summary"]).exists()


def test_run_connectivity_matrix(tmp_path):
    ts = tmp_path / "ts.npy"
    np.save(ts, np.random.rand(10, 5))
    params = ConnectivityMatrixParameters(
        timeseries=str(ts), output_file=str(tmp_path / "matrix.npy")
    )
    result = run_connectivity_matrix(params)
    assert Path(result["outputs"]["matrix"]).exists()
    contract_path = Path(result["outputs"]["feature_contract"])
    assert contract_path.exists()
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert contract["matrix_kind"] == "correlation"
    assert contract["n_rois"] == 5
    assert contract["n_timepoints"] == 10
    assert contract["transform_state"] == "fisher_z"
    assert contract["covariance_condition_number"] is not None


def test_run_partial_connectivity_matrix_contract_marks_regularization(tmp_path):
    ts = tmp_path / "ts.npy"
    np.save(ts, np.random.default_rng(0).normal(size=(30, 5)))
    params = ConnectivityMatrixParameters(
        timeseries=str(ts),
        kind="partial correlation",
        fisher_z=False,
        output_file=str(tmp_path / "partial.npy"),
    )

    result = run_connectivity_matrix(params)

    contract = json.loads(
        Path(result["outputs"]["feature_contract"]).read_text(encoding="utf-8")
    )
    assert contract["matrix_kind"] == "partial correlation"
    assert contract["precision_estimator"] == "LedoitWolf"
    assert contract["regularization"] == "regularized"
    assert contract["effective_n_timepoints"] == 30
    assert contract["precision_condition_number"] is not None


def test_run_seed_based_connectivity(tmp_path):
    img = _make_4d_nifti(tmp_path / "func.nii.gz")
    params = SeedBasedConnectivityParameters(
        img=str(img),
        output_dir=str(tmp_path / "seed"),
        seed_coords=(2.0, 2.0, 2.0),
    )
    result = run_seed_based_connectivity(params)
    assert Path(result["outputs"]["map"]).exists()
