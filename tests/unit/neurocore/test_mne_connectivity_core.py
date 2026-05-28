from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from brain_researcher.services.tools.params import (
    MNEConnectivityParameters,
    run_mne_connectivity,
)


def _create_epochs(tmp_path: Path) -> Path:
    os.environ.setdefault("NUMBA_DISABLE_CACHING", "1")
    os.environ.setdefault("MNE_USE_NATIVE_CODE", "0")
    os.environ.setdefault("NUMBA_CACHE_DIR", str(tmp_path / ".numba-cache"))
    os.environ.setdefault("MNE_HOME", str(tmp_path / ".mne"))
    os.environ["HOME"] = str(tmp_path)

    import mne

    sfreq = 64.0
    times = np.arange(0, 2, 1 / sfreq)
    ch_names = ["Fz", "Cz"]
    info = mne.create_info(ch_names=ch_names, sfreq=sfreq, ch_types="eeg")

    sig1 = np.sin(2 * np.pi * 8 * times)
    sig2 = np.sin(2 * np.pi * 8 * times + np.pi / 4)
    data = np.vstack([sig1, sig2])

    raw = mne.io.RawArray(data, info)
    raw.set_montage(mne.channels.make_standard_montage("standard_1020"))

    events = mne.make_fixed_length_events(raw, duration=0.5, id=1)
    epochs = mne.Epochs(
        raw,
        events,
        event_id={"stim": 1},
        tmin=0.0,
        tmax=0.5,
        baseline=None,
        preload=True,
    )

    epochs_path = tmp_path / "connectivity_epochs-epo.fif"
    epochs.save(epochs_path, overwrite=True)
    return epochs_path


def test_run_mne_connectivity(tmp_path):
    epochs_path = _create_epochs(tmp_path)
    params = MNEConnectivityParameters(
        epochs_file=str(epochs_path),
        output_dir=str(tmp_path / "out"),
        methods=("coherence",),
        save_matrix=True,
        save_plots=True,
    )

    result = run_mne_connectivity(params)
    outputs = result["outputs"]
    assert "coherence" in outputs["matrices"]
    assert Path(outputs["matrices"]["coherence"]).exists()
    assert "coherence" in outputs["feature_contracts"]
    assert Path(outputs["feature_contracts"]["coherence"]).exists()
    assert outputs["report"] is not None
    assert Path(outputs["report"]).exists()
    assert outputs["plots"]["coherence"].endswith(".png")
    assert Path(outputs["plots"]["coherence"]).exists()
    summary = result["summary"]
    assert summary["methods"] == ["coherence"]
    assert summary["n_channels"] == 2
    assert result["used_mne_connectivity_package"] in (True, False)
