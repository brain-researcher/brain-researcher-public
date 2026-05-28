from types import SimpleNamespace

import numpy as np
import pandas as pd

from brain_researcher.services.tools.ibl_tools import (
    IBLBrainboxSessionEphysTool,
    IBLDecodingDatasetTool,
    IBLDeepLabCutTool,
    IBLKilosortTool,
    IBLLightningPoseTool,
    IBLNeuropixelsWorkflowTool,
    IBLOneTool,
    IBLSpikeBehaviorAlignmentTool,
    get_all_tools,
)


def test_get_all_tools_returns_expected_ibl_wrappers():
    tools = get_all_tools()
    names = [tool.get_tool_name() for tool in tools]

    assert names == [
        "ibl_one",
        "ibl_brainbox_session_ephys",
        "ibl_atlas_region_mapping",
        "ibl_rig_task_layer",
        "ibl_sorter",
        "ibl_kilosort",
        "ibl_deeplabcut",
        "ibl_lightning_pose",
        "ibl_spike_behavior_alignment",
        "ibl_decoding_dataset",
        "ibl_neuropixels_workflow",
    ]


def test_ibl_one_tool_dry_run_succeeds_with_dependency_summary():
    tool = IBLOneTool()
    result = tool._run(
        dataset_ref="ds:manual:ibl_brainwide",
        query="visual decision-making",
        limit=10,
        dry_run=True,
    )

    assert result.status == "success"
    assert result.data["summary"]["tool_id"] == "ibl_one"
    assert result.data["summary"]["mode"] == "dry_run"
    assert "dependency_summary" in result.data["summary"]
    assert result.data["outputs"]["dataset_ref"] == "ds:manual:ibl_brainwide"
    assert result.data["outputs"]["planned_resources"] == ["path_list", "metadata"]


def test_ibl_one_tool_strict_mode_errors_when_dependencies_are_missing(monkeypatch):
    tool = IBLOneTool()
    monkeypatch.setattr(
        "brain_researcher.services.tools.ibl_tools._dependency_summary",
        lambda *args, **kwargs: {
            "required_modules": ["one.api"],
            "available_modules": [],
            "missing_modules": ["one.api"],
            "all_available": False,
        },
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.ibl_tools.query_service.dataset_resources",
        lambda *args, **kwargs: None,
    )

    result = tool._run(
        dataset_ref="ds:manual:ibl_brainwide",
        dry_run=False,
        allow_missing_dependencies=False,
    )

    assert result.status == "error"
    assert result.error == "missing_optional_dependencies"
    assert result.data["summary"]["dependency_mode"] == "missing"


def test_ibl_one_tool_live_mode_prefers_aggregate_smoke_summary(monkeypatch, tmp_path):
    root = tmp_path / "ibl-brain-wide-map-public"
    aggregate_release = root / "aggregates" / "2024_Q2_IBL_et_al_BWM"
    aggregate_release.mkdir(parents=True, exist_ok=True)
    (aggregate_release / "trials.pqt").write_text("x", encoding="utf-8")
    (aggregate_release / "clusters.pqt").write_text("x", encoding="utf-8")

    monkeypatch.setattr(
        "brain_researcher.services.tools.ibl_tools.query_service.dataset_resources",
        lambda *args, **kwargs: SimpleNamespace(
            local_path=str(root),
            resolved_dataset_id="ds:manual:ibl_brainwide",
            mount_status={"mounted": True, "mount_kind": "public_s3"},
        ),
    )

    tool = IBLOneTool()
    result = tool._run(
        dataset_ref="ds:manual:ibl_brainwide",
        dry_run=False,
        allow_missing_dependencies=False,
    )

    assert result.status == "success"
    assert result.data["summary"]["mode"] == "local_mount"
    assert result.data["summary"]["dependency_mode"] == "local_mount"
    aggregate_summary = result.data["outputs"]["aggregate_summary"]
    assert aggregate_summary["aggregate_release"] == "2024_Q2_IBL_et_al_BWM"
    assert aggregate_summary["required_files"] == {
        "trials.pqt": True,
        "clusters.pqt": True,
    }
    assert aggregate_summary["smoke_passed"] is True


def test_ibl_one_tool_live_mode_uses_local_mount_summary(monkeypatch, tmp_path):
    root = tmp_path / "ibl-brain-wide-map-public"
    session = root / "data" / "cortexlab" / "Subjects" / "KS023" / "2019-12-10" / "001"
    (session / "alf" / "probe01").mkdir(parents=True, exist_ok=True)
    (session / "raw_ephys_data" / "probe01").mkdir(parents=True, exist_ok=True)
    (session / "alf" / "_ibl_trials.choice.npy").write_text("x", encoding="utf-8")
    (session / "alf" / "probe01" / "spikes.times.npy").write_text("x", encoding="utf-8")

    monkeypatch.setattr(
        "brain_researcher.services.tools.ibl_tools.query_service.dataset_resources",
        lambda *args, **kwargs: SimpleNamespace(
            local_path=str(root),
            resolved_dataset_id="ds:manual:ibl_brainwide",
            mount_status={"mounted": True, "mount_kind": "public_s3"},
        ),
    )

    tool = IBLOneTool()
    result = tool._run(
        dataset_ref="ds:manual:ibl_brainwide",
        dry_run=False,
        allow_missing_dependencies=False,
    )

    assert result.status == "success"
    assert result.data["summary"]["mode"] == "local_mount"
    assert result.data["summary"]["dependency_mode"] == "local_mount"
    assert result.data["outputs"]["labs_count"] == 1
    assert result.data["outputs"]["labs_sample"] == ["cortexlab"]
    assert result.data["outputs"]["sample_sessions"][0]["session_id"] == (
        "cortexlab/KS023/2019-12-10/001"
    )
    assert result.data["outputs"]["sample_sessions"][0]["probe_labels"] == ["probe01"]


def test_ibl_brainbox_session_ephys_live_mode_summarizes_session(monkeypatch, tmp_path):
    root = tmp_path / "ibl-brain-wide-map-public"
    session = (
        root
        / "data"
        / "churchlandlab"
        / "Subjects"
        / "CSHL049"
        / "2020-01-08"
        / "001"
    )
    (session / "alf" / "probe00").mkdir(parents=True, exist_ok=True)
    (session / "raw_ephys_data" / "probe00").mkdir(parents=True, exist_ok=True)
    (session / "raw_behavior_data").mkdir(parents=True, exist_ok=True)
    np.save(session / "alf" / "_ibl_trials.choice.npy", np.asarray([1, -1]))
    np.save(
        session / "alf" / "_ibl_trials.intervals.npy",
        np.asarray([[0.0, 1.0], [1.5, 2.5]]),
    )
    np.save(session / "alf" / "_ibl_wheel.timestamps.npy", np.asarray([0.0, 0.5, 1.0]))
    np.save(session / "alf" / "_ibl_wheel.position.npy", np.asarray([0.0, 0.1, 0.4]))
    np.save(session / "alf" / "_ibl_wheelMoves.intervals.npy", np.asarray([[0.0, 0.3]]))
    np.save(session / "alf" / "_ibl_wheelMoves.peakAmplitude.npy", np.asarray([0.4]))
    np.save(session / "alf" / "probe00" / "spikes.times.npy", np.asarray([0.1, 0.2, 1.8]))
    np.save(session / "alf" / "probe00" / "spikes.clusters.npy", np.asarray([0, 1, 0]))
    np.save(session / "alf" / "probe00" / "spikes.amps.npy", np.asarray([10.0, 11.0, 12.0]))
    np.save(
        session / "alf" / "probe00" / "clusters.brainLocationAcronyms_ccf_2017.npy",
        np.asarray(["VISp", "LGd"]),
    )
    np.save(
        session / "alf" / "probe00" / "clusters.brainLocationIds_ccf_2017.npy",
        np.asarray([101, 202]),
    )
    np.save(session / "alf" / "probe00" / "clusters.channels.npy", np.asarray([11, 22]))
    np.save(session / "alf" / "probe00" / "clusters.depths.npy", np.asarray([123.4, 234.5]))
    np.save(
        session / "alf" / "probe00" / "clusters.mlapdv.npy",
        np.asarray([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]),
    )
    np.save(
        session / "alf" / "probe00" / "channels.brainLocationIds_ccf_2017.npy",
        np.asarray([101, 102, 103]),
    )
    np.save(
        session / "alf" / "probe00" / "channels.localCoordinates.npy",
        np.asarray([[43.0, 20.0], [11.0, 20.0], [59.0, 40.0]]),
    )
    np.save(
        session / "alf" / "probe00" / "channels.mlapdv.npy",
        np.asarray([[-1222, -2714, -4318], [-1222, -2714, -4318], [-1226, -2710, -4297]]),
    )
    np.save(session / "alf" / "probe00" / "channels.rawInd.npy", np.asarray([0, 1, 2]))
    np.save(
        session / "alf" / "probe00" / "electrodeSites.brainLocationIds_ccf_2017.npy",
        np.asarray([101, 102, 103, 104]),
    )
    np.save(
        session / "alf" / "probe00" / "electrodeSites.localCoordinates.npy",
        np.asarray([[43.0, 20.0], [11.0, 20.0], [59.0, 40.0], [27.0, 60.0]]),
    )
    np.save(
        session / "alf" / "probe00" / "electrodeSites.mlapdv.npy",
        np.asarray(
            [
                [-1222, -2714, -4318],
                [-1222, -2714, -4318],
                [-1226, -2710, -4297],
                [-1230, -2706, -4276],
            ]
        ),
    )
    (session / "alf" / "probes.description.test.json").write_text(
        '[{"label":"probe00","model":"3A","serial":714001507,"raw_file_name":"raw/probe00.ap.bin"}]',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "brain_researcher.services.tools.ibl_tools.query_service.dataset_resources",
        lambda *args, **kwargs: SimpleNamespace(
            local_path=str(root),
            resolved_dataset_id="ds:manual:ibl_brainwide",
            mount_status={"mounted": True, "mount_kind": "public_s3"},
        ),
    )

    tool = IBLBrainboxSessionEphysTool()
    result = tool._run(
        session_id="CSHL049/2020-01-08/001",
        dataset_ref="ds:manual:ibl_brainwide",
        probe_label="probe00",
        output_dir=str(tmp_path / "extract_out"),
        spike_limit=2,
        dry_run=False,
        allow_missing_dependencies=False,
    )

    assert result.status == "success"
    assert result.data["summary"]["mode"] == "local_mount"
    assert result.data["outputs"]["session_id"] == "churchlandlab/CSHL049/2020-01-08/001"
    assert result.data["outputs"]["session_summary"]["has_raw_behavior"] is True
    assert result.data["outputs"]["session_summary"]["requested_probe_present"] is True
    assert result.data["outputs"]["output_dir"] == str(tmp_path / "extract_out")
    assert result.data["outputs"]["notes"] == []
    extracted_tables = result.data["outputs"]["extracted_tables"]
    assert set(extracted_tables) == {
        "trials",
        "wheel_samples",
        "wheel_moves",
        "spikes_probe00",
        "regions_probe00",
        "channels_probe00",
        "electrode_sites_probe00",
        "probe_trajectories",
    }
    assert extracted_tables["trials"]["rows"] == 2
    assert extracted_tables["wheel_samples"]["rows"] == 3
    assert extracted_tables["wheel_moves"]["rows"] == 1
    assert extracted_tables["spikes_probe00"]["rows"] == 2
    assert extracted_tables["regions_probe00"]["rows"] == 2
    assert extracted_tables["channels_probe00"]["rows"] == 3
    assert extracted_tables["electrode_sites_probe00"]["rows"] == 4
    assert extracted_tables["probe_trajectories"]["rows"] == 1


def test_ibl_kilosort_tool_dry_run_plans_spike_sort_command():
    tool = IBLKilosortTool()
    result = tool._run(
        data_dir="/tmp/raw_ephys_data/probe00",
        sorter="kilosort4",
        dry_run=True,
    )

    assert result.status == "success"
    assert result.data["summary"]["tool_id"] == "ibl_kilosort"
    assert result.data["outputs"]["planned_command"] == [
        "spike_sort",
        "/tmp/raw_ephys_data/probe00",
        "--method",
        "kilosort4",
    ]
    assert result.data["outputs"]["planned_outputs"] == [
        "spike_times",
        "qc_report",
        "features_table",
        "metadata",
    ]


def test_ibl_kilosort_tool_live_mode_runs_spikeinterface_backend(monkeypatch, tmp_path):
    probe_dir = tmp_path / "raw_ephys_data" / "probe00"
    probe_dir.mkdir(parents=True, exist_ok=True)
    (probe_dir / "_spikeglx_ephysData_g0_t0.imec.ap.fake.cbin").write_bytes(b"cbin")
    (probe_dir / "_spikeglx_ephysData_g0_t0.imec.ap.fake.meta").write_text("meta", encoding="utf-8")

    class FakeRecording:
        def get_num_frames(self):
            return 30000

        def get_sampling_frequency(self):
            return 30000.0

        def frame_slice(self, start_frame: int, end_frame: int):
            return self

    class FakeSorting:
        def to_spike_vector(self):
            return np.array(
                [(0, 0, 0), (1500, 0, 1), (3000, 0, 1)],
                dtype=[("sample_index", "int64"), ("segment_index", "int64"), ("unit_index", "int64")],
            )

        def get_unit_ids(self):
            return np.asarray([11, 22])

    monkeypatch.setattr(
        "brain_researcher.services.tools.ibl_tools._load_spikeglx_recording",
        lambda *args, **kwargs: (
            FakeRecording(),
            {
                "normalized_input_dir": str(tmp_path / "norm"),
                "normalized_bin_path": str(tmp_path / "norm" / "fake.bin"),
                "normalized_meta_path": str(tmp_path / "norm" / "fake.meta"),
                "source_cbin_path": str(probe_dir / "_spikeglx_ephysData_g0_t0.imec.ap.fake.cbin"),
                "source_meta_path": str(probe_dir / "_spikeglx_ephysData_g0_t0.imec.ap.fake.meta"),
            },
            1.0,
        ),
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.ibl_tools._materialize_sorter_recording",
        lambda recording, *, output_dir: recording,
    )
    monkeypatch.setattr(
        "spikeinterface.full.run_sorter",
        lambda *args, **kwargs: FakeSorting(),
    )
    monkeypatch.setattr(
        "spikeinterface.full.get_default_sorter_params",
        lambda sorter_name: {
            "Th_universal": 9,
            "Th_learned": 8,
            "n_pcs": 6,
            "torch_device": "auto",
        },
    )

    result = IBLKilosortTool()._run(
        data_dir=str(probe_dir),
        probe_label="probe00",
        output_dir=str(tmp_path / "kilosort_out"),
        max_duration_s=60,
        dry_run=False,
        allow_missing_dependencies=False,
    )

    assert result.status == "success"
    outputs = result.data["outputs"]
    assert outputs["n_units"] == 2
    assert outputs["n_spikes"] == 3
    assert outputs["spike_times_path"].endswith("spike_times.parquet")
    assert outputs["features_table_path"].endswith("unit_features.parquet")
    assert outputs["qc_report_path"].endswith("qc_report.json")
    assert outputs["sorter_recording_dir"].endswith("sorter_recording")


def test_pose_tools_dry_run_report_expected_backends():
    deeplabcut = IBLDeepLabCutTool()._run(
        video_path="/tmp/video.mp4",
        keypoint_schema=["nose", "paw_l"],
        dry_run=True,
    )
    lightning_pose = IBLLightningPoseTool()._run(
        video_path="/tmp/video.mp4",
        keypoint_schema=["nose", "paw_l"],
        dry_run=True,
    )

    assert deeplabcut.status == "success"
    assert deeplabcut.data["outputs"]["backend"] == "deeplabcut"
    assert deeplabcut.data["outputs"]["planned_outputs"] == [
        "coord_table",
        "optical_metrics",
        "metadata",
    ]
    assert lightning_pose.status == "success"
    assert lightning_pose.data["outputs"]["backend"] == "lightning_pose"
    assert lightning_pose.data["outputs"]["planned_outputs"] == [
        "coord_table",
        "optical_metrics",
        "metadata",
    ]


def test_ibl_spike_behavior_alignment_live_mode_extracts_local_inputs(
    monkeypatch, tmp_path
):
    root = tmp_path / "ibl-brain-wide-map-public"
    session = (
        root
        / "data"
        / "churchlandlab"
        / "Subjects"
        / "CSHL049"
        / "2020-01-08"
        / "001"
    )
    (session / "alf" / "probe00").mkdir(parents=True, exist_ok=True)
    np.save(session / "alf" / "_ibl_trials.choice.npy", np.asarray([1, -1]))
    np.save(
        session / "alf" / "_ibl_trials.intervals.npy",
        np.asarray([[0.0, 1.0], [1.5, 2.5]]),
    )
    np.save(session / "alf" / "_ibl_wheel.timestamps.npy", np.asarray([0.0, 0.5, 1.0]))
    np.save(session / "alf" / "_ibl_wheel.position.npy", np.asarray([0.0, 0.1, 0.4]))
    np.save(session / "alf" / "_ibl_wheelMoves.intervals.npy", np.asarray([[0.0, 0.3]]))
    np.save(session / "alf" / "_ibl_wheelMoves.peakAmplitude.npy", np.asarray([0.4]))
    np.save(session / "alf" / "probe00" / "spikes.times.npy", np.asarray([0.1, 0.2, 1.8]))
    np.save(session / "alf" / "probe00" / "spikes.clusters.npy", np.asarray([0, 1, 0]))

    monkeypatch.setattr(
        "brain_researcher.services.tools.ibl_tools.query_service.dataset_resources",
        lambda *args, **kwargs: SimpleNamespace(
            local_path=str(root),
            resolved_dataset_id="ds:manual:ibl_brainwide",
            mount_status={"mounted": True, "mount_kind": "public_s3"},
        ),
    )

    tool = IBLSpikeBehaviorAlignmentTool()
    result = tool._run(
        dataset_ref="ds:manual:ibl_brainwide",
        session_id="CSHL049/2020-01-08/001",
        output_dir=str(tmp_path / "alignment_out"),
        dry_run=False,
        allow_missing_dependencies=False,
    )

    assert result.status == "success"
    assert result.data["summary"]["mode"] == "local_mount"
    assert result.data["outputs"]["events_path"].endswith("trials.parquet")
    assert result.data["outputs"]["spike_times_path"].endswith("spikes_probe00.parquet")
    assert result.data["outputs"]["aligned_timeseries_path"].endswith("aligned_spikes.parquet")
    assert result.data["outputs"]["features_table_path"].endswith("trial_features.parquet")
    assert result.data["outputs"]["planned_outputs"] == [
        "aligned_timeseries",
        "timeseries",
        "features_table",
        "metadata",
    ]
    assert set(result.data["outputs"]["extracted_alignment_inputs"]) == {
        "trials",
        "wheel_samples",
        "wheel_moves",
        "spikes_probe00",
    }

    features = pd.read_parquet(result.data["outputs"]["features_table_path"])
    assert set(features["trial_index"]) == {0, 1}
    assert int(features["spike_count"].fillna(0).sum()) == 3


def test_ibl_decoding_dataset_tool_dry_run_reports_expected_outputs():
    result = IBLDecodingDatasetTool()._run(
        dataset_ref="ds:manual:ibl_brainwide",
        session_id="CSHL049/2020-01-08/001",
        probe_label="probe00",
        label_field="choice",
        feature_level="region",
        dry_run=True,
    )

    assert result.status == "success"
    assert result.data["summary"]["tool_id"] == "ibl_decoding_dataset"
    assert result.data["outputs"]["planned_outputs"] == [
        "data_file",
        "labels_file",
        "groups_file",
        "sample_metadata",
        "feature_metadata",
        "label_map",
        "metadata",
    ]


def test_ibl_decoding_dataset_tool_live_mode_builds_region_level_arrays(
    monkeypatch, tmp_path
):
    root = tmp_path / "ibl-brain-wide-map-public"
    session = (
        root
        / "data"
        / "churchlandlab"
        / "Subjects"
        / "CSHL049"
        / "2020-01-08"
        / "001"
    )
    (session / "alf" / "probe00").mkdir(parents=True, exist_ok=True)
    np.save(session / "alf" / "_ibl_trials.choice.npy", np.asarray([1, -1]))
    np.save(
        session / "alf" / "_ibl_trials.intervals.npy",
        np.asarray([[0.0, 1.0], [1.5, 2.5]]),
    )
    np.save(session / "alf" / "_ibl_trials.stimOn_times.npy", np.asarray([0.0, 1.6]))
    np.save(session / "alf" / "_ibl_trials.contrastLeft.npy", np.asarray([0.0, 0.5]))
    np.save(session / "alf" / "_ibl_trials.contrastRight.npy", np.asarray([0.5, 0.0]))
    np.save(session / "alf" / "probe00" / "spikes.times.npy", np.asarray([0.1, 0.2, 1.8]))
    np.save(session / "alf" / "probe00" / "spikes.clusters.npy", np.asarray([0, 1, 0]))
    np.save(
        session / "alf" / "probe00" / "clusters.brainLocationAcronyms_ccf_2017.npy",
        np.asarray(["VISp", "LGd"]),
    )
    np.save(
        session / "alf" / "probe00" / "clusters.brainLocationIds_ccf_2017.npy",
        np.asarray([101, 202]),
    )

    monkeypatch.setattr(
        "brain_researcher.services.tools.ibl_tools.query_service.dataset_resources",
        lambda *args, **kwargs: SimpleNamespace(
            local_path=str(root),
            resolved_dataset_id="ds:manual:ibl_brainwide",
            mount_status={"mounted": True, "mount_kind": "public_s3"},
        ),
    )

    result = IBLDecodingDatasetTool()._run(
        dataset_ref="ds:manual:ibl_brainwide",
        session_id="CSHL049/2020-01-08/001",
        probe_label="probe00",
        label_field="choice",
        feature_level="region",
        output_dir=str(tmp_path / "decoding_inputs"),
        dry_run=False,
        allow_missing_dependencies=False,
    )

    assert result.status == "success"
    assert result.data["summary"]["mode"] == "local_mount"
    outputs = result.data["outputs"]
    assert outputs["n_samples"] == 2
    assert outputs["n_features"] == 2
    X = np.load(outputs["data_file"])
    y = np.load(outputs["labels_file"])
    groups = np.load(outputs["groups_file"])
    assert X.shape == (2, 2)
    assert y.tolist() == [1, 0]
    assert groups.tolist() == [0, 0]

    sample_metadata = pd.read_parquet(outputs["sample_metadata_path"])
    assert sample_metadata["stimulus_side"].tolist() == [1, -1]
    feature_metadata = pd.read_parquet(outputs["feature_metadata_path"])
    assert set(feature_metadata["feature_name"]) == {"VISp", "LGd"}


def test_pose_tools_live_mode_materialize_precomputed_alf_pose(
    monkeypatch, tmp_path
):
    root = tmp_path / "ibl-brain-wide-map-public"
    session = (
        root
        / "data"
        / "churchlandlab"
        / "Subjects"
        / "CSHL049"
        / "2020-01-08"
        / "001"
    )
    (session / "alf").mkdir(parents=True, exist_ok=True)
    (session / "raw_video_data").mkdir(parents=True, exist_ok=True)
    (session / "raw_video_data" / "_iblrig_leftCamera.raw.mp4").write_bytes(b"video")
    pd.DataFrame({"paw_l_x": [1.0, 2.0], "paw_l_y": [3.0, 4.0]}).to_parquet(
        session / "alf" / "_ibl_leftCamera.lightningPose.test.pqt",
        index=False,
    )
    pd.DataFrame({"pupilDiameter_raw": [4.2, 4.3]}).to_parquet(
        session / "alf" / "_ibl_leftCamera.features.test.pqt",
        index=False,
    )
    np.save(session / "alf" / "_ibl_leftCamera.times.test.npy", np.asarray([0.1, 0.2]))

    monkeypatch.setattr(
        "brain_researcher.services.tools.ibl_tools.query_service.dataset_resources",
        lambda *args, **kwargs: SimpleNamespace(
            local_path=str(root),
            resolved_dataset_id="ds:manual:ibl_brainwide",
            mount_status={"mounted": True, "mount_kind": "public_s3"},
        ),
    )

    result = IBLLightningPoseTool()._run(
        dataset_ref="ds:manual:ibl_brainwide",
        session_id="CSHL049/2020-01-08/001",
        output_dir=str(tmp_path / "pose_out"),
        dry_run=False,
        allow_missing_dependencies=False,
    )

    assert result.status == "success"
    assert result.data["outputs"]["source"] == "ibl_alf_precomputed"
    assert result.data["outputs"]["camera"] == "leftCamera"
    coord_df = pd.read_parquet(result.data["outputs"]["coord_table_path"])
    assert list(coord_df["time_s"]) == [0.1, 0.2]


def test_ibl_neuropixels_workflow_live_mode_runs_kilosort_pose_and_alignment(
    monkeypatch, tmp_path
):
    root = tmp_path / "ibl-brain-wide-map-public"
    session = (
        root
        / "data"
        / "churchlandlab"
        / "Subjects"
        / "CSHL049"
        / "2020-01-08"
        / "001"
    )
    (session / "alf" / "probe00").mkdir(parents=True, exist_ok=True)
    (session / "raw_ephys_data" / "probe00").mkdir(parents=True, exist_ok=True)
    (session / "raw_video_data").mkdir(parents=True, exist_ok=True)
    (session / "raw_video_data" / "_iblrig_leftCamera.raw.mp4").write_bytes(b"video")
    np.save(session / "alf" / "_ibl_trials.choice.npy", np.asarray([1]))
    np.save(session / "alf" / "_ibl_trials.intervals.npy", np.asarray([[0.0, 1.0]]))
    np.save(session / "alf" / "_ibl_wheel.timestamps.npy", np.asarray([0.0, 0.5]))
    np.save(session / "alf" / "_ibl_wheel.position.npy", np.asarray([0.0, 0.1]))
    np.save(session / "alf" / "_ibl_wheelMoves.intervals.npy", np.asarray([[0.0, 0.3]]))
    np.save(session / "alf" / "_ibl_wheelMoves.peakAmplitude.npy", np.asarray([0.4]))
    np.save(session / "alf" / "probe00" / "spikes.times.npy", np.asarray([0.1]))
    np.save(session / "alf" / "probe00" / "spikes.clusters.npy", np.asarray([0]))
    pd.DataFrame({"paw_l_x": [1.0], "paw_l_y": [2.0]}).to_parquet(
        session / "alf" / "_ibl_leftCamera.dlc.test.pqt",
        index=False,
    )
    np.save(session / "alf" / "_ibl_leftCamera.times.test.npy", np.asarray([0.1]))

    monkeypatch.setattr(
        "brain_researcher.services.tools.ibl_tools.query_service.dataset_resources",
        lambda *args, **kwargs: SimpleNamespace(
            local_path=str(root),
            resolved_dataset_id="ds:manual:ibl_brainwide",
            mount_status={"mounted": True, "mount_kind": "public_s3"},
        ),
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.ibl_tools.IBLKilosortTool._run",
        lambda self, **kwargs: SimpleNamespace(
            status="success",
            data={
                "outputs": {
                    "spike_times_path": str(tmp_path / "fake_spike_times.parquet"),
                    "spike_times": {"path": str(tmp_path / "fake_spike_times.parquet")},
                    "qc_report": {"path": str(tmp_path / "fake_qc_report.json")},
                    "features_table": {"path": str(tmp_path / "fake_unit_features.parquet")},
                    "metadata": {"path": str(tmp_path / "fake_kilosort_meta.json")},
                }
            },
            model_dump=lambda: {
                "status": "success",
                "data": {"outputs": {"spike_times_path": str(tmp_path / "fake_spike_times.parquet")}},
            },
        ),
    )
    pd.DataFrame({"spike_index": [0], "time_s": [0.1], "unit_id": [1]}).to_parquet(
        tmp_path / "fake_spike_times.parquet",
        index=False,
    )

    tool = IBLNeuropixelsWorkflowTool()
    result = tool._run(
        dataset_ref="ds:manual:ibl_brainwide",
        session_id="CSHL049/2020-01-08/001",
        probe_label="probe00",
        pose_backend="deeplabcut",
        dry_run=False,
        allow_missing_dependencies=False,
    )

    assert result.status == "success"
    assert result.data["summary"]["mode"] == "local_mount"
    assert result.data["outputs"]["pose_backend"] == "ibl_deeplabcut"
    assert result.data["outputs"]["raw_ephys_dir"].endswith("raw_ephys_data/probe00")
    assert result.data["outputs"]["video_path"].endswith("_iblrig_leftCamera.raw.mp4")
    assert result.data["outputs"]["spike_times_path"].endswith("fake_spike_times.parquet")
    assert result.data["outputs"]["coord_table_path"].endswith(".parquet")
    assert result.data["outputs"]["aligned_timeseries_path"].endswith("aligned_spikes.parquet")
    assert [step["tool"] for step in result.data["outputs"]["workflow_steps"]] == [
        "ibl_kilosort",
        "ibl_deeplabcut",
        "ibl_spike_behavior_alignment",
    ]
    assert result.data["outputs"]["planned_outputs"] == [
        "spike_times",
        "coord_table",
        "aligned_timeseries",
        "qc_report",
        "optical_metrics",
        "metadata",
    ]
