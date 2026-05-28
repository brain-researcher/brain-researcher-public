"""Smoke tests for Grandmaster YAML-driven tools/workflows."""

from __future__ import annotations

from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from brain_researcher.services.tools.tool_base import ToolResult
from brain_researcher.services.tools.tool_registry import ToolRegistry


def test_grandmaster_tools_are_registered_in_light_mode():
    registry = ToolRegistry(light_mode=True)

    assert registry.get_tool("validate_bids_structure") is not None
    assert registry.get_tool("compute_connectivity") is not None
    assert registry.get_tool("workflow_rest_connectome_e2e") is not None


def test_workflow_rest_connectome_e2e_runs(tmp_path: Path):
    registry = ToolRegistry(light_mode=True)
    wf = registry.get_tool("workflow_rest_connectome_e2e")
    assert wf is not None

    img_path = tmp_path / "bold.nii.gz"
    out_dir = tmp_path / "out"

    rng = np.random.default_rng(0)
    data = rng.normal(size=(6, 6, 6, 12)).astype("float32")
    img = nib.Nifti1Image(data, affine=np.eye(4))
    nib.save(img, str(img_path))

    res = wf._run(
        img=str(img_path),
        atlas_name="synthetic",
        output_dir=str(out_dir),
        connectivity_kind="correlation",
    )
    assert res.status == "success"

    workflow_data = res.data or {}
    provenance = workflow_data.get("provenance") or {}
    assert provenance.get("workflow_id") == "workflow_rest_connectome_e2e"
    assert provenance.get("recipe_family") == "rest_connectome"
    assert provenance.get("primary_target") == "python"

    steps = (res.data or {}).get("steps") or {}
    atlas_outputs = (steps.get("atlas") or {}).get("data", {}).get("outputs", {})
    timeseries_outputs = (
        (steps.get("timeseries") or {}).get("data", {}).get("outputs", {})
    )
    matrix = (
        steps.get("connectivity", {}).get("data", {}).get("outputs", {}).get("matrix")
    )
    assert atlas_outputs.get("atlas_path")
    assert Path(atlas_outputs["atlas_path"]).exists()
    assert Path(atlas_outputs["labels_tsv"]).exists()
    assert Path(atlas_outputs["labels_json"]).exists()
    assert timeseries_outputs.get("timeseries")
    assert Path(timeseries_outputs["timeseries"]).exists()
    assert Path(timeseries_outputs["timeseries_csv"]).exists()
    assert Path(timeseries_outputs["summary"]).exists()
    assert matrix, "workflow did not produce connectivity matrix path"
    assert Path(matrix).exists()

    workflow_outputs = workflow_data.get("outputs") or {}
    assert Path(workflow_outputs["atlas_path"]).exists()
    assert Path(workflow_outputs["timeseries"]) == Path(
        timeseries_outputs["timeseries"]
    )
    assert Path(workflow_outputs["timeseries_csv"]) == Path(
        timeseries_outputs["timeseries_csv"]
    )
    assert Path(workflow_outputs["connectivity_matrix"]) == Path(matrix)
    assert workflow_data["summary"]["n_subjects"] == 1
    assert workflow_data["summary"]["n_rois"] >= 1


def test_workflow_ml_decoding_pipeline_runs(tmp_path: Path):
    registry = ToolRegistry(light_mode=True)
    wf = registry.get_tool("workflow_ml_decoding_pipeline")
    assert wf is not None

    out_dir = tmp_path / "out"
    data_file = tmp_path / "X.npy"
    labels_file = tmp_path / "y.npy"
    groups_file = tmp_path / "groups.npy"

    rng = np.random.default_rng(0)
    X = rng.normal(size=(30, 10)).astype("float32")
    y = rng.integers(0, 2, size=(30,), dtype="int64")
    groups = rng.integers(0, 3, size=(30,), dtype="int64")
    np.save(data_file, X)
    np.save(labels_file, y)
    np.save(groups_file, groups)

    res = wf._run(
        data_file=str(data_file),
        labels_file=str(labels_file),
        groups_file=str(groups_file),
        cv_type="group",
        n_splits=3,
        task_type="classification",
        output_dir=str(out_dir),
    )
    assert res.status == "success"

    steps = (res.data or {}).get("steps") or {}
    summary = steps.get("cv", {}).get("data", {}).get("outputs", {}).get("summary")
    assert summary
    assert Path(summary).exists()


def test_toolspec_execute_exposed_workflow_ml(tmp_path: Path):
    from brain_researcher.services.tools.executor import execute_tool

    out_dir = tmp_path / "out"
    data_file = tmp_path / "X.npy"
    labels_file = tmp_path / "y.npy"
    groups_file = tmp_path / "groups.npy"

    rng = np.random.default_rng(0)
    X = rng.normal(size=(20, 5)).astype("float32")
    y = rng.integers(0, 2, size=(20,), dtype="int64")
    groups = rng.integers(0, 4, size=(20,), dtype="int64")
    np.save(data_file, X)
    np.save(labels_file, y)
    np.save(groups_file, groups)

    res = execute_tool(
        "workflow_ml_decoding_pipeline",
        {
            "data_file": str(data_file),
            "labels_file": str(labels_file),
            "groups_file": str(groups_file),
            "cv_type": "group",
            "n_splits": 4,
            "task_type": "classification",
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success"


def test_workflow_network_based_statistics_runs(tmp_path: Path):
    """NBS workflow should be wired to the real nbs_engine implementation."""
    pytest.importorskip("scipy")

    registry = ToolRegistry(light_mode=True)
    wf = registry.get_tool("workflow_network_based_statistics")
    assert wf is not None

    out_dir = tmp_path / "out"
    ts_file = tmp_path / "ts.npy"
    labels_file = tmp_path / "labels.npy"

    rng = np.random.default_rng(0)
    ts = rng.normal(size=(2, 20, 6)).astype("float32")  # subjects, timepoints, rois
    np.save(ts_file, ts)
    np.save(labels_file, np.asarray([0, 1], dtype="int64"))

    res = wf._run(
        timeseries=str(ts_file),
        connectivity_kind="correlation",
        labels=str(labels_file),
        threshold=1.0,
        n_permutations=5,
        output_dir=str(out_dir),
    )
    assert res.status == "success", res.error

    workflow_data = res.data or {}
    provenance = workflow_data.get("provenance") or {}
    assert provenance.get("workflow_id") == "workflow_network_based_statistics"
    assert provenance.get("stage") == "connectivity"

    steps = workflow_data.get("steps") or {}
    connectivity_outputs = (
        (steps.get("connectivity") or {}).get("data", {}).get("outputs", {})
    )
    stats_payload = (steps.get("similarity") or {}).get("data") or {}
    assert Path(connectivity_outputs["matrix"]).exists()

    outputs = workflow_data.get("outputs") or {}
    tmap_file = outputs.get("tmap_file")
    assert tmap_file, "missing tmap_file output"
    assert Path(tmap_file).exists()
    assert Path(stats_payload["tmap_file"]) == Path(tmap_file)
    assert Path(outputs["supra_mask_file"]).exists()
    assert Path(outputs["components_file"]).exists()


def test_workflow_group_ica_runs(tmp_path: Path):
    registry = ToolRegistry(light_mode=True)
    wf = registry.get_tool("workflow_group_ica")
    assert wf is not None

    out_dir = tmp_path / "group_ica"
    mask_path = tmp_path / "mask.nii.gz"
    nib.save(
        nib.Nifti1Image(np.ones((6, 6, 6), dtype="uint8"), affine=np.eye(4)),
        str(mask_path),
    )

    rng = np.random.default_rng(0)
    imgs = []
    for idx in range(2):
        img_path = tmp_path / f"sub-{idx + 1:02d}_bold.nii.gz"
        data = np.zeros((6, 6, 6, 20), dtype="float32")
        data[1:5, 1:5, 1:5, :] = (
            rng.normal(size=(4, 4, 4, 20)).astype("float32") + 10.0 + idx
        )
        nib.save(nib.Nifti1Image(data, affine=np.eye(4)), str(img_path))
        imgs.append(str(img_path))

    res = wf._run(
        img=imgs,
        labels=[0, 1],
        n_components=3,
        threshold=0.5,
        n_permutations=5,
        output_dir=str(out_dir),
        mask=str(mask_path),
    )
    assert res.status == "success", res.error

    outputs = (res.data or {}).get("outputs") or {}
    assert Path(outputs["ica_dir"]).exists()
    assert Path(outputs["components_file"]).exists()
    assert Path(outputs["timecourses_file"]).exists()
    assert Path(outputs["connectivity_matrix"]).exists()
    assert Path(outputs["nbs_tmap"]).exists()
    assert Path(outputs["nbs_supra_mask"]).exists()
    assert Path(outputs["nbs_components"]).exists()


def test_workflow_task_glm_group_runs(tmp_path: Path):
    """Task GLM group workflow should support multi-subject inputs."""
    registry = ToolRegistry(light_mode=True)
    wf = registry.get_tool("workflow_task_glm_group")
    assert wf is not None

    out_dir = tmp_path / "out"
    img1_path = tmp_path / "sub-01_bold.nii.gz"
    img2_path = tmp_path / "sub-02_bold.nii.gz"
    mask_path = tmp_path / "mask.nii.gz"
    events1_path = tmp_path / "sub-01_events.tsv"
    events2_path = tmp_path / "sub-02_events.tsv"

    rng = np.random.default_rng(0)
    data1 = np.zeros((6, 6, 6, 20), dtype="float32")
    data2 = np.zeros((6, 6, 6, 20), dtype="float32")
    data1[1:5, 1:5, 1:5, :] = rng.normal(size=(4, 4, 4, 20)).astype("float32") + 10.0
    data2[1:5, 1:5, 1:5, :] = rng.normal(size=(4, 4, 4, 20)).astype("float32") + 10.0
    nib.save(nib.Nifti1Image(data1, affine=np.eye(4)), str(img1_path))
    nib.save(nib.Nifti1Image(data2, affine=np.eye(4)), str(img2_path))
    nib.save(
        nib.Nifti1Image(np.ones((6, 6, 6), dtype="uint8"), affine=np.eye(4)),
        str(mask_path),
    )

    events_tsv = "onset\tduration\ttrial_type\n0\t5\tstim\n10\t5\tstim\n"
    events1_path.write_text(events_tsv, encoding="utf-8")
    events2_path.write_text(events_tsv, encoding="utf-8")

    res = wf._run(
        img=[str(img1_path), str(img2_path)],
        events=[str(events1_path), str(events2_path)],
        t_r=2.0,
        mask_img=str(mask_path),
        contrast_name="stim",
        output_dir=str(out_dir),
    )
    assert res.status == "success", res.error

    workflow_outputs = (res.data or {}).get("outputs") or {}
    assert workflow_outputs.get("route") == "direct_inputs"
    assert len(workflow_outputs.get("first_level_dirs") or []) == 2
    assert len(workflow_outputs.get("selected_zmaps") or []) == 2
    assert workflow_outputs.get("resolved_inputs_manifest")
    assert Path(workflow_outputs["resolved_inputs_manifest"]).exists()
    assert Path(workflow_outputs["group_zmap"]).exists()

    steps = (res.data or {}).get("steps") or {}
    selected = (
        steps.get("first_level", {})
        .get("data", {})
        .get("outputs", {})
        .get("selected_zmaps")
    )
    assert isinstance(selected, list)
    assert len(selected) == 2
    assert all(Path(p).exists() for p in selected)

    zmap = steps.get("second_level", {}).get("data", {}).get("outputs", {}).get("zmap")
    assert zmap, "workflow did not produce group zmap path"
    assert Path(zmap).exists()


def test_workflow_fitlins_direct_preview_contract(tmp_path: Path):
    registry = ToolRegistry(light_mode=True)
    wf = registry.get_tool("workflow_fitlins_direct")
    assert wf is not None

    bids_root = tmp_path / "bids"
    fmriprep_root = tmp_path / "derivatives" / "fmriprep"
    out_dir = tmp_path / "fitlins_out"
    model_path = tmp_path / "model.json"
    bids_root.mkdir(parents=True, exist_ok=True)
    fmriprep_root.mkdir(parents=True, exist_ok=True)
    model_path.write_text('{"Name": "demo"}', encoding="utf-8")

    res = wf._run(
        bids_dir=str(bids_root),
        fmriprep_dir=str(fmriprep_root),
        model=str(model_path),
        output_dir=str(out_dir),
        dry_run=True,
    )
    assert res.status == "success", res.error

    outputs = (res.data or {}).get("outputs") or {}
    assert outputs.get("dry_run") is True
    assert outputs.get("preview_only") is True
    assert outputs.get("runtime") == "apptainer"
    assert outputs.get("fitlins_dir", "").endswith("/fitlins")
    command = outputs.get("command")
    assert command
    command_str = " ".join(command) if isinstance(command, list) else str(command)
    assert "--model" in command_str
    assert str(model_path) in command_str


def _write_task_glm_subject(
    *,
    bids_root: Path,
    fmriprep_root: Path,
    subject: str,
    task: str,
    session: str,
) -> tuple[Path, Path]:
    subject_bids = bids_root / subject / f"ses-{session}" / "func"
    subject_deriv = fmriprep_root / subject / f"ses-{session}" / "func"
    subject_bids.mkdir(parents=True, exist_ok=True)
    subject_deriv.mkdir(parents=True, exist_ok=True)

    img_path = (
        subject_deriv
        / f"{subject}_ses-{session}_task-{task}_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz"
    )
    events_path = subject_bids / f"{subject}_ses-{session}_task-{task}_events.tsv"

    seed = 1 if subject.endswith("01") else 2
    rng = np.random.default_rng(seed)
    data = np.zeros((6, 6, 6, 20), dtype="float32")
    data[1:5, 1:5, 1:5, :] = rng.normal(size=(4, 4, 4, 20)).astype("float32") + 10.0
    img = nib.Nifti1Image(data, affine=np.eye(4))
    img.header.set_zooms((1.0, 1.0, 1.0, 2.0))
    nib.save(img, str(img_path))
    events_path.write_text(
        "onset\tduration\ttrial_type\n0\t5\tstim\n10\t5\tstim\n",
        encoding="utf-8",
    )
    return img_path, events_path


def test_workflow_task_glm_group_preview_from_bids_fmriprep_contract(tmp_path: Path):
    registry = ToolRegistry(light_mode=True)
    wf = registry.get_tool("workflow_task_glm_group")
    assert wf is not None

    bids_root = tmp_path / "bids"
    fmriprep_root = tmp_path / "derivatives" / "fmriprep"
    _write_task_glm_subject(
        bids_root=bids_root,
        fmriprep_root=fmriprep_root,
        subject="sub-01",
        task="linebisection",
        session="test",
    )
    _write_task_glm_subject(
        bids_root=bids_root,
        fmriprep_root=fmriprep_root,
        subject="sub-02",
        task="linebisection",
        session="test",
    )

    out_dir = tmp_path / "preview_out"
    res = wf._run(
        bids_dir=str(bids_root),
        fmriprep_dir=str(fmriprep_root),
        task="linebisection",
        participant_label=["01", "02"],
        output_dir=str(out_dir),
        dry_run=True,
    )
    assert res.status == "success", res.error

    outputs = (res.data or {}).get("outputs") or {}
    assert outputs.get("preview_only") is True
    first_level = outputs.get("first_level") or {}
    first_level_outputs = first_level.get("outputs") or {}
    assert first_level_outputs.get("route") == "bids_fmriprep_derivatives"
    assert len(first_level_outputs.get("first_level_dirs") or []) == 2
    manifest = first_level_outputs.get("resolved_inputs_manifest")
    assert manifest
    assert Path(manifest).exists()
    planned = outputs.get("planned_second_level") or {}
    assert planned.get("contrast") == "intercept"
    assert planned.get("output_dir", "").endswith("second_level")


def test_workflow_task_glm_group_runs_from_bids_fmriprep_contract(tmp_path: Path):
    registry = ToolRegistry(light_mode=True)
    wf = registry.get_tool("workflow_task_glm_group")
    assert wf is not None

    bids_root = tmp_path / "bids"
    fmriprep_root = tmp_path / "derivatives" / "fmriprep"
    _write_task_glm_subject(
        bids_root=bids_root,
        fmriprep_root=fmriprep_root,
        subject="sub-01",
        task="linebisection",
        session="test",
    )
    _write_task_glm_subject(
        bids_root=bids_root,
        fmriprep_root=fmriprep_root,
        subject="sub-02",
        task="linebisection",
        session="test",
    )

    out_dir = tmp_path / "stable_out"
    mask_path = tmp_path / "stable_mask.nii.gz"
    nib.save(
        nib.Nifti1Image(np.ones((6, 6, 6), dtype="uint8"), affine=np.eye(4)),
        str(mask_path),
    )
    res = wf._run(
        bids_dir=str(bids_root),
        fmriprep_dir=str(fmriprep_root),
        task="linebisection",
        participant_label=["01", "02"],
        mask_img=str(mask_path),
        output_dir=str(out_dir),
    )
    assert res.status == "success", res.error

    workflow_outputs = (res.data or {}).get("outputs") or {}
    assert workflow_outputs.get("route") == "bids_fmriprep_derivatives"
    manifest = workflow_outputs.get("resolved_inputs_manifest")
    assert manifest
    assert Path(manifest).exists()
    assert Path(workflow_outputs["group_zmap"]).exists()
    steps = (res.data or {}).get("steps") or {}
    selected = (
        steps.get("first_level", {})
        .get("data", {})
        .get("outputs", {})
        .get("selected_zmaps")
    )
    assert isinstance(selected, list)
    assert len(selected) == 2
    assert all(Path(path).exists() for path in selected)


def test_workflow_precision_parcellation_runs(tmp_path: Path):
    registry = ToolRegistry(light_mode=True)
    wf = registry.get_tool("workflow_precision_parcellation")
    assert wf is not None

    out_dir = tmp_path / "out"
    timeseries_file = tmp_path / "timeseries.npy"

    rng = np.random.default_rng(0)
    timeseries = rng.normal(size=(60, 24)).astype("float32")
    np.save(timeseries_file, timeseries)

    res = wf._run(
        timeseries=str(timeseries_file),
        n_components=6,
        output_dir=str(out_dir),
    )
    assert res.status == "success", res.error

    workflow_outputs = (res.data or {}).get("outputs", {}).get("outputs", {})
    assert Path(workflow_outputs["npz"]).exists()
    assert Path(workflow_outputs["labels"]).exists()
    assert Path(workflow_outputs["stability_report"]).exists()
    assert Path(workflow_outputs["provenance"]).exists()
    assert Path(workflow_outputs["provenance_json"]).exists()
    assert (res.data or {}).get("outputs", {}).get("summary", {}).get(
        "atlas_family"
    ) == ("precision_parcellation_reference")
    assert (res.data or {}).get("outputs", {}).get("summary", {}).get(
        "reference_asset_ids"
    ) == [
        "nilearn.atlas.schaefer2018.400.17networks",
        "nilearn.atlas.yeo2011.17networks.volume",
    ]

    labels = np.load(workflow_outputs["labels"])
    assert labels.ndim == 1

    workflow_provenance = (res.data or {}).get("provenance") or {}
    assert workflow_provenance.get("stable_workflow_pack") is True
    assert workflow_provenance.get("recipe_family") == "precision_parcellation"
    assert workflow_provenance.get("reference_assets") == [
        "nilearn.atlas.schaefer2018.400.17networks",
        "nilearn.atlas.yeo2011.17networks.volume",
    ]


def test_run_bids_app_dry_run_preview_fmriprep(tmp_path: Path):
    registry = ToolRegistry(light_mode=True)
    tool = registry.get_tool("run_bids_app")
    assert tool is not None

    bids_dir = tmp_path / "bids"
    out_dir = tmp_path / "out"
    bids_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    res = tool._run(
        app="fmriprep",
        bids_dir=str(bids_dir),
        output_dir=str(out_dir),
        extra_args=["--skip-bids-validation"],
        dry_run=True,
    )
    assert res.status == "success", res.error
    payload = res.data or {}
    assert payload.get("dry_run") is True
    cmd = payload.get("command")
    assert isinstance(cmd, list)
    assert cmd[1] == str(bids_dir)
    assert cmd[2] == str(out_dir)


def test_run_bids_app_dry_run_preview_smriprep(tmp_path: Path):
    registry = ToolRegistry(light_mode=True)
    tool = registry.get_tool("run_bids_app")
    assert tool is not None

    bids_dir = tmp_path / "bids"
    out_dir = tmp_path / "out"
    bids_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    res = tool._run(
        app="smriprep",
        bids_dir=str(bids_dir),
        output_dir=str(out_dir),
        extra_args=["--skip-bids-validation"],
        dry_run=True,
    )
    assert res.status == "success", res.error
    payload = res.data or {}
    assert payload.get("dry_run") is True
    cmd = payload.get("command")
    assert isinstance(cmd, list)
    assert cmd[1] == str(bids_dir)
    assert cmd[2] == str(out_dir)


def test_workflow_fmriprep_preprocessing_preview(tmp_path: Path):
    registry = ToolRegistry(light_mode=True)
    tool = registry.get_tool("workflow_fmriprep_preprocessing")
    assert tool is not None

    bids_dir = tmp_path / "bids"
    out_dir = tmp_path / "out"
    bids_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    res = tool._run(
        bids_dir=str(bids_dir),
        output_dir=str(out_dir),
        dry_run=True,
        extra_args=["--skip-bids-validation"],
    )
    assert res.status == "success", res.error
    outputs = (res.data or {}).get("outputs") or {}
    assert outputs.get("app") == "fmriprep"
    assert isinstance(outputs.get("command"), list)


def test_workflow_fmriprep_preprocessing_execute(monkeypatch, tmp_path: Path):
    def _fake_run_subprocess(cmd, env=None, cwd=None):
        output_dir = Path(cmd[2])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "dataset_description.json").write_text("{}", encoding="utf-8")
        return type("Proc", (), {"stdout": "", "stderr": ""})()

    monkeypatch.setattr(
        "brain_researcher.services.tools.pipeline_tools.run_subprocess",
        _fake_run_subprocess,
    )

    registry = ToolRegistry(light_mode=True)
    tool = registry.get_tool("workflow_fmriprep_preprocessing")
    assert tool is not None

    bids_dir = tmp_path / "bids"
    out_dir = tmp_path / "out"
    work_dir = tmp_path / "work"
    license_file = tmp_path / "license.txt"
    bids_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    license_file.write_text("license", encoding="utf-8")

    res = tool._run(
        bids_dir=str(bids_dir),
        output_dir=str(out_dir),
        participant_label=["01"],
        work_dir=str(work_dir),
        fs_license_file=str(license_file),
        output_spaces=["MNI152NLin2009cAsym"],
        dry_run=False,
    )
    assert res.status == "success", res.error
    outputs = (res.data or {}).get("outputs") or {}
    assert outputs.get("summary", {}).get("backend") == "wrapper_executable"
    assert Path(outputs["outputs"]["dataset_description"]).exists()


def test_workflow_mriqc_execute(monkeypatch, tmp_path: Path):
    def _fake_run_subprocess(cmd, env=None, cwd=None):
        output_dir = Path(cmd[2])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "group_bold.html").write_text("<html />", encoding="utf-8")
        return type("Proc", (), {"stdout": "", "stderr": ""})()

    monkeypatch.setattr(
        "brain_researcher.services.tools.pipeline_tools.run_subprocess",
        _fake_run_subprocess,
    )

    registry = ToolRegistry(light_mode=True)
    tool = registry.get_tool("workflow_mriqc")
    assert tool is not None

    bids_dir = tmp_path / "bids"
    out_dir = tmp_path / "out"
    bids_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    res = tool._run(
        bids_dir=str(bids_dir),
        output_dir=str(out_dir),
        participant_label=["01"],
        modalities=["bold"],
        dry_run=False,
    )
    assert res.status == "success", res.error
    outputs = (res.data or {}).get("outputs") or {}
    assert outputs.get("summary", {}).get("backend") == "wrapper_executable"
    assert outputs["outputs"]["group_reports"] == [
        str(out_dir / "mriqc" / "group_bold.html")
    ]


def test_workflow_preprocessing_qc_preview_short_circuits_without_qc_source(
    monkeypatch, tmp_path: Path
):
    registry = ToolRegistry(light_mode=True)
    tool = registry.get_tool("workflow_preprocessing_qc")
    validate = registry.get_tool("validate_bids_structure")
    get_qc_table = registry.get_tool("get_qc_table")
    assert tool is not None
    assert validate is not None
    assert get_qc_table is not None

    monkeypatch.setattr(
        validate,
        "_run",
        lambda **kwargs: ToolResult(
            status="success",
            data={"bids_dir": kwargs.get("bids_dir"), "validated": True},
        ),
    )

    def _unexpected_qc_table(**kwargs):
        raise AssertionError("get_qc_table should not run in preview-only mode")

    monkeypatch.setattr(get_qc_table, "_run", _unexpected_qc_table)

    bids_dir = tmp_path / "bids"
    out_dir = tmp_path / "out"
    bids_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    res = tool._run(
        bids_dir=str(bids_dir),
        output_dir=str(out_dir),
        dry_run=True,
    )
    assert res.status == "success", res.error
    outputs = (res.data or {}).get("outputs") or {}
    assert outputs.get("dry_run") is True
    assert outputs.get("preview_only") is True
    assert isinstance((outputs.get("fmriprep") or {}).get("command"), list)
    assert isinstance((outputs.get("mriqc") or {}).get("command"), list)
    assert not (out_dir / "qc").exists()


def test_workflow_preprocessing_qc_execute(monkeypatch, tmp_path: Path):
    def _fake_run_subprocess(cmd, env=None, cwd=None):
        output_dir = Path(cmd[2])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "dataset_description.json").write_text("{}", encoding="utf-8")
        if output_dir.name == "mriqc":
            (output_dir / "group_bold.tsv").write_text(
                "bids_name\tfd_mean\n"
                "sub-01_task-rest_bold\t0.10\n"
                "sub-02_task-rest_bold\t1.50\n",
                encoding="utf-8",
            )
        return type("Proc", (), {"stdout": "", "stderr": ""})()

    monkeypatch.setattr(
        "brain_researcher.services.tools.pipeline_tools.run_subprocess",
        _fake_run_subprocess,
    )

    registry = ToolRegistry(light_mode=True)
    tool = registry.get_tool("workflow_preprocessing_qc")
    validate = registry.get_tool("validate_bids_structure")
    assert tool is not None
    assert validate is not None

    monkeypatch.setattr(
        validate,
        "_run",
        lambda **kwargs: ToolResult(
            status="success",
            data={"bids_dir": kwargs.get("bids_dir"), "validated": True},
        ),
    )

    bids_dir = tmp_path / "bids"
    out_dir = tmp_path / "out"
    work_dir = tmp_path / "work"
    license_file = tmp_path / "license.txt"
    bids_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    license_file.write_text("license", encoding="utf-8")

    res = tool._run(
        bids_dir=str(bids_dir),
        output_dir=str(out_dir),
        participant_label=["01"],
        work_dir=str(work_dir),
        fs_license_file=str(license_file),
        outlier_metric="fd_mean",
        outlier_z=1.0,
        dry_run=False,
    )
    assert res.status == "success", res.error
    steps = (res.data or {}).get("steps") or {}
    assert (
        steps.get("fmriprep", {}).get("data", {}).get("summary", {}).get("backend")
        == "wrapper_executable"
    )
    assert (
        steps.get("mriqc", {}).get("data", {}).get("summary", {}).get("backend")
        == "wrapper_executable"
    )
    outputs = (res.data or {}).get("outputs") or {}
    assert Path(outputs["outputs"]["dashboard"]).exists()
    assert Path(outputs["outputs"]["dashboard"]).name == "index.html"
    assert Path(outputs["outputs"]["dashboard"]).parent == out_dir / "qc"
    assert (out_dir / "qc" / "qc_table.csv").exists()
    assert (out_dir / "qc" / "qc_outliers.csv").exists()
    assert (out_dir / "qc" / "qc_summary.json").exists()


def test_workflow_qsiprep_preview(tmp_path: Path):
    registry = ToolRegistry(light_mode=True)
    tool = registry.get_tool("workflow_qsiprep")
    assert tool is not None

    bids_dir = tmp_path / "bids"
    out_dir = tmp_path / "out"
    bids_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    res = tool._run(
        bids_dir=str(bids_dir),
        output_dir=str(out_dir),
        participant_label=["01"],
        dry_run=True,
        extra_args=["--skip-bids-validation"],
    )
    assert res.status == "success", res.error
    outputs = (res.data or {}).get("outputs") or {}
    assert outputs.get("app") == "qsiprep"
    assert isinstance(outputs.get("command"), list)


def test_workflow_qsiprep_execute(monkeypatch, tmp_path: Path):
    def _fake_run_subprocess(cmd, env=None, cwd=None):
        output_dir = Path(cmd[2])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "dataset_description.json").write_text("{}", encoding="utf-8")
        return type("Proc", (), {"stdout": "", "stderr": ""})()

    monkeypatch.setattr(
        "brain_researcher.services.tools.pipeline_tools.run_subprocess",
        _fake_run_subprocess,
    )

    registry = ToolRegistry(light_mode=True)
    tool = registry.get_tool("workflow_qsiprep")
    assert tool is not None

    bids_dir = tmp_path / "bids"
    out_dir = tmp_path / "out"
    work_dir = tmp_path / "work"
    license_file = tmp_path / "license.txt"
    bids_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    license_file.write_text("license", encoding="utf-8")

    res = tool._run(
        bids_dir=str(bids_dir),
        output_dir=str(out_dir),
        participant_label=["01"],
        work_dir=str(work_dir),
        fs_license_file=str(license_file),
        n_cpus=4,
        omp_nthreads=2,
        mem_mb=16000,
        dry_run=False,
        extra_args=["--skip-bids-validation"],
    )
    assert res.status == "success", res.error
    outputs = (res.data or {}).get("outputs") or {}
    assert outputs.get("summary", {}).get("backend") == "wrapper_executable"
    assert Path(outputs["outputs"]["dataset_description"]).exists()


def test_workflow_smriprep_execute(monkeypatch, tmp_path: Path):
    def _fake_run_subprocess(cmd, env=None, cwd=None):
        output_dir = Path(cmd[2])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "dataset_description.json").write_text("{}", encoding="utf-8")
        return type("Proc", (), {"stdout": "", "stderr": ""})()

    monkeypatch.setattr(
        "brain_researcher.services.tools.pipeline_tools.run_subprocess",
        _fake_run_subprocess,
    )

    registry = ToolRegistry(light_mode=True)
    tool = registry.get_tool("workflow_smriprep")
    assert tool is not None

    bids_dir = tmp_path / "bids"
    out_dir = tmp_path / "out"
    work_dir = tmp_path / "work"
    license_file = tmp_path / "license.txt"
    bids_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    license_file.write_text("license", encoding="utf-8")

    res = tool._run(
        bids_dir=str(bids_dir),
        output_dir=str(out_dir),
        participant_label=["01"],
        work_dir=str(work_dir),
        fs_license_file=str(license_file),
        dry_run=False,
        extra_args=["--skip-bids-validation"],
    )
    assert res.status == "success", res.error
    outputs = (res.data or {}).get("outputs") or {}
    assert outputs.get("summary", {}).get("backend") == "wrapper_executable"
    assert Path(outputs["outputs"]["dataset_description"]).exists()


def test_workflow_qsirecon_command_generation(tmp_path: Path):
    registry = ToolRegistry(light_mode=True)
    tool = registry.get_tool("workflow_qsirecon")
    assert tool is not None

    qsiprep_dir = tmp_path / "qsiprep"
    qsiprep_dir.mkdir(parents=True, exist_ok=True)
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    res = tool._run(
        qsiprep_dir=str(qsiprep_dir),
        output_dir=str(out_dir),
        recon_spec="mrtrix_multishell_msmt_ACT-hsvs",
    )
    assert res.status == "success", res.error
    outputs = (res.data or {}).get("outputs") or {}
    command = outputs.get("command")
    assert isinstance(command, list)
    assert "--recon-spec" in command


def test_workflow_qsirecon_execute(monkeypatch, tmp_path: Path):
    def _fake_run_subprocess(cmd, env=None, cwd=None):
        output_dir = Path(cmd[2])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "dataset_description.json").write_text("{}", encoding="utf-8")
        (output_dir / "sub-01_connectivity.tsv").write_text(
            "edge\tweight\n", encoding="utf-8"
        )
        return type("Proc", (), {"stdout": "", "stderr": ""})()

    monkeypatch.setenv("BR_QSIRECON_EXECUTE", "1")
    monkeypatch.setattr(
        "brain_researcher.services.tools.qsiprep_tool.run_subprocess",
        _fake_run_subprocess,
    )

    registry = ToolRegistry(light_mode=True)
    tool = registry.get_tool("workflow_qsirecon")
    assert tool is not None

    qsiprep_dir = tmp_path / "qsiprep"
    out_dir = tmp_path / "out"
    qsiprep_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    res = tool._run(
        qsiprep_dir=str(qsiprep_dir),
        output_dir=str(out_dir),
        recon_spec="mrtrix_multishell_msmt_ACT-hsvs",
        participant_label=["01"],
    )
    assert res.status == "success", res.error
    outputs = (res.data or {}).get("outputs") or {}
    assert outputs.get("summary", {}).get("backend") == "wrapper_executable"
    assert outputs["outputs"]["qsirecon_dir"] == str(out_dir / "qsirecon")


def test_workflow_fastsurfer_execute_backend(monkeypatch, tmp_path: Path):
    def _fake_run_container(request):
        subject_dir = Path(request.mounts[1].host_path) / "sub-01"
        (subject_dir / "surf").mkdir(parents=True, exist_ok=True)
        (subject_dir / "mri").mkdir(parents=True, exist_ok=True)
        (subject_dir / "mri" / "aparc.DKTatlas+aseg.deep.mgz").write_bytes(b"")
        (subject_dir / "mri" / "aseg.auto_noCCseg.mgz").write_bytes(b"")
        return {
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "mode": "local",
            "command": request.command,
        }

    monkeypatch.setattr(
        "brain_researcher.services.tools.pipeline_tools.run_container",
        _fake_run_container,
    )

    registry = ToolRegistry(light_mode=True)
    tool = registry.get_tool("workflow_fastsurfer")
    assert tool is not None

    t1w = tmp_path / "sub-01_T1w.nii.gz"
    license_file = tmp_path / "license.txt"
    t1w.write_bytes(b"stub")
    license_file.write_text("license", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    res = tool._run(
        t1w_image=str(t1w),
        subject_id="sub-01",
        output_dir=str(out_dir),
        fs_license_file=str(license_file),
        dry_run=False,
    )
    assert res.status == "success", res.error
    outputs = (res.data or {}).get("outputs") or {}
    assert outputs.get("summary", {}).get("backend") == "fastsurfer_container"
    recon_outputs = outputs.get("outputs") or {}
    assert Path(recon_outputs["surfaces_dir"]).exists()


def test_workflow_dwi_connectome_qsiprep_preview(tmp_path: Path):
    registry = ToolRegistry(light_mode=True)
    tool = registry.get_tool("workflow_dwi_connectome")
    assert tool is not None

    qsiprep_dir = tmp_path / "qsiprep"
    qsiprep_dir.mkdir(parents=True, exist_ok=True)
    out_dir = tmp_path / "out"

    res = tool._run(
        qsiprep_dir=str(qsiprep_dir),
        output_dir=str(out_dir),
        dry_run=True,
    )
    assert res.status == "success", res.error
    outputs = (res.data or {}).get("outputs") or {}
    assert outputs.get("preview_only") is True
    assert outputs.get("route") == "qsiprep_to_qsirecon_preview"
    qsirecon = outputs.get("qsirecon") or {}
    command = qsirecon.get("command")
    assert isinstance(command, list)
    assert "--recon-spec" in command


def test_workflow_dwi_connectome_executes_from_qsirecon_dir(tmp_path: Path):
    registry = ToolRegistry(light_mode=True)
    tool = registry.get_tool("workflow_dwi_connectome")
    assert tool is not None

    atlas = tmp_path / "atlas.nii.gz"
    atlas_img = nib.Nifti1Image(
        np.array([[[1, 2], [3, 4]], [[1, 2], [3, 4]]], dtype=np.int16),
        affine=np.eye(4),
    )
    nib.save(atlas_img, str(atlas))

    qsirecon_dir = tmp_path / "qsirecon"
    qsirecon_dir.mkdir(parents=True, exist_ok=True)
    tractogram = qsirecon_dir / "sub-01_desc-tracks.tck"
    tractogram.write_bytes(b"synthetic-tractogram")

    res = tool._run(
        qsirecon_dir=str(qsirecon_dir),
        atlas=str(atlas),
        output_dir=str(tmp_path / "dwi_connectome"),
        dry_run=False,
    )
    assert res.status == "success", res.error
    outputs = (res.data or {}).get("outputs") or {}
    summary = outputs.get("summary") or {}
    assert summary.get("route") == "qsirecon_derivatives"
    assert summary.get("used_derivatives") is True
    connectome_outputs = outputs.get("outputs") or {}
    assert Path(connectome_outputs["connectivity_matrix"]).exists()
    assert Path(connectome_outputs["connectivity_matrix_npy"]).exists()
    assert Path(connectome_outputs["feature_contract"]).exists()
    assert connectome_outputs["qsirecon_dir"] == str(qsirecon_dir)
    assert connectome_outputs["tractogram"] == str(tractogram)


def test_workflow_dwi_connectome_raw_preview_only(tmp_path: Path):
    registry = ToolRegistry(light_mode=True)
    tool = registry.get_tool("workflow_dwi_connectome")
    assert tool is not None

    dwi = tmp_path / "dwi.npy"
    np.save(dwi, np.random.default_rng(0).normal(size=(4, 4, 4, 8)).astype(np.float32))
    bval = tmp_path / "dwi.bval"
    bval.write_text("0 1000 1000 1000\n", encoding="utf-8")
    bvec = tmp_path / "dwi.bvec"
    bvec.write_text("1 0 0 0\n0 1 0 0\n0 0 1 0\n", encoding="utf-8")
    atlas = tmp_path / "atlas.nii.gz"
    nib.save(
        nib.Nifti1Image(np.ones((4, 4, 4), dtype=np.int16), affine=np.eye(4)),
        str(atlas),
    )

    res = tool._run(
        dwi=str(dwi),
        bvals=str(bval),
        bvecs=str(bvec),
        atlas=str(atlas),
        output_dir=str(tmp_path / "raw_preview"),
        dry_run=True,
    )
    assert res.status == "success", res.error
    outputs = (res.data or {}).get("outputs") or {}
    assert outputs.get("preview_only") is True
    assert outputs.get("route") == "raw_fallback_preview"


def test_run_tractography_resolves_qsiprep_derivatives(tmp_path: Path):
    registry = ToolRegistry(light_mode=True)
    tool = registry.get_tool("run_tractography")
    assert tool is not None

    qsiprep_dir = tmp_path / "qsiprep" / "sub-01" / "dwi"
    qsiprep_dir.mkdir(parents=True, exist_ok=True)
    dwi = qsiprep_dir / "sub-01_desc-preproc_dwi.nii.gz"
    dwi.write_bytes(b"synthetic-dwi")
    bval = qsiprep_dir / "sub-01_desc-preproc_dwi.bval"
    bval.write_text("0 1000 1000 1000\n", encoding="utf-8")
    bvec = qsiprep_dir / "sub-01_desc-preproc_dwi.bvec"
    bvec.write_text("1 0 0 0\n0 1 0 0\n0 0 1 0\n", encoding="utf-8")

    out_dir = tmp_path / "tracts"
    res = tool._run(
        qsiprep_dir=str(tmp_path / "qsiprep"),
        participant_label=["01"],
        output_dir=str(out_dir),
    )
    assert res.status == "success", res.error
    payload = res.data or {}
    outputs = payload.get("outputs") or {}
    summary = payload.get("summary") or {}
    assert Path(outputs["streamlines"]).exists()
    assert Path(outputs["provenance_json"]).exists()
    assert summary.get("input_mode") == "qsiprep_derivatives"
    assert summary.get("resolved_from_qsiprep") is True
