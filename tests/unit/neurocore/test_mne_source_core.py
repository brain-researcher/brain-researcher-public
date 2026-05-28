from __future__ import annotations

from pathlib import Path

import numpy as np

from brain_researcher.core.utils import configure_mne_environment

from brain_researcher.services.tools.params import (
    MNESourceInverseParameters,
    MNEBeamformerParameters,
    MNEDipoleParameters,
    run_mne_source_inverse,
    run_mne_beamformer,
    run_mne_dipole,
)


def _create_raw(tmp_path: Path):
    configure_mne_environment()
    import mne

    sfreq = 100.0
    ch_names = ["Fp1", "Fp2", "F3", "F4", "C3", "C4", "P3", "P4", "O1", "O2"]
    data = np.random.randn(len(ch_names), int(sfreq * 10)) * 1e-6
    info = mne.create_info(ch_names, sfreq, ch_types="eeg")
    raw = mne.io.RawArray(data, info, verbose=False)
    raw.set_montage("standard_1020")
    raw_path = tmp_path / "raw.fif"
    raw.save(raw_path, overwrite=True, verbose=False)
    return raw, raw_path


def _create_evoked(tmp_path: Path):
    configure_mne_environment()
    import mne

    raw, raw_path = _create_raw(tmp_path)
    events = mne.make_fixed_length_events(raw, id=1, duration=1.0)
    epochs = mne.Epochs(raw, events, tmin=-0.1, tmax=0.3, baseline=None, preload=True, verbose=False)
    evoked = epochs.average()
    evoked_path = tmp_path / "evoked-ave.fif"
    evoked.save(evoked_path, overwrite=True)

    return raw_path, evoked_path


def test_run_mne_source_inverse(tmp_path):
    subj_dir = tmp_path / "subjects"
    subj_dir.mkdir()
    _, raw_path = _create_raw(tmp_path)
    params = MNESourceInverseParameters(
        subjects_dir=str(subj_dir),
        subject="subj01",
        output_dir=str(tmp_path / "inverse_out"),
        raw_file=str(raw_path),
    )
    result = run_mne_source_inverse(params)
    outputs = result["outputs"]
    assert Path(outputs["summary"]).exists()
    assert outputs["stc"]
    assert Path(outputs["stc"]).exists()
    assert result["summary"]["method"] == "dSPM"


def test_run_mne_beamformer(tmp_path):
    subj_dir = tmp_path / "subjects"
    subj_dir.mkdir()
    _, raw_path = _create_raw(tmp_path)
    params = MNEBeamformerParameters(
        subjects_dir=str(subj_dir),
        subject="subj01",
        output_dir=str(tmp_path / "beamformer_out"),
        raw_file=str(raw_path),
        method="lcmv",
    )
    result = run_mne_beamformer(params)
    outputs = result["outputs"]
    assert Path(outputs["summary"]).exists()
    assert outputs["filters"]
    assert Path(outputs["filters"]).exists()


def test_run_mne_dipole(tmp_path):
    subj_dir = tmp_path / "subjects"
    subj_dir.mkdir()
    _, evoked_path = _create_evoked(tmp_path)
    params = MNEDipoleParameters(
        evoked_file=str(evoked_path),
        subjects_dir=str(subj_dir),
        subject="subj01",
        output_dir=str(tmp_path / "dipole_out"),
        n_dipoles=2,
    )
    result = run_mne_dipole(params)
    outputs = result["outputs"]
    assert Path(outputs["summary"]).exists()
    assert outputs["dipoles"]
    assert Path(outputs["dipoles"]).exists()
