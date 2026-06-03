"""Shared helpers for MNE FOOOF spectral parameterisation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from brain_researcher.core.utils import configure_mne_environment


@dataclass(frozen=True)
class MNEFOOOFParameters:
    output_dir: str
    freq_range: tuple[float, float] = (1.0, 40.0)
    peak_width_limits: tuple[float, float] = (0.5, 12.0)
    max_n_peaks: int = 6
    min_peak_height: float = 0.0
    peak_threshold: float = 2.0
    aperiodic_mode: str = "fixed"
    raw_file: str | None = None
    epochs_file: str | None = None
    psd_file: str | None = None
    picks: tuple[str, ...] | None = None
    group_mode: bool = False
    save_model: bool = True
    save_report: bool = True
    save_plots: bool = True


def _ensure_path(path: str | None) -> str | None:
    if path is None:
        return None
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    return str(p)


def _fit_aperiodic(
    freqs: np.ndarray, psd: np.ndarray
) -> tuple[float, float, np.ndarray]:
    log_freqs = np.log10(freqs)
    log_power = np.log10(psd)
    design = np.column_stack([np.ones_like(log_freqs), -log_freqs])
    coeffs, *_ = np.linalg.lstsq(design, log_power, rcond=None)
    offset, exponent = coeffs
    fit = offset - exponent * log_freqs
    return float(offset), float(exponent), fit


def _extract_peaks(
    freqs: np.ndarray,
    psd: np.ndarray,
    *,
    min_peak_height: float,
    peak_threshold: float,
    peak_width_limits: tuple[float, float],
    max_n_peaks: int,
) -> tuple[list[float], list[list[float]]]:
    from scipy.signal import find_peaks, peak_widths

    offset, exponent, aperiodic_fit = _fit_aperiodic(freqs, psd)
    residual = np.log10(psd) - aperiodic_fit
    peaks, props = find_peaks(
        residual, height=min_peak_height, prominence=peak_threshold
    )
    peak_params: list[list[float]] = []
    if peaks.size:
        widths, _, _, _ = peak_widths(residual, peaks, rel_height=0.5)
        df = float(freqs[1] - freqs[0])
        widths_hz = widths * df
        for idx, peak_idx in enumerate(peaks):
            bw = float(widths_hz[idx])
            if bw < peak_width_limits[0] or bw > peak_width_limits[1]:
                continue
            cf = float(freqs[peak_idx])
            amp = float(residual[peak_idx])
            peak_params.append([cf, amp, bw])
        peak_params.sort(key=lambda row: row[1], reverse=True)
        peak_params = peak_params[: max_n_peaks or len(peak_params)]
    return [offset, exponent], peak_params


def mne_fooof_from_payload(payload: dict[str, Any]) -> MNEFOOOFParameters:
    picks = payload.get("picks")
    picks_tuple = None
    if isinstance(picks, str):
        picks_tuple = (picks,)
    elif isinstance(picks, list | tuple):
        picks_tuple = tuple(picks)
    return MNEFOOOFParameters(
        output_dir=str(payload["output_dir"]),
        freq_range=tuple(payload.get("freq_range", (1.0, 40.0))),
        peak_width_limits=tuple(payload.get("peak_width_limits", (0.5, 12.0))),
        max_n_peaks=int(payload.get("max_n_peaks", 6)),
        min_peak_height=float(payload.get("min_peak_height", 0.0)),
        peak_threshold=float(payload.get("peak_threshold", 2.0)),
        aperiodic_mode=str(payload.get("aperiodic_mode", "fixed")),
        raw_file=payload.get("raw_file"),
        epochs_file=payload.get("epochs_file"),
        psd_file=payload.get("psd_file"),
        picks=picks_tuple,
        group_mode=bool(payload.get("group_mode", False)),
        save_model=bool(payload.get("save_model", True)),
        save_report=bool(payload.get("save_report", True)),
        save_plots=bool(payload.get("save_plots", True)),
    )


def run_mne_fooof(params: MNEFOOOFParameters) -> dict[str, Any]:
    output_dir = Path(params.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    freqs: np.ndarray
    psd: np.ndarray
    info = None
    configure_mne_environment()
    import mne  # local import to avoid config lock at import time

    if params.psd_file:
        psd_path = Path(_ensure_path(params.psd_file))
        if psd_path.suffix == ".npz":
            loaded = np.load(psd_path)
            psd = loaded["psd"]
            freqs = loaded["freqs"]
        else:
            psd = np.load(psd_path)
            freqs = np.linspace(
                params.freq_range[0], params.freq_range[1], psd.shape[-1]
            )
    elif params.epochs_file:
        epochs = mne.read_epochs(
            _ensure_path(params.epochs_file), preload=True, verbose=False
        )
        info = epochs.info
        spectrum = epochs.compute_psd(
            method="welch",
            fmin=params.freq_range[0],
            fmax=params.freq_range[1],
            verbose=False,
        )
        freqs = spectrum.freqs
        data = spectrum.get_data()
        psd = data.mean(axis=0)
    elif params.raw_file:
        raw = mne.io.read_raw_fif(
            _ensure_path(params.raw_file), preload=True, verbose=False
        )
        info = raw.info
        spectrum = raw.compute_psd(
            method="welch",
            fmin=params.freq_range[0],
            fmax=params.freq_range[1],
            verbose=False,
        )
        freqs = spectrum.freqs
        psd = spectrum.get_data()
    else:
        raise ValueError("One of raw_file, epochs_file, or psd_file is required")

    if params.picks:
        if info is None:
            raise ValueError("picks requires raw_file or epochs_file")
        picks = mne.pick_channels(info["ch_names"], include=list(params.picks))
        psd = psd[picks]

    used_fooof_package = True
    try:
        from fooof import FOOOF, FOOOFGroup
    except ModuleNotFoundError:
        used_fooof_package = False
        FOOOF = None  # type: ignore[assignment]
        FOOOFGroup = None  # type: ignore[assignment]

    if used_fooof_package:
        if params.group_mode:
            fg_group = FOOOFGroup(
                peak_width_limits=params.peak_width_limits,
                max_n_peaks=params.max_n_peaks,
                min_peak_height=params.min_peak_height,
                peak_threshold=params.peak_threshold,
                aperiodic_mode=params.aperiodic_mode,
            )
            fg_group.fit(freqs, psd)
            fooof_summary = {
                "aperiodic_params": [
                    ap.tolist() for ap in fg_group.get_params("aperiodic_params")
                ],
                "peak_params": [
                    pk.tolist() for pk in fg_group.get_params("peak_params")
                ],
                "n_channels": psd.shape[0],
            }
        else:
            model = FOOOF(
                peak_width_limits=params.peak_width_limits,
                max_n_peaks=params.max_n_peaks,
                min_peak_height=params.min_peak_height,
                peak_threshold=params.peak_threshold,
                aperiodic_mode=params.aperiodic_mode,
            )
            psd_mean = psd.mean(axis=0)
            model.fit(freqs, psd_mean)
            fooof_summary = {
                "aperiodic_params": model.aperiodic_params_.tolist(),
                "peak_params": model.peak_params_.tolist(),
                "n_channels": psd.shape[0],
            }
    else:
        if params.group_mode:
            aperiodic_params = []
            peak_params = []
            for ch_psd in psd:
                ap, peaks = _extract_peaks(
                    freqs,
                    ch_psd,
                    min_peak_height=params.min_peak_height,
                    peak_threshold=params.peak_threshold,
                    peak_width_limits=params.peak_width_limits,
                    max_n_peaks=params.max_n_peaks,
                )
                aperiodic_params.append(ap)
                peak_params.append(peaks)
            fooof_summary = {
                "aperiodic_params": aperiodic_params,
                "peak_params": peak_params,
                "n_channels": psd.shape[0],
            }
        else:
            psd_mean = psd.mean(axis=0)
            ap, peaks = _extract_peaks(
                freqs,
                psd_mean,
                min_peak_height=params.min_peak_height,
                peak_threshold=params.peak_threshold,
                peak_width_limits=params.peak_width_limits,
                max_n_peaks=params.max_n_peaks,
            )
            fooof_summary = {
                "aperiodic_params": ap,
                "peak_params": peaks,
                "n_channels": psd.shape[0],
            }

    model_path = None
    if params.save_model:
        model_path = output_dir / "fooof_model.json"
        model_path.write_text(json.dumps(fooof_summary, indent=2), encoding="utf-8")

    report_path = None
    if params.save_report:
        report_path = output_dir / "fooof_report.json"
        report_path.write_text(json.dumps(fooof_summary, indent=2), encoding="utf-8")

    plots = {}
    if params.save_plots:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(5, 3))
        ax.plot(freqs, psd.mean(axis=0))
        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel("Power")
        plot_path = output_dir / "fooof_power.png"
        fig.tight_layout()
        fig.savefig(plot_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        plots["power"] = str(plot_path)

    outputs = {
        "model": str(model_path) if model_path else None,
        "report": str(report_path) if report_path else None,
        "plots": plots,
    }

    return {
        "outputs": outputs,
        "summary": fooof_summary,
        "message": "FOOOF analysis completed.",
        "used_fooof_package": used_fooof_package,
    }


__all__ = [
    "MNEFOOOFParameters",
    "mne_fooof_from_payload",
    "run_mne_fooof",
]
