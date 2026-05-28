from __future__ import annotations

import os
import numpy as np
from pathlib import Path

from brain_researcher.services.tools.params import (
    MNEICAParameters,
    run_mne_ica,
)


def _create_preprocessed_raw(tmp_path):
    import mne

    sfreq = 50.0
    times = np.arange(0, 1, 1 / sfreq)
    data = np.vstack([np.sin(2 * np.pi * 5 * times)])
    info = mne.create_info(["Fz"], sfreq=sfreq, ch_types="eeg")
    raw = mne.io.RawArray(data, info)
    raw_file = tmp_path / "raw.fif"
    raw.save(raw_file, overwrite=True)
    return raw_file


def test_run_mne_ica(tmp_path):
    os.environ.setdefault("NUMBA_DISABLE_CACHING", "1")
    os.environ.setdefault("MNE_USE_NATIVE_CODE", "0")
    os.environ.setdefault("HOME", str(tmp_path))

    raw_path = _create_preprocessed_raw(tmp_path)
    params = MNEICAParameters(
        raw_file=str(raw_path),
        output_dir=str(tmp_path / "out"),
        detect_artifacts=("eog",),
        save_ica=False,
        apply_ica=False,
    )
    result = run_mne_ica(params)
    outputs = result["outputs"]
    assert "report" in outputs
    assert Path(outputs["report"]).exists()
