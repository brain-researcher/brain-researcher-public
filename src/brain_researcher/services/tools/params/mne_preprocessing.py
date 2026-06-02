"""
Shared helpers for MNE preprocessing workflows.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from brain_researcher.core.utils import configure_mne_environment


@dataclass(frozen=True)
class MNEPreprocessingParameters:
    raw_file: str
    output_dir: str
    l_freq: Optional[float] = 0.1
    h_freq: Optional[float] = 40.0
    filter_method: str = "fir"
    filter_length: str = "auto"
    sfreq: Optional[float] = None
    detect_bad_channels: bool = True
    bad_channels: Tuple[str, ...] = field(default_factory=tuple)
    interpolate_bads: bool = True
    reference: str = "average"
    reference_channels: Tuple[str, ...] = field(default_factory=tuple)
    create_epochs: bool = False
    epoch_tmin: float = -0.2
    epoch_tmax: float = 0.8
    event_id: Optional[Dict[str, int]] = None
    baseline: Optional[Tuple[Optional[float], Optional[float]]] = (None, 0)
    reject: Optional[Dict[str, float]] = None
    flat: Optional[Dict[str, float]] = None
    notch_freq: Optional[Union[float, Tuple[float, ...]]] = None
    set_montage: Optional[str] = None
    save_format: str = "fif"
    overwrite: bool = False


def _load_raw_data(raw_file: str):
    import mne

    file_path = Path(raw_file)
    if not file_path.exists():
        raise FileNotFoundError(f"Raw file not found: {raw_file}")

    suffix = file_path.suffix.lower()
    if suffix in [".fif", ".fiff"]:
        return mne.io.read_raw_fif(raw_file, preload=True)
    if suffix == ".edf":
        return mne.io.read_raw_edf(raw_file, preload=True)
    if suffix == ".bdf":
        return mne.io.read_raw_bdf(raw_file, preload=True)
    if suffix == ".vhdr":
        return mne.io.read_raw_brainvision(raw_file, preload=True)
    if suffix == ".set":
        return mne.io.read_raw_eeglab(raw_file, preload=True)
    if suffix == ".cnt":
        return mne.io.read_raw_cnt(raw_file, preload=True)
    if suffix == ".egi":
        return mne.io.read_raw_egi(raw_file, preload=True)
    return mne.io.read_raw(raw_file, preload=True)


def _detect_bad_channels(raw) -> List[str]:
    data = raw.get_data()
    channel_vars = np.var(data, axis=1)
    flat_threshold = np.percentile(channel_vars, 1)
    flat_channels = np.where(channel_vars < flat_threshold)[0]
    noise_threshold = np.percentile(channel_vars, 99)
    noisy_channels = np.where(channel_vars > noise_threshold * 3)[0]
    bad_indices = np.concatenate([flat_channels, noisy_channels])
    return list({raw.ch_names[idx] for idx in bad_indices})


def _apply_reference(
    raw, reference: str, reference_channels: Optional[List[str]] = None
):
    import mne

    if reference.lower() == "average":
        raw.set_eeg_reference("average", projection=False)
    elif reference.upper() == "REST":
        raw.set_eeg_reference("REST")
    elif reference.upper() == "CSD":
        raw = mne.preprocessing.compute_current_source_density(raw)
    elif reference.lower() == "bipolar":
        if reference_channels:
            anodes = reference_channels[::2]
            cathodes = reference_channels[1::2]
            raw = mne.set_bipolar_reference(raw, anodes, cathodes)
    elif reference_channels:
        raw.set_eeg_reference(reference_channels)
    else:
        raw.set_eeg_reference([reference])
    return raw


def mne_preprocessing_from_payload(
    payload: Dict[str, Any],
) -> MNEPreprocessingParameters:
    def _tuple(val):
        if val is None:
            return tuple()
        if isinstance(val, (list, tuple, set)):
            return tuple(val)
        return (val,)

    return MNEPreprocessingParameters(
        raw_file=str(payload["raw_file"]),
        output_dir=str(payload["output_dir"]),
        l_freq=payload.get("l_freq", 0.1),
        h_freq=payload.get("h_freq", 40.0),
        filter_method=payload.get("filter_method", "fir"),
        filter_length=payload.get("filter_length", "auto"),
        sfreq=payload.get("sfreq"),
        detect_bad_channels=bool(payload.get("detect_bad_channels", True)),
        bad_channels=_tuple(payload.get("bad_channels")),
        interpolate_bads=bool(payload.get("interpolate_bads", True)),
        reference=str(payload.get("reference", "average")),
        reference_channels=_tuple(payload.get("reference_channels")),
        create_epochs=bool(payload.get("create_epochs", False)),
        epoch_tmin=float(payload.get("epoch_tmin", -0.2)),
        epoch_tmax=float(payload.get("epoch_tmax", 0.8)),
        event_id=payload.get("event_id"),
        baseline=payload.get("baseline", (None, 0)),
        reject=payload.get("reject"),
        flat=payload.get("flat"),
        notch_freq=payload.get("notch_freq"),
        set_montage=payload.get("set_montage"),
        save_format=payload.get("save_format", "fif"),
        overwrite=bool(payload.get("overwrite", False)),
    )


def run_mne_preprocessing(params: MNEPreprocessingParameters) -> Dict[str, Any]:
    configure_mne_environment()
    cache_dir = Path(params.output_dir) / ".numba-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["NUMBA_CACHE_DIR"] = str(cache_dir)
    os.environ.setdefault("NUMBA_DISABLE_CACHING", "1")
    os.environ.setdefault("MNE_HOME", str(Path(params.output_dir)))
    import mne

    raw = _load_raw_data(params.raw_file)
    orig_sfreq = raw.info["sfreq"]
    orig_nchan = len(raw.ch_names)

    output_path = Path(params.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    processing_log: List[str] = []

    if params.set_montage:
        montage = mne.channels.make_standard_montage(params.set_montage)
        raw.set_montage(montage)
        processing_log.append(f"Set montage: {params.set_montage}")

    if params.notch_freq:
        raw.notch_filter(
            params.notch_freq,
            filter_length=params.filter_length,
            method=params.filter_method,
        )
        processing_log.append(f"Notch filter at {params.notch_freq} Hz")

    if params.l_freq is not None or params.h_freq is not None:
        raw.filter(
            l_freq=params.l_freq,
            h_freq=params.h_freq,
            method=params.filter_method,
            filter_length=params.filter_length,
        )
        processing_log.append(f"Band-pass filter: {params.l_freq}-{params.h_freq} Hz")

    detected_bads: List[str] = []
    if params.detect_bad_channels:
        detected_bads = _detect_bad_channels(raw)
        processing_log.append(f"Detected {len(detected_bads)} bad channels")

    all_bads = list(set(detected_bads + list(params.bad_channels)))
    if all_bads:
        raw.info["bads"] = all_bads
        if params.interpolate_bads and raw.info.get("dig") is not None:
            raw.interpolate_bads(reset_bads=True)
            processing_log.append(f"Interpolated {len(all_bads)} bad channels")
        elif params.interpolate_bads:
            processing_log.append("Bad channel interpolation skipped (no digitization)")

    raw = _apply_reference(raw, params.reference, list(params.reference_channels))
    processing_log.append(f"Re-referenced to {params.reference}")

    if params.sfreq and params.sfreq != orig_sfreq:
        raw.resample(params.sfreq)
        processing_log.append(f"Resampled to {params.sfreq} Hz")

    epochs = None
    if params.create_epochs:
        events = mne.find_events(
            raw, stim_channel="STI 014" if "STI 014" in raw.ch_names else None
        )
        if len(events) > 0:
            epochs = mne.Epochs(
                raw,
                events,
                event_id=params.event_id,
                tmin=params.epoch_tmin,
                tmax=params.epoch_tmax,
                baseline=params.baseline,
                reject=params.reject,
                flat=params.flat,
                preload=True,
            )
            processing_log.append(f"Created {len(epochs)} epochs")

    output_file = output_path / f"preprocessed_raw.{params.save_format}"
    if params.save_format == "fif":
        raw.save(output_file, overwrite=params.overwrite)
    elif params.save_format == "edf":
        mne.export.export_raw(output_file, raw, fmt="edf", overwrite=params.overwrite)
    elif params.save_format == "bdf":
        mne.export.export_raw(output_file, raw, fmt="bdf", overwrite=params.overwrite)

    epochs_file = None
    if epochs is not None:
        epochs_file = output_path / f"epochs.{params.save_format}"
        epochs.save(epochs_file, overwrite=params.overwrite)

    report = {
        "input_file": params.raw_file,
        "output_file": str(output_file),
        "epochs_file": str(epochs_file) if epochs_file else None,
        "original_sfreq": orig_sfreq,
        "final_sfreq": raw.info["sfreq"],
        "n_channels_orig": orig_nchan,
        "n_channels_final": len(raw.ch_names),
        "bad_channels": all_bads,
        "processing_steps": processing_log,
        "duration_seconds": raw.times[-1],
        "n_epochs": len(epochs) if epochs else None,
    }

    report_file = output_path / "preprocessing_report.json"
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2)

    return {
        "outputs": {
            "preprocessed_data": str(output_file),
            "epochs": str(epochs_file) if epochs_file else None,
            "report": str(report_file),
        },
        "processing_log": processing_log,
        "statistics": {
            "duration": raw.times[-1],
            "n_channels": len(raw.ch_names),
            "sampling_rate": raw.info["sfreq"],
            "n_bad_channels": len(all_bads),
            "n_epochs": len(epochs) if epochs else None,
        },
    }


__all__ = [
    "MNEPreprocessingParameters",
    "mne_preprocessing_from_payload",
    "run_mne_preprocessing",
]
