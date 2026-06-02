"""ALF-aware extraction helpers for mounted IBL public-tree sessions."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_TRIAL_FIELDS = (
    "choice",
    "contrastLeft",
    "contrastRight",
    "feedbackType",
    "feedback_times",
    "firstMovement_times",
    "goCueTrigger_times",
    "goCue_times",
    "intervals",
    "probabilityLeft",
    "response_times",
    "rewardVolume",
    "stimOff_times",
    "stimOn_times",
)


def _find_alf_file(directory: Path, prefix: str, extension: str) -> Path | None:
    ext = extension.lstrip(".")
    for pattern in (f"{prefix}.{ext}", f"{prefix}.*.{ext}"):
        matches = sorted(directory.glob(pattern))
        if matches:
            return matches[0]
    return None


def _load_npy(directory: Path, prefix: str) -> np.ndarray | None:
    path = _find_alf_file(directory, prefix, "npy")
    if path is None:
        return None
    return np.load(path, allow_pickle=True)


def _load_frame(directory: Path, prefix: str) -> pd.DataFrame | None:
    for extension in ("pqt", "parquet", "csv"):
        path = _find_alf_file(directory, prefix, extension)
        if path is None:
            continue
        if extension == "csv":
            return pd.read_csv(path)
        return pd.read_parquet(path)
    return None


def _load_json(directory: Path, prefix: str) -> Any:
    path = _find_alf_file(directory, prefix, "json")
    if path is None:
        return None
    return json.loads(path.read_text())


def _normalize_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    if isinstance(value, np.generic):
        return value.item()
    return value


def _series(values: Any) -> pd.Series:
    array = np.asarray(values)
    if array.ndim == 0:
        return pd.Series([_normalize_value(array.item())])
    if array.ndim == 1:
        return pd.Series([_normalize_value(item) for item in array.tolist()])
    return pd.Series([_normalize_value(item) for item in array.tolist()])


def _write_table(df: pd.DataFrame, output_dir: Path, stem: str) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = output_dir / f"{stem}.parquet"
    try:
        df.to_parquet(parquet_path, index=False)
        path = parquet_path
        fmt = "parquet"
    except Exception:
        csv_path = output_dir / f"{stem}.csv"
        df.to_csv(csv_path, index=False)
        path = csv_path
        fmt = "csv"

    return {
        "path": str(path),
        "format": fmt,
        "rows": int(len(df)),
        "columns": list(df.columns),
    }


def _probe_metadata_by_label(alf_dir: Path) -> dict[str, dict[str, Any]]:
    payload = _load_json(alf_dir, "probes.description")
    if not isinstance(payload, list):
        return {}

    metadata: dict[str, dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        if isinstance(label, str) and label:
            metadata[label] = item
    return metadata


def _add_local_coordinates(data: dict[str, Any], coords: np.ndarray | None) -> None:
    if coords is None:
        return
    array = np.asarray(coords)
    if array.ndim == 2 and array.shape[1] >= 2:
        data["local_x_um"] = _series(array[:, 0])
        data["local_y_um"] = _series(array[:, 1])


def _add_mlapdv_coordinates(data: dict[str, Any], coords: np.ndarray | None) -> None:
    if coords is None:
        return
    array = np.asarray(coords)
    if array.ndim == 2 and array.shape[1] >= 3:
        data["ml_um"] = _series(array[:, 0])
        data["ap_um"] = _series(array[:, 1])
        data["dv_um"] = _series(array[:, 2])


def _ordered_probe_sites(
    coords: np.ndarray | None,
    local_coords: np.ndarray | None,
) -> tuple[np.ndarray | None, np.ndarray | None]:
    if coords is None:
        return None, None

    coords_array = np.asarray(coords)
    if coords_array.ndim != 2 or coords_array.shape[1] < 3 or len(coords_array) == 0:
        return None, None

    if local_coords is not None:
        local_array = np.asarray(local_coords)
        if local_array.ndim == 2 and local_array.shape[0] == coords_array.shape[0]:
            order_index = np.argsort(local_array[:, 1], kind="stable")
            return coords_array[order_index[0]], coords_array[order_index[-1]]

    order_index = np.argsort(coords_array[:, 2], kind="stable")
    return coords_array[order_index[0]], coords_array[order_index[-1]]


def _session_output_dir(output_dir: str | None, session_path: Path) -> Path:
    if output_dir:
        return Path(output_dir).expanduser()
    return Path(tempfile.mkdtemp(prefix=f"ibl_alf_{session_path.name}_"))


def extract_trials_table(alf_dir: Path) -> pd.DataFrame:
    trials_table = _load_frame(alf_dir, "_ibl_trials.table")
    if trials_table is not None:
        renamed = trials_table.rename(
            columns={"intervals_0": "interval_start", "intervals_1": "interval_end"}
        ).copy()
        if "trial_index" not in renamed.columns:
            renamed.insert(0, "trial_index", np.arange(len(renamed), dtype=int))
        return renamed

    columns: dict[str, pd.Series] = {}
    for field in _TRIAL_FIELDS:
        values = _load_npy(alf_dir, f"_ibl_trials.{field}")
        if values is None and field == "intervals":
            values = _load_npy(alf_dir, "_ibl_trials.intervals_bpod")
        if values is None:
            continue
        if (
            field == "intervals"
            and np.asarray(values).ndim == 2
            and np.asarray(values).shape[1] >= 2
        ):
            array = np.asarray(values)
            columns["interval_start"] = _series(array[:, 0])
            columns["interval_end"] = _series(array[:, 1])
        else:
            columns[field] = _series(values)

    if not columns:
        raise FileNotFoundError(f"No ALF trial arrays found in {alf_dir}")

    trials = pd.DataFrame(columns)
    trials.insert(0, "trial_index", np.arange(len(trials), dtype=int))
    return trials


def extract_wheel_samples_table(alf_dir: Path) -> pd.DataFrame:
    timestamps = _load_npy(alf_dir, "_ibl_wheel.timestamps")
    if timestamps is None:
        timestamps = _load_npy(alf_dir, "_ibl_wheel.times")
    position = _load_npy(alf_dir, "_ibl_wheel.position")
    if timestamps is None or position is None:
        raise FileNotFoundError(f"Wheel timestamps/position not found in {alf_dir}")

    wheel = pd.DataFrame(
        {
            "sample_index": np.arange(len(timestamps), dtype=int),
            "time_s": _series(timestamps),
            "position": _series(position),
        }
    )
    return wheel


def extract_wheel_moves_table(alf_dir: Path) -> pd.DataFrame | None:
    intervals = _load_npy(alf_dir, "_ibl_wheelMoves.intervals")
    if intervals is None:
        return None
    array = np.asarray(intervals)
    if array.ndim != 2 or array.shape[1] < 2:
        return None

    peak_amplitude = _load_npy(alf_dir, "_ibl_wheelMoves.peakAmplitude")
    moves = pd.DataFrame(
        {
            "move_index": np.arange(array.shape[0], dtype=int),
            "interval_start": _series(array[:, 0]),
            "interval_end": _series(array[:, 1]),
        }
    )
    if peak_amplitude is not None:
        moves["peakAmplitude"] = _series(peak_amplitude)
    return moves


def extract_spikes_table(
    probe_dir: Path,
    *,
    probe_label: str,
    spike_limit: int | None = None,
) -> pd.DataFrame:
    times = _load_npy(probe_dir, "spikes.times")
    clusters = _load_npy(probe_dir, "spikes.clusters")
    if times is None or clusters is None:
        raise FileNotFoundError(f"Spike arrays not found in {probe_dir}")

    if spike_limit is not None:
        times = np.asarray(times)[:spike_limit]
        clusters = np.asarray(clusters)[:spike_limit]

    columns: dict[str, Any] = {
        "spike_index": np.arange(len(times), dtype=int),
        "probe_label": [probe_label] * len(times),
        "time_s": _series(times),
        "cluster_id": _series(clusters),
    }

    for field in ("amps", "depths", "samples"):
        values = _load_npy(probe_dir, f"spikes.{field}")
        if values is not None:
            if spike_limit is not None:
                values = np.asarray(values)[:spike_limit]
            columns[field] = _series(values)

    return pd.DataFrame(columns)


def extract_regions_table(probe_dir: Path, *, probe_label: str) -> pd.DataFrame:
    acronyms = _load_npy(probe_dir, "clusters.brainLocationAcronyms_ccf_2017")
    region_ids = _load_npy(probe_dir, "clusters.brainLocationIds_ccf_2017")
    channels = _load_npy(probe_dir, "clusters.channels")
    depths = _load_npy(probe_dir, "clusters.depths")

    if acronyms is None and region_ids is None:
        raise FileNotFoundError(f"Cluster region arrays not found in {probe_dir}")

    base_length = 0
    for values in (acronyms, region_ids, channels, depths):
        if values is not None:
            base_length = len(values)
            break
    if base_length == 0:
        raise FileNotFoundError(f"No usable cluster region arrays found in {probe_dir}")

    data: dict[str, Any] = {
        "cluster_id": np.arange(base_length, dtype=int),
        "probe_label": [probe_label] * base_length,
    }
    if acronyms is not None:
        data["region_acronym"] = _series(acronyms)
    if region_ids is not None:
        data["region_id"] = _series(region_ids)
    if channels is not None:
        data["channel"] = _series(channels)
    if depths is not None:
        data["depth_um"] = _series(depths)

    mlapdv = _load_npy(probe_dir, "clusters.mlapdv")
    if mlapdv is not None:
        coords = np.asarray(mlapdv)
        if coords.ndim == 2 and coords.shape[1] >= 3:
            data["ml_um"] = _series(coords[:, 0])
            data["ap_um"] = _series(coords[:, 1])
            data["dv_um"] = _series(coords[:, 2])

    return pd.DataFrame(data)


def extract_channels_table(probe_dir: Path, *, probe_label: str) -> pd.DataFrame:
    region_ids = _load_npy(probe_dir, "channels.brainLocationIds_ccf_2017")
    local_coords = _load_npy(probe_dir, "channels.localCoordinates")
    mlapdv = _load_npy(probe_dir, "channels.mlapdv")
    raw_ind = _load_npy(probe_dir, "channels.rawInd")

    base_length = 0
    for values in (region_ids, local_coords, mlapdv, raw_ind):
        if values is not None:
            base_length = len(values)
            break
    if base_length == 0:
        raise FileNotFoundError(f"Channel arrays not found in {probe_dir}")

    data: dict[str, Any] = {
        "channel_index": np.arange(base_length, dtype=int),
        "probe_label": [probe_label] * base_length,
    }
    if region_ids is not None:
        data["region_id"] = _series(region_ids)
    if raw_ind is not None:
        data["raw_index"] = _series(raw_ind)
    _add_local_coordinates(data, local_coords)
    _add_mlapdv_coordinates(data, mlapdv)
    return pd.DataFrame(data)


def extract_electrode_sites_table(probe_dir: Path, *, probe_label: str) -> pd.DataFrame:
    region_ids = _load_npy(probe_dir, "electrodeSites.brainLocationIds_ccf_2017")
    local_coords = _load_npy(probe_dir, "electrodeSites.localCoordinates")
    mlapdv = _load_npy(probe_dir, "electrodeSites.mlapdv")

    base_length = 0
    for values in (region_ids, local_coords, mlapdv):
        if values is not None:
            base_length = len(values)
            break
    if base_length == 0:
        raise FileNotFoundError(f"Electrode-site arrays not found in {probe_dir}")

    data: dict[str, Any] = {
        "site_index": np.arange(base_length, dtype=int),
        "probe_label": [probe_label] * base_length,
    }
    if region_ids is not None:
        data["region_id"] = _series(region_ids)
    _add_local_coordinates(data, local_coords)
    _add_mlapdv_coordinates(data, mlapdv)
    return pd.DataFrame(data)


def extract_probe_trajectories_table(
    alf_dir: Path, probe_dirs: list[Path]
) -> pd.DataFrame | None:
    metadata_by_label = _probe_metadata_by_label(alf_dir)
    rows: list[dict[str, Any]] = []

    for probe_dir in probe_dirs:
        label = probe_dir.name
        electrode_coords = _load_npy(probe_dir, "electrodeSites.mlapdv")
        electrode_local = _load_npy(probe_dir, "electrodeSites.localCoordinates")
        channel_coords = _load_npy(probe_dir, "channels.mlapdv")
        channel_local = _load_npy(probe_dir, "channels.localCoordinates")

        source = "electrodeSites.mlapdv" if electrode_coords is not None else None
        coords = electrode_coords
        local_coords = electrode_local
        if coords is None:
            coords = channel_coords
            local_coords = channel_local
            if coords is not None:
                source = "channels.mlapdv"

        start, end = _ordered_probe_sites(coords, local_coords)
        if coords is None and label not in metadata_by_label:
            continue

        row: dict[str, Any] = {"probe_label": label}
        meta = metadata_by_label.get(label, {})
        for key in ("model", "serial", "raw_file_name"):
            if key in meta:
                row[key] = meta[key]

        if coords is not None:
            coords_array = np.asarray(coords)
            row["trajectory_source"] = source
            row["site_count"] = int(len(coords_array))
            if start is not None and end is not None:
                row["start_ml_um"] = int(start[0])
                row["start_ap_um"] = int(start[1])
                row["start_dv_um"] = int(start[2])
                row["end_ml_um"] = int(end[0])
                row["end_ap_um"] = int(end[1])
                row["end_dv_um"] = int(end[2])
                row["track_extent_um"] = float(np.linalg.norm(end - start))

        rows.append(row)

    if not rows:
        return None
    return pd.DataFrame(rows)


def extract_session_tables(
    session_path: str | Path,
    *,
    output_dir: str | None = None,
    include_trials: bool = True,
    include_wheel: bool = True,
    include_spikes: bool = True,
    include_regions: bool = True,
    include_channels: bool = True,
    include_electrode_sites: bool = True,
    include_probe_trajectories: bool = True,
    probe_label: str | None = None,
    spike_limit: int | None = None,
) -> dict[str, Any]:
    """Extract session-level ALF tables into tabular files."""

    session = Path(session_path).expanduser()
    alf_dir = session / "alf"
    if not alf_dir.exists():
        raise FileNotFoundError(f"ALF directory not found for session: {session}")

    out_dir = _session_output_dir(output_dir, session)
    outputs: dict[str, Any] = {
        "session_path": str(session),
        "alf_path": str(alf_dir),
        "output_dir": str(out_dir),
        "tables": {},
        "notes": [],
    }

    if include_trials:
        try:
            trials = extract_trials_table(alf_dir)
            outputs["tables"]["trials"] = _write_table(trials, out_dir, "trials")
        except FileNotFoundError as exc:
            outputs["notes"].append(str(exc))

    if include_wheel:
        try:
            wheel = extract_wheel_samples_table(alf_dir)
            outputs["tables"]["wheel_samples"] = _write_table(
                wheel, out_dir, "wheel_samples"
            )
        except FileNotFoundError as exc:
            outputs["notes"].append(str(exc))

        wheel_moves = extract_wheel_moves_table(alf_dir)
        if wheel_moves is not None:
            outputs["tables"]["wheel_moves"] = _write_table(
                wheel_moves, out_dir, "wheel_moves"
            )

    probe_dirs = sorted(
        child
        for child in alf_dir.iterdir()
        if child.is_dir() and child.name.startswith("probe")
    )
    if probe_label:
        probe_dirs = [probe for probe in probe_dirs if probe.name == probe_label]

    outputs["probes"] = [probe.name for probe in probe_dirs]
    if probe_label and not probe_dirs:
        outputs["notes"].append(
            f"Requested probe not found in ALF directory: {probe_label}"
        )

    for probe_dir in probe_dirs:
        if include_spikes:
            try:
                spikes = extract_spikes_table(
                    probe_dir,
                    probe_label=probe_dir.name,
                    spike_limit=spike_limit,
                )
                outputs["tables"][f"spikes_{probe_dir.name}"] = _write_table(
                    spikes, out_dir, f"spikes_{probe_dir.name}"
                )
            except FileNotFoundError as exc:
                outputs["notes"].append(str(exc))
        if include_regions:
            try:
                regions = extract_regions_table(probe_dir, probe_label=probe_dir.name)
                outputs["tables"][f"regions_{probe_dir.name}"] = _write_table(
                    regions, out_dir, f"regions_{probe_dir.name}"
                )
            except FileNotFoundError as exc:
                outputs["notes"].append(str(exc))
        if include_channels:
            try:
                channels = extract_channels_table(probe_dir, probe_label=probe_dir.name)
                outputs["tables"][f"channels_{probe_dir.name}"] = _write_table(
                    channels, out_dir, f"channels_{probe_dir.name}"
                )
            except FileNotFoundError as exc:
                outputs["notes"].append(str(exc))
        if include_electrode_sites:
            try:
                electrode_sites = extract_electrode_sites_table(
                    probe_dir, probe_label=probe_dir.name
                )
                outputs["tables"][f"electrode_sites_{probe_dir.name}"] = _write_table(
                    electrode_sites, out_dir, f"electrode_sites_{probe_dir.name}"
                )
            except FileNotFoundError as exc:
                outputs["notes"].append(str(exc))

    if include_probe_trajectories:
        trajectories = extract_probe_trajectories_table(alf_dir, probe_dirs)
        if trajectories is not None:
            outputs["tables"]["probe_trajectories"] = _write_table(
                trajectories, out_dir, "probe_trajectories"
            )

    return outputs


__all__ = [
    "extract_session_tables",
    "extract_trials_table",
    "extract_wheel_samples_table",
    "extract_wheel_moves_table",
    "extract_spikes_table",
    "extract_regions_table",
    "extract_channels_table",
    "extract_electrode_sites_table",
    "extract_probe_trajectories_table",
]
