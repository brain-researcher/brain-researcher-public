"""Real-data smoke test for NBS workflow on ds000114 metadata.

We derive group labels from `participants.tsv` and run
`workflow_network_based_statistics` on a deterministic compact timeseries tensor.

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


def _labels_from_participants(participants_tsv: Path, subjects: list[str]) -> list[int]:
    df = pd.read_csv(participants_tsv, sep="\t")
    if "participant_id" not in df.columns or "dominant_hand" not in df.columns:
        raise RuntimeError(
            "participants.tsv missing required columns: participant_id/dominant_hand"
        )
    mapping = dict(
        zip(df["participant_id"].astype(str), df["dominant_hand"].astype(str))
    )
    labels = []
    for sub in subjects:
        hand = mapping.get(sub)
        if hand is None:
            raise RuntimeError(f"Subject {sub} not found in participants.tsv")
        # binary labels: left=1, right=0
        labels.append(1 if hand.strip().lower() == "left" else 0)
    if len(set(labels)) != 2:
        raise RuntimeError(f"Need two groups for NBS, got labels={labels}")
    return labels


@pytest.mark.realdata
@pytest.mark.slow
@pytest.mark.timeout(900)
def test_workflow_network_based_statistics_ds000114_smoke(tmp_path: Path):
    openneuro_root = Path(
        os.environ.get(
            "BR_DS000114_OPENNEURO_ROOT",
            "/app/data/openneuro/ds000114",
        )
    )
    participants = openneuro_root / "participants.tsv"
    if not participants.exists():
        pytest.skip(f"participants.tsv not found: {participants}")

    subjects = ["sub-01", "sub-02", "sub-03", "sub-06"]
    labels = _labels_from_participants(participants, subjects)

    rng = np.random.default_rng(7)
    timeseries = rng.normal(
        loc=0.0,
        scale=1.0,
        size=(len(subjects), 80, 12),
    ).astype(np.float32)
    for idx, label in enumerate(labels):
        # Inject a stable small group effect to keep NBS outputs finite.
        timeseries[idx, :, :3] += 0.30 if label == 1 else -0.30
    tc_file = tmp_path / "timeseries.npy"
    np.save(tc_file, timeseries)

    out_dir = tmp_path / "nbs_workflow"
    out_dir.mkdir(parents=True, exist_ok=True)

    res = execute_tool(
        "workflow_network_based_statistics",
        {
            "timeseries": str(tc_file),
            "connectivity_kind": "correlation",
            "labels": labels,
            "threshold": 1.0,
            "n_permutations": 20,
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error

    workflow_data = res.data or {}
    provenance = workflow_data.get("provenance") or {}
    assert provenance.get("workflow_id") == "workflow_network_based_statistics"
    assert provenance.get("stage") == "connectivity"

    steps = workflow_data.get("steps") or {}
    connectivity_outputs = (
        (steps.get("connectivity") or {}).get("data", {}).get("outputs", {})
    )
    stats_payload = (steps.get("similarity") or {}).get("data") or {}
    assert Path(connectivity_outputs["matrix"]).exists()

    nbs_dir = out_dir
    tmap = nbs_dir / "nbs.npy"
    assert tmap.exists() and tmap.stat().st_size > 0
    assert Path(stats_payload["tmap_file"]) == tmap
    assert Path(stats_payload["supra_mask_file"]).exists()
    assert Path(stats_payload["components_file"]).exists()

    workflow_outputs = workflow_data.get("outputs") or {}
    assert Path(workflow_outputs["connectivity_matrix"]) == Path(
        connectivity_outputs["matrix"]
    )
    assert Path(workflow_outputs["tmap_file"]) == tmap
    assert Path(workflow_outputs["supra_mask_file"]).exists()
    assert Path(workflow_outputs["components_file"]).exists()

    t = np.load(tmap)
    assert t.ndim == 2 and t.shape[0] == t.shape[1]
    assert np.isfinite(t).all()
