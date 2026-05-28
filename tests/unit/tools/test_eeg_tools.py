from __future__ import annotations

from pathlib import Path

import numpy as np

from brain_researcher.core.utils import configure_mne_environment
from brain_researcher.services.tools.connectivity_measures_tool import (
    ConnectivityMeasuresTool,
)
from brain_researcher.services.tools.eeg_preprocess_tool import EEGPreprocessTool
from brain_researcher.services.tools.epoch_events_tool import EpochEventsTool


def _create_raw(tmp_path: Path) -> Path:
    configure_mne_environment()
    import mne

    sfreq = 100.0
    data = np.random.randn(4, int(sfreq * 2)) * 1e-6
    info = mne.create_info(["Fz", "Cz", "Pz", "Oz"], sfreq, ch_types="eeg")
    raw = mne.io.RawArray(data, info, verbose=False)
    raw.set_montage("standard_1020")
    raw_path = tmp_path / "raw.fif"
    raw.save(raw_path, overwrite=True, verbose=False)
    return raw_path


def test_eeg_preprocess_epoch_connectivity(tmp_path: Path) -> None:
    raw_path = _create_raw(tmp_path)

    preprocess = EEGPreprocessTool()
    preprocess_result = preprocess._run(
        raw_eeg=str(raw_path),
        montage_def="standard_1020",
        highpass_hz=1.0,
        lowpass_hz=40.0,
        output_dir=str(tmp_path),
    )
    assert preprocess_result.status == "success"
    clean_path = Path(preprocess_result.data["outputs"]["clean_eeg"])
    assert clean_path.exists()

    epoch_tool = EpochEventsTool()
    epoch_result = epoch_tool._run(
        clean_eeg=str(clean_path),
        tmin=-0.1,
        tmax=0.3,
        output_dir=str(tmp_path),
    )
    assert epoch_result.status == "success"
    epochs_path = Path(epoch_result.data["outputs"]["epochs"])
    assert epochs_path.exists()

    connectivity_tool = ConnectivityMeasuresTool()
    conn_result = connectivity_tool._run(
        epochs=str(epochs_path),
        method="pli",
        fmin=8.0,
        fmax=12.0,
        output_dir=str(tmp_path),
    )
    assert conn_result.status == "success"
    matrix_path = Path(conn_result.data["outputs"]["connectivity_matrix"])
    assert matrix_path.exists()
    contract_path = Path(conn_result.data["outputs"]["feature_contract"])
    assert contract_path.exists()
