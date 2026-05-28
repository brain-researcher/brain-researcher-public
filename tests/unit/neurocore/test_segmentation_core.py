from __future__ import annotations

import numpy as np

from brain_researcher.services.tools.params import (
    SegmentationParameters,
    run_segmentation,
)


def test_run_segmentation(tmp_path):
    image = np.random.randn(20, 20, 20)
    image_file = tmp_path / "image.npy"
    np.save(image_file, image)

    params = SegmentationParameters(
        input_image=str(image_file),
        output_dir=str(tmp_path / "seg"),
        segmentation_type="tissue",
        modality="T1",
        n_classes=3,
        threshold_method="adaptive",
        min_lesion_size=3,
        save_masks=True,
        save_probabilities=True,
        save_volumes=True,
        output_format="nifti",
        random_state=0,
    )

    result = run_segmentation(params)
    assert "n_classes" in result["summary"]
