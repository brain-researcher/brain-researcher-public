from __future__ import annotations

from pathlib import Path

import numpy as np
from importlib.util import find_spec

from brain_researcher.core.utils import configure_mne_environment

from brain_researcher.services.tools.params import (
    MNEFOOOFParameters,
    run_mne_fooof,
)


def test_run_mne_fooof(tmp_path):
    configure_mne_environment()
    import mne

    sfreq = 100.0
    data = np.random.randn(4, int(sfreq * 2)) * 1e-6
    info = mne.create_info(["Fz", "Cz", "Pz", "Oz"], sfreq, ch_types="eeg")
    raw = mne.io.RawArray(data, info, verbose=False)
    raw.set_montage("standard_1020")
    raw_path = tmp_path / "raw.fif"
    raw.save(raw_path, overwrite=True, verbose=False)

    params = MNEFOOOFParameters(
        output_dir=str(tmp_path / "fooof_out"),
        raw_file=str(raw_path),
        save_model=True,
        save_report=True,
        save_plots=True,
    )
    result = run_mne_fooof(params)
    outputs = result["outputs"]
    assert Path(outputs["report"]).exists()
    assert outputs["plots"]["power"].endswith(".png")
    assert Path(outputs["plots"]["power"]).exists()
    assert result["used_fooof_package"] is (find_spec("fooof") is not None)
