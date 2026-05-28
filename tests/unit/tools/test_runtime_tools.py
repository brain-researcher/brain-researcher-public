"""Tests for runtime tools in grandmaster/runtime_tools.py."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import brain_researcher.services.tools.grandmaster.runtime_tools as runtime_tools_module

from brain_researcher.services.tools.grandmaster.runtime_tools import (
    compute_brain_age_tool,
    individual_parcellation_tool,
    query_neuromaps_tool,
    run_local_script_tool,
    visual_feature_decoder_tool,
)


def test_compute_brain_age_tool(tmp_path: Path):
    """Test brain age prediction using Ridge regression."""
    np.random.seed(42)
    n_subjects = 20
    n_features = 50

    # Create synthetic brain features (upper triangle of FC matrices)
    features = np.random.rand(n_subjects, n_features).astype("float32")

    # Create chronological ages (with some relationship to features for realistic results)
    ages = np.random.randint(20, 65, n_subjects).astype("float32")

    features_file = tmp_path / "brain_features.npy"
    ages_file = tmp_path / "chronological_ages.npy"
    output_file = tmp_path / "brain_age.tsv"

    np.save(features_file, features)
    np.save(ages_file, ages)

    # Run the tool
    result = compute_brain_age_tool(
        features_file=str(features_file),
        ages_file=str(ages_file),
        output_file=str(output_file),
    )

    # Validate results
    assert result["status"] == "success"
    assert "outputs" in result
    assert "brain_age_table" in result["outputs"]
    assert Path(result["outputs"]["brain_age_table"]).exists()

    # Check output format
    output_df = pd.read_csv(result["outputs"]["brain_age_table"], sep="\t")
    expected_cols = ["age_true", "age_pred", "age_gap"]
    assert all(col in output_df.columns for col in expected_cols)

    # Check MAE is reasonable (should be less than 20 years for this random data)
    assert "metrics" in result
    assert "mae" in result["metrics"]
    assert result["metrics"]["mae"] < 20


def test_individual_parcellation_tool(tmp_path: Path):
    """Test individualized parcellation using NMF."""
    np.random.seed(42)
    n_timepoints = 200
    n_voxels = 1000
    n_components = 10

    # Create synthetic timeseries data
    timeseries = np.random.rand(n_timepoints, n_voxels).astype("float32")

    timeseries_file = tmp_path / "timeseries.npy"
    output_file = tmp_path / "individual_parcellation.npz"

    np.save(timeseries_file, timeseries)

    # Run the tool
    result = individual_parcellation_tool(
        timeseries_file=str(timeseries_file),
        n_components=n_components,
        method="nmf",
        output_file=str(output_file),
        n_init=2,
        seed_list=[3, 7],
        reference_asset_ids=["atlas.schaefer2018.400.17networks.bundle"],
        atlas_family="precision_parcellation_reference",
        atlas_version="2026-03-09",
    )

    # Validate results
    assert result["status"] == "success"
    assert "outputs" in result
    assert "npz" in result["outputs"]
    assert "labels" in result["outputs"]
    assert "stability_report" in result["outputs"]
    assert "provenance" in result["outputs"]
    assert "provenance_json" in result["outputs"]
    assert Path(result["outputs"]["npz"]).exists()
    assert Path(result["outputs"]["labels"]).exists()
    assert Path(result["outputs"]["stability_report"]).exists()
    assert Path(result["outputs"]["provenance"]).exists()
    assert result["outputs"]["provenance_json"] == result["outputs"]["provenance"]

    # Check NPZ contents
    data = np.load(result["outputs"]["npz"])
    assert "time_factors" in data
    assert "spatial_components" in data

    # Check dimensions
    assert data["time_factors"].shape == (n_timepoints, n_components)
    assert data["spatial_components"].shape == (n_components, n_voxels)

    labels = np.load(result["outputs"]["labels"])
    assert labels.shape == (n_voxels,)

    stability = json.loads(Path(result["outputs"]["stability_report"]).read_text())
    assert "mean_pairwise_ari" in stability
    assert len(stability["pairwise_ari"]) == 1
    assert stability["input_shift_offset"] == 0.0

    provenance = json.loads(Path(result["outputs"]["provenance"]).read_text())
    assert provenance["tool"] == "individual_parcellation_tool"
    assert provenance["input"]["shape"] == [n_timepoints, n_voxels]
    assert provenance["reference_context"]["atlas_family"] == (
        "precision_parcellation_reference"
    )
    assert provenance["reference_context"]["atlas_version"] == "2026-03-09"
    assert provenance["reference_context"]["reference_asset_ids"] == [
        "atlas.schaefer2018.400.17networks.bundle"
    ]
    assert (
        provenance["artifacts"]["stability_report"]
        == result["outputs"]["stability_report"]
    )
    assert result["summary"]["reference_asset_ids"] == [
        "atlas.schaefer2018.400.17networks.bundle"
    ]


def test_individual_parcellation_tool_nmf_negative_input_is_shifted(tmp_path: Path):
    rng = np.random.default_rng(0)
    # Center around zero so negatives are present.
    timeseries = rng.normal(size=(80, 120)).astype("float32")
    timeseries_file = tmp_path / "timeseries_neg.npy"
    np.save(timeseries_file, timeseries)

    result = individual_parcellation_tool(
        timeseries_file=str(timeseries_file),
        n_components=8,
        method="nmf",
        output_file=str(tmp_path / "indiv_neg.npz"),
        n_init=2,
    )

    assert result["status"] == "success"
    assert result["summary"]["input_shift_offset"] > 0.0
    stability = json.loads(Path(result["outputs"]["stability_report"]).read_text())
    assert stability["input_shift_offset"] > 0.0


def test_individual_parcellation_tool_invalid_input_returns_error(tmp_path: Path):
    bad_timeseries = np.random.rand(20).astype("float32")  # 1D, invalid
    timeseries_file = tmp_path / "bad_timeseries.npy"
    np.save(timeseries_file, bad_timeseries)

    result = individual_parcellation_tool(
        timeseries_file=str(timeseries_file),
        n_components=5,
        method="nmf",
    )

    assert result["status"] == "error"
    assert result["error_code"] == "INVALID_INPUT"


def test_visual_feature_decoder_tool(tmp_path: Path):
    """Test visual feature decoder using ridge/logistic regression."""
    np.random.seed(42)
    n_samples = 100
    n_features = 50

    # Create synthetic brain features and visual targets
    X = np.random.rand(n_samples, n_features).astype("float32")

    # Regression case (continuous targets)
    y_continuous = np.random.rand(n_samples).astype("float32")

    features_file = tmp_path / "features.npy"
    targets_file = tmp_path / "targets.npy"
    output_dir = tmp_path / "decoder_output"

    np.save(features_file, X)
    np.save(targets_file, y_continuous)

    # Run the tool (regression mode)
    result = visual_feature_decoder_tool(
        features_file=str(features_file),
        targets_file=str(targets_file),
        output_dir=str(output_dir),
        model_type="ridge",
        cv_folds=3,
    )

    # Validate results
    assert result["status"] == "success"
    assert "outputs" in result
    assert "weights" in result["outputs"]
    assert "model_bundle" in result["outputs"]
    assert "pred" in result["outputs"]
    assert Path(result["outputs"]["weights"]).exists()
    assert Path(result["outputs"]["model_bundle"]).exists()
    assert Path(result["outputs"]["pred"]).exists()

    bundle = np.load(result["outputs"]["model_bundle"])
    assert "coef" in bundle
    assert "intercept" in bundle
    assert "scaler_mean" in bundle
    assert "scaler_scale" in bundle

    # Check metrics
    assert "metrics" in result
    assert "mse" in result["metrics"]
    assert "corr" in result["metrics"]
    assert "cv" in result["metrics"]
    assert "mse_mean" in result["metrics"]["cv"]
    assert result["metrics"]["mse"] >= 0


def test_visual_feature_decoder_tool_classification(tmp_path: Path):
    rng = np.random.default_rng(42)
    n_samples = 120
    n_features = 24

    x = rng.normal(size=(n_samples, n_features)).astype("float32")
    y = (x[:, 0] + 0.5 * x[:, 1] + 0.25 * rng.normal(size=n_samples) > 0).astype(int)

    features_file = tmp_path / "features_cls.npy"
    targets_file = tmp_path / "targets_cls.npy"
    output_dir = tmp_path / "decoder_cls_output"
    np.save(features_file, x)
    np.save(targets_file, y)

    result = visual_feature_decoder_tool(
        features_file=str(features_file),
        targets_file=str(targets_file),
        output_dir=str(output_dir),
        model_type="logistic",
        cv_folds=4,
    )

    assert result["status"] == "success"
    assert result["metrics"]["task_type"] == "classification"
    assert "accuracy" in result["metrics"]
    assert 0.0 <= result["metrics"]["accuracy"] <= 1.0
    assert "accuracy_mean" in result["metrics"]["cv"]
    assert Path(result["outputs"]["weights"]).exists()
    assert Path(result["outputs"]["model_bundle"]).exists()
    assert Path(result["outputs"]["pred"]).exists()


def test_visual_feature_decoder_tool_invalid_model_type(tmp_path: Path):
    x = np.random.rand(20, 5).astype("float32")
    y = np.random.rand(20).astype("float32")
    features_file = tmp_path / "features_invalid.npy"
    targets_file = tmp_path / "targets_invalid.npy"
    np.save(features_file, x)
    np.save(targets_file, y)

    result = visual_feature_decoder_tool(
        features_file=str(features_file),
        targets_file=str(targets_file),
        model_type="svm",
    )

    assert result["status"] == "error"
    assert result["error_code"] == "UNSUPPORTED_MODEL_TYPE"


def _install_fake_neuromaps(monkeypatch, fetch_impl):
    neuromaps_mod = types.ModuleType("neuromaps")
    neuromaps_datasets_mod = types.ModuleType("neuromaps.datasets")
    neuromaps_datasets_mod.fetch_annotation = fetch_impl
    neuromaps_mod.datasets = neuromaps_datasets_mod
    monkeypatch.setitem(sys.modules, "neuromaps", neuromaps_mod)
    monkeypatch.setitem(sys.modules, "neuromaps.datasets", neuromaps_datasets_mod)


def test_query_neuromaps_tool_sets_template_fallback_source(monkeypatch):
    import nibabel as nib
    import nilearn.datasets as nilearn_datasets

    _install_fake_neuromaps(
        monkeypatch,
        fetch_impl=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    tmpl_img = nib.Nifti1Image(np.ones((2, 2, 2), dtype=np.float32), np.eye(4))
    monkeypatch.setattr(nilearn_datasets, "load_mni152_template", lambda: tmpl_img)

    result = query_neuromaps_tool(term="working memory")

    assert result["status"] == "success"
    assert result["outputs"]["source"] == "template_fallback"
    assert result["outputs"]["fallback_reason"].startswith("fetch_annotation_error:")


def test_run_local_script_tool_resolves_repo_relative_script_when_cwd_differs(
    tmp_path: Path, monkeypatch
):
    repo_root = tmp_path / "repo"
    script_dir = repo_root / "scripts"
    script_dir.mkdir(parents=True, exist_ok=True)
    script_path = script_dir / "hello_repo.py"
    script_path.write_text("print('repo-script-ok')\n", encoding="utf-8")

    other_cwd = tmp_path / "other"
    other_cwd.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(other_cwd)
    monkeypatch.setattr(runtime_tools_module, "_repo_root", lambda: repo_root)

    result = run_local_script_tool(script="scripts/hello_repo.py")
    assert result["status"] == "success"
    assert "repo-script-ok" in result["outputs"]["stdout"]


def test_run_local_script_tool_resolves_cwd_relative_script(
    tmp_path: Path, monkeypatch
):
    script_path = tmp_path / "hello_cwd.py"
    script_path.write_text("print('cwd-script-ok')\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = run_local_script_tool(script="hello_cwd.py")
    assert result["status"] == "success"
    assert "cwd-script-ok" in result["outputs"]["stdout"]


def test_run_local_script_tool_missing_script_reports_candidates(
    tmp_path: Path, monkeypatch
):
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    cwd = tmp_path / "cwd"
    cwd.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(runtime_tools_module, "_repo_root", lambda: repo_root)

    with pytest.raises(FileNotFoundError) as exc_info:
        run_local_script_tool(script="scripts/missing.py")

    message = str(exc_info.value)
    assert "Script not found: scripts/missing.py" in message
    assert "Tried:" in message
    assert str((cwd / "scripts" / "missing.py").resolve()) in message
    assert str((repo_root / "scripts" / "missing.py").resolve()) in message


def test_query_neuromaps_tool_template_without_term_has_no_fallback_reason(monkeypatch):
    import nibabel as nib
    import nilearn.datasets as nilearn_datasets

    _install_fake_neuromaps(monkeypatch, fetch_impl=lambda **_kwargs: {})
    tmpl_img = nib.Nifti1Image(np.ones((2, 2, 2), dtype=np.float32), np.eye(4))
    monkeypatch.setattr(nilearn_datasets, "load_mni152_template", lambda: tmpl_img)

    result = query_neuromaps_tool(term=None)

    assert result["status"] == "success"
    assert result["outputs"]["source"] == "template"
    assert "fallback_reason" not in result["outputs"]


def test_query_neuromaps_tool_map1_honors_br_path_alias_map(
    monkeypatch, tmp_path: Path
):
    import nibabel as nib

    _install_fake_neuromaps(monkeypatch, fetch_impl=lambda **_kwargs: {})
    alias_src = tmp_path / "host_data"
    alias_dst = tmp_path / "container_data"
    alias_dst.mkdir(parents=True, exist_ok=True)
    mapped_img_path = alias_dst / "map.nii.gz"
    nib.save(
        nib.Nifti1Image(np.ones((2, 2, 2), dtype=np.float32), np.eye(4)),
        mapped_img_path,
    )

    monkeypatch.setenv("BR_PATH_ALIAS_MAP", f"{alias_src}={alias_dst}")
    # The source path does not exist on disk, but should resolve via alias.
    input_map_path = alias_src / "map.nii.gz"

    result = query_neuromaps_tool(map1=str(input_map_path))

    assert result["status"] == "success"
    assert result["outputs"]["source"] == "local"
    assert Path(result["outputs"]["map_path"]).resolve() == mapped_img_path.resolve()


def test_query_neuromaps_tool_map1_rewrites_openneuro_glmfitlins_layout(
    monkeypatch, tmp_path: Path
):
    import nibabel as nib

    _install_fake_neuromaps(monkeypatch, fetch_impl=lambda **_kwargs: {})
    deriv_root = tmp_path / "OpenNeuroDerivatives"
    mapped_img_path = (
        deriv_root
        / "fitlins"
        / "ds000115-fitlins"
        / "task-letter2backtask"
        / "node-dataLevel"
        / "contrast-twoback_stat-z_statmap.nii.gz"
    )
    mapped_img_path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(
        nib.Nifti1Image(np.ones((2, 2, 2), dtype=np.float32), np.eye(4)),
        mapped_img_path,
    )

    monkeypatch.setenv("OPENNEURO_DERIV_ROOT", str(deriv_root))
    input_map_path = (
        tmp_path
        / "openneuro_glmfitlins"
        / "stat_maps"
        / "ds000115"
        / "task-letter2backtask"
        / "node-dataLevel"
        / "contrast-twoback_stat-z_statmap.nii.gz"
    )

    result = query_neuromaps_tool(map1=str(input_map_path))

    assert result["status"] == "success"
    assert result["outputs"]["source"] == "local"
    assert Path(result["outputs"]["map_path"]).resolve() == mapped_img_path.resolve()
