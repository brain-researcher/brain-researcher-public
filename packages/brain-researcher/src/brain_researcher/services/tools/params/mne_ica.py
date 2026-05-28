"""Shared helpers for MNE ICA artifact removal."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
from brain_researcher.core.utils import configure_mne_environment


@dataclass(frozen=True)
class MNEICAParameters:
    raw_file: str
    output_dir: str
    n_components: Optional[Union[int, float]] = None
    method: str = "fastica"
    max_iter: Union[int, str] = "auto"
    random_state: Optional[int] = 42
    l_freq: Optional[float] = 1.0
    h_freq: Optional[float] = None
    detect_artifacts: Tuple[str, ...] = field(default_factory=lambda: ("eog", "ecg"))
    eog_channels: Tuple[str, ...] = field(default_factory=tuple)
    ecg_channels: Tuple[str, ...] = field(default_factory=tuple)
    eog_threshold: float = 3.0
    ecg_threshold: float = 3.0
    muscle_threshold: float = 5.0
    exclude_components: Tuple[int, ...] = field(default_factory=tuple)
    n_max_eog: int = 2
    n_max_ecg: int = 2
    n_pca_components: Optional[int] = None
    fit_params: Optional[Dict[str, Any]] = None
    reject: Optional[Dict[str, float]] = None
    picks: Tuple[str, ...] = field(default_factory=tuple)
    save_ica: bool = True
    apply_ica: bool = True
    overwrite: bool = False
    plot_components: bool = True
    plot_sources: bool = True
    plot_overlay: bool = True


def mne_ica_from_payload(payload: Dict[str, Any]) -> MNEICAParameters:
    def _tuple(val):
        if val is None:
            return tuple()
        if isinstance(val, (list, tuple, set)):
            return tuple(val)
        return (val,)

    return MNEICAParameters(
        raw_file=str(payload["raw_file"]),
        output_dir=str(payload["output_dir"]),
        n_components=payload.get("n_components"),
        method=str(payload.get("method", "fastica")),
        max_iter=payload.get("max_iter", "auto"),
        random_state=payload.get("random_state", 42),
        l_freq=payload.get("l_freq", 1.0),
        h_freq=payload.get("h_freq"),
        detect_artifacts=_tuple(payload.get("detect_artifacts", ("eog", "ecg"))),
        eog_channels=_tuple(payload.get("eog_channels")),
        ecg_channels=_tuple(payload.get("ecg_channels")),
        eog_threshold=float(payload.get("eog_threshold", 3.0)),
        ecg_threshold=float(payload.get("ecg_threshold", 3.0)),
        muscle_threshold=float(payload.get("muscle_threshold", 5.0)),
        exclude_components=_tuple(payload.get("exclude_components")),
        n_max_eog=int(payload.get("n_max_eog", 2)),
        n_max_ecg=int(payload.get("n_max_ecg", 2)),
        n_pca_components=payload.get("n_pca_components"),
        fit_params=payload.get("fit_params"),
        reject=payload.get("reject"),
        picks=_tuple(payload.get("picks")),
        save_ica=bool(payload.get("save_ica", True)),
        apply_ica=bool(payload.get("apply_ica", True)),
        overwrite=bool(payload.get("overwrite", False)),
        plot_components=bool(payload.get("plot_components", True)),
        plot_sources=bool(payload.get("plot_sources", True)),
        plot_overlay=bool(payload.get("plot_overlay", True)),
    )


def run_mne_ica(params: MNEICAParameters) -> Dict[str, Any]:
    configure_mne_environment()
    cache_dir = Path(params.output_dir) / ".numba-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["NUMBA_CACHE_DIR"] = str(cache_dir)
    os.environ.setdefault("NUMBA_DISABLE_CACHING", "1")
    os.environ.setdefault("MNE_HOME", str(Path(params.output_dir)))

    import mne
    from scipy import signal
    import matplotlib

    matplotlib.use("Agg")

    raw = mne.io.read_raw(params.raw_file, preload=True)
    output_path = Path(params.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    if params.l_freq is not None or params.h_freq is not None:
        raw.filter(l_freq=params.l_freq, h_freq=params.h_freq)

    picks = mne.pick_types(raw.info, eeg=True, meg=True, exclude="bads")
    if params.picks:
        picks = mne.pick_channels(raw.info["ch_names"], include=list(params.picks), exclude="bads")

    ica = mne.preprocessing.ICA(
        n_components=params.n_components,
        method=params.method,
        max_iter=params.max_iter,
        random_state=params.random_state,
    )
    ica.fit(raw, picks=picks, reject=params.reject)

    exclude: List[int] = list(params.exclude_components)
    detect = {name.lower() for name in params.detect_artifacts}

    detection: Dict[str, List[int]] = {"eog": [], "ecg": [], "muscle": []}

    if "eog" in detect:
        try:
            eog_inds, _ = ica.find_bads_eog(
                raw,
                ch_name=params.eog_channels[0] if params.eog_channels else None,
                threshold=params.eog_threshold,
            )
        except RuntimeError:
            detection["eog"] = []
        else:
            eog_inds = list(eog_inds[: params.n_max_eog])
            detection["eog"] = eog_inds
            exclude.extend(eog_inds)

    if "ecg" in detect:
        try:
            ecg_inds, _ = ica.find_bads_ecg(
                raw,
                ch_name=params.ecg_channels[0] if params.ecg_channels else None,
                threshold=params.ecg_threshold,
                method="correlation",
            )
            ecg_inds = list(ecg_inds[: params.n_max_ecg])
            detection["ecg"] = ecg_inds
            exclude.extend(ecg_inds)
        except Exception:
            detection["ecg"] = []

    if "muscle" in detect:
        sources = ica.get_sources(raw).get_data()
        muscle_indices: List[int] = []
        for idx in range(ica.n_components_):
            comp = sources[idx, :]
            freqs, psd = signal.welch(comp, raw.info["sfreq"], nperseg=1024)
            mask = (freqs >= 30) & (freqs <= 100)
            muscle_power = np.mean(psd[mask])
            low_power = np.mean(psd[(freqs >= 1) & (freqs <= 30)])
            if low_power > 0 and muscle_power / low_power > params.muscle_threshold:
                muscle_indices.append(idx)
        detection["muscle"] = muscle_indices
        exclude.extend(muscle_indices)

    exclude = sorted(set(exclude))
    ica.exclude = exclude

    plots: Dict[str, str] = {}
    if params.plot_components and ica.n_components_ > 0:
        try:
            fig = ica.plot_components(show=False)
        except RuntimeError:
            fig = None
        if fig is not None:
            comp_path = output_path / "ica_components.png"
            if isinstance(fig, list):
                fig[0].savefig(comp_path)
            else:
                fig.savefig(comp_path)
            plots["components"] = str(comp_path)

    if params.plot_sources:
        fig = ica.plot_sources(raw, show=False)
        src_path = output_path / "ica_sources.png"
        fig.savefig(src_path)
        plots["sources"] = str(src_path)

    if params.plot_overlay and exclude:
        fig = ica.plot_overlay(raw, exclude=exclude, show=False)
        ov_path = output_path / "ica_overlay.png"
        fig.savefig(ov_path)
        plots["overlay"] = str(ov_path)

    cleaned_file = None
    raw_clean = raw.copy()
    if params.apply_ica and exclude:
        ica.apply(raw_clean, exclude=exclude)
        cleaned_file = output_path / "ica_cleaned_raw.fif"
        raw_clean.save(cleaned_file, overwrite=params.overwrite)
    elif params.apply_ica:
        cleaned_file = Path(params.raw_file)

    ica_path = None
    if params.save_ica:
        ica_path = output_path / "ica_solution-ica.fif"
        ica.save(ica_path, overwrite=params.overwrite)

    exclude_serializable = [int(x) for x in exclude]
    detection_serializable = {
        key: [int(x) for x in value] for key, value in detection.items()
    }
    report = {
        "raw_file": params.raw_file,
        "n_components": int(ica.n_components_),
        "method": params.method,
        "excluded_components": exclude_serializable,
        "artifact_detection": detection_serializable,
        "plots": plots,
        "ica_solution": str(ica_path) if ica_path else None,
        "cleaned_file": str(cleaned_file) if cleaned_file else None,
    }
    report_path = output_path / "ica_report.json"
    with open(report_path, "w") as f:
        import json

        json.dump(report, f, indent=2)

    return {
        "outputs": {
            "cleaned": str(cleaned_file) if cleaned_file else None,
            "ica_solution": str(ica_path) if ica_path else None,
            "report": str(report_path),
            "plots": plots,
        },
        "artifact_components": {
            "total_excluded": int(len(exclude_serializable)),
            "indices": exclude_serializable,
            "by_type": detection_serializable,
        },
    }


__all__ = [
    "MNEICAParameters",
    "mne_ica_from_payload",
    "run_mne_ica",
]
