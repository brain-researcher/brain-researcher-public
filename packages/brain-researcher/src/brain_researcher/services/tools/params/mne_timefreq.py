"""Shared helpers for MNE time-frequency analysis."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

from brain_researcher.core.analysis.connectivity_contracts import (
    FeatureContract,
    write_feature_contract,
)
from brain_researcher.core.utils import configure_mne_environment


@dataclass(frozen=True)
class MNETimeFreqParameters:
    epochs_file: str
    output_dir: str
    method: str = "morlet"
    freqs: tuple[float, ...] | None = None
    freq_min: float = 1.0
    freq_max: float = 40.0
    n_freqs: int = 30
    n_cycles: tuple[float, ...] | None = None
    use_fft: bool = True
    average: bool = True
    return_itc: bool = True
    baseline: tuple[float | None, float | None] | None = (None, 0.0)
    baseline_mode: str = "mean"
    compute_psd: bool = True
    psd_method: str = "welch"
    save_plots: bool = True
    picks: tuple[str, ...] | None = None
    time_bandwidth: float = 4.0
    n_tapers: int | None = None
    save_format: str = "hdf5"
    compute_connectivity: bool = False
    connectivity_method: str = "coherence"
    connectivity_pairs: tuple[tuple[str, str], ...] | None = None
    compute_band_power: bool = False
    bands: dict[str, tuple[float, float]] | None = None
    compute_statistics: bool = False
    stat_threshold: float = 0.05


def _ensure_tuple(val: Any) -> tuple[Any, ...] | None:
    if val is None:
        return None
    if isinstance(val, tuple | list | set):
        return tuple(val)
    return (val,)


def mne_timefreq_from_payload(payload: dict[str, Any]) -> MNETimeFreqParameters:
    picks = payload.get("picks")
    picks_tuple: tuple[str, ...] | None
    if isinstance(picks, str):
        picks_tuple = (picks,)
    else:
        picks_tuple = _ensure_tuple(picks)

    freqs = payload.get("freqs")
    if freqs is not None and isinstance(freqs, np.ndarray):
        freqs = freqs.tolist()

    n_cycles = payload.get("n_cycles")
    if isinstance(n_cycles, np.ndarray):
        n_cycles = n_cycles.tolist()

    baseline = payload.get("baseline", (None, 0))
    if baseline is not None:
        baseline = tuple(baseline)

    connectivity_pairs = payload.get("connectivity_pairs")
    if connectivity_pairs is not None:
        connectivity_pairs = tuple(tuple(pair) for pair in connectivity_pairs)

    bands_payload = payload.get("bands")
    if bands_payload is not None:
        bands_dict = {
            str(k): (float(v[0]), float(v[1])) for k, v in bands_payload.items()
        }
    else:
        bands_dict = None

    return MNETimeFreqParameters(
        epochs_file=str(payload["epochs_file"]),
        output_dir=str(payload["output_dir"]),
        method=str(payload.get("method", "morlet")),
        freqs=_ensure_tuple(freqs),
        freq_min=float(payload.get("freq_min", 1.0)),
        freq_max=float(payload.get("freq_max", 40.0)),
        n_freqs=int(payload.get("n_freqs", 30)),
        n_cycles=_ensure_tuple(n_cycles),
        use_fft=bool(payload.get("use_fft", True)),
        average=bool(payload.get("average", True)),
        return_itc=bool(payload.get("return_itc", True)),
        baseline=baseline,
        baseline_mode=str(payload.get("baseline_mode", "mean")),
        compute_psd=bool(payload.get("compute_psd", True)),
        psd_method=str(payload.get("psd_method", "welch")),
        save_plots=bool(payload.get("save_plots", True)),
        picks=picks_tuple,
        time_bandwidth=float(payload.get("time_bandwidth", 4.0)),
        n_tapers=payload.get("n_tapers"),
        save_format=str(payload.get("save_format", "hdf5")),
        compute_connectivity=bool(payload.get("compute_connectivity", False)),
        connectivity_method=str(payload.get("connectivity_method", "coherence")),
        connectivity_pairs=connectivity_pairs,
        compute_band_power=bool(payload.get("compute_band_power", False)),
        bands=bands_dict,
        compute_statistics=bool(payload.get("compute_statistics", False)),
        stat_threshold=float(payload.get("stat_threshold", 0.05)),
    )


def _generate_freqs(params: MNETimeFreqParameters) -> np.ndarray:
    if params.freqs:
        return np.asarray(params.freqs, dtype=float)
    return np.logspace(
        np.log10(params.freq_min),
        np.log10(params.freq_max),
        params.n_freqs,
    )


def _generate_n_cycles(
    freqs: np.ndarray, params: MNETimeFreqParameters
) -> float | np.ndarray:
    if params.n_cycles is None:
        return np.maximum(1.0, freqs / 2.0)
    if len(params.n_cycles) == 1:
        return float(params.n_cycles[0])
    if len(params.n_cycles) == len(freqs):
        return np.asarray(params.n_cycles, dtype=float)
    return np.maximum(1.0, freqs / 2.0)


def run_mne_timefreq(params: MNETimeFreqParameters) -> dict[str, Any]:
    configure_mne_environment()
    cache_dir = Path(params.output_dir) / ".numba-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["NUMBA_CACHE_DIR"] = str(cache_dir)
    os.environ.setdefault("NUMBA_DISABLE_CACHING", "1")
    os.environ.setdefault("MNE_HOME", str(Path(params.output_dir)))

    import matplotlib

    matplotlib.use("Agg")

    import mne

    epochs = mne.read_epochs(params.epochs_file, preload=True)

    if params.picks:
        try:
            epochs = epochs.copy().pick(list(params.picks))
        except Exception:
            pass

    freqs = _generate_freqs(params)
    sfreq = float(epochs.info.get("sfreq", 1.0))
    nyquist = sfreq / 2.0
    freqs = freqs[freqs < nyquist]
    if freqs.size == 0:
        freqs = np.array([nyquist * 0.8])
    n_cycles = _generate_n_cycles(freqs, params)
    if isinstance(n_cycles, np.ndarray) and n_cycles.shape[0] != freqs.shape[0]:
        base_cycles = float(params.n_cycles[0]) if params.n_cycles else 7.0
        n_cycles = np.full_like(freqs, base_cycles, dtype=float)
    epoch_duration = epochs.times[-1] - epochs.times[0]
    if isinstance(n_cycles, np.ndarray):
        max_cycles = np.maximum(1.0, epoch_duration * freqs)
        n_cycles = np.minimum(n_cycles, max_cycles)
        valid_mask = (n_cycles / np.maximum(freqs, 1e-6)) <= max(
            epoch_duration, 1e-6
        ) * 1.0
        freqs = freqs[valid_mask]
        n_cycles = n_cycles[valid_mask]
    else:
        max_cycles_scalar = max(1.0, epoch_duration * freqs.max())
        n_cycles = float(min(n_cycles, max_cycles_scalar))
        min_freq_allowed = n_cycles / max(epoch_duration, 1e-6)
        freqs = freqs[freqs >= min_freq_allowed]
        if freqs.size == 0:
            freqs = np.array([min_freq_allowed])
        n_cycles = np.full_like(freqs, n_cycles, dtype=float)

    if freqs.size == 0:
        freqs = np.array([nyquist * 0.5])
        n_cycles = np.full_like(freqs, 1.0, dtype=float)

    output_path = Path(params.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    used_mne_timefreq = True

    tfr = None
    itc = None
    try:
        compute_kwargs = {
            "freqs": freqs,
            "n_cycles": n_cycles,
            "use_fft": params.use_fft,
            "average": params.average,
            "return_itc": params.return_itc,
            "n_jobs": 1,
        }
        if params.method.lower() == "multitaper":
            compute_kwargs.update(time_bandwidth=params.time_bandwidth)
            tfr = epochs.compute_tfr(method="multitaper", **compute_kwargs)
        else:
            tfr = epochs.compute_tfr(method="morlet", **compute_kwargs)
        if isinstance(tfr, tuple):
            tfr, itc = tfr
    except Exception as exc:
        import warnings

        warnings.warn(
            f"Falling back to simple STFT for time-frequency: {exc}",
            stacklevel=2,
        )
        used_mne_timefreq = False
        data = epochs.get_data()
        from scipy.signal import stft

        channel_power = []
        for ch_idx in range(data.shape[1]):
            avg_signal = data[:, ch_idx, :].mean(axis=0)
            f_vals, t_vals, Zxx = stft(
                avg_signal, fs=sfreq, nperseg=min(data.shape[-1], 64)
            )
            channel_power.append(np.abs(Zxx))
        stft_array = np.stack(channel_power, axis=0)
        tfr = SimpleNamespace(
            data=stft_array,
            times=t_vals,
            freqs=f_vals,
            nave=data.shape[0],
            ch_names=epochs.ch_names,
            info=epochs.info.copy(),
        )

    if params.baseline is not None and hasattr(tfr, "apply_baseline"):
        baseline = params.baseline
        if isinstance(baseline, tuple):
            try:
                tfr.apply_baseline(baseline=baseline, mode=params.baseline_mode)
            except Exception:
                pass

    if params.save_format.lower() == "hdf5" and hasattr(tfr, "save"):
        tfr_file = output_path / f"tfr_{params.method.lower()}.h5"
        tfr.save(str(tfr_file), overwrite=True)
    else:
        tfr_file = output_path / f"tfr_{params.method.lower()}.npz"
        np.savez(
            tfr_file,
            data=tfr.data,
            times=tfr.times,
            freqs=tfr.freqs,
            nave=getattr(tfr, "nave", 1),
        )

    itc_path = None
    if params.return_itc and itc is not None:
        itc_path = output_path / f"itc_{params.method.lower()}.h5"
        try:
            itc.save(str(itc_path), overwrite=True)
        except Exception:
            np.savez(
                itc_path.with_suffix(".npz"),
                data=itc.data,
                times=itc.times,
                freqs=itc.freqs,
                nave=itc.nave,
            )
            itc_path = itc_path.with_suffix(".npz")

    psd_path = None
    psd_summary = None
    psd_enabled = params.compute_psd
    if psd_enabled:
        try:
            psd = epochs.compute_psd(
                method=params.psd_method,
                fmin=params.freq_min,
                fmax=params.freq_max,
            )
            psd_data, psd_freqs = psd.get_data(return_freqs=True)
            psd_path = output_path / "psd_power.npz"
            np.savez(psd_path, psd=psd_data, freqs=psd_freqs)
            psd_summary = {
                "shape": list(psd_data.shape),
                "mean": float(np.mean(psd_data)),
                "max": float(np.max(psd_data)),
            }
        except Exception:
            psd_enabled = False

    from matplotlib import pyplot as plt

    plots: dict[str, str] = {}
    if params.save_plots:
        power = tfr.data.mean(axis=0)
        fig, ax = plt.subplots(figsize=(6, 4))
        im = ax.imshow(
            power,
            aspect="auto",
            origin="lower",
            extent=[tfr.times[0], tfr.times[-1], tfr.freqs[0], tfr.freqs[-1]],
            cmap="magma",
        )
        fig.colorbar(im, ax=ax, shrink=0.8)
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Frequency (Hz)")
        ax.set_title(f"{params.method.title()} Power")
        plot_path = output_path / "tfr_power.png"
        fig.tight_layout()
        fig.savefig(plot_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        plots["power"] = str(plot_path)

    def _default_bands() -> dict[str, tuple[float, float]]:
        return {
            "delta": (1.0, 4.0),
            "theta": (4.0, 8.0),
            "alpha": (8.0, 13.0),
            "beta": (13.0, 30.0),
            "gamma": (30.0, 45.0),
        }

    summary = {
        "method": params.method,
        "n_channels": int(tfr.data.shape[0]),
        "n_freqs": int(tfr.data.shape[1]),
        "n_times": int(tfr.data.shape[2]),
        "average": params.average,
        "baseline": params.baseline,
        "psd": psd_summary,
    }

    if params.compute_band_power:
        bands = params.bands or _default_bands()
        band_results: dict[str, dict[str, float]] = {}
        for band_name, (low, high) in bands.items():
            mask = (tfr.freqs >= low) & (tfr.freqs <= high)
            if not np.any(mask):
                continue
            band_power = tfr.data[:, mask, :].mean(axis=(1, 2))
            band_results[band_name] = {
                "mean_power": float(band_power.mean()),
                "max_power": float(band_power.max()),
            }
        band_power_path = output_path / "band_power.json"
        with open(band_power_path, "w", encoding="utf-8") as fp:
            json.dump(band_results, fp, indent=2)
        summary["band_power"] = band_results
    else:
        band_power_path = None

    connectivity_summary = None
    feature_contract_path: Path | None = None
    if params.compute_connectivity:
        power_time = tfr.data.mean(axis=1)
        if power_time.shape[1] > 1:
            conn_matrix = np.corrcoef(power_time)
        else:
            conn_matrix = np.ones((power_time.shape[0], power_time.shape[0]))
        connectivity_path = output_path / "timefreq_connectivity.npy"
        np.save(connectivity_path, conn_matrix)
        connectivity_summary = {
            "matrix_path": str(connectivity_path),
            "mean": float(np.mean(conn_matrix)),
            "max": float(np.max(conn_matrix)),
        }
        try:
            contract = FeatureContract(
                matrix_kind="timefreq_power_correlation",
                source_level="mne_timefreq_power",
                n_rois=int(conn_matrix.shape[0]),
                n_timepoints=int(power_time.shape[1]),
                effective_n_timepoints=int(power_time.shape[1]),
                covariance_estimator="PearsonCorrelation",
                transform_state="raw_connectivity",
                extras={
                    "n_freqs": int(tfr.data.shape[1]),
                    "method": params.method,
                    "connectivity_method": params.connectivity_method,
                },
            )
            feature_contract_path = write_feature_contract(contract, output_path)
        except Exception:
            feature_contract_path = None
        summary["connectivity"] = connectivity_summary
    else:
        connectivity_path = None

    statistics_summary = None
    stats_path: Path | None = None
    if params.compute_statistics and params.baseline is not None:
        baseline = params.baseline
        tfr_times = tfr.times
        bmin = baseline[0] if baseline[0] is not None else tfr_times[0]
        bmax = baseline[1] if baseline[1] is not None else tfr_times[-1]
        baseline_mask = (tfr_times >= bmin) & (tfr_times <= bmax)
        if np.any(baseline_mask):
            baseline_data = tfr.data[:, :, baseline_mask]
            baseline_mean = baseline_data.mean(axis=-1)
            baseline_std = baseline_data.std(axis=-1) + 1e-6
            overall_mean = tfr.data.mean(axis=-1)
            zscores = (overall_mean - baseline_mean) / baseline_std
            statistics_summary = {
                "channel_max_z": [float(z) for z in zscores.max(axis=-1)],
                "global_max_z": float(np.max(zscores)),
                "threshold": params.stat_threshold,
            }
            stats_path = output_path / "timefreq_statistics.json"
            with open(stats_path, "w", encoding="utf-8") as fp:
                json.dump(statistics_summary, fp, indent=2)
        summary["statistics"] = statistics_summary

    report = {
        "summary": summary,
        "tfr_mean": float(np.mean(tfr.data)),
        "tfr_max": float(np.max(tfr.data)),
    }

    report_path = output_path / "timefreq_report.json"
    with open(report_path, "w", encoding="utf-8") as fp:
        json.dump(report, fp, indent=2)

    return {
        "outputs": {
            "tfr": str(tfr_file),
            "itc": str(itc_path) if itc_path else None,
            "psd": str(psd_path) if psd_path else None,
            "report": str(report_path),
            "plots": plots,
            "band_power": str(band_power_path) if band_power_path else None,
            "connectivity": str(connectivity_path) if connectivity_path else None,
            "feature_contract": (
                str(feature_contract_path) if feature_contract_path else None
            ),
            "statistics": str(stats_path) if statistics_summary else None,
        },
        "summary": summary,
        "message": "Time-frequency analysis completed.",
        "used_mne_timefreq_package": used_mne_timefreq,
    }


__all__ = [
    "MNETimeFreqParameters",
    "mne_timefreq_from_payload",
    "run_mne_timefreq",
]
