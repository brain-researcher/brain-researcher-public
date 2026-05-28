import json
from pathlib import Path

import pandas as pd
import pytest

from brain_researcher.services.tools.fitlins_tool import (
    FitLinsTool,
    _find_convolve_idx,
    _find_run_node,
)
from brain_researcher.services.tools.pipelines.helpers import (
    _prepare_fitlins_effective_model,
    _prepare_fitlins_external_confounds,
)
from brain_researcher.services.tools.pipelines.params import FitLinsParameters


def _write_model(path: Path) -> Path:
    model = {
        "Name": "test-model",
        "BIDSModelVersion": "1.0.0",
        "Input": {"task": ["rest"]},
        "Nodes": [
            {
                "Level": "Run",
                "Name": "run_level",
                "GroupBy": ["run", "subject"],
                "Transformations": {
                    "Transformer": "pybids-transforms-v1",
                    "Instructions": [
                        {"Name": "Factor", "Input": ["trial_type"]},
                        {
                            "Name": "Convolve",
                            "Input": ["trial_type.*"],
                            "Model": "glover",
                            "Derivative": False,
                            "Dispersion": False,
                        },
                    ],
                },
                "Model": {"Type": "glm", "X": [1, "trial_type.*", "trans_*", "rot_*"]},
                "Contrasts": [],
            }
        ],
    }
    path.write_text(json.dumps(model, indent=2), encoding="utf-8")
    return path


def test_build_fitlins_command_uses_supported_cli_subset():
    params = FitLinsParameters(
        bids_dir="/data",
        output_dir="/out",
        analysis_level="subject",
        model="/tmp/model.json",
        derivatives_dir="/derivatives",
        participant_label=("01",),
        exclude_participant=("02",),
        desc="preproc",
        smoothing="5",
        hrf_model="canonical",
        drift_model="cosine",
        drift_order=3,
        include_confounds=("trans_x",),
        confound_strategy="motion",
        confounds_file="/tmp/confounds.tsv",
        confounds_target_file="/tmp/native_confounds.tsv",
        n_compcor=2,
        estimator="nilearn",
        reports_only=True,
        write_graph=True,
        ignore=("events",),
        force_index=("suffix",),
        extra_args=("--drop-missing",),
    )

    cmd = params.command()

    assert "--model" in cmd
    assert "--derivatives" in cmd
    assert "--participant-label" in cmd
    assert "--desc-label" in cmd
    assert "--drift-model" in cmd
    assert "--estimator" in cmd
    assert "--reports-only" in cmd
    assert "--ignore" in cmd
    assert "--force-index" in cmd
    assert "--drop-missing" in cmd

    assert "--hrf-model" not in cmd
    assert "--include-confounds" not in cmd
    assert "--confound-strategy" not in cmd
    assert "--n-compcor" not in cmd
    assert "--drift-order" not in cmd
    assert "--exclude-participant-label" not in cmd
    assert "--write-graph" not in cmd


def test_prepare_fitlins_effective_model_injects_hrf_and_confounds(tmp_path: Path):
    model_path = _write_model(tmp_path / "model.json")
    out_dir = tmp_path / "out"
    params = FitLinsParameters(
        bids_dir=str(tmp_path / "bids"),
        output_dir=str(out_dir),
        model=str(model_path),
        hrf_model="canonical",
        include_confounds=("cardiac_retroicor_sin1", "pupil_filtered_z"),
    )
    (tmp_path / "bids").mkdir()

    prepared = _prepare_fitlins_effective_model(params)
    prepared_model = json.loads(Path(prepared.model).read_text())
    run_node = _find_run_node(prepared_model)
    assert run_node is not None
    convolve_idx = _find_convolve_idx(run_node)
    assert convolve_idx is not None
    convolve = run_node["Transformations"]["Instructions"][convolve_idx]
    assert convolve["Model"] == "spm"
    assert convolve["Derivative"] is False
    assert convolve["Dispersion"] is False
    assert run_node["Model"]["X"] == [1, "trial_type.*", "cardiac_retroicor_sin1", "pupil_filtered_z"]


def test_prepare_fitlins_effective_model_rejects_flobs(tmp_path: Path):
    model_path = _write_model(tmp_path / "model.json")
    out_dir = tmp_path / "out"
    (tmp_path / "bids").mkdir()
    params = FitLinsParameters(
        bids_dir=str(tmp_path / "bids"),
        output_dir=str(out_dir),
        model=str(model_path),
        hrf_model="flobs",
    )

    with pytest.raises(ValueError, match="FLOBS"):
        _prepare_fitlins_effective_model(params)


def test_prepare_fitlins_external_confounds_creates_overlay(tmp_path: Path):
    bids_dir = tmp_path / "bids"
    bids_dir.mkdir()
    derivatives_dir = tmp_path / "derivatives"
    func_dir = derivatives_dir / "sub-01" / "func"
    func_dir.mkdir(parents=True)
    (derivatives_dir / "dataset_description.json").write_text(
        json.dumps({"Name": "derivs", "BIDSVersion": "1.4.0", "DatasetType": "derivative"}),
        encoding="utf-8",
    )
    native_confounds = func_dir / "sub-01_task-rest_desc-confounds_timeseries.tsv"
    pd.DataFrame({"trans_x": [0.1, 0.2, 0.3]}).to_csv(native_confounds, sep="	", index=False)
    external_confounds = tmp_path / "merged_confounds.tsv"
    pd.DataFrame({"cardiac_retroicor_sin1": [1.0, 0.0, -1.0]}).to_csv(
        external_confounds,
        sep="	",
        index=False,
    )

    params = FitLinsParameters(
        bids_dir=str(bids_dir),
        output_dir=str(tmp_path / "out"),
        derivatives_dir=str(derivatives_dir),
        participant_label=("01",),
        confounds_file=str(external_confounds),
    )

    prepared = _prepare_fitlins_external_confounds(params)
    overlay_root = Path(prepared.derivatives_dir)
    overlay_confounds = overlay_root / "sub-01" / "func" / native_confounds.name
    overlay_df = pd.read_csv(overlay_confounds, sep="	")
    original_df = pd.read_csv(native_confounds, sep="	")

    assert overlay_root.exists()
    assert overlay_df.columns.tolist() == ["trans_x", "cardiac_retroicor_sin1"]
    assert original_df.columns.tolist() == ["trans_x"]
    assert (overlay_root / "native_confounds_overlay.json").exists()


def test_fitlins_tool_create_bids_model_uses_nodes_structure():
    model = FitLinsTool()._create_bids_model(
        bids_dir="/tmp/ds",
        hrf_model="canonical",
        include_confounds=["cardiac_retroicor_sin1"],
    )
    run_node = _find_run_node(model)
    assert run_node is not None
    convolve = run_node["Transformations"]["Instructions"][1]
    assert convolve["Model"] == "spm"
    assert "cardiac_retroicor_sin1" in run_node["Model"]["X"]



def test_prepare_fitlins_external_confounds_infers_unique_target_by_row_count(tmp_path: Path):
    bids_dir = tmp_path / "bids"
    bids_dir.mkdir()
    derivatives_dir = tmp_path / "derivatives"
    func_dir_01 = derivatives_dir / "sub-01" / "func"
    func_dir_02 = derivatives_dir / "sub-02" / "func"
    func_dir_01.mkdir(parents=True)
    func_dir_02.mkdir(parents=True)
    (derivatives_dir / "dataset_description.json").write_text(
        json.dumps({"Name": "derivs", "BIDSVersion": "1.4.0", "DatasetType": "derivative"}),
        encoding="utf-8",
    )
    native_01 = func_dir_01 / "sub-01_task-rest_desc-confounds_timeseries.tsv"
    native_02 = func_dir_02 / "sub-02_task-rest_desc-confounds_timeseries.tsv"
    pd.DataFrame({"trans_x": [0.1, 0.2, 0.3]}).to_csv(native_01, sep="	", index=False)
    pd.DataFrame({"trans_x": [0.1, 0.2, 0.3, 0.4]}).to_csv(native_02, sep="	", index=False)
    external_confounds = tmp_path / "merged_confounds.tsv"
    pd.DataFrame({"pupil_filtered_z": [1.0, 0.0, -1.0]}).to_csv(
        external_confounds,
        sep="	",
        index=False,
    )

    params = FitLinsParameters(
        bids_dir=str(bids_dir),
        output_dir=str(tmp_path / "out"),
        derivatives_dir=str(derivatives_dir),
        confounds_file=str(external_confounds),
    )

    prepared = _prepare_fitlins_external_confounds(params)
    overlay_root = Path(prepared.derivatives_dir)
    overlay_df = pd.read_csv(
        overlay_root / "sub-01" / "func" / native_01.name,
        sep="	",
    )

    assert overlay_df.columns.tolist() == ["trans_x", "pupil_filtered_z"]
    assert not (overlay_root / "sub-02" / "func" / native_02.name).exists()



def test_prepare_fitlins_external_confounds_map_stages_multiple_targets(tmp_path: Path):
    bids_dir = tmp_path / "bids"
    bids_dir.mkdir()
    derivatives_dir = tmp_path / "derivatives"
    func_dir_01 = derivatives_dir / "sub-01" / "func"
    func_dir_02 = derivatives_dir / "sub-02" / "func"
    func_dir_01.mkdir(parents=True)
    func_dir_02.mkdir(parents=True)
    (derivatives_dir / "dataset_description.json").write_text(
        json.dumps({"Name": "derivs", "BIDSVersion": "1.4.0", "DatasetType": "derivative"}),
        encoding="utf-8",
    )
    native_01 = func_dir_01 / "sub-01_task-rest_desc-confounds_timeseries.tsv"
    native_02 = func_dir_02 / "sub-02_task-rest_desc-confounds_timeseries.tsv"
    pd.DataFrame({"trans_x": [0.1, 0.2, 0.3]}).to_csv(native_01, sep="	", index=False)
    pd.DataFrame({"trans_x": [0.4, 0.5, 0.6]}).to_csv(native_02, sep="	", index=False)

    external_01 = tmp_path / "external_01.tsv"
    external_02 = tmp_path / "external_02.tsv"
    pd.DataFrame({"cardiac_retroicor_sin1": [1.0, 0.0, -1.0]}).to_csv(external_01, sep="	", index=False)
    pd.DataFrame({"pupil_filtered_z": [0.5, 0.2, -0.7]}).to_csv(external_02, sep="	", index=False)
    mapping_path = tmp_path / "confounds_map.json"
    mapping_path.write_text(
        json.dumps(
            {
                "targets": [
                    {
                        "target": str(native_01.relative_to(derivatives_dir)),
                        "confounds_file": str(external_01),
                    },
                    {
                        "target": str(native_02.relative_to(derivatives_dir)),
                        "confounds_file": str(external_02),
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    params = FitLinsParameters(
        bids_dir=str(bids_dir),
        output_dir=str(tmp_path / "out"),
        derivatives_dir=str(derivatives_dir),
        participant_label=("01", "02"),
        confounds_map_file=str(mapping_path),
    )

    prepared = _prepare_fitlins_external_confounds(params)
    overlay_root = Path(prepared.derivatives_dir)
    overlay_01 = pd.read_csv(overlay_root / "sub-01" / "func" / native_01.name, sep="	")
    overlay_02 = pd.read_csv(overlay_root / "sub-02" / "func" / native_02.name, sep="	")
    metadata = json.loads((overlay_root / "native_confounds_overlay.json").read_text())

    assert overlay_01.columns.tolist() == ["trans_x", "cardiac_retroicor_sin1"]
    assert overlay_02.columns.tolist() == ["trans_x", "pupil_filtered_z"]
    assert metadata["overlay_count"] == 2
