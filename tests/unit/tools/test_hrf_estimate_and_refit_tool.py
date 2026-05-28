from __future__ import annotations

import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd

from brain_researcher.services.tools.hrf_estimate_and_refit_tool import (
    HRFEstimateAndRefitTool,
)


def test_hrf_estimate_and_refit_tool_improves_on_canonical_for_shifted_kernel(
    tmp_path: Path,
) -> None:
    t_r = 2.0
    n_scans = 12
    event_vector = np.zeros(n_scans, dtype=float)
    event_vector[[1, 5, 9]] = 1.0
    true_kernel = np.asarray([0.0, 1.0, 0.65, 0.25], dtype=float)
    signal = np.convolve(event_vector, true_kernel, mode="full")[:n_scans]
    signal = signal + 0.01 * np.linspace(0.0, 1.0, n_scans)

    data = np.zeros((3, 3, 3, n_scans), dtype=float)
    data[1, 1, 1, :] = signal
    img = nib.Nifti1Image(data, np.eye(4))
    img.header.set_zooms((2.0, 2.0, 2.0, t_r))
    img_path = tmp_path / "func.nii.gz"
    nib.save(img, img_path)

    mask = np.zeros((3, 3, 3), dtype=float)
    mask[1, 1, 1] = 1.0
    mask_img = nib.Nifti1Image(mask, np.eye(4))
    mask_path = tmp_path / "roi_mask.nii.gz"
    nib.save(mask_img, mask_path)

    events = pd.DataFrame(
        {
            "onset": [2.0, 10.0, 18.0],
            "duration": [0.0, 0.0, 0.0],
            "trial_type": ["stim", "stim", "stim"],
        }
    )
    events_path = tmp_path / "events.tsv"
    events.to_csv(events_path, sep="\t", index=False)

    result = HRFEstimateAndRefitTool()._run(
        img=str(img_path),
        events=str(events_path),
        output_dir=str(tmp_path / "out"),
        t_r=t_r,
        roi_mask=str(mask_path),
        fir_delays=[0, 1, 2, 3],
    )

    assert result.status == "success"
    outputs = result.data["outputs"]
    assert Path(outputs["estimated_hrf_tsv"]).exists()
    assert Path(outputs["summary_json"]).exists()
    assert Path(outputs["predictions_tsv"]).exists()

    summary = json.loads(Path(outputs["summary_json"]).read_text(encoding="utf-8"))
    assert summary["conditions"] == ["stim"]
    assert summary["custom_refit_r2"] >= summary["canonical_refit_r2"]

    hrf_df = pd.read_csv(outputs["estimated_hrf_tsv"], sep="\t")
    assert set(hrf_df.columns) >= {
        "condition",
        "delay_index",
        "delay_s",
        "beta",
        "normalized_hrf",
    }
