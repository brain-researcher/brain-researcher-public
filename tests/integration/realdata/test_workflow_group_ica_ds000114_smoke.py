"""Real-data smoke test for workflow_group_ica on ds000114 derivatives.

Runs the declarative workflow:
  group_ica (CanICA) -> connectivity -> nbs_engine

Marked as `realdata` + `slow` so it is skipped by default in CI.
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


def _labels_from_participants(participants_tsv: Path, subjects: list[str]) -> list[int]:
    df = pd.read_csv(participants_tsv, sep="\t")
    mapping = dict(
        zip(df["participant_id"].astype(str), df["dominant_hand"].astype(str))
    )
    labels = []
    for sub in subjects:
        hand = mapping.get(sub)
        if hand is None:
            raise RuntimeError(f"Subject {sub} not found in participants.tsv")
        labels.append(1 if hand.strip().lower() == "left" else 0)
    if len(set(labels)) != 2:
        raise RuntimeError(f"Need two groups for NBS, got labels={labels}")
    return labels


@pytest.mark.realdata
@pytest.mark.slow
@pytest.mark.timeout(1800)
def test_workflow_group_ica_ds000114_smoke(tmp_path: Path):
    openneuro_root = Path(
        os.environ.get(
            "BR_DS000114_OPENNEURO_ROOT",
            "/app/data/openneuro/ds000114",
        )
    )
    participants = openneuro_root / "participants.tsv"
    if not participants.exists():
        pytest.skip(f"participants.tsv not found: {participants}")

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

    subjects = ["sub-01", "sub-02", "sub-03", "sub-06"]
    imgs = []
    for sub in subjects:
        img = (
            fmriprep_root
            / f"{sub}/ses-test/func/{sub}_ses-test_task-linebisection_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz"
        )
        if not img.exists():
            pytest.skip(f"Missing required preproc BOLD: {img}")
        imgs.append(str(img))

    labels = _labels_from_participants(participants, subjects)

    out_dir = tmp_path / "group_ica"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_group_ica",
        {
            "img": imgs,
            "n_components": 10,
            "labels": labels,
            "threshold": 1.0,
            "n_permutations": 20,
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error

    workflow_data = res.data or {}
    provenance = workflow_data.get("provenance") or {}
    assert provenance.get("workflow_id") == "workflow_group_ica"
    assert provenance.get("stage") == "connectivity"

    steps = workflow_data.get("steps") or {}
    ica_outputs = (steps.get("ica") or {}).get("data", {}).get("outputs", {})
    conn_outputs = (steps.get("conn") or {}).get("data", {}).get("outputs", {})
    stats_payload = (steps.get("stats") or {}).get("data") or {}

    ica_dir = out_dir / "group_ica"
    assert (ica_dir / "canica_components.nii.gz").exists()
    assert (ica_dir / "canica_timecourses.npy").exists()
    assert (ica_dir / "connectivity.npy").exists()
    assert Path(ica_outputs["components_file"]) == (
        ica_dir / "canica_components.nii.gz"
    )
    assert Path(ica_outputs["timecourses"]) == (ica_dir / "canica_timecourses.npy")
    assert Path(conn_outputs["matrix"]) == (ica_dir / "connectivity.npy")

    tmap = ica_dir / "nbs.npy"
    assert tmap.exists() and tmap.stat().st_size > 0
    assert Path(stats_payload["tmap_file"]) == tmap
    assert Path(stats_payload["supra_mask_file"]).exists()
    assert Path(stats_payload["components_file"]).exists()

    workflow_outputs = workflow_data.get("outputs") or {}
    assert Path(workflow_outputs["ica_dir"]) == ica_dir
    assert Path(workflow_outputs["components_file"]) == (
        ica_dir / "canica_components.nii.gz"
    )
    assert Path(workflow_outputs["timecourses_file"]) == (
        ica_dir / "canica_timecourses.npy"
    )
    assert Path(workflow_outputs["connectivity_matrix"]) == (
        ica_dir / "connectivity.npy"
    )
    assert Path(workflow_outputs["nbs_tmap"]) == tmap
    assert Path(workflow_outputs["nbs_supra_mask"]).exists()
    assert Path(workflow_outputs["nbs_components"]).exists()

    t = np.load(tmap)
    assert t.ndim == 2 and t.shape[0] == t.shape[1]
