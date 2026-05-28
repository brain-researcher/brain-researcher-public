from __future__ import annotations

import os
import numpy as np
import pytest

from brain_researcher.services.tools.params.mne_preprocessing import (
    MNEPreprocessingParameters,
    run_mne_preprocessing,
)


def _create_raw(tmp_path):
    os.environ.setdefault("NUMBA_DISABLE_CACHING", "1")
    os.environ.setdefault("MNE_USE_NATIVE_CODE", "0")
    os.environ.setdefault("NUMBA_CACHE_DIR", str(tmp_path / ".numba-cache"))
    os.environ.setdefault("MNE_HOME", str(tmp_path / ".mne"))
    os.environ["HOME"] = str(tmp_path)
    import mne

    sfreq = 100.0
    times = np.arange(0, 1, 1 / sfreq)
    data = np.vstack([np.sin(2 * np.pi * 10 * times), np.cos(2 * np.pi * 15 * times)])
    info = mne.create_info(ch_names=["Fz", "Cz"], sfreq=sfreq, ch_types="eeg")
    raw = mne.io.RawArray(data, info)
    raw_file = tmp_path / "synthetic_raw.fif"
    raw.save(raw_file, overwrite=True)
    return raw_file


@pytest.mark.filterwarnings("ignore:The default value of return_copy will change")
def test_run_mne_preprocessing(tmp_path):
    raw_file = _create_raw(tmp_path)
    params = MNEPreprocessingParameters(
        raw_file=str(raw_file),
        output_dir=str(tmp_path / "out"),
        detect_bad_channels=False,
        create_epochs=False,
        notch_freq=None,
    )
    result = run_mne_preprocessing(params)
    outputs = result["outputs"]
    assert "preprocessed_data" in outputs
    assert (tmp_path / "out" / "preprocessed_raw.fif").exists()
