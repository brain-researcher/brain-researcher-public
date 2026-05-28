from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

from brain_researcher.services.tools.params import (
    MNETimeFreqParameters,
    run_mne_timefreq,
)


def _create_epochs(tmp_path: Path) -> Path:
    os.environ.setdefault("NUMBA_DISABLE_CACHING", "1")
    os.environ.setdefault("MNE_USE_NATIVE_CODE", "0")
    os.environ.setdefault("NUMBA_CACHE_DIR", str(tmp_path / ".numba-cache"))
    os.environ.setdefault("MNE_HOME", str(tmp_path / ".mne"))
    os.environ["HOME"] = str(tmp_path)

    import mne

    sfreq = 32.0
    times = np.arange(0, 2, 1 / sfreq)
    ch_names = ["Fz", "Cz"]
    info = mne.create_info(ch_names=ch_names, sfreq=sfreq, ch_types="eeg")

    sig1 = np.sin(2 * np.pi * 5 * times)
    sig2 = np.sin(2 * np.pi * 12 * times)
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

    epochs_path = tmp_path / "timefreq_epochs-epo.fif"
    epochs.save(epochs_path, overwrite=True)
    return epochs_path


def test_run_mne_timefreq(tmp_path):
    epochs_path = _create_epochs(tmp_path)
    params = MNETimeFreqParameters(
        epochs_file=str(epochs_path),
        output_dir=str(tmp_path / "out"),
        method="morlet",
        average=True,
        return_itc=True,
        compute_psd=True,
        save_plots=True,
        compute_band_power=True,
        compute_connectivity=True,
        compute_statistics=True,
    )

    result = run_mne_timefreq(params)
    outputs = result["outputs"]
    assert Path(outputs["tfr"]).exists()
    if outputs.get("itc"):
        assert Path(outputs["itc"]).exists()
    assert Path(outputs["report"]).exists()
    assert outputs["plots"].get("power")
    assert Path(outputs["plots"]["power"]).exists()
    assert outputs["band_power"] is not None
    assert Path(outputs["band_power"]).exists()
    assert outputs["connectivity"] is not None
    assert Path(outputs["connectivity"]).exists()
    assert outputs["feature_contract"] is not None
    assert Path(outputs["feature_contract"]).exists()
    contract = json.loads(Path(outputs["feature_contract"]).read_text())
    assert contract["matrix_kind"] == "timefreq_power_correlation"
    if outputs["statistics"]:
        assert Path(outputs["statistics"]).exists()
    summary = result["summary"]
    assert summary["n_channels"] == 2
    assert "band_power" in summary
    assert "connectivity" in summary
    assert result["used_mne_timefreq_package"] in (True, False)
