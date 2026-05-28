from __future__ import annotations

import numpy as np

from brain_researcher.services.tools.params import (
    LesionDetectionParameters,
    run_lesion_detection,
)


def test_run_lesion_detection(tmp_path):
    flair = np.random.randn(32, 32, 32)
    flair_file = tmp_path / "flair.npy"
    np.save(flair_file, flair)

    params = LesionDetectionParameters(
        flair_image=str(flair_file),
        t1_image=None,
        dwi_image=None,
        output_dir=str(tmp_path / "lesions"),
        lesion_type="wmh",
        min_lesion_size=5,
        threshold_method="adaptive",
        random_state=0,
        save_masks=True,
        save_report=True,
    )

    result = run_lesion_detection(params)
    assert "lesion_volume" in result["summary"]
