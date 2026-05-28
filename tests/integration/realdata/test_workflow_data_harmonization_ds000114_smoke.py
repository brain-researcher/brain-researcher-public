"""Real-data smoke test for workflow_data_harmonization on ds000114.

This builds a small connectivity-derived feature table from real fMRIPrep
preprocessed BOLD (ds000114) and runs the declarative ComBat-like harmonization
workflow.

Marked as `realdata` so it is skipped by default in CI.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from brain_researcher.services.tools.runner import execute_tool


PROJECT_ROOT = Path(__file__).resolve().parents[3]
TMP_ROOT = PROJECT_ROOT / "out" / "tmp_tests"
TMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TMPDIR", str(TMP_ROOT))


@pytest.mark.realdata
@pytest.mark.slow
@pytest.mark.timeout(900)
def test_workflow_data_harmonization_ds000114_smoke(tmp_path: Path):
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

    atlas = (
        PROJECT_ROOT
        / "data"
        / "neurokg"
        / "raw"
        / "nilearn_atlases"
        / "schaefer_2018"
        / "Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz"
    )
    if not atlas.exists():
        pytest.skip(f"Atlas not found: {atlas}")

    # Use two subjects, test/retest sessions, as two "batches" (session effect).
    samples: list[tuple[str, str]] = [
        ("sub-01", "ses-test"),
        ("sub-01", "ses-retest"),
        ("sub-02", "ses-test"),
        ("sub-02", "ses-retest"),
    ]
    imgs: list[Path] = []
    batches: list[int] = []
    sample_ids: list[str] = []
    for sub, ses in samples:
        img = (
            fmriprep_root
            / f"{sub}/{ses}/func/{sub}_{ses}_task-linebisection_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz"
        )
        if not img.exists():
            pytest.skip(f"Missing required preproc BOLD: {img}")
        imgs.append(img)
        sample_ids.append(f"{sub}_{ses}")
        batches.append(0 if ses == "ses-test" else 1)

    out_dir = tmp_path / "harmonization"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build a small feature table from FC edges (upper triangle).
    X_rows = []
    for sid, img in zip(sample_ids, imgs, strict=True):
        ts_dir = out_dir / "timeseries" / sid
        ts_dir.mkdir(parents=True, exist_ok=True)
        res_ts = execute_tool(
            "extract_timeseries",
            {"img": str(img), "atlas": str(atlas), "output_dir": str(ts_dir)},
        )
        assert res_ts.status == "success", res_ts.error
        ts_file = Path((res_ts.data or {}).get("outputs", {}).get("timeseries", ""))
        assert ts_file.exists() and ts_file.stat().st_size > 0

        conn_dir = out_dir / "connectivity" / sid
        conn_dir.mkdir(parents=True, exist_ok=True)
        conn_file = conn_dir / "conn.npy"
        res_conn = execute_tool(
            "compute_connectivity",
            {"timeseries": str(ts_file), "kind": "correlation", "output_file": str(conn_file)},
        )
        assert res_conn.status == "success", res_conn.error
        mats = np.load(conn_file)
        assert mats.ndim == 3 and mats.shape[0] == 1
        mat = mats[0]
        iu = np.triu_indices(mat.shape[0], k=1)
        X_rows.append(mat[iu].astype("float32"))

    X = np.stack(X_rows, axis=0)
    assert X.shape[0] == len(samples)

    features_file = out_dir / "features.csv"
    df = pd.DataFrame(X)
    df.insert(0, "sample_id", sample_ids)
    df.to_csv(features_file, index=False)

    harmonized_out = out_dir / "harmonized.csv"
    report_out = out_dir / "harmonization_report.json"
    provenance_out = out_dir / "provenance.json"
    res = execute_tool(
        "workflow_data_harmonization",
        {
            "bids_dir": str(bids_root),
            "features": str(features_file),
            "batch": batches,
            "covars": None,
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error

    assert harmonized_out.exists() and harmonized_out.stat().st_size > 0
    assert report_out.exists() and report_out.stat().st_size > 0
    assert provenance_out.exists() and provenance_out.stat().st_size > 0
    out_df = pd.read_csv(harmonized_out)
    assert out_df.shape[0] == len(samples)
    numeric = out_df.select_dtypes(include=[np.number])
    assert numeric.shape[1] == X.shape[1]
    assert np.isfinite(numeric.to_numpy(dtype=float)).all()
