"""Repo-owned IBL tool wrappers.

These wrappers are intentionally conservative: they expose stable tool names
and return normalized dry-run style payloads without depending on the optional
IBL Python stack at import time.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from importlib.util import find_spec
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from brain_researcher.services.neurokg import query_service
from brain_researcher.services.tools.ibl_alf_extractor import extract_session_tables
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

_IBL_DEPENDENCY_MODULES = (
    "one.api",
    "brainbox.io.one",
    "iblatlas.regions",
    "iblrig",
    "iblsorter.sorting",
)
_KILOSORT_DEPENDENCY_MODULES = ("spikeinterface.full",)
_DEEPLABCUT_DEPENDENCY_MODULES = ("deeplabcut",)
_LIGHTNING_POSE_DEPENDENCY_MODULES = ("lightning_pose",)
_DEFAULT_IBL_DATASET_REF = "ds:manual:ibl_brainwide"
_IBL_BWM_AGGREGATE_FILES = ("trials.pqt", "clusters.pqt")
_SPIKEGLX_AP_BIN_GLOB = "*imec.ap*.cbin"
_SPIKEGLX_AP_META_GLOB = "*imec.ap*.meta"
_POSE_CAMERA_PRIORITY = ("leftCamera", "rightCamera", "bodyCamera")


def _sorted_child_dirs(path: Path) -> list[Path]:
    try:
        return sorted(child for child in path.iterdir() if child.is_dir())
    except Exception:
        return []


def _resolve_ibl_resources(dataset_ref: str | None) -> Any:
    ref = (dataset_ref or _DEFAULT_IBL_DATASET_REF).strip() or _DEFAULT_IBL_DATASET_REF
    return query_service.dataset_resources(
        ref,
        analysis_goal="generic",
        run_bids_validation=False,
        enforce_semantic_gate=False,
        check_source_access=False,
    )


def _resolve_ibl_data_root(local_path: str | None) -> Path | None:
    if not local_path:
        return None
    root = Path(local_path)
    if not root.exists():
        return None
    data_root = root / "data"
    if data_root.exists() and data_root.is_dir():
        return data_root
    return root


def _resolve_ibl_aggregate_release(local_path: str | None) -> Path | None:
    if not local_path:
        return None
    root = Path(local_path)
    if not root.exists():
        return None
    aggregate_root = root / "aggregates"
    if not aggregate_root.exists() or not aggregate_root.is_dir():
        return None
    releases = [
        child for child in _sorted_child_dirs(aggregate_root) if "IBL_et_al_BWM" in child.name
    ]
    if not releases:
        return None
    return releases[-1]


def _ibl_aggregate_summary(release_dir: Path) -> dict[str, Any]:
    aggregate_files = sorted(child.name for child in release_dir.iterdir() if child.is_file())
    required_files = {
        name: (release_dir / name).exists() for name in _IBL_BWM_AGGREGATE_FILES
    }
    return {
        "aggregate_release": release_dir.name,
        "aggregate_path": str(release_dir),
        "aggregate_files": aggregate_files,
        "required_files": required_files,
        "smoke_passed": all(required_files.values()),
    }


def _list_ibl_labs(data_root: Path, *, limit: int = 20) -> list[str]:
    labs: list[str] = []
    for child in _sorted_child_dirs(data_root):
        if child.name in {"resources", "registration"}:
            continue
        if (child / "Subjects").exists():
            labs.append(child.name)
        if len(labs) >= limit:
            break
    return labs


def _ibl_session_summary(
    session_path: Path,
    *,
    lab: str,
    subject: str,
    date: str,
    number: str,
) -> dict[str, Any]:
    alf_dir = session_path / "alf"
    raw_ephys_dir = session_path / "raw_ephys_data"
    raw_behavior_dir = session_path / "raw_behavior_data"
    raw_video_dir = session_path / "raw_video_data"
    probe_dirs = []
    if alf_dir.exists():
        probe_dirs = [
            child.name
            for child in _sorted_child_dirs(alf_dir)
            if child.name.startswith("probe")
        ][:8]

    return {
        "lab": lab,
        "subject": subject,
        "date": date,
        "number": number,
        "session_id": f"{lab}/{subject}/{date}/{number}",
        "session_path": str(session_path),
        "has_alf": alf_dir.exists(),
        "has_raw_ephys": raw_ephys_dir.exists(),
        "has_raw_behavior": raw_behavior_dir.exists(),
        "has_raw_video": raw_video_dir.exists(),
        "probe_labels": probe_dirs,
    }


def _discover_ibl_sessions(data_root: Path, *, limit: int = 5) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    for lab_dir in _sorted_child_dirs(data_root):
        subjects_root = lab_dir / "Subjects"
        if not subjects_root.exists():
            continue
        for subject_dir in _sorted_child_dirs(subjects_root):
            for date_dir in _sorted_child_dirs(subject_dir):
                for session_dir in _sorted_child_dirs(date_dir):
                    sessions.append(
                        _ibl_session_summary(
                            session_dir,
                            lab=lab_dir.name,
                            subject=subject_dir.name,
                            date=date_dir.name,
                            number=session_dir.name,
                        )
                    )
                    if len(sessions) >= limit:
                        return sessions
    return sessions


def _resolve_session_path(
    data_root: Path,
    *,
    session_id: str | None,
    subject_id: str | None,
) -> Path | None:
    if session_id:
        parts = [part for part in session_id.split("/") if part]
        if len(parts) == 4:
            candidate = (
                data_root / parts[0] / "Subjects" / parts[1] / parts[2] / parts[3]
            )
            if candidate.exists():
                return candidate
        elif len(parts) == 3:
            subject, date, number = parts
            for lab_dir in _sorted_child_dirs(data_root):
                candidate = lab_dir / "Subjects" / subject / date / number
                if candidate.exists():
                    return candidate

    if subject_id:
        for lab_dir in _sorted_child_dirs(data_root):
            subject_root = lab_dir / "Subjects" / subject_id
            if not subject_root.exists():
                continue
            for date_dir in _sorted_child_dirs(subject_root):
                for session_dir in _sorted_child_dirs(date_dir):
                    return session_dir
    return None


def _list_files(root: Path, *, limit: int = 20) -> list[str]:
    try:
        return sorted(str(path) for path in root.rglob("*") if path.is_file())[:limit]
    except Exception:
        return []


def _resolve_local_session_context(
    *,
    dataset_ref: str | None,
    session_id: str | None,
    subject_id: str | None,
    probe_label: str | None = None,
) -> dict[str, Any] | None:
    resources = _resolve_ibl_resources(dataset_ref)
    data_root = _resolve_ibl_data_root(getattr(resources, "local_path", None))
    if not data_root:
        return None

    session_path = _resolve_session_path(
        data_root,
        session_id=session_id,
        subject_id=subject_id,
    )
    if not session_path:
        return None

    parts = session_path.parts
    idx = parts.index("Subjects")
    session_summary = _ibl_session_summary(
        session_path,
        lab=parts[idx - 1],
        subject=parts[idx + 1],
        date=parts[idx + 2],
        number=parts[idx + 3],
    )
    raw_ephys_dir = session_path / "raw_ephys_data"
    raw_video_dir = session_path / "raw_video_data"
    probe_path = raw_ephys_dir / probe_label if probe_label else None

    return {
        "dataset_ref": dataset_ref or _DEFAULT_IBL_DATASET_REF,
        "resolved_dataset_id": getattr(resources, "resolved_dataset_id", None),
        "local_path": getattr(resources, "local_path", None),
        "session_path": str(session_path),
        "session_summary": session_summary,
        "raw_ephys_dir": str(raw_ephys_dir) if raw_ephys_dir.exists() else None,
        "raw_ephys_probe_dir": str(probe_path) if probe_path and probe_path.exists() else None,
        "raw_video_dir": str(raw_video_dir) if raw_video_dir.exists() else None,
        "video_files": _list_files(raw_video_dir, limit=12) if raw_video_dir.exists() else [],
    }


def _load_table(path: str | None) -> pd.DataFrame | None:
    if not path:
        return None
    table_path = Path(path).expanduser()
    if not table_path.exists():
        return None
    suffix = table_path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(table_path)
    if suffix in {".parquet", ".pqt"}:
        return pd.read_parquet(table_path)
    if suffix == ".json":
        payload = json.loads(table_path.read_text())
        if isinstance(payload, list):
            return pd.DataFrame(payload)
        if isinstance(payload, dict):
            return pd.DataFrame([payload])
    raise ValueError(f"Unsupported table format: {table_path}")


def _write_table_output(df: pd.DataFrame, output_dir: Path, stem: str) -> dict[str, Any]:
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


def _write_json_output(payload: dict[str, Any], output_dir: Path, stem: str) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{stem}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return {"path": str(path), "format": "json"}


def _write_npy_output(array: np.ndarray, output_dir: Path, stem: str) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{stem}.npy"
    np.save(path, array)
    return {
        "path": str(path),
        "format": "npy",
        "shape": [int(dim) for dim in array.shape],
        "dtype": str(array.dtype),
    }


def _infer_probe_label_from_dir(probe_dir: Path, probe_label: str | None) -> str:
    if probe_label:
        return probe_label
    if probe_dir.name.startswith("probe"):
        return probe_dir.name
    return "probe00"


def _resolve_probe_dir(data_dir: str | None, probe_label: str | None) -> Path | None:
    if not data_dir:
        return None
    root = Path(data_dir).expanduser()
    if not root.exists():
        return None
    if root.is_file():
        return root.parent
    if list(root.glob(_SPIKEGLX_AP_BIN_GLOB)) and list(root.glob(_SPIKEGLX_AP_META_GLOB)):
        return root
    if probe_label:
        candidate = root / probe_label
        if candidate.exists():
            return candidate
    candidates = [
        child
        for child in _sorted_child_dirs(root)
        if list(child.glob(_SPIKEGLX_AP_BIN_GLOB)) and list(child.glob(_SPIKEGLX_AP_META_GLOB))
    ]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _build_spikeglx_normalized_view(probe_dir: Path, output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    cbin_candidates = sorted(probe_dir.glob(_SPIKEGLX_AP_BIN_GLOB))
    meta_candidates = sorted(probe_dir.glob(_SPIKEGLX_AP_META_GLOB))
    ch_candidates = sorted(probe_dir.glob("*imec.ap*.ch"))
    if not cbin_candidates or not meta_candidates or not ch_candidates:
        raise FileNotFoundError(f"Missing AP cbin/meta/ch files under {probe_dir}")

    normalized_base = "_spikeglx_ephysData_g0_t0.imec.ap"
    cbin_path = output_dir / f"{normalized_base}.cbin"
    meta_path = output_dir / f"{normalized_base}.meta"
    ch_path = output_dir / f"{normalized_base}.ch"

    for path in (cbin_path, meta_path, ch_path):
        if path.exists() or path.is_symlink():
            path.unlink()

    cbin_path.symlink_to(cbin_candidates[0])
    meta_path.symlink_to(meta_candidates[0])
    ch_path.symlink_to(ch_candidates[0])
    return {
        "normalized_input_dir": str(output_dir),
        "normalized_cbin_path": str(cbin_path),
        "normalized_meta_path": str(meta_path),
        "normalized_ch_path": str(ch_path),
        "source_cbin_path": str(cbin_candidates[0]),
        "source_meta_path": str(meta_candidates[0]),
        "source_ch_path": str(ch_candidates[0]),
    }


def _load_spikeglx_recording(
    probe_dir: Path,
    *,
    normalized_dir: Path,
):
    from unittest.mock import patch

    import probeinterface
    import spikeinterface.full as si

    normalized = _build_spikeglx_normalized_view(probe_dir, normalized_dir)
    original_read_spikeglx = probeinterface.read_spikeglx

    def _patched_read_spikeglx(meta_file):
        probe = original_read_spikeglx(meta_file)
        if "probe_type" not in probe.annotations:
            model_name = str(probe.annotations.get("model_name", ""))
            part_number = str(probe.annotations.get("part_number", ""))
            if "NP1" in part_number or "1.0" in model_name:
                probe.annotate(probe_type=0)
            else:
                probe.annotate(probe_type=21)
        return probe

    with patch.object(probeinterface, "read_spikeglx", _patched_read_spikeglx):
        recording = si.read_cbin_ibl(
            cbin_file_path=Path(normalized["normalized_cbin_path"]),
            stream_name="ap",
        )
    if hasattr(recording, "_kwargs") and isinstance(recording._kwargs, dict):
        recording._kwargs["folder_path"] = normalized["normalized_input_dir"]
        recording._kwargs["cbin_file_path"] = normalized["normalized_cbin_path"]
    original_duration_s = float(recording.get_num_frames() / recording.get_sampling_frequency())
    return recording, normalized, original_duration_s


def _materialize_sorter_recording(recording: Any, *, output_dir: Path):
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    return recording.save(
        folder=output_dir,
        format="binary",
        overwrite=True,
        verbose=False,
        n_jobs=1,
        chunk_duration="1s",
        progress_bar=False,
    )


def _suggest_active_window_start(
    session_path: str | None,
    probe_label: str | None,
    max_duration_s: float | None,
    *,
    max_time_s: float | None = None,
) -> float | None:
    if not session_path or not probe_label or not max_duration_s or max_duration_s <= 0:
        return None
    probe_dir = Path(session_path) / "alf" / probe_label
    if not probe_dir.exists():
        return None
    spike_time_files = sorted(probe_dir.glob("spikes.times*.npy"))
    if not spike_time_files:
        return None
    spike_times = np.load(spike_time_files[0], allow_pickle=True)
    if len(spike_times) == 0:
        return None
    if max_time_s is not None:
        spike_times = np.asarray(spike_times, dtype=float)
        spike_times = spike_times[spike_times <= max_time_s]
        if len(spike_times) == 0:
            return None
    max_time = float(np.max(spike_times))
    bins = np.arange(0.0, max_time + max_duration_s, max_duration_s)
    if len(bins) < 2:
        return 0.0
    counts, edges = np.histogram(spike_times, bins=bins)
    if len(counts) == 0:
        return 0.0
    best_idx = int(np.argmax(counts))
    return float(edges[best_idx])


def _pick_pose_camera(video_path: str | None) -> str | None:
    if not video_path:
        return None
    lower = str(video_path).lower()
    for camera in _POSE_CAMERA_PRIORITY:
        if camera.lower() in lower:
            return camera
    return None


def _find_alf_pose_file(alf_dir: Path, prefix: str, extension: str) -> Path | None:
    ext = extension.lstrip(".")
    direct_patterns = (f"{prefix}.{ext}", f"{prefix}.*.{ext}")
    for pattern in direct_patterns:
        matches = sorted(alf_dir.glob(pattern))
        if matches:
            return matches[0]

    revision_dirs = sorted(
        child for child in alf_dir.iterdir() if child.is_dir() and child.name.startswith("#")
    )
    for revision_dir in reversed(revision_dirs):
        for pattern in direct_patterns:
            matches = sorted(revision_dir.glob(pattern))
            if matches:
                return matches[0]
    return None


def _resolve_precomputed_pose_files(
    session_path: Path,
    *,
    backend: str,
    video_path: str | None,
) -> dict[str, str] | None:
    alf_dir = session_path / "alf"
    if not alf_dir.exists():
        return None

    backend_token = "lightningPose" if backend == "lightning_pose" else "dlc"
    preferred_camera = _pick_pose_camera(video_path)
    search_order = (
        (preferred_camera,) + tuple(c for c in _POSE_CAMERA_PRIORITY if c != preferred_camera)
        if preferred_camera
        else _POSE_CAMERA_PRIORITY
    )

    for camera in search_order:
        prefix = f"_ibl_{camera}.{backend_token}"
        coord_path = _find_alf_pose_file(alf_dir, prefix, "pqt")
        if coord_path is None:
            coord_path = _find_alf_pose_file(alf_dir, prefix, "parquet")
        if coord_path is None and backend == "deeplabcut":
            coord_path = _find_alf_pose_file(alf_dir, prefix, "csv")
        if coord_path is None:
            continue
        times_path = _find_alf_pose_file(alf_dir, f"_ibl_{camera}.times", "npy")
        features_path = _find_alf_pose_file(alf_dir, f"_ibl_{camera}.features", "pqt")
        if features_path is None:
            features_path = _find_alf_pose_file(alf_dir, f"_ibl_{camera}.features", "parquet")
        roi_motion_path = _find_alf_pose_file(alf_dir, f"{camera}.ROIMotionEnergy", "npy")
        return {
            "camera": camera,
            "coord_path": str(coord_path),
            "times_path": str(times_path) if times_path else "",
            "features_path": str(features_path) if features_path else "",
            "roi_motion_path": str(roi_motion_path) if roi_motion_path else "",
        }
    return None


def _materialize_pose_tables(
    session_path: Path,
    *,
    backend: str,
    video_path: str | None,
    output_dir: Path,
) -> dict[str, Any] | None:
    pose_files = _resolve_precomputed_pose_files(
        session_path,
        backend=backend,
        video_path=video_path,
    )
    if pose_files is None:
        return None

    coord_df = pd.read_parquet(pose_files["coord_path"]).copy()
    coord_df.insert(0, "frame_index", np.arange(len(coord_df), dtype=int))
    coord_df.insert(1, "camera", pose_files["camera"])
    coord_df.insert(2, "backend", backend)
    if pose_files.get("times_path"):
        times = np.load(pose_files["times_path"], allow_pickle=True)
        if len(times) == len(coord_df):
            coord_df.insert(3, "time_s", np.asarray(times, dtype=float))

    metrics_df: pd.DataFrame
    if pose_files.get("features_path"):
        metrics_df = pd.read_parquet(pose_files["features_path"]).copy()
    else:
        likelihood_cols = [col for col in coord_df.columns if col.endswith("_likelihood")]
        summary = {
            "camera": pose_files["camera"],
            "backend": backend,
            "n_frames": int(len(coord_df)),
            "n_columns": int(len(coord_df.columns)),
        }
        if likelihood_cols:
            summary["mean_likelihood"] = float(
                coord_df[likelihood_cols].to_numpy(dtype=float).mean()
            )
        metrics_df = pd.DataFrame([summary])

    if pose_files.get("roi_motion_path"):
        roi_motion = np.load(pose_files["roi_motion_path"], allow_pickle=True)
        if len(roi_motion) == len(coord_df):
            coord_df["roi_motion_energy"] = np.asarray(roi_motion, dtype=float)

    coord_output = _write_table_output(
        coord_df,
        output_dir,
        f"{backend}_coords_{pose_files['camera']}",
    )
    metrics_output = _write_table_output(
        metrics_df,
        output_dir,
        f"{backend}_metrics_{pose_files['camera']}",
    )
    metadata_output = _write_json_output(
        {
            "backend": backend,
            "camera": pose_files["camera"],
            "source": "ibl_alf_precomputed",
            "source_coord_path": pose_files["coord_path"],
            "source_times_path": pose_files.get("times_path") or None,
            "source_features_path": pose_files.get("features_path") or None,
            "source_roi_motion_path": pose_files.get("roi_motion_path") or None,
            "video_path": video_path,
        },
        output_dir,
        f"{backend}_metadata_{pose_files['camera']}",
    )
    return {
        "coord_table": coord_output,
        "optical_metrics": metrics_output,
        "metadata": metadata_output,
        "camera": pose_files["camera"],
        "source": "ibl_alf_precomputed",
    }


def _assign_trials(
    timestamps: np.ndarray,
    interval_start: np.ndarray,
    interval_end: np.ndarray,
) -> np.ndarray:
    assigned = np.full(len(timestamps), -1, dtype=int)
    if len(interval_start) == 0 or len(timestamps) == 0:
        return assigned
    candidate = np.searchsorted(interval_start, timestamps, side="right") - 1
    valid = (
        (candidate >= 0)
        & (candidate < len(interval_end))
        & (timestamps >= interval_start[np.clip(candidate, 0, len(interval_start) - 1)])
        & (timestamps <= interval_end[np.clip(candidate, 0, len(interval_end) - 1)])
    )
    assigned[valid] = candidate[valid]
    return assigned


def _append_trial_membership(
    df: pd.DataFrame,
    *,
    time_column: str,
    trials: pd.DataFrame,
) -> pd.DataFrame:
    if time_column not in df.columns or "interval_start" not in trials.columns or "interval_end" not in trials.columns:
        return df
    interval_start = trials["interval_start"].to_numpy(dtype=float)
    interval_end = trials["interval_end"].to_numpy(dtype=float)
    times = df[time_column].to_numpy(dtype=float)
    trial_index = _assign_trials(times, interval_start, interval_end)
    out = df.copy()
    out["trial_index"] = trial_index
    valid = out["trial_index"] >= 0
    if valid.any():
        trial_lookup = trials.set_index("trial_index")
        for column in (
            "choice",
            "contrastLeft",
            "contrastRight",
            "feedbackType",
            "probabilityLeft",
            "stimOn_times",
            "response_times",
            "feedback_times",
            "interval_start",
            "interval_end",
        ):
            if column in trial_lookup.columns:
                out.loc[valid, column] = (
                    out.loc[valid, "trial_index"].map(trial_lookup[column]).to_numpy()
                )
        if "stimOn_times" in out.columns:
            out["time_from_stimOn_s"] = out[time_column] - out["stimOn_times"]
        if "interval_start" in out.columns:
            out["time_from_trial_start_s"] = out[time_column] - out["interval_start"]
    return out


def _session_summary_from_path(session_path: Path) -> dict[str, Any]:
    parts = session_path.parts
    idx = parts.index("Subjects")
    return _ibl_session_summary(
        session_path,
        lab=parts[idx - 1],
        subject=parts[idx + 1],
        date=parts[idx + 2],
        number=parts[idx + 3],
    )


def _resolve_subject_session_paths(data_root: Path, subject_id: str) -> list[Path]:
    paths: list[Path] = []
    for lab_dir in _sorted_child_dirs(data_root):
        subject_root = lab_dir / "Subjects" / subject_id
        if not subject_root.exists():
            continue
        for date_dir in _sorted_child_dirs(subject_root):
            for session_dir in _sorted_child_dirs(date_dir):
                paths.append(session_dir)
    return paths


def _resolve_requested_session_paths(
    data_root: Path,
    *,
    session_ids: list[str],
    session_id: str | None,
    subject_id: str | None,
) -> list[Path]:
    requested = [item for item in session_ids if item]
    if session_id:
        requested.append(session_id)

    seen: set[str] = set()
    resolved: list[Path] = []
    for requested_id in requested:
        path = _resolve_session_path(data_root, session_id=requested_id, subject_id=None)
        if path is None:
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        resolved.append(path)

    if resolved:
        return resolved
    if subject_id:
        for path in _resolve_subject_session_paths(data_root, subject_id):
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            resolved.append(path)
    return resolved


def _safe_session_stem(session_id: str) -> str:
    return session_id.replace("/", "__")


def _with_trial_index(df: pd.DataFrame) -> pd.DataFrame:
    if "trial_index" in df.columns:
        return df
    out = df.copy()
    out.insert(0, "trial_index", np.arange(len(out), dtype=int))
    return out


def _prepare_ibl_trial_metadata(df: pd.DataFrame) -> pd.DataFrame:
    out = _with_trial_index(df).copy()
    if "contrastLeft" in out.columns and "contrastRight" in out.columns:
        left = pd.to_numeric(out["contrastLeft"], errors="coerce")
        right = pd.to_numeric(out["contrastRight"], errors="coerce")
        out["signed_contrast"] = right.fillna(0.0) - left.fillna(0.0)
        out["stimulus_side"] = np.select(
            [right > left, left > right],
            [1, -1],
            default=0,
        ).astype("int64")
        out["zero_contrast"] = (
            left.fillna(0.0).eq(0.0) & right.fillna(0.0).eq(0.0)
        )
        out["max_contrast"] = np.maximum(
            left.abs().fillna(0.0),
            right.abs().fillna(0.0),
        )
    return out


def _fallback_trials_from_spikes(spikes_df: pd.DataFrame) -> pd.DataFrame | None:
    if "trial_index" not in spikes_df.columns:
        return None
    candidate_columns = [
        "trial_index",
        "choice",
        "contrastLeft",
        "contrastRight",
        "feedbackType",
        "probabilityLeft",
        "stimOn_times",
        "response_times",
        "feedback_times",
        "interval_start",
        "interval_end",
        "signed_contrast",
        "stimulus_side",
        "zero_contrast",
        "max_contrast",
    ]
    available = [column for column in candidate_columns if column in spikes_df.columns]
    if len(available) == 1:
        return None
    return (
        spikes_df.loc[spikes_df["trial_index"] >= 0, available]
        .drop_duplicates(subset=["trial_index"])
        .sort_values("trial_index")
        .reset_index(drop=True)
    )


def _resolve_label_values(df: pd.DataFrame, label_field: str) -> pd.Series:
    if label_field in df.columns:
        return df[label_field]
    raise KeyError(f"Unsupported IBL label_field: {label_field}")


def _encode_label_array(values: pd.Series, *, label_field: str) -> tuple[np.ndarray, dict[str, Any]]:
    observed = values.dropna()
    if observed.empty:
        raise ValueError(f"No valid labels found for {label_field}")

    numeric = pd.to_numeric(observed, errors="coerce")
    numeric_fraction = float(numeric.notna().mean()) if len(observed) else 0.0
    if numeric_fraction == 1.0 and numeric.nunique(dropna=True) > 10:
        array = numeric.to_numpy(dtype=np.float32)
        return array, {
            "label_field": label_field,
            "label_type": "continuous",
            "unique_count": int(pd.Series(array).nunique(dropna=True)),
        }

    if numeric_fraction == 1.0:
        ordered_values = sorted(
            value.item() if isinstance(value, np.generic) else value
            for value in numeric.unique().tolist()
        )
        mapping = {value: index for index, value in enumerate(ordered_values)}
        encoded = numeric.map(mapping).to_numpy(dtype=np.int64)
    else:
        normalized = observed.astype(str)
        ordered_values = sorted(normalized.unique().tolist())
        mapping = {value: index for index, value in enumerate(ordered_values)}
        encoded = normalized.map(mapping).to_numpy(dtype=np.int64)

    return encoded, {
        "label_field": label_field,
        "label_type": "categorical",
        "mapping": [
            {"code": int(index), "value": value}
            for index, value in enumerate(ordered_values)
        ],
    }


def _encode_group_array(values: pd.Series, *, group_by: str) -> tuple[np.ndarray, dict[str, Any]]:
    observed = values.fillna("unknown").astype(str)
    ordered_values = sorted(observed.unique().tolist())
    mapping = {value: index for index, value in enumerate(ordered_values)}
    encoded = observed.map(mapping).to_numpy(dtype=np.int64)
    return encoded, {
        "group_by": group_by,
        "mapping": [
            {"code": int(index), "value": value}
            for index, value in enumerate(ordered_values)
        ],
    }


def _dependency_status(modules: tuple[str, ...] | None = None) -> dict[str, bool]:
    """Report whether optional tool dependencies are importable."""
    status: dict[str, bool] = {}
    for module in modules or _IBL_DEPENDENCY_MODULES:
        try:
            status[module] = find_spec(module) is not None
        except Exception:
            status[module] = False
    return status


def _dependency_summary(modules: tuple[str, ...] | None = None) -> dict[str, Any]:
    active_modules = modules or _IBL_DEPENDENCY_MODULES
    status = _dependency_status(active_modules)
    return {
        "required_modules": list(active_modules),
        "available_modules": [name for name, ok in status.items() if ok],
        "missing_modules": [name for name, ok in status.items() if not ok],
        "all_available": all(status.values()),
    }


class _IBLBaseArgs(BaseModel):
    dry_run: bool = Field(
        default=True,
        description="Return a normalized planning payload instead of attempting live IBL execution.",
    )
    allow_missing_dependencies: bool = Field(
        default=True,
        description="Keep returning a success payload when optional IBL packages are unavailable.",
    )


class IBLOneArgs(_IBLBaseArgs):
    dataset_ref: str | None = Field(
        default=None,
        description="IBL dataset reference or alias, for example ds:manual:ibl_brainwide.",
    )
    query: str | None = Field(
        default=None,
        description="Optional search/query string to narrow the dataset or session scope.",
    )
    limit: int = Field(default=25, ge=1, le=500, description="Maximum results to plan for.")


class IBLBrainboxSessionEphysArgs(_IBLBaseArgs):
    session_id: str | None = Field(default=None, description="IBL session identifier.")
    subject_id: str | None = Field(default=None, description="IBL subject identifier.")
    dataset_ref: str | None = Field(default=None, description="Dataset reference for the session.")
    probe_label: str | None = Field(default=None, description="Optional probe label.")
    load_trials: bool = Field(default=True, description="Whether trial tables should be planned.")
    load_wheel: bool = Field(default=True, description="Whether wheel tables should be extracted.")
    load_spikes: bool = Field(default=True, description="Whether spike tables should be planned.")
    load_regions: bool = Field(
        default=True, description="Whether cluster-region tables should be extracted."
    )
    load_channels: bool = Field(
        default=True, description="Whether channel-coordinate tables should be extracted."
    )
    load_electrode_sites: bool = Field(
        default=True, description="Whether electrode-site tables should be extracted."
    )
    load_probe_trajectories: bool = Field(
        default=True,
        description="Whether derived probe-trajectory summary tables should be extracted.",
    )
    output_dir: str | None = Field(
        default=None,
        description="Optional output directory for extracted ALF tables.",
    )
    spike_limit: int | None = Field(
        default=None,
        ge=1,
        description="Optional row limit to cap extracted spikes per probe.",
    )


class IBLAtlasRegionMappingArgs(_IBLBaseArgs):
    atlas_name: str = Field(default="AllenCCFv3", description="Atlas identifier to map against.")
    coordinates: list[str] = Field(
        default_factory=list,
        description="Optional coordinate strings or identifiers to map.",
    )


class IBLRigTaskLayerArgs(_IBLBaseArgs):
    task_name: str = Field(
        default="visual decision-making",
        description="Task name to stage or inspect.",
    )
    subject_id: str | None = Field(default=None, description="Optional subject identifier.")
    n_trials: int | None = Field(
        default=None,
        ge=1,
        description="Optional trial count for planning or QC summaries.",
    )


class IBLSpikeSorterArgs(_IBLBaseArgs):
    sorter: str = Field(default="ibl-sorter", description="Sorter name to plan for.")
    session_id: str | None = Field(default=None, description="Optional session identifier.")
    probe_label: str | None = Field(default=None, description="Optional probe label.")


class IBLKilosortArgs(_IBLBaseArgs):
    data_dir: str | None = Field(
        default=None,
        description="Raw electrophysiology directory or probe folder for Kilosort input.",
    )
    dataset_ref: str | None = Field(default=None, description="Optional IBL dataset reference.")
    session_id: str | None = Field(default=None, description="Optional IBL session identifier.")
    subject_id: str | None = Field(default=None, description="Optional subject identifier.")
    probe_label: str | None = Field(default=None, description="Optional probe label.")
    sorter: str = Field(default="kilosort4", description="Spike sorting backend.")
    output_dir: str | None = Field(default=None, description="Optional output directory.")
    max_duration_s: float | None = Field(
        default=None,
        gt=0,
        description="Optional duration cap for smoke-test or preview Kilosort runs.",
    )


class IBLPoseToolArgs(_IBLBaseArgs):
    video_path: str | None = Field(default=None, description="Input video file or directory.")
    dataset_ref: str | None = Field(default=None, description="Optional IBL dataset reference.")
    session_id: str | None = Field(default=None, description="Optional IBL session identifier.")
    subject_id: str | None = Field(default=None, description="Optional subject identifier.")
    output_dir: str | None = Field(default=None, description="Optional output directory.")
    keypoint_schema: list[str] = Field(
        default_factory=list,
        description="Optional keypoint names or schema hints.",
    )


class IBLSpikeBehaviorAlignmentArgs(_IBLBaseArgs):
    spike_times_path: str | None = Field(default=None, description="Spike-times table path.")
    events_path: str | None = Field(default=None, description="Behavior/events table path.")
    pose_coordinates_path: str | None = Field(
        default=None,
        description="Optional pose/keypoint coordinate table path.",
    )
    dataset_ref: str | None = Field(default=None, description="Optional IBL dataset reference.")
    session_id: str | None = Field(default=None, description="Optional IBL session identifier.")
    subject_id: str | None = Field(default=None, description="Optional subject identifier.")
    probe_label: str | None = Field(default=None, description="Optional probe label.")
    output_dir: str | None = Field(default=None, description="Optional output directory.")
    spike_limit: int | None = Field(
        default=None,
        ge=1,
        description="Optional cap when materializing spike tables from mounted ALF data.",
    )
    alignment_anchor: str = Field(
        default="trial_intervals",
        description="Primary anchor used for spike/behavior alignment.",
    )


class IBLNeuropixelsWorkflowArgs(_IBLBaseArgs):
    raw_ephys_dir: str | None = Field(
        default=None,
        description="Raw electrophysiology directory override for Kilosort.",
    )
    video_path: str | None = Field(default=None, description="Optional video input path.")
    behavior_events_path: str | None = Field(
        default=None,
        description="Optional behavior/events table path.",
    )
    dataset_ref: str | None = Field(default=None, description="Optional IBL dataset reference.")
    session_id: str | None = Field(default=None, description="Optional IBL session identifier.")
    subject_id: str | None = Field(default=None, description="Optional subject identifier.")
    probe_label: str | None = Field(default=None, description="Optional probe label.")
    pose_backend: str = Field(
        default="lightning_pose",
        description="Pose backend: lightning_pose or deeplabcut.",
    )
    include_pose: bool = Field(
        default=True,
        description="Whether the workflow should include a pose-tracking stage.",
    )
    output_dir: str | None = Field(default=None, description="Optional output directory root.")
    spike_limit: int | None = Field(
        default=None,
        ge=1,
        description="Optional cap when materializing spike tables for alignment planning.",
    )
    max_duration_s: float | None = Field(
        default=None,
        gt=0,
        description="Optional duration cap passed through to Kilosort during workflow execution.",
    )


class IBLDecodingDatasetArgs(_IBLBaseArgs):
    spike_times_path: str | None = Field(
        default=None,
        description="Optional spike table path, for example spike_times.parquet or aligned_spikes.parquet.",
    )
    trials_path: str | None = Field(
        default=None,
        description="Optional trials table path.",
    )
    trial_features_path: str | None = Field(
        default=None,
        description="Optional trial-features table path used as a trials surrogate or metadata sidecar.",
    )
    regions_path: str | None = Field(
        default=None,
        description="Optional region lookup table path, typically regions_<probe>.parquet.",
    )
    dataset_ref: str | None = Field(default=None, description="Optional IBL dataset reference.")
    session_id: str | None = Field(default=None, description="Optional IBL session identifier.")
    session_ids: list[str] = Field(
        default_factory=list,
        description="Optional list of IBL session identifiers for multi-session builders.",
    )
    subject_id: str | None = Field(default=None, description="Optional IBL subject identifier.")
    probe_label: str | None = Field(default=None, description="Optional probe label.")
    label_field: str = Field(
        default="choice",
        description="Label field for y, for example choice, feedbackType, stimulus_side, or signed_contrast.",
    )
    feature_level: str = Field(
        default="unit",
        description="Feature aggregation level: unit or region.",
    )
    group_by: str = Field(
        default="session",
        description="Grouping field for groups.npy: session or subject.",
    )
    anchor_field: str = Field(
        default="stimOn_times",
        description="Trial anchor used to window spikes before feature aggregation.",
    )
    window_start_s: float = Field(
        default=0.0,
        description="Window start in seconds relative to the chosen anchor.",
    )
    window_end_s: float = Field(
        default=0.2,
        description="Window end in seconds relative to the chosen anchor.",
    )
    min_feature_count: int = Field(
        default=1,
        ge=1,
        description="Minimum total spike count required to keep a feature column.",
    )
    output_dir: str | None = Field(default=None, description="Optional output directory.")
    spike_limit: int | None = Field(
        default=None,
        ge=1,
        description="Optional cap when materializing spike tables from mounted ALF data.",
    )


class _IBLToolBase(NeuroToolWrapper):
    """Common behavior for the repo-owned IBL wrappers."""

    execution_backend = "python"
    tool_id: str = ""
    args_model: type[BaseModel] = _IBLBaseArgs
    dependency_modules: tuple[str, ...] = ()

    def get_tool_name(self) -> str:
        return self.tool_id

    def get_tool_description(self) -> str:
        deps = ", ".join(self.dependency_modules) if self.dependency_modules else "none"
        return (
            f"Repo-owned IBL wrapper for {self.tool_id}. "
            f"Dependency-aware, dry-run by default, optional dependencies: {deps}."
        )

    def get_args_schema(self):
        return self.args_model

    def _wrap_result(
        self,
        *,
        args: BaseModel,
        outputs: dict[str, Any],
        mode_override: str | None = None,
        dependency_mode_override: str | None = None,
        ignore_dependency_gate: bool = False,
    ) -> ToolResult:
        dependency_info = _dependency_summary(self.dependency_modules)
        requested_mode = mode_override or (
            "dry_run" if getattr(args, "dry_run", True) else "configured"
        )
        allow_missing = bool(getattr(args, "allow_missing_dependencies", True))
        is_dry_run = bool(getattr(args, "dry_run", True))
        if dependency_mode_override:
            dependency_mode = dependency_mode_override
        elif dependency_info["all_available"]:
            dependency_mode = "available"
        elif allow_missing or is_dry_run:
            dependency_mode = "fallback"
        else:
            dependency_mode = "missing"

        if dependency_mode == "missing" and not ignore_dependency_gate:
            return ToolResult(
                status="error",
                error="missing_optional_dependencies",
                data={
                    "outputs": outputs,
                    "summary": {
                        "tool_id": self.tool_id,
                        "mode": requested_mode,
                        "dependency_mode": dependency_mode,
                        "dependency_summary": dependency_info,
                    },
                },
            )

        return ToolResult(
            status="success",
            data={
                "outputs": outputs,
                "summary": {
                    "tool_id": self.tool_id,
                    "mode": requested_mode,
                    "dependency_mode": dependency_mode,
                    "dependency_summary": dependency_info,
                },
            },
        )


class IBLOneTool(_IBLToolBase):
    tool_id = "ibl_one"
    args_model = IBLOneArgs
    dependency_modules = ("one.api",)

    def _run(
        self,
        dataset_ref: str | None = None,
        query: str | None = None,
        limit: int = 25,
        dry_run: bool = True,
        allow_missing_dependencies: bool = True,
        **kwargs,
    ) -> ToolResult:
        args = IBLOneArgs(
            dataset_ref=dataset_ref,
            query=query,
            limit=limit,
            dry_run=dry_run,
            allow_missing_dependencies=allow_missing_dependencies,
        )
        if not args.dry_run:
            resources = _resolve_ibl_resources(args.dataset_ref)
            aggregate_release = _resolve_ibl_aggregate_release(
                getattr(resources, "local_path", None)
            )
            if aggregate_release:
                outputs = {
                    "dataset_ref": args.dataset_ref or _DEFAULT_IBL_DATASET_REF,
                    "resolved_dataset_id": getattr(resources, "resolved_dataset_id", None),
                    "local_path": getattr(resources, "local_path", None),
                    "mount_status": dict(getattr(resources, "mount_status", {}) or {}),
                    "aggregate_summary": _ibl_aggregate_summary(aggregate_release),
                }
                return self._wrap_result(
                    args=args,
                    outputs=outputs,
                    mode_override="local_mount",
                    dependency_mode_override="local_mount",
                    ignore_dependency_gate=True,
                )
            data_root = _resolve_ibl_data_root(getattr(resources, "local_path", None))
            if data_root:
                sample_sessions = _discover_ibl_sessions(data_root, limit=min(args.limit, 5))
                labs = _list_ibl_labs(data_root)
                outputs = {
                    "dataset_ref": args.dataset_ref or _DEFAULT_IBL_DATASET_REF,
                    "resolved_dataset_id": getattr(resources, "resolved_dataset_id", None),
                    "local_path": getattr(resources, "local_path", None),
                    "data_root": str(data_root),
                    "mount_status": dict(getattr(resources, "mount_status", {}) or {}),
                    "labs_count": len(labs),
                    "labs_sample": labs[:10],
                    "sample_sessions": sample_sessions,
                }
                return self._wrap_result(
                    args=args,
                    outputs=outputs,
                    mode_override="local_mount",
                    dependency_mode_override="local_mount",
                    ignore_dependency_gate=True,
                )
        outputs = {
            "dataset_ref": args.dataset_ref,
            "query": args.query,
            "limit": args.limit,
            "planned_resources": ["path_list", "metadata"],
        }
        return self._wrap_result(args=args, outputs=outputs)


class IBLBrainboxSessionEphysTool(_IBLToolBase):
    tool_id = "ibl_brainbox_session_ephys"
    args_model = IBLBrainboxSessionEphysArgs
    dependency_modules = ("brainbox.io.one",)

    def _run(
        self,
        session_id: str | None = None,
        subject_id: str | None = None,
        dataset_ref: str | None = None,
        probe_label: str | None = None,
        load_trials: bool = True,
        load_wheel: bool = True,
        load_spikes: bool = True,
        load_regions: bool = True,
        load_channels: bool = True,
        load_electrode_sites: bool = True,
        load_probe_trajectories: bool = True,
        output_dir: str | None = None,
        spike_limit: int | None = None,
        dry_run: bool = True,
        allow_missing_dependencies: bool = True,
        **kwargs,
    ) -> ToolResult:
        args = IBLBrainboxSessionEphysArgs(
            session_id=session_id,
            subject_id=subject_id,
            dataset_ref=dataset_ref,
            probe_label=probe_label,
            load_trials=load_trials,
            load_wheel=load_wheel,
            load_spikes=load_spikes,
            load_regions=load_regions,
            load_channels=load_channels,
            load_electrode_sites=load_electrode_sites,
            load_probe_trajectories=load_probe_trajectories,
            output_dir=output_dir,
            spike_limit=spike_limit,
            dry_run=dry_run,
            allow_missing_dependencies=allow_missing_dependencies,
        )
        if not args.dry_run:
            resources = _resolve_ibl_resources(args.dataset_ref)
            data_root = _resolve_ibl_data_root(getattr(resources, "local_path", None))
            if data_root:
                session_path = _resolve_session_path(
                    data_root,
                    session_id=args.session_id,
                    subject_id=args.subject_id,
                )
                if session_path:
                    parts = session_path.parts
                    idx = parts.index("Subjects")
                    session_summary = _ibl_session_summary(
                        session_path,
                        lab=parts[idx - 1],
                        subject=parts[idx + 1],
                        date=parts[idx + 2],
                        number=parts[idx + 3],
                    )
                    if args.probe_label:
                        session_summary["requested_probe_present"] = (
                            args.probe_label in session_summary["probe_labels"]
                        )
                    try:
                        extracted = extract_session_tables(
                            session_path,
                            output_dir=args.output_dir,
                            include_trials=args.load_trials,
                            include_wheel=args.load_wheel,
                            include_spikes=args.load_spikes,
                            include_regions=args.load_regions,
                            include_channels=args.load_channels,
                            include_electrode_sites=args.load_electrode_sites,
                            include_probe_trajectories=args.load_probe_trajectories,
                            probe_label=args.probe_label,
                            spike_limit=args.spike_limit,
                        )
                    except FileNotFoundError as exc:
                        extracted = {
                            "output_dir": str(Path(args.output_dir).expanduser())
                            if args.output_dir
                            else None,
                            "alf_path": str(session_path / "alf"),
                            "probes": session_summary["probe_labels"],
                            "notes": [str(exc)],
                            "tables": {},
                        }
                    outputs = {
                        "session_id": session_summary["session_id"],
                        "subject_id": session_summary["subject"],
                        "dataset_ref": args.dataset_ref or _DEFAULT_IBL_DATASET_REF,
                        "probe_label": args.probe_label,
                        "requested_tables": {
                            "trials": args.load_trials,
                            "wheel": args.load_wheel,
                            "spikes": args.load_spikes,
                            "regions": args.load_regions,
                            "channels": args.load_channels,
                            "electrode_sites": args.load_electrode_sites,
                            "probe_trajectories": args.load_probe_trajectories,
                        },
                        "session_summary": session_summary,
                        "output_dir": extracted["output_dir"],
                        "alf_path": extracted["alf_path"],
                        "probes": extracted["probes"],
                        "notes": extracted["notes"],
                        "extracted_tables": extracted["tables"],
                    }
                    return self._wrap_result(
                        args=args,
                        outputs=outputs,
                        mode_override="local_mount",
                        dependency_mode_override="local_mount",
                        ignore_dependency_gate=True,
                    )
        outputs = {
            "session_id": args.session_id,
            "subject_id": args.subject_id,
            "dataset_ref": args.dataset_ref,
            "probe_label": args.probe_label,
            "requested_tables": {
                "trials": args.load_trials,
                "wheel": args.load_wheel,
                "spikes": args.load_spikes,
                "regions": args.load_regions,
                "channels": args.load_channels,
                "electrode_sites": args.load_electrode_sites,
                "probe_trajectories": args.load_probe_trajectories,
            },
            "output_dir": args.output_dir,
            "spike_limit": args.spike_limit,
        }
        return self._wrap_result(args=args, outputs=outputs)


class IBLAtlasRegionMappingTool(_IBLToolBase):
    tool_id = "ibl_atlas_region_mapping"
    args_model = IBLAtlasRegionMappingArgs
    dependency_modules = ("iblatlas.regions",)

    def _run(
        self,
        atlas_name: str = "AllenCCFv3",
        coordinates: list[str] | None = None,
        dry_run: bool = True,
        allow_missing_dependencies: bool = True,
        **kwargs,
    ) -> ToolResult:
        args = IBLAtlasRegionMappingArgs(
            atlas_name=atlas_name,
            coordinates=list(coordinates or []),
            dry_run=dry_run,
            allow_missing_dependencies=allow_missing_dependencies,
        )
        outputs = {
            "atlas_name": args.atlas_name,
            "coordinate_count": len(args.coordinates),
            "aligned_space": "AllenCCFv3",
        }
        return self._wrap_result(args=args, outputs=outputs)


class IBLRigTaskLayerTool(_IBLToolBase):
    tool_id = "ibl_rig_task_layer"
    args_model = IBLRigTaskLayerArgs
    dependency_modules = ("iblrig",)

    def _run(
        self,
        task_name: str = "visual decision-making",
        subject_id: str | None = None,
        n_trials: int | None = None,
        dry_run: bool = True,
        allow_missing_dependencies: bool = True,
        **kwargs,
    ) -> ToolResult:
        args = IBLRigTaskLayerArgs(
            task_name=task_name,
            subject_id=subject_id,
            n_trials=n_trials,
            dry_run=dry_run,
            allow_missing_dependencies=allow_missing_dependencies,
        )
        outputs = {
            "task_name": args.task_name,
            "subject_id": args.subject_id,
            "n_trials": args.n_trials,
            "planned_tables": ["events_tsv", "nwb_summary", "metadata"],
        }
        return self._wrap_result(args=args, outputs=outputs)


class IBLSpikeSorterTool(_IBLToolBase):
    tool_id = "ibl_sorter"
    args_model = IBLSpikeSorterArgs
    dependency_modules = ("iblsorter.sorting",)

    def _run(
        self,
        sorter: str = "ibl-sorter",
        session_id: str | None = None,
        probe_label: str | None = None,
        dry_run: bool = True,
        allow_missing_dependencies: bool = True,
        **kwargs,
    ) -> ToolResult:
        args = IBLSpikeSorterArgs(
            sorter=sorter,
            session_id=session_id,
            probe_label=probe_label,
            dry_run=dry_run,
            allow_missing_dependencies=allow_missing_dependencies,
        )
        outputs = {
            "sorter": args.sorter,
            "session_id": args.session_id,
            "probe_label": args.probe_label,
            "planned_outputs": ["spike_times", "qc_report", "features_table"],
        }
        return self._wrap_result(args=args, outputs=outputs)


class IBLKilosortTool(_IBLToolBase):
    tool_id = "ibl_kilosort"
    args_model = IBLKilosortArgs
    dependency_modules = _KILOSORT_DEPENDENCY_MODULES

    def _run(
        self,
        data_dir: str | None = None,
        dataset_ref: str | None = None,
        session_id: str | None = None,
        subject_id: str | None = None,
        probe_label: str | None = None,
        sorter: str = "kilosort4",
        output_dir: str | None = None,
        max_duration_s: float | None = None,
        dry_run: bool = True,
        allow_missing_dependencies: bool = True,
        **kwargs,
    ) -> ToolResult:
        args = IBLKilosortArgs(
            data_dir=data_dir,
            dataset_ref=dataset_ref,
            session_id=session_id,
            subject_id=subject_id,
            probe_label=probe_label,
            sorter=sorter,
            output_dir=output_dir,
            max_duration_s=max_duration_s,
            dry_run=dry_run,
            allow_missing_dependencies=allow_missing_dependencies,
        )

        local_context = None
        resolved_data_dir = args.data_dir
        resolved_probe_label = args.probe_label
        if not args.dry_run:
            local_context = _resolve_local_session_context(
                dataset_ref=args.dataset_ref,
                session_id=args.session_id,
                subject_id=args.subject_id,
                probe_label=args.probe_label,
            )
            if local_context:
                resolved_data_dir = (
                    local_context.get("raw_ephys_probe_dir")
                    or local_context.get("raw_ephys_dir")
                    or resolved_data_dir
                )
                resolved_probe_label = (
                    args.probe_label
                    or (
                        Path(local_context["raw_ephys_probe_dir"]).name
                        if local_context.get("raw_ephys_probe_dir")
                        else None
                    )
                )

        planned_command = None
        if resolved_data_dir:
            planned_command = ["spike_sort", resolved_data_dir, "--method", args.sorter]

        outputs = {
            "sorter": args.sorter,
            "data_dir": resolved_data_dir,
            "session_id": args.session_id,
            "subject_id": args.subject_id,
            "probe_label": resolved_probe_label,
            "output_dir": args.output_dir,
            "max_duration_s": args.max_duration_s,
            "planned_command": planned_command,
            "planned_outputs": ["spike_times", "qc_report", "features_table", "metadata"],
        }
        if args.dry_run:
            if local_context:
                outputs["local_session_context"] = local_context
                return self._wrap_result(
                    args=args,
                    outputs=outputs,
                    mode_override="local_mount",
                    dependency_mode_override="local_mount",
                    ignore_dependency_gate=True,
                )
            return self._wrap_result(args=args, outputs=outputs)

        probe_dir = _resolve_probe_dir(resolved_data_dir, resolved_probe_label)
        if probe_dir is None:
            if local_context:
                outputs["local_session_context"] = local_context
                return self._wrap_result(
                    args=args,
                    outputs=outputs,
                    mode_override="local_mount",
                    dependency_mode_override="local_mount",
                    ignore_dependency_gate=True,
                )
            return self._wrap_result(args=args, outputs=outputs)

        output_root = (
            Path(args.output_dir).expanduser()
            if args.output_dir
            else Path(tempfile.mkdtemp(prefix="ibl_kilosort_"))
        )
        output_root.mkdir(parents=True, exist_ok=True)
        sorter_output = output_root / "sorter_output"
        sorter_recording_dir = output_root / "sorter_recording"
        normalized_dir = output_root / "normalized_input"

        try:
            import spikeinterface.full as si
            import torch

            recording, normalized_inputs, original_duration_s = _load_spikeglx_recording(
                probe_dir,
                normalized_dir=normalized_dir,
            )
            start_time_s = _suggest_active_window_start(
                local_context["session_path"] if local_context else None,
                _infer_probe_label_from_dir(probe_dir, resolved_probe_label),
                args.max_duration_s,
                max_time_s=original_duration_s,
            )
            if args.max_duration_s and args.max_duration_s > 0:
                max_start_time = max(0.0, original_duration_s - args.max_duration_s)
                clipped_start_s = min(start_time_s or 0.0, max_start_time)
                start_frame = int(recording.get_sampling_frequency() * clipped_start_s)
                end_frame = min(
                    recording.get_num_frames(),
                    start_frame + int(recording.get_sampling_frequency() * args.max_duration_s),
                )
                recording = recording.frame_slice(start_frame=start_frame, end_frame=end_frame)
                start_time_s = clipped_start_s
            executed_duration_s = float(
                recording.get_num_frames() / recording.get_sampling_frequency()
            )
            sorter_recording = _materialize_sorter_recording(
                recording,
                output_dir=sorter_recording_dir,
            )

            sorter_params = si.get_default_sorter_params(args.sorter)
            sorter_params["torch_device"] = "cuda" if torch.cuda.is_available() else "cpu"
            smoke_mode = bool(args.max_duration_s and args.max_duration_s <= 120)
            if smoke_mode:
                sorter_params.update(
                    {
                        "Th_universal": min(float(sorter_params["Th_universal"]), 6.0),
                        "Th_learned": min(float(sorter_params["Th_learned"]), 6.0),
                        "n_pcs": min(int(sorter_params["n_pcs"]), 3),
                    }
                )

            if sorter_output.exists():
                shutil.rmtree(sorter_output)
            sorting = si.run_sorter(
                args.sorter,
                recording=sorter_recording,
                folder=str(sorter_output),
                remove_existing_folder=True,
                delete_output_folder=False,
                verbose=False,
                raise_error=True,
                docker_image=False,
                singularity_image=False,
                with_output=True,
                **sorter_params,
            )

            spike_vector = sorting.to_spike_vector()
            spike_df = pd.DataFrame(
                {
                    "spike_index": np.arange(len(spike_vector), dtype=int),
                    "sample_index": spike_vector["sample_index"].astype(np.int64),
                    "segment_index": spike_vector["segment_index"].astype(np.int64),
                    "unit_index": spike_vector["unit_index"].astype(np.int64),
                }
            )
            unit_ids = np.asarray(sorting.get_unit_ids())
            if len(unit_ids):
                spike_df["unit_id"] = unit_ids[spike_df["unit_index"].to_numpy()]
            else:
                spike_df["unit_id"] = spike_df["unit_index"]
            spike_df["time_s"] = (
                spike_df["sample_index"].to_numpy(dtype=float)
                / float(recording.get_sampling_frequency())
            )
            spike_df["probe_label"] = _infer_probe_label_from_dir(probe_dir, resolved_probe_label)
            spike_df["sorter"] = args.sorter

            features_df = (
                spike_df.groupby("unit_id", dropna=False)
                .agg(
                    spike_count=("spike_index", "count"),
                    first_spike_s=("time_s", "min"),
                    last_spike_s=("time_s", "max"),
                )
                .reset_index()
            )
            features_df["firing_rate_hz"] = (
                features_df["spike_count"].to_numpy(dtype=float) / max(executed_duration_s, 1e-6)
            )
            features_df["probe_label"] = _infer_probe_label_from_dir(probe_dir, resolved_probe_label)

            spike_output = _write_table_output(spike_df, output_root, "spike_times")
            features_output = _write_table_output(features_df, output_root, "unit_features")
            qc_payload = {
                "sorter": args.sorter,
                "probe_dir": str(probe_dir),
                "probe_label": _infer_probe_label_from_dir(probe_dir, resolved_probe_label),
                "n_units": int(len(features_df)),
                "n_spikes": int(len(spike_df)),
                "sampling_frequency_hz": float(sorter_recording.get_sampling_frequency()),
                "executed_duration_s": executed_duration_s,
                "original_duration_s": original_duration_s,
                "max_duration_s": args.max_duration_s,
                "start_time_s": start_time_s,
                "smoke_mode": smoke_mode,
                "torch_device": sorter_params["torch_device"],
                "spikeinterface_log": str(sorter_output / "spikeinterface_log.json"),
            }
            qc_output = _write_json_output(qc_payload, output_root, "qc_report")
            metadata_output = _write_json_output(
                {
                    "tool_id": self.tool_id,
                    "sorter": args.sorter,
                    "dataset_ref": args.dataset_ref,
                    "session_id": args.session_id,
                    "subject_id": args.subject_id,
                    "probe_label": _infer_probe_label_from_dir(probe_dir, resolved_probe_label),
                    "probe_dir": str(probe_dir),
                    "output_dir": str(output_root),
                    "normalized_inputs": normalized_inputs,
                    "sorter_recording_dir": str(sorter_recording_dir),
                    "sorter_output_dir": str(sorter_output),
                    "sorter_params": sorter_params,
                    "start_time_s": start_time_s,
                    "local_context": local_context,
                },
                output_root,
                "metadata",
            )

            outputs.update(
                {
                    "data_dir": str(probe_dir),
                    "probe_label": _infer_probe_label_from_dir(probe_dir, resolved_probe_label),
                    "output_dir": str(output_root),
                    "sorter_output_dir": str(sorter_output),
                    "sorter_recording_dir": str(sorter_recording_dir),
                    "normalized_input_dir": normalized_inputs["normalized_input_dir"],
                    "spike_times": spike_output,
                    "qc_report": qc_output,
                    "features_table": features_output,
                    "metadata": metadata_output,
                    "spike_times_path": spike_output["path"],
                    "qc_report_path": qc_output["path"],
                    "features_table_path": features_output["path"],
                    "metadata_path": metadata_output["path"],
                    "start_time_s": start_time_s,
                    "n_units": int(len(features_df)),
                    "n_spikes": int(len(spike_df)),
                }
            )
        except Exception as exc:
            dependency_info = _dependency_summary(self.dependency_modules)
            error_outputs = dict(outputs)
            error_outputs.update(
                {
                    "data_dir": str(probe_dir),
                    "output_dir": str(output_root),
                    "sorter_output_dir": str(sorter_output),
                    "sorter_recording_dir": str(sorter_recording_dir),
                    "error_type": exc.__class__.__name__,
                    "local_session_context": local_context,
                }
            )
            return ToolResult(
                status="error",
                error=str(exc),
                data={
                    "outputs": error_outputs,
                    "summary": {
                        "tool_id": self.tool_id,
                        "mode": "local_mount" if local_context else "configured",
                        "dependency_mode": "available"
                        if dependency_info["all_available"]
                        else "fallback",
                        "dependency_summary": dependency_info,
                    },
                },
            )

        if local_context:
            outputs["local_session_context"] = local_context
            return self._wrap_result(
                args=args,
                outputs=outputs,
                mode_override="local_mount",
                dependency_mode_override="local_mount",
                ignore_dependency_gate=True,
            )
        return self._wrap_result(args=args, outputs=outputs)


class IBLDeepLabCutTool(_IBLToolBase):
    tool_id = "ibl_deeplabcut"
    args_model = IBLPoseToolArgs
    dependency_modules = _DEEPLABCUT_DEPENDENCY_MODULES

    def _run(
        self,
        video_path: str | None = None,
        dataset_ref: str | None = None,
        session_id: str | None = None,
        subject_id: str | None = None,
        output_dir: str | None = None,
        keypoint_schema: list[str] | None = None,
        dry_run: bool = True,
        allow_missing_dependencies: bool = True,
        **kwargs,
    ) -> ToolResult:
        args = IBLPoseToolArgs(
            video_path=video_path,
            dataset_ref=dataset_ref,
            session_id=session_id,
            subject_id=subject_id,
            output_dir=output_dir,
            keypoint_schema=list(keypoint_schema or []),
            dry_run=dry_run,
            allow_missing_dependencies=allow_missing_dependencies,
        )
        local_context = None
        resolved_video_path = args.video_path
        if not args.dry_run:
            local_context = _resolve_local_session_context(
                dataset_ref=args.dataset_ref,
                session_id=args.session_id,
                subject_id=args.subject_id,
            )
            if local_context and not resolved_video_path:
                video_files = local_context.get("video_files") or []
                resolved_video_path = video_files[0] if video_files else None

        outputs = {
            "backend": "deeplabcut",
            "video_path": resolved_video_path,
            "output_dir": args.output_dir,
            "keypoint_schema": args.keypoint_schema,
            "planned_outputs": ["coord_table", "optical_metrics", "metadata"],
        }
        if not args.dry_run and local_context:
            pose_output_dir = (
                Path(args.output_dir).expanduser()
                if args.output_dir
                else Path(tempfile.mkdtemp(prefix="ibl_dlc_"))
            )
            materialized = _materialize_pose_tables(
                Path(local_context["session_path"]),
                backend="deeplabcut",
                video_path=resolved_video_path,
                output_dir=pose_output_dir,
            )
            if materialized is not None:
                outputs.update(
                    {
                        "output_dir": str(pose_output_dir),
                        "coord_table": materialized["coord_table"],
                        "optical_metrics": materialized["optical_metrics"],
                        "metadata": materialized["metadata"],
                        "coord_table_path": materialized["coord_table"]["path"],
                        "optical_metrics_path": materialized["optical_metrics"]["path"],
                        "metadata_path": materialized["metadata"]["path"],
                        "camera": materialized["camera"],
                        "source": materialized["source"],
                    }
                )
        if local_context:
            outputs["local_session_context"] = local_context
            return self._wrap_result(
                args=args,
                outputs=outputs,
                mode_override="local_mount",
                dependency_mode_override="local_mount",
                ignore_dependency_gate=True,
            )
        return self._wrap_result(args=args, outputs=outputs)


class IBLLightningPoseTool(_IBLToolBase):
    tool_id = "ibl_lightning_pose"
    args_model = IBLPoseToolArgs
    dependency_modules = _LIGHTNING_POSE_DEPENDENCY_MODULES

    def _run(
        self,
        video_path: str | None = None,
        dataset_ref: str | None = None,
        session_id: str | None = None,
        subject_id: str | None = None,
        output_dir: str | None = None,
        keypoint_schema: list[str] | None = None,
        dry_run: bool = True,
        allow_missing_dependencies: bool = True,
        **kwargs,
    ) -> ToolResult:
        args = IBLPoseToolArgs(
            video_path=video_path,
            dataset_ref=dataset_ref,
            session_id=session_id,
            subject_id=subject_id,
            output_dir=output_dir,
            keypoint_schema=list(keypoint_schema or []),
            dry_run=dry_run,
            allow_missing_dependencies=allow_missing_dependencies,
        )
        local_context = None
        resolved_video_path = args.video_path
        if not args.dry_run:
            local_context = _resolve_local_session_context(
                dataset_ref=args.dataset_ref,
                session_id=args.session_id,
                subject_id=args.subject_id,
            )
            if local_context and not resolved_video_path:
                video_files = local_context.get("video_files") or []
                resolved_video_path = video_files[0] if video_files else None

        outputs = {
            "backend": "lightning_pose",
            "video_path": resolved_video_path,
            "output_dir": args.output_dir,
            "keypoint_schema": args.keypoint_schema,
            "planned_outputs": ["coord_table", "optical_metrics", "metadata"],
        }
        if not args.dry_run and local_context:
            pose_output_dir = (
                Path(args.output_dir).expanduser()
                if args.output_dir
                else Path(tempfile.mkdtemp(prefix="ibl_lightning_pose_"))
            )
            materialized = _materialize_pose_tables(
                Path(local_context["session_path"]),
                backend="lightning_pose",
                video_path=resolved_video_path,
                output_dir=pose_output_dir,
            )
            if materialized is not None:
                outputs.update(
                    {
                        "output_dir": str(pose_output_dir),
                        "coord_table": materialized["coord_table"],
                        "optical_metrics": materialized["optical_metrics"],
                        "metadata": materialized["metadata"],
                        "coord_table_path": materialized["coord_table"]["path"],
                        "optical_metrics_path": materialized["optical_metrics"]["path"],
                        "metadata_path": materialized["metadata"]["path"],
                        "camera": materialized["camera"],
                        "source": materialized["source"],
                    }
                )
        if local_context:
            outputs["local_session_context"] = local_context
            return self._wrap_result(
                args=args,
                outputs=outputs,
                mode_override="local_mount",
                dependency_mode_override="local_mount",
                ignore_dependency_gate=True,
            )
        return self._wrap_result(args=args, outputs=outputs)


class IBLSpikeBehaviorAlignmentTool(_IBLToolBase):
    tool_id = "ibl_spike_behavior_alignment"
    args_model = IBLSpikeBehaviorAlignmentArgs

    def _run(
        self,
        spike_times_path: str | None = None,
        events_path: str | None = None,
        pose_coordinates_path: str | None = None,
        dataset_ref: str | None = None,
        session_id: str | None = None,
        subject_id: str | None = None,
        probe_label: str | None = None,
        output_dir: str | None = None,
        spike_limit: int | None = None,
        alignment_anchor: str = "trial_intervals",
        dry_run: bool = True,
        allow_missing_dependencies: bool = True,
        **kwargs,
    ) -> ToolResult:
        args = IBLSpikeBehaviorAlignmentArgs(
            spike_times_path=spike_times_path,
            events_path=events_path,
            pose_coordinates_path=pose_coordinates_path,
            dataset_ref=dataset_ref,
            session_id=session_id,
            subject_id=subject_id,
            probe_label=probe_label,
            output_dir=output_dir,
            spike_limit=spike_limit,
            alignment_anchor=alignment_anchor,
            dry_run=dry_run,
            allow_missing_dependencies=allow_missing_dependencies,
        )

        local_context = None
        extracted_tables = None
        output_root = (
            Path(args.output_dir).expanduser()
            if args.output_dir
            else Path(tempfile.mkdtemp(prefix="ibl_alignment_"))
        )
        if not args.dry_run:
            local_context = _resolve_local_session_context(
                dataset_ref=args.dataset_ref,
                session_id=args.session_id,
                subject_id=args.subject_id,
                probe_label=args.probe_label,
            )
            if local_context:
                extracted = extract_session_tables(
                    local_context["session_path"],
                    output_dir=str(output_root / "inputs"),
                    include_trials=True,
                    include_wheel=True,
                    include_spikes=True,
                    include_regions=False,
                    include_channels=False,
                    include_electrode_sites=False,
                    include_probe_trajectories=False,
                    probe_label=args.probe_label,
                    spike_limit=args.spike_limit,
                )
                extracted_tables = extracted["tables"]
                if not args.events_path:
                    args.events_path = (
                        extracted_tables.get("trials", {}) or {}
                    ).get("path")
                if not args.spike_times_path:
                    spike_table_key = (
                        f"spikes_{args.probe_label}"
                        if args.probe_label
                        else next(
                            (
                                key
                                for key in extracted_tables
                                if key.startswith("spikes_")
                            ),
                            None,
                        )
                    )
                    if spike_table_key:
                        args.spike_times_path = (
                            extracted_tables.get(spike_table_key, {}) or {}
                        ).get("path")

        outputs = {
            "spike_times_path": args.spike_times_path,
            "events_path": args.events_path,
            "pose_coordinates_path": args.pose_coordinates_path,
            "alignment_anchor": args.alignment_anchor,
            "output_dir": str(output_root),
            "planned_join_strategy": [
                "join spikes on time_s to trial interval_start/interval_end",
                "optionally merge pose coordinates on shared timestamps",
                "emit aligned timeseries and feature tables for decoding or GLM",
            ],
            "planned_outputs": [
                "aligned_timeseries",
                "timeseries",
                "features_table",
                "metadata",
            ],
        }

        if not args.dry_run and args.events_path and args.spike_times_path:
            try:
                trials_df = _load_table(args.events_path)
                spikes_df = _load_table(args.spike_times_path)
                pose_df = _load_table(args.pose_coordinates_path)
                wheel_moves_df = None
                if extracted_tables is not None:
                    wheel_moves_path = (
                        extracted_tables.get("wheel_moves", {}) or {}
                    ).get("path")
                    wheel_moves_df = _load_table(wheel_moves_path)

                if trials_df is None or spikes_df is None:
                    raise FileNotFoundError("Spike or trial table could not be loaded.")

                if "trial_index" not in trials_df.columns:
                    trials_df = trials_df.copy()
                    trials_df.insert(0, "trial_index", np.arange(len(trials_df), dtype=int))

                aligned_spikes_df = _append_trial_membership(
                    spikes_df,
                    time_column="time_s",
                    trials=trials_df,
                )

                aligned_behavior_df = None
                if wheel_moves_df is not None and "interval_start" in wheel_moves_df.columns:
                    wheel_moves_aligned = _append_trial_membership(
                        wheel_moves_df.rename(columns={"interval_start": "time_s"}),
                        time_column="time_s",
                        trials=trials_df,
                    )
                    aligned_behavior_df = wheel_moves_aligned.rename(
                        columns={"time_s": "interval_start"}
                    )
                elif pose_df is not None and "time_s" in pose_df.columns:
                    aligned_behavior_df = _append_trial_membership(
                        pose_df,
                        time_column="time_s",
                        trials=trials_df,
                    )

                trial_features_df = trials_df.copy()
                unit_column = (
                    "unit_id"
                    if "unit_id" in aligned_spikes_df.columns
                    else "cluster_id"
                    if "cluster_id" in aligned_spikes_df.columns
                    else None
                )
                spike_summary = (
                    aligned_spikes_df.loc[aligned_spikes_df["trial_index"] >= 0]
                    .groupby("trial_index", dropna=False)
                    .agg(
                        spike_count=("spike_index", "count"),
                        active_units=(
                            unit_column or "spike_index",
                            "nunique",
                        ),
                    )
                    .reset_index()
                )
                if "amp_uV" in aligned_spikes_df.columns:
                    amp_summary = (
                        aligned_spikes_df.loc[aligned_spikes_df["trial_index"] >= 0]
                        .groupby("trial_index")["amp_uV"]
                        .mean()
                        .rename("mean_spike_amp_uV")
                        .reset_index()
                    )
                    spike_summary = spike_summary.merge(amp_summary, on="trial_index", how="left")
                trial_features_df = trial_features_df.merge(
                    spike_summary,
                    on="trial_index",
                    how="left",
                )

                if wheel_moves_df is not None and aligned_behavior_df is not None:
                    wheel_summary = (
                        aligned_behavior_df.loc[aligned_behavior_df["trial_index"] >= 0]
                        .groupby("trial_index", dropna=False)
                        .agg(wheel_move_count=("move_index", "count"))
                        .reset_index()
                    )
                    if "peakAmplitude" in aligned_behavior_df.columns:
                        amp_sum = (
                            aligned_behavior_df.loc[aligned_behavior_df["trial_index"] >= 0]
                            .groupby("trial_index")["peakAmplitude"]
                            .sum()
                            .rename("wheel_peakAmplitude_sum")
                            .reset_index()
                        )
                        wheel_summary = wheel_summary.merge(amp_sum, on="trial_index", how="left")
                    trial_features_df = trial_features_df.merge(
                        wheel_summary,
                        on="trial_index",
                        how="left",
                    )

                if pose_df is not None and "time_s" in pose_df.columns:
                    pose_aligned = _append_trial_membership(
                        pose_df,
                        time_column="time_s",
                        trials=trials_df,
                    )
                    pose_summary = (
                        pose_aligned.loc[pose_aligned["trial_index"] >= 0]
                        .groupby("trial_index", dropna=False)
                        .agg(pose_frame_count=("frame_index", "count"))
                        .reset_index()
                    )
                    likelihood_cols = [col for col in pose_aligned.columns if col.endswith("_likelihood")]
                    if likelihood_cols:
                        pose_quality = (
                            pose_aligned.loc[pose_aligned["trial_index"] >= 0]
                            .groupby("trial_index")[likelihood_cols]
                            .mean()
                            .mean(axis=1)
                            .rename("pose_mean_likelihood")
                            .reset_index()
                        )
                        pose_summary = pose_summary.merge(
                            pose_quality,
                            on="trial_index",
                            how="left",
                        )
                    trial_features_df = trial_features_df.merge(
                        pose_summary,
                        on="trial_index",
                        how="left",
                    )

                aligned_spikes_output = _write_table_output(
                    aligned_spikes_df,
                    output_root,
                    "aligned_spikes",
                )
                timeseries_df = aligned_behavior_df if aligned_behavior_df is not None else trials_df
                timeseries_output = _write_table_output(
                    timeseries_df,
                    output_root,
                    "aligned_behavior",
                )
                features_output = _write_table_output(
                    trial_features_df,
                    output_root,
                    "trial_features",
                )
                metadata_output = _write_json_output(
                    {
                        "tool_id": self.tool_id,
                        "dataset_ref": args.dataset_ref,
                        "session_id": args.session_id,
                        "subject_id": args.subject_id,
                        "probe_label": args.probe_label,
                        "alignment_anchor": args.alignment_anchor,
                        "spike_times_path": args.spike_times_path,
                        "events_path": args.events_path,
                        "pose_coordinates_path": args.pose_coordinates_path,
                        "has_wheel_moves": wheel_moves_df is not None,
                    },
                    output_root,
                    "metadata",
                )

                outputs.update(
                    {
                        "aligned_timeseries": aligned_spikes_output,
                        "timeseries": timeseries_output,
                        "features_table": features_output,
                        "metadata": metadata_output,
                        "aligned_timeseries_path": aligned_spikes_output["path"],
                        "timeseries_path": timeseries_output["path"],
                        "features_table_path": features_output["path"],
                        "metadata_path": metadata_output["path"],
                    }
                )
            except Exception as exc:
                dependency_info = _dependency_summary(self.dependency_modules)
                error_outputs = dict(outputs)
                if extracted_tables is not None:
                    error_outputs["extracted_alignment_inputs"] = extracted_tables
                if local_context:
                    error_outputs["local_session_context"] = local_context
                return ToolResult(
                    status="error",
                    error=str(exc),
                    data={
                        "outputs": error_outputs,
                        "summary": {
                            "tool_id": self.tool_id,
                            "mode": "local_mount" if local_context else "configured",
                            "dependency_mode": "available"
                            if dependency_info["all_available"]
                            else "fallback",
                            "dependency_summary": dependency_info,
                        },
                    },
                )

        if extracted_tables is not None:
            outputs["extracted_alignment_inputs"] = extracted_tables
        if local_context:
            outputs["local_session_context"] = local_context
            return self._wrap_result(
                args=args,
                outputs=outputs,
                mode_override="local_mount",
                dependency_mode_override="local_mount",
                ignore_dependency_gate=True,
            )
        return self._wrap_result(args=args, outputs=outputs)


class IBLDecodingDatasetTool(_IBLToolBase):
    tool_id = "ibl_decoding_dataset"
    args_model = IBLDecodingDatasetArgs

    def _run(
        self,
        spike_times_path: str | None = None,
        trials_path: str | None = None,
        trial_features_path: str | None = None,
        regions_path: str | None = None,
        dataset_ref: str | None = None,
        session_id: str | None = None,
        session_ids: list[str] | None = None,
        subject_id: str | None = None,
        probe_label: str | None = None,
        label_field: str = "choice",
        feature_level: str = "unit",
        group_by: str = "session",
        anchor_field: str = "stimOn_times",
        window_start_s: float = 0.0,
        window_end_s: float = 0.2,
        min_feature_count: int = 1,
        output_dir: str | None = None,
        spike_limit: int | None = None,
        dry_run: bool = True,
        allow_missing_dependencies: bool = True,
        **kwargs,
    ) -> ToolResult:
        args = IBLDecodingDatasetArgs(
            spike_times_path=spike_times_path,
            trials_path=trials_path,
            trial_features_path=trial_features_path,
            regions_path=regions_path,
            dataset_ref=dataset_ref,
            session_id=session_id,
            session_ids=list(session_ids or []),
            subject_id=subject_id,
            probe_label=probe_label,
            label_field=label_field,
            feature_level=feature_level,
            group_by=group_by,
            anchor_field=anchor_field,
            window_start_s=window_start_s,
            window_end_s=window_end_s,
            min_feature_count=min_feature_count,
            output_dir=output_dir,
            spike_limit=spike_limit,
            dry_run=dry_run,
            allow_missing_dependencies=allow_missing_dependencies,
        )

        output_root = (
            Path(args.output_dir).expanduser()
            if args.output_dir
            else Path(tempfile.mkdtemp(prefix="ibl_decoding_dataset_"))
        )
        output_root.mkdir(parents=True, exist_ok=True)

        outputs: dict[str, Any] = {
            "dataset_ref": args.dataset_ref,
            "session_id": args.session_id,
            "session_ids": args.session_ids,
            "subject_id": args.subject_id,
            "probe_label": args.probe_label,
            "label_field": args.label_field,
            "feature_level": args.feature_level,
            "group_by": args.group_by,
            "anchor_field": args.anchor_field,
            "window_s": [args.window_start_s, args.window_end_s],
            "min_feature_count": args.min_feature_count,
            "output_dir": str(output_root),
            "planned_outputs": [
                "data_file",
                "labels_file",
                "groups_file",
                "sample_metadata",
                "feature_metadata",
                "label_map",
                "metadata",
            ],
        }

        if args.dry_run:
            return self._wrap_result(args=args, outputs=outputs)

        feature_level_value = args.feature_level.strip().lower()
        if feature_level_value not in {"unit", "region"}:
            return ToolResult(
                status="error",
                error=f"Unsupported feature_level: {args.feature_level}",
                data={"outputs": outputs, "summary": {"tool_id": self.tool_id}},
            )

        group_by_value = args.group_by.strip().lower()
        if group_by_value not in {"session", "subject"}:
            return ToolResult(
                status="error",
                error=f"Unsupported group_by: {args.group_by}",
                data={"outputs": outputs, "summary": {"tool_id": self.tool_id}},
            )

        notes: list[str] = []
        sample_frames: list[pd.DataFrame] = []
        count_frames: list[pd.DataFrame] = []
        feature_rows: list[dict[str, Any]] = []
        session_inputs: list[dict[str, Any]] = []
        local_mode = False
        resources = None

        use_direct_inputs = bool(args.spike_times_path and (args.trials_path or args.trial_features_path))
        if use_direct_inputs:
            spikes_df = _load_table(args.spike_times_path)
            trials_df = _load_table(args.trials_path)
            if trials_df is None:
                trials_df = _load_table(args.trial_features_path)
            regions_df = _load_table(args.regions_path)
            if spikes_df is None:
                return ToolResult(
                    status="error",
                    error="Spike table could not be loaded.",
                    data={"outputs": outputs, "summary": {"tool_id": self.tool_id}},
                )
            if trials_df is None:
                trials_df = _fallback_trials_from_spikes(spikes_df)
                if trials_df is not None:
                    notes.append("trial_table_inferred_from_spikes_only; zero-spike trials may be absent")
            if trials_df is None:
                return ToolResult(
                    status="error",
                    error="Trials or trial-features table could not be loaded.",
                    data={"outputs": outputs, "summary": {"tool_id": self.tool_id}},
                )

            session_key = args.session_id or "session_000"
            subject_key = args.subject_id or "subject_000"
            trials_df = _prepare_ibl_trial_metadata(trials_df)
            if args.trial_features_path:
                trial_features_df = _load_table(args.trial_features_path)
                if trial_features_df is not None and "trial_index" in trial_features_df.columns:
                    merge_cols = [
                        column
                        for column in trial_features_df.columns
                        if column == "trial_index" or column not in trials_df.columns
                    ]
                    trials_df = trials_df.merge(
                        trial_features_df.loc[:, merge_cols],
                        on="trial_index",
                        how="left",
                    )
            actual_probe_label = (
                args.probe_label
                or (
                    str(spikes_df["probe_label"].iloc[0])
                    if "probe_label" in spikes_df.columns and not spikes_df.empty
                    else "probe00"
                )
            )
            if "session_id" not in trials_df.columns:
                trials_df["session_id"] = session_key
            if "subject_id" not in trials_df.columns:
                trials_df["subject_id"] = subject_key
            if "probe_label" not in trials_df.columns:
                trials_df["probe_label"] = actual_probe_label
            session_inputs.append(
                {
                    "session_id": session_key,
                    "subject_id": subject_key,
                    "probe_label": actual_probe_label,
                    "source": "direct_paths",
                    "spike_times_path": args.spike_times_path,
                    "trials_path": args.trials_path,
                    "trial_features_path": args.trial_features_path,
                    "regions_path": args.regions_path,
                }
            )
            prepared_sessions = [
                (session_key, subject_key, actual_probe_label, trials_df, spikes_df, regions_df)
            ]
        else:
            resources = _resolve_ibl_resources(args.dataset_ref)
            data_root = _resolve_ibl_data_root(getattr(resources, "local_path", None))
            if data_root is None:
                return ToolResult(
                    status="error",
                    error="Mounted IBL dataset root is unavailable for decoding dataset extraction.",
                    data={"outputs": outputs, "summary": {"tool_id": self.tool_id}},
                )

            requested_session_paths = _resolve_requested_session_paths(
                data_root,
                session_ids=args.session_ids,
                session_id=args.session_id,
                subject_id=args.subject_id,
            )
            if not requested_session_paths:
                return ToolResult(
                    status="error",
                    error="No IBL sessions resolved for decoding dataset extraction.",
                    data={"outputs": outputs, "summary": {"tool_id": self.tool_id}},
                )

            local_mode = True
            prepared_sessions = []
            for session_path in requested_session_paths:
                session_summary = _session_summary_from_path(session_path)
                extract_output = extract_session_tables(
                    session_path,
                    output_dir=str(output_root / "inputs" / _safe_session_stem(session_summary["session_id"])),
                    include_trials=True,
                    include_wheel=False,
                    include_spikes=True,
                    include_regions=True,
                    include_channels=False,
                    include_electrode_sites=False,
                    include_probe_trajectories=False,
                    probe_label=args.probe_label,
                    spike_limit=args.spike_limit,
                )
                notes.extend(extract_output.get("notes") or [])
                extracted_tables = extract_output.get("tables") or {}
                spike_table_key = (
                    f"spikes_{args.probe_label}"
                    if args.probe_label
                    else next(
                        (key for key in extracted_tables if key.startswith("spikes_")),
                        None,
                    )
                )
                if spike_table_key is None:
                    notes.append(f"No spike table available for session {session_summary['session_id']}")
                    continue

                actual_probe_label = spike_table_key.removeprefix("spikes_")
                trials_df = _load_table((extracted_tables.get("trials") or {}).get("path"))
                spikes_df = _load_table((extracted_tables.get(spike_table_key) or {}).get("path"))
                regions_df = _load_table(
                    (extracted_tables.get(f"regions_{actual_probe_label}") or {}).get("path")
                )
                if trials_df is None or spikes_df is None:
                    notes.append(
                        f"Required trials/spikes tables missing for session {session_summary['session_id']}"
                    )
                    continue

                trials_df = _prepare_ibl_trial_metadata(trials_df)
                trials_df["session_id"] = session_summary["session_id"]
                trials_df["subject_id"] = session_summary["subject"]
                trials_df["probe_label"] = actual_probe_label
                session_inputs.append(
                    {
                        "session_id": session_summary["session_id"],
                        "subject_id": session_summary["subject"],
                        "probe_label": actual_probe_label,
                        "source": "mounted_alf",
                        "session_path": str(session_path),
                        "alf_path": extract_output.get("alf_path"),
                        "trials_path": (extracted_tables.get("trials") or {}).get("path"),
                        "spike_times_path": (extracted_tables.get(spike_table_key) or {}).get("path"),
                        "regions_path": (
                            extracted_tables.get(f"regions_{actual_probe_label}") or {}
                        ).get("path"),
                    }
                )
                prepared_sessions.append(
                    (
                        session_summary["session_id"],
                        session_summary["subject"],
                        actual_probe_label,
                        trials_df,
                        spikes_df,
                        regions_df,
                    )
                )

            if not prepared_sessions:
                return ToolResult(
                    status="error",
                    error="No usable IBL sessions were extracted for decoding dataset construction.",
                    data={"outputs": outputs, "summary": {"tool_id": self.tool_id}},
                )

        try:
            for (
                session_key,
                subject_key,
                actual_probe_label,
                trials_df,
                spikes_df,
                regions_df,
            ) in prepared_sessions:
                trials_df = _prepare_ibl_trial_metadata(trials_df)
                trials_df["session_id"] = session_key
                trials_df["subject_id"] = subject_key
                trials_df["probe_label"] = actual_probe_label
                trials_df["sample_id"] = [
                    f"{session_key}::trial{int(trial_index)}"
                    for trial_index in trials_df["trial_index"].to_numpy(dtype=int)
                ]
                sample_frames.append(trials_df.copy())

                spikes_session = spikes_df.copy()
                if "trial_index" not in spikes_session.columns or spikes_session["trial_index"].isna().all():
                    spikes_session = _append_trial_membership(
                        spikes_session,
                        time_column="time_s",
                        trials=trials_df,
                    )
                if "trial_index" not in spikes_session.columns:
                    raise ValueError(f"Spike table for {session_key} lacks trial_index and could not be aligned.")

                spikes_session = spikes_session.loc[spikes_session["trial_index"] >= 0].copy()
                sample_lookup = trials_df.set_index("trial_index")["sample_id"]
                spikes_session["sample_id"] = spikes_session["trial_index"].map(sample_lookup)
                if "probe_label" not in spikes_session.columns:
                    spikes_session["probe_label"] = actual_probe_label

                relative_time = None
                if args.anchor_field == "stimOn_times" and "time_from_stimOn_s" in spikes_session.columns:
                    relative_time = pd.to_numeric(
                        spikes_session["time_from_stimOn_s"], errors="coerce"
                    )
                elif (
                    args.anchor_field == "interval_start"
                    and "time_from_trial_start_s" in spikes_session.columns
                ):
                    relative_time = pd.to_numeric(
                        spikes_session["time_from_trial_start_s"], errors="coerce"
                    )
                elif args.anchor_field in spikes_session.columns:
                    relative_time = pd.to_numeric(
                        spikes_session["time_s"], errors="coerce"
                    ) - pd.to_numeric(
                        spikes_session[args.anchor_field], errors="coerce"
                    )

                if relative_time is not None:
                    spikes_session["relative_time_s"] = relative_time
                    spikes_window = spikes_session.loc[
                        relative_time.between(args.window_start_s, args.window_end_s, inclusive="both")
                    ].copy()
                else:
                    notes.append(
                        f"Anchor {args.anchor_field} unavailable for {session_key}; using full trial intervals"
                    )
                    spikes_window = spikes_session.copy()

                session_index = pd.Index(trials_df["sample_id"].astype(str), name="sample_id")
                counts = pd.DataFrame(index=session_index)
                if not spikes_window.empty:
                    if feature_level_value == "unit":
                        unit_column = (
                            "unit_id"
                            if "unit_id" in spikes_window.columns
                            else "cluster_id"
                            if "cluster_id" in spikes_window.columns
                            else None
                        )
                        if unit_column is None:
                            raise ValueError(
                                f"Spike table for {session_key} lacks unit_id/cluster_id for unit-level features."
                            )
                        spikes_window["feature_name"] = (
                            session_key
                            + "|"
                            + actual_probe_label
                            + "|"
                            + unit_column
                            + ":"
                            + spikes_window[unit_column].astype(str)
                        )
                        grouped = (
                            spikes_window.groupby(["sample_id", "feature_name"])
                            .size()
                            .unstack(fill_value=0)
                        )
                        counts = grouped.reindex(session_index, fill_value=0)

                        unit_features = spikes_window[[unit_column, "feature_name"]].drop_duplicates()
                        if (
                            regions_df is not None
                            and "cluster_id" in unit_features.columns
                            and "cluster_id" in regions_df.columns
                        ):
                            unit_features = unit_features.merge(
                                regions_df.drop_duplicates(subset=["cluster_id"]),
                                on="cluster_id",
                                how="left",
                            )
                        unit_features = unit_features.rename(columns={unit_column: "unit_identifier"})
                        unit_features["feature_level"] = "unit"
                        unit_features["session_id"] = session_key
                        unit_features["subject_id"] = subject_key
                        unit_features["probe_label"] = actual_probe_label
                        feature_rows.extend(unit_features.to_dict(orient="records"))
                    else:
                        if "cluster_id" not in spikes_window.columns:
                            raise ValueError(
                                f"Spike table for {session_key} lacks cluster_id for region-level features."
                            )
                        if regions_df is None or "cluster_id" not in regions_df.columns:
                            raise ValueError(
                                f"Region table unavailable for {session_key} region-level decoding."
                            )
                        region_lookup = regions_df.drop_duplicates(subset=["cluster_id"]).copy()
                        spikes_region = spikes_window.merge(
                            region_lookup,
                            on="cluster_id",
                            how="left",
                        )
                        feature_values = spikes_region.get("region_acronym")
                        if feature_values is None or feature_values.isna().all():
                            feature_values = "region_" + spikes_region["region_id"].astype(str)
                        else:
                            feature_values = feature_values.fillna(
                                "region_" + spikes_region["region_id"].astype(str)
                            )
                        spikes_region["feature_name"] = feature_values.astype(str)
                        grouped = (
                            spikes_region.groupby(["sample_id", "feature_name"])
                            .size()
                            .unstack(fill_value=0)
                        )
                        counts = grouped.reindex(session_index, fill_value=0)
                        region_features = (
                            spikes_region[["feature_name", "region_acronym", "region_id"]]
                            .drop_duplicates()
                            .copy()
                        )
                        region_features["feature_level"] = "region"
                        feature_rows.extend(region_features.to_dict(orient="records"))

                count_frames.append(counts)

            sample_metadata_df = pd.concat(sample_frames, ignore_index=True)
            sample_metadata_df = sample_metadata_df.drop_duplicates(subset=["sample_id"])
            sample_metadata_df = sample_metadata_df.sort_values(
                ["session_id", "trial_index"],
                kind="stable",
            ).reset_index(drop=True)

            label_values = _resolve_label_values(sample_metadata_df, args.label_field)
            valid_label_mask = label_values.notna()
            if not bool(valid_label_mask.any()):
                raise ValueError(f"No valid labels found for {args.label_field}")

            sample_metadata_df = sample_metadata_df.loc[valid_label_mask].reset_index(drop=True)
            label_values = label_values.loc[valid_label_mask].reset_index(drop=True)
            y_array, label_info = _encode_label_array(label_values, label_field=args.label_field)
            sample_metadata_df["label_value"] = label_values.tolist()
            if label_info["label_type"] == "categorical":
                sample_metadata_df["label_code"] = y_array

            group_values = sample_metadata_df["session_id"]
            if group_by_value == "subject":
                group_values = sample_metadata_df["subject_id"]
            groups_array, group_info = _encode_group_array(group_values, group_by=group_by_value)
            sample_metadata_df["group_value"] = group_values.astype(str).tolist()
            sample_metadata_df["group_code"] = groups_array

            X_df = pd.concat(count_frames, axis=0, sort=True) if count_frames else pd.DataFrame()
            X_df = X_df.reindex(sample_metadata_df["sample_id"].astype(str)).fillna(0.0)
            if X_df.shape[1] == 0:
                raise ValueError("No spike-derived features were available for decoding.")

            feature_totals = X_df.sum(axis=0)
            keep_columns = feature_totals.loc[
                feature_totals >= float(args.min_feature_count)
            ].index.tolist()
            if not keep_columns:
                raise ValueError("All decoding features were filtered out by min_feature_count.")
            X_df = X_df.loc[:, keep_columns].astype(np.float32)

            feature_metadata_df = pd.DataFrame(feature_rows)
            if feature_metadata_df.empty:
                feature_metadata_df = pd.DataFrame({"feature_name": keep_columns})
            feature_metadata_df = feature_metadata_df.drop_duplicates(subset=["feature_name"])
            feature_metadata_df = feature_metadata_df.loc[
                feature_metadata_df["feature_name"].isin(keep_columns)
            ].copy()
            if feature_metadata_df.empty:
                feature_metadata_df = pd.DataFrame({"feature_name": keep_columns})
            feature_order = {name: index for index, name in enumerate(keep_columns)}
            feature_metadata_df["feature_index"] = feature_metadata_df["feature_name"].map(
                feature_order
            )
            feature_metadata_df["feature_level"] = feature_level_value
            feature_metadata_df = feature_metadata_df.sort_values(
                "feature_index", kind="stable"
            ).reset_index(drop=True)

            data_output = _write_npy_output(
                X_df.to_numpy(dtype=np.float32),
                output_root,
                "X",
            )
            labels_output = _write_npy_output(np.asarray(y_array), output_root, "y")
            groups_output = _write_npy_output(np.asarray(groups_array, dtype=np.int64), output_root, "groups")
            sample_metadata_output = _write_table_output(
                sample_metadata_df,
                output_root,
                "sample_metadata",
            )
            feature_metadata_output = _write_table_output(
                feature_metadata_df,
                output_root,
                "feature_metadata",
            )
            label_map_output = _write_json_output(label_info, output_root, "label_map")
            metadata_output = _write_json_output(
                {
                    "tool_id": self.tool_id,
                    "dataset_ref": args.dataset_ref,
                    "resolved_dataset_id": getattr(resources, "resolved_dataset_id", None)
                    if resources is not None
                    else None,
                    "label_field": args.label_field,
                    "feature_level": feature_level_value,
                    "group_by": group_by_value,
                    "anchor_field": args.anchor_field,
                    "window_start_s": args.window_start_s,
                    "window_end_s": args.window_end_s,
                    "min_feature_count": args.min_feature_count,
                    "n_samples": int(X_df.shape[0]),
                    "n_features": int(X_df.shape[1]),
                    "label_info": label_info,
                    "group_info": group_info,
                    "session_inputs": session_inputs,
                    "notes": notes,
                },
                output_root,
                "metadata",
            )

            outputs.update(
                {
                    "data_file": data_output["path"],
                    "labels_file": labels_output["path"],
                    "groups_file": groups_output["path"],
                    "data_matrix": data_output,
                    "labels": labels_output,
                    "groups": groups_output,
                    "sample_metadata": sample_metadata_output,
                    "feature_metadata": feature_metadata_output,
                    "label_map": label_map_output,
                    "metadata": metadata_output,
                    "data_file_path": data_output["path"],
                    "labels_file_path": labels_output["path"],
                    "groups_file_path": groups_output["path"],
                    "sample_metadata_path": sample_metadata_output["path"],
                    "feature_metadata_path": feature_metadata_output["path"],
                    "metadata_path": metadata_output["path"],
                    "n_samples": int(X_df.shape[0]),
                    "n_features": int(X_df.shape[1]),
                    "notes": notes,
                    "session_inputs": session_inputs,
                }
            )
        except Exception as exc:
            return ToolResult(
                status="error",
                error=str(exc),
                data={"outputs": outputs, "summary": {"tool_id": self.tool_id}},
            )

        if local_mode:
            outputs["local_path"] = getattr(resources, "local_path", None) if resources else None
            outputs["resolved_dataset_id"] = (
                getattr(resources, "resolved_dataset_id", None) if resources else None
            )
            return self._wrap_result(
                args=args,
                outputs=outputs,
                mode_override="local_mount",
                dependency_mode_override="local_mount",
                ignore_dependency_gate=True,
            )
        return self._wrap_result(args=args, outputs=outputs)


class IBLNeuropixelsWorkflowTool(_IBLToolBase):
    tool_id = "ibl_neuropixels_workflow"
    args_model = IBLNeuropixelsWorkflowArgs

    def _run(
        self,
        raw_ephys_dir: str | None = None,
        video_path: str | None = None,
        behavior_events_path: str | None = None,
        dataset_ref: str | None = None,
        session_id: str | None = None,
        subject_id: str | None = None,
        probe_label: str | None = None,
        pose_backend: str = "lightning_pose",
        include_pose: bool = True,
        output_dir: str | None = None,
        spike_limit: int | None = None,
        max_duration_s: float | None = None,
        dry_run: bool = True,
        allow_missing_dependencies: bool = True,
        **kwargs,
    ) -> ToolResult:
        args = IBLNeuropixelsWorkflowArgs(
            raw_ephys_dir=raw_ephys_dir,
            video_path=video_path,
            behavior_events_path=behavior_events_path,
            dataset_ref=dataset_ref,
            session_id=session_id,
            subject_id=subject_id,
            probe_label=probe_label,
            pose_backend=pose_backend,
            include_pose=include_pose,
            output_dir=output_dir,
            spike_limit=spike_limit,
            max_duration_s=max_duration_s,
            dry_run=dry_run,
            allow_missing_dependencies=allow_missing_dependencies,
        )

        local_context = None
        if not args.dry_run:
            local_context = _resolve_local_session_context(
                dataset_ref=args.dataset_ref,
                session_id=args.session_id,
                subject_id=args.subject_id,
                probe_label=args.probe_label,
            )

        pose_tool = (
            "ibl_deeplabcut"
            if args.pose_backend.strip().lower() == "deeplabcut"
            else "ibl_lightning_pose"
        )
        steps: list[dict[str, Any]] = [
            {
                "step": "spike_sorting",
                "tool": "ibl_kilosort",
                "purpose": "Convert raw extracellular signals into sorted spikes and QC outputs.",
            }
        ]
        if args.include_pose:
            steps.append(
                {
                    "step": "pose_tracking",
                    "tool": pose_tool,
                    "purpose": "Estimate video keypoints from behavior camera footage.",
                    "optional": False,
                }
            )
        steps.append(
            {
                "step": "spike_behavior_alignment",
                "tool": "ibl_spike_behavior_alignment",
                "purpose": "Link spikes, trials/events, and optional pose coordinates in time.",
            }
        )

        outputs = {
            "pose_backend": pose_tool,
            "include_pose": args.include_pose,
            "raw_ephys_dir": args.raw_ephys_dir,
            "video_path": args.video_path,
            "behavior_events_path": args.behavior_events_path,
            "probe_label": args.probe_label,
            "output_dir": args.output_dir,
            "max_duration_s": args.max_duration_s,
            "workflow_steps": steps,
            "workflow_summary": [
                "raw ephys -> Kilosort",
                "optional video -> DeepLabCut or Lightning Pose",
                "spikes + behavior -> alignment for downstream decoding/GLM",
            ],
            "planned_outputs": [
                "spike_times",
                "coord_table",
                "aligned_timeseries",
                "qc_report",
                "optical_metrics",
                "metadata",
            ],
        }
        if not args.dry_run:
            workflow_root = (
                Path(args.output_dir).expanduser()
                if args.output_dir
                else Path(tempfile.mkdtemp(prefix="ibl_neuropixels_workflow_"))
            )
            workflow_root.mkdir(parents=True, exist_ok=True)
            outputs["output_dir"] = str(workflow_root)

            raw_ephys_input = args.raw_ephys_dir
            if local_context:
                raw_ephys_input = (
                    local_context.get("raw_ephys_probe_dir")
                    or local_context.get("raw_ephys_dir")
                    or raw_ephys_input
                )
            resolved_video = args.video_path
            if local_context and not resolved_video:
                video_files = local_context.get("video_files") or []
                resolved_video = video_files[0] if video_files else None

            kilosort_tool = IBLKilosortTool()
            kilosort_result = kilosort_tool._run(
                data_dir=raw_ephys_input,
                dataset_ref=args.dataset_ref,
                session_id=args.session_id,
                subject_id=args.subject_id,
                probe_label=args.probe_label,
                sorter="kilosort4",
                output_dir=str(workflow_root / "kilosort"),
                max_duration_s=args.max_duration_s,
                dry_run=False,
                allow_missing_dependencies=args.allow_missing_dependencies,
            )

            pose_result = None
            pose_path = None
            if args.include_pose:
                pose_tool_impl = (
                    IBLDeepLabCutTool()
                    if pose_tool == "ibl_deeplabcut"
                    else IBLLightningPoseTool()
                )
                pose_result = pose_tool_impl._run(
                    video_path=resolved_video,
                    dataset_ref=args.dataset_ref,
                    session_id=args.session_id,
                    subject_id=args.subject_id,
                    output_dir=str(workflow_root / "pose"),
                    dry_run=False,
                    allow_missing_dependencies=args.allow_missing_dependencies,
                )
                if pose_result.status == "success":
                    pose_path = (
                        ((pose_result.data or {}).get("outputs") or {}).get("coord_table_path")
                    )

            spike_times_path = None
            if kilosort_result.status == "success":
                spike_times_path = (
                    ((kilosort_result.data or {}).get("outputs") or {}).get("spike_times_path")
                )

            alignment_tool = IBLSpikeBehaviorAlignmentTool()
            alignment_result = alignment_tool._run(
                spike_times_path=spike_times_path,
                events_path=args.behavior_events_path,
                pose_coordinates_path=pose_path,
                dataset_ref=args.dataset_ref,
                session_id=args.session_id,
                subject_id=args.subject_id,
                probe_label=args.probe_label,
                output_dir=str(workflow_root / "alignment"),
                spike_limit=args.spike_limit,
                dry_run=False,
                allow_missing_dependencies=args.allow_missing_dependencies,
            )

            workflow_notes: list[str] = []
            if kilosort_result.status != "success":
                workflow_notes.append(
                    "kilosort_failed_alignment_used_local_spike_fallback_if_available"
                )
            if args.include_pose and (pose_result is None or pose_result.status != "success"):
                workflow_notes.append("pose_stage_unavailable_or_missing_precomputed_outputs")

            summary_payload = {
                "tool_id": self.tool_id,
                "dataset_ref": args.dataset_ref,
                "session_id": args.session_id,
                "subject_id": args.subject_id,
                "probe_label": args.probe_label,
                "pose_backend": pose_tool,
                "include_pose": args.include_pose,
                "max_duration_s": args.max_duration_s,
                "notes": workflow_notes,
                "step_status": {
                    "kilosort": kilosort_result.status,
                    "pose": pose_result.status if pose_result is not None else "skipped",
                    "alignment": alignment_result.status,
                },
            }
            workflow_summary_output = _write_json_output(
                summary_payload,
                workflow_root,
                "workflow_summary",
            )

            outputs.update(
                {
                    "raw_ephys_dir": raw_ephys_input,
                    "video_path": resolved_video,
                    "workflow_summary_file": workflow_summary_output,
                    "workflow_notes": workflow_notes,
                    "kilosort_result": kilosort_result.model_dump(),
                    "alignment_result": alignment_result.model_dump(),
                }
            )
            if pose_result is not None:
                outputs["pose_result"] = pose_result.model_dump()

            for result in (kilosort_result, pose_result, alignment_result):
                if result is None or result.status != "success" or not result.data:
                    continue
                result_outputs = result.data.get("outputs") or {}
                for key in (
                    "spike_times",
                    "qc_report",
                    "coord_table",
                    "optical_metrics",
                    "aligned_timeseries",
                    "timeseries",
                    "features_table",
                    "metadata",
                ):
                    if key in result_outputs and key not in outputs:
                        outputs[key] = result_outputs[key]
                for key in (
                    "spike_times_path",
                    "qc_report_path",
                    "coord_table_path",
                    "optical_metrics_path",
                    "aligned_timeseries_path",
                    "timeseries_path",
                    "features_table_path",
                    "metadata_path",
                ):
                    if key in result_outputs and key not in outputs:
                        outputs[key] = result_outputs[key]

        if local_context:
            outputs["local_session_context"] = local_context
            return self._wrap_result(
                args=args,
                outputs=outputs,
                mode_override="local_mount",
                dependency_mode_override="local_mount",
                ignore_dependency_gate=True,
            )
        return self._wrap_result(args=args, outputs=outputs)


def ibl_decoding_dataset_entrypoint(**kwargs) -> ToolResult:
    """Grandmaster/runtime bridge for the IBL decoding dataset builder."""

    return IBLDecodingDatasetTool()._run(**kwargs)


def ibl_neuropixels_workflow_entrypoint(**kwargs) -> ToolResult:
    """Grandmaster/runtime bridge for the IBL Neuropixels workflow."""

    return IBLNeuropixelsWorkflowTool()._run(**kwargs)


def get_all_tools() -> list[NeuroToolWrapper]:
    """Expose the IBL wrappers to the tool executor."""
    return [
        IBLOneTool(),
        IBLBrainboxSessionEphysTool(),
        IBLAtlasRegionMappingTool(),
        IBLRigTaskLayerTool(),
        IBLSpikeSorterTool(),
        IBLKilosortTool(),
        IBLDeepLabCutTool(),
        IBLLightningPoseTool(),
        IBLSpikeBehaviorAlignmentTool(),
        IBLDecodingDatasetTool(),
        IBLNeuropixelsWorkflowTool(),
    ]


__all__ = [
    "IBLOneTool",
    "IBLBrainboxSessionEphysTool",
    "IBLAtlasRegionMappingTool",
    "IBLRigTaskLayerTool",
    "IBLSpikeSorterTool",
    "IBLKilosortTool",
    "IBLDeepLabCutTool",
    "IBLLightningPoseTool",
    "IBLSpikeBehaviorAlignmentTool",
    "IBLDecodingDatasetTool",
    "IBLNeuropixelsWorkflowTool",
    "get_all_tools",
]
