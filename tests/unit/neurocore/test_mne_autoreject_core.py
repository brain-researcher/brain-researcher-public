from __future__ import annotations

import os
import numpy as np
from pathlib import Path

from brain_researcher.services.tools.params import (
    MNEAutorejectParameters,
    run_mne_autoreject,
)


def _create_epochs(tmp_path: Path):
    os.environ.setdefault("NUMBA_DISABLE_CACHING", "1")
    os.environ.setdefault("MNE_USE_NATIVE_CODE", "0")
    os.environ.setdefault("NUMBA_CACHE_DIR", str(tmp_path / ".numba-cache"))
    os.environ.setdefault("MNE_HOME", str(tmp_path / ".mne"))
    os.environ["HOME"] = str(tmp_path)

    import mne

    sfreq = 100.0
    times = np.arange(0, 2, 1 / sfreq)
    data = np.vstack(
        [
            np.sin(2 * np.pi * 10 * times),
            np.cos(2 * np.pi * 12 * times),
        ]
    )
    info = mne.create_info(["Fz", "Cz"], sfreq=sfreq, ch_types="eeg")
    raw = mne.io.RawArray(data, info)
    raw.set_montage(mne.channels.make_standard_montage("standard_1020"))
    events = mne.make_fixed_length_events(raw, duration=0.5, start=0, stop=None, id=1)
    epochs = mne.Epochs(
        raw,
        events,
        event_id={"stim": 1},
        tmin=0.0,
        tmax=0.5,
        baseline=None,
        preload=True,
    )

    # Introduce an outlier epoch to exercise rejection path.
    epochs._data[0, 0, :] *= 10

    epochs_file = tmp_path / "synthetic_epochs-epo.fif"
    epochs.save(epochs_file, overwrite=True)
    return epochs_file


def test_run_mne_autoreject(tmp_path):
    epochs_path = _create_epochs(tmp_path)
    params = MNEAutorejectParameters(
        epochs_file=str(epochs_path),
        output_dir=str(tmp_path / "out"),
        cv=2,
        save_epochs=True,
        save_report=True,
        save_plots=True,
        verbose=False,
    )
    result = run_mne_autoreject(params)

    outputs = result["outputs"]
    assert outputs["epochs_clean"] is not None
    assert Path(outputs["epochs_clean"]).exists()
    assert outputs["report"] is not None
    assert Path(outputs["report"]).exists()
    assert "reject_log" in outputs["plots"]
    assert Path(outputs["plots"]["reject_log"]).exists()

    stats = result["statistics"]
    assert stats["n_epochs_original"] > 0
    assert stats["n_epochs_clean"] <= stats["n_epochs_original"]
    assert "message" in result
    assert result["used_autoreject_package"] in (True, False)
