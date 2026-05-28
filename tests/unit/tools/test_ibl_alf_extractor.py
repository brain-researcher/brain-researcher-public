from pathlib import Path

import numpy as np
import pandas as pd

from brain_researcher.services.tools.ibl_alf_extractor import extract_session_tables


def _save_npy(path: Path, values) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, np.asarray(values))


def _read_table(result: dict[str, object]) -> pd.DataFrame:
    path = Path(result["path"])
    if result["format"] == "parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def test_extract_session_tables_creates_expected_outputs(tmp_path):
    session = (
        tmp_path
        / "data"
        / "churchlandlab"
        / "Subjects"
        / "CSHL049"
        / "2020-01-08"
        / "001"
    )
    alf_dir = session / "alf"
    probe_dir = alf_dir / "probe00"

    _save_npy(alf_dir / "_ibl_trials.choice.npy", [1, -1])
    _save_npy(alf_dir / "_ibl_trials.contrastLeft.npy", [0.25, 0.0])
    _save_npy(alf_dir / "_ibl_trials.contrastRight.npy", [0.0, 0.5])
    _save_npy(alf_dir / "_ibl_trials.feedbackType.npy", [1, -1])
    _save_npy(alf_dir / "_ibl_trials.intervals.npy", [[0.0, 1.0], [1.5, 2.5]])
    _save_npy(alf_dir / "_ibl_wheel.timestamps.npy", [0.0, 0.5, 1.0])
    _save_npy(alf_dir / "_ibl_wheel.position.npy", [0.0, 0.1, 0.4])
    _save_npy(probe_dir / "spikes.times.npy", [0.1, 0.2, 1.8, 2.0])
    _save_npy(probe_dir / "spikes.clusters.npy", [0, 1, 0, 1])
    _save_npy(probe_dir / "spikes.amps.npy", [10.0, 11.0, 12.0, 13.0])
    _save_npy(
        probe_dir / "clusters.brainLocationAcronyms_ccf_2017.npy",
        ["VISp", "LGd"],
    )
    _save_npy(probe_dir / "clusters.brainLocationIds_ccf_2017.npy", [101, 202])
    _save_npy(probe_dir / "clusters.channels.npy", [11, 22])
    _save_npy(probe_dir / "clusters.depths.npy", [123.4, 234.5])
    _save_npy(probe_dir / "clusters.mlapdv.npy", [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
    _save_npy(probe_dir / "channels.brainLocationIds_ccf_2017.npy", [101, 102, 103])
    _save_npy(
        probe_dir / "channels.localCoordinates.npy",
        [[43.0, 20.0], [11.0, 20.0], [59.0, 40.0]],
    )
    _save_npy(
        probe_dir / "channels.mlapdv.npy",
        [[-1222, -2714, -4318], [-1222, -2714, -4318], [-1226, -2710, -4297]],
    )
    _save_npy(probe_dir / "channels.rawInd.npy", [0, 1, 2])
    _save_npy(probe_dir / "electrodeSites.brainLocationIds_ccf_2017.npy", [101, 102, 103, 104])
    _save_npy(
        probe_dir / "electrodeSites.localCoordinates.npy",
        [[43.0, 20.0], [11.0, 20.0], [59.0, 40.0], [27.0, 60.0]],
    )
    _save_npy(
        probe_dir / "electrodeSites.mlapdv.npy",
        [
            [-1222, -2714, -4318],
            [-1222, -2714, -4318],
            [-1226, -2710, -4297],
            [-1230, -2706, -4276],
        ],
    )
    (alf_dir / "probes.description.test.json").write_text(
        '[{"label":"probe00","model":"3A","serial":714001507,"raw_file_name":"raw/probe00.ap.bin"}]',
        encoding="utf-8",
    )

    result = extract_session_tables(session, output_dir=tmp_path / "out")

    assert result["session_path"] == str(session)
    assert result["alf_path"] == str(alf_dir)
    assert result["output_dir"] == str(tmp_path / "out")
    assert result["probes"] == ["probe00"]
    assert set(result["tables"]) == {
        "trials",
        "wheel_samples",
        "spikes_probe00",
        "regions_probe00",
        "channels_probe00",
        "electrode_sites_probe00",
        "probe_trajectories",
    }

    trials = result["tables"]["trials"]
    wheel = result["tables"]["wheel_samples"]
    spikes = result["tables"]["spikes_probe00"]
    regions = result["tables"]["regions_probe00"]
    channels = result["tables"]["channels_probe00"]
    electrode_sites = result["tables"]["electrode_sites_probe00"]
    probe_trajectories = result["tables"]["probe_trajectories"]

    assert Path(trials["path"]).exists()
    assert Path(wheel["path"]).exists()
    assert Path(spikes["path"]).exists()
    assert Path(regions["path"]).exists()
    assert Path(channels["path"]).exists()
    assert Path(electrode_sites["path"]).exists()
    assert Path(probe_trajectories["path"]).exists()

    assert trials["rows"] == 2
    assert wheel["rows"] == 3
    assert spikes["rows"] == 4
    assert regions["rows"] == 2
    assert channels["rows"] == 3
    assert electrode_sites["rows"] == 4
    assert probe_trajectories["rows"] == 1

    trials_df = _read_table(trials)
    wheel_df = _read_table(wheel)
    spikes_df = _read_table(spikes)
    regions_df = _read_table(regions)
    channels_df = _read_table(channels)
    electrode_sites_df = _read_table(electrode_sites)
    probe_trajectories_df = _read_table(probe_trajectories)

    assert list(trials_df["trial_index"]) == [0, 1]
    assert list(trials_df["choice"]) == [1, -1]
    assert list(trials_df["interval_start"]) == [0.0, 1.5]
    assert list(trials_df["interval_end"]) == [1.0, 2.5]

    assert list(wheel_df["sample_index"]) == [0, 1, 2]
    assert list(wheel_df["position"]) == [0.0, 0.1, 0.4]

    assert list(spikes_df["probe_label"]) == ["probe00"] * 4
    assert list(spikes_df["cluster_id"]) == [0, 1, 0, 1]
    assert list(spikes_df["amps"]) == [10.0, 11.0, 12.0, 13.0]

    assert list(regions_df["probe_label"]) == ["probe00"] * 2
    assert list(regions_df["region_acronym"]) == ["VISp", "LGd"]
    assert list(regions_df["region_id"]) == [101, 202]
    assert list(regions_df["channel"]) == [11, 22]
    assert list(regions_df["depth_um"]) == [123.4, 234.5]
    assert list(regions_df["ml_um"]) == [1.0, 4.0]
    assert list(regions_df["ap_um"]) == [2.0, 5.0]
    assert list(regions_df["dv_um"]) == [3.0, 6.0]

    assert list(channels_df["channel_index"]) == [0, 1, 2]
    assert list(channels_df["region_id"]) == [101, 102, 103]
    assert list(channels_df["raw_index"]) == [0, 1, 2]
    assert list(channels_df["local_x_um"]) == [43.0, 11.0, 59.0]
    assert list(channels_df["dv_um"]) == [-4318, -4318, -4297]

    assert list(electrode_sites_df["site_index"]) == [0, 1, 2, 3]
    assert list(electrode_sites_df["region_id"]) == [101, 102, 103, 104]
    assert list(electrode_sites_df["local_y_um"]) == [20.0, 20.0, 40.0, 60.0]
    assert list(electrode_sites_df["ml_um"]) == [-1222, -1222, -1226, -1230]

    assert list(probe_trajectories_df["probe_label"]) == ["probe00"]
    assert list(probe_trajectories_df["model"]) == ["3A"]
    assert list(probe_trajectories_df["serial"]) == [714001507]
    assert list(probe_trajectories_df["trajectory_source"]) == ["electrodeSites.mlapdv"]
    assert list(probe_trajectories_df["site_count"]) == [4]
    assert list(probe_trajectories_df["start_ml_um"]) == [-1222]
    assert list(probe_trajectories_df["end_dv_um"]) == [-4276]


def test_extract_session_tables_prefers_trials_table_parquet(tmp_path):
    session = (
        tmp_path
        / "data"
        / "churchlandlab"
        / "Subjects"
        / "CSHL049"
        / "2020-01-08"
        / "001"
    )
    alf_dir = session / "alf"
    probe_dir = alf_dir / "probe00"
    alf_dir.mkdir(parents=True, exist_ok=True)
    probe_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        {
            "choice": [1, -1],
            "contrastLeft": [1.0, np.nan],
            "contrastRight": [np.nan, 0.125],
            "intervals_0": [0.0, 1.0],
            "intervals_1": [0.9, 2.0],
        }
    ).to_parquet(alf_dir / "_ibl_trials.table.test.pqt", index=False)
    _save_npy(alf_dir / "_ibl_wheel.timestamps.npy", [0.0, 0.5, 1.0])
    _save_npy(alf_dir / "_ibl_wheel.position.npy", [0.0, 0.1, 0.4])
    _save_npy(probe_dir / "spikes.times.npy", [0.1, 0.2])
    _save_npy(probe_dir / "spikes.clusters.npy", [0, 1])
    _save_npy(probe_dir / "clusters.brainLocationIds_ccf_2017.npy", [101, 202])

    result = extract_session_tables(session, output_dir=tmp_path / "out")
    trials_df = _read_table(result["tables"]["trials"])

    assert list(trials_df["trial_index"]) == [0, 1]
    assert list(trials_df["choice"]) == [1, -1]
    assert list(trials_df["interval_start"]) == [0.0, 1.0]
    assert list(trials_df["interval_end"]) == [0.9, 2.0]


def test_extract_session_tables_handles_probe_with_only_electrode_sites(tmp_path):
    session = (
        tmp_path
        / "data"
        / "churchlandlab"
        / "Subjects"
        / "CSHL049"
        / "2020-01-08"
        / "001"
    )
    alf_dir = session / "alf"
    probe_dir = alf_dir / "probe01"
    probe_dir.mkdir(parents=True, exist_ok=True)

    _save_npy(alf_dir / "_ibl_wheel.timestamps.npy", [0.0, 0.5])
    _save_npy(alf_dir / "_ibl_wheel.position.npy", [0.0, 0.1])
    _save_npy(
        probe_dir / "electrodeSites.localCoordinates.npy",
        [[43.0, 20.0], [11.0, 40.0]],
    )
    _save_npy(
        probe_dir / "electrodeSites.mlapdv.npy",
        [[-2969, -639, -7237], [-1975, 24, -3769]],
    )
    (alf_dir / "probes.description.test.json").write_text(
        '[{"label":"probe01","model":"3A","serial":714001528}]',
        encoding="utf-8",
    )

    result = extract_session_tables(
        session,
        output_dir=tmp_path / "out",
        include_trials=False,
        include_wheel=False,
        include_spikes=False,
        include_regions=False,
        probe_label="probe01",
    )

    assert "channels_probe01" not in result["tables"]
    assert "electrode_sites_probe01" in result["tables"]
    assert "probe_trajectories" in result["tables"]
    assert any("Channel arrays not found" in note for note in result["notes"])

    trajectory_df = _read_table(result["tables"]["probe_trajectories"])
    assert list(trajectory_df["probe_label"]) == ["probe01"]
    assert list(trajectory_df["trajectory_source"]) == ["electrodeSites.mlapdv"]
    assert list(trajectory_df["site_count"]) == [2]
