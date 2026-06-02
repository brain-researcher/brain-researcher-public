"""Real-data smoke test for brain-age prediction workflow using ds000117 ages.

Builds a tiny feature matrix from two subjects' ROI timeseries connectivity and
uses the real `age` field from participants.tsv.

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
@pytest.mark.timeout(900)
def test_workflow_brain_age_prediction_ds000117_smoke(tmp_path: Path):
    bids_root = Path(
        os.environ.get("BR_DS000117_BIDS_ROOT", "/app/data/openneuro/ds000117")
    )
    if not bids_root.exists():
        pytest.skip(f"ds000117 not found at {bids_root}")

    atlas_path = Path(
        os.environ.get(
            "BR_SCHAEFER100_ATLAS",
            _resolve_repo_path(
                PROJECT_ROOT
                / "data"
                / "br_kg"
                / "raw"
                / "nilearn_atlases"
                / "schaefer_2018"
                / "Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz"
            ),
        )
    )
    if not atlas_path.exists():
        pytest.skip(f"Atlas file not found: {atlas_path}")

    participants = bids_root / "participants.tsv"
    if not participants.exists():
        pytest.skip(f"participants.tsv missing: {participants}")

    rows = participants.read_text(encoding="utf-8").splitlines()
    header = rows[0].split("\t")
    idx_id = header.index("participant_id")
    idx_age = header.index("age")
    age_map: dict[str, float] = {}
    for row in rows[1:]:
        if not row.strip():
            continue
        parts = row.split("\t")
        if len(parts) <= max(idx_id, idx_age):
            continue
        pid = parts[idx_id]
        try:
            age_map[pid] = float(parts[idx_age])
        except Exception:
            continue

    # Pick two subjects with available fMRI and known numeric age.
    subjects: list[str] = []
    ages: list[float] = []
    for pid, age in sorted(age_map.items()):
        bold = (
            bids_root
            / f"{pid}/ses-mri/func/{pid}_ses-mri_task-facerecognition_run-01_bold.nii.gz"
        )
        if not bold.exists():
            continue
        subjects.append(pid)
        ages.append(age)
        if len(subjects) >= 2:
            break
    if len(subjects) < 2:
        pytest.skip("Need at least 2 subjects with numeric age + facerecognition BOLD")

    ts_list = []
    for sub, age in zip(subjects, ages, strict=True):
        bold = (
            bids_root
            / f"{sub}/ses-mri/func/{sub}_ses-mri_task-facerecognition_run-01_bold.nii.gz"
        )

        ts_dir = tmp_path / f"ts_{sub}"
        ts_dir.mkdir(parents=True, exist_ok=True)
        res_ts = execute_tool(
            "extract_timeseries",
            {"img": str(bold), "atlas": str(atlas_path), "output_dir": str(ts_dir)},
        )
        assert res_ts.status == "success", res_ts.error
        ts_list.append(np.load(res_ts.data["outputs"]["timeseries"]))

    min_tp = min(ts.shape[0] for ts in ts_list)
    ts_stack = np.stack([ts[:min_tp] for ts in ts_list], axis=0)
    ts_file = tmp_path / "timeseries_2sub.npy"
    np.save(ts_file, ts_stack)

    # Vectorized connectivity features.
    features_file = tmp_path / "features.npy"
    res_conn = execute_tool(
        "connectivity_matrix",
        {
            "timeseries": str(ts_file),
            "kind": "correlation",
            "vectorize": True,
            "output_file": str(features_file),
        },
    )
    assert res_conn.status == "success", res_conn.error
    assert features_file.exists() and features_file.stat().st_size > 0

    ages_file = tmp_path / "ages.npy"
    np.save(ages_file, np.asarray(ages, dtype=float))

    out_dir = tmp_path / "brain_age"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_brain_age_prediction",
        {
            "features": str(features_file),
            "ages": str(ages_file),
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error
    out_table = out_dir / "brain_age.csv"
    assert out_table.exists() and out_table.stat().st_size > 0
