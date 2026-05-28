"""Real-data smoke test for EEG/MEG source estimation workflow on ds000117.

Uses ds000117 MEG FIF input as a stand-in raw recording (the preprocessing and
localization paths should handle .fif).

Marked as `realdata` so it is skipped by default in CI.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from brain_researcher.services.tools.runner import execute_tool


PROJECT_ROOT = Path(__file__).resolve().parents[3]
TMP_ROOT = PROJECT_ROOT / "out" / "tmp_tests"
TMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TMPDIR", str(TMP_ROOT))


def _make_tiny_meg_subset(raw_path: Path, output_path: Path) -> Path:
    try:
        import mne
    except Exception as exc:
        pytest.skip(f"MNE unavailable: {exc}")

    raw = mne.io.read_raw_fif(str(raw_path), preload=False, verbose=False)
    keep = raw.ch_names[: min(12, len(raw.ch_names))]
    raw.pick(keep)
    if raw.n_times > 1:
        sfreq = float(raw.info["sfreq"])
        max_t = max(0.0, (raw.n_times - 1) / sfreq)
        raw.crop(tmin=0.0, tmax=min(8.0, max_t))
    raw.load_data()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    raw.save(str(output_path), overwrite=True, verbose=False)
    return output_path


@pytest.mark.realdata
@pytest.mark.slow
@pytest.mark.timeout(900)
def test_workflow_eeg_source_estimation_ds000117_smoke(tmp_path: Path):
    bids_root = Path(
        os.environ.get(
            "BR_DS000117_BIDS_ROOT",
            "/app/data/openneuro/ds000117",
        )
    )
    if not bids_root.exists():
        pytest.skip(f"ds000117 not found at {bids_root}")

    raw = (
        bids_root
        / "sub-01/ses-meg/meg/sub-01_ses-meg_task-facerecognition_run-01_meg.fif"
    )
    if not raw.exists():
        pytest.skip(f"MEG FIF missing: {raw}")

    tiny_raw = _make_tiny_meg_subset(raw, tmp_path / "sub-01_tiny_raw.fif")

    out_dir = tmp_path / "eeg_source"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_eeg_source_estimation",
        {
            "raw_eeg": str(tiny_raw),
            "montage": "standard_1020",
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error

    stc_files = res.data.get("outputs", {}).get("outputs", {}).get("source_estimate")
    assert stc_files, "Missing source_estimate outputs"
    for p in stc_files:
        path = Path(p)
        assert path.exists() and path.stat().st_size > 0
