"""Real-data smoke test for workflow_preprocessing_qc on ds000114.

This smoke keeps the composite workflow in explicit preview mode:
- `dry_run=True` preserves preview behavior for the fMRIPrep and MRIQC substeps
- QC aggregation runs on a small real QC TSV derived from ds000114 fMRIPrep confounds
- the catalog now also exposes `dry_run=False` for callers that want real execution
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from brain_researcher.services.tools.runner import execute_tool


PROJECT_ROOT = Path(__file__).resolve().parents[3]
TMP_ROOT = PROJECT_ROOT / "out" / "tmp_tests"
TMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TMPDIR", str(TMP_ROOT))


def _mean_fd(confounds_tsv: Path) -> float:
    df = pd.read_csv(confounds_tsv, sep="\t")
    if "framewise_displacement" not in df.columns:
        raise ValueError(f"Missing framewise_displacement in {confounds_tsv}")
    fd = pd.to_numeric(df["framewise_displacement"], errors="coerce").dropna()
    return float(fd.mean()) if not fd.empty else float("nan")


@pytest.mark.realdata
@pytest.mark.timeout(300)
def test_workflow_preprocessing_qc_ds000114_smoke(tmp_path: Path):
    bids_root = Path(
        os.environ.get(
            "BR_DS000114_BIDS_ROOT",
            PROJECT_ROOT / "out" / "openneuro_local" / "ds000114" / "bids",
        )
    )
    if not bids_root.exists():
        pytest.skip(f"BIDS root not found: {bids_root}")

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
    if not fmriprep_root.exists():
        pytest.skip(f"fMRIPrep derivatives not found: {fmriprep_root}")

    conf_test = (
        fmriprep_root
        / "sub-01/ses-test/func/sub-01_ses-test_task-linebisection_desc-confounds_timeseries.tsv"
    )
    conf_retest = (
        fmriprep_root
        / "sub-01/ses-retest/func/sub-01_ses-retest_task-linebisection_desc-confounds_timeseries.tsv"
    )
    for p in (conf_test, conf_retest):
        if not p.exists():
            pytest.skip(f"Missing required confounds TSV: {p}")

    qc_tsv = tmp_path / "qc.tsv"
    qc_df = pd.DataFrame(
        [
            {"run_id": "sub-01_ses-test", "fd_mean": _mean_fd(conf_test)},
            {"run_id": "sub-01_ses-retest", "fd_mean": _mean_fd(conf_retest)},
        ]
    )
    qc_df.to_csv(qc_tsv, sep="\t", index=False)

    out_dir = tmp_path / "preprocessing_qc"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_preprocessing_qc",
        {
            "bids_dir": str(bids_root),
            "qc_tsv": str(qc_tsv),
            "outlier_metric": "fd_mean",
            "outlier_z": 3.0,
            "output_dir": str(out_dir),
            "dry_run": True,
        },
    )
    assert res.status == "success", res.error

    assert (out_dir / "qc/qc_table.csv").exists()
    assert (out_dir / "qc/qc_outliers.csv").exists()
    assert (out_dir / "qc/qc_summary.json").exists()
    assert (out_dir / "qc/index.html").exists()
