"""Real-data smoke test for GNN classification workflow on ds000114.

This builds a small multi-subject ROI time series tensor from fMRIPrep BOLD
and uses `dominant_hand` as a real label (left/right).

Marked as `realdata` so it is skipped by default in CI.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from brain_researcher.services.tools.runner import execute_tool


PROJECT_ROOT = Path(__file__).resolve().parents[3]
TMP_ROOT = PROJECT_ROOT / "out" / "tmp_tests"
TMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TMPDIR", str(TMP_ROOT))


def _resolve_repo_path(path: Path) -> Path:
    if path.exists():
        return path
    try:
        alt = PROJECT_ROOT.parent.parent / path.relative_to(PROJECT_ROOT)
    except ValueError:
        return path
    return alt if alt.exists() else path


@pytest.mark.realdata
@pytest.mark.slow
@pytest.mark.timeout(600)
def test_workflow_gnn_classification_ds000114_smoke(tmp_path: Path):
    bids_root = Path(
        os.environ.get(
            "BR_DS000114_BIDS_ROOT",
            PROJECT_ROOT / "out" / "openneuro_local" / "ds000114" / "bids",
        )
    )
    fmriprep_root = Path(
        os.environ.get(
            "BR_DS000114_FMRIPREP_ROOT",
            PROJECT_ROOT
            / "outputs"
            / "_a4_ds000114_linebisection"
            / "derivatives_local"
            / "ds000114-fmriprep",
        )
    )
    if not bids_root.exists():
        pytest.skip(f"BIDS root not found: {bids_root}")
    if not fmriprep_root.exists():
        pytest.skip(f"fMRIPrep derivatives not found: {fmriprep_root}")

    atlas_path = Path(
        os.environ.get(
            "BR_SCHAEFER100_ATLAS",
            _resolve_repo_path(
                PROJECT_ROOT
                / "data"
                / "neurokg"
                / "raw"
                / "nilearn_atlases"
                / "schaefer_2018"
                / "Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz"
            ),
        )
    )
    if not atlas_path.exists():
        pytest.skip(f"Atlas file not found: {atlas_path}")

    # Use two subjects with different dominant_hand labels.
    subjects = ("sub-01", "sub-02")
    labels = []
    ts_list = []
    for sub in subjects:
        img = (
            fmriprep_root
            / f"{sub}/ses-test/func/{sub}_ses-test_task-linebisection_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz"
        )
        if not img.exists():
            pytest.skip(f"Required preproc BOLD missing: {img}")

        ts_dir = tmp_path / f"ts_{sub}"
        ts_dir.mkdir(parents=True, exist_ok=True)
        res_ts = execute_tool(
            "extract_timeseries",
            {"img": str(img), "atlas": str(atlas_path), "output_dir": str(ts_dir)},
        )
        assert res_ts.status == "success", res_ts.error
        ts_arr = np.load(res_ts.data["outputs"]["timeseries"])
        ts_list.append(ts_arr)

        # Derive label from participants.tsv.
        participants_tsv = bids_root / "participants.tsv"
        if not participants_tsv.exists():
            pytest.skip(f"participants.tsv missing: {participants_tsv}")
        rows = participants_tsv.read_text(encoding="utf-8").splitlines()
        header = rows[0].split("\t")
        idx_id = header.index("participant_id")
        idx_hand = header.index("dominant_hand")
        hand = None
        for row in rows[1:]:
            parts = row.split("\t")
            if parts[idx_id] == sub:
                hand = parts[idx_hand].strip().lower()
                break
        if hand not in {"left", "right"}:
            pytest.skip(f"dominant_hand not found for {sub}")
        labels.append(0 if hand == "left" else 1)

    # Stack to (subjects x time x rois) and save.
    min_tp = min(ts.shape[0] for ts in ts_list)
    ts_stack = np.stack([ts[:min_tp] for ts in ts_list], axis=0)
    ts_file = tmp_path / "timeseries_2sub.npy"
    np.save(ts_file, ts_stack)

    labels_file = tmp_path / "labels.npy"
    np.save(labels_file, np.asarray(labels, dtype=int))

    out_dir = tmp_path / "gnn_workflow"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_gnn_classification",
        {
            "timeseries": str(ts_file),
            "labels": str(labels_file),
            "connectivity_kind": "correlation",
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error

    pred = out_dir / "gnn" / "predictions.npy"
    assert pred.exists() and pred.stat().st_size > 0
