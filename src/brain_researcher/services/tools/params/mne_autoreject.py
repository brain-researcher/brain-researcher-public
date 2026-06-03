"""Shared helpers for MNE Autoreject automated artifact rejection."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
from brain_researcher.core.utils import configure_mne_environment


@dataclass(frozen=True)
class MNEAutorejectParameters:
    epochs_file: str
    output_dir: str
    n_interpolate: Optional[Tuple[int, ...]] = None
    consensus: Optional[Tuple[float, ...]] = None
    cv: int = 5
    thresh_method: str = "bayesian_optimization"
    n_jobs: int = 1
    random_state: Optional[int] = 42
    mode: str = "repair"
    picks: Optional[Union[str, Tuple[str, ...]]] = None
    use_local: bool = True
    use_global: bool = True
    save_epochs: bool = True
    save_report: bool = True
    save_plots: bool = True
    verbose: bool = True


def _ensure_tuple(value: Any) -> Optional[Tuple[Any, ...]]:
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        return tuple(value)
    return (value,)


def _ensure_picks(value: Any) -> Optional[Union[str, Tuple[str, ...]]]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return tuple(value)


def mne_autoreject_from_payload(payload: Dict[str, Any]) -> MNEAutorejectParameters:
    return MNEAutorejectParameters(
        epochs_file=str(payload["epochs_file"]),
        output_dir=str(payload["output_dir"]),
        n_interpolate=_ensure_tuple(payload.get("n_interpolate")),
        consensus=_ensure_tuple(payload.get("consensus")),
        cv=int(payload.get("cv", 5)),
        thresh_method=str(payload.get("thresh_method", "bayesian_optimization")),
        n_jobs=int(payload.get("n_jobs", 1)),
        random_state=(
            None
            if payload.get("random_state", 42) is None
            else int(payload.get("random_state", 42))
        ),
        mode=str(payload.get("mode", "repair")),
        picks=_ensure_picks(payload.get("picks")),
        use_local=bool(payload.get("use_local", True)),
        use_global=bool(payload.get("use_global", True)),
        save_epochs=bool(payload.get("save_epochs", True)),
        save_report=bool(payload.get("save_report", True)),
        save_plots=bool(payload.get("save_plots", True)),
        verbose=bool(payload.get("verbose", True)),
    )


def _autoreject_with_package(epochs, params: MNEAutorejectParameters, pick_idx):
    from autoreject import AutoReject

    ar = AutoReject(
        n_interpolate=params.n_interpolate,
        consensus=params.consensus,
        cv=params.cv,
        thresh_method=params.thresh_method,
        n_jobs=params.n_jobs,
        random_state=params.random_state,
        picks=pick_idx,
        verbose="tqdm",
    )
    epochs_clean = ar.fit_transform(epochs)
    reject_log = ar.get_reject_log(epochs)
    thresholds: Dict[str, Any] = {}
    if hasattr(ar, "threshes_"):
        threshes = ar.threshes_
        thresholds["thresholds"] = threshes.tolist() if hasattr(threshes, "tolist") else threshes
    if hasattr(ar, "consensus_"):
        thresholds["consensus"] = float(ar.consensus_)
    if hasattr(ar, "n_interpolate_"):
        thresholds["n_interpolate"] = int(ar.n_interpolate_)
    return epochs_clean, reject_log, thresholds


def _autoreject_fallback(epochs, params: MNEAutorejectParameters, pick_idx):
    from sklearn.model_selection import KFold

    data = epochs.get_data(picks=pick_idx)
    n_epochs, n_channels, _ = data.shape
    if pick_idx is None:
        channel_indices = np.arange(n_channels)
    else:
        channel_indices = np.asarray(pick_idx)
        if channel_indices.shape[0] != n_channels:
            channel_indices = channel_indices[:n_channels]
    random_state = params.random_state if params.random_state is not None else 42
    kf = KFold(n_splits=params.cv, shuffle=True, random_state=random_state)

    thresholds = np.zeros(n_channels)
    for ch_idx in range(n_channels):
        ch_data = data[:, ch_idx, :]
        cv_thresholds: List[float] = []
        for train_idx, _ in kf.split(ch_data):
            train_data = ch_data[train_idx]
            peak_to_peak = np.ptp(train_data, axis=1)
            cv_thresholds.append(float(np.percentile(peak_to_peak, 95)))
        thresholds[ch_idx] = np.mean(cv_thresholds)

    bad_epochs = np.zeros(n_epochs, dtype=bool)
    bad_channels = np.zeros((n_epochs, n_channels), dtype=bool)

    for epoch_idx in range(n_epochs):
        for ch_idx in range(n_channels):
            peak_to_peak = np.ptp(data[epoch_idx, ch_idx, :])
            if thresholds[ch_idx] > 0 and peak_to_peak > thresholds[ch_idx] * 1.5:
                bad_channels[epoch_idx, ch_idx] = True
        n_bad = np.sum(bad_channels[epoch_idx, :])
        if n_bad > max(1, int(n_channels * 0.3)):
            bad_epochs[epoch_idx] = True

    epochs_clean = epochs.copy()
    for epoch_idx in range(n_epochs):
        if bad_epochs[epoch_idx]:
            continue
        bad_indices = np.where(bad_channels[epoch_idx])[0]
        if len(bad_indices) == 0:
            continue
        if len(bad_indices) >= n_channels:
            bad_epochs[epoch_idx] = True
            continue
        for idx in bad_indices:
            ch = channel_indices[idx]
            neighbors: List[np.ndarray] = []
            neighbor_positions = np.where(channel_indices == ch)[0]
            pos = neighbor_positions[0] if len(neighbor_positions) else None
            if pos is not None:
                if pos > 0:
                    neighbors.append(data[epoch_idx, pos - 1, :])
                if pos < n_channels - 1:
                    neighbors.append(data[epoch_idx, pos + 1, :])
            if neighbors:
                epochs_clean._data[epoch_idx, ch, :] = np.mean(neighbors, axis=0)

    good_mask = ~bad_epochs
    epochs_clean = epochs_clean[good_mask]

    reject_log = {
        "bad_epochs": bad_epochs,
        "labels": bad_channels,
        "n_bad_epochs": int(np.sum(bad_epochs)),
        "n_interpolated": int(np.sum(bad_channels[good_mask])),
    }
    return epochs_clean, reject_log, {}


def _calculate_rejection_stats(epochs_original, epochs_clean, reject_log) -> Dict[str, Any]:
    n_epochs_original = len(epochs_original)
    n_epochs_clean = len(epochs_clean)
    n_rejected = n_epochs_original - n_epochs_clean
    stats: Dict[str, Any] = {
        "n_epochs_original": n_epochs_original,
        "n_epochs_clean": n_epochs_clean,
        "n_epochs_rejected": n_rejected,
        "rejection_rate": n_rejected / n_epochs_original if n_epochs_original else 0.0,
    }
    if isinstance(reject_log, dict):
        stats["n_bad_channels_total"] = int(np.sum(reject_log["labels"]))
        stats["n_interpolated"] = int(reject_log.get("n_interpolated", 0))
    elif hasattr(reject_log, "labels"):
        stats["n_bad_channels_total"] = int(np.sum(reject_log.labels))
    return stats


def _plot_reject_log(has_package: bool, epochs, reject_log, output_file: Path) -> None:
    import matplotlib.pyplot as plt

    if has_package and hasattr(reject_log, "plot"):
        reject_log.plot(show=False)
        plt.savefig(output_file, dpi=150, bbox_inches="tight")
        plt.close()
        return

    bad_epochs = reject_log["bad_epochs"]
    labels = reject_log["labels"]

    fig, axes = plt.subplots(2, 1, figsize=(12, 8))
    axes[0].plot(bad_epochs.astype(int), "r-", alpha=0.7)
    axes[0].fill_between(range(len(bad_epochs)), 0, bad_epochs.astype(int), alpha=0.3, color="red")
    axes[0].set_xlabel("Epoch")
    axes[0].set_ylabel("Rejected")
    axes[0].set_title(f"Epoch Rejection ({np.sum(bad_epochs)}/{len(bad_epochs)} rejected)")
    axes[0].set_ylim(-0.1, 1.1)

    im = axes[1].imshow(labels.T, aspect="auto", cmap="RdYlGn_r", interpolation="nearest")
    axes[1].set_xlabel("Epoch")
    axes[1].set_ylabel("Channel")
    axes[1].set_title("Bad Channels per Epoch (red = bad)")
    plt.colorbar(im, ax=axes[1])
    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches="tight")
    plt.close()


def run_mne_autoreject(params: MNEAutorejectParameters) -> Dict[str, Any]:
    configure_mne_environment()
    cache_dir = Path(params.output_dir) / ".numba-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["NUMBA_CACHE_DIR"] = str(cache_dir)
    os.environ.setdefault("NUMBA_DISABLE_CACHING", "1")
    os.environ.setdefault("MNE_HOME", str(Path(params.output_dir)))

    import mne
    import matplotlib

    matplotlib.use("Agg")

    epochs = mne.read_epochs(params.epochs_file, preload=True)
    pick_idx = None
    if params.picks:
        if isinstance(params.picks, str):
            if params.picks.lower() == "eeg":
                pick_idx = mne.pick_types(epochs.info, meg=False, eeg=True)
            elif params.picks.lower() == "meg":
                pick_idx = mne.pick_types(epochs.info, meg=True, eeg=False)
            else:
                pick_idx = mne.pick_channels(epochs.info["ch_names"], [params.picks])
        else:
            pick_idx = mne.pick_channels(epochs.info["ch_names"], list(params.picks))

    output_path = Path(params.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    try:
        has_autoreject = True
        epochs_clean, reject_log, thresholds = _autoreject_with_package(epochs, params, pick_idx)
    except (ImportError, RuntimeError, ValueError, AttributeError, TypeError, Exception):
        has_autoreject = False
        epochs_clean, reject_log, thresholds = _autoreject_fallback(epochs, params, pick_idx)

    stats = _calculate_rejection_stats(epochs, epochs_clean, reject_log)

    epochs_file_clean: Optional[Path] = None
    if params.save_epochs:
        epochs_file_clean = output_path / "epochs_autoreject_epo.fif"
        epochs_clean.save(epochs_file_clean, overwrite=True)

    plot_files: Dict[str, str] = {}
    if params.save_plots:
        reject_plot = output_path / "autoreject_log.png"
        _plot_reject_log(has_autoreject, epochs, reject_log, reject_plot)
        plot_files["reject_log"] = str(reject_plot)

        comparison_plot = output_path / "autoreject_comparison.png"
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(1, 2, figsize=(12, 5))
        data_orig = epochs.get_data()
        axes[0].plot(epochs.times, np.mean(data_orig, axis=(0, 1)), "b-", alpha=0.7)
        axes[0].fill_between(
            epochs.times,
            np.mean(data_orig, axis=(0, 1)) - np.std(data_orig, axis=(0, 1)),
            np.mean(data_orig, axis=(0, 1)) + np.std(data_orig, axis=(0, 1)),
            alpha=0.3,
        )
        axes[0].set_title(f"Original ({len(epochs)} epochs)")
        axes[0].set_xlabel("Time (s)")
        axes[0].set_ylabel("Amplitude")

        data_clean = epochs_clean.get_data()
        axes[1].plot(epochs_clean.times, np.mean(data_clean, axis=(0, 1)), "g-", alpha=0.7)
        axes[1].fill_between(
            epochs_clean.times,
            np.mean(data_clean, axis=(0, 1)) - np.std(data_clean, axis=(0, 1)),
            np.mean(data_clean, axis=(0, 1)) + np.std(data_clean, axis=(0, 1)),
            alpha=0.3,
        )
        axes[1].set_title(f"Cleaned ({len(epochs_clean)} epochs)")
        axes[1].set_xlabel("Time (s)")
        axes[1].set_ylabel("Amplitude")
        plt.suptitle("Autoreject: Before and After")
        plt.tight_layout()
        plt.savefig(comparison_plot, dpi=150, bbox_inches="tight")
        plt.close()
        plot_files["comparison"] = str(comparison_plot)

    report = {
        "statistics": stats,
        "parameters": {
            "cv": params.cv,
            "thresh_method": params.thresh_method,
            "mode": params.mode,
            "use_local": params.use_local,
            "use_global": params.use_global,
        },
        "thresholds": thresholds,
        "file_info": {
            "input_file": params.epochs_file,
            "output_file": str(epochs_file_clean) if epochs_file_clean else None,
        },
    }

    report_path: Optional[Path] = None
    if params.save_report:
        report_path = output_path / "autoreject_report.json"
        with open(report_path, "w", encoding="utf-8") as fp:
            json.dump(report, fp, indent=2)

    message = (
        f"Autoreject completed: {stats['n_epochs_clean']}/{stats['n_epochs_original']} "
        f"epochs retained ({(1 - stats['rejection_rate']) * 100:.1f}%)."
    )

    return {
        "outputs": {
            "epochs_clean": str(epochs_file_clean) if epochs_file_clean else None,
            "report": str(report_path) if report_path else None,
            "plots": plot_files,
        },
        "statistics": stats,
        "thresholds": thresholds,
        "message": message,
        "used_autoreject_package": has_autoreject,
    }


__all__ = [
    "MNEAutorejectParameters",
    "mne_autoreject_from_payload",
    "run_mne_autoreject",
]
