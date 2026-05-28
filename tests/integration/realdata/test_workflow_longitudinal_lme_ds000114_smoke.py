"""Real-data smoke test for workflow_longitudinal_lme on ds000114.

Builds a lightweight longitudinal score from real BOLD images across
ses-test/ses-retest, then runs the declarative longitudinal LME workflow.

Marked as `realdata` + `slow` so it is skipped by default in CI.
"""

from __future__ import annotations

import os
from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd
import pytest
from brain_researcher.services.tools.runner import execute_tool


PROJECT_ROOT = Path(__file__).resolve().parents[3]
TMP_ROOT = PROJECT_ROOT / "out" / "tmp_tests"
TMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TMPDIR", str(TMP_ROOT))


def _lightweight_bold_score(img: Path) -> float:
    """Compute a cheap scalar from real BOLD without heavy timeseries pipelines."""
    arr = np.asarray(nib.load(str(img)).dataobj[..., :8], dtype="float32")
    return float(np.nanmean(arr))


@pytest.mark.realdata
@pytest.mark.slow
@pytest.mark.timeout(1200)
def test_workflow_longitudinal_lme_ds000114_smoke(tmp_path: Path):
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

    # Require subjects that have both sessions (avoid partial runs)
    candidate_subjects = ["sub-01", "sub-02", "sub-03", "sub-04", "sub-05", "sub-06"]
    sessions = ["ses-test", "ses-retest"]

    subjects: list[str] = []
    for sub in candidate_subjects:
        ok = True
        for ses in sessions:
            img = (
                fmriprep_root
                / f"{sub}/{ses}/func/{sub}_{ses}_task-linebisection_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz"
            )
            if not img.exists():
                ok = False
                break
        if ok:
            subjects.append(sub)
        if len(subjects) >= 2:
            break

    if len(subjects) < 2:
        pytest.skip("Need >=2 subjects with ses-test + ses-retest for LME smoke test")

    rows: list[dict[str, object]] = []
    for sub in subjects:
        for ses in sessions:
            img = (
                fmriprep_root
                / f"{sub}/{ses}/func/{sub}_{ses}_task-linebisection_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz"
            )
            score = _lightweight_bold_score(img)
            rows.append({"participant_id": sub, "session": ses, "score": score})

    data_file = tmp_path / "longitudinal_scores.csv"
    pd.DataFrame(rows).to_csv(data_file, index=False)

    out_dir = tmp_path / "longitudinal_lme"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_longitudinal_lme",
        {
            "data_file": str(data_file),
            "subject_col": "participant_id",
            "time_col": "session",
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error

    # The workflow writes to this path (even though it is a text summary).
    out_file = out_dir / "lme_results.csv"
    assert out_file.exists() and out_file.stat().st_size > 0
    text = out_file.read_text(encoding="utf-8")
    assert "session" in text or "Intercept" in text
